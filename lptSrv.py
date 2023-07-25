#!/usr/bin/env python3
##
#   lptsrv.py
#
#   Copyright (C) David McNaughton 2023-present
#
#   a utility to remotely provide a lineprinter on LPT: for the IMSAI8080esp 
#   using the RESTful interface provided for IO
#   providing text file output 
#   or direct to PDF in either portrait (80 col) or landscape (132 col)
#
#   dependencies:
#       python3
#       requests (module)           - to install, use: pip install requests
#       simple_http_server (module) - to install, use: pip install simple_http_server
#       fpdf2 (module)              - to install, use: pip install fpdf2
#
#   TODO:
#       - add US paper sizes
#       - make mode selection a command line arg or a key switched mode
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
import socket
from simple_http_server import route, server, Response, ModelDict, logger as httpdlog
from threading import Thread
from logging import debug, info, error, warning
import logging
from fpdf import FPDF

httpdlog.set_level("ERROR")

srv = os.path.splitext(os.path.basename(sys.argv[0]))[0]

LPT_PORT = 0xF6
SRV_PORT = 3000 + LPT_PORT
SRV_PATH = srv

hosturl = 'http://imsai8080'
_srvurl = f'http://{socket.gethostname()}:{SRV_PORT}/{SRV_PATH}'

sess = requests.Session()

TMAX = 77
win = None

mode = 'txt'
file = "print"
orientation = "PORTRAIT"
line = 0
lines = 0
pages = 0


def main(sc):

    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)

    global RED
    global GREEN
    global YELLOW
    global CYAN

    RED = curses.color_pair(1)
    GREEN = curses.color_pair(2)
    YELLOW = curses.color_pair(3)
    CYAN = curses.color_pair(4)

    global win
    curses.curs_set(0)
    curses.textpad.rectangle(sc, 0, 0, curses.LINES - 1, TMAX + 1)
    title = f"[ Remote IMSAI LPT - {srv} ]"
    sc.addstr(0, (TMAX + 2 - len(title))//2, title)
    sc.refresh()
    win = curses.newwin(curses.LINES - 2 , TMAX , 1, 1)

    win.addstr(0, 0, f"*** Not Connected ***", YELLOW)
    connect_to_host()

    ## DONT RUN THIS IN A VM OR THE HOST CAN'T BE SEEN
    th = Thread(target=server.start, args=("", SRV_PORT), daemon=True)
    th.start()

    global pdf, tf
    global mode, file, orientation
    global line, lines, pages

    if mode == 'pdf':
        pdf = FPDF()
    else:
        tf = open(file + '.txt', "w")
        tf.close()

    while True:
        key = win.getkey()
        win.addstr(curses.LINES - 3, 1, f"KEY: <{key}>", CYAN)
        win.clrtoeol()
        win.refresh()

        # info(f"KEY: {key} len={len(key)} ord={ord(key)}")
        if key == chr(24): # ^X
            connect_to_host()
        if key == chr(4): # ^D
            # ORIENTATION
            if orientation == "PORTRAIT":
                orientation = "LANDSCPE"
            else:
                orientation = "PORTRAIT"
            win.addstr(curses.LINES - 3, 12, f"{orientation}", GREEN)
        if key == chr(16): # ^P
            # PORTRAIT
            orientation = "PORTRAIT"
            win.addstr(curses.LINES - 3, 12, f"{orientation}", GREEN)
        if key == chr(12): # ^L
            # LANDSCAPE
            orientation = "LANDSCPE"
            win.addstr(curses.LINES - 3, 12, f"{orientation}", GREEN)
        if key == chr(6): # ^F
            # EJECT
            win.addstr(curses.LINES - 3, 12, f"FORMFEED/EJECT", YELLOW)
            if line > 0:
                if mode == 'pdf':
                    if len(linebuf) > 0:
                        pdf.cell(txt="".join(linebuf[0:lineLength]))
                    pdf.output(file + '.pdf')
                    pdf = FPDF()
                else:
                    if len(linebuf) > 0:
                        tf = open(file + '.txt', "a")
                        tf.write("".join(linebuf))
                        tf.close()
                line = 0

                lines = 0
                pages = 0
        elif key == chr(14): # ^N
            #CHANGE FILE
            # PROMPT USER FOR FILE NAME USING TEXTBOX
            win.addstr(curses.LINES - 3, 0, f"{mode.upper()} FILE NAME = ")
            win.clrtoeol()
            win.refresh()
            curses.curs_set(1)
            txtwin = curses.newwin(1 , TMAX - 34 , curses.LINES - 2, 17)
            tb = curses.textpad.Textbox(txtwin, insert_mode=True)
            txt = tb.edit()
            curses.curs_set(0)
            txt = txt.strip()
            info(f"CHANGE {mode.upper()} FILE NAME TO {txt}")
            file = txt


@route(f'/{SRV_PATH}', method="PUT")
def io_out(p, m=ModelDict()):
    port = int(p, 16)
    #BODY is a little hard to get as it ends up as the first KEY in the DICT m
    data = int(next(iter(m)), 16) 
    # info(f'{port:02X} {data:02X}')
    if port == LPT_PORT:
        t = lpt_out(data)

        if t == 1:
            return Response(status_code=201)
    return #normal 200 response 

def connect_to_host():

    try:
        sys_get = requests.delete(f'{hosturl}/io?p={LPT_PORT:02X}')
        if sys_get.status_code == 200:
            info(f'De-registered on {sys_get.text}')
            win.addnstr(0, 0, f'De-registered on {sys_get.text}', TMAX)

        sys_get = requests.patch(f'{hosturl}/io?p=-{LPT_PORT:02X}&b=0xFF&t=0x0D', data=_srvurl)
        if sys_get.status_code == 200:
            info(f'Listening and registered on Port {LPT_PORT:02X}h to {sys_get.text}')
            win.addnstr(0, 0, f'Listening and registered on Port {LPT_PORT:02X}h to {sys_get.text}', TMAX, GREEN)
            win.refresh()
    except:
        win.addnstr(0, 0, f"*** FAILED to find {hosturl} - not connected", TMAX, RED)
        win.getkey()
        sys.exit(f"FAILED to find {hosturl} - not connected")

def lpt_out(data):

    res = 0

    win.addstr(1, 0, 'RECV', curses.A_REVERSE + RED)
    win.clrtoeol()
    win.refresh()

    ch = chr(data)
    if mode == 'pdf':
        pdfPrint(ch)
    else:
        textPrint(ch)

    updateStats()

    win.addstr(1, 0, '    ')
    win.refresh()
    return res

def updateStats():

    win.addstr(2, 0, f"Mode: {mode.upper()}  File: {file + '.' + mode}")
    win.clrtoeol()
    win.addstr(3, 0, f'Orientation: {orientation}  Size: A4')
    win.clrtoeol()
    win.addstr(4, 0, f'Pages: {pages}  Lines: {lines}')
    win.clrtoeol()
    win.addstr(5, 0, f'Line: {line}/{pageLength}  Pos: {lpos}')
    win.clrtoeol()


lpos = 0
linebuf = []
pageLength = 66
lineLength = 80

def pdfPrint(ch):
    
    global lpos, line, lines, pages, lineLength

    if line == 0:
        if orientation == 'PORTRAIT':
            pdf.add_page(orientation=orientation[0])
            pdf.set_margin(2.5)
            pdf.set_font('Courier', size=12)
            lineLength = 80
            linespacing = 0
        else: 
            pdf.add_page(orientation=orientation[0])
            pdf.set_margin(2.5)
            pdf.set_font('Courier', size=9)
            lineLength = 132
            lineSpacing = 3.1

        pages += 1
        line += 1
        lines += 1
        lpos = 0

    if ord(ch) >= 0x20 and ord(ch) < 0x7F:
        if lpos == len(linebuf):
            linebuf.append(ch)
        else:
            linebuf[lpos] = ch
        lpos += 1
    elif ord(ch) == 13: # <CR>
        lpos = 0
    elif ord(ch) == 10: # <LF>
        pdf.cell(txt="".join(linebuf[0:lineLength]))
        if lineSpacing > 0:
            pdf.ln(lineSpacing)
        else:
            pdf.ln()
        line += 1
        lines += 1
        linebuf.clear()
        lpos = 0
    elif ord(ch) == 12: # <FF>
        lines += pageLength - line
        line = 0

    if line > pageLength:
        lines -= 1
        line = 0

def textPrint(ch):
    global lpos, line, lines, pages, lineLength

    if line == 0: 
        if len(linebuf) > 0:
            tf = open(file + '.txt', "a")
            tf.write("".join(linebuf))
            tf.close()
            linebuf.clear()
        pages += 1
        line += 1
        lines += 1
        lpos = 0

    if ord(ch) >= 0x20 and ord(ch) < 0x7F:
        lpos += 1
    elif ord(ch) == 13: # <CR>
        lpos = 0
    elif ord(ch) == 10: # <LF>
        tf = open(file + '.txt', "a")
        tf.write("".join(linebuf))
        tf.close()
        linebuf.clear()
        line += 1
        lines += 1
        lpos = 0
    elif ord(ch) == 12: # <FF>
        lines += pageLength - line
        line = 0

    if line > pageLength:
        lines -= 1
        line = 0

    linebuf.append(ch)


if __name__ == "__main__":
    try:
        logging.basicConfig(filename="lpt.log", filemode="w", level=logging.INFO)
        curses.wrapper(main)
    except KeyboardInterrupt:
        logging.root.setLevel(logging.INFO)
        debug("KEY INT")
        sess.close()
        if mode == 'pdf':
            if len(linebuf) > 0:
                pdf.cell(txt="".join(linebuf[0:lineLength]))
            pdf.output(file + '.pdf')
        else:
            if len(linebuf) > 0:
                tf = open(file + '.txt', "a")
                tf.write("".join(linebuf))
                tf.close()
        try:
            sys_get = requests.delete(f'{hosturl}/io?p={LPT_PORT:02X}')
            if sys_get.status_code == 200:
                info(f'De-registered on {sys_get.text}')
        except:
            pass