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
#       - use requests.Sessions
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
sel_units = [ ]
unit_info = { }

def main():

    print('DISKS:')
    for d in disks:
        sel_units.append(disk_to_unit[d])

        unit_info[disk_to_unit[d.upper()]] = {}

        dstat = os.stat(disks[d])
    
        if S_ISREG(dstat.st_mode):
            unit_info[disk_to_unit[d.upper()]]['type'] = 'IMG'
            unit_info[disk_to_unit[d.upper()]]['file'] = disks[d]
            print(f'\tDSK:{d.upper()}: = IMAGE: {disks[d]}')
        elif S_ISDIR(dstat.st_mode):
            print(f'\tDSK:{d.upper()}: = PATH : {disks[d]}')
            (boot, data) = build_directory(disks[d])
            dir = parseDir(data)
            printDir(dir)
            unit_info[disk_to_unit[d.upper()]]['type'] = 'DIR'
            unit_info[disk_to_unit[d.upper()]]['root'] = disks[d]
            unit_info[disk_to_unit[d.upper()]]['boot'] = boot
            unit_info[disk_to_unit[d.upper()]]['dirdata'] = data
            unit_info[disk_to_unit[d.upper()]]['dir'] = dir
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

            print(f"{i.name:12} {s:6} {s//1024:5} {s//128:5} {outcome}")
            
        if S_ISDIR(i.stat().st_mode):

            if f"{int(i.name)}" == i.name and int(i.name) in range(16):
                outcome = f'USER: {i.name}'
            else:
                outcome = '<IGNORED>'

            # print(f"{i.name:12} <DIR> {outcome}")

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

                    # XL - extent number
                    xl = 0

                    # BC - always ZERO for CPM22 - ignore

                    # XH - always ZERO for CPM22 (?) - ignore

                    # RC - number of recs/secs in the extent
                    rc = size // SEC_SZ

                    while rc >= 0:
                        nextext = list(ext)
                        nextext[12] = xl
                        # nextext[13] = 0
                        # nextext[14] = 0
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

                        xl += 1
                        rc -= 128    

    return ( boot, bytearray(dirdata) )


# PARSE DIRECTORY EXTENTS INTO dir ARRAY OF DICTIONARIES ie. USER:FILE.EXT
def parseDir(dirData):

    # dir = [ {} ] * 16
    dir = [ {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {} ]

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


def writeDirSector(unit, trk, sec, data):

    root = unit_info[unit]['root']
    dirdata = unit_info[unit]['dirdata']
    dir = unit_info[unit]['dir']

    # BOOT TRACKS
    if trk < dpb['offset']:
        print(f"WRITE BOOT: {trk}:{sec}")
        return

    sec = trans.index(sec)
    sec = (trk - dpb['offset']) * dpb['sectors'] + sec
    blk = sec // 8

    # DIRECTORY
    if sec < ((dpb['dirsize'] * EXT_SZ) // SEC_SZ):
        print(f"WRITE DIR : {trk}:{sec}")

        # DO ALL THE DIRECTORY MAGIC
        # - check for change to USER 0xE5 means DELETE file
        # - check for change to FILENAME.EXT means RENAME file
        # - check for change to xl,xh,bc,rc means ?????
        # - check for chnages to blockPointers (16) means ?????

    else:
        for u in range(16):
            for f in dir[u]:
                if blk in dir[u][f]['data']:
                    fn = f.split('.',1)
                    fn[0] = fn[0].strip()
                    fn[1] = fn[1].strip()
                    fn = '.'.join(fn)

                    pos = (sec - (dir[u][f]['data'][0] * 8)) * SEC_SZ
                    print(f"WRITE FILE: {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")

                    # fd = open(os.path.join(root, f'{u}', fn), 'rb')

                    # fd.seek(pos)
                    # fd.close()

                    break
            else:
                continue
            break
        else:
            print(f"WRITE EMPTY: {trk}:{sec} block:{blk}")
    return


def read_sector(unit, trk, sec):

    if unit_info[unit]['type'] == 'IMG':
        return readFileSector(unit, trk, sec)
    elif unit_info[unit]['type'] == 'DIR':
        return readDirSector(unit, trk, sec)


def readFileSector(unit, trk, sec):

    print(f"IMAGE READ: {unit}:{trk}:{sec} {unit_info[unit]['file']}")

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
        print(f"BOOT: {trk}:{sec}")
        if boot:
            fd = open(os.path.join(root, '$BOOT'), 'rb')

            pos = (trk * SPT8 + sec - 1) * SEC_SZ
            fd.seek(pos)
            data = fd.read(SEC_SZ)
            fd.close()
        else:
            data = bytearray(empty_sec)

        return data

    sec = trans.index(sec)
    sec = (trk - dpb['offset']) * dpb['sectors'] + sec
    blk = sec // 8

    # DIRECTORY
    if sec < ((dpb['dirsize'] * EXT_SZ) // SEC_SZ):
        print(f"DIR : {trk}:{sec}")

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
                    print(f"READ : {trk}:{sec} block:{blk} in file: {fn} pos: {pos}")

                    fd = open(os.path.join(root, f'{u}', fn), 'rb')

                    fd.seek(pos)
                    data = fd.read(SEC_SZ)
                    fd.close()

                    break
            else:
                continue
            break
        else:
            data = bytearray(empty_sec)

    return data


def disk_io(addr):
    dma_get = requests.get(f'{hosturl}/dma?m={addr:04X}&n=7')
    mem = dma_get.content

    unit = mem[0] & 0x0F
    cmd = mem[0] >> 4
    res = mem[1]
    fmt = mem[2]
    track = mem[3]
    sector = mem[4]
    dma_addr = (mem[6] << 8) + mem[5]

    # print(f'{cmd_str[cmd]} {unit}:{track}:{sector} <-> {dma_addr:04X}')

    if unit in sel_units:

        if cmd == 1:

            sec_get = requests.get(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}')
            blksec = sec_get.content

            write_sector(unit, track, sector, blksec)

            disk_res = bytes.fromhex('01')
        elif cmd == 2:

            blksec = read_sector(unit, track, sector)

            sec_put = requests.put(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}', data=blksec)
            
            disk_res = bytes.fromhex('01')
        else: 
            disk_res = bytes.fromhex('A1')

        dma_put = requests.put(f'{hosturl}/dma?m={(addr + 1):04X}', data=disk_res)
        # print(dma_put.status_code, dma_put.text)

        return 1

    return 0

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # do nothing here
        print("KEY INT")
        sys_get = requests.delete(f'{hosturl}/io?p={FIF_PORT:02X}')
        if sys_get.status_code == 200:
            print(f'De-registered on {sys_get.text}')
        pass