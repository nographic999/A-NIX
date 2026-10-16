"""sleep - wait, optionally in a low-power mode (battery projects).

  sleep <seconds>       wait normally (Ctrl-C stops it)
  sleep -l <seconds>    light sleep: the chip mostly stops and draws
                        far less current, then everything carries on
                        where it was (RAM, pins, the shell)
  sleep -d <seconds>    deep sleep: lowest power, then the board
                        RESTARTS - boot.py and main.py run again, as
                        after a reset (so the @boot jobs run again)

Light and deep sleep stop the USB connection: the terminal (and a
telnet session) loses the board while it sleeps and may need to
reconnect afterwards. Use them in a script or program on a
battery-powered board, not while working at the console. Ctrl-C
can't interrupt them. WiFi on the W boards is not switched off by
this - `wifi off` first saves much more.
"""

import time
import shell


def run(args, cwd):
    mode = None
    if args and args[0] in ("-l", "-d"):
        mode = args[0]
        args = args[1:]
    if not args:
        shell._out("usage: sleep [-l | -d] <seconds>")
        return
    try:
        seconds = float(args[0])
    except ValueError:
        shell._err("sleep needs a number of seconds")
        return
    if not 0 <= seconds <= 10 ** 7:     # also refuses nan and inf
        shell._err("seconds must be 0 to 10000000")
        return
    if mode and seconds > 4294:         # the chip's sleep timer limit
        shell._err("light/deep sleep lasts at most 4294 s (71 minutes)")
        return
    ms = int(seconds * 1000)
    if mode is None:
        while ms > 0:                   # in steps: the shell watchdog
            step = min(ms, 1000)        # must see it's alive
            time.sleep_ms(step)
            ms -= step
            shell.alive()
        return
    if shell._wdt is not None:
        shell._err("a watchdog is running - light/deep sleep would let it reset the board")
        return
    import machine
    if mode == "-l":
        shell._out("light sleep for %gs - the USB connection pauses" % seconds)
        time.sleep_ms(50)               # let that line reach the terminal
        machine.lightsleep(ms)
        return
    shell._out("deep sleep for %gs - the board restarts afterwards" % seconds)
    try:
        with open("/var/log/reboot", "w") as f:     # noted in the boot log
            f.write("deep sleep %gs" % seconds)
    except OSError:
        pass
    time.sleep_ms(50)
    machine.deepsleep(ms)
