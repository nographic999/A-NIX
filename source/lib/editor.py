"""editor - small nano-style full-screen text editor. The command you
type is `edit` (/bin/edit.py, a thin wrapper around this; `ed` is an
alias for it in /etc/profile). Reads raw keystrokes via ANSI/
VT100 escapes; any terminal that understands cursor-position/clear/
reverse-video codes works (PuTTY, mintty, GNOME Terminal, screen).

Keys (^ = Ctrl, full list on ^H inside the editor):
  ^O save    ^X exit    ^B mark    ^K cut     ^Y copy    ^V paste
  ^Z undo    ^W find    ^F go to   ^A all     ^H help    Tab indent

Ctrl+C is never used - it's MicroPython's interrupt key and would
kill the shell. Ctrl+S is avoided too - PuTTY's serial connection
uses it for flow control by default. Ctrl+E also exits (mpremote's
own terminal eats Ctrl+X).

^H is Ctrl+H = byte 0x08. Backspace must therefore send 0x7F
("Control-?"), which is PuTTY's default (Terminal > Keyboard >
Backspace key). If Backspace opens the help screen instead of
deleting, switch that PuTTY setting back to Control-?. ^G also
opens help.
"""

import sys
import os
import gc

try:
    import select
except ImportError:
    try:
        import uselect as select
    except ImportError:
        select = None


def _file_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _env_get(name, default):
    """Reads an env var from the shell's ENV without a hard
    import-time dependency (avoids a circular import - shell.py
    imports this module)."""
    try:
        import shell
        return shell.ENV.get(name, default)
    except Exception:
        return default


def _detect_screen_size(fallback_cols, fallback_rows):
    """Asks the terminal its real size via the standard DSR cursor-
    position query, instead of trusting a possibly-stale COLUMNS/
    LINES guess - that mismatch is what left a dead gap below the
    UI on a terminal window taller than the assumed default. Falls
    back to fallback_cols/fallback_rows, bounded by a short poll
    timeout, if the terminal never answers - this can't hang even on
    a terminal that doesn't support the query at all."""
    if select is None:
        return fallback_cols, fallback_rows
    try:
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        sys.stdout.write("\x1b[s\x1b[999;999H\x1b[6n")  # save cursor, jump past
        resp = ""                                        # any real edge, ask where
        for _ in range(20):                               # it actually landed
            if poll.poll(10):
                ch = sys.stdin.read(1)
                resp += ch
                if ch == "R":
                    break
            if len(resp) > 16:  # malformed/unexpected reply - bail out
                break
        sys.stdout.write("\x1b[u")  # restore cursor
        if resp.startswith("\x1b[") and resp.endswith("R") and ";" in resp:
            rows_s, cols_s = resp[2:-1].split(";", 1)
            return int(cols_s), int(rows_s)
    except Exception:
        pass
    return fallback_cols, fallback_rows


def _screen_size():
    try:
        cols = int(_env_get("COLUMNS", "80"))
    except ValueError:
        cols = 80
    try:
        rows = int(_env_get("LINES", "24"))
    except ValueError:
        rows = 24
    cols, rows = _detect_screen_size(cols, rows)
    return max(20, cols), max(6, rows)


def _pad(text, width):
    """Manual left-justify - MicroPython's str has no .ljust() on
    most builds."""
    return text if len(text) >= width else text + " " * (width - len(text))


def _rjust(text, width):
    return text if len(text) >= width else " " * (width - len(text)) + text


def _gutter_width(line_count):
    return max(3, len(str(max(1, line_count)))) + 1


_HOME_END_ETC = {"1": "HOME", "7": "HOME", "3": "DELETE", "4": "END", "8": "END",
                 "5": "PGUP", "6": "PGDN"}
_LETTER_KEYS = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
                "H": "HOME", "F": "END"}


def _readkey():
    """One keystroke, resolving ANSI escapes to short symbolic
    names: arrows, Home/End, PgUp/Dn, Delete. Terminals disagree on
    Home/End, so every common form is accepted:
      ESC[1~ ESC[4~   PuTTY "Standard", Linux console
      ESC[7~ ESC[8~   rxvt / urxvt
      ESC[H  ESC[F    xterm, PuTTY "SCO"/"xterm R6"
      ESCOH  ESCOF    xterm in application cursor mode
    Keys sent with a modifier (Shift/Ctrl/Alt, e.g. ESC[1;2A) count
    as the plain key - selecting is done with the ^B mark. Anything
    unrecognised comes back as "UNKNOWN:<code>" so the editor can
    show which code the terminal sent instead of silently doing
    nothing."""
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        return ch
    ch2 = sys.stdin.read(1)
    if ch2 == "O":
        term = sys.stdin.read(1)
        return _LETTER_KEYS.get(term) or "UNKNOWN:ESC O " + term
    if ch2 != "[":
        return "UNKNOWN:ESC " + ch2
    seq = ""
    term = sys.stdin.read(1)
    while term in "0123456789;":
        seq += term
        term = sys.stdin.read(1)
    if term in _LETTER_KEYS:
        return _LETTER_KEYS[term]
    if term == "~":
        key = _HOME_END_ETC.get(seq.split(";")[0])
        if key:
            return key
    return "UNKNOWN:ESC [ " + seq + term


def _selection_range(mark, cy, cx):
    """((start_y,start_x),(end_y,end_x)) in document order, or None."""
    if mark is None:
        return None
    my, mx = mark
    return ((my, mx), (cy, cx)) if (my, mx) <= (cy, cx) else ((cy, cx), (my, mx))


def _extract_range(lines, start, end):
    sy, sx = start
    ey, ex = end
    if sy == ey:
        return [lines[sy][sx:ex]]
    result = [lines[sy][sx:]]
    for i in range(sy + 1, ey):
        result.append(lines[i])
    result.append(lines[ey][:ex])
    return result


def _delete_range(lines, start, end):
    sy, sx = start
    ey, ex = end
    if sy == ey:
        lines[sy] = lines[sy][:sx] + lines[sy][ex:]
    else:
        merged = lines[sy][:sx] + lines[ey][ex:]
        del lines[sy:ey + 1]
        lines.insert(sy, merged)
    if not lines:
        lines = [""]
    return lines, sy, sx


def _paste_fragments(lines, cy, cx, frags):
    if len(frags) == 1:
        lines[cy] = lines[cy][:cx] + frags[0] + lines[cy][cx:]
        return lines, cy, cx + len(frags[0])
    tail = lines[cy][cx:]
    lines[cy] = lines[cy][:cx] + frags[0]
    insert_at = cy + 1
    for frag in frags[1:-1]:
        lines.insert(insert_at, frag)
        insert_at += 1
    lines.insert(insert_at, frags[-1] + tail)
    return lines, insert_at, len(frags[-1])


# ---------------------------------------------------------------
# Settings - change these to tune the editor.
# ---------------------------------------------------------------

# Undo (^Z). Every change is kept as one undo step; when a limit is
# hit, the OLDEST step is dropped, so ^Z always reaches back to the
# most recent changes.
#
# UNDO_MAX_STEPS - how many changes ^Z can go back. 0 = undo off.
# UNDO_MAX_KB    - RAM the undo steps may use together. A step only
#                  holds the lines that changed (each line = its
#                  length + about 20 bytes), so typing in one line is
#                  ~50-150 bytes and 8 KB is plenty for 20 normal
#                  steps. Only cutting a big selection is expensive:
#                  that step holds the whole cut text. One step
#                  bigger than the whole limit is still kept on its
#                  own, so the last change can always be undone.
#
# RAM guide: the RP2040 (Pico, Pico W) has roughly 150-180 KB free
# for MicroPython, the RP2350 (Pico 2, Pico 2 W) roughly 400+ KB.
# The file being edited must fit too - the editor refuses files
# bigger than 40% of free RAM. Sensible ranges:
#   RP2040: UNDO_MAX_KB 4-16    RP2350: UNDO_MAX_KB 8-64
# Typing in a row on the same line counts as ONE step.
UNDO_MAX_STEPS = 20
UNDO_MAX_KB = 8

# Tab key inserts spaces up to the next multiple of TAB_SIZE; Enter
# keeps the current line's indentation and adds one TAB_SIZE level
# after a line ending in ":" (Python blocks).
TAB_SIZE = 4

_LINE_OVERHEAD = 20     # rough MicroPython cost of one str object
_STEP_OVERHEAD = 40     # rough cost of one undo step's bookkeeping


_MOVE_KEYS = ("UP", "DOWN", "LEFT", "RIGHT", "HOME", "END", "PGUP", "PGDN")
_SELECTION_AWARE_KEYS = _MOVE_KEYS + ("DELETE", "\x7f", "\x0b", "\x19", "\x01", "\x02")

_K_SAVE = "\x0f"        # ^O
_K_EXIT = ("\x18", "\x05")  # ^X (^E alias)
_K_HELP = ("\x08", "\x07")  # ^H (^G alias)
_K_MARK = "\x02"        # ^B
_K_ALL = "\x01"         # ^A
_K_CUT = "\x0b"         # ^K
_K_COPY = "\x19"        # ^Y
_K_PASTE = "\x16"       # ^V
_K_UNDO = "\x1a"        # ^Z
_K_FIND = "\x17"        # ^W
_K_GOTO = "\x06"        # ^F
_K_BACKSPACE = "\x7f"


def _is_char(key):
    # printable ASCII and any non-ASCII letter (ą, č, €...)
    return key is not None and len(key) == 1 and (32 <= ord(key) <= 126 or ord(key) >= 160)


def _is_insert(key):
    """Keys that put text in - over a selection, they replace it."""
    return _is_char(key) or key in ("\t", "\r", "\n", _K_PASTE)


def _may_modify(key):
    return _is_insert(key) or key in (_K_BACKSPACE, "DELETE", _K_CUT)


def _apply_key(key, lines, cy, cx, clip, dirty, mark, text_rows, auto_indent):
    """Editing logic, separate from drawing/reading so it's testable
    on its own. action is None, or "save"/"exit"/"help"/"goto"/
    "find"/"undo"/"selectall"/"mark"/"unmark" when start() needs to do
    more than update the buffer.

    Selecting: ^B drops a mark, then arrows/Home/End/PgUp/PgDn extend
    the selection from it; ^B again cancels. Typing, Tab, Enter or ^V
    over a selection replaces it."""
    action = None

    if mark is not None and _is_insert(key) and not (key == _K_PASTE and clip is None):
        start, end = _selection_range(mark, cy, cx)
        lines, cy, cx = _delete_range(lines, start, end)
        mark = None
        dirty = True
    elif key not in _SELECTION_AWARE_KEYS:
        mark = None

    if key == _K_MARK:
        if mark is None:
            mark = (cy, cx)
            action = "mark"
        else:
            mark = None
            action = "unmark"
    elif key == "UP":
        cy -= 1
    elif key == "DOWN":
        cy += 1
    elif key == "LEFT":
        if cx > 0:
            cx -= 1
        elif cy > 0:
            cy -= 1
            cx = len(lines[cy])
    elif key == "RIGHT":
        if cx < len(lines[cy]):
            cx += 1
        elif cy < len(lines) - 1:
            cy += 1
            cx = 0
    elif key == "HOME":
        cx = 0
    elif key == "END":
        cx = len(lines[cy])
    elif key == "PGUP":
        cy -= text_rows
    elif key == "PGDN":
        cy += text_rows
    elif key == "DELETE":
        if mark is not None:
            start, end = _selection_range(mark, cy, cx)
            lines, cy, cx = _delete_range(lines, start, end)
            mark = None
            dirty = True
        elif cx < len(lines[cy]):
            lines[cy] = lines[cy][:cx] + lines[cy][cx + 1:]
            dirty = True
        elif cy < len(lines) - 1:
            lines[cy] = lines[cy] + lines[cy + 1]
            del lines[cy + 1]
            dirty = True
    elif key in ("\r", "\n"):
        head, rest = lines[cy][:cx], lines[cy][cx:]
        indent = ""
        if auto_indent:
            indent = head[:len(head) - len(head.lstrip(" "))]
            if head.rstrip().endswith(":"):
                indent += " " * TAB_SIZE
            rest = rest.lstrip(" ")
        lines[cy] = head
        lines.insert(cy + 1, indent + rest)
        cy += 1
        cx = len(indent)
        dirty = True
    elif key == "\t":
        spaces = " " * (TAB_SIZE - cx % TAB_SIZE)
        lines[cy] = lines[cy][:cx] + spaces + lines[cy][cx:]
        cx += len(spaces)
        dirty = True
    elif key == _K_BACKSPACE:
        if mark is not None:
            start, end = _selection_range(mark, cy, cx)
            lines, cy, cx = _delete_range(lines, start, end)
            mark = None
            dirty = True
        elif cx > 0:
            lines[cy] = lines[cy][:cx - 1] + lines[cy][cx:]
            cx -= 1
            dirty = True
        elif cy > 0:
            prev_len = len(lines[cy - 1])
            lines[cy - 1] += lines[cy]
            del lines[cy]
            cy -= 1
            cx = prev_len
            dirty = True
    elif key == _K_SAVE:
        action = "save"
    elif key in _K_EXIT:
        action = "exit"
    elif key in _K_HELP:
        action = "help"
    elif key == _K_UNDO:
        action = "undo"
    elif key == _K_FIND:
        action = "find"
    elif key == _K_GOTO:
        action = "goto"
    elif key == _K_ALL:
        mark = (0, 0)
        cy = len(lines) - 1
        cx = len(lines[cy])
        action = "selectall"
    elif key == _K_CUT:
        if mark is not None:
            start, end = _selection_range(mark, cy, cx)
            clip = _extract_range(lines, start, end)
            lines, cy, cx = _delete_range(lines, start, end)
            mark = None
        else:
            clip = lines[cy]
            if len(lines) == 1:
                lines[cy] = ""
            else:
                del lines[cy]
        dirty = True
    elif key == _K_COPY:
        if mark is not None:
            start, end = _selection_range(mark, cy, cx)
            clip = _extract_range(lines, start, end)
            mark = None
        else:
            clip = lines[cy]
    elif key == _K_PASTE:
        if clip is not None:
            if isinstance(clip, list):
                lines, cy, cx = _paste_fragments(lines, cy, cx, clip)
            else:
                lines.insert(cy, clip)
            dirty = True
    elif _is_char(key):
        lines[cy] = lines[cy][:cx] + key + lines[cy][cx:]
        cx += 1
        dirty = True

    if not lines:
        lines = [""]
    cy = max(0, min(cy, len(lines) - 1))
    cx = max(0, min(cx, len(lines[cy])))
    return lines, cy, cx, clip, dirty, mark, action


def _diff(a, b):
    """(start, old_lines, new_count) - the block of lines that differs
    between list a (before) and list b (after), or None if identical.
    Only that block is kept for undo, never the whole file."""
    p = 0
    na, nb = len(a), len(b)
    while p < na and p < nb and a[p] == b[p]:
        p += 1
    if p == na == nb:
        return None
    s = 0
    while s < na - p and s < nb - p and a[na - 1 - s] == b[nb - 1 - s]:
        s += 1
    return p, a[p:na - s], nb - s - p


def _step_cost(old_lines):
    return _STEP_OVERHEAD + sum(len(ln) + _LINE_OVERHEAD for ln in old_lines)


def _find(lines, cy, cx, needle):
    """Next occurrence after the cursor, wrapping around the end of the
    file. Returns (y, x, wrapped) or None."""
    pos = lines[cy].find(needle, cx + 1)
    if pos >= 0:
        return cy, pos, False
    for y in range(cy + 1, len(lines)):
        pos = lines[y].find(needle)
        if pos >= 0:
            return y, pos, False
    for y in range(0, cy + 1):
        pos = lines[y].find(needle)
        if pos >= 0 and (y < cy or pos <= cx):
            return y, pos, True
    return None


def _render(lines, cy, cx, top, left, path, dirty, cols, rows, msg, mark, hl=None):
    """Builds the whole screen as a list of row strings (one per
    terminal row, escape codes for highlighting included) plus the
    cursor position - nothing is written here, see _paint()."""
    text_rows = rows - 3
    gutter = _gutter_width(len(lines))
    text_width = max(1, cols - gutter)
    sel = _selection_range(mark, cy, cx) if mark is not None else None
    frame = []

    title_left = " A-NIX edit"
    state = "  (modified)" if dirty else ""
    title_right = "L%d:C%d  %s%s " % (cy + 1, cx + 1, path, state)
    gap = cols - len(title_left) - len(title_right)
    title = (title_left + " " * gap + title_right) if gap >= 1 else (title_left + " " + title_right)
    frame.append("\x1b[7m" + _pad(title[:cols], cols) + "\x1b[0m")

    state = hl.state_at(lines, top) if hl else None
    for i in range(text_rows):
        idx = top + i
        if idx >= len(lines):
            frame.append("")
            continue
        row = _rjust(str(idx + 1), gutter - 1) + " "
        full = lines[idx]
        line_text = full[left:left + text_width]
        hs = he = None
        if sel and sel[0][0] <= idx <= sel[1][0]:
            (sy, sx), (ey, ex) = sel
            hs = (sx if idx == sy else 0) - left
            he = (ex if idx == ey else len(full)) - left
            hs = max(0, min(hs, len(line_text)))
            he = max(0, min(he, len(line_text)))
        if hl:
            text, state = hl.row(full, state, left, text_width,
                                 (hs, he) if hs is not None and he > hs else None)
            row += text
        elif hs is not None:
            row += (line_text[:hs] + "\x1b[7m" + line_text[hs:he] +
                    "\x1b[0m" + line_text[he:])
        else:
            row += line_text
        frame.append(row)

    frame.append(msg[:cols] if msg else "")
    helpline = "^O Save ^X Exit ^B Mark ^K Cut ^Y Copy ^V Paste ^Z Undo ^W Find ^H Help"
    frame.append("\x1b[7m" + _pad(helpline[:cols], cols) + "\x1b[0m")
    return frame, 2 + (cy - top), gutter + (cx - left) + 1


def _help_frame(cols, rows):
    text = [
        "",
        "  MOVING",
        "    Arrows Home End PgUp PgDn   move the cursor",
        "    ^F                          go to line number",
        "",
        "  SELECTING",
        "    ^B   mark on/off - then move the cursor to select",
        "    ^A   select the whole file",
        "",
        "  EDITING",
        "    ^K   cut  (selection, or the whole line)",
        "    ^Y   copy (selection, or the whole line)",
        "    ^V   paste          Del / Backspace   delete",
        "    ^Z   undo (last %d changes, max %d KB)" % (UNDO_MAX_STEPS, UNDO_MAX_KB),
        "    Tab  indent %d spaces; Enter keeps indent, adds one after ':'" % TAB_SIZE,
        "    Typing or pasting over a selection replaces it",
        "",
        "  SEARCH",
        "    ^W   find text - ^W then Enter finds the next match",
        "",
        "  FILE",
        "    ^O   save        ^X   exit (asks to save changes)",
    ]
    frame = ["\x1b[7m" + _pad(" A-NIX edit - help"[:cols], cols) + "\x1b[0m"]
    for i in range(rows - 2):
        frame.append(text[i][:cols] if i < len(text) else "")
    frame.append("\x1b[7m" + _pad(" Press any key to return"[:cols], cols) + "\x1b[0m")
    return frame


def _paint(frame, prev, cur_row, cur_col):
    """Writes only the rows that differ from the previous frame, all in
    ONE write, with the cursor hidden meanwhile - this is what keeps
    the screen from flickering over a serial link. prev=None repaints
    everything. Each changed row is cleared before it's written (not
    after) - clearing after a row that fills the full width would
    erase its last character on most terminals."""
    out = ["\x1b[?25l"]
    for i, row in enumerate(frame):
        if prev is None or i >= len(prev) or prev[i] != row:
            out.append("\x1b[%d;1H\x1b[K" % (i + 1))
            out.append(row)
    out.append("\x1b[%d;%dH\x1b[?25h" % (cur_row, cur_col))
    sys.stdout.write("".join(out))


def _prompt(rows, cols, prompt_text, digits_only=False):
    """One-line input on the message row. Returns the text, "" for an
    empty Enter, or None if cancelled with ^X."""
    buf = ""
    while True:
        sys.stdout.write("\x1b[%d;1H\x1b[K" % (rows - 1))
        sys.stdout.write((prompt_text + buf)[:cols])
        try:
            key = _readkey()
        except EOFError:
            return None
        if key is None:
            continue
        if key in _K_EXIT:
            return None
        if key in ("\r", "\n"):
            return buf
        if key in (_K_BACKSPACE, "\x08"):
            buf = buf[:-1]
        elif _is_char(key) and (key.isdigit() or not digits_only):
            buf += key


def _save(path, lines):
    """Writes to <path>.tmp first, then renames it over the real file,
    so a power cut or a full disk mid-save leaves the old file intact
    instead of a half-written one. LittleFS (the Pico's filesystem)
    replaces an existing file on rename; the remove+rename fallback
    covers filesystems that don't."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            for ln in lines:
                f.write(ln)
                f.write("\n")
        try:
            os.rename(tmp, path)
        except OSError:
            try:
                os.remove(path)
            except OSError:
                pass
            os.rename(tmp, path)
        return True, "Wrote %d line(s)" % len(lines)
    except OSError as e:
        try:
            os.stat(path)
        except OSError:
            # the old file is already gone: the .tmp is the only copy
            return False, "error: saved only as %s - %s" % (tmp, e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, "error: could not save - %s" % e


def start(path):
    # Ctrl-C must be a key here, not an exception that throws away the
    # unsaved buffer
    try:
        import micropython
        micropython.kbd_intr(-1)
    except (ImportError, AttributeError):
        micropython = None
    try:
        return _start(path)
    finally:
        if micropython is not None:
            micropython.kbd_intr(3)


def _start(path):
    """Main editor loop.

    Loads line-by-line rather than read().splitlines() - that would
    briefly need the whole file as one string AND as a list of lines
    at once. Refuses up front if the file looks too big for what's
    free, rather than loading partway and dying mid-read."""
    cols, rows = _screen_size()
    text_rows = max(1, rows - 3)

    existed = _file_exists(path)
    if existed:
        try:
            file_size = os.stat(path)[6]
        except OSError:
            file_size = 0
        gc.collect()
        free = gc.mem_free()
        import shell
        pct = max(10, min(90, shell._setting_int("EDIT_MEM", 40)))
        if file_size > free * pct // 100:
            shell._err("file too large to edit (%d bytes, %d free, EDIT_MEM=%d%%) - view it with `pg`" %
                        (file_size, free, pct))
            return

    lines = []
    try:
        with open(path) as f:
            for raw in f:
                lines.append(raw.rstrip("\n").rstrip("\r"))
    except OSError:
        lines = []
    except MemoryError:
        import shell
        shell._err("ran out of memory loading this file - view it with `pg`")
        return
    gc.collect()
    if not lines:
        lines = [""]

    cy = cx = top = left = 0
    hl = None                   # syntax colours (/lib/syntax.py), like nano
    try:
        import shell
        if shell.ENV.get("COLOR", "on").lower() != "off":
            import syntax
            kind = syntax.kind_for(path)
            if kind:
                hl = syntax.Highlighter(kind)
    except (ImportError, MemoryError):
        hl = None
    dirty = False
    clip = None
    mark = None
    msg = (("%d line(s) read" % len(lines)) if existed else "New file")
    last_find = ""
    last_key = None

    undo = []               # [start, old_lines, new_count, cy, cx]
    undo_bytes = 0
    undo_budget = UNDO_MAX_KB * 1024
    typing = False          # True while a run of typed chars is one step

    poller = None
    if select is not None:
        try:
            poller = select.poll()
            poller.register(sys.stdin, select.POLLIN)
        except Exception:
            poller = None

    def pending():
        """More input already waiting = a paste in progress."""
        return bool(poller and poller.poll(0))

    sys.stdout.write("\x1b[2J")   # the only full clear - see _paint()
    prev = None

    def redraw(message):
        nonlocal prev
        frame, crow, ccol = _render(lines, cy, cx, top, left, path, dirty,
                                    cols, rows, message, mark, hl)
        _paint(frame, prev, crow, ccol)
        prev = frame

    def ask(text, digits_only=False):
        answer = _prompt(rows, cols, text, digits_only)
        prev[rows - 2] = None   # the prompt wrote over the message row
        return answer

    while True:
        if cy < top:
            top = cy
        elif cy >= top + text_rows:
            top = cy - text_rows + 1
        top = max(0, top)
        text_width = max(1, cols - _gutter_width(len(lines)))
        if cx < left:
            left = cx
        elif cx >= left + text_width:
            left = cx - text_width + 1

        # while a paste is still streaming in, skip drawing - one
        # redraw at the end instead of one per pasted character
        if not pending():
            redraw(msg)
            msg = ""

        try:
            key = _readkey()
        except EOFError:
            key = None
        if key is None:
            continue
        if key.startswith("UNKNOWN:"):
            msg = "Unknown key code: " + key[8:]
            continue
        # terminals that send CR LF for Enter/paste: one line, not two
        if key == "\n" and last_key == "\r":
            last_key = None
            continue
        last_key = key

        try:
            # undo bookkeeping: remember what the change will touch
            record = UNDO_MAX_STEPS > 0 and _may_modify(key)
            fast = record and _is_char(key) and mark is None
            if not (_is_char(key) and mark is None):
                typing = False
            if fast:
                before_line, bcy, bcx = lines[cy], cy, cx
            elif record:
                before, bcy, bcx = lines[:], cy, cx   # list of references, not text

            lines, cy, cx, clip, dirty, mark, action = _apply_key(
                key, lines, cy, cx, clip, dirty, mark, text_rows,
                auto_indent=not pending())

            if record:
                if fast:
                    change = (bcy, [before_line], 1) if lines[bcy] != before_line else None
                else:
                    change = _diff(before, lines)
                    before = None
                if change is not None:
                    start_i, old, new_count = change
                    last = undo[-1] if undo else None
                    if (fast and typing and last is not None and last[0] == start_i
                            and len(last[1]) == 1 and last[2] == 1):
                        pass    # same typing run - the first step already has the old line
                    else:
                        undo.append([start_i, old, new_count, bcy, bcx])
                        undo_bytes += _step_cost(old)
                        while len(undo) > UNDO_MAX_STEPS or (undo_bytes > undo_budget and len(undo) > 1):
                            undo_bytes -= _step_cost(undo.pop(0)[1])
                    typing = fast

            if action == "undo":
                if not undo:
                    msg = "Nothing to undo"
                else:
                    start_i, old, new_count, ucy, ucx = undo.pop()
                    undo_bytes -= _step_cost(old)
                    lines[start_i:start_i + new_count] = old
                    if not lines:
                        lines = [""]
                    cy = max(0, min(ucy, len(lines) - 1))
                    cx = max(0, min(ucx, len(lines[cy])))
                    mark = None
                    dirty = True
                    typing = False
                    msg = "Undone (%d more step(s) available)" % len(undo)
            elif action == "save":
                ok, msg = _save(path, lines)
                if ok:
                    dirty = False
            elif action == "help":
                frame = _help_frame(cols, rows)
                _paint(frame, prev, rows, cols)
                prev = frame
                try:
                    _readkey()
                except EOFError:
                    pass
            elif action == "mark":
                msg = "Mark set - move to select, ^B again to cancel"
            elif action == "unmark":
                msg = "Mark cancelled"
            elif action == "selectall":
                msg = "Entire file selected - Del/^K/^Y act on all of it"
            elif action == "goto":
                entered = ask("Go to line: ", digits_only=True)
                if entered:
                    cy = max(0, min(int(entered) - 1, len(lines) - 1))
                    cx = 0
                    msg = "Line %d" % (cy + 1)
            elif action == "find":
                hint = (" [%s]" % last_find) if last_find else ""
                entered = ask("Find%s: " % hint)
                if entered is None:
                    msg = "Cancelled"
                else:
                    needle = entered or last_find
                    if needle:
                        last_find = needle
                        hit = _find(lines, cy, cx, needle)
                        if hit is None:
                            msg = "\"%s\" not found" % needle
                        else:
                            cy, cx, wrapped = hit
                            msg = "Search wrapped to the top" if wrapped else ""
            elif action == "exit":
                if not dirty:
                    sys.stdout.write("\x1b[2J\x1b[H")
                    return
                redraw("Save modified buffer? (y = yes, n = no, other key = cancel)")
                try:
                    ans = _readkey()
                except EOFError:
                    ans = None
                if ans in ("y", "Y"):
                    ok, msg = _save(path, lines)
                    if ok:
                        sys.stdout.write("\x1b[2J\x1b[H")
                        return
                    # save failed - stay in the editor so nothing is lost
                elif ans in ("n", "N"):
                    sys.stdout.write("\x1b[2J\x1b[H")
                    return

        except MemoryError:
            # out of RAM mid-change: keep the buffer (the change may be
            # half done), drop the undo history to free memory
            undo = []
            undo_bytes = 0
            before = None
            gc.collect()
            dirty = True
            msg = "OUT OF MEMORY - undo cleared; save now with ^S"


def run(args, cwd):
    import shell
    if not args:
        shell._out("usage: edit <file>")
        return
    start(shell._join(cwd, args[0]))
