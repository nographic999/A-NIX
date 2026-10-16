"""ps - what the board is doing right now.

Shows uptime, CPU, memory, flash, what runs on each core (the shell,
telnetd and httpd on core 0; on core 1 the background job, the
scheduler with each task, or your own program, and how long it has
run), WiFi, Bluetooth,
the watchdog, open UART/SPI buses and configured pins. Read-only:
it changes nothing.
"""

import gc
import os
import sys
import time
import shell


def _uptime():
    s = shell.uptime_ms() // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    text = "%dh %02dm %02ds" % (h, m, s)
    return ("%dd " % d + text) if d else text


def _row(name, value):
    shell._out("%-10s %s" % (name, value))


def run(args, cwd):
    try:
        board = os.uname().machine
    except AttributeError:
        board = "unknown board"
    _row("A-NIX", "%s on %s" % (shell.VERSION, board))
    _row("uptime", _uptime() + " since power-on")
    try:
        import machine
        _row("cpu", "%d MHz" % (machine.freq() // 1000000))
    except Exception:
        pass

    gc.collect()
    free = gc.mem_free()
    total = free + gc.mem_alloc()
    _row("memory", "%d KB free of %d KB" % (free // 1024, total // 1024))
    try:
        st = os.statvfs("/")
        _row("flash", "%d KB free of %d KB" % (st[0] * st[3] // 1024, st[0] * st[2] // 1024))
    except OSError:
        pass

    # only modules already loaded can be running - don't import (RAM)
    mods = sys.modules
    core0 = "shell (cwd %s)" % cwd
    if "telnetsrv" in mods and mods["telnetsrv"].running():
        core0 += ", telnetd"
    if "server" in mods and mods["server"].is_running():
        core0 += ", httpd"
    _row("core 0", core0)
    core1 = []
    if "jobctl" in mods and mods["jobctl"].running():
        j = mods["jobctl"].job
        secs = time.ticks_diff(time.ticks_ms(), j["started"]) // 1000
        core1.append("background job [%d] %ds: %s" % (j["n"], secs, j["cmd"]))
    if "tasksched" in mods and mods["tasksched"].running():
        t = mods["tasksched"]
        core1.append("task scheduler, %d task(s):" % t.count())
        for k in sorted(t._tasks):
            task = t._tasks[k]
            if task["state"] in ("starting", "running"):
                secs = time.ticks_diff(time.ticks_ms(), task["started"]) // 1000
                core1.append("  (%d) %ds: %s %s" % (k, secs, task["name"], " ".join(task["args"])))
    if not core1 and "core1" in mods and mods["core1"].busy():
        core1.append(mods["core1"].busy())  # your own program
    if not core1:
        core1 = ["idle"]
    _row("core 1", core1[0])
    for line in core1[1:]:
        _row("", line)

    try:
        import net
        if net.available():
            _row("wifi", net.status())
    except ImportError:
        pass
    if "telnetsrv" in mods:
        telnetd = mods["telnetsrv"]
        if telnetd.running():
            who = telnetd.client_address()
            _row("telnet", "port %d, %s" % (telnetd.port(),
                 ("%s connected" % who[0]) if who else "no client"))
    try:
        import crond as cron
        if cron.jobs:
            _row("cron", "%d job(s), %s" % (len(cron.jobs), "on" if cron.enabled else "off"))
    except ImportError:
        pass
    if shell._ble is not None:
        try:
            _row("bluetooth", "on" if shell._ble.active() else "off")
        except Exception:
            pass
    wd = sys.modules.get("watchdog")
    if wd is not None and wd.running():
        _row("watchdog", "shell watchdog (fed automatically)")
    else:
        _row("watchdog", "running - must be fed" if shell._wdt is not None else "off")

    buses = ["UART%d" % b for b in sorted(shell._uarts)]
    buses += ["SPI%d" % b for b in sorted(shell._spis)]
    _row("buses", ", ".join(buses) if buses else "none open")
    n = len(shell._pins) + len(shell._adcs) + len(shell._pwms)
    _row("pins", ("%d configured (see pins)" % n) if n else "none configured")
