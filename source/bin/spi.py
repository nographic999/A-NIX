"""spi - configure and use an SPI bus (0 or 1). The bus lives in
shell.py (shared, like pins/uarts) so a sequence of commands can use
it.

  spi <bus> init [baud] [sck] [mosi] [miso] [cs]
  spi <bus> xfer <hex bytes>    full-duplex: send, show what came back
  spi <bus> write <hex bytes>
  spi <bus> read <n>            clocks out n zero bytes, shows the reply

Defaults: 1000000 baud, the bus's default pins (SPI0: SCK 18, MOSI
19, MISO 16; SPI1: SCK 10, MOSI 11, MISO 12), SPI mode 0. With a cs
pin, chip select is pulled low around every xfer/write/read and
high again afterwards - most SPI devices need that. Without one,
drive CS yourself with `out`. Hex can be written together or with
spaces: DEADBEEF or DE AD BE EF.
"""

import shell
import machine
import gpio

_MAX_READ = 1024


def _parse_hex(words):
    try:
        return bytes.fromhex("".join(words))
    except ValueError:
        return None


def _usage():
    shell._out("usage: spi <bus> init [baud] [sck] [mosi] [miso] [cs]")
    shell._out("       spi <bus> xfer|write <hex bytes>")
    shell._out("       spi <bus> read <n>")


def run(args, cwd):
    if len(args) < 2:
        _usage()
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
            baud = int(args[2]) if len(args) > 2 else 1000000
            pins = [int(a) for a in args[3:7]]
        except ValueError:
            shell._err("baud and pins must be numbers")
            return
        for p in pins:
            if not gpio.check(p):
                return
        kwargs = {}
        for name, value in zip(("sck", "mosi", "miso"), pins[:3]):
            kwargs[name] = machine.Pin(value)
        cs = None
        try:
            if len(pins) > 3:
                gpio.release(pins[3], None)
                cs = machine.Pin(pins[3], machine.Pin.OUT, value=1)
            shell._spis[bus] = (machine.SPI(bus, baudrate=baud, **kwargs), cs)
            shell._out("SPI%d initialized at %d baud%s" %
                        (bus, baud, (", CS on GPIO%d" % pins[3]) if cs else ""))
        except Exception as e:
            shell._err("could not init SPI%d" % bus, e)
        return

    entry = shell._spis.get(bus)
    if entry is None:
        shell._err("SPI%d not initialized - run: spi %d init [baud] [sck] [mosi] [miso] [cs]" % (bus, bus))
        return
    s, cs = entry

    if action in ("xfer", "write"):
        if len(args) < 3:
            _usage()
            return
        out_bytes = _parse_hex(args[2:])
        if not out_bytes:
            shell._err("bytes must be hex, e.g. DEADBEEF")
            return
    elif action == "read":
        try:
            n = int(args[2]) if len(args) > 2 else 0
        except ValueError:
            n = 0
        if not 1 <= n <= _MAX_READ:
            shell._err("n must be 1-%d" % _MAX_READ)
            return
    else:
        shell._err("unknown action - %s" % action)
        return

    if cs is not None:
        cs.value(0)
    try:
        if action == "xfer":
            # SPI is full-duplex: every byte clocked out clocks one in
            in_bytes = bytearray(len(out_bytes))
            s.write_readinto(out_bytes, in_bytes)
            shell._out("received: %s" % " ".join("%02X" % b for b in in_bytes))
        elif action == "write":
            s.write(out_bytes)
            shell._out("wrote %d byte(s)" % len(out_bytes))
        else:
            data = s.read(n)
            shell._out("received: %s" % " ".join("%02X" % b for b in data))
    except Exception as e:
        shell._err("SPI %s failed on bus %d" % (action, bus), e)
    finally:
        if cs is not None:
            cs.value(1)
