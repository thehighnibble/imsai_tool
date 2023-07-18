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
#       - make file paths platform independent
#       - make target folder for disk directories either PWD or an argumant
#
#   known issues:
#       - TBD
#
#   history:
#        17-JUL-2023     1.0     Initial release
##

import sys
import os

DEL_BYTE = 0xE5
EXT_SZ = 32
SEC_SZ = 128

trans = [ 1,7,13,19,25,5,11,17,23,3,9,15,21,2,8,14,20,26,6,12,18,24,4,10,16,22 ]

dpb = { 
    'sectors': 26,
    'blksize': 1024,
    'dirsize': 64,
    'disksize': 243,
    'offset': 2,
    'tracks': 77
}


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


def main():

    args = sys.argv[1:]
    print (args)

    image = open(args[0], "rb")

    # print(dpb)

    boot = image.read(dpb['offset'] * dpb['sectors'] * SEC_SZ)

    if boot[0] != DEL_BYTE:
        print("$$$BOOT RECORD$$$")

    dirsecs = dpb['dirsize'] * EXT_SZ // SEC_SZ
    # print(dirsecs)

    dirData = b''

    # READ DIRECTORY SECTORS
    for b in range( dirsecs ):
        # print(trans[b])
        tb = trans[b] - 1
        loc = ((dpb['offset'] * dpb['sectors']) + tb) * SEC_SZ
        # print(b, trans[b], f'{loc:04X}')
        image.seek(loc)
        blk = image.read(SEC_SZ)
        dirData += blk

    dir = parseDir(dirData)
    printDir(dir)

    os.mkdir('disk')
    if boot[0] != DEL_BYTE:
        bf = open('disk/$BOOT', 'wb')
        bf.write(boot)
        bf.close()

    for u in range(16):
        if dir[u] != {}:
            os.mkdir(f'disk/{u}')
            if dir[u] != { }:
                for f in dir[u]:
                    fn = f.split('.',1)
                    fn[0] = fn[0].strip()
                    fn[1] = fn[1].strip()
                    fn = '.'.join(fn)

                    file = open(f'disk/{u}/{fn}','ab')

                    recs = dir[u][f]['recs']

                    for b in dir[u][f]['data']:

                        if b > 0:
                            r = 8 if recs > 8 else recs
                            recs -= r

                            for s in range(r):
                                sec = b * 8 + s
                                trk = sec // dpb['sectors']
                                sec = sec % dpb['sectors']
                                
                                tb = trans[sec] - 1
                                loc = (((dpb['offset'] + trk) * dpb['sectors']) + tb) * SEC_SZ
                                image.seek(loc)
                                data = image.read(SEC_SZ)

                                file.write(data)

                            # print(f"File: {f} Block: {b} Trk: {trk:02} Sec: {sec:02} Recs: {recs} Len: {len(data)}")

                    file.close()

    image.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # do nothing here
        print("KEY INT")
        pass