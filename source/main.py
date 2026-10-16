"""main.py - starts the shell (Raspberry Pi Pico, Pico W, Pico 2,
Pico 2 W).

Runs right after boot.py (MicroPython convention), but only if
boot.py finished without an exception - and not on a soft reset
done from a raw-REPL tool such as Thonny or mpremote. Uses boot.py's
startup_key/status_led globals directly (see boot.py's comment for
why no import is needed for that).

The shell always starts; `exit` restarts it. Ctrl-C at the shell
prompt is the way out to the bare REPL - Thonny and mpremote rely
on that to connect.

Safe mode: press BOOTSEL right after power is applied and hold it
until the banner (held BEFORE power-on, it starts the USB bootloader
instead) -> the shell starts without /etc/profile, /etc/startup,
/etc/crontab and the shell watchdog: no aliases, no @boot jobs,
nothing started by itself. Reboot without BOOTSEL to leave it.

If the shell can't be loaded or crashes (a broken file after an
upload, out of memory), the error goes to /var/log/boot.log and the
board stops at the bare REPL with a message - no restart loop (unless
WATCHDOG=on: boot.py keeps feeding the watchdog at the REPL, so the
board stays there too; safe mode skips the watchdog).

Boot log: every boot is written to /var/log/boot.log (see `dmesg`)
with its number, the RTC time, why the board started (power on,
watchdog, reboot command, soft reset) and the mode. Logging never
stops the boot.
"""

import time
import os

LOG = "/var/log/boot.log"
STATE = "/var/log/state"
MARKER = "/var/log/reboot"

_boot_ms = time.ticks_ms()      # keeps counting through a soft reset

# Blink the LED briefly just to confirm the board is alive.
# For a faster start (about 0.1 s), comment out these three lines.
status_led.on()
time.sleep_ms(100)
status_led.off()


def _boot_number():
    """Counts boots in /var/log/state."""
    try:
        with open(STATE) as f:
            n = int(f.read().split()[0]) + 1
    except (OSError, ValueError, IndexError):
        n = 1
    try:
        with open(STATE, "w") as f:
            f.write("%d 0" % n)
    except OSError:
        pass
    return n


def _log(text):
    try:
        with open(LOG, "a") as f:
            f.write(text + "\n")
    except OSError:
        pass


def _trim_log():
    """Keeps the boot log small (see /lib/logs.py)."""
    try:
        import logs
        logs.trim(LOG)
    except Exception:
        pass


def _reset_cause():
    try:
        with open(MARKER) as f:
            why = f.read().strip()
        os.remove(MARKER)
        if why:
            return why
    except OSError:
        pass
    if time.ticks_diff(_boot_ms, 0) > 3000:
        return "soft reset"
    try:
        import machine
        rc = machine.reset_cause()
        if rc == getattr(machine, "WDT_RESET", -1):
            return "watchdog"
        if rc == getattr(machine, "PWRON_RESET", -1):
            return "power on"
        return "reset %d" % rc
    except Exception:
        return "unknown"


def _now():
    try:
        import machine
        y, mo, d, _wd, h, mi, s, _ss = machine.RTC().datetime()
        return "%04d-%02d-%02d %02d:%02d:%02d" % (y, mo, d, h, mi, s)
    except Exception:
        return "----------"


for _d in ("/var", "/var/log"):
    try:
        os.mkdir(_d)
    except OSError:
        pass
_trim_log()
_safe = bool(startup_key())
_log("#%d %s %s - %s" % (_boot_number(), _now(), _reset_cause(),
                          "shell (SAFE MODE: BOOTSEL)" if _safe else "shell"))



def _fatal(what, e):
    """Logs why the shell isn't running and says so on the console."""
    try:
        import io
        import sys
        buf = io.StringIO()
        sys.print_exception(e, buf)
        text = buf.getvalue().rstrip()
    except Exception:
        text = repr(e)
    _log("   %s:" % what)
    for ln in text.split("\n"):
        _log("   " + ln)
    print("\nA-NIX: %s - details in /var/log/boot.log" % what)
    print(text)
    print("This is the bare MicroPython REPL. Fix the broken file,")
    print("then reset the board. Safe mode: hold BOOTSEL at start.")


try:
    import shell
except Exception as e:
    _fatal("the shell could not be loaded", e)
else:
    shell.SAFE = _safe
    shell.BOOT_WDT = (wdt, wdt_timer)    # boot.py's watchdog, for lib/watchdog.py
    if _safe:
        shell.NOTICE = ("SAFE MODE (BOOTSEL held): skipped /etc/profile, /etc/startup,\n"
                        "/etc/crontab and the watchdog. Reboot without BOOTSEL to leave it.")
    try:
        while True:
            shell.run()
    except KeyboardInterrupt:
        pass                            # Ctrl-C at the prompt: the bare REPL, on purpose
    except Exception as e:
        _fatal("the shell crashed", e)
