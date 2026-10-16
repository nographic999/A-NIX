"""view - a read-only full-screen viewer for files of any size (used by
`man` and `license`).

The file is never loaded: only where each line starts is remembered
(4 bytes per line - the whole manual needs about 5 KB), and each
screen is read from the flash as it is drawn.

    Up/Down, j/k          one line          PgUp/PgDn, b/Space   one page
    Home/End, g/G         start / end       /  search  (n: next match)
    q, Ctrl-X, Esc Esc    quit
"""

import sys

try:
    from array import array
except ImportError:
    array = None

_TILDE = {"1": "HOME", "7": "HOME", "4": "END", "8": "END", "5": "PGUP", "6": "PGDN"}
_LETTERS = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "H": "HOME", "F": "END"}


def _index(f):
    """Start offsets of every line."""
    offs = array("I") if array else []
    pos = 0
    while True:
        line = f.readline()
        if not line:
            break
        offs.append(pos)
        pos += len(line)
    if not len(offs):
        offs.append(0)                  # empty file: one empty line
    return offs, pos


def _readkey(le):
    ch = le._read()
    if ch != "\x1b":
        return ch
    if not le._waiting(50):
        return "ESC"
    ch2 = le._read()
    if ch2 == "\x1b":
        return "ESC"
    if ch2 == "O":
        return _LETTERS.get(le._read())
    if ch2 != "[":
        return None
    seq = ""
    term = le._read()
    while term and term in "0123456789;":
        seq += term
        term = le._read()
    if term in _LETTERS:
        return _LETTERS[term]
    if term == "~":
        return _TILDE.get(seq.split(";")[0])
    return None


def _heading(line):
    """A man page heading: NAME, COMMANDS, LS(1) ... - capitals at the
    start of the line."""
    if not line or not ("A" <= line[0] <= "Z"):
        return False
    for ch in line.split(" (", 1)[0]:     # THE WEB SERVER (httpd)
        if not ("A" <= ch <= "Z" or "0" <= ch <= "9" or ch in " ()-'"):
            return False
    return True


def start(path, start_line=1, title=None, man=False):
    """Shows path (1-based start_line). Returns False if it can't be
    opened. man=True shows the headings bold (COLOR=off: plain)."""
    import lineedit as le
    try:
        f = open(path, "rb")
    except OSError:
        return False
    w = sys.stdout.write
    try:
        offs, size = _index(f)
        total = len(offs)
        cols, rows = le.terminal_size()
        cols = max(20, cols)
        body = max(3, rows - 1)
        top = max(0, min(start_line - 1, total - 1))
        needle = ""
        msg = ""
        name = title or path
        if man:
            import shell
            man = shell.ENV.get("COLOR", "on").lower() != "off"

        def draw():
            out = ["\x1b[?25l\x1b[H"]
            f.seek(offs[top] if top < total else size)
            for r in range(body):
                if top + r < total:
                    line = f.readline().decode("utf-8", "replace").rstrip("\r\n")
                    line = line.replace("\t", "    ")[:cols]
                    if man and _heading(line):
                        line = "\x1b[1m" + line + "\x1b[0m"
                else:
                    line = "~"
                out.append(line + "\x1b[K\r\n")
            end = min(total, top + body)
            pct = 100 if total <= body else end * 100 // total
            status = msg or "%s  lines %d-%d of %d (%d%%)   q quit  / search  n next" % (
                name, top + 1, end, total, pct)
            status = status[:cols - 1]
            status += " " * (cols - 1 - len(status))   # full width (no ljust in MicroPython)
            # \x1b[K while still inverse fills the last column too
            out.append("\x1b[7m" + status + "\x1b[K\x1b[0m")
            w("".join(out))

        def find(start):
            """First line from start on (wrapping) containing needle."""
            low = needle.lower()
            for k in range(total):
                i = (start + k) % total
                f.seek(offs[i])
                if low in f.readline().decode("utf-8", "replace").lower():
                    return i
            return None

        w("\x1b[2J")
        while True:
            draw()
            msg = ""
            key = _readkey(le)
            last = max(0, total - body)
            if key in ("q", "Q", "\x18", "ESC", "\x03", ""):
                break
            elif key in ("DOWN", "j", "\r", "\n"):
                top = min(last, top + 1)
            elif key in ("UP", "k"):
                top = max(0, top - 1)
            elif key in ("PGDN", " ", "f"):
                top = min(last, top + body)
            elif key in ("PGUP", "b"):
                top = max(0, top - body)
            elif key in ("HOME", "g"):
                top = 0
            elif key in ("END", "G"):
                top = last
            elif key == "/":
                w("\x1b[%d;1H\x1b[K/" % rows + "\x1b[?25h")
                try:
                    typed = le.input_line("")
                except (EOFError, KeyboardInterrupt):
                    typed = ""
                if typed:
                    needle = typed
                if needle:
                    hit = find(top + 1)
                    if hit is None:
                        msg = "not found: %s" % needle
                    else:
                        top = hit
            elif key == "n" and needle:
                hit = find(top + 1)
                if hit is None:
                    msg = "not found: %s" % needle
                else:
                    if hit <= top:
                        msg = "search wrapped to the top"
                    top = hit
    finally:
        f.close()
        w("\x1b[?25h\x1b[2J\x1b[H")
    return True
