"""i2c - scan an I2C bus and talk to devices on it.

  i2c scan [sda scl]                  list device addresses
  i2c read <addr> <reg|-> [n]         read n bytes (default 1)
  i2c write <addr> <reg|-> <hex...>   write bytes

Pins: given to `scan`, otherwise $I2C_SDA / $I2C_SCL (default 4/5).
The bus number is worked out from the pins: SDA must be an even pin
and SCL the next one (4/5, 0/1, 8/9 ... -> bus 0; 2/3, 6/7, 10/11 ...
-> bus 1), the same on all four Pico boards. $I2C_FREQ sets the
clock (default 100000 Hz).

addr and reg can be decimal or hex (0x68, 68h is not accepted). reg
"-" means no register byte: a plain read/write of the device itself.
Data is hex: `i2c write 0x3c 0x00 AE` or `... AE A8 3F`.
"""

import machine
import shell
import gpio


def _num(text):
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def _bus(sda, scl):
    """I2C bus for an SDA/SCL pair, or None if the pair isn't valid."""
    if sda % 2 != 0 or scl != sda + 1 or not 0 <= sda <= 28:
        return None
    return (sda // 2) % 2


def _open(sda, scl):
    if not (gpio.check(sda) and gpio.check(scl)):
        return None
    bus = _bus(sda, scl)
    if bus is None:
        shell._err("SDA must be an even pin and SCL the next one (e.g. 4 5)")
        return None
    freq = shell._setting_int("I2C_FREQ", 100000)
    try:
        return machine.I2C(bus, sda=machine.Pin(sda), scl=machine.Pin(scl), freq=freq)
    except Exception as e:
        shell._err("could not open I2C%d (sda=GPIO%d scl=GPIO%d)" % (bus, sda, scl), e)
        return None


def _env_pins():
    return shell._setting_int("I2C_SDA", 4), shell._setting_int("I2C_SCL", 5)


def _usage():
    shell._out("usage: i2c scan [sda scl]")
    shell._out("       i2c read <addr> <reg|-> [n]")
    shell._out("       i2c write <addr> <reg|-> <hex bytes>")


def run(args, cwd):
    if not args:
        _usage()
        return
    action = args[0].lower()
    try:
        if action == "scan" and len(args) == 3:
            sda, scl = int(args[1]), int(args[2])
        else:
            sda, scl = _env_pins()
    except ValueError:
        shell._err("pins must be numbers")
        return

    if action == "scan":
        i2c = _open(sda, scl)
        if i2c is None:
            return
        try:
            addrs = i2c.scan()
        except Exception as e:
            shell._err("i2c scan failed", e)
            return
        if not addrs:
            shell._out("no I2C devices found (sda=GPIO%d scl=GPIO%d) - pull-ups fitted?" % (sda, scl))
            shell._set_status(1)
            return
        shell._out("found %d device(s) on I2C%d (sda=GPIO%d scl=GPIO%d):" %
                    (len(addrs), _bus(sda, scl), sda, scl))
        for a in addrs:
            shell._out("  0x%02X (%d)" % (a, a))
        return

    if action not in ("read", "write") or len(args) < 3:
        _usage()
        return
    try:
        addr = _num(args[1])
        reg = None if args[2] == "-" else _num(args[2])
    except ValueError:
        shell._err("addr and reg must be numbers, e.g. 0x68")
        return
    if not 0 <= addr <= 127 or (reg is not None and not 0 <= reg <= 255):
        shell._err("addr must be 0-127 and reg 0-255")
        return
    i2c = _open(sda, scl)
    if i2c is None:
        return

    if action == "read":
        try:
            n = int(args[3]) if len(args) > 3 else 1
        except ValueError:
            shell._err("n must be a number")
            return
        if not 1 <= n <= 256:
            shell._err("n must be 1-256")
            return
        try:
            data = i2c.readfrom(addr, n) if reg is None else i2c.readfrom_mem(addr, reg, n)
        except OSError as e:
            shell._err("no answer from 0x%02X" % addr, e)
            return
        shell._out(" ".join("%02X" % b for b in data))
        return

    if len(args) < 4:
        shell._out("usage: i2c write <addr> <reg|-> <hex bytes>")
        return
    try:
        data = bytes.fromhex("".join(args[3:]))
    except ValueError:
        shell._err("bytes must be hex, e.g. AE or AE A8 3F")
        return
    try:
        if reg is None:
            i2c.writeto(addr, data)
        else:
            i2c.writeto_mem(addr, reg, data)
    except OSError as e:
        shell._err("no answer from 0x%02X" % addr, e)
        return
    shell._out("wrote %d byte(s) to 0x%02X" % (len(data), addr))
