"""lineedit - the shell's prompt line editor: history, Tab completion
and cursor editing, over any VT100/ANSI terminal (PuTTY, mintty,
GNOME Terminal, screen).

  Up / Down          previous / next command from history
  Left / Right       move in the line      Home / End (or ^A / ^E)
  Backspace / Del    delete                ^U  delete to line start
  ^K                 delete to line end    ^L  clear screen
  Tab                complete a command or file name; a second Tab
                     lists all matches

Ctrl-C is MicroPython's interrupt key: it arrives as KeyboardInterrupt
(at the prompt the shell then leaves to the raw REPL).

A line longer than the terminal scrolls sideways inside the prompt
instead of wrapping, so redrawing never garbles the screen.

watch(sock, fn): while the prompt waits for keys it also watches sock
and calls fn() as soon as sock is readable - that's how httpd answers a
browser at once from core 0. unwatch(sock) ends it.
"""

import sys
import time

try:
    import select
except ImportError:
    try:
        import uselect as select
    except ImportError:
        select = None

_LETTERS = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "H": "HOME", "F": "END"}
_TILDE = {"1": "HOME", "7": "HOME", "3": "DELETE", "4": "END", "8": "END"}

_poll = None
_poll_all = None        # stdin + watched sockets, for the idle wait
_watches = []           # (socket, fn) - see watch()
_pushback = []          # a byte read too early, handed out first
_after_cr = [False]     # last line ended with CR: an LF next is its other half


def _visible_len(text):
    """Length on screen: colour codes (ESC [ ... m) take no room."""
    if "\x1b" not in text:
        return len(text)
    n = 0
    esc = False
    for ch in text:
        if esc:
            esc = ch != "m"
        elif ch == "\x1b":
            esc = True
        else:
            n += 1
    return n


def _read():
    if _pushback:
        return _pushback.pop()
    ch = sys.stdin.read(1)
    if _after_cr[0]:
        _after_cr[0] = False
        if ch == "\n":                  # CR LF terminal: one Enter, not two
            ch = sys.stdin.read(1)
    return ch


def _settle():
    """At the start of a prompt: eat the LF of a CR LF Enter now, so
    the idle wait doesn't mistake it for a key."""
    if _after_cr[0] and not _pushback and _waiting(20):
        _after_cr[0] = False
        ch = sys.stdin.read(1)
        if ch != "\n":
            _pushback.append(ch)
    else:
        _after_cr[0] = False


def input_line(prompt=""):
    """input() replacement for commands (read, choice...): shares
    the prompt's key reading, so a pasted block keeps every character
    and a CR LF Enter counts once. Backspace edits; Ctrl-C raises
    KeyboardInterrupt; Ctrl-D on an empty line raises EOFError."""
    w = sys.stdout.write
    w(prompt)
    buf = []
    while True:
        ch = _read()
        if ch == "":
            raise EOFError
        if ch in ("\r", "\n"):
            if ch == "\r":
                _after_cr[0] = True
            w("\r\n")
            return "".join(buf)
        if ch == "\x03":
            w("^C\r\n")
            raise KeyboardInterrupt
        if ch == "\x04" and not buf:
            raise EOFError
        if ch in ("\x7f", "\x08"):
            if buf:
                buf.pop()
                w("\b \b")
        elif ch >= " ":
            buf.append(ch)
            w(ch)


def watch(sock, fn):
    """While the prompt waits for keys, call fn() whenever sock is
    readable (a browser connecting to httpd)."""
    global _poll_all
    unwatch(sock)
    _watches.append((sock, fn))
    _poll_all = None                    # rebuilt with the socket


def unwatch(sock):
    global _poll_all
    _watches[:] = [w for w in _watches if w[0] is not sock]
    _poll_all = None


def _waiting_serving(ms):
    """_waiting() for the idle prompt: also runs the watch() handlers
    for sockets that become readable meanwhile. True on a key."""
    global _poll_all
    if _poll_all is None:
        _poll_all = select.poll()
        _poll_all.register(sys.stdin, select.POLLIN)
        for sock, _fn in _watches:
            _poll_all.register(sock, select.POLLIN)
    end = time.ticks_add(time.ticks_ms(), ms)
    while True:
        left = time.ticks_diff(end, time.ticks_ms())
        if left <= 0:
            return False
        ready = _poll_all.poll(left)
        if not ready:
            return False
        key = False
        for item in ready:
            for sock, fn in _watches:
                if item[0] is sock:
                    try:
                        fn()
                    except Exception:
                        pass
                    break
            else:
                key = True              # stdin: a key
        if key:
            return True


def _waiting(ms, serve=False):
    """True if another byte arrives within ms. serve=True (the idle
    prompt): watched sockets are served meanwhile, see watch()."""
    global _poll
    if _pushback:
        return True
    if select is None:
        return True
    if serve and _watches:
        try:
            return _waiting_serving(ms)
        except Exception:
            pass                        # fall back to keys only
    try:
        if _poll is None:
            _poll = select.poll()
            _poll.register(sys.stdin, select.POLLIN)
        return bool(_poll.poll(ms))
    except Exception:
        return True


def _readkey():
    ch = _read()
    if ch != "\x1b":
        return ch
    # a lone Esc press sends nothing more - don't swallow the next key
    if not _waiting(50):
        return None
    ch2 = _read()
    if ch2 == "O":
        return _LETTERS.get(_read())
    if ch2 != "[":
        return None
    seq = ""
    term = _read()
    while term and term in "0123456789;":
        seq += term
        term = _read()
    if term in _LETTERS:
        return _LETTERS[term]
    if term == "~":
        return _TILDE.get(seq.split(";")[0])
    return None


def terminal_size(default_cols=80, default_rows=24):
    """Asks the terminal for its size (cursor-position report). Returns
    the defaults if nothing answers within ~200 ms (no terminal
    connected, or one that doesn't support the query)."""
    if select is None:
        return default_cols, default_rows
    try:
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        sys.stdout.write("\x1b[s\x1b[999;999H\x1b[6n\x1b[u")
        resp = ""
        for _ in range(20):
            if poll.poll(10):
                ch = _read()
                resp += ch
                if ch == "R":
                    break
            if len(resp) > 16:
                break
        if resp.startswith("\x1b[") and resp.endswith("R") and ";" in resp:
            rows_s, cols_s = resp[2:-1].split(";", 1)
            return int(cols_s), int(rows_s)
    except Exception:
        pass
    return default_cols, default_rows


def _common_prefix(words):
    p = words[0]
    for w in words[1:]:
        i = 0
        while i < len(p) and i < len(w) and p[i] == w[i]:
            i += 1
        p = p[:i]
    return p


_current = [None]           # while readline waits: () -> prompt + typed text


def on_screen():
    """The prompt and the half-typed line, as readline shows them now -
    or None when no prompt is waiting (telnetd shows it after login)."""
    fn = _current[0]
    return fn() if fn else None


def readline(prompt, history=None, completer=None, width=80, idle=None):
    try:
        return _readline(prompt, history, completer, width, idle)
    finally:
        _current[0] = None


def _readline(prompt, history, completer, width, idle):
    """Reads one line. history: a list (oldest first) browsed with
    Up/Down - not modified here. idle(), if given, is called about once
    a second while no key is pressed; if it returns text, that text is
    printed above the prompt (e.g. a background job's output) and the
    prompt and the half-typed line are drawn again under it. prompt may
    be a function, asked again at every redraw (so it can change, like
    a [1] job marker). completer(text_before_cursor) returns
    the possible replacements for the last word. Returns the line
    without the line ending."""
    buf = []
    pos = 0
    hist = history or []
    hidx = len(hist)        # len(hist) = the line being typed
    saved = ""              # what was typed before browsing history
    last_tab = False
    w = sys.stdout.write
    get_prompt = prompt if callable(prompt) else (lambda: prompt)
    cur_prompt = [get_prompt()]
    _settle()

    # what is on screen after the prompt, and where the cursor is in it
    screen = [""]
    scur = [0]
    view = [0]              # first character of buf shown (sideways scroll)

    def _move(n):
        if n > 0:
            return "\x1b[%dC" % n
        if n < 0:
            return "\x1b[%dD" % -n
        return ""

    def redraw():
        """Changes only what differs on screen: the cursor moves
        relatively, only characters from the first difference on are
        rewritten, and it all goes out in one write. Typing at the end
        of a line sends just that character; moving the cursor sends
        just a cursor move - no rewriting of the prompt or the line,
        so nothing flickers."""
        avail = max(10, width - _visible_len(cur_prompt[0]) - 1)
        text = "".join(buf)
        start = view[0]
        if pos < start:
            start = pos
        elif pos - start >= avail:
            start = pos - avail + 1
        if len(text) - start < avail:
            start = max(0, len(text) - avail)
        view[0] = start
        new = text[start:start + avail]
        new_cur = pos - start
        old = screen[0]
        p = 0
        n = min(len(old), len(new))
        while p < n and old[p] == new[p]:
            p += 1
        if p == len(old) == len(new):
            out = _move(new_cur - scur[0])
        else:
            out = _move(p - scur[0]) + new[p:]
            if len(new) < len(old):
                out += "\x1b[K"
            out += _move(new_cur - len(new))
            if len(new) - p > 1:
                out = "\x1b[?25l" + out + "\x1b[?25h"
        if out:
            w(out)
        screen[0] = new
        scur[0] = new_cur

    def reprint():
        """After something else wrote over the line (^L, Tab list)."""
        screen[0] = ""
        scur[0] = 0

    w(cur_prompt[0])
    # exactly what is on screen, cursor included
    _current[0] = lambda: cur_prompt[0] + screen[0] + _move(scur[0] - len(screen[0]))
    while True:
        # nothing typed for a second: let the shell do background work
        # (cron jobs). idle() must not write to the screen.
        if idle is not None:
            while not _waiting(1000, True):
                try:
                    text = idle()
                except Exception:
                    text = None
                if text:
                    cur_prompt[0] = get_prompt()
                    w("\r\x1b[K" + text + cur_prompt[0])
                    reprint()
                    redraw()
        key = _readkey()
        if key is None:
            continue
        tab = False

        if key in ("\r", "\n"):
            # a terminal sending CR LF for Enter: eat the LF now, so a
            # command that reads input next (choice, read) doesn't get
            # it as an empty answer
            if key == "\r":
                _after_cr[0] = True     # an LF right after it is skipped
            w("\r\n")
            return "".join(buf)
        elif key == "\x03":
            w("^C\r\n")
            raise KeyboardInterrupt
        elif key in ("\x7f", "\x08"):
            if pos > 0:
                del buf[pos - 1]
                pos -= 1
        elif key == "DELETE":
            if pos < len(buf):
                del buf[pos]
        elif key == "LEFT":
            pos = max(0, pos - 1)
        elif key == "RIGHT":
            pos = min(len(buf), pos + 1)
        elif key in ("HOME", "\x01"):
            pos = 0
        elif key in ("END", "\x05"):
            pos = len(buf)
        elif key == "\x15":         # ^U
            del buf[:pos]
            pos = 0
        elif key == "\x0b":         # ^K
            del buf[pos:]
        elif key == "\x0c":         # ^L
            w("\x1b[2J\x1b[H" + cur_prompt[0])
            reprint()
        elif key in ("UP", "DOWN"):
            if not hist:
                continue
            if hidx == len(hist):
                saved = "".join(buf)
            if key == "UP":
                hidx = max(0, hidx - 1)
            else:
                hidx = min(len(hist), hidx + 1)
            buf = list(hist[hidx] if hidx < len(hist) else saved)
            pos = len(buf)
        elif key == "\t":
            tab = True
            if completer is not None:
                before = "".join(buf[:pos])
                word = before[before.rfind(" ") + 1:]
                try:
                    cands = completer(before)
                except Exception:
                    cands = []
                if len(cands) == 1:
                    rep = cands[0]
                    if not rep.endswith("/"):
                        rep += " "
                    buf[pos - len(word):pos] = list(rep)
                    pos += len(rep) - len(word)
                elif cands:
                    common = _common_prefix(cands)
                    if len(common) > len(word):
                        buf[pos - len(word):pos] = list(common)
                        pos += len(common) - len(word)
                    elif last_tab:
                        names = [c.rstrip("/").rsplit("/", 1)[-1] + ("/" if c.endswith("/") else "")
                                 for c in sorted(cands)]
                        w("\r\n" + "  ".join(names) + "\r\n" + cur_prompt[0])
                        reprint()
        elif len(key) == 1 and (32 <= ord(key) <= 126 or ord(key) >= 160):
            buf.insert(pos, key)
            pos += 1
        else:
            continue
        last_tab = tab
        redraw()
