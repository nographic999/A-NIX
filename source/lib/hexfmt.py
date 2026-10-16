"""hexfmt - the hex dump layout shared by `hexdump` and `flash read`.

    00000000  48 65 6c 6c 6f 2c 20 50  69 63 6f 21 0a 00 00 00  |Hello, Pico!....|

Offset, 16 bytes in two groups of 8, then the same bytes as text
(non-printable ones as "."). A run of identical lines is shown once,
followed by "*", like the classic hexdump -C. On a terminal narrower
than 78 columns it shows 8 bytes per line.

On the screen bytes are coloured by kind, so structure stands out:
    00                    dark grey
    printable text        normal
    space, tab, CR, LF    green
    other control bytes   magenta
    80-FF                 yellow
No colour when the output goes into a file or a pipe, with plain=True,
or with COLOR=off in /etc/anix.conf.
"""

import shell

_RESET = "\x1b[0m"
_GREY = "\x1b[90m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_MAGENTA = "\x1b[35m"
_YELLOW = "\x1b[33m"


def _colors_ok():
    """Colours allowed: straight to the screen and COLOR not off."""
    return shell._colors()


def _paint(cells, color):
    """Joins (text, colour) cells, sending a colour code only where the
    colour changes - far fewer bytes over the serial line than one
    code per byte."""
    if not color:
        return "".join(t for t, _k in cells)
    out = []
    cur = ""
    for t, k in cells:
        if k != cur:
            out.append(k if k else _RESET)
            cur = k
        out.append(t)
    if cur:
        out.append(_RESET)
    return "".join(out)


def _kind(b):
    if b == 0:
        return _GREY
    if b in (9, 10, 13, 32):
        return _GREEN
    if b < 32 or b == 127:
        return _MAGENTA
    if b >= 128:
        return _YELLOW
    return ""


class Dumper:
    def __init__(self, offset=0, plain=False, width=None):
        self.offset = offset
        self.color = not plain and _colors_ok()
        cols = width or shell.TERM_WIDTH
        self.per_line = 16 if cols >= 78 else 8
        self.pending = b""
        self.last = None
        self.starred = False
        self.total = 0

    def _line(self, data):
        n = self.per_line
        half = n // 2
        hexes = []
        text = []
        for i in range(n):
            if i < len(data):
                b = data[i]
                k = _kind(b)
                hexes.append(("%02x" % b, k))
                text.append((chr(b) if 32 <= b < 127 else ".", k))
            else:
                hexes.append(("  ", ""))
            if i < n - 1:
                hexes.append(("  " if i == half - 1 else " ", ""))
        # a gap between two bytes of the same colour takes that colour,
        # so a run like "00 00 00" needs one colour code, not three
        for j in range(1, len(hexes) - 1):
            if hexes[j][0].strip() == "" and hexes[j - 1][1] == hexes[j + 1][1]:
                hexes[j] = (hexes[j][0], hexes[j - 1][1])
        off = "%08x" % self.offset
        bar = "|"
        if self.color:
            off = _CYAN + off + _RESET
            bar = _GREY + "|" + _RESET
        shell._write("%s  %s  %s%s%s\n" % (off, _paint(hexes, self.color), bar,
                                            _paint(text, self.color), bar))

    def feed(self, data):
        if self.pending:
            data = self.pending + data
            self.pending = b""
        n = self.per_line
        i = 0
        while len(data) - i >= n:
            line = data[i:i + n]
            if line == self.last:
                if not self.starred:
                    shell._write("*\n")
                    self.starred = True
            else:
                self._line(line)
                self.last = line
                self.starred = False
            self.offset += n
            self.total += n
            i += n
        self.pending = data[i:]

    def end(self):
        if self.pending:
            self._line(self.pending)
            self.offset += len(self.pending)
            self.total += len(self.pending)
            self.pending = b""
        end = "%08x" % self.offset
        if self.color:
            end = _CYAN + end + _RESET
        shell._write("%s  (%d bytes)\n" % (end, self.total))
