#!/bin/bash
# menu.sh - menu for all A-NIX board tools on Linux (Debian, Ubuntu,
# Raspberry Pi OS). Uses anix.py with its own Python in .venv, made on
# the first start. The status line shows where the Pico is.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
PY=.venv/bin/python
DIR="$(pwd)"

# --- uninstall: ./menu.sh uninstall, or U in the menu ---
ask() {   # ask "question" -> true for yes (Enter = no)
    local a
    read -r -p "$1 [y/N] " a
    case "$a" in [yY]*) return 0 ;; *) return 1 ;; esac
}
installed() {   # installed PACKAGE -> true if apt has it installed
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}
uninstall() {
    echo "Uninstall the A-NIX tools' dependencies (your files, source/,"
    echo "firmware/ and dump/ stay; the board is not touched)."
    echo
    if [ -d .venv ]; then
        if ask "Remove .venv (mpremote, mpy-cross, pyserial - $(du -sh .venv | cut -f1))?"; then
            rm -rf .venv && echo "  removed .venv"
        fi
    else
        echo "  .venv: not there"
    fi
    rm -f .lastip
    PKGS=""
    VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
    for p in putty picocom telnet python3-pip python3-venv ${VER:+python$VER-venv}; do
        installed "$p" && PKGS="$PKGS $p"
    done
    if [ -n "$PKGS" ]; then
        echo
        echo "Installed system packages that A-NIX can use:$PKGS"
        echo "(other programs may need them too - remove only what you"
        echo " installed for A-NIX)"
        for p in $PKGS; do
            if ask "  sudo apt remove $p?"; then
                sudo apt-get remove -y "$p" >/dev/null && echo "  removed $p"
            fi
        done
    else
        echo "  system packages: none of putty, picocom, telnet, python3-pip,"
        echo "  python3-venv is installed"
    fi
    if [ "$(id -u)" != 0 ] && id -nG "$USER" | grep -qw dialout; then
        echo
        if ask "Remove $USER from the dialout group (USB serial ports)?"; then
            sudo gpasswd -d "$USER" dialout && echo "  done - takes effect after logging out"
        fi
    fi
    echo
    echo "Done. To remove A-NIX tools completely, delete this folder:"
    echo "    rm -rf \"$DIR\""
}
if [ "$1" = "uninstall" ]; then
    uninstall
    exit 0
fi

# --- permissions: the folder must be yours (copied from another system,
# a USB stick or with sudo it may belong to root or be read-only) ---
if [ "$(id -u)" != 0 ] && [ -n "$(find . -maxdepth 3 ! -user "$USER" -print -quit 2>/dev/null)" ]; then
    echo "Some files in $DIR don't belong to you ($USER)."
    read -r -p "Make the whole folder yours (sudo chown)? [Y/n] " ans
    case "$ans" in
        [nN]*) ;;
        *) sudo chown -R "$USER": "$DIR" ;;
    esac
fi
if [ ! -w . ]; then
    echo "$DIR is read-only - copy it to your home folder (e.g. ~/A-NIX) first."
    exit 1
fi
chmod u+rwX -R . 2>/dev/null           # read/write everything, enter folders
chmod +x menu.sh anix.py 2>/dev/null

# --- USB port access: the dialout group ---
if [ "$(id -u)" != 0 ] && ! id -nG "$USER" | grep -qw dialout; then
    echo "To use the Pico's USB port you must be in the dialout group."
    read -r -p "Add $USER to dialout now (sudo)? [Y/n] " ans
    case "$ans" in
        [nN]*) ;;
        *) sudo usermod -aG dialout "$USER" &&
           echo "done - log out and in once (or reboot) for it to work" ;;
    esac
    echo
elif [ "$(id -u)" != 0 ] && ! id -nG | grep -qw dialout; then
    echo "note: you were added to dialout, but this login doesn't have it yet -"
    echo "      log out and in once (or reboot)"
    echo
fi

# --- Python environment in .venv (made once; rebuilt if broken) ---
venv_ok() {
    [ -x "$PY" ] && "$PY" -c "import mpremote, mpy_cross, serial" 2>/dev/null
}
if ! venv_ok; then
    VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
    if [ -z "$VER" ]; then
        echo "Python 3 is missing - run: sudo apt install python3 python3-venv"
        exit 1
    fi
    echo "Setting up a Python environment in .venv ..."
    rm -rf .venv
    if ! python3 -m venv .venv 2>/dev/null || ! "$PY" -m pip --version >/dev/null 2>&1; then
        rm -rf .venv
        echo "Python can't make an environment with pip - Debian keeps that in"
        echo "a separate package. Install it, then start menu.sh again:"
        echo "    sudo apt install python3-venv python3-pip python$VER-venv"
        exit 1
    fi
    if ! "$PY" -m pip install -q -r requirements.txt; then
        rm -rf .venv
        echo "could not install mpremote / mpy-cross - internet connection?"
        exit 1
    fi
    echo "done"
fi

clear
while true; do
    echo " =========================================================="
    echo "  A-NIX tools"
    "$PY" anix.py status
    echo " =========================================================="
    echo
    echo "  USB (close the console first)"
    echo "    1  Install / update A-NIX     (compiled .mpy - normal)"
    echo "    2  Install / update A-NIX     (plain .py - to debug)"
    echo "    3  Copy source/root to /root  (.py compiled to .mpy)"
    echo "    4  Backup the board           (to dump/)"
    echo
    echo "  Firmware"
    echo "    5  Install MicroPython        (.uf2 from firmware/)"
    echo "    6  NUKE - erase everything, then install MicroPython"
    echo
    echo "  Console"
    echo "    7  Console over USB"
    echo "    8  Console over WiFi (telnet) (Enter = last IP, s = scan)"
    echo "    9  Find the Pico on WiFi"
    echo
    echo "    U  Uninstall dependencies (.venv, packages, dialout)"
    echo "    0  Exit"
    echo
    read -r -n1 -p "  Select: " pick
    echo
    case "$pick" in
        0) exit 0 ;;
        [uU]) clear; uninstall; exit 0 ;;
        [1-9]) clear ;;
        *) clear; continue ;;
    esac
    case "$pick" in
        1) "$PY" anix.py upload ;;
        2) "$PY" anix.py upload_py ;;
        3) "$PY" anix.py root ;;
        4) "$PY" anix.py dump ;;
        5) "$PY" anix.py flash ;;
        6) "$PY" anix.py nuke ;;
        7) "$PY" anix.py connect ;;
        8) "$PY" anix.py telnet ;;
        9) "$PY" anix.py find ;;
    esac
    echo
done
