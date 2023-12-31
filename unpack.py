#!/usr/bin/env python3
##
#   unpack.py
#
#   Copyright (C) David McNaughton 2023-present
#
#   a utility to unpack a CP/M (2.2) disk image files (*.dsk) directories  
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

import sys
import os
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

        if user != DEL_BYTE and user <= 0x0F:
            # info(f'Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {list(blocks)}')

            if dir[user].get(filename) == None:
                dir[user][filename] = { 'blocks': 0, "recs": 0, "data": [] }
            
            dir[user][filename]['blocks'] += blkcount
            dir[user][filename]['recs'] += rc
            dir[user][filename]['data'].extend(blocks)
        elif user != DEL_BYTE:
            warning(f'***UNKNOWN Entry: {d:02} User: {user:02X} Filename: {filename} Ext(xl:xh): {xl:02X}:{xh:02X} Len(bc:rc): {bc}:{rc} Bps: {list(blocks)}')

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

def main():

    args = sys.argv[1:]
    print (args)

    try:
        image = open(args[0] + '.dsk', "rb")

        dpb = dpb8
        trans = trans8
    except FileNotFoundError:
        try:
            image = open(args[0] + '.hdd', "rb")

            dpb = dpbHD
            trans = 0
        except FileNotFoundError as e:
            sys.exit(f'DISK IMAGE FILE NOT FOUND for {args[0]}')

    root = args[0] + '.unpacked'

    if dpb['offset'] > 0:
        boot = image.read(dpb['offset'] * dpb['sectors'] * SEC_SZ)

        if boot[0] != DEL_BYTE:
            print("$$$BOOT RECORD$$$")

    dirsecs = dpb['dirsize'] * EXT_SZ // SEC_SZ
    # debug(dirsecs)

    dirData = b''

    # READ DIRECTORY SECTORS
    for b in range( dirsecs ):
        if trans:
            tb = trans[b] - 1
        else:
            tb = b
        loc = ((dpb['offset'] * dpb['sectors']) + tb) * SEC_SZ
        # debug(b, tb, f'{loc:04X}')
        image.seek(loc)
        blk = image.read(SEC_SZ)
        dirData += blk

    dir = parseDir(dirData, 1 if dpb['disksize'] > 255 else 0)
    printDir(dir, dpb['blksize'])

    try:
        os.mkdir(root)
    except FileExistsError:
        sys.exit(f'FAILED to create {root} - directory already exists')

    if dpb['offset'] > 0 and boot[0] != DEL_BYTE:
        bf = open(os.path.join(root, '$BOOT'), 'wb')
        bf.write(boot)
        bf.close()

    for u in range(16):
        if dir[u] != {}:
            os.mkdir(os.path.join(root, f'{u}'))
            if dir[u] != { }:
                for f in dir[u]:
                    fn = f.split('.',1)
                    fn[0] = fn[0].strip()
                    fn[1] = fn[1].strip()
                    fn = '.'.join(fn)

                    file = open(os.path.join(root, f'{u}', fn),'ab')

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
                                image.seek(loc)
                                data = image.read(SEC_SZ)

                                file.write(data)

                                # info(f"File: {f} Block: {b} Trk: {trk:02} Sec: {sec:02} Recs: {recs} Len: {len(data)}")

                    file.close()

    image.close()

if __name__ == "__main__":
    try:
        # logging.basicConfig(filename="trace.log", filemode="w", level=logging.INFO)
        logging.basicConfig(level=logging.INFO)
        main()
    except KeyboardInterrupt:
        # do nothing here
        info("KEY INT")
        pass