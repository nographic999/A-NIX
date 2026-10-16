"""dmesg - show the boot log.

  dmesg        every logged boot: number, RTC time, why the board
               started, and the mode (shell, or safe mode - BOOTSEL)
  dmesg -c     clear the log

main.py writes /var/log/boot.log (kept under 16 KB). The
RTC has no battery, so after a power cut times start again from the
firmware's default date unless `date` or `date ntp` set them.
"""

import os
import shell

LOG = "/var/log/boot.log"
STATE = "/var/log/state"


def run(args, cwd):
    if args and args[0] == "-c":
        for path in (LOG, STATE):
            try:
                os.remove(path)
            except OSError:
                pass
        shell._out("boot log cleared")
        return
    color = shell._colors()
    try:
        with open(LOG) as f:
            for line in f:
                shell._write(_paint(line) if color else line)
    except OSError:
        shell._out("boot log is empty")


def _paint(line):
    """#12 2026-10-10 20:01:02 power on - shell: number bold, time
    green, a watchdog/unknown start red, safe mode yellow; the
    indented lines (why the shell couldn't start) red."""
    c = shell._c
    text = line.rstrip("\n")
    if not text.startswith("#"):
        return c(shell.RED, text) + "\n" if text.strip() else line
    parts = text.split(" ", 3)
    if len(parts) < 4:
        return line
    num, day, clock, rest = parts
    cause, sep, mode = rest.rpartition(" - ")
    if not sep:
        cause, mode = rest, ""
    bad = cause.startswith("watchdog") or cause.startswith("reset") or cause == "unknown"
    cause = c(shell.RED_BOLD, cause) if bad else cause
    if "SAFE" in mode:
        mode = c(shell.YELLOW, mode)
    return "%s %s %s%s%s\n" % (c(shell.BOLD, num), c(shell.GREEN, day + " " + clock),
                                cause, sep, mode)
