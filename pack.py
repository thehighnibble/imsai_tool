#!/usr/bin/env python3
##
#   pack.py
#
#   Copyright (C) David McNaughton 2023-present
#
#   a utility to pack a CP/M (2.2) disk image file (*.dsk) from directories  
#   on the local file system
#
#   dependencies:
#       python3
#
#   TODO:
#
#   known issues:
#       - TBD
#
#   history:
#        17-JUL-2023     1.0     Initial release
##

# import requests
import sys
import os
from stat import *
from logging import debug, info, error, warning
import logging


DEL_BYTE = 0xE5
EOF_BYTE = 0x1A
EXT_SZ = 32
SEC_SZ = 128

trans8 = [ 1,7,13,19,25,5,11,17,23,3,9,15,21,2,8,14,20,26,6,12,18,24,4,10,16,22 ]

dpb8 = { 
    'sectors': 26,
    'blksize': 1024,
    'dirsize': 64,
    'disksize': 243,
    'offset': 2,
    'tracks': 77
}

dpbHD = { 
    'sectors': 128,
    'blksize': 2048,
    'dirsize': 1024,
    'disksize': 2040,
    'offset': 0,
    'tracks': 255
}


# PARSE DIRECTORY EXTENTS INTO dir ARRAY OF DICTIONARIES ie. USER:FILE.EXT
def parseDir(dirData, blkMode):

    dir = [ {} for _ in range(16) ]

    for d in range(len(dirData) // EXT_SZ):

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

        blkcount = 0
        if blkMode:
            blocks = []
            for b in range(0, 16, 2):
                bp = dirExt[ 16 + b ] | (dirExt[ 17 + b ] << 8)
                if bp:
                    blkcount += 1
                blocks.append(bp)
        else:
            blocks = dirExt[ 16 : 32 ]
            for a in range(16):
                if dirExt[ 16 + a ]:
                    blkcount += 1

        # print(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {list(blocks)}')

        if user != DEL_BYTE:
            # print(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {list(blocks)}')

            if dir[user].get(filename) == None:
                dir[user][filename] = { 'blocks': 0, "recs": 0, "data": [] }
            
            dir[user][filename]['blocks'] += blkcount
            dir[user][filename]['recs'] += rc
            dir[user][filename]['data'].extend(blocks)
    return dir


# PRINT DIRECTORY
def printDir(dir, blksize):
    for u in range(16):
        if dir[u] != {}:
            print()
            print(f'User {u}:')
            print()
            print('Name         Bytes   Recs')
            print('------------ ------ ------')
            for f in dir[u]:
                size = dir[u][f]['blocks']*(blksize//1024)
                print(f"{f} {size:5}K {dir[u][f]['recs']:5}")


# FORMAT AN EMPTY DISK IMAGE
def formatImage(name, dpb):

    try:
        disk = open(name, 'xb')
    except FileExistsError:
        sys.exit(f"FAILED to open {name} - file exists")

    sec = [ DEL_BYTE ] * SEC_SZ

    for s in range(dpb['sectors'] * dpb['tracks']):
        disk.seek(s * SEC_SZ)
        disk.write(bytearray(sec))

    disk.close()


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


def build_directory(root, dpb):

    boot = False
    dirdata = [ DEL_BYTE ] * (EXT_SZ * dpb['dirsize'])

    d = os.scandir(root)

    dirI = 0
    blkN = (EXT_SZ * dpb['dirsize']) // dpb['blksize']

    for i in d:
        s = i.stat().st_size
        if S_ISREG(i.stat().st_mode):

            if i.name == "$BOOT":
                outcome = '$$$BOOT RECORD$$$'
                boot = True
            else:
                outcome = '<IGNORED>'

            info(f"{i.name:12} {s:6} {s//1024:5} {s//128:5} {outcome}")
            
        if S_ISDIR(i.stat().st_mode):

            if i.name.isnumeric() and int(i.name) in range(16):
                outcome = f'USER: {i.name}'
            else:
                outcome = '<IGNORED>'
                info(f"{i.name:12} <DIR> {outcome}")
                continue

            info(f"{i.name:12} <DIR> {outcome}")

            files = list(os.scandir(os.path.join(root, i.name)))
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

                    f, e = os.path.splitext(name)
                    cpmfile = f'{f:8}'
                    cpmext = f'{e[1:]:3}'

                    info(f"{cpmfile}.{cpmext} {size:6} {size//1024:5} {size//128:5}")

                    ext = [0] * 32

                    ext[0] = int(i.name)

                    ext[1:9] = [ord(c) for c in cpmfile]
                    ext[9:12] = [ord(c) for c in cpmext]

                    # XL - extent number bits 0-4
                    # XH - extent number bits 5-10
                    xNum = 0

                    # BC - always ZERO for CPM22 - ignore

                    # RC - number of recs/secs in the extent
                    # round up if not a full sector (even multiple)
                    rc = size // SEC_SZ + ( 1 if (size % SEC_SZ) else 0)

                    while rc >= 0:
                        nextext = list(ext)
                        nextext[12] = xNum & 0x1F
                        # nextext[13] = 0
                        nextext[14] = xNum >> 5
                        nextext[15] = rc if rc <= 128 else 128

                        ### ADD BLOCK POINTERS HERE
                        numRec = dpb['blksize'] // SEC_SZ
                        bc = (nextext[15] // numRec) + (1 if (nextext[15] % numRec) else 0)

                        for b in range(bc):
                            if dpb['disksize'] > 255:
                                nextext[16 + b*2] = blkN & 0xFF
                                nextext[17 + b*2] = blkN >> 8
                            else:
                                nextext[16 + b] = blkN

                            blkN += 1

                        # debug(nextext)

                        for d in range(EXT_SZ):
                            dirdata[(dirI * EXT_SZ + d)] = nextext[d]
                        
                        dirI += 1

                        xNum += 1
                        rc -= 128

    return ( boot, bytearray(dirdata) )


def writeImage(name, boot, dirdata, dpb, trans):

    root, ext = os.path.splitext(name)
    root += '.unpacked'

    disk = open(name , 'r+b')

    #WRITE BOOT TRACKS
    if boot:
        bootfile = open(os.path.join(root, '$BOOT'), 'rb');
        bootdata = bootfile.read(dpb['sectors'] * dpb['offset'] * SEC_SZ)
        disk.seek(0)
        disk.write(bootdata)
        bootfile.close()

    #WRITE DIRECTORY - MUST BE SECTOR BY SECTOR
    for sd in range((dpb['dirsize'] * EXT_SZ) // SEC_SZ):

        trk = sd // dpb['sectors']
        sec = sd % dpb['sectors']
        
        if trans != 0:
            tb = trans[sec] - 1
        else:
            tb = sec

        loc = (((dpb['offset'] + trk) * dpb['sectors']) + tb) * SEC_SZ
        disk.seek(loc)
        disk.write(bytearray(dirdata[sd * SEC_SZ : (sd+1) * SEC_SZ]))

    dir = parseDir(bytearray(dirdata), 1 if dpb['disksize'] > 255 else 0)
    printDir(dir, dpb['blksize'])

    #WRITE DATABLOCKS - MUST BE SECTOR BY SECTOR
    for u in range(16):
        if dir[u] != {}:
            for f in dir[u]:
                fn = f.split('.',1)
                fn[0] = fn[0].strip()
                fn[1] = fn[1].strip()
                fn = '.'.join(fn)

                file = open(os.path.join(root, f'{u}', fn),'rb')
                fsec = 0

                recs = dir[u][f]['recs']

                for b in dir[u][f]['data']:

                    if b > 0:
                        numRec = dpb['blksize'] // SEC_SZ
                        r = numRec if recs > numRec else recs
                        recs -= r

                        for s in range(r):
                            sec = b * numRec + s
                            trk = sec // dpb['sectors']
                            sec = sec % dpb['sectors']
                            
                            if trans:
                                tb = trans[sec] - 1
                            else:
                                tb = sec

                            loc = (((dpb['offset'] + trk) * dpb['sectors']) + tb) * SEC_SZ
                            disk.seek(loc)
                            file.seek(fsec * SEC_SZ)
                            data = file.read(SEC_SZ)

                            disk.write(data)

                            fsec += 1

                        # debug(f"File: {f} Block: {b} Trk: {trk:02} Sec: {sec:02} Recs: {recs} Len: {len(data)}")

                file.close()

    disk.close()


def main():

    args = sys.argv[1:]
    print (args)

    file, ext = os.path.splitext(args[0])

    if ext == '.hdd':
        dpb = dpbHD
        trans = 0
    elif ext == '.dsk':
        dpb = dpb8
        trans = trans8

    else:
        sys.exit(f'UNKNOWN IMAGE TYPE: {ext} FOR FILE {file + ext}')
      

    (boot, dirdata) = build_directory(file + '.unpacked', dpb)

    formatImage(file + ext, dpb)

    writeImage(file + ext, boot, dirdata, dpb, trans)


if __name__ == "__main__":
    try:
        # logging.basicConfig(filename="trace.log", filemode="w", level=logging.INFO)
        logging.basicConfig(level=logging.INFO)
        main()
    except KeyboardInterrupt:
        # do nothing here
        info("KEY INT")
        pass

