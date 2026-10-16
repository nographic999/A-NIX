"""reboot - restart the board.

  reboot      full hardware reset, same as pressing RESET or
              power-cycling: everything restarts from scratch.
  reboot -s   soft reset, same as Ctrl-D at the REPL: MicroPython
              restarts and runs boot.py and main.py again, but the
              hardware (RTC time, a running watchdog) keeps going.

Neither returns - this shell session and all its state are gone.
The reason is noted for the boot log (see `dmesg`): on the Pico a
hardware reset is done through the watchdog, so without the note it
would look like a watchdog reset.
"""

import machine
import shell


def _mark(why):
    try:
        with open("/var/log/reboot", "w") as f:
            f.write(why)
    except OSError:
        pass


def run(args, cwd):
    if args and args != ["-s"]:
        shell._out("usage: reboot [-s]")
        return
    if args:
        _mark("reboot -s")
        shell._out("soft rebooting...")
        machine.soft_reset()
    else:
        _mark("reboot")
        shell._out("rebooting...")
        machine.reset()
