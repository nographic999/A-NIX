"""uart - configure and use a UART bus (0 or 1). Bus objects live in
shell.py (shared, like pins/adcs/pwms) so they persist across calls.

  uart <bus> init [baud] [tx] [rx]
  uart <bus> send [-crlf|-cr|-lf] <text>
  uart <bus> send -hex <hex bytes>
  uart <bus> recv [timeout_ms] [-hex]

send adds no line ending unless asked: most devices (AT modems,
GPS, other boards) want -crlf. -hex sends raw bytes (`uart 0 send
-hex 01 03 00 00 00 02`). recv prints text, or with -hex every byte
as hex - for binary protocols.
"""

import time
import shell
import machine
import gpio

_ENDINGS = {"-crlf": b"\r\n", "-cr": b"\r", "-lf": b"\n"}


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: uart <bus> init [baud] [tx] [rx]")
        shell._out("       uart <bus> send [-crlf|-cr|-lf] <text>")
        shell._out("       uart <bus> send -hex <hex bytes>")
        shell._out("       uart <bus> recv [timeout_ms] [-hex]")
        return
    try:
        bus = int(args[0])
    except ValueError:
        bus = -1
    if bus not in (0, 1):
        shell._err("bus must be 0 or 1")
        return
    action = args[1].lower()

    if action == "init":
        try:
            baud = int(args[2]) if len(args) > 2 else 9600
        except ValueError:
            shell._err("baud must be a number")
            return
        kwargs = {}
        try:
            pins = [int(a) for a in args[3:5]]
        except ValueError:
            shell._err("tx/rx must be pin numbers")
            return
        for p in pins:
            if not gpio.check(p):
                return
        for name, p in zip(("tx", "rx"), pins):
            kwargs[name] = machine.Pin(p)
        try:
            shell._uarts[bus] = machine.UART(bus, baudrate=baud, **kwargs)
            shell._out("UART%d initialized at %d baud" % (bus, baud))
        except Exception as e:
            shell._err("could not init UART%d" % bus, e)
        return

    u = shell._uarts.get(bus)
    if u is None:
        shell._err("UART%d not initialized - run: uart %d init [baud] [tx] [rx]" % (bus, bus))
        return

    if action == "send":
        rest = args[2:]
        ending = b""
        if rest and rest[0].lower() == "-hex":
            try:
                data = bytes.fromhex("".join(rest[1:]))
            except ValueError:
                shell._err("bytes must be hex, e.g. 01 03 FF")
                return
        else:
            if rest and rest[0].lower() in _ENDINGS:
                ending = _ENDINGS[rest[0].lower()]
                rest = rest[1:]
            data = " ".join(rest).encode() + ending
        if not data:
            shell._out("usage: uart <bus> send [-crlf|-cr|-lf|-hex] <text>")
            return
        try:
            u.write(data)
            shell._out("sent %d byte(s)" % len(data))
        except Exception as e:
            shell._err("could not write to UART%d" % bus, e)
        return

    if action == "recv":
        rest = [a.lower() for a in args[2:]]
        as_hex = "-hex" in rest
        rest = [a for a in rest if a != "-hex"]
        try:
            timeout_ms = int(rest[0]) if rest else 1000
        except ValueError:
            shell._err("timeout_ms must be a number")
            return
        start = time.ticks_ms()
        data = b""
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms and len(data) < 4096:
            if u.any():
                chunk = u.read()
                if chunk:
                    data += chunk
            else:
                time.sleep_ms(10)
        if not data:
            shell._out("(no data received)")
            shell._set_status(1)
        elif as_hex:
            shell._out(" ".join("%02X" % b for b in data))
        else:
            shell._out(data.decode("utf-8", "replace"))
        return

    shell._err("unknown action - %s" % action)
