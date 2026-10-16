"""selftest - check that A-NIX and the board work.

  selftest        run all checks
  selftest -q     only show problems

Checks, without switching any pin: the board and chip, firmware, RAM,
flash, writing a file, the clock, the temperature sensor, the GPIO
register access boot.py uses, every /lib module, the files in /etc
and the manual, and every /bin command (each must load and have a
run() function). On W boards it
also checks the WiFi and Bluetooth modules are present - it doesn't
connect anywhere. $? is 1 if anything failed.
"""

import gc
import os
import time
import shell


class _T:
    def __init__(self, quiet):
        self.quiet = quiet
        self.fails = 0
        self.warns = 0

    def ok(self, name, detail=""):
        if not self.quiet:
            shell._out("  %s    %-22s %s" % (shell._c(shell.GREEN, "ok"), name, detail))

    def warn(self, name, detail):
        self.warns += 1
        shell._out("  %s  %-22s %s" % (shell._c(shell.YELLOW, "WARN"), name, detail))

    def fail(self, name, detail):
        self.fails += 1
        shell._out("  %s  %-22s %s" % (shell._c(shell.RED_BOLD, "FAIL"), name, detail))


def _board(t):
    u = os.uname()
    t.ok("board", u.machine)
    t.ok("firmware", "MicroPython %s" % u.release)
    chip = "RP2040" if "RP2040" in u.machine else ("RP2350" if "RP2350" in u.machine else None)
    if chip is None:
        t.warn("chip", "not an RP2040/RP2350 - A-NIX targets the Pico boards")
    else:
        t.ok("chip", chip)
    return u.machine, chip


def _memory(t):
    gc.collect()
    free = gc.mem_free()
    total = free + gc.mem_alloc()
    detail = "%d KB free of %d KB" % (free // 1024, total // 1024)
    if free < 40 * 1024:
        t.warn("RAM", detail + " - low, big commands (edit, https) may fail")
    else:
        t.ok("RAM", detail)


def _flash(t):
    try:
        st = os.statvfs("/")
        free = st[0] * st[3] // 1024
        total = st[0] * st[2] // 1024
        if free < 32:
            t.warn("flash", "%d KB free of %d KB - nearly full" % (free, total))
        else:
            t.ok("flash", "%d KB free of %d KB" % (free, total))
    except OSError as e:
        t.fail("flash", str(e))
    path = "/selftest.tmp"
    try:
        with open(path, "w") as f:
            f.write("A-NIX selftest\n")
        with open(path) as f:
            good = f.read() == "A-NIX selftest\n"
        os.remove(path)
        if good:
            t.ok("file write/read")
        else:
            t.fail("file write/read", "read back different data")
    except OSError as e:
        t.fail("file write/read", str(e))


def _clock(t):
    try:
        import machine
        a = machine.RTC().datetime()
        time.sleep_ms(1100)
        b = machine.RTC().datetime()
        if a != b:
            t.ok("RTC", "%04d-%02d-%02d %02d:%02d:%02d" % (b[0], b[1], b[2], b[4], b[5], b[6]))
        else:
            t.fail("RTC", "clock is not running")
    except Exception as e:
        t.fail("RTC", str(e))


def _temp(t):
    try:
        import machine
        v = machine.ADC(4).read_u16() * 3.3 / 65535
        c = 27 - (v - 0.706) / 0.001721
        if -20 < c < 90:
            t.ok("temperature", "%.1f C" % c)
        else:
            t.warn("temperature", "%.1f C looks wrong" % c)
    except Exception as e:
        t.fail("temperature", str(e))


def _gpio_regs(t, chip):
    """boot.py's reset_outputs reads the SIO output/enable registers -
    reading them is harmless, this only proves the addresses answer."""
    try:
        import machine
        oe = 0xD0000020 if chip == "RP2040" else 0xD0000030
        machine.mem32[0xD0000010]
        machine.mem32[oe]
        t.ok("GPIO registers", "reset_outputs() addresses readable")
    except Exception as e:
        t.fail("GPIO registers", str(e))


def _wireless(t, board):
    has_w = " W" in board
    try:
        import network
        t.ok("WiFi module", "present")
    except ImportError:
        if has_w:
            t.fail("WiFi module", "missing - flash the W firmware for this board")
        else:
            t.ok("WiFi module", "none (board without WiFi)")
    if has_w:
        if hasattr(os, "dupterm"):
            t.ok("telnet support", "os.dupterm present")
        else:
            t.warn("telnet support", "no os.dupterm - telnetd won't work")
    try:
        import bluetooth
        t.ok("Bluetooth module", "present")
    except ImportError:
        if has_w:
            t.warn("Bluetooth module", "missing - `ble` won't work with this firmware")


def _check_module(t, name):
    try:
        mod = __import__(name)
        # the file that really loaded: shell.py or shell.mpy
        t.ok(getattr(mod, "__file__", "/lib/" + name))
    except Exception as e:
        t.fail("/lib/" + name, str(e))


def _modules(t):
    for name in ("shell", "gpio", "lineedit", "tui", "hexfmt", "crond", "editor",
                 "jobctl", "tasksched", "core1", "script", "logs", "watchdog", "view",
                 "shbuiltin", "subst", "fileops", "tabcomp", "syntax"):
        _check_module(t, name)
    try:
        import network
        for name in ("net", "server", "webfiles", "telnetsrv"):
            _check_module(t, name)
    except ImportError:
        pass


def _files(t):
    """The settings, scripts and manual A-NIX reads - a missing one only
    means defaults (or no manual), so it's a warning."""
    missing = []
    for path in (shell.CONF, shell.PROFILE, shell.STARTUP, "/etc/crontab",
                 shell.MAN_PAGE, shell.LICENSE_PATH):
        try:
            os.stat(path)
        except OSError:
            missing.append(path)
    if missing:
        t.warn("files", "missing: " + ", ".join(missing))
    else:
        t.ok("files", "/etc settings, manual, license")


def _commands(t):
    try:
        names = sorted(n for n in os.listdir("/bin") if n.endswith(".py") or n.endswith(".mpy"))
    except OSError as e:
        t.fail("/bin", str(e))
        return
    bad = []
    for name in names:
        gc.collect()
        try:
            if name.endswith(".mpy"):
                mod = shell._import_file("/bin/" + name)
                ok = callable(getattr(mod, "run", None))
                shell._unload(name[:-4], mod)
                mod = None
                if not ok:
                    bad.append(name + " (no run)")
                continue
            with open("/bin/" + name) as f:
                src = f.read()
            g = {"__name__": "__selftest__"}
            exec(src, g)
            if not callable(g.get("run")):
                bad.append(name + " (no run)")
        except ImportError as e:
            # network/bluetooth commands on boards without them
            if "network" in str(e) or "bluetooth" in str(e):
                continue
            bad.append("%s (%s)" % (name, e))
        except MemoryError:
            bad.append(name + " (out of memory)")
        except Exception as e:
            bad.append("%s (%s)" % (name, e))
        g = None
        src = None
    if bad:
        for b in bad:
            t.fail("command", b)
    else:
        t.ok("/bin commands", "all %d load" % len(names))


def run(args, cwd):
    quiet = "-q" in args
    t = _T(quiet)
    shell._out("A-NIX %s selftest" % shell.VERSION)
    board, chip = _board(t)
    _memory(t)
    _flash(t)
    _clock(t)
    _temp(t)
    if chip:
        _gpio_regs(t, chip)
    _wireless(t, board)
    _modules(t)
    _files(t)
    _commands(t)
    gc.collect()
    if t.fails:
        shell._out(shell._c(shell.RED_BOLD, "%d problem(s), %d warning(s)" % (t.fails, t.warns)))
        shell._set_status(1)
    else:
        shell._out(shell._c(shell.GREEN, "all checks passed%s" % ((", %d warning(s)" % t.warns) if t.warns else "")))
