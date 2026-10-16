"""anix.py - A-NIX board tools: the program behind menu.sh and menu.bat.

Start the menu, or run a command directly (python = the Python of
.venv or python/):

  python anix.py upload        compile source/ to .mpy (temp folder),
                               remove old copies, upload, restart the board
  python anix.py upload_py     upload source/ as plain .py, restart the board
  python anix.py root          board /root := source/root, .py compiled to .mpy
  python anix.py root_py       the same, .py copied as they are
  python anix.py dump          copy the whole board into dump/
  python anix.py flash [f]     write firmware .uf2 from firmware/ (newest, never nuke)
  python anix.py nuke          ERASE everything, reinstall firmware
  python anix.py connect       console on the Pico's USB serial port
  python anix.py find [net]    list the devices on the WiFi network,
                               mark the Raspberry Pi ones
  python anix.py telnet [ip]   console by telnet (asks for the IP;
                               Enter = the last one, s = scan)
  python anix.py scantelnet [net]  find, then telnet to the Pi found
  python anix.py status        one line: where the Pico is (for the menu)

find scans the computer's own network (x.x.x.1-254), or the one given
as net, e.g. 192.168.1. find and telnet don't use the USB port.
Needs mpremote and mpy-cross==1.29.0.post2 (mpy-cross must match the
board's firmware version) - if one is missing, anix.py offers to
install it. The USB port must be free: close the console first. Works
with WATCHDOG=on too (boot.py keeps feeding it during uploads).
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "source")
DUMP = os.path.join(HERE, "dump")
FIRMWARE = os.path.join(HERE, "firmware")      # the .uf2 files (firmware and nuke)


def _uf2_files():
    """All .uf2 files in firmware\\ (and, for old setups, next to anix.py)."""
    import glob
    return glob.glob(os.path.join(FIRMWARE, "*.uf2")) + glob.glob(os.path.join(HERE, "*.uf2"))

# files renamed or removed in A-NIX 0.1c: deleted from the board too
OLD = ["lib/cron", "lib/jobs", "lib/tasks", "lib/telnetd", "lib/ed",
       "lib/xmodem", "bin/rx", "bin/sx", "bin/put"]


PORT = []         # the Pico's serial port, once _board() found it


def _need(module, package):
    """Imports module; if it's missing, offers to pip-install package."""
    import importlib
    try:
        importlib.import_module(module)
        return
    except ImportError:
        pass
    print("%s is not installed in this Python." % package)
    try:
        ok = input("install it now (needs internet)? [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:
        ok = False
    if not ok or subprocess.call([sys.executable, "-m", "pip", "install", package]) != 0:
        sys.exit("missing %s - install it with: %s -m pip install %s"
                 % (package, sys.executable, package))


def _pico_ports():
    """Serial ports of Raspberry Pi boards on USB."""
    _need("serial", "mpremote")                 # pyserial comes with mpremote
    from serial.tools import list_ports
    return sorted(p.device for p in list_ports.comports() if p.vid == 0x2E8A)


def _no_pico():
    if _boot_drives():
        sys.exit("the board is in BOOTSEL mode (a USB drive) - install the firmware "
                 "first: menu 5")
    sys.exit("no Pico found on USB - plugged in? (a charge-only cable shows nothing)")


def _terminal(*cmds):
    """The first of several command lines whose program is installed."""
    for cmd in cmds:
        exe = cmd[0]
        if os.path.isfile(exe) or shutil.which(exe):
            return cmd
    return None


def _board():
    """The Pico's serial port, checked to be free - or a clear message why
    the board can't be used now."""
    if PORT:
        return PORT[0]
    _need("mpremote", "mpremote")
    ports = _pico_ports()
    if not ports:
        _no_pico()
    if len(ports) > 1:
        print("several Picos: %s - using %s" % (", ".join(ports), ports[0]))
    import serial
    try:
        serial.Serial(ports[0], **({} if _WINDOWS else {"exclusive": True})).close()
    except serial.SerialException as e:
        if "ermission" in str(e):
            sys.exit("no permission for %s - run: sudo usermod -aG dialout $USER, "
                     "then log out and in again" % ports[0])
        sys.exit("%s is in use - close the console (PuTTY, picocom, Thonny) first, then try again" % ports[0])
    PORT.append(ports[0])
    return ports[0]


def mpremote(*args, cwd=None):
    """Runs mpremote on the Pico's port; returns True if it worked."""
    cmd = [sys.executable, "-m", "mpremote", "connect", _board()] + list(args)
    return subprocess.call(cmd, cwd=cwd) == 0


def _restart():
    """Hard-resets the board so the new files run (the USB link drops
    for a moment - an error from that is normal)."""
    subprocess.call([sys.executable, "-m", "mpremote", "connect", _board(), "reset"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("done - the board restarted. Open the console (menu 7) and run: selftest")


def mpy_cross(src, dst):
    exe = os.environ.get("MPY_CROSS")           # optional: a mpy-cross program
    if not exe:
        _need("mpy_cross", "mpy-cross==1.29.0.post2")
    cmd = [exe] if exe else [sys.executable, "-m", "mpy_cross"]
    return subprocess.call(cmd + ["-o", dst, src]) == 0


def check_source():
    if not os.path.isfile(os.path.join(SOURCE, "lib", "shell.py")):
        sys.exit("no A-NIX in %s (lib\\shell.py missing)" % SOURCE)


def items(folder):
    """Everything in a folder (hidden files too), for one mpremote cp."""
    return sorted(n for n in os.listdir(folder) if n not in ("__pycache__",))


# --- build -----------------------------------------------------------

def build(out):
    """source -> out: lib/ and bin/ .py become .mpy, the rest is copied."""
    compiled = failed = 0
    for name in items(SOURCE):
        src = os.path.join(SOURCE, name)
        if name in ("lib", "bin", "tools") or name.endswith(".zip"):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(out, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, out)
    for d in ("lib", "bin"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
        for name in items(os.path.join(SOURCE, d)):
            src = os.path.join(SOURCE, d, name)
            if os.path.isdir(src):
                continue
            if name.endswith(".py"):
                if mpy_cross(src, os.path.join(out, d, name[:-3] + ".mpy")):
                    compiled += 1
                else:
                    print("FAILED: %s/%s" % (d, name))
                    failed += 1
            else:
                shutil.copy2(src, os.path.join(out, d))
    print("%d compiled to .mpy, %d failed" % (compiled, failed))
    return failed == 0


def remove_old(stems):
    """Deletes stem.py and stem.mpy on the board for every stem."""
    code = """
import os
n = 0
for stem in %r:
    for ext in ('.py', '.mpy'):
        try:
            os.remove('/' + stem + ext)
            n += 1
        except OSError:
            pass
print('removed', n, 'old file(s)')
""" % (stems,)
    return mpremote("exec", code)


def upload_tree(folder):
    return mpremote("fs", "cp", "-r", *items(folder), ":", cwd=folder)


# --- commands --------------------------------------------------------

def cmd_upload():
    check_source()
    _board()                                    # before compiling: fail fast
    tmp = tempfile.mkdtemp(prefix="anix_mpy_")
    try:
        print("compiling %s ..." % SOURCE)
        if not build(tmp):
            sys.exit("build failed - nothing uploaded")
        stems = []
        for d in ("lib", "bin"):
            stems += ["%s/%s" % (d, n[:-4]) for n in os.listdir(os.path.join(tmp, d))
                      if n.endswith(".mpy")]
        print("removing old copies from the board ...")
        if not remove_old(stems + OLD):
            sys.exit("could not reach the board - is a program running on its USB port?")
        print("copying to the board ...")
        if not upload_tree(tmp):
            sys.exit("upload failed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)    # always, whatever happened
    _restart()


def cmd_upload_py():
    check_source()
    stems = []
    for d in ("lib", "bin"):
        stems += ["%s/%s" % (d, n[:-3]) for n in os.listdir(os.path.join(SOURCE, d))
                  if n.endswith(".py")]
    print("removing old copies from the board ...")
    if not remove_old(stems + OLD):
        sys.exit("could not reach the board - is a program running on its USB port?")
    print("copying %s to the board ..." % SOURCE)
    tmp = tempfile.mkdtemp(prefix="anix_py_")
    try:
        for name in items(SOURCE):
            if name in ("tools",) or name.endswith(".zip"):
                continue
            src = os.path.join(SOURCE, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tmp, name),
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(src, tmp)
        if not upload_tree(tmp):
            sys.exit("upload failed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _restart()


def _compile_tree(src, out):
    """Copies folder src to out, with every .py compiled to .mpy (the
    Pico then runs it without compiling - less RAM, no holes in it).
    Returns how many failed."""
    failed = 0
    for name in items(src):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            os.makedirs(os.path.join(out, name), exist_ok=True)
            failed += _compile_tree(s, os.path.join(out, name))
        elif name.endswith(".py"):
            if not mpy_cross(s, os.path.join(out, name[:-3] + ".mpy")):
                print("FAILED: %s" % s)
                failed += 1
        else:
            shutil.copy2(s, out)
    return failed


def cmd_root(plain=False):
    """board /root := source/root - .py programs compiled to .mpy, or
    copied as they are with plain=True (root_py)."""
    local = os.path.join(SOURCE, "root")
    if not os.path.isdir(local):
        sys.exit("no folder %s" % local)
    _board()                                    # fail fast, before compiling
    tmp = None
    if not plain:
        tmp = tempfile.mkdtemp(prefix="anix_root_")
        print("compiling %s ..." % local)
        if _compile_tree(local, tmp):
            shutil.rmtree(tmp, ignore_errors=True)
            sys.exit("compile failed - nothing on the board changed")
        local = tmp
    try:
        _copy_root(local)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _copy_root(local):
    print("cleaning /root on the board ...")
    ok = mpremote("exec", """
import os
def rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rm(p + '/' + n)
            os.rmdir(p)
        else:
            os.remove(p)
        return 1
    except OSError as e:
        print('could not remove', p, e)
        return 0
n = 0
try:
    for name in os.listdir('/root'):
        n += rm('/root/' + name)
except OSError:
    os.mkdir('/root')
print('removed', n, 'item(s)')
""")
    if not ok:
        sys.exit("could not reach the board - is a program running on its USB port?")
    names = items(local)
    if not names:
        print("%s is empty - /root on the board is now empty too" % local)
        return
    print("copying %d item(s) from %s ..." % (len(names), local))
    if not mpremote("fs", "cp", "-r", *names, ":/root/", cwd=local):
        sys.exit("copy failed")
    print("done")


# --- firmware (.uf2) ---------------------------------------------------

_FAMILY = {0xE48BFF56: "RP2040", 0xE48BFF57: "RP2350", 0xE48BFF59: "RP2350",
           0xE48BFF5A: "RP2350 (RISC-V)"}


def _uf2_chip(path):
    """Chip the .uf2 is built for (from its first block), or None."""
    import struct
    with open(path, "rb") as f:
        block = f.read(512)
    if len(block) < 32:
        return None
    magic0, magic1, flags = struct.unpack_from("<III", block, 0)
    if magic0 != 0x0A324655 or magic1 != 0x9E5D5157:
        return None
    family = struct.unpack_from("<I", block, 28)[0] if flags & 0x2000 else None
    return _FAMILY.get(family, "unknown")


def _boot_drives():
    """[(folder, INFO_UF2.TXT text)] for each Pico in BOOTSEL mode: drive
    on Linux mounted drives (/media/USER/RPI-RP2 ...), else drive letters."""
    import glob
    if _WINDOWS:
        roots = ["%s:\\" % c for c in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    else:
        roots = sorted(glob.glob("/media/*/*/") + glob.glob("/run/media/*/*/")
                       + glob.glob("/media/*/"))
    found = []
    for root in roots:
        try:
            with open(os.path.join(root, "INFO_UF2.TXT")) as f:
                found.append((root, f.read()))
        except OSError:
            pass
    return found


def _is_nuke(path):
    return "nuke" in os.path.basename(path).lower()


def _firmware_file(uf2=None):
    """The .uf2 to install: the one given, else the newest firmware in
    firmware\\ (never a flash_nuke file)."""
    if uf2 is None:
        files = sorted((f for f in _uf2_files() if not _is_nuke(f)),
                       key=os.path.getmtime)
        if not files:
            sys.exit("no firmware .uf2 file in %s" % FIRMWARE)
        uf2 = files[-1]
        if len(files) > 1:
            print("several firmware .uf2 files - using the newest; another one: anix.py flash file.uf2")
    if not os.path.isfile(uf2):
        sys.exit("no such file: %s" % uf2)
    if _is_nuke(uf2):
        sys.exit("%s erases the whole flash - use menu 6 (nuke) for that" % os.path.basename(uf2))
    if _uf2_chip(uf2) is None:
        sys.exit("%s is not a .uf2 firmware file" % uf2)
    return uf2


def _wait_drive(seconds=60):
    import time
    for _ in range(seconds):
        drives = _boot_drives()
        if drives:
            if len(drives) > 1:
                sys.exit("several boards in BOOTSEL mode (%s) - keep only one plugged in"
                         % ", ".join(d[0] for d in drives))
            return drives[0]
        time.sleep(1)
    sys.exit("no BOOTSEL drive appeared - unplug the board, hold BOOTSEL, plug it in, try again")


def _get_boot_drive():
    """The board's BOOTSEL drive, asking a running board to switch."""
    drives = _boot_drives()
    if not drives:
        print("asking the board to restart into BOOTSEL mode ...")
        # machine.bootloader() drops the USB connection: an error here is normal
        subprocess.call([sys.executable, "-m", "mpremote", "bootloader"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("waiting for the board's drive (RPI-RP2 / RP2350) ...")
        if not _WINDOWS:
            print("(on Linux it must be mounted: open it once in the file manager)")
        print("(if nothing happens: unplug it, hold BOOTSEL, plug it back in)")
    return _wait_drive()


def _write(uf2, drive, check_chip=True):
    folder, info = drive
    board_chip = "RP2350" if "RP2350" in info else "RP2040"
    chip = _uf2_chip(uf2)
    if check_chip and not chip.startswith(board_chip):
        sys.exit("%s is for %s but the board is %s - wrong file, not written"
                 % (os.path.basename(uf2), chip, board_chip))
    print("writing %s to %s (%s) ..." % (os.path.basename(uf2), folder, board_chip))
    shutil.copyfile(uf2, os.path.join(folder, os.path.basename(uf2)))
    try:
        os.sync()                               # Linux: write it out before it reboots
    except AttributeError:
        pass
    return folder


def cmd_flash(uf2=None):
    uf2 = _firmware_file(uf2)
    print("firmware: %s (%s, %d KB)" % (os.path.basename(uf2), _uf2_chip(uf2),
                                        os.path.getsize(uf2) // 1024))
    _write(uf2, _get_boot_drive())
    print("done - the board restarts by itself with the new firmware")
    print("(your files in flash stay; check with: selftest)")


def cmd_nuke():
    """Erases the WHOLE flash (firmware and every file), then installs
    the firmware again, so the board ends up like new."""
    import time
    nukes = sorted((f for f in _uf2_files() if _is_nuke(f)),
                   key=os.path.getmtime)
    if not nukes:
        sys.exit("no flash_nuke .uf2 in %s (a file with 'nuke' in its name)" % FIRMWARE)
    nuke = nukes[-1]
    firmware = _firmware_file()                 # checked BEFORE erasing anything
    print("This ERASES EVERYTHING on the board: MicroPython, A-NIX, /root,")
    print("settings, logs. Then it installs %s again." % os.path.basename(firmware))
    print("Make a backup first if you need anything (menu 4, dump).")
    if "--yes" not in sys.argv:                 # the GUI asks before it starts us
        try:
            ok = input("type YES to continue: ").strip() == "YES"
        except EOFError:
            ok = False
        if not ok:
            sys.exit("cancelled - nothing changed")
    drive = _get_boot_drive()
    _write(nuke, drive, check_chip=False)       # universal: any chip
    print("erasing ... (the drive disappears and comes back when done)")
    for _ in range(30):                         # wait for the old drive to go
        time.sleep(1)
        if not _boot_drives():
            break
    drive = _wait_drive(90)
    print("flash erased")
    _write(firmware, drive)
    print("done - the board is like new: MicroPython only, no A-NIX")
    print("next: menu 1 (A-NIX), menu 3 (your /root), then menu 7 (console)")


def cmd_connect():
    """Opens a console on the Pico's serial port: on Linux putty,
    picocom or else mpremote's own terminal (Ctrl-] leaves); with
    menu.bat the putty.exe next to this script."""
    ports = _pico_ports()
    if not ports:
        _no_pico()
    if len(ports) > 1:
        print("several Picos: %s - using %s" % (", ".join(ports), ports[0]))
    port = ports[0]
    if _WINDOWS:
        putty = os.path.join(HERE, "putty.exe")
        if not os.path.isfile(putty):
            sys.exit("the Pico is on %s - but there is no putty.exe in %s" % (port, HERE))
        print("opening PuTTY on %s" % port)
        subprocess.Popen([putty, "-serial", port, "-sercfg", "115200,8,n,1,N"])
        return
    if shutil.which("putty"):
        print("opening PuTTY on %s" % port)
        subprocess.Popen(["putty", "-serial", port, "-sercfg", "115200,8,n,1,N"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    cmd = _terminal(["picocom", "-q", "-b", "115200", port]) or \
        [sys.executable, "-m", "mpremote", "connect", port, "repl"]
    print("console on %s - leave with %s" % (port, "Ctrl-A Ctrl-X" if cmd[0] == "picocom"
                                                 else "Ctrl-]"))
    subprocess.call(cmd)


def cmd_dump():
    os.makedirs(DUMP, exist_ok=True)
    print("copying the whole board to %s ..." % DUMP)
    if not mpremote("fs", "cp", "-r", ":.", DUMP + os.sep):
        sys.exit("dump failed - could not reach the board")
    print("done")


# --- WiFi: find the board, telnet --------------------------------------

# MAC prefixes (OUI) of Raspberry Pi Ltd / Raspberry Pi Trading
PI_PREFIXES = ("28:cd:c1", "2c:cf:67", "b8:27:eb", "d8:3a:dd", "dc:a6:32", "e4:5f:01")
_WINDOWS = sys.platform.startswith("win")


def _my_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))      # no packet is sent - just picks the interface
        return s.getsockname()[0]
    finally:
        s.close()


def _ping(ip):
    if _WINDOWS:
        cmd = ["ping", "-n", "1", "-w", "500", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    flags = 0x08000000 if _WINDOWS else 0           # CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           creationflags=flags, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return False
    out = r.stdout.decode(errors="ignore").lower()
    # some ping versions answer "Destination host unreachable" with exit code 0
    return r.returncode == 0 and "unreachable" not in out


def _arp_table():
    """{ip: mac} from the computer's ARP cache (ip neigh on Linux, else arp -a)."""
    import re
    table = {}
    if not _WINDOWS:
        try:
            out = subprocess.run(["ip", "neigh"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL).stdout.decode(errors="ignore")
            for m in re.finditer(r"^(\d+\.\d+\.\d+\.\d+) .*?lladdr ([0-9a-f:]{17})", out, re.M):
                table[m.group(1)] = m.group(2).lower()
            return table
        except OSError:
            pass
    try:
        out = subprocess.run(["arp", "-a"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL).stdout.decode(errors="ignore")
    except OSError:
        return {}
    for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\D+?([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})", out):
        table[m.group(1)] = m.group(2).lower().replace("-", ":")
    return table


def _port_open(ip, port):
    import socket
    try:
        with socket.create_connection((ip, port), timeout=0.5):
            return True
    except OSError:
        return False


def _name_of(ip):
    import socket
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""


def _scan(base=None):
    """Pings x.x.x.1-254, reads the ARP table; prints a table and
    returns [(ip, mac)]. Port 23 is NOT tested: a test connection to
    the board's telnetd keeps it busy and the next real telnet client
    gets no answer - the Pi is found by its MAC address instead."""
    import ipaddress
    from concurrent.futures import ThreadPoolExecutor
    base = (base or _my_ip().rsplit(".", 1)[0]).rstrip(".")
    net = ipaddress.ip_network(base + ".0/24")
    ips = [str(h) for h in net.hosts()]
    print("scanning %s (%d addresses) ..." % (net, len(ips)))
    with ThreadPoolExecutor(64) as pool:
        alive = [ip for ip, ok in zip(ips, pool.map(_ping, ips)) if ok]
    arp = _arp_table()
    # devices that don't answer ping can still be in the ARP table
    found = sorted(set(alive) | {ip for ip in arp
                                 if ipaddress.ip_address(ip) in net and not ip.endswith(".255")},
                   key=lambda ip: int(ip.rsplit(".", 1)[1]))

    def info(ip):
        return ip, _name_of(ip), _port_open(ip, 80)

    with ThreadPoolExecutor(32) as pool:
        details = list(pool.map(info, found))
    print()
    print("%-16s %-18s %-5s %s" % ("IP", "MAC", "http", "name"))
    result = []
    pis = 0
    for ip, name, http in details:
        mac = arp.get(ip, "?")
        pi = mac.startswith(PI_PREFIXES)
        pis += pi
        result.append((ip, mac))
        print("%-16s %-18s %-5s %s%s" % (ip, mac, "yes" if http else "-", name,
                                         "   <-- RASPBERRY PI" if pi else ""))
    print()
    print("%d device(s), %d Raspberry Pi" % (len(details), pis))
    if not pis:
        print("no Raspberry Pi found - is it connected (A-NIX: wifi status)?")
    return result


def cmd_find(base=None):
    _scan(base)


def cmd_telnet(ip=None):
    """Opens PuTTY (or telnet) on the board. Asks for the IP (Enter =
    the last one used, kept in .lastip next to this file). No scan
    first: the scan's test connection to port 23 can still be busy on
    the board when PuTTY connects."""
    last_file = os.path.join(HERE, ".lastip")
    last = ""
    try:
        with open(last_file) as f:
            last = f.read().strip()
    except OSError:
        pass
    if not ip:
        prompt = "board IP (%ss = scan the network): " % (
            "Enter = %s, " % last if last else "")
        try:
            ip = input(prompt).strip() or last
        except EOFError:
            ip = last
        if ip.lower() == "s":
            return cmd_scantelnet()
    if not ip:
        sys.exit("no IP given")
    try:
        with open(last_file, "w") as f:
            f.write(ip)
    except OSError:
        pass
    putty = os.path.join(HERE, "putty.exe") if _WINDOWS else shutil.which("putty")
    if putty and os.path.isfile(putty):
        print("opening PuTTY: telnet %s:23" % ip)
        subprocess.Popen([putty, "-telnet", ip, "-P", "23"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if not _WINDOWS and shutil.which("telnet"):
        print("telnet %s - leave with Ctrl-], then: quit" % ip)
        subprocess.call(["telnet", ip, "23"])
        return
    sys.exit("no PuTTY or telnet found - connect by hand: telnet %s 23 "
             "(Debian: sudo apt install putty or telnet)" % ip)


def cmd_scantelnet(base=None):
    """Scans the network, picks the Raspberry Pi (asks if several),
    then opens PuTTY by telnet on it."""
    devices = _scan(base)
    print()
    pis = [ip for ip, mac in devices if mac.startswith(PI_PREFIXES)]
    if not pis:
        print("no Raspberry Pi found - on the board: wifi status")
        return cmd_telnet()                     # ask for the IP instead
    if len(pis) == 1:
        ip = pis[0]
    else:
        for n, p in enumerate(pis, 1):
            print("  %d  %s" % (n, p))
        try:
            pick = input("which one (1-%d, Enter = cancel): " % len(pis)).strip()
        except EOFError:
            pick = ""
        if not pick.isdigit() or not 1 <= int(pick) <= len(pis):
            return
        ip = pis[int(pick) - 1]
    print("found %s" % ip)
    cmd_telnet(ip)


def cmd_status():
    """One line for the menu: where the Pico is right now."""
    try:
        from serial.tools import list_ports
        ports = sorted(p.device for p in list_ports.comports() if p.vid == 0x2E8A)
    except ImportError:
        ports = None
    drives = _boot_drives()
    if ports:
        line = "Pico on USB: %s" % ", ".join(ports)
    elif drives:
        line = "Pico in BOOTSEL mode (%s) - ready for firmware" % drives[0][0]
    elif ports is None:
        line = "mpremote not installed yet - offered on first use"
    else:
        line = "no Pico on USB"
    try:
        with open(os.path.join(HERE, ".lastip")) as f:
            line += "    last WiFi IP: " + f.read().strip()
    except OSError:
        pass
    print("  " + line)


COMMANDS = {"upload": cmd_upload, "upload_py": cmd_upload_py,
            "root": cmd_root, "root_py": lambda: cmd_root(plain=True), "dump": cmd_dump, "flash": cmd_flash,
            "nuke": cmd_nuke, "connect": cmd_connect, "find": cmd_find,
            "telnet": cmd_telnet, "scantelnet": cmd_scantelnet,
            "status": cmd_status}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: anix.py " + " | ".join(COMMANDS) +
                 "   (flash [file.uf2], find/scantelnet [192.168.1], telnet [ip])")
    if sys.argv[1] in ("find", "telnet", "scantelnet"):
        COMMANDS[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "flash":
        cmd_flash(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "--yes" else None)
    else:
        COMMANDS[sys.argv[1]]()
