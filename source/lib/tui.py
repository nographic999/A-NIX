"""tui - small whiptail-style dialog toolkit: bordered boxes drawn as
an overlay on the existing screen (not a full-screen clear - real
whiptail dialogs work the same way, appearing over whatever's
already there rather than taking over the terminal). Four dialog
types: menu (arrow keys + Enter), msgbox (any key to dismiss),
yesno (Left/Right + Enter, or y/n), inputbox (type + Enter).
Imported by the whiptail /bin command - see `man whiptail` for the
CLI, or import this directly from another program for the same
dialogs without going through whiptail's text-argument parsing.

No persistent state between calls (unlike net.py/server.py) - each
dialog function draws, waits for a result, and returns; nothing
here needs to survive to a later, separate command.
"""

import sys

try:
    import select
except ImportError:
    try:
        import uselect as select
    except ImportError:
        select = None


def _env_get(name, default):
    """shell.ENV, imported only when needed - so this module also works
    without the shell (same idea as editor.py's _env_get)."""
    try:
        import shell
        return shell.ENV.get(name, default)
    except Exception:
        return default


def _screen_size():
    """COLUMNS/LINES, refined by asking the terminal its real size if
    it answers - the same technique as editor.py's _detect_screen_size,
    kept as a copy here so this module stays usable on its own."""
    try:
        cols = int(_env_get("COLUMNS", "80"))
    except ValueError:
        cols = 80
    try:
        rows = int(_env_get("LINES", "24"))
    except ValueError:
        rows = 24
    if select is not None:
        try:
            poll = select.poll()
            poll.register(sys.stdin, select.POLLIN)
            sys.stdout.write("\x1b[s\x1b[999;999H\x1b[6n")
            resp = ""
            for _ in range(20):
                if poll.poll(10):
                    ch = sys.stdin.read(1)
                    resp += ch
                    if ch == "R":
                        break
                if len(resp) > 16:
                    break
            sys.stdout.write("\x1b[u")
            if resp.startswith("\x1b[") and resp.endswith("R") and ";" in resp:
                rows_s, cols_s = resp[2:-1].split(";", 1)
                cols, rows = int(cols_s), int(rows_s)
        except Exception:
            pass
    return max(30, cols), max(10, rows)


_out_buf = []


def _w(text):
    """Collects drawing output; _flush() sends it as ONE write with the
    cursor hidden, so redrawing a dialog doesn't flicker over a slow
    serial link (same idea as the edit editor's single-write redraw)."""
    _out_buf.append(text)


def _flush():
    if _out_buf:
        sys.stdout.write("\x1b[?25l" + "".join(_out_buf) + "\x1b[?25h")
        del _out_buf[:]


def _getch():
    """One character - through the prompt's reader when the shell runs,
    so the LF of a CR LF Enter typed at the prompt isn't taken as an
    Enter in the dialog."""
    le = sys.modules.get("lineedit")
    return le._read() if le is not None else sys.stdin.read(1)


def _more(ms):
    """True if another byte arrives within ms."""
    le = sys.modules.get("lineedit")
    if le is not None:
        return le._waiting(ms)
    if select is None:
        return True
    try:
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        return bool(poll.poll(ms))
    except Exception:
        return True


def _readkey():
    """One keystroke - see _readkey_raw. A read that fails (seen once on
    the board right after a background thread started) counts as Esc,
    so the dialog is cancelled instead of crashing the script."""
    _flush()
    try:
        return _readkey_raw()
    except Exception:
        return "ESC"


def _readkey_raw():
    """One keystroke, resolving arrow keys/Home/End/PgUp/PgDn from
    their ANSI escape sequences, like editor.py's _readkey. A bare Esc
    (Cancel) and the start of an arrow key begin with the same byte, so
    this waits up to 50 ms for a second byte: an escape sequence's
    bytes arrive together, a lone Esc sends nothing more."""
    ch = _getch()
    if ch != "\x1b":
        return ch
    if not _more(50):
        return "ESC"
    letters = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
               "H": "HOME", "F": "END"}
    ch2 = _getch()
    if ch2 == "O":                      # application cursor mode
        return letters.get(_getch())
    if ch2 != "[":
        return "ESC"
    seq = ""
    term = _getch()
    while term and term in "0123456789;":
        seq += term
        term = _getch()
    if term in letters:                 # also Shift/Ctrl + key: ESC[1;2A
        return letters[term]
    if term == "~":
        num = seq.split(";")[0]
        return {"1": "HOME", "7": "HOME", "3": "DELETE", "4": "END",
                "8": "END", "5": "PGUP", "6": "PGDN"}.get(num)
    return None


def _pad(text, width):
    return text if len(text) >= width else text + " " * (width - len(text))


def _wrap_text(text, width):
    """Plain greedy word-wrap - MicroPython has no textwrap module.
    A single word longer than width is left as its own (overlong)
    line rather than getting split mid-word."""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w) if cur else w
        if len(candidate) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_box(top, left, height, width, title=""):
    """Plain ASCII border (+/-/|), not Unicode box-drawing - same
    reasoning as tree.py's indent-only listing: not every terminal
    connected to this board can be assumed to render box-drawing
    glyphs correctly, but +/-/| render everywhere."""
    w = _w
    w("\x1b[%d;%dH" % (top, left))
    if title:
        t = " %s " % title
        pad_total = max(0, width - 2 - len(t))
        pad_left = pad_total // 2
        pad_right = pad_total - pad_left
        w("+" + "-" * pad_left + t + "-" * pad_right + "+")
    else:
        w("+" + "-" * (width - 2) + "+")
    for r in range(1, height - 1):
        w("\x1b[%d;%dH" % (top + r, left))
        w("|" + " " * (width - 2) + "|")
    w("\x1b[%d;%dH" % (top + height - 1, left))
    w("+" + "-" * (width - 2) + "+")


def _dialog_geometry(lines, extra_rows, title):
    """Shared sizing/centering math for msgbox/yesno/inputbox - each
    just supplies its wrapped text lines and how many extra rows it
    needs below them (a button row, an input field, etc.)."""
    cols, rows = _screen_size()
    content_width = max([len(l) for l in lines] + [len(title)] + [20])
    width = min(cols - 4, content_width + 6)
    height = min(rows - 2, len(lines) + extra_rows)
    top = max(1, (rows - height) // 2)
    left = max(1, (cols - width) // 2)
    return top, left, height, width


def menu(items, title="", prompt=""):
    """items: a list of (tag, text) pairs. Arrow keys move the
    highlighted row (wrapping at the ends), Enter returns that row's
    tag, Esc or q returns None. Scrolls if there are more items than
    fit on screen."""
    if not items:
        return None
    cols, rows = _screen_size()
    hint = "Up/Down move, Enter select, Esc cancel"
    inner_w = max([len(t) + len(x) + 3 for t, x in items] + [len(prompt), len(title), len(hint) - 2])
    width = min(cols - 4, inner_w + 6)
    prompt_lines = _wrap_text(prompt, width - 4) if prompt else []
    list_height = min(len(items), rows - len(prompt_lines) - 8)
    list_height = max(1, list_height)
    height = min(rows - 2, len(prompt_lines) + list_height + 4 + (1 if prompt else 0))
    top = max(1, (rows - height) // 2)
    left = max(1, (cols - width) // 2)

    sel = 0
    scroll = 0
    while True:
        _draw_box(top, left, height, width, title)
        row = top + 1
        for pl in prompt_lines:
            _w("\x1b[%d;%dH%s" % (row, left + 2, _pad(pl, width - 4)))
            row += 1
        if prompt_lines:
            row += 1

        if sel < scroll:
            scroll = sel
        elif sel >= scroll + list_height:
            scroll = sel - list_height + 1

        for i in range(list_height):
            idx = scroll + i
            _w("\x1b[%d;%dH" % (row + i, left + 2))
            if idx < len(items):
                tag, text = items[idx]
                label = _pad("%-8s %s" % (tag, text), width - 4)[:width - 4]
                if idx == sel:
                    _w("\x1b[7m" + label + "\x1b[0m")
                else:
                    _w(label)
            else:
                _w(" " * (width - 4))

        _w("\x1b[%d;%dH%s" % (top + height - 2, left + 2,
                                             _pad(hint[:width - 4], width - 4)))
        _w("\x1b[%d;%dH" % (top + height, left))

        key = _readkey()
        if key is None:
            continue
        if key == "UP":
            sel = (sel - 1) % len(items)
        elif key == "DOWN":
            sel = (sel + 1) % len(items)
        elif key == "PGUP":
            sel = max(0, sel - list_height)
        elif key == "PGDN":
            sel = min(len(items) - 1, sel + list_height)
        elif key in ("\r", "\n"):
            return items[sel][0]
        elif key in ("ESC", "q", "Q"):
            return None


def msgbox(text, title=""):
    """A message with an OK button; Enter, Esc, space, or q all
    dismiss it the same way - there's only one outcome, so anything
    that isn't further navigation just closes it. Always returns
    None."""
    cols, rows = _screen_size()
    lines = _wrap_text(text, min(cols - 6, 60))
    top, left, height, width = _dialog_geometry(lines, 4, title)

    _draw_box(top, left, height, width, title)
    for i, l in enumerate(lines):
        _w("\x1b[%d;%dH%s" % (top + 1 + i, left + 2, _pad(l, width - 4)))
    button = "< OK >"
    bx = left + max(1, (width - len(button)) // 2)
    _w("\x1b[%d;%dH\x1b[7m%s\x1b[0m" % (top + height - 2, bx, button))
    _w("\x1b[%d;%dH" % (top + height, left))

    while True:
        key = _readkey()
        if key in ("\r", "\n", "ESC", "q", "Q", " "):
            return None


def yesno(text, title=""):
    """Text with Yes/No buttons; Left/Right (or Tab) toggles which
    is highlighted, Enter confirms the highlighted one, y/n jump
    straight to an answer. Esc counts as No - dismissing without an
    explicit choice means "didn't agree", same convention real
    whiptail uses."""
    cols, rows = _screen_size()
    lines = _wrap_text(text, min(cols - 6, 60))
    top, left, height, width = _dialog_geometry(lines, 4, title)

    sel_yes = True
    while True:
        _draw_box(top, left, height, width, title)
        for i, l in enumerate(lines):
            _w("\x1b[%d;%dH%s" % (top + 1 + i, left + 2, _pad(l, width - 4)))
        yes_btn, no_btn = "< Yes >", "< No >"
        gap = "  "
        total = len(yes_btn) + len(no_btn) + len(gap)
        bx = left + max(1, (width - total) // 2)
        _w("\x1b[%d;%dH" % (top + height - 2, bx))
        if sel_yes:
            _w("\x1b[7m" + yes_btn + "\x1b[0m" + gap + no_btn)
        else:
            _w(yes_btn + gap + "\x1b[7m" + no_btn + "\x1b[0m")
        _w("\x1b[%d;%dH" % (top + height, left))

        key = _readkey()
        if key in ("LEFT", "RIGHT", "\t"):
            sel_yes = not sel_yes
        elif key in ("\r", "\n"):
            return sel_yes
        elif key in ("ESC", "q", "Q"):
            return False
        elif key in ("y", "Y"):
            return True
        elif key in ("n", "N"):
            return False


def inputbox(prompt, default="", title=""):
    """Prompt text with an editable field below it, pre-filled with
    default. Enter confirms (returns the current text), Esc cancels
    (returns None). Left/Right/Home/End move within the field."""
    cols, rows = _screen_size()
    lines = _wrap_text(prompt, min(cols - 6, 60))
    field_width = min(cols - 8, 50)
    top, left, height, width = _dialog_geometry(
        lines + [" " * field_width], 5, title)

    buf = list(default)
    cx = len(buf)
    while True:
        _draw_box(top, left, height, width, title)
        for i, l in enumerate(lines):
            _w("\x1b[%d;%dH%s" % (top + 1 + i, left + 2, _pad(l, width - 4)))
        field_row = top + 1 + len(lines)
        text = "".join(buf)
        visible = width - 6
        start = max(0, cx - visible + 1)    # scroll so the cursor stays inside
        _w("\x1b[%d;%dH[%s]" %
                          (field_row, left + 2, _pad(text[start:start + visible], visible)))
        _w("\x1b[%d;%dH" % (field_row, left + 3 + cx - start))

        key = _readkey()
        if key is None:
            continue
        if key in ("\r", "\n"):
            return "".join(buf)
        elif key == "ESC":
            return None
        elif key in ("\x08", "\x7f"):
            if cx > 0:
                del buf[cx - 1]
                cx -= 1
        elif key == "LEFT":
            cx = max(0, cx - 1)
        elif key == "RIGHT":
            cx = min(len(buf), cx + 1)
        elif key == "HOME":
            cx = 0
        elif key == "END":
            cx = len(buf)
        elif key == "DELETE":
            if cx < len(buf):
                del buf[cx]
        elif len(key) == 1 and (32 <= ord(key) <= 126 or ord(key) >= 160) and len(buf) < 200:
            buf.insert(cx, key)
            cx += 1
