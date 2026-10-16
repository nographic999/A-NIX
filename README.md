# A-NIX

A small *NIX-like command shell for the **Raspberry Pi Pico, Pico W,
Pico 2 and Pico 2 W**, written in MicroPython.

## Features

- **Shell:** pipes `|`, `;` `&&` `||`, redirects `>` `>>` `<` `2>` `2>&1`,
  variables, `$(cmd)`, `$((expr))`, aliases, history, Tab completion
- **Scripts:** `if`/`elif`/`else`, `for`, `while`, functions, `goto`,
  arguments `$1..$9`
- **79 commands:** files (`ls cp mv rm find grep sort diff ...`), an
  editor (`edit`), hardware (`out in pwm adc i2c spi uart flash`),
  system (`ps free df dmesg selftest conf cron`)
- **Two cores:** background jobs (`cmd &`) and an async task scheduler
  (`spawn`) on core 1
- **Network (W boards):** `wifi`, `wget`, `curl`, `ping`, `nc` (with
  file transfer), a web panel with a **file browser** (`httpd`), and the
  console over **telnet** (`telnetd`)
- **Colours like Linux:** start-up banner, prompt, `ls`, `tree`, `grep`,
  `diff`, errors, status commands, and nano-style syntax colours in `edit` (`conf COLOR
  off` for a plain terminal)
- **Robust:** BOOTSEL safe mode, boot log, safe file writes, optional
  watchdog, log rotation, low-RAM handling
- Full manual on the board: `man`, or `man <command>`

## Repository layout

```
A-NIX/
  menu.sh           Linux menu: install, copy /root, backup, firmware, console
  menu.bat          the same menu for Windows
  anix.py           the tool behind both menus
  CHANGELOG.md      what is in this version, known issues
  requirements.txt  Python packages for anix.py
  source/           what goes on the board
    boot.py main.py   start-up
    bin/              commands (one file each)
    lib/              the shell and its libraries
    etc/              settings: anix.conf, profile, startup, crontab
    usr/              manual
    root/             your own programs (empty; not in the repository)
  firmware/         MicroPython .uf2 files (not in the repository)
  python/           portable Python, Windows only (not in the repository)
```

## Installing

You need a Pico / Pico W / Pico 2 / Pico 2 W, a USB data cable and a
computer with Linux or Windows.

First, for both: download the MicroPython `.uf2` for your board from
<https://micropython.org/download/> (A-NIX 0.1T is made for **v1.29**)
and put it in `firmware/`. Optionally add `flash_nuke.uf2` (any name
containing "nuke") to be able to erase a board completely.

### Linux (Debian, Ubuntu, Raspberry Pi OS)

1. Install Python's venv and pip (PuTTY is optional):
   ```
   sudo apt install python3-venv python3-pip putty
   ```
2. Start the menu:
   ```
   bash menu.sh
   ```
   The first start sets everything up:
   - makes the folder yours if it was copied as root or from another
     system (asks first), and makes the scripts executable
   - offers to add you to the `dialout` group for the USB port - log
     out and in once after that
   - makes a Python environment in `.venv` with mpremote and mpy-cross
     (needs internet once; rebuilt by itself if it breaks)

   After that, `./menu.sh` is enough.
3. In the menu (its top line shows where the Pico is):
   - `5` install MicroPython - the BOOTSEL drive must be mounted (open
     it once in the file manager)
   - `1` install A-NIX (compiled `.mpy`); the board restarts by itself
   - `3` copy your own programs from `source/root` to the board
     (`.py` compiled to `.mpy` on the way - you keep editing the `.py`)
   - `7` console over USB, then type `selftest`

The console is PuTTY if installed, else picocom, else mpremote's own
terminal (leave with Ctrl-]). Over WiFi (8) it is PuTTY or `telnet`.
By hand: the Pico is `/dev/ttyACM0`, e.g.
`picocom -b 115200 /dev/ttyACM0`.

**Uninstall:** `./menu.sh uninstall` (or `U` in the menu) removes
`.venv`, then asks one by one about the installed packages (putty,
picocom, telnet, python3-pip, python3-venv) and the `dialout` group.
Your files, `firmware/` and the board are not touched.

### Windows

1. **Python** - put a portable Python in `python\` (or edit the paths
   in `menu.bat`). The packages it needs (mpremote, pyserial,
   mpy-cross) are offered for installing the first time they're
   needed, or install them at once:
   ```
   python\python.exe -m pip install -r requirements.txt
   ```
2. **PuTTY** - put `putty.exe` next to `menu.bat`
   (<https://www.chiark.greenend.org.uk/~sgtatham/putty/>).
3. Run **`menu.bat`** and use the same numbers as on Linux: `5`, `1`,
   `3`, then `7` and `selftest`.

### Without the menu

Copy everything in `source/` to the board with any MicroPython tool
(`mpremote fs cp -r source/* :`, Thonny, ...).

## Using it

The board always starts the shell. Programs that should start by
themselves go in `/etc/crontab` as `@boot` lines, e.g.
`@boot wifi -r 5 && telnetd`. **Safe mode:** hold BOOTSEL while the
board starts (press it right after power is applied - held before, it
starts the USB bootloader) - the shell starts without `/etc/profile`,
`/etc/startup`, `/etc/crontab` and the watchdog, so nothing starts by
itself. Settings: `conf` (Wi-Fi, passwords, pins, watchdog...).

The menu, the same in `menu.sh` and `menu.bat`:

| Menu | Does |
|---|---|
| 1 Install A-NIX (.mpy) | compile and upload A-NIX (faster, less RAM), restart the board |
| 2 Install A-NIX (.py) | upload plain source (editable on the board), restart the board |
| 3 Copy /root | board `/root` = `source/root`, with `.py` compiled to `.mpy` (less RAM on the board); `anix.py root_py` copies them as `.py` |
| 4 Backup | copy the whole board to `dump/` |
| 5 Install MicroPython | write the newest firmware from `firmware/` |
| 6 Nuke | erase everything, then install MicroPython again |
| 7 Console over USB | open the console |
| 8 Console over WiFi | telnet to the board: Enter = the last IP, `s` = scan the network for it |
| 9 Find on WiFi | scan the network, mark the Raspberry Pi |

1-6 need the USB port free: close the console (PuTTY, Thonny) first.
8 and 9 use WiFi.

## Status

Version **0.1T** (experimental alpha), tested on a Pico W with MicroPython 1.29. Not yet
tested on real hardware: Pico 2 / Pico 2 W specifics, light/deep sleep,
the watchdog reset path. Core 1 (background jobs, tasks, your own
programs) is kept off the filesystem by A-NIX, but a program's own
file use on core 1 is not - see CHANGELOG.md, known issues.

## License

MIT - see [LICENSE](LICENSE). (c) 2026 NoGraphic999.
MicroPython, PuTTY and Python have their own licenses and are not part of
this repository.
