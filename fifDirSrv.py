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
#       - get disk map from a file or the command line
#       - add text UI using CURSES module
#       - add more error detection and return more error codes
#
#   known issues:
#       - TBD
#
#   history:
#        13-JUL-2023     1.0     Initial release
##

import requests
import sys
import os
from stat import *
import socket
from simple_http_server import route, server, Response, ModelDict, logger

logger.set_level("ERROR")

srv = os.path.splitext(os.path.basename(sys.argv[0]))[0]

FIF_PORT = 0xFD
SRV_PORT = 3000
SRV_PATH = srv

hosturl = 'http://imsai8080'
_srvurl = f'http://{socket.gethostname()}:{SRV_PORT}/{SRV_PATH}'

disks = { 'A': 'cpm22b01.unpacked', 'B': 'comms.unpacked', 'C': 'dazzler.unpacked', 'D': 'ZorkI.unpacked' }
disk_to_unit = { 'A': 1, 'B': 2, 'C': 4, 'D': 8, 'I': 15 }
unit_info = { }

sess = requests.Session()

def main():

    print('DISKS:')
    for d in disks:

        unit_info[disk_to_unit[d.upper()]] = {}

        dstat = os.stat(disks[d])
    
        if S_ISREG(dstat.st_mode):
            unit_info[disk_to_unit[d.upper()]]['type'] = 'IMG'
            unit_info[disk_to_unit[d.upper()]]['file'] = disks[d]
            print(f'DSK:{d.upper()}: = IMAGE: {disks[d]}')
        elif S_ISDIR(dstat.st_mode):
            print(f'DSK:{d.upper()}: = PATH : {disks[d]}')
            (boot, data) = build_directory(disks[d])
            dir = parseDir(data)
            # printDir(dir)
            unit_info[disk_to_unit[d.upper()]]['type'] = 'DIR'
            unit_info[disk_to_unit[d.upper()]]['root'] = disks[d]
            unit_info[disk_to_unit[d.upper()]]['boot'] = boot
            unit_info[disk_to_unit[d.upper()]]['dirdata'] = data
            unit_info[disk_to_unit[d.upper()]]['dir'] = dir
            unit_info[disk_to_unit[d.upper()]]['buffer'] = [ ]
        else:
            sys.exit(f"FAILED drive {d}: file {disks[d]} - not recognised")

    # print(unit_info)

    try:
        sys_get = requests.patch(f'{hosturl}/io?p=-{FIF_PORT:02X}', data=_srvurl)
        if sys_get.status_code == 200:
            print(f'Listening and registered on Port {FIF_PORT:02X}h to {sys_get.text}')
    except:
        sys.exit(f"FAILED to find {hosturl} - not connected")

    ## DONT RUN THIS IN A VM OR THE HOST CAN'T BE SEEN
    server.start(host="", port=SRV_PORT)

@route(f'/{SRV_PATH}', method="PUT")
def io_out(p, m=ModelDict()):
    port = int(p, 16)
    #BODY is a little hard to get as it ends up as the first KEY in the DICT m
    data = int(next(iter(m)), 16) 
    # print(f'{port:02X} {data:02X}')
    if port == FIF_PORT:
        t = fif_out(data)

        if t == 1:
            return Response(status_code=201)
    return #normal 200 response 

fdstate = 0
descno = 0
fdaddr = [0] * 16

def fif_out(data):

    global descno
    global fdstate
    global fdaddr

    res = 0

    if fdstate == 0:
        op = data & 0xF0
        if op == 0x00:
            descno = data & 0x0F
            res = disk_io(fdaddr[descno])
        elif op == 0x10:
            descno = data & 0x0F
            fdstate += 1
    elif fdstate == 1:
        fdaddr[descno] = data
        fdstate += 1
    elif fdstate == 2:
        fdaddr[descno] += data << 8
        # print(f'Descriptor={descno} addr={fdaddr[descno]:04X}')
        fdstate = 0
    else:
        print(f'Internal error fdstate={fdstate}')
        fdstate = 0
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


def build_directory(root):

    boot = False
    dirdata = [ DEL_BYTE ] * (EXT_SZ * dpb['dirsize'])

    d = os.scandir(root)

    dirI = 0
    # blkN = 2 # CALCULATE BASED ON dirsize
    blkN = (EXT_SZ * dpb['dirsize']) // dpb['blksize']

    # print(len(dirdata))
    
    for i in d:
        s = i.stat().st_size
        if S_ISREG(i.stat().st_mode):

            if i.name == "$BOOT":
                outcome = '$$$BOOT RECORD$$$'
                boot = True
            else:
                outcome = '<IGNORED>'

            print(f"{i.name:12} {s//1024:5}K {s//128:5} {outcome}")
            
        if S_ISDIR(i.stat().st_mode):

            if i.name.isnumeric() and int(i.name) in range(16):
                outcome = f'USER: {i.name}'
            else:
                outcome = '<IGNORED>'

            print(f"{i.name:12} <DIR> {outcome}")

            subd = os.path.join(root, i.name)
            sd = os.scandir(subd)

            for f in sd:
                size = f.stat().st_size
                if S_ISREG(f.stat().st_mode):

                    n = f.name.split('.')
                    cpmfile = f'{n[0]:8}'
                    cpmext = f'{n[1]:3}'

                    # print(f"{cpmfile}.{cpmext} {size:6} {size//1024:5} {size//128:5}")

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
                        
                        # print(nextext)

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

        # print(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {blkcount}')
        
        if user != DEL_BYTE:
            # print(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {blkcount}')

            if dir[user].get(filename) == None:
                dir[user][filename] = { 'blocks': 0, "recs": 0, "data": [] }
            
            dir[user][filename]['blocks'] += blkcount
            dir[user][filename]['recs'] += rc
            dir[user][filename]['data'].extend(blocks)
    return dir


# PRINT DIRECTORY
def printDir(dir):
    for u in range(16):
        if dir[u] != {}:
            print()
            print(f'User {u}:')
            print()
            print('Name         Bytes   Recs')
            print('------------ ------ ------')
            for f in dir[u]:
                print(f"{f} {((dir[u][f]['blocks'] * dpb['blksize'])//1024):5}K {dir[u][f]['recs']:5}")


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


def writeFileSector(unit, trk, sec, data):

    fd = open(unit_info[unit]['file'], 'r+b')

    pos = (trk * SPT8 + sec - 1) * SEC_SZ

    fd.seek(pos)
    fd.write(data)
    fd.close()

def lsec(e):
    return e['lsec']

# DO ALL THE DIRECTORY MAGIC
# - check for change to USER 0xE5 means DELETE file
# - check for change to FILENAME.EXT means RENAME file
# - check for change to xl,xh,bc,rc means ?????
# - check for changes to blockPointers (16) means WRITE new block from buffer
def check_dir_sec(unit, trk, sec, data):

    root = unit_info[unit]['root']
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

    # print (ext)
    if ext > -1:
        lext = ext + sec * (SEC_SZ // EXT_SZ)
    else:
        print("NO DIRECTORY EXTENT HAS CHANGED")
        return

    # print(dext)
    extpos = lext * EXT_SZ
    # print('BEFORE:', dirdata[extpos: extpos + EXT_SZ])
    # print('AFTER :', bytearray(data[ext * EXT_SZ:(ext + 1) * EXT_SZ]))

    orig = {
        'user': dirdata[extpos],
        'file': bytes(dirdata[extpos + 1 : extpos + 12]),
        'xl': dirdata[extpos + 12],
        'xh': dirdata[extpos + 14],
        'xNum': (dirdata[extpos + 14] & 0x2F) << 5 | (dirdata[extpos + 12] & 0x1F),
        'rc': dirdata[extpos + 15],
        'blocks': bytes(dirdata[extpos + 16 :extpos + 32])
    }

    new = {
        'user': data[ext * EXT_SZ],
        'file': data[ext * EXT_SZ + 1 : ext * EXT_SZ + 12],
        'xl': data[ext * EXT_SZ + 12],
        'xh': data[ext * EXT_SZ + 14],
        'xNum': ((dirdata[extpos + 14] & 0x2F) << 5) | (dirdata[extpos + 12] & 0x1F),
        'rc': data[ext * EXT_SZ + 15],
        'blocks': data[ext * EXT_SZ + 16 :ext * EXT_SZ + 32]
    }

    # print(orig)
    # print(new)

    # DELETE
    if orig['user'] < 16 and new['user'] == DEL_BYTE:
        if new['xNum'] == 0:
            print(f"DELETE FILE: {filename(orig['file'])}")
            try:
                os.remove(os.path.join(root, f"{orig['user']}", filename(orig['file'])))
            except:
                pass
        else: # new['xNum'] > 0:
            print(f"MARK DELETED EXTENT: {new['xNum']} for {orig['file']}")
    # CREATE
    elif orig['user'] == DEL_BYTE and new['user'] < 16:
        if new['xNum'] == 0:
            print(f"CREATE FILE: {filename(new['file'])}")
            try:
                fd = file_start(os.path.join(root, f"{new['user']}", filename(new['file'])), "xb")
                # file_end()
            except:
                pass
        else: # new['xNum'] > 0:
            print(f"ADD EXTENT: {new['xNum']} {new['file']}")
    # RENAME
    elif new['file'] != orig['file']:
        if new['xNum'] == 0:
            print(f"RENAME FILE: {filename(orig['file'])} to {filename(new['file'])}")
            try:
                os.rename(os.path.join(root, f"{orig['user']}", filename(orig['file'])),
                          os.path.join(root, f"{new['user']}", filename(new['file'])))
            except:
                pass
        else: # new['xNum'] > 0:
            print(f"RENAME EXTENT: {new['xNum']} {orig['file']} to {new['file']}")
    # ADD SECTORS/BLOCKS TO AN EXTENT
    else:
        print(f"UPDATE EXTENT: {new['file']}")

        # print(unit_info[unit]['buffer'])
        unit_info[unit]['buffer'].sort(key=lsec)

        fd = file_start(os.path.join(root, f"{new['user']}", filename(new['file'])), 'r+b')
        for n in new['blocks']:
            found = False 
            if n != orig['blocks'][new['blocks'].index(n)]:
                for b in unit_info[unit]['buffer']:
                    if b['blk'] == n:
                        found = True
                        if new['xNum'] == 0: # if first extent, use first block as base
                            pos = (b['lsec'] - (new['blocks'][0] * 8)) * SEC_SZ
                        else: # if NOT first extent, use first block in first extent as base
                            pos = (b['lsec'] - (dir[new['user']][filename(new['file'], False)]['data'][0] * 8)) * SEC_SZ

                        # print(b['lsec'], new['xNum'], pos)
                        fd.seek(pos)
                        fd.write(b['data'])
                        b['blk'] = -1 # mark buffer entry as used
            # DETECT IF A NEW BLOCK HAS NO DATA IN THE BUFFER
            if not found and n != 0:
                print(f"BAD BLOCK REF {n} - NO DATA AVAILABLE IN BUFFER")
        
        file_end()

        # TEST TO SEE IF ANY DATA REMAINS UNUSED IN THE BUFFER
        for b in unit_info[unit]['buffer']:
            if b['blk'] >= 0:
                print(f"UNUSED DATA IN WRITE BUFFER blk={b['blk']} lsec={b['lsec']}")
        
        #EMPTY THE BUFFER
        unit_info[unit]['buffer'].clear()

    # UPDATE IN MEMORY DIRECTORY STRUCTURES 
    # for i in range(EXT_SZ):
    #     dirdata[extpos + i ] = data[ext * EXT_SZ + i]
    dirdata[extpos: extpos + EXT_SZ] = data[ext * EXT_SZ: (ext + 1) * EXT_SZ]
    #unit_info[unit]['dirdata'] = dirdata # not needed as lists are by reference not copied
    unit_info[unit]['dir'] = parseDir(dirdata)


def writeDirSector(unit, trk, sec, data):

    root = unit_info[unit]['root']
    # dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # BOOT TRACKS
    if trk < dpb['offset']:

        pos = (trk * dpb['sectors'] + sec) * SEC_SZ #??? TODO: does this need top go through trans[] ???
        print(f"WRITE BOOT: {trk}:{sec} pos= {pos}")

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
        # print(f"WRITE DIR : {trk}:{sec}")
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
                    print(f"WRITE TO FILE BLOCK: {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")

                    fd = file_start(os.path.join(root, f'{u}', fn), 'r+b')
                    fd.seek(pos)
                    fd.write(data)
                    # fd.close()

                    break
            else:
                continue
            break
        else:
            # print(f"WRITE TO EMPTY BLOCK: {trk}:{sec} block:{blk}")
            unit_info[unit]['buffer'].append({ 'lsec': sec, 'blk': blk, 'data': data })
    return


def read_sector(unit, trk, sec):

    if unit_info[unit]['type'] == 'IMG':
        return readFileSector(unit, trk, sec)
    elif unit_info[unit]['type'] == 'DIR':
        return readDirSector(unit, trk, sec)


def readFileSector(unit, trk, sec):

    # print(f"IMAGE READ: {unit}:{trk}:{sec} {unit_info[unit]['file']}")

    fd = open(unit_info[unit]['file'], 'rb')

    pos = (trk * SPT8 + sec - 1) * SEC_SZ
    fd.seek(pos)
    data = fd.read(SEC_SZ)
    
    fd.close()
    return data


def readDirSector(unit, trk, sec):

    empty_sec = [ DEL_BYTE ] * SEC_SZ
    root = unit_info[unit]['root']
    boot = unit_info[unit]['boot']
    dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # BOOT TRACKS
    if trk < dpb['offset']:
        # print(f"READ BOOT: {trk}:{sec}")
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
        # print(f"READ DIR : {trk}:{sec}")

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
                    # print(f"READ FILE BLOCK: {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")

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

    # print(f'{cmd_str[cmd]} {unit}:{track}:{sector} <-> {dma_addr:04X}')

    if unit in list(unit_info):

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

        dma_put = sess.put(f'{hosturl}/dma?m={(addr + 1):04X}', data=disk_res)
        # print(dma_put.status_code, dma_put.text)

        return 1

    return 0

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # do nothing here
        print("KEY INT")
        sess.close()
        sys_get = requests.delete(f'{hosturl}/io?p={FIF_PORT:02X}')
        if sys_get.status_code == 200:
            print(f'De-registered on {sys_get.text}')
        pass