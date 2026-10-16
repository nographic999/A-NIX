"""flash - read and write a 25-series SPI NOR flash chip (W25Q32/64/128,
GD25Q, MX25L, ...) wired to an SPI bus.

  flash id                          chip maker and size
  flash status                      status registers, write protection
  flash read <addr> [n]             hex dump (default 256 bytes)
  flash save <addr> <n> <file>      copy flash -> file
  flash load [-e] <file> <addr>     copy file -> flash, then verify
  flash write [-e] <addr> <hex...>  write a few bytes, then verify
  flash erase <addr> [4k|32k|64k]   erase one block (default 4k)
  flash erase all                   erase the whole chip (asks first)
  flash unprotect                   clear the write-protect bits

Flash can only change bits from 1 to 0; erasing sets a whole block
back to FF. `write` and `load` check the area first and refuse if it
isn't erased. With -e they erase what's needed themselves - and keep
everything else in the touched 4 KB sectors (read, merge, erase,
rewrite), so nothing outside your data is lost.

addr and n: decimal or 0x hex. Wiring and bus come from /etc/anix.conf:
FLASH_SPI (bus, 0), FLASH_SCK (18), FLASH_MOSI (19), FLASH_MISO (16),
FLASH_CS (17), FLASH_BAUD (8000000). 3-byte addressing: the first
16 MB of bigger chips.
"""

import time
import machine
import shell
import gpio

_MAKERS = {0xEF: "Winbond", 0xC8: "GigaDevice", 0xC2: "Macronix", 0x20: "Micron/XMC",
           0x9D: "ISSI", 0x1F: "Adesto", 0xBF: "SST", 0x01: "Spansion/Cypress",
           0x68: "Boya", 0x5E: "Zbit", 0x0B: "XTX", 0x85: "Puya", 0xA1: "Fudan"}
_ERASE = {"4k": (0x20, 4096), "32k": (0x52, 32768), "64k": (0xD8, 65536)}
_PAGE = 256
_SECTOR = 4096


def _num(text):
    return int(text, 16) if text.lower().startswith("0x") else int(text)


class _Chip:
    def __init__(self):
        env = shell._setting_int
        bus = env("FLASH_SPI", 0)
        sck = env("FLASH_SCK", 18)
        mosi = env("FLASH_MOSI", 19)
        miso = env("FLASH_MISO", 16)
        cs = env("FLASH_CS", 17)
        baud = env("FLASH_BAUD", 8000000)
        for p in (sck, mosi, miso, cs):
            if not gpio.check(p):
                raise ValueError("reserved pin")
        gpio.release(cs, None)
        self.cs = machine.Pin(cs, machine.Pin.OUT, value=1)
        self.spi = machine.SPI(bus, baudrate=baud, polarity=0, phase=0,
                               sck=machine.Pin(sck), mosi=machine.Pin(mosi),
                               miso=machine.Pin(miso))
        self.cmd(b"\xab")               # wake up from deep power-down
        time.sleep_ms(1)
        self.size = None

    def cmd(self, out, nread=0):
        self.cs.value(0)
        try:
            self.spi.write(out)
            return self.spi.read(nread) if nread else b""
        finally:
            self.cs.value(1)

    def jedec(self):
        return self.cmd(b"\x9f", 3)

    def check(self):
        """Chip size from its ID; ValueError if nothing answers."""
        mid = self.jedec()
        if mid in (b"\xff\xff\xff", b"\x00\x00\x00"):
            raise ValueError("no flash chip answers - check wiring, CS pin and 3.3V")
        if 16 <= mid[2] <= 31:
            self.size = 1 << mid[2]
        return mid

    def status(self):
        return self.cmd(b"\x05", 1)[0]

    def wait(self, timeout_ms, dots=False):
        t0 = time.ticks_ms()
        last = t0
        while self.status() & 1:
            now = time.ticks_ms()
            if time.ticks_diff(now, t0) > timeout_ms:
                raise OSError("flash stayed busy for %d s" % (timeout_ms // 1000))
            if dots and time.ticks_diff(now, last) > 1000:
                shell._write(".")
                last = now
            time.sleep_ms(1)

    def write_enable(self):
        self.cmd(b"\x06")
        if not self.status() & 2:
            raise OSError("write enable refused - chip write-protected? try: flash unprotect")

    def read(self, addr, n):
        """Yields the data in chunks of up to 256 bytes."""
        self.cs.value(0)
        try:
            self.spi.write(bytes((0x03, addr >> 16 & 255, addr >> 8 & 255, addr & 255)))
            while n > 0:
                k = min(256, n)
                yield self.spi.read(k)
                n -= k
        finally:
            self.cs.value(1)

    def read_all(self, addr, n):
        return b"".join(self.read(addr, n))

    def program(self, addr, data):
        """Page program, split at 256-byte page edges."""
        i = 0
        while i < len(data):
            room = _PAGE - ((addr + i) % _PAGE)
            chunk = data[i:i + room]
            a = addr + i
            self.write_enable()
            self.cs.value(0)
            try:
                self.spi.write(bytes((0x02, a >> 16 & 255, a >> 8 & 255, a & 255)))
                self.spi.write(chunk)
            finally:
                self.cs.value(1)
            self.wait(50)
            i += len(chunk)

    def erase(self, addr, opcode, timeout_ms=5000):
        self.write_enable()
        self.cmd(bytes((opcode, addr >> 16 & 255, addr >> 8 & 255, addr & 255)))
        self.wait(timeout_ms)


def _fits(old, data):
    """True if every byte can be written over old without an erase
    (flash bits only go 1 -> 0)."""
    return all((o & d) == d for o, d in zip(old, data))


def _range_ok(chip, addr, n):
    if addr < 0 or n < 0:
        shell._err("address and length can't be negative")
        return False
    limit = min(chip.size or (1 << 24), 1 << 24)
    if addr + n > limit:
        shell._err("0x%x..0x%x is past the end (0x%x)" % (addr, addr + n, limit))
        return False
    return True


def _write_region(chip, addr, data, erase):
    """Writes data at addr. Without erase: refuses if the area isn't
    erased. With erase: read-modify-write of every touched 4 KB sector,
    so bytes around the data are kept. Returns True when verified."""
    if not erase:
        old = chip.read_all(addr, len(data))
        if not _fits(old, data):
            for i in range(len(data)):
                if (old[i] & data[i]) != data[i]:
                    break
            shell._err("not erased at 0x%x (has %02x) - erase it first, or use -e"
                       % (addr + i, old[i]))
            return False
        chip.program(addr, data)
    else:
        first = addr - addr % _SECTOR
        end = addr + len(data)
        sec = first
        while sec < end:
            lo = max(addr, sec)
            hi = min(end, sec + _SECTOR)
            part = data[lo - addr:hi - addr]
            old = chip.read_all(lo, len(part))
            if not _fits(old, part):
                if lo == sec and hi == sec + _SECTOR:
                    chip.erase(sec, 0x20)
                    chip.program(sec, part)
                else:
                    buf = bytearray(chip.read_all(sec, _SECTOR))
                    buf[lo - sec:hi - sec] = part
                    chip.erase(sec, 0x20)
                    chip.program(sec, bytes(buf))
            else:
                chip.program(lo, part)
            sec += _SECTOR
    if chip.read_all(addr, len(data)) != bytes(data):
        shell._err("verify failed at 0x%x - data on the chip differs" % addr)
        return False
    return True


_USAGE = """usage: flash id | status | unprotect
       flash read <addr> [n]
       flash save <addr> <n> <file>
       flash load [-e] <file> <addr>
       flash write [-e] <addr> <hex bytes>
       flash erase <addr> [4k|32k|64k]  |  flash erase all"""


def _usage():
    for line in _USAGE.split("\n"):
        shell._out(line)


def run(args, cwd):
    if not args:
        _usage()
        return
    action = args[0].lower()
    rest = args[1:]
    erase_flag = "-e" in rest
    rest = [a for a in rest if a != "-e"]
    try:
        chip = _Chip()
        mid = chip.check()
    except ValueError as e:
        if str(e) != "reserved pin":
            shell._err(str(e))
        return
    except Exception as e:
        shell._err("could not open the SPI bus - check FLASH_* in /etc/anix.conf", e)
        return

    try:
        if action == "id":
            maker = _MAKERS.get(mid[0], "unknown maker")
            size = ("%d MB" % (chip.size >> 20)) if chip.size and chip.size >= 1 << 20 else \
                   (("%d KB" % (chip.size >> 10)) if chip.size else "unknown size")
            shell._out("%s, %s  (JEDEC ID %02X %02X %02X)" % (maker, size, mid[0], mid[1], mid[2]))
            if chip.size and chip.size > 1 << 24:
                shell._out("note: only the first 16 MB are reachable (3-byte addresses)")

        elif action == "status":
            sr1 = chip.status()
            sr2 = chip.cmd(b"\x35", 1)[0]
            shell._out("SR1 %02X  SR2 %02X" % (sr1, sr2))
            shell._out("busy %s, write enabled %s" % (bool(sr1 & 1), bool(sr1 & 2)))
            bp = (sr1 >> 2) & 0x7
            shell._out("protected blocks: %s" % ("none" if bp == 0 else
                                                "yes (BP=%d) - writes will fail, see: flash unprotect" % bp))

        elif action == "unprotect":
            chip.cmd(b"\x06")
            chip.cmd(b"\x01\x00")
            chip.wait(100)
            bp = (chip.status() >> 2) & 0x7
            if bp:
                shell._err("still protected - the chip's /WP pin may be held low")
            else:
                shell._out("write protection cleared")

        elif action == "read":
            addr = _num(rest[0])
            n = _num(rest[1]) if len(rest) > 1 else 256
            if not _range_ok(chip, addr, n):
                return
            import hexfmt
            d = hexfmt.Dumper(addr)
            for chunk in chip.read(addr, n):
                d.feed(chunk)
            d.end()

        elif action == "save":
            if len(rest) < 3:
                shell._out("usage: flash save <addr> <n> <file>")
                return
            addr, n = _num(rest[0]), _num(rest[1])
            if not _range_ok(chip, addr, n):
                return
            path = shell._join(cwd, rest[2])
            done = 0
            with open(path, "wb") as f:
                for chunk in chip.read(addr, n):
                    f.write(chunk)
                    done += len(chunk)
                    if done % 16384 == 0:
                        shell._write("\r%d KB" % (done // 1024))
            shell._write("\r")
            shell._out("saved %d bytes from 0x%x to %s" % (n, addr, path))

        elif action == "load":
            if len(rest) < 2:
                shell._out("usage: flash load [-e] <file> <addr>")
                return
            path = shell._join(cwd, rest[0])
            addr = _num(rest[1])
            import os
            try:
                size = os.stat(path)[6]
            except OSError:
                shell._err("file not found", path)
                return
            if not _range_ok(chip, addr, size):
                return
            done = 0
            with open(path, "rb") as f:
                while True:
                    block = f.read(_SECTOR - (addr + done) % _SECTOR)
                    if not block:
                        break
                    if not _write_region(chip, addr + done, block, erase_flag):
                        return
                    done += len(block)
                    shell._write("\r%d KB / %d KB" % (done // 1024, size // 1024))
            shell._write("\r\x1b[K")
            shell._out("wrote and verified %d bytes at 0x%x" % (size, addr))

        elif action == "write":
            if len(rest) < 2:
                shell._out("usage: flash write [-e] <addr> <hex bytes>")
                return
            addr = _num(rest[0])
            try:
                data = bytes.fromhex("".join(rest[1:]))
            except ValueError:
                shell._err("bytes must be hex, e.g. 48 65 6C 6C 6F")
                return
            if not data or not _range_ok(chip, addr, len(data)):
                return
            if _write_region(chip, addr, data, erase_flag):
                shell._out("wrote and verified %d byte(s) at 0x%x" % (len(data), addr))

        elif action == "erase":
            if not rest:
                shell._out("usage: flash erase <addr> [4k|32k|64k]  |  flash erase all")
                return
            if rest[0].lower() == "all":
                if not shell._ask("erase the WHOLE chip?"):
                    shell._out("cancelled")
                    return
                chip.write_enable()
                chip.cmd(b"\xc7")
                shell._write("erasing (can take minutes)")
                chip.wait(600000, dots=True)
                shell._out()
                shell._out("chip erased")
                return
            addr = _num(rest[0])
            kind = rest[1].lower() if len(rest) > 1 else "4k"
            if kind not in _ERASE:
                shell._err("block size must be 4k, 32k or 64k")
                return
            opcode, size = _ERASE[kind]
            if addr % size:
                shell._err("a %s block starts at a multiple of 0x%x - e.g. 0x%x"
                           % (kind, size, addr - addr % size))
                return
            if not _range_ok(chip, addr, size):
                return
            chip.erase(addr, opcode, 5000)
            shell._out("erased %s at 0x%x" % (kind, addr))

        else:
            shell._err("unknown action - %s (try: flash)" % action)
    except (ValueError, IndexError):
        shell._err("bad number or missing argument - try: flash")
    except OSError as e:
        shell._err("flash", e)
