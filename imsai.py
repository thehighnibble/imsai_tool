#!/usr/bin/env python3
##
#   imsai.py
#
#   Copyright (C) David McNaughton 2021-present
#
#   a utility to remotely manage the IMSAI8080esp
#   using the RESTful interface used by the webfontend
#
#   dependencies:
#       python3
#       requests (module)           - to install, use: pip install requests
#       websocket-client (module)   - to install, use: pip install websocket-client
#
#   known issues:
#       - SYS: information is only shown as JSON and isn't formatted
#       - MAN: only lists the manual contents and you can't manage the content
#       - still can't load/eject the I:DSK: harddisk
#       - the webfrontemnd does not automatically update
#           if changes are made using this script
#       - hangs if the IMSAI isn't reachable
#
#   history:
#        07-JUL-2021     1.0     Initial release
##

import requests
import json
import sys
import os
import websocket

cmd = os.path.split(sys.argv[0])[1]

if cmd == 'imsai':
    baseurl = 'http://imsai8080'
elif cmd == 'cromemco':
    baseurl = 'http://cromemco'

sys_get = requests.get(baseurl + '/system')
task_get = requests.get(baseurl + '/tasks')
dsk_get = requests.get(baseurl + '/disks?x')
lib_get = requests.get(baseurl + '/library')
man_get = requests.get(baseurl + '/manual')
conf_get = requests.get(baseurl + '/conf')

d_sys = sys_get.json()
d_tasks = task_get.json()
d_dsk = dsk_get.json()
a_lib = lib_get.json()
a_man = man_get.json()
a_conf = conf_get.json()


def sys_f(args):

    if len(args) >= 1:
        sect = args[0]
        if sect in d_sys.keys():
            print(json.dumps(d_sys[sect], indent=4))
        elif sect == 'tasks':
            print(json.dumps(d_tasks, indent=4))
        elif sect == '--reboot':
            reboot_get = requests.delete(baseurl + '/system')
            if reboot_get.status_code == 205:
                print('SYS: REBOOT underway')
            else:
                print('SYS: REBOOT failed')
        elif sect == '--update' and len(args) >= 2:
            bin_name = args[1]
            if not bin_name.endswith('.bin'):
                print("SYS: UPDATE only try to flash a binary")
            else:
                if not os.path.exists(bin_name):
                    print(f'SYS: UPDATE {bin_name} does not exist ?')
                else:
                    print(f"SYS: UPDATE {bin_name}")
                    files = open(bin_name, 'rb')
                    bin_file = requests.put(baseurl + '/flash?' + bin_name,
                                            data=files)
                    if bin_file.status_code == 200:
                        fmt = 'SYS: UPDATE success - {} bytes uploaded to {}'
                        res = bin_file.json()
                        print(fmt.format(res['size'], res['filename']))
                    else:
                        fmt = 'SYS: UPDATE failed - server error ({})'
                        print(fmt.format(bin_file.status_code))
        else:
            print('SYS: ' + sect + ' ?')

    else:
        print(json.dumps(d_sys, indent=4))
        print(json.dumps(d_tasks, indent=4))


def dsk_f(args):
    # print(json.dumps(d_dsk, indent=4))
    for d in d_dsk:
        fmt = '\t{}:DSK: = {}'
        print(fmt.format(d, d_dsk[d] or '<empty>'))


def xdsk_f(disk, args):
    disk = disk.upper()
    if len(args) == 0:
        fmt = '\t{} = {}'
        print(fmt.format(disk, d_dsk[disk[0]] or '<empty>'))
    else:
        action = args[0]
        if action == '--eject':
            print('Eject ' + disk)
            if disk[0] not in ['A', 'B', 'C', 'D']:
                print('ERROR: ' + disk + ' not a floppy disk drive')
            elif not d_dsk[disk[0]]:
                print('ERROR: ' + disk + ' already empty')
            else:
                dsk_get = requests.delete(baseurl + '/disks?' + disk)
                if dsk_get.status_code == 200:
                    print('OK Ejected')
                else:
                    print('Failed to Eject')

        elif action == '--load':
            image = args[1]
            print('Load ' + disk + ' = ' + image)

            if disk[0] not in ['A', 'B', 'C', 'D']:
                print('ERROR: ' + disk + ' not a floppy disk drive')
            elif d_dsk[disk[0]]:
                print('ERROR: ' + disk + ' not empty')
            elif not image.endswith('.dsk'):
                print('ERROR: ' + image + ' not a floppy disk image')
            elif not image in a_lib:
                print('ERROR: ' + image + ' not in library')
            elif image in d_dsk.values():
                print('ERROR: ' + image + ' already loaded')
            else:
                dsk_get = requests.put(baseurl + '/disks?' + disk, data=image)

                if dsk_get.status_code == 200:
                    print('OK Loaded')
                else:
                    print('Failed to load')
        else:
            print(disk + ' ' + action + ' ?')


def lib_f(args):
    # print(json.dumps(a_lib, indent=4))
    if len(args) == 0:
        for l in sorted(a_lib):
            fmt = '\t{1}{0}'
            print(fmt.format(l, '\b\b* ' if l in d_dsk.values() else ''))
    else:
        action = args[0]
        if action == '--upload' and len(args) >= 2:
            lib_name = args[1]
            if lib_name in a_lib:
                print('LIB: UPLOAD ' + lib_name + ' already exists in LIB:')
            elif lib_name.endswith('.dsk') or lib_name.endswith('.hdd'):
                print('LIB: UPLOAD ' + lib_name)
                if not os.path.exists(lib_name):
                    print('LIB: UPLOAD ' + lib_name + ' does not exist ?')
                else:
                    files = open(lib_name, 'rb')
                    lib_file = requests.put(baseurl + '/library?' + lib_name,
                                            data=files)
                    if lib_file.status_code == 200:
                        fmt = 'LIB: UPLOAD success - {} bytes uploaded to {}'
                        res = lib_file.json()
                        print(fmt.format(res['size'], res['filename']))
                    else:
                        fmt = 'CFG: UPLOAD failed - server error ({})'
                        print(fmt.format(lib_file.status_code))
            else:
                print('LIB: UPLOAD ' + lib_name +
                      ' does not look like a disk image ?')
        elif action == '--delete' and len(args) >= 2:
            lib_name = args[1]
            if lib_name in a_lib:
                if lib_name in d_dsk.values():
                    fmt = 'LIB: --DELETE failed - {} currently loaded'
                    print(fmt.format(lib_name))
                else:
                    lib_file = requests.delete(baseurl + '/library',
                                               data=lib_name)
                    if lib_file.status_code == 200:
                        print('LIB: --DELETE success - deleted ' + lib_name +
                              ' from LIB:')
                    else:
                        fmt = 'LIB: --DELETE failed - server error ({})'
                        print(fmt.format(lib_file.status_code))
            else:
                print('LIB: --DELETE ' + lib_name + ' ?')
        else:
            lib_name = action
            if lib_name in a_lib:
                lib_file = requests.get(baseurl + '/imsai/disks/' + lib_name)
                if lib_file.status_code == 200:
                    # print(lib_file.reponse)
                    files = open(lib_name, 'wb')
                    files.write(lib_file.content)
                    files.close()
                else:
                    print('ERROR: could not open ' + lib_name)
            else:
                print('LIB: ' + lib_name + ' ?')


def man_f(args):
    # print(json.dumps(o_man, indent=4))
    for m in sorted(a_man):
        fmt = '\t{}'
        if not m.endswith('png'):
            print(fmt.format(m))


def conf_f(args):
    # print(json.dumps(a_conf, indent=4)
    if len(args) == 0:
        for c in sorted(a_conf):
            fmt = '\t{}'
            print(fmt.format(c))
    else:
        action = args[0]
        if action == '--upload' and len(args) >= 2:
            cfg_name = args[1]
            if cfg_name in a_conf:
                print('CFG: UPLOAD ' + cfg_name)
                if not os.path.exists(cfg_name):
                    print('CFG: UPLOAD' + cfg_name + ' does not exist ?')
                else:
                    files = open(cfg_name, 'rb')
                    cfg_file = requests.put(baseurl + '/conf?' + cfg_name,
                                            data=files)
                    if cfg_file.status_code == 200:
                        fmt = 'CFG: UPLOAD success - {} bytes uploaded to {}'
                        res = cfg_file.json()
                        print(fmt.format(res['size'], res['filename']))
                    else:
                        fmt = 'CFG: UPLOAD failed - server error ({})'
                        print(fmt.format(cfg_file.status_code))
            else:
                print('CFG: UPLOAD ' + cfg_name + ' ?')
        else:
            cfg_name = action
            if cfg_name in a_conf:
                cfg_file = requests.get(baseurl + '/imsai/conf/' + cfg_name)
                if cfg_file.status_code == 200:
                    print(cfg_file.text)
                else:
                    print('ERROR: could not open ' + cfg_name)
            else:
                print('CFG: ' + cfg_name + ' ?')


def cpa_f(args):

    msg = ''

    if len(args) == 0:
        msg = 'P'
        action = '\b'
    else:
        action = args[0]
        if action == 'run':
            print('CPA: RUN')
            msg = 'ruP'
        elif action == 'stop':
            print('CPA: STOP')
            msg = 'rdP'
        elif action == 'step':
            print('CPA: STEP')
            msg = 'suP'
        elif action == 'reset':
            print('CPA: RESET')
            msg = 'cuP'
        elif action == 'extclr':
            print('CPA: EXTCLR')
            msg = 'cdP'
        else:
            print('CPA: ' + action + ' ?')

    if msg != '':
        ws = websocket.WebSocket()
        ws.connect(baseurl.replace('http', 'ws', 1) + '/cpa')
        ws.send(msg)
        cpa = ws.recv()
        ws.close()

        state = ''
        if cpa[1] == 'I':
            state += 'INTR.EN '
        if cpa[2] == 'R':
            state += 'RUN '
        if cpa[3] == 'W':
            state += 'WAIT '
        if cpa[4] == 'H':
            state += 'HOLD '
        if cpa[0] == 'U':
            state += 'PWR.ON'
        if cpa[0] == 'D':
            state += 'PWR.OFF'

        print('CPA: ' + state)


def help_f(args):

    cmd = os.path.basename(sys.argv[0])

    if len(args) == 0:
        sect = ''
        print('\tusage: ' + cmd +
              ' {sys: | dsk: | x:dsk: | lib: | man: | cfg: | cpa:}')
        print('\tfor help on a device use: ' + cmd + ' help [device | all]')
        print('\t- device (optional) - one of the listed devices')
        print('\t- all (optional) - show all help')

    else:
        sect = args[0]

        if sect == 'all':
            help_f([])
            print()
            for s in sections:
                if ':' in s:
                    help_f([s])
                    print()

        elif sect == 'sys:':
            print('\tusage: ' + cmd + ' sys: [{section | --reboot | --update binary_file}] ')
            print('\tshow the system details (currently only in json)')
            print('\t- section (optional) - show only the named section')
            print('\t- --reboot (optional) - reboot the IMSAI8080')
            print('\t- --update binary_file (optional) - update the system with the binary file from the local directory ')
            # TODO: format the output

        elif sect == 'dsk:':
            print('\tusage: ' + cmd + ' dsk:')
            print('\tshow the loaded disks')

        elif sect == 'x:dsk:':
            print('\tusage: ' + cmd +
                  ' x:dsk: [{--eject | --load disk_image}] ')
            print(
                '\tshow the disk loaded in drive x - where x is a valid drive {a|b|c|d|i}'
            )
            print('\t- --eject (optional) - eject drive x')
            print(
                '\t- --load disk_image (optional) - load the library image in drive x'
            )

        elif sect == 'lib:':
            print('\tusage: ' + cmd +
                  ' lib: [{--upload | --delete}] [disk_image]')
            print(
                '\tshow the contents of the disk library - loaded disk images are prefixed with an asterix (*)'
            )
            print(
                '\t- disk_image (optional) - downloads the library image from LIB: to the currernt local directory'
            )
            print(
                '\t- --upload disk_image (optional) - uploads the disk image from the currernt local directory to LIB:'
            )
            print(
                '\t- --delete disk_image (optional) - deletes the library image from LIB:'
            )

        elif sect == 'man:':
            print('\tusage: ' + cmd + ' man:')
            print('\tshow the contents of the manual')
            # TODO: add upload and (open) and delete

        elif sect == 'cfg:':
            print('\tusage: ' + cmd + ' cfg: [--upload] [config_name]')
            print('\tshow the list of config files')
            print(
                '\t- config_name (optional) - show the contents of the config file'
            )
            print(
                '\t- --upload config_name (optional) - upload the contents of the config file'
            )

        elif sect == 'cpa:':
            print('\tusage: ' + cmd +
                  ' cpa: {[run | stop | step | reset | extclr]}')
            print(
                '\tshow the current state of the CPA: control lights and power switch'
            )
            print(
                '\t- key (optional) - press/depress the corresponding key on the CPA:'
            )
        else:
            print('HELP ' + sect + ' ?')


sections = {
    'sys:': sys_f,
    'dsk:': dsk_f,
    'x:dsk:': None,
    'lib:': lib_f,
    'man:': man_f,
    'cfg:': conf_f,
    'cpa:': cpa_f,
    'help': help_f,
    '-h': help_f,
    '--help': help_f
}

args = sys.argv[1:]

if len(args) == 0:
    help_f(args)
elif len(args) >= 1:
    sect = args[0]
    if sect in sections:
        if sections[sect]:
            sections[sect](args[1:])
        else:
            print(sect + ' ?')
    elif sect.endswith(':dsk:') and sect[:-5].upper() in d_dsk.keys():
        xdsk_f(sect, args[1:])
    else:
        print(sect + ' ?')