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
import socket
from simple_http_server import route, server, Response, ModelDict, logger

logger.set_level("ERROR")

srv = os.path.splitext(os.path.basename(sys.argv[0]))[0]

FIF_PORT = 0xFD
SRV_PORT = 3000
SRV_PATH = srv

hosturl = 'http://imsai8080'
_srvurl = f'http://{socket.gethostname()}:{SRV_PORT}/{SRV_PATH}'

disks = { 'A': 'cpm22b01.dsk', 'B': 'comms.dsk', 'C': 'dazzler.dsk', 'D': 'ZorkI.dsk' }
disk_to_unit = { 'A': 1, 'B': 2, 'C': 4, 'D': 8, 'I': 15 }
sel_units = [ ]
unit_file = { }

def main():
    print('DISKS:')
    for d in disks:
        sel_units.append(disk_to_unit[d])
        unit_file[disk_to_unit[d.upper()]] = disks[d]
        print(f'\tDSK:{d.upper()}: = {disks[d]}')

    sys_get = requests.patch(f'{hosturl}/io?p=-{FIF_PORT:02X}', data=_srvurl)
    if sys_get.status_code == 200:
        print(f'Listening and registered on Port {FIF_PORT:02X}h to {sys_get.text}')

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

SEC_SZ = 128
SPT8 = 26

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
            fd = open(unit_file[unit], 'r+b')

            pos = (track * SPT8 + sector - 1) * SEC_SZ

            sec_get = requests.get(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}')
            blksec = sec_get.content

            fd.seek(pos)
            fd.write(blksec)
            fd.close()

            disk_res = bytes.fromhex('01')
        elif cmd == 2:
            fd = open(unit_file[unit], 'rb')

            pos = (track * SPT8 + sector - 1) * SEC_SZ
            fd.seek(pos)
            block = fd.read(SEC_SZ)

            sec_put = requests.put(f'{hosturl}/dma?m={dma_addr:04X}&n={SEC_SZ:02X}', data=block)
            
            fd.close()
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