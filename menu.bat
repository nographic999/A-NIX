@echo off
rem menu.bat - menu for all A-NIX board tools (uses anix.py and the
rem portable Python in python\). The status line shows where the Pico is.
setlocal
cd /d "%~dp0"
set PY="%~dp0python\python.exe"
set TOOL="%~dp0anix.py"
title A-NIX tools
if not exist %PY% (
    echo No portable Python in %~dp0python\
    echo Put it there first - see README.md, "Installing".
    pause
    goto :eof
)

cls
:menu
echo  ==========================================================
echo   A-NIX tools
%PY% %TOOL% status
echo  ==========================================================
echo.
echo   USB (close the console first)
echo     1  Install / update A-NIX     (compiled .mpy - normal)
echo     2  Install / update A-NIX     (plain .py - to debug)
echo     3  Copy source\root to /root  (.py compiled to .mpy)
echo     4  Backup the board           (to dump\)
echo.
echo   Firmware
echo     5  Install MicroPython        (.uf2 from firmware\)
echo     6  NUKE - erase everything, then install MicroPython
echo.
echo   Console
echo     7  PuTTY over USB
echo     8  PuTTY over WiFi (telnet)   (Enter = last IP, s = scan)
echo     9  Find the Pico on WiFi
echo.
echo     0  Exit
echo.
choice /c 1234567890 /n /m "  Select: "
set pick=%errorlevel%
if %pick%==10 goto :eof
cls
if %pick%==1 %PY% %TOOL% upload
if %pick%==2 %PY% %TOOL% upload_py
if %pick%==3 %PY% %TOOL% root
if %pick%==4 %PY% %TOOL% dump
if %pick%==5 %PY% %TOOL% flash
if %pick%==6 %PY% %TOOL% nuke
if %pick%==7 %PY% %TOOL% connect
if %pick%==8 %PY% %TOOL% telnet
if %pick%==9 %PY% %TOOL% find
echo.
goto menu
