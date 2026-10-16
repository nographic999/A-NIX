"""uartterm - transparent terminal to a device on a UART.

Every key you type goes to the UART unchanged, and every byte from
the UART goes to your screen unchanged - so the device's own prompt,
menus, line editing and escape codes work as if you were plugged
into it directly. Nothing is added or prefixed.

  Ctrl+]   leaves (the only key not passed through)
  Ctrl+C   goes to the device too - MicroPython's own Ctrl-C
           interrupt is switched off while uartterm runs, and always
           switched back on when it ends

Enter sends a bare CR, like a real serial terminal. Add `crlf` if
the device wants CR+LF (many AT modems and other boards do).

Runs on core 0 only, no background thread - core 1 stays free for
httpd or tasks. Reuses a bus already set up with `uart <bus> init`
(for custom pins), or opens it with the given/default baud.
"""

import sys
import time
import machine
import micropython
import shell

try:
    import select
except ImportError:
    import uselect as select

_ESCAPE = "\x1d"    # Ctrl+]


def run(args, cwd):
    if not args:
        shell._out("usage: uartterm <bus> [baud] [crlf]")
        return
    crlf = "crlf" in [a.lower() for a in args]
    args = [a for a in args if a.lower() != "crlf"]
    try:
        bus = int(args[0])
    except ValueError:
        shell._err("bus must be a number (0 or 1)")
        return

    if bus not in shell._uarts:
        try:
            baud = int(args[1]) if len(args) > 1 else 9600
        except ValueError:
            shell._err("baud must be a number")
            return
        try:
            shell._uarts[bus] = machine.UART(bus, baudrate=baud)
        except Exception as e:
            shell._err("could not init UART%d" % bus, e)
            return

    u = shell._uarts[bus]
    shell._out("UART%d terminal%s - Ctrl+] to leave" % (bus, " (Enter = CR+LF)" if crlf else ""))

    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    screen = getattr(sys.stdout, "buffer", None)

    micropython.kbd_intr(-1)
    try:
        while True:
            busy = False
            if poll.poll(0):
                ch = sys.stdin.read(1)
                if ch == _ESCAPE:
                    break
                if crlf and ch == "\r":
                    u.write(b"\r\n")
                else:
                    u.write(ch.encode())
                busy = True
            n = u.any()
            if n:
                data = u.read(n)
                if data:
                    if screen is not None:
                        screen.write(data)
                    else:
                        sys.stdout.write(data.decode("utf-8", "replace"))
                busy = True
            if not busy:
                time.sleep_ms(2)
    finally:
        micropython.kbd_intr(3)
    shell._out()
    shell._out("uart terminal closed.")
