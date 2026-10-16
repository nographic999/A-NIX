"""watchdog - the shell's own watchdog (WATCHDOG=on in /etc/anix.conf).

The hardware watchdog resets the board unless it's fed every 8 s. A
timer feeds it once a second - as a soft callback, which only runs
while the MicroPython VM is alive. So:
  - a lock-up (a driver or the VM stuck in C, a crash that leaves the
    board frozen) stops the feeding: the board resets and the boot log
    says "watchdog"
  - with WATCHDOG_HANG=N it also stops feeding when the shell has shown
    no sign of life for N minutes - no prompt, no command starting, no
    output. A command that runs that long silently counts as stuck, and
    so does an editor or `read` left waiting: use it on unattended
    boards. Long silent commands can call shell.alive().

boot.py already starts the watchdog with a plain feeding timer (it runs
at every start, also after a soft reset from Thonny, mpremote or the PC
menu, so those keep working with WATCHDOG=on). start() takes it over
and replaces that timer with this one. The RP2040/RP2350 watchdog can't
be stopped once started: WATCHDOG=off, then `reboot`. Light and deep
sleep (`sleep -l` / `-d`) are refused while it runs.
"""

import time
import shell

TIMEOUT_MS = 8000

_timer = None
_hang_ms = None


def running():
    return _timer is not None


def hang_minutes():
    return None if _hang_ms is None else _hang_ms // 60000


def _feed(_t):
    if _hang_ms is not None and time.ticks_diff(time.ticks_ms(), shell._beat[0]) > _hang_ms:
        return                          # the shell looks stuck: let it reset
    try:
        shell._wdt.feed()
    except Exception:
        pass


def start(hang=None):
    """Starts it. hang = minutes, or None. Returns "" or the reason it
    couldn't start."""
    global _timer, _hang_ms
    if _timer is not None:
        return ""
    import machine
    boot_wdt, boot_timer = getattr(shell, "BOOT_WDT", (None, None))
    if shell._wdt is not None and shell._wdt is not boot_wdt:
        return "the watchdog was already started with `wdt start` - feed it yourself"
    try:
        hang_ms = int(hang) * 60000 if hang not in (None, "", "none") else None
    except ValueError:
        return "WATCHDOG_HANG must be minutes or none"
    if hang_ms is not None and hang_ms <= 0:
        return "WATCHDOG_HANG must be at least 1 minute"
    _hang_ms = hang_ms
    shell.alive()
    if boot_wdt is not None:
        shell._wdt = boot_wdt           # started by boot.py, already fed
    else:
        try:
            shell._wdt = machine.WDT(timeout=TIMEOUT_MS)
        except Exception as e:
            return "could not start the watchdog: %s" % e
    try:
        try:
            t = machine.Timer(period=1000, mode=machine.Timer.PERIODIC,
                              callback=_feed, hard=False)
        except TypeError:
            t = machine.Timer(period=1000, mode=machine.Timer.PERIODIC, callback=_feed)
    except Exception as e:
        return "watchdog started but its timer failed (%s) - the board will reset" % e
    _timer = t
    if boot_timer is not None:
        try:
            boot_timer.deinit()         # this timer feeds it from now on
        except Exception:
            pass
    return ""
