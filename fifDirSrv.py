#!/usr/bin/env python3
##
#   fifsrv.py
#
#   Copyright (C) David McNaughton 2023-present
#
#   a utility to remotely mount disk image files (*.dsk) to the IMSAI8080esp 
#   using the RESTful interface provided for IO and DMA
#
#   dependencies:
#       python3
#       requests (module)           - to install, use: pip install requests
#       simple_http_server (module) - to install, use: pip install simple_http_server
#
#   TODO:
#       - normalize the use of trk:sec vs. linear sector
#       - add more error detection and return more error codes
#
#   known issues:
#       - TBD
#
#   history:
#        13-JUL-2023     1.0     Initial release
##

import requests
import curses
import curses.textpad
import sys
import os
from stat import *
import socket
from simple_http_server import route, server, Response, ModelDict, logger as httpdlog
from threading import Thread
from logging import debug, info, error, warning
import logging
import json

httpdlog.set_level("ERROR")

srv = os.path.splitext(os.path.basename(sys.argv[0]))[0]

FIF_PORT = 0xFD
SRV_PORT = 3000
SRV_PATH = srv

hosturl = 'http://imsai8080'
_srvurl = f'http://{socket.gethostname()}:{SRV_PORT}/{SRV_PATH}'

diskmap_file = 'diskmap.json'

disks = { }
disk_to_unit = { 'A': 1, 'B': 2, 'C': 4, 'D': 8 }
unit_info = { }

sess = requests.Session()

TMAX = 77
win = None


def main(sc):

    global win
    curses.curs_set(0)
    curses.textpad.rectangle(sc, 0, 0, curses.LINES - 1, TMAX + 1)
    title = f"[ Remote IMSAI FIF - {srv} ]"
    sc.addstr(0, (TMAX + 2 - len(title))//2, title)
    sc.refresh()
    win = curses.newwin(curses.LINES - 2 , TMAX , 1, 1)

    load_diskmap()

    process_diskmap()

    connect_to_host()

    ## DONT RUN THIS IN A VM OR THE HOST CAN'T BE SEEN
    th = Thread(target=server.start, args=("", SRV_PORT), daemon=True)
    th.start()

    drive = None

    while True:
        key = win.getkey()
        win.addstr(curses.LINES - 3, 1, f"KEY: <{key}>")
        win.clrtoeol()
        win.refresh()

        # info(f"KEY: {key} len={len(key)} ord={ord(key)}")
        if key == chr(24): # ^X
            connect_to_host()
        elif key == chr(16): # ^P
            info(f"PERSIST: {disks}")
            with open(diskmap_file, "w") as fp:
                json.dump(disks, fp)  # encode disks dict into JSON 
            win.addstr(curses.LINES - 3, 12, f"SAVED TO {diskmap_file}")
        elif key == chr(18): # ^R
            info(f"RELOAD: {disks}")
            load_diskmap()   
            process_diskmap()
        elif key == chr(21): # ^U
            if drive in list(disks):
                info(f"UNLOAD: DSK:{drive}: {disks[drive]}")        
                disks.pop(drive)          
                process_diskmap()
        elif key == chr(12): # ^L
            if drive in list(disk_to_unit):
                info(f"LOAD: DSK:{drive}:")
                # PROMPT USER FOR image/directory NAME USING TEXTBOX
                win.addstr(curses.LINES - 3, 0, f"LOAD: DSK:{drive}: = ")
                win.clrtoeol()
                win.refresh()
                curses.curs_set(1)
                txtwin = curses.newwin(1 , TMAX - 32 , curses.LINES - 2, 16)
                tb = curses.textpad.Textbox(txtwin, insert_mode=True)
                txt = tb.edit()
                curses.curs_set(0)
                txt = txt.strip()
                disks[drive] = txt
                process_diskmap()
        elif key in list(disk_to_unit):
            drive = key
            win.addstr(curses.LINES - 3, 10, f"DRIVE: DSK:{drive}:")
            continue

        drive = None
        

@route(f'/{SRV_PATH}', method="PUT")
def io_out(p, m=ModelDict()):
    port = int(p, 16)
    #BODY is a little hard to get as it ends up as the first KEY in the DICT m
    data = int(next(iter(m)), 16) 
    # info(f'{port:02X} {data:02X}')
    if port == FIF_PORT:
        t = fif_out(data)

        if t == 1:
            return Response(status_code=201)
    return #normal 200 response 

def connect_to_host():

    sys_get = requests.delete(f'{hosturl}/io?p={FIF_PORT:02X}')
    if sys_get.status_code == 200:
        info(f'De-registered on {sys_get.text}')
        win.addnstr(0, 0, f'De-registered on {sys_get.text}', TMAX)

    try:
        sys_get = requests.patch(f'{hosturl}/io?p=-{FIF_PORT:02X}', data=_srvurl)
        if sys_get.status_code == 200:
            info(f'Listening and registered on Port {FIF_PORT:02X}h to {sys_get.text}')
            win.addnstr(0, 0, f'Listening and registered on Port {FIF_PORT:02X}h to {sys_get.text}', TMAX)
            win.addnstr(1, 0, f'***You must COLD BOOT the IMSAI to recognize the remote FIF***', TMAX)
            win.refresh()
    except:
        sys.exit(f"FAILED to find {hosturl} - not connected")

fdstate = 0
descno = 0
fdaddr = [0] * 16

def fif_out(data):

    global descno
    global fdstate
    global fdaddr

    res = 0

    win.addstr(1, 0, 'RECV', curses.A_REVERSE)
    win.refresh()

    if fdstate == 0:
        op = data & 0xF0
        if op == 0x00:
            descno = data & 0x0F
            res = disk_io(fdaddr[descno])
        elif op == 0x10:
            descno = data & 0x0F
            fdstate += 1

        win.addstr(2, 0, f"FIF DESC:{descno:X}")
        win.clrtoeol()
        for i in range(16):
            win.addstr((i//8) + 2, (i%8) * 7 + 12, f"{i:X}:{fdaddr[i]:04X}")

    elif fdstate == 1:
        fdaddr[descno] = data
        fdstate += 1
    elif fdstate == 2:
        fdaddr[descno] += data << 8
        # info(f'Descriptor={descno} addr={fdaddr[descno]:04X}')
        fdstate = 0
    else:
        error(f'Internal error fdstate={fdstate}')
        fdstate = 0

    win.move(1, 0)
    win.clrtoeol()
    win.refresh()
    return res

cmd_str = [ "", "WRITE", "READ", "FORMAT", "VERIFY" ]

DEL_BYTE = 0xE5
EXT_SZ = 32
SEC_SZ = 128
SPT8 = 26

trans = [ 1,7,13,19,25,5,11,17,23,3,9,15,21,2,8,14,20,26,6,12,18,24,4,10,16,22 ]

dpb = { 
    'sectors': 26,
    'blksize': 1024,
    'dirsize': 64,
    'disksize': 243,
    'offset': 2,
    'tracks': 77
}

def load_diskmap():
    global disks

    try:
        with open(diskmap_file, "r") as fp:
            disks = json.load(fp) # Load the disks dict from the file
        info(f"LOADED: {disks}")
        win.addstr(2, 0, f"Loaded: {diskmap_file}")
    except json.decoder.JSONDecodeError as e:
        error(f'JSON error in {diskmap_file}: {e}')
        sys.exit(f'JSON error in {diskmap_file}: {e}')
    except FileNotFoundError:
        warning(f'Diskmap file {diskmap_file} not found')
        win.addstr(2, 0, f"*** Warning: no {diskmap_file} file found ***")


def process_diskmap():

    win.move(5,0)
    win.clrtobot()

    info('DISKS:')
    for i, d in enumerate(disk_to_unit):

        unit_info[disk_to_unit[d]] = {}

        if d in list(disks):
            dstat = os.stat(disks[d])

            if S_ISREG(dstat.st_mode):
                unit_info[disk_to_unit[d]]['type'] = 'IMG'
                unit_info[disk_to_unit[d]]['file'] = disks[d]
                unit_info[disk_to_unit[d]]['last'] = 0
                info(f'DSK:{d}: = IMAGE: {disks[d]}')
            elif S_ISDIR(dstat.st_mode):
                info(f'DSK:{d}: = PATH : {disks[d]}')
                (boot, data) = build_directory(disks[d])
                dir = parseDir(data)
                # infoDir(dir)
                unit_info[disk_to_unit[d]]['type'] = 'DIR'
                unit_info[disk_to_unit[d]]['file'] = disks[d]
                unit_info[disk_to_unit[d]]['last'] = 0
                unit_info[disk_to_unit[d]]['boot'] = boot
                unit_info[disk_to_unit[d]]['dirdata'] = data
                unit_info[disk_to_unit[d]]['dir'] = dir
                unit_info[disk_to_unit[d]]['buffer'] = [ ]
            else:
                sys.exit(f"FAILED drive {d}: file {disks[d]} - not recognized")
        else:
            unit_info[disk_to_unit[d]]['type'] = 'LOCAL'
            unit_info[disk_to_unit[d]]['file'] = ''
            unit_info[disk_to_unit[d]]['last'] = 0

        win.addstr(4*i + 5, 0, f"DSK:{d}: =  {unit_info[disk_to_unit[d]]['type']}:{unit_info[disk_to_unit[d]]['file']}")
        win.addstr(4*i + 5, 35, f"Login/Warm boot to reload disk")
        win.hline(4*i + 6, 0, '.', 77)

    win.refresh()
    # debug(unit_info)


def shorten(name, list):

    tx = str.maketrans("<>.,;:=?*[]%|()/\\_", "                  ")

    f, e = os.path.splitext(name)

    file = f.upper().translate(tx).replace(' ', '')
    ext = '.' + e[1:].upper().translate(tx).replace(' ', '')

    tail = 0

    if len(file) > 8:
        tail += 1
        file = f"{file[0:6]}~{tail:X}"
    ext = ext[0:4]

    shortname = file + ext

    while tail and (shortname in list) and tail < 15:
        tail += 1
        shortname = f"{file[0:7]}{tail:X}{ext}"
    
    if tail == 16:
        error(f'TOO MANY FILES WITH THE SAME SHORT NAME: {shortname}')

    if shortname != name:
        list[list.index(name)] = shortname

    return shortname


def build_directory(root):

    boot = False
    dirdata = [ DEL_BYTE ] * (EXT_SZ * dpb['dirsize'])

    d = os.scandir(root)

    dirI = 0
    # blkN = 2 # CALCULATE BASED ON dirsize
    blkN = (EXT_SZ * dpb['dirsize']) // dpb['blksize']

    # debug(len(dirdata))
    
    for i in d:
        s = i.stat().st_size
        if S_ISREG(i.stat().st_mode):

            if i.name == "$BOOT":
                outcome = '$$$BOOT RECORD$$$'
                boot = True
            else:
                outcome = '<IGNORED>'

            info(f"{i.name:12} {s//1024:5}K {s//128:5} {outcome}")
            
        if S_ISDIR(i.stat().st_mode):

            if i.name.isnumeric() and int(i.name) in range(16):
                outcome = f'USER: {i.name}'
            else:
                outcome = '<IGNORED>'

            info(f"{i.name:12} <DIR> {outcome}")

            subd = os.path.join(root, i.name)
            sd = os.scandir(subd)
            files = list(sd)
            names = [ f.name for f in files ]

            for f in files:

                size = f.stat().st_size
                mode = f.stat().st_mode
                name = shorten(f.name, names)

                if name != f.name:
                    try:
                        os.rename(os.path.join(root, i.name, f.name), os.path.join(root, i.name, name))
                        warning(f'RENAMED FILE: {f.name} to {name}')
                    except:
                        error(f"FAILED TO RENAME {f.name} to {name}")

                if S_ISREG(mode):

                    n = name.split('.')
                    cpmfile = f'{n[0]:8}'
                    cpmext = f'{n[1]:3}'

                    # info(f"{cpmfile}.{cpmext} {size:6} {size//1024:5} {size//128:5}")

                    ext = [0] * 32

                    ext[0] = int(i.name)

                    for m in range(8):
                        ext[m + 1] = ord(cpmfile[m])

                    for n in range(3):
                        ext[n + 9] = ord(cpmext[n])

                    # XL - extent number bits 0-4
                    # XH - extent number bits 5-10
                    xNum = 0

                    # BC - always ZERO for CPM22 - ignore

                    # RC - number of recs/secs in the extent
                    rc = size // SEC_SZ

                    while rc >= 0:
                        nextext = list(ext)
                        nextext[12] = xNum & 0x1F
                        # nextext[13] = 0
                        nextext[14] = xNum >> 5
                        nextext[15] = rc if rc <= 128 else 128

                        ### ADD BLOCK POINTERS HERE
                        bc = (nextext[15] // 8) + (1 if (nextext[15] % 8) else 0)

                        for b in range(bc):
                            nextext[16 + b] = blkN
                            blkN += 1
                        
                        # info(nextext)

                        for d in range(EXT_SZ):
                            dirdata[(dirI + d)] = nextext[d]
                        
                        dirI += EXT_SZ

                        xNum += 1
                        rc -= 128    

    return ( boot, bytearray(dirdata) )


def filename(buf, strip = True):
    """Format a filename as FILENAME.EXT
    
    #### Parameters
    - buf : the source array for characters (8+3)
    - strip : strip trailing spaces from the filename and extension 
    """
    filename = ''
    for f in range(8):
        filename += chr(buf[ f ])

    if strip:
        filename = filename.rstrip()

    filename += '.'
    for e in range(3):
        filename += chr(buf[ 8 + e ])

    if strip:
        filename = filename.rstrip()
    
    return filename


# PARSE DIRECTORY EXTENTS INTO dir ARRAY OF DICTIONARIES ie. USER:FILE.EXT
def parseDir(dirData):

    dir = [ {} for _ in range(16) ]

    for d in range(dpb['dirsize']):

        dirExt = dirData[ d * EXT_SZ : (d + 1) * EXT_SZ ]

        user = dirExt[ 0 ]
        filename = ''
        for f in range(8):
            filename += chr(dirExt[ 1 + f ])

        filename += '.'
        for e in range(3):
            filename += chr(dirExt[ 9 + e ])

        xl = dirExt[ 12 ]
        bc = dirExt[ 13 ]
        xh = dirExt[ 14 ]
        rc = dirExt[ 15 ]
        blocks = dirExt[ 16 : 32 ]

        blkcount = 0

        for a in range(16):
            if dirExt[ 16 + a ]:
                blkcount += 1

        # info(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {blkcount}')
        
        if user != DEL_BYTE:
            # info(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {blkcount}')

            if dir[user].get(filename) == None:
                dir[user][filename] = { 'blocks': 0, "recs": 0, "data": [] }
            
            dir[user][filename]['blocks'] += blkcount
            dir[user][filename]['recs'] += rc
            dir[user][filename]['data'].extend(blocks)
    return dir


# PRINT DIRECTORY
def infoDir(dir):
    for u in range(16):
        if dir[u] != {}:
            info()
            info(f'User {u}:')
            info()
            info('Name         Bytes   Recs')
            info('------------ ------ ------')
            for f in dir[u]:
                info(f"{f} {((dir[u][f]['blocks'] * dpb['blksize'])//1024):5}K {dir[u][f]['recs']:5}")


current_file = { 'file': '', 'mode': '', 'fd': None }

def file_start(file, mode):

    if file == current_file['file'] and mode == current_file['mode']:
        return current_file['fd']
    
    if current_file['fd'] != None:
        current_file['fd'].close()

    current_file['file'] = file
    current_file['mode'] = mode
    current_file['fd'] = open(file, mode)

    return current_file['fd']

def file_end():

    if current_file['fd'] != None:
        current_file['fd'].close()

    current_file['file'] = ''
    current_file['mode'] = ''
    current_file['fd'] = None


def write_sector(unit, trk, sec, data):

    if unit_info[unit]['type'] == 'IMG':
        writeFileSector(unit, trk, sec, data)
    elif unit_info[unit]['type'] == 'DIR':
        writeDirSector(unit, trk, sec, data)

def dispFileSector(unit, trk, sec, mode):

    i = list(unit_info).index(unit)
    win.addstr(4*i + 6, unit_info[unit]['last'], '.')
    win.addstr(4*i + 7, unit_info[unit]['last'], ' ')
    unit_info[unit]['last'] = trk
    win.addstr(4*i + 6, trk, mode)
    dtest = ((trk - dpb['offset']) * SPT8 + trans.index(sec)) < (dpb['dirsize'] * EXT_SZ // SEC_SZ)
    ind = 'B' if trk < dpb['offset'] else 'D' if dtest else 'E' 
    win.addstr(4*i + 7, trk, ind)
    win.refresh()

def writeFileSector(unit, trk, sec, data):

    info(f"IMAGE WRITE: {unit}:{trk}:{sec} {unit_info[unit]['file']}")
    dispFileSector(unit, trk, sec, 'W')

    fd = open(unit_info[unit]['file'], 'r+b')

    pos = (trk * SPT8 + sec - 1) * SEC_SZ

    fd.seek(pos)
    fd.write(data)
    fd.close()

def lsec(e):
    return e['lsec']

def dispDirAction(unit, desc):
    i = list(unit_info).index(unit)
    win.addstr(4*i + 8, 0, f"<DIR> - {desc}")
    win.clrtoeol()
    win.refresh()

# DO ALL THE DIRECTORY MAGIC
# - check for change to USER 0xE5 means DELETE file
# - check for change to FILENAME.EXT means RENAME file
# - check for change to xl,xh,bc,rc means ?????
# - check for changes to blockPointers (16) means WRITE new block from buffer
def check_dir_sec(unit, trk, sec, data):

    root = unit_info[unit]['file']
    dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # diff = [ 0 ] * SEC_SZ

    pos = sec * SEC_SZ
    secdata = dirdata[pos: pos + SEC_SZ]

    ext = -1

    # FIND *FIRST* EXTENT THAT HAS CHANGED - ASSUMES ONLY ONE!
    for i in range(len(data)):
        if data[i] != secdata[i]:
            # diff[i] = ( data[i], secdata[i] )
            ext = i // EXT_SZ
            break

    # info (ext)
    if ext > -1:
        lext = ext + sec * (SEC_SZ // EXT_SZ)
    else:
        warning("NO DIRECTORY EXTENT HAS CHANGED")
        return

    # info(dext)
    extpos = lext * EXT_SZ
    debug('BEFORE:', dirdata[extpos: extpos + EXT_SZ])
    debug('AFTER :', bytearray(data[ext * EXT_SZ:(ext + 1) * EXT_SZ]))

    orig = {
        'user': dirdata[extpos],
        'file': bytes(dirdata[extpos + 1 : extpos + 12]),
        'xl': dirdata[extpos + 12],
        'xh': dirdata[extpos + 14],
        'xNum': ((dirdata[extpos + 14] & 0x2F) << 5) | (dirdata[extpos + 12] & 0x1F),
        'rc': dirdata[extpos + 15],
        'blocks': bytes(dirdata[extpos + 16 :extpos + 32])
    }

    new = {
        'user': data[ext * EXT_SZ],
        'file': data[ext * EXT_SZ + 1 : ext * EXT_SZ + 12],
        'xl': data[ext * EXT_SZ + 12],
        'xh': data[ext * EXT_SZ + 14],
        'xNum': ((data[ext * EXT_SZ + 14] & 0x2F) << 5) | (data[ext * EXT_SZ + 12] & 0x1F),
        'rc': data[ext * EXT_SZ + 15],
        'blocks': data[ext * EXT_SZ + 16 :ext * EXT_SZ + 32]
    }

    # info(orig)
    # info(new)

    # DELETE
    if orig['user'] < 16 and new['user'] == DEL_BYTE:
        if new['xNum'] == 0:
            info(f"DELETE FILE: {filename(orig['file'])}")
            dispDirAction(unit, f"DELETE FILE: {orig['user']}:{filename(orig['file'])}")
            try:
                os.remove(os.path.join(root, f"{orig['user']}", filename(orig['file'])))
            except:
                pass
        else: # new['xNum'] > 0:
            info(f"MARK DELETED EXTENT: {new['xNum']} for {orig['file']}")
            dispDirAction(unit, f"DELETE LOGICAL EXTENT: {new['xNum']} for {orig['user']}:{filename(orig['file'])}")
    # CREATE
    elif orig['user'] == DEL_BYTE and new['user'] < 16:
        if new['xNum'] == 0:
            info(f"CREATE FILE: {filename(new['file'])}")
            dispDirAction(unit, f"CREATE FILE: {new['user']}:{filename(new['file'])}")
            try:
                fd = file_start(os.path.join(root, f"{new['user']}", filename(new['file'])), "xb")
                # file_end()
            except:
                pass
        else: # new['xNum'] > 0:
            info(f"ADD EXTENT: {new['xNum']} {new['file']}")
            dispDirAction(unit, f"ADD LOGICAL EXTENT: {new['xNum']} for {new['user']}:{filename(new['file'])}")
    # RENAME
    elif new['file'] != orig['file']:
        if new['xNum'] == 0:
            info(f"RENAME FILE: {filename(orig['file'])} to {filename(new['file'])}")
            dispDirAction(unit, f"RENAME FILE: {orig['user']}:{filename(orig['file'])} to {new['user']}:{filename(new['file'])}")
            try:
                os.rename(os.path.join(root, f"{orig['user']}", filename(orig['file'])),
                          os.path.join(root, f"{new['user']}", filename(new['file'])))
            except:
                pass
        else: # new['xNum'] > 0:
            info(f"RENAME EXTENT: {new['xNum']} {orig['file']} to {new['file']}")
            dispDirAction(unit, f"RENAME LOGICAL EXTENT: {new['xNum']} from {orig['user']}:{filename(orig['file'])} to {new['user']}:{filename(new['file'])}")
    # ADD SECTORS/BLOCKS TO AN EXTENT
    else:
        info(f"UPDATE EXTENT: {new['file']}")

        # info(unit_info[unit]['buffer'])
        unit_info[unit]['buffer'].sort(key=lsec)

        fd = file_start(os.path.join(root, f"{new['user']}", filename(new['file'])), 'r+b')
        for n in new['blocks']:
            found = False 
            if n != orig['blocks'][new['blocks'].index(n)]:
                for b in unit_info[unit]['buffer']:
                    if b['blk'] == n:
                        dispDirAction(unit, f"WRITE BUFFERED BLOCK TO DISK: {b['blk']} to {new['user']}:{filename(new['file'])}")
                        found = True
                        if new['xNum'] == 0: # if first extent, use first block as base
                            pos = (b['lsec'] - (new['blocks'][0] * 8)) * SEC_SZ
                        else: # if NOT first extent, use first block in first extent as base
                            pos = (b['lsec'] - (dir[new['user']][filename(new['file'], False)]['data'][0] * 8)) * SEC_SZ

                        # info(b['lsec'], new['xNum'], pos)
                        fd.seek(pos)
                        fd.write(b['data'])
                        b['blk'] = -1 # mark buffer entry as used
            # DETECT IF A NEW BLOCK HAS NO DATA IN THE BUFFER
            if not found and n != 0:
                warning(f"BAD BLOCK REF {n} - NO DATA AVAILABLE IN BUFFER")
        
        file_end()

        # TEST TO SEE IF ANY DATA REMAINS UNUSED IN THE BUFFER
        for b in unit_info[unit]['buffer']:
            if b['blk'] >= 0:
                warning(f"UNUSED DATA IN WRITE BUFFER blk={b['blk']} lsec={b['lsec']}")
        
        #EMPTY THE BUFFER
        unit_info[unit]['buffer'].clear()

    # UPDATE IN MEMORY DIRECTORY STRUCTURES 
    # for i in range(EXT_SZ):
    #     dirdata[extpos + i ] = data[ext * EXT_SZ + i]
    dirdata[extpos: extpos + EXT_SZ] = data[ext * EXT_SZ: (ext + 1) * EXT_SZ]
    #unit_info[unit]['dirdata'] = dirdata # not needed as lists are by reference not copied
    unit_info[unit]['dir'] = parseDir(dirdata)


def dispDirSector(unit, trk, sec, mode, type, desc):
    i = list(unit_info).index(unit)
    win.addstr(4*i + 6, unit_info[unit]['last'], '.')
    win.addstr(4*i + 7, unit_info[unit]['last'], ' ')
    unit_info[unit]['last'] = trk
    win.addstr(4*i + 6, trk, mode)
    win.addstr(4*i + 7, trk, type)
    win.addstr(4*i + 8, 0, desc)
    win.clrtoeol()
    win.refresh()


def writeDirSector(unit, trk, sec, data):

    root = unit_info[unit]['file']
    # dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # BOOT TRACKS
    if trk < dpb['offset']:

        pos = (trk * dpb['sectors'] + sec) * SEC_SZ #??? TODO: does this need top go through trans[] ???
        info(f"WRITE BOOT: {trk}:{sec} pos= {pos}")
        dispDirSector(unit, trk, sec, 'W', 'B', '$BOOT')

        fd = file_start(os.path.join(root, '$BOOT'), 'r+b')
        fd.seek(pos)
        fd.write(data)
        # fd.close()

        return

    sec = trans.index(sec)
    sec = (trk - dpb['offset']) * dpb['sectors'] + sec
    blk = sec // 8

    # DIRECTORY
    if sec < ((dpb['dirsize'] * EXT_SZ) // SEC_SZ):
        info(f"WRITE DIR : {trk}:{sec}")
        dispDirSector(unit, trk, sec, 'W', 'D', '<DIR>')
        check_dir_sec(unit, trk, sec, data)
    else:
        for u in range(16):
            for f in dir[u]:
                if blk in dir[u][f]['data']:
                    fn = f.split('.',1)
                    fn[0] = fn[0].strip()
                    fn[1] = fn[1].strip()
                    fn = '.'.join(fn)

                    pos = (sec - (dir[u][f]['data'][0] * 8)) * SEC_SZ
                    info(f"WRITE TO FILE BLOCK: {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")
                    dispDirSector(unit, trk, sec, 'W', f"{u:X}", f"{u}: {fn}")

                    fd = file_start(os.path.join(root, f'{u}', fn), 'r+b')
                    fd.seek(pos)
                    fd.write(data)
                    # fd.close()

                    break
            else:
                continue
            break
        else:
            info(f"WRITE TO EMPTY BLOCK: {trk}:{sec} block:{blk}")
            dispDirSector(unit, trk, sec, 'W', '#', '<BUFFERING>')
            unit_info[unit]['buffer'].append({ 'lsec': sec, 'blk': blk, 'data': data })
    return


def read_sector(unit, trk, sec):

    if unit_info[unit]['type'] == 'IMG':
        return readFileSector(unit, trk, sec)
    elif unit_info[unit]['type'] == 'DIR':
        return readDirSector(unit, trk, sec)


def readFileSector(unit, trk, sec):

    info(f"IMAGE READ: {unit}:{trk}:{sec} {unit_info[unit]['file']}")
    dispFileSector(unit, trk, sec, 'R')

    fd = open(unit_info[unit]['file'], 'rb')

    pos = (trk * SPT8 + sec - 1) * SEC_SZ
    fd.seek(pos)
    data = fd.read(SEC_SZ)
    
    fd.close()
    return data


def readDirSector(unit, trk, sec):

    empty_sec = [ DEL_BYTE ] * SEC_SZ
    root = unit_info[unit]['file']
    boot = unit_info[unit]['boot']
    dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # BOOT TRACKS
    if trk < dpb['offset']:
        info(f"READ BOOT: {trk}:{sec}")
        dispDirSector(unit, trk, sec, 'R', 'B', '$BOOT')

        if boot:
            fd = file_start(os.path.join(root, '$BOOT'), 'rb')

            pos = (trk * SPT8 + sec - 1) * SEC_SZ
            fd.seek(pos)
            data = fd.read(SEC_SZ)
            # fd.close()
        else:
            data = bytearray(empty_sec)

        return data

    sec = trans.index(sec)
    sec = (trk - dpb['offset']) * dpb['sectors'] + sec
    blk = sec // 8

    # DIRECTORY
    if sec < ((dpb['dirsize'] * EXT_SZ) // SEC_SZ):
        info(f"READ DIR : {trk}:{sec}")
        dispDirSector(unit, trk, sec, 'R', 'D', '<DIR>')

        file_end()

        pos = sec * SEC_SZ
        data = dirdata[pos: pos + SEC_SZ]

    # DISK DATA
    else:
        for u in range(16):
            for f in dir[u]:
                if blk in dir[u][f]['data']:
                    fn = f.split('.',1)
                    fn[0] = fn[0].strip()
                    fn[1] = fn[1].strip()
                    fn = '.'.join(fn)

                    pos = (sec - (dir[u][f]['data'][0] * 8)) * SEC_SZ
                    info(f"READ FILE BLOCK: {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")
                    dispDirSector(unit, trk, sec, 'R', f"{u:X}", f"{u}: {fn}")

                    fd = file_start(os.path.join(root, f'{u}', fn), 'rb')

                    fd.seek(pos)
                    data = fd.read(SEC_SZ)
                    # fd.close()

                    break
            else:
                continue
            break
        else:
            data = bytearray(empty_sec)

    return data


def disk_io(addr):
    dma_get = sess.get(f'{hosturl}/dma?m={addr:04X}&n=7')
    mem = dma_get.content

    unit = mem[0] & 0x0F
    cmd = mem[0] >> 4
    res = mem[1]
    fmt = mem[2]
    track = mem[3]
    sector = mem[4]
    dma_addr = (mem[6] << 8) + mem[5]

    # info(f'{cmd_str[cmd]} {unit}:{track}:{sector} <-> {dma_addr:04X}')

    if unit in list(unit_info):

        i = list(unit_info).index(unit)
        win.addstr(4*i + 5, 35, f"{cmd_str[cmd]:6} TRK:{(track+1):3} SEC:{sector:3} DMA: {dma_addr:04X}h")
        win.refresh()
        if unit_info[unit]['type'] == 'LOCAL':

            mode = 'W' if cmd == 1 else 'R' if cmd == 2 else '?'
            dispFileSector(unit, track, sector,  mode)
            
            return 0
        
        if cmd == 1:

            sec_get = sess.get(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}')
            blksec = sec_get.content

            write_sector(unit, track, sector, blksec)

            disk_res = bytes.fromhex('01')
        elif cmd == 2:

            blksec = read_sector(unit, track, sector)

            sec_put = sess.put(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}', data=blksec)
            
            disk_res = bytes.fromhex('01')
        else: 
            disk_res = bytes.fromhex('A1')

        win.addstr(4*i + 5, 69, f"RES: {disk_res[0]:02X}")
        win.refresh()
        dma_put = sess.put(f'{hosturl}/dma?m={(addr + 1):04X}', data=disk_res)
        # info(dma_put.status_code, dma_put.text)

        return 1

    return 0

if __name__ == "__main__":
    try:
        logging.basicConfig(filename="trace.log", filemode="w", level=logging.INFO)
        curses.wrapper(main)
        # main(None)
    except KeyboardInterrupt:
        logging.root.setLevel(logging.INFO)
        debug("KEY INT")
        sess.close()
        sys_get = requests.delete(f'{hosturl}/io?p={FIF_PORT:02X}')
        if sys_get.status_code == 200:
            info(f'De-registered on {sys_get.text}')
        pass