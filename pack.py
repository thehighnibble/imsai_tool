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
#       - make source folder for disk directories either PWD or an argumant or the image name
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


# FORMAT AN EMPTY DISK IMAGE
def formatImage(name):
    disk = open(name, 'w+b')

    sec = [ DEL_BYTE ] * SEC_SZ

    for s in range(dpb['sectors'] * dpb['tracks']):
        disk.seek(s * SEC_SZ)
        disk.write(bytearray(sec))

    disk.close()


def main():

    args = sys.argv[1:]
    print (args)

    root = 'source'

    d = os.scandir(root)

    dirdata = [ DEL_BYTE ] * (EXT_SZ * dpb['dirsize'])
    dirI = 0
    boot = False
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

            print(f"{i.name:12} <DIR> {outcome}")

            subd = os.path.join(root, i.name)
            sd = os.scandir(subd)

            for f in sd:
                size = f.stat().st_size
                if S_ISREG(f.stat().st_mode):

                    n = f.name.split('.')
                    cpmfile = f'{n[0]:8}'
                    cpmext = f'{n[1]:3}'

                    print(f"{cpmfile}.{cpmext} {size:6} {size//1024:5} {size//128:5}")

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

    formatImage(args[0])

    disk = open(args[0], 'r+b')

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
        
        tb = trans[sec] - 1
        loc = (((dpb['offset'] + trk) * dpb['sectors']) + tb) * SEC_SZ
        disk.seek(loc)
        disk.write(bytearray(dirdata[sd * SEC_SZ : (sd+1) * SEC_SZ]))


    dir = parseDir(bytearray(dirdata))
    printDir(dir)

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
                        r = 8 if recs > 8 else recs
                        recs -= r

                        for s in range(r):
                            sec = b * 8 + s
                            trk = sec // dpb['sectors']
                            sec = sec % dpb['sectors']
                            
                            tb = trans[sec] - 1
                            loc = (((dpb['offset'] + trk) * dpb['sectors']) + tb) * SEC_SZ
                            disk.seek(loc)
                            file.seek(fsec * SEC_SZ)
                            data = file.read(SEC_SZ)

                            disk.write(data)

                            fsec += 1

                        # print(f"File: {f} Block: {b} Trk: {trk:02} Sec: {sec:02} Recs: {recs} Len: {len(data)}")

                file.close()

    disk.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # do nothing here
        print("KEY INT")
        pass

