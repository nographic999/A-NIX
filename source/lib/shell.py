"""shell - *NIX-style shell for the Pico (MicroPython).
Only true sh builtins live here (cd/export/etc need the shell's own
process state, so they can't be separate files). Everything else is
resolved via $PATH and exec'd from /bin, same as a real *NIX shell.
See `man` for the full guide.
"""

import os
import sys
import gc
import time

# Only /lib is searched for imports. A file on the import path hides
# MicroPython's built-in module of the same name, so neither /bin
# (commands are exec'd from there, not imported) nor the current folder
# ("" - e.g. a /root/time.py) may be on it.
for _p in ("", "/", "/bin"):
    while _p in sys.path:
        sys.path.remove(_p)
if "/lib" not in sys.path:
    sys.path.append("/lib")

try:
    import machine
except ImportError:
    machine = None

VERSION = "0.1T"
TAGLINE = "Experimental Alpha"
AUTHOR = "NoGraphic999"
PROFILE = "/etc/profile"
CONF = "/etc/anix.conf"
STARTUP = "/etc/startup"
MAN_PAGE = "/usr/share/man/anix"
LICENSE_PATH = "/usr/share/doc/copyright"

ENV = {}
ALIASES = {}        # alias name -> replacement text (see shbuiltin.cmd_alias)
FUNCTIONS = {}      # script function name -> parsed body (see _parse_script)
HISTORY = []        # prompt history, oldest first (see run)
NOTICE = None       # set by main.py (e.g. safe mode) - shown under the banner
SAFE = False        # set by main.py (BOOTSEL held): no profile, startup, crontab, watchdog
_last_status = "0"  # $?
TERM_WIDTH = 80  # updated from $COLUMNS at boot (see _load_config) -
                 # ls's multi-column layout reads this rather than
                 # ENV directly, so it works even if a script hasn't
                 # bothered to check ENV itself

# --- shared pin/bus state (must live here, not in /bin, since each
# /bin command is exec'd fresh - only shell.py's own globals persist
# for the life of the session). Used by out/in/adc/pwm/pins/uart/spi.
_pins = {}
_pin_modes = {}
_adcs = {}
_pwms = {}
_uarts = {}
_spis = {}
_wdt = None          # machine.WDT - once created it can't be torn down
_beat = [time.ticks_ms()]   # last sign of life, for the shell watchdog


def alive():
    """Tells the shell watchdog (WATCHDOG_HANG) the shell isn't stuck.
    Called on every output, command start and idle second at the
    prompt; a command that works silently for minutes can call it."""
    _beat[0] = time.ticks_ms()


_up = [time.ticks_ms(), time.ticks_ms()]    # last ticks seen, ms since power-on


def uptime_ms():
    """Milliseconds since power-on. time.ticks_ms() itself wraps to 0
    every ~12.4 days; adding up the steps between calls keeps counting
    past that (the prompt calls this every second, so no step is
    anywhere near the wrap)."""
    now = time.ticks_ms()
    _up[1] += time.ticks_diff(now, _up[0])
    _up[0] = now
    return _up[1]
_ble = None          # bluetooth.BLE - created once, stays active
_ble_scan_results = []
_ble_scan_done = [False]  # list so the irq handler can flip it without `global`

try:
    import _thread
except ImportError:
    _thread = None
_capture_buf = None    # None = normal mode; a list = a capture is active
_capture_owner = None   # thread ident of whoever owns the active capture
_capture_lock = _thread.allocate_lock() if _thread else None
# Held while a pin/bus command runs (here) or while the httpd panel
# handles a request (server.py), so a command in a background job on
# core 1 and the shell or panel on core 0 never change the shared pin
# dictionaries at the same moment - MicroPython on the Pico has no
# global interpreter lock to do that for us.
_pin_lock = _thread.allocate_lock() if _thread else None
_pin_holder = [None]    # thread ident that holds _pin_lock for a command
_PIN_COMMANDS = ("out", "in", "pwm", "adc", "pins", "spi", "i2c", "uart", "httpd", "flash")
# _capture_buf: cron grabs a job's output here (for /var/log/cron.log)
# instead of the screen - see _dispatch_captured. Only the thread that
# set the capture up (_capture_owner) writes into it, so a background
# job's output on core 1 never ends up in a cron job's log. The lock
# stops two captures from overlapping; _write never takes it (the
# capturing thread already holds it, and the lock isn't reentrant).


def _current_thread_ident():
    if _thread and hasattr(_thread, "get_ident"):
        try:
            return _thread.get_ident()
        except Exception:
            pass
    return None


_MAIN = _current_thread_ident()     # the thread running the shell itself


# The filesystem is not safe with both cores in it at once: core 1
# loading a command while core 0 writes a log can freeze the board.
# A-NIX's own file work - loading commands and scripts, writing logs
# and the history - holds this lock. (A program's own file reads and
# writes on core 1 are not covered: keep core-1 programs off files.)
_fs_lock = _thread.allocate_lock() if _thread else None
_fs_owner = [None, 0]   # thread holding it, how deep


def fs_begin():
    if _fs_lock is None:
        return
    me = _current_thread_ident()
    if _fs_owner[0] == me:
        _fs_owner[1] += 1               # nested (an import loading more)
        return
    _fs_lock.acquire()
    _fs_owner[0] = me
    _fs_owner[1] = 1


def fs_end():
    if _fs_lock is None or _fs_owner[0] != _current_thread_ident():
        return
    _fs_owner[1] -= 1
    if _fs_owner[1] == 0:
        _fs_owner[0] = None
        _fs_lock.release()


_redirects = {}         # thread ident -> open file while a command runs with > / >>
_err_redirects = {}     # thread ident -> file for 2> / 2>>, or 1 for 2>&1


class _NullFile:
    """/dev/null: swallows everything written to it."""

    def write(self, data):
        return len(data)

    def close(self):
        pass

    def commit(self):
        pass

    def abort(self):
        pass


def _write(text, is_error=False):
    """Writes raw text (no newline added) - the one place all command
    output goes through. A `> file` / `>> file` redirection sends it
    to that file instead (errors excepted: they always reach the
    screen, like a real shell's stderr), and a cron capture (see
    _capture_buf, above) collects it - each only for the thread that
    set it up. Commands that print file contents (cat, head, tail...)
    use this so their output can be redirected too."""
    me = _current_thread_ident()
    if _kill and _kill.get(me):
        raise _Killed()
    if me == _MAIN:
        _beat[0] = time.ticks_ms()
    if is_error and _err_redirects:
        e = _err_redirects.get(me)
        if e == 1:
            is_error = False            # 2>&1: errors go where output goes
        elif e is not None:
            e.write(text)
            return
    f = _redirects.get(me) if _redirects and not is_error else None
    if f is not None:
        f.write(text)
    elif _capture_buf is not None and _capture_owner == me:
        _capture_buf.append(text)
    else:
        sys.stdout.write(text)


def _out(*args):
    """Prints a line, space-joining multiple arguments like a real
    print(). Goes through _write, so redirection and capture apply."""
    _write(" ".join(str(a) for a in args) + "\n")


_thread_status = {}     # $? of commands running in other threads (the background job)
_kill = {}              # thread ident -> True: stop that thread's command


class _Killed(BaseException):
    """Raised inside a background job asked to stop (`kill`). A
    BaseException so a command's own `except Exception` can't swallow
    it."""


def _status():
    """$? as seen by the calling thread."""
    me = _current_thread_ident()
    if me is None or me == _MAIN:
        return _last_status
    return _thread_status.get(me, "0")


def _put_status(value):
    global _last_status
    me = _current_thread_ident()
    if me is None or me == _MAIN:
        _last_status = value
    else:
        _thread_status[me] = value


def _err(msg, exc=None):
    """Prints an error and sets $? to "1" - the one place error
    output and exit-status tracking both happen, so `if` conditions
    and $? in scripts stay accurate no matter which command failed.
    Never goes into a > / >> file."""
    _put_status("1")
    if msg == "file not found" and isinstance(exc, str) and _is_dir(exc):
        msg, exc = "%s is a folder, not a file" % exc, None
    text = ("%s - %s" % (msg, exc)) if exc is not None else msg
    me = _current_thread_ident()
    e = _err_redirects.get(me) if _err_redirects else None
    to_screen = _capture_buf is None and (e is None or (e == 1 and me not in _redirects))
    head = "error:"
    if to_screen and ENV.get("COLOR", "on").lower() != "off":
        head = "\x1b[01;31merror:\x1b[0m"
    _write("%s %s\n" % (head, text), is_error=True)


def _set_status(code):
    """Sets $? without printing anything - for a command whose
    non-zero result is a legitimate answer, not a failure worth an
    "error: ..." message (e.g. whiptail's Cancel/No - a script can
    still branch on it with `if $?==1 then`, same as any other exit
    status, without a spurious error line on screen)."""
    _put_status(str(code))


PIPE_RAM = 8192        # pipe data kept in RAM up to this, then in a file
_pipe_in = {}           # thread ident -> _PipeBuf feeding the current command


_pipe_count = [0]


class _PipeBuf:
    """Collects one pipeline stage's output for the next stage. Kept in
    RAM while small; past PIPE_RAM it moves to a temporary file, so a
    big output (cat of a large file | grep) can't run the Pico out of
    memory."""

    def __init__(self, n):
        self.parts = []
        self.size = 0
        self.path = None
        self.f = None
        self.n = n
        self.rd = None                  # line reader used by `read`

    def write(self, text):
        if self.f is not None:
            self.f.write(text)
            return
        self.parts.append(text)
        self.size += len(text)
        if self.size > PIPE_RAM:
            for d in ("/var", "/var/tmp"):
                try:
                    os.mkdir(d)
                except OSError:
                    pass
            _pipe_count[0] += 1         # unique: nested pipes, job + prompt
            self.path = "/var/tmp/pipe%d_%d" % (self.n, _pipe_count[0])
            self.f = open(self.path, "w")
            for part in self.parts:
                self.f.write(part)
            self.parts = []

    def finish(self):
        if self.f is not None:
            self.f.close()
            self.f = None

    def reader(self, binary=False):
        import io
        if self.path is not None:
            return open(self.path, "rb" if binary else "r")
        text = "".join(self.parts)
        return io.BytesIO(text.encode()) if binary else io.StringIO(text)

    def discard(self):
        self.finish()
        if self.rd is not None:
            self.rd.close()
            self.rd = None
        self.parts = []
        if self.path is not None:
            try:
                os.remove(self.path)
            except OSError:
                pass


class _FileIn:
    """`cmd < file`: the file as the command's input, the same way a
    pipe feeds it (see _input)."""

    def __init__(self, path):
        self.path = path
        self.rd = None

    def reader(self, binary=False):
        return open(self.path, "rb" if binary else "r")

    def discard(self):
        if self.rd is not None:
            self.rd.close()
            self.rd = None


def _to_screen():
    """True if this command's output goes straight to the terminal - not
    into a > file, a pipe, or a cron log. Commands use it to choose
    a screen layout (colour, columns) or a plain one."""
    if _capture_buf is not None:
        return False
    return _current_thread_ident() not in _redirects


# --- Linux-style colours (the default dircolors / grep / diff ones).
# Only straight to the terminal, never into a file, a pipe or a log;
# COLOR=off in /etc/anix.conf turns them all off (e.g. for Thonny).
BLUE_BOLD, GREEN_BOLD, RED_BOLD, MAGENTA_BOLD = "01;34", "01;32", "01;31", "01;35"
RED, GREEN, YELLOW, MAGENTA, CYAN, GREY, BOLD = "31", "32", "33", "35", "36", "90", "01"
_EXEC = (".py", ".mpy", ".sh")
_ARCHIVE = (".zip", ".gz", ".tgz", ".tar", ".bz2", ".7z", ".uf2", ".bin")
_IMAGE = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico")


def _colors():
    """True if colours may be used for this command's output now."""
    return ENV.get("COLOR", "on").lower() != "off" and _to_screen()


def _c(code, text):
    """text in colour code ("01;34" = bold blue...) - or plain text when
    colours are off or the output doesn't go to the screen."""
    if not _colors():
        return text
    return "\x1b[%sm%s\x1b[0m" % (code, text)


def _name_color(name):
    """The colour `ls` and `tree` give a name (folders end in /), like
    Linux's default dircolors: folders bold blue, programs bold green,
    archives and firmware bold red, images bold magenta. None = plain."""
    low = name.lower()
    if low.endswith("/"):
        return BLUE_BOLD
    for ext, code in ((_EXEC, GREEN_BOLD), (_ARCHIVE, RED_BOLD), (_IMAGE, MAGENTA_BOLD)):
        for e in ext:
            if low.endswith(e):
                return code
    return None


def _c_status(text, ok):
    """text green when ok, else bold red - for running/failed, $?=0/1."""
    return _c(GREEN if ok else RED_BOLD, text)


def _c_signal(rssi, text=None):
    """WiFi signal strength coloured like nmcli's bars: strong green,
    usable yellow, weak red."""
    text = text if text is not None else "%d dBm" % rssi
    return _c(GREEN if rssi >= -60 else (YELLOW if rssi >= -75 else RED), text)


def _color_name(name):
    code = _name_color(name)
    return _c(code, name) if code else name


# Commands that wait for keys or draw on the screen: refused in a
# background job, cron or anything else not at the prompt itself.
_KEYBOARD_COMMANDS = ("edit", "whiptail", "python", "choice", "uartterm",
                      "man", "pg", "mkfs", "license", "watch", "clear",
                      "nc")


def _no_keyboard():
    """True when the running command can't use the keyboard/screen:
    it runs in a background job or is captured (cron)."""
    return _current_thread_ident() != _MAIN or _capture_buf is not None


def _input_line(prompt=""):
    """input() for commands: reads keys the same way the prompt does
    (see lineedit.input_line), so pasted text isn't reordered."""
    import lineedit
    return lineedit.input_line(prompt)


def _setting_int(name, default):
    """A number setting from ENV; "none", empty or not a number gives
    the default (so `conf KEY none` means "use the default")."""
    try:
        return int(ENV.get(name, default))
    except (TypeError, ValueError):
        return default


def _ask(question):
    """Asks a y/n question; True only for y. Without a keyboard (a
    background job, cron) it says so and returns False instead of
    hanging."""
    if _no_keyboard():
        _err("this needs a yes/no answer - run it at the prompt")
        return False
    try:
        return _input_line(question + " (y/n) ").strip().lower() == "y"
    except EOFError:
        return False


def _piped():
    """True if the running command has pipe input (cmd | this)."""
    return _current_thread_ident() in _pipe_in


def _input(cwd, name=None, binary=False):
    """The input of a command that reads text: the named file, or - with
    no name - what was piped into it. Returns an open file object, or
    None when there's neither (the caller prints its usage). Raises
    OSError for a missing file, like open()."""
    if name is not None:
        path = _join(cwd, name)
        if _is_dir(path):
            raise OSError(21)           # a folder: the caller says so
        return open(path, "rb" if binary else "r")
    buf = _pipe_in.get(_current_thread_ident())
    if buf is None:
        return None
    return buf.reader(binary)


def _banner(color=None):
    """A-NIX [Version 0.1T] - Experimental Alpha. On the screen (COLOR
    not off) the name is bold cyan, the version bold yellow and the
    tagline magenta; plain in a file, a pipe or a log."""
    if color is None:
        color = _colors()
    if not color:
        return "A-NIX [Version %s] - %s" % (VERSION, TAGLINE)
    return ("\x1b[01;36mA-NIX\x1b[0m [\x1b[01;33mVersion %s\x1b[0m] - \x1b[35m%s\x1b[0m"
            % (VERSION, TAGLINE))


def _is_word_char(ch):
    """A "word" character for $VAR-style expansion - matches Python's
    own identifier rules (letters, digits, underscore) so env var
    names behave the way you'd expect from any other language."""
    return ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


_sub_count = [0]


# Text that came from a $VAR or $(command) must never act as a
# redirection or a quote: while a command line is parsed, these
# characters of expanded text are swapped for private stand-ins, and
# swapped back once the line is split into arguments (_unprotect).
_PROT_FROM = "><\"'"
_PROT_TO = "\ue001\ue002\ue003\ue004"


def _protect(text):
    for a, b in zip(_PROT_FROM, _PROT_TO):
        if a in text:
            text = text.replace(a, b)
    return text


def _unprotect(text):
    for a, b in zip(_PROT_FROM, _PROT_TO):
        if b in text:
            text = text.replace(b, a)
    return text


def _expand(line, cwd=None, protect=False):
    """$?, $#, $@, $0-$9, $((expr)), $(command), ${VAR}, $VAR -
    unmatched text is left as-is. $(command) runs the command (in cwd)
    and puts its output in its place (newlines become spaces). With
    protect, the inserted text is marked so it can't act as > < or
    quotes (see _protect)."""
    if "$" not in line:
        return line
    out = []
    raw = out.append                    # text from the line itself

    if protect:
        def put(text):                  # expanded text: protected
            raw(_protect(text))
    else:
        put = raw
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "$" and i + 1 < n:
            nxt = line[i + 1]
            if nxt == "?":
                put(_status())
                i += 2
                continue
            if nxt in "#@" or "0" <= nxt <= "9":
                put(ENV.get(nxt, ""))   # script/function arguments
                i += 2
                continue
            if nxt == "(" and not (i + 2 < n and line[i + 2] == "("):
                import subst
                end = subst.matching_paren(line, i + 1)
                if end != -1:
                    put(subst.substitute(line[i + 2:end], cwd))
                    i = end + 1
                    continue
            if nxt == "(" and i + 2 < n and line[i + 2] == "(":
                import subst
                end = subst.matching_paren(line, i + 1)
                if end != -1 and line[end - 1] == ")":
                    result = subst.eval_arithmetic(line[i + 3:end - 1])
                    if result is not None:
                        put(result)
                        i = end + 1
                        continue
            elif nxt == "{":
                end = line.find("}", i + 2)
                if end != -1:
                    name = line[i + 2:end]
                    if name in ENV:
                        put(ENV[name])
                        i = end + 1
                        continue
            elif _is_word_char(nxt):
                j = i + 1
                while j < n and _is_word_char(line[j]):
                    j += 1
                name = line[i + 1:j]
                if name in ENV:
                    put(ENV[name])
                    i = j
                    continue
        raw(line[i])
        i += 1
    return "".join(out)


def _glob_match(pattern, name):
    """* and ? matcher. Iterative, remembering only the last * - so it
    is linear-ish and can't blow the stack or hang on patterns like
    *a*a*a*b. No character classes ([abc]) or **."""
    p = n = 0
    star = -1
    mark = 0
    while n < len(name):
        if p < len(pattern) and (pattern[p] == "?" or pattern[p] == name[n]):
            p += 1
            n += 1
        elif p < len(pattern) and pattern[p] == "*":
            star = p
            mark = n
            p += 1
        elif star != -1:
            p = star + 1
            mark += 1
            n = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def _glob_expand(cwd, pattern):
    """Expands one glob pattern (e.g. "*.py" or "sub/*.txt") into the
    list of matching names, called from _dispatch for each argument
    that contains * or ?. Falls back to returning the pattern
    unchanged (as a literal, one-item list) if it matches nothing or
    the directory can't be read - same as real shells leaving an
    unmatched glob as literal text rather than erroring."""
    if "*" not in pattern and "?" not in pattern:
        return [pattern]
    if "/" in pattern:
        dir_part, name_part = pattern.rsplit("/", 1)
        search_dir = _join(cwd, dir_part or "/")
        prefix = dir_part + "/"         # "/" for /*.py
    else:
        name_part, search_dir, prefix = pattern, cwd, ""
    try:
        entries = os.listdir(search_dir)
    except OSError:
        return [pattern]
    hidden = name_part.startswith(".")  # * skips .files unless asked
    matches = sorted(e for e in entries
                     if (hidden or not e.startswith(".")) and _glob_match(name_part, e))
    if not matches:
        return [pattern]
    return [prefix + m for m in matches]


def _join(cwd, name):
    """Resolves name against cwd (a name starting with "/" is already
    absolute) and normalises the result: "." and ".." are resolved and
    repeated or trailing slashes dropped, so every command sees clean
    paths like /root/a instead of /root/x/../a/."""
    path = name if name.startswith("/") else (cwd.rstrip("/") + "/" + name)
    parts = []
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/" + "/".join(parts)


def _basename(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


def _is_dir(path):
    try:
        return bool(os.stat(path)[0] & 0x4000)  # 0x4000 = S_IFDIR bit in st_mode
    except OSError:
        return False


def _replace_file(tmp, path):
    """Moves tmp over path. LittleFS (the Pico's filesystem) replaces an
    existing file on rename; the remove+rename fallback covers ones that
    don't."""
    try:
        os.rename(tmp, path)
    except OSError:
        try:
            if os.stat(path)[0] & 0x4000:
                raise OSError(21)       # a folder: never removed for a file
        except OSError:
            raise                       # nothing to replace - a real error
        os.remove(path)
        os.rename(tmp, path)


def _open_append(path):
    """>> : opens path for appending. A file whose last line has no
    newline (often one edited on a PC) gets one first, so the new text
    starts on its own line instead of being glued to the last one -
    e.g. `echo every 5m wifi >> /etc/crontab`."""
    end = b"\n"
    try:
        size = os.stat(path)[6]
        if size:
            with open(path, "rb") as f:
                f.seek(size - 1)
                end = f.read(1)
    except OSError:
        pass                            # a new file
    f = open(path, "a")
    if end != b"\n":
        f.write("\n")
    return f


class _SafeFile:
    """A file opened for writing that only replaces the real file when
    it is closed successfully: everything goes to <path>.tmp first.
    commit() renames it over the real file; abort() throws it away, so
    a Ctrl-C, an error or a power cut halfway leaves the old file as it
    was instead of a half-written one."""

    def __init__(self, path, binary=False):
        self.path = path
        self.tmp = path + ".tmp"
        self.f = open(self.tmp, "wb" if binary else "w")

    def write(self, data):
        return self.f.write(data)

    def commit(self):
        self.f.close()
        _replace_file(self.tmp, self.path)

    def abort(self):
        try:
            self.f.close()
        except OSError:
            pass
        try:
            os.remove(self.tmp)
        except OSError:
            pass


def _pin_key(text):
    """Turns a command's pin argument into a dict key for _pins/etc -
    "LED" (any case) maps to the string "LED", anything else must
    parse as a plain GPIO number. Returns None for neither, so
    callers can report "pin must be a number or LED" uniformly."""
    if text.upper() == "LED":
        return "LED"
    try:
        return int(text)
    except ValueError:
        return None


def _make_led_pin(mode):
    """The onboard LED is GPIO25 on a plain Pico, but a named "LED"
    pin on the Pico W (its LED is wired through the wifi chip, not a
    normal GPIO) - try the portable name first, fall back to the
    number for boards where "LED" isn't a valid Pin identifier."""
    try:
        return machine.Pin("LED", mode)
    except (TypeError, ValueError):
        return machine.Pin(25, mode)


def _load_config():
    """Reads /etc/anix.conf (settings) and then /etc/profile (shell
    environment, aliases) into ENV at startup - a value in profile wins.
    Only understands plain "export KEY=VALUE" (or bare "KEY=VALUE")
    lines and "alias" lines - no real shell syntax, no $VAR expansion
    within the files. Any line that doesn't parse is just skipped, so
    one bad line can't stop the shell from booting."""
    gc.collect()                # settings stay in RAM: pack them low
    _load_settings(CONF)
    if not SAFE and _on("PROFILE"):
        _load_settings(PROFILE)
    global TERM_WIDTH
    try:
        TERM_WIDTH = int(ENV.get("COLUMNS", "80"))
    except ValueError:
        TERM_WIDTH = 80


def _on(key):
    """A start-up switch in anix.conf (PROFILE, STARTUP, CRONTAB,
    HISTORY):
    on unless set to off."""
    return ENV.get(key, "on").lower() != "off"


def _load_settings(path):
    """One line at a time - comments never sit in RAM, and no whole-file
    copy is left as holes between the settings that stay."""
    try:
        f = open(path)
    except OSError:
        return
    with f:
        _settings_from(f)


def _settings_from(f):
    for line in f:
        try:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("alias "):
                _set_alias(line[6:].strip())
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]     # WIFI_PASS="my pass"
            ENV[key.strip()] = value
        except Exception:
            continue


# --- builtins (need the shell's own process state - cd/export/etc
# can't be separate exec'd files any more than they can in real sh) --

def cmd_cd(args, cwd):
    """Changes directory, or goes to $HOME with no argument. Has to
    be a builtin, not a /bin file: os.chdir() changes the process's
    actual working directory, and a /bin command is exec'd into a
    throwaway namespace that vanishes the instant it returns - only
    code that runs in the shell's own persistent frame (this
    function) can make a directory change that's still in effect for
    the *next* command."""
    target = _join(cwd, args[0]) if args else ENV.get("HOME", "/root")
    if not _is_dir(target):
        _err("path not found", target)
        return cwd
    if _current_thread_ident() == _MAIN and _capture_buf is None:
        # only the prompt's own thread moves the process's directory: a
        # background job or cron keep their cwd to themselves
        try:
            os.chdir(target)
            return os.getcwd()
        except OSError:
            _err("path not found", target)
            return cwd
    return target


def cmd_pwd(args, cwd):
    _out(cwd)


def cmd_echo(text, cwd):
    """Takes the raw, un-tokenized remainder of the line (everything
    after the mandatory single space following "echo"), not a
    pre-split args list - a plain word-split collapses intentional
    multi-space formatting (column-aligned text, indentation) down
    to single spaces, which is fine for arguments in general but
    defeats the point of what's being echoed. Trade-off: unlike
    other commands' arguments, echo's text does not glob-expand
    */? - there'd be no way to tell a literal * in text apart from
    a pattern once tokenization is gone.
    Quotes are removed (spacing inside and outside them is kept), and
    a > or >> inside quotes is plain text, not a redirection."""
    body = []
    quote = None
    target = None
    mode = None
    k = 0
    while k < len(text):
        ch = text[k]
        if quote:
            if ch == quote:
                quote = None
            else:
                body.append(ch)
        elif ch == '"' or ch == "'":
            quote = ch
        elif ch == ">" and body and body[-1] == "2" and (len(body) == 1 or body[-2] == " "):
            # 2> / 2>> / 2>&1: echo has no errors to send anywhere - drop it
            body.pop()
            while body and body[-1] == " ":
                body.pop()
            k += 1
            while k < len(text) and text[k] in ">&":
                k += 1
            while k < len(text) and text[k] == " ":
                k += 1
            while k < len(text) and text[k] != " ":
                k += 1
            continue
        elif ch == ">":
            mode = "a" if text[k + 1:k + 2] == ">" else "w"
            target = text[k + (2 if mode == "a" else 1):].strip()
            if len(target) > 1 and target[0] in "\"'" and target[-1] == target[0]:
                target = target[1:-1]
            elif " " in target:
                target = target.split()[0]  # echo hi > f 2>/dev/null
            break
        else:
            body.append(ch)
        k += 1
    line = _unprotect("".join(body))
    if quote:
        line = _unprotect(text)     # unclosed quote (echo it's): print it as typed
    target = _unprotect(target) if target else target
    if mode is None:
        _out(line)
        return
    if not target:
        _err("usage: echo [text] > file   or   echo [text] >> file")
        return
    if _join(cwd, target) == "/dev/null":
        return
    try:
        if mode == "w":
            f = _SafeFile(_join(cwd, target))
            try:
                f.write(line.rstrip() + "\n")
            except BaseException:
                f.abort()
                raise
            f.commit()
        else:
            with _open_append(_join(cwd, target)) as f:
                f.write(line.rstrip() + "\n")
    except OSError as e:
        _err("could not write to file", e)


def _set_alias(text):
    name, eq, value = text.partition("=")
    name = name.strip()
    value = value.strip()
    if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
        value = value[1:-1]
    if not eq or not name or " " in name:
        return False
    ALIASES[name] = value
    return True


_ARG_KEYS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "#", "@")


def _push_args(name, args):
    """Sets $0 $1..$9 $# $@ for a script or function; returns what they
    were, for _pop_args."""
    saved = {}
    for k in _ARG_KEYS:
        saved[k] = ENV.pop(k, None)
    ENV["0"] = name
    for k, v in enumerate(args[:9], 1):
        ENV[str(k)] = v
    ENV["#"] = str(len(args))
    ENV["@"] = " ".join(args)
    return saved


def _pop_args(saved):
    for k in _ARG_KEYS:
        if saved.get(k) is None:
            ENV.pop(k, None)
        else:
            ENV[k] = saved[k]


def cmd_source(args, cwd):
    """`. file` / `source file`: runs a script in this shell. Every
    A-NIX script already runs that way (its variables, functions, cd
    and aliases stay afterwards - there are no subshells), so this is
    the same as running it by name, but works for any file name and
    never searches $PATH."""
    if not args:
        _out("usage: source <file.sh>   (or . <file.sh>)")
        return cwd
    return _run_batch(_join(cwd, args[0]), cwd, args[1:])


# --- exec: everything that isn't a builtin lives in /bin and is
# found via $PATH, exactly like a real *NIX shell resolves commands --

def _exec_pyfile(path, args, cwd):
    """This is what makes /bin a real *NIX-style $PATH instead of a
    disguised if/elif chain: reads a command file's source and
    exec()s it into a fresh, throwaway globals dict (g) - not a real
    Python import, deliberately. A normal `import` would cache the
    module in sys.modules and keep its state alive for the rest of
    the session; exec() here means every invocation starts clean and
    every bit of memory it used is eligible for garbage collection
    the moment this function returns. That's also why a command
    needing state across separate calls (a UART bus, a configured
    GPIO pin) can't keep it in its own file - it has to live in
    shell.py's own globals instead, since shell.py is the one module
    that actually stays imported for the whole session (see the
    _pins/_uarts/etc. comment near the top of this file).

    After exec'ing the source, looks for a top-level `run(args, cwd)`
    function in what it just defined and calls it - that's the one
    convention every /bin command file has to follow. A returned
    string is treated as the new cwd - a program can change the
    shell's folder that way (`cd` itself is a builtin)."""
    g = {"__name__": "__main__", "ENV": ENV, "input": _input_line}
    fs_begin()
    try:
        with open(path) as f:
            src = f.read()
    finally:
        fs_end()
    exec(src, g)
    fn = g.get("run")
    if callable(fn):
        result = fn(args, cwd)
        if isinstance(result, str):
            return result
    return cwd


def _import_file(path):
    """Loads a compiled .mpy program as a module and returns it - the
    .mpy counterpart of reading and exec'ing a .py file's source.

    A .mpy file has no source text to exec, so it has to go through
    import: the file's folder is put on sys.path just for this
    import, and the module is taken out of sys.modules again by
    _unload() afterwards, so the next run starts fresh (same as an
    exec'd .py command) and its memory can be freed.

    Refuses a name that is already a different module (shell, net, os,
    time, ...): importing it would hand back that module instead, or
    replace a library the shell depends on. Rename the program."""
    folder, name = path.rsplit("/", 1)
    name = name[:-4]                     # strip .mpy
    old = sys.modules.get(name)
    if old is not None:
        if getattr(old, "__file__", "") != path:
            # never replace a loaded module (it may hold live state)
            raise ImportError("%s.mpy clashes with the module %s - rename it" % (name, name))
        del sys.modules[name]            # left over from an earlier run
    # at the END of the path, so /lib modules win over same-named files
    # in the program's folder while it imports what it needs
    sys.path.append(folder or "/")
    fs_begin()
    try:
        mod = __import__(name)
    finally:
        fs_end()
        sys.path.pop()
    if getattr(mod, "__file__", "") != path:
        # another module of the same name answered (built-in, or /lib)
        _unload(name, mod)
        raise ImportError("%s.mpy clashes with the built-in module %s - rename it" % (name, name))
    return mod


def _unload(name, mod):
    if sys.modules.get(name) is mod:
        del sys.modules[name]


def _exec_mpy(path, args, cwd):
    """Runs a compiled .mpy command: imports it (see _import_file),
    calls its run(args, cwd) like any .py command, then unloads it.
    A returned string is the new cwd, same convention as .py."""
    mod = _import_file(path)
    name = path.rsplit("/", 1)[1][:-4]
    try:
        mod.ENV = ENV
        mod.input = _input_line
        fn = getattr(mod, "run", None)
        if callable(fn):
            result = fn(args, cwd)
            if isinstance(result, str):
                return result
        return cwd
    finally:
        _unload(name, mod)


def _find_executable(orig_name, cwd):
    """cwd-relative (or absolute) first, then $PATH (default /bin) -
    a name with "/" in it is never PATH-searched, same as real sh.
    Directories never count as a command (a folder called `ls` in
    cwd must not hide /bin/ls)."""
    def candidates_for(base):
        # .py before .mpy: while you still have both, the editable
        # source wins - same order MicroPython's own import uses
        if base.endswith(".sh") or base.endswith(".py") or base.endswith(".mpy"):
            return (base,)
        # never the bare name: a data file called `cat` in cwd must
        # not hide /bin/cat
        return (base + ".sh", base + ".py", base + ".mpy")

    def is_file(c):
        try:
            return not (os.stat(c)[0] & 0x4000)
        except OSError:
            return False

    for c in candidates_for(_join(cwd, orig_name)):
        if is_file(c):
            return c

    if "/" not in orig_name:
        for d in ENV.get("PATH", "/bin").split(":"):
            d = d.strip()
            if not d:
                continue
            base = d.rstrip("/") + "/" + orig_name
            for c in candidates_for(base):
                if is_file(c):
                    return c
    return None


def _tokenize(line):
    """Splits a command line into (text, quoted) pairs. Double or
    single quotes group words into one argument and are removed:
    `grep "two words" f.txt` gives grep the two words as one
    argument. A quoted argument is never glob-expanded and never
    taken as a > / >> redirection. ($VARs are expanded before this,
    inside quotes too.)"""
    toks = []
    cur = []
    quote = None
    quoted = False
    have = False
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch == '"' or ch == "'":
            quote = ch
            quoted = True
            have = True
        elif ch == " " or ch == "\t":
            if have:
                toks.append(("".join(cur), quoted))
                cur = []
                quoted = False
                have = False
        else:
            cur.append(ch)
            have = True
    if have:
        toks.append(("".join(cur), quoted))
    return toks


def _split_redirect(toks, take_input=True):
    """Pulls the redirections out of the tokens:
        > f   >> f   (also >f, >>f)      output
        2> f  2>> f  (also 2>f)          errors
        2>&1                             errors go where output goes
        < f   (also <f)                  input (when take_input)
    Returns (remaining_tokens, out, err, inp): out is (target, mode) or
    None, err is (target, mode), 1 (for 2>&1) or None, inp a file name
    or None - or out is the string "missing" if a > or < has no file
    name after it."""
    rest = []
    out = None
    err = None
    inp = None
    i = 0
    while i < len(toks):
        text, quoted = toks[i]
        if not quoted and text == "2>&1":
            err = 1
        elif not quoted and take_input and text.startswith("<"):
            inp = text[1:]
            if not inp:
                if i + 1 >= len(toks):
                    return rest, "missing", None, None
                i += 1
                inp = toks[i][0]
        elif not quoted and (text.startswith(">") or text.startswith("2>")):
            is_err = text.startswith("2>")
            body = text[1:] if is_err else text
            mode = "a" if body.startswith(">>") else "w"
            target = body[2:] if mode == "a" else body[1:]
            if not target:
                if i + 1 >= len(toks):
                    return rest, "missing", None, None
                i += 1
                target = toks[i][0]
            if is_err:
                err = (target, mode)
            else:
                out = (target, mode)
        else:
            rest.append(toks[i])
        i += 1
    return rest, out, err, inp


def _split_pipes(line):
    """Splits a line at every | outside quotes. Returns the list of
    segments (a line without | gives one segment)."""
    segs = []
    cur = []
    quote = None
    depth = 0               # inside $( ... ): not our pipe
    prev = ""
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch == '"' or ch == "'":
            quote = ch
        elif ch == "(" and (prev == "$" or depth):
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "|" and not depth:
            segs.append("".join(cur))
            cur = []
            prev = ch
            continue
        cur.append(ch)
        prev = ch
    segs.append("".join(cur))
    return segs


def _dispatch(cmdline, cwd):
    """Runs one command line. In order: a trailing & starts the whole
    line as a background job; ; && || split it into commands run one
    after another (&& only if the previous one succeeded, || only if
    it failed - by $?); each of those may be a pipeline `a | b | c`: each command's output becomes the next one's input
    (see _PipeBuf; commands that read text - cat, grep, head, tail,
    wc, hexdump, sha256 - read it when given no file). Errors still
    go to the screen. Returns (new_cwd, still_running)."""
    if ALIASES:
        word = cmdline.split(None, 1)[:1]
        if word and word[0] in ALIASES and any(c in ALIASES[word[0]] for c in "|;&"):
            cmdline = _apply_alias(cmdline.strip())     # alias x="a | b"
    stripped = cmdline.strip()
    if stripped.endswith("&") and not stripped.endswith("&&") \
            and stripped.count('"') % 2 == 0 and stripped.count("'") % 2 == 0:
        if _current_thread_ident() not in (None, _MAIN):
            _err("a background job can't start another one")
            return cwd, True
        import jobctl as jobs
        n, why = jobs.start(stripped[:-1].strip(), cwd)
        if n is None:
            _err(why)
        else:
            _put_status("0")
            _out("[%d] started - jobs shows it, kill stops it" % n)
        return cwd, True
    chain = _split_chain(cmdline)
    if len(chain) == 1:
        return _dispatch_pipe(chain[0][1], cwd)
    if any(not seg.strip() for _op, seg in chain):
        _err("missing command next to ; && or ||")
        return cwd, True
    running = True
    for op, seg in chain:
        if op == "&&" and _status() != "0":
            continue
        if op == "||" and _status() == "0":
            continue
        cwd, running = _dispatch_pipe(seg, cwd)
        if not running:
            break
    return cwd, running


def _split_chain(line):
    """Splits a line at ; && and || outside quotes. Returns a list of
    (operator_before, segment): the first operator is "" - e.g.
    "a; b && c" -> [("", "a"), (";", " b"), ("&&", " c")]."""
    out = []
    cur = []
    op = ""
    quote = None
    depth = 0               # inside $( ... ): not our operator
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch == '"' or ch == "'":
            quote = ch
        elif ch == "(" and ((i and line[i - 1] == "$") or depth):
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif depth:
            pass
        elif ch == ";":
            out.append((op, "".join(cur)))
            cur = []
            op = ";"
            i += 1
            continue
        elif ch in "&|" and i + 1 < n and line[i + 1] == ch:
            out.append((op, "".join(cur)))
            cur = []
            op = ch + ch
            i += 2
            continue
        cur.append(ch)
        i += 1
    out.append((op, "".join(cur)))
    if len(out) > 1 and out[-1][0] == ";" and not out[-1][1].strip():
        out.pop()                       # "ls;" - a trailing ; is fine
    return out


def _dispatch_pipe(cmdline, cwd):
    """One command, or a pipeline a | b | c."""
    segs = _split_pipes(cmdline)
    if len(segs) == 1:
        return _dispatch_one(cmdline, cwd)
    if any(not s.strip() for s in segs):
        _err("missing command next to |")
        return cwd, True
    me = _current_thread_ident()
    saved_in = _pipe_in.get(me)
    saved_out = _redirects.get(me)
    prev = None
    running = True
    try:
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            buf = None if last else _PipeBuf(i)
            if prev is not None:
                _pipe_in[me] = prev
            elif saved_in is None:
                _pipe_in.pop(me, None)
            if buf is not None:
                _redirects[me] = buf
            elif saved_out is None:
                _redirects.pop(me, None)
            else:
                _redirects[me] = saved_out
            try:
                cwd, running = _dispatch_one(seg, cwd)
            except BaseException:
                if buf is not None:
                    buf.discard()       # Ctrl-C / error: no leftover temp file
                raise
            finally:
                if buf is not None:
                    buf.finish()
                if prev is not None:
                    prev.discard()
            prev = buf
    finally:
        if prev is not None:
            prev.discard()
        if saved_in is None:
            _pipe_in.pop(me, None)
        else:
            _pipe_in[me] = saved_in
        if saved_out is None:
            _redirects.pop(me, None)
        else:
            _redirects[me] = saved_out
    return cwd, running


def _first_words(line):
    """The command word of every command in a line (split at ; && ||
    | &), aliases resolved, lowercased - for jobs and cron to refuse
    commands that need the keyboard anywhere in the line."""
    words = []
    for _op, seg in _split_chain(line):
        for part in _split_pipes(seg):
            for piece in part.split("&"):
                piece = _apply_alias(piece.strip()) if ALIASES else piece.strip()
                w = piece.split(None, 1)[:1]
                if w:
                    words.append(w[0].lower().rsplit("/", 1)[-1].split(".")[0])
    return words


def _apply_alias(line):
    """Replaces the first word with its alias, if it has one (up to 5
    levels, so an alias can use another alias but a loop stops)."""
    for _ in range(5):
        parts = line.split(None, 1)
        if not parts or parts[0] not in ALIASES:
            break
        repl = ALIASES[parts[0]]
        line = repl + ((" " + parts[1]) if len(parts) > 1 else "")
        if repl.split(None, 1)[:1] == parts[:1]:
            break           # alias ls=ls -l: don't expand again
    return line


def _dispatch_one(cmdline, cwd):
    """Runs one command: expand variables, tokenize (quotes
    group words), take out a > / >> redirection, glob-expand any
    unquoted */? arguments, then either call a builtin directly or
    hand off to _exec_or_run for everything else. Called for every
    interactive prompt line and every line of every script - this
    one function is the single place a command actually happens.
    Returns (new_cwd, still_running) - still_running is False only
    for `exit`, which is how the interactive loop in run() (and, for
    a script, _run_batch) knows to stop.

    `echo` is the exception to tokenizing: it gets the raw rest of
    the line (spacing kept) and handles its own > / >>."""
    if _kill and _kill.get(_current_thread_ident()):
        raise _Killed()         # a killed background job stops between commands
    _beat[0] = time.ticks_ms()
    cmdline = cmdline.strip()
    if not cmdline:
        return cwd, True

    if ALIASES:
        cmdline = _apply_alias(cmdline)
    # expanded text is protected: a $VAR holding "a > b" stays text
    cmdline = _expand(cmdline, cwd, True)
    toks = _tokenize(cmdline)
    if not toks:
        return cwd, True
    cmd = _unprotect(toks[0][0]).lower()  # builtins match case-insensitively
    _put_status("0")

    if cmd == "echo":
        k = len(cmdline.split(None, 1)[0])
        cmd_echo(cmdline[k + 1:] if len(cmdline) > k else "", cwd)
        return cwd, True

    if cmd == "let":            # < and > are comparisons there
        redirect = err_redirect = inp = None
    else:
        toks, redirect, err_redirect, inp = _split_redirect(toks)
    if redirect == "missing":
        _err("missing file name after > or <")
        return cwd, True
    if not toks:
        _err("missing command before > or <")
        return cwd, True
    toks = [(_unprotect(t), q) for t, q in toks]
    if redirect:
        redirect = (_unprotect(redirect[0]), redirect[1])
    if err_redirect and err_redirect != 1:
        err_redirect = (_unprotect(err_redirect[0]), err_redirect[1])
    if inp:
        inp = _unprotect(inp)

    args = []
    for text, quoted in toks[1:]:
        if not quoted and ("*" in text or "?" in text):
            args.extend(_glob_expand(cwd, text))
        else:
            args.append(text)

    if inp is not None:
        path = _join(cwd, inp)
        try:
            if os.stat(path)[0] & 0x4000:
                _err("%s is a folder" % inp)
                return cwd, True
        except OSError:
            _err("file not found", inp)
            return cwd, True
        me = _current_thread_ident()
        saved_in = _pipe_in.get(me)
        fin = _FileIn(path)
        _pipe_in[me] = fin
        try:
            return _redirected(cmd, toks, args, cwd, redirect, err_redirect)
        finally:
            fin.discard()
            if saved_in is None:
                _pipe_in.pop(me, None)
            else:
                _pipe_in[me] = saved_in
    return _redirected(cmd, toks, args, cwd, redirect, err_redirect)


def _redirected(cmd, toks, args, cwd, redirect, err_redirect):
    """Runs the command with its > / 2> redirections in place."""
    if redirect is None and err_redirect is None:
        return _run_command(cmd, toks[0][0], args, cwd)

    # > writes a temporary file that replaces the old one only when the
    # command finishes; >> appends directly (a cut-off append loses only
    # the new part - what the file had before stays intact). /dev/null
    # swallows everything.
    def _open(target, mode):
        path = _join(cwd, target)
        if path == "/dev/null":
            return _NullFile()
        return _SafeFile(path) if mode == "w" else _open_append(path)

    me = _current_thread_ident()
    opened = []
    try:
        out_f = _open(*redirect) if redirect is not None else None
        if out_f is not None:
            opened.append(out_f)
        err_f = 1 if err_redirect == 1 else (_open(*err_redirect) if err_redirect else None)
        if err_f not in (None, 1):
            opened.append(err_f)
    except OSError as e:
        for f in opened:
            f.abort() if isinstance(f, _SafeFile) else f.close()
        _err("could not open the redirect file", e)
        return cwd, True
    saved_out = _redirects.get(me)
    saved_err = _err_redirects.get(me)
    if out_f is not None:
        _redirects[me] = out_f
    if err_f is not None:
        _err_redirects[me] = err_f
    ok = False
    try:
        result = _run_command(cmd, toks[0][0], args, cwd)
        ok = True
        return result
    finally:
        if out_f is not None:
            if saved_out is None:
                _redirects.pop(me, None)
            else:
                _redirects[me] = saved_out  # a script line inside a redirected script
        if err_f is not None:
            if saved_err is None:
                _err_redirects.pop(me, None)
            else:
                _err_redirects[me] = saved_err
        for f in opened:
            if isinstance(f, _SafeFile):
                if ok:
                    try:
                        f.commit()
                    except OSError as e:
                        f.abort()
                        _err("could not write %s" % f.path, e)
                else:
                    f.abort()               # Ctrl-C: keep the old file
            else:
                f.close()


def _call_function(name, args, cwd):
    """Runs a script function (see script.py)."""
    import script
    return script._call_function(name, args, cwd)


def _run_command(cmd, name, args, cwd):
    # true builtins - these touch the shell's own process state
    # (cwd, ENV), so they can't be separate exec'd files any more
    # than they can be in a real *NIX shell.
    if cmd == "exit":
        return cwd, False
    elif cmd == "cd":
        cwd = cmd_cd(args, cwd)
    elif cmd == "pwd":
        cmd_pwd(args, cwd)
    elif cmd in _RARE_BUILTINS:
        import shbuiltin                # loaded only when one is used
        result = getattr(shbuiltin, "cmd_" + cmd)(args, cwd)
        if isinstance(result, str):     # time returns the new cwd
            cwd = result
    elif cmd == "." or cmd == "source":
        cwd = cmd_source(args, cwd)
    elif name in FUNCTIONS:
        return _call_function(name, args, cwd)
    else:
        cwd = _exec_or_run(name, args, cwd)
    return cwd, True


def _dispatch_captured(line, cwd):
    """Runs one command line like _dispatch, but collects its output
    (errors too) instead of showing it - returns (text, new_cwd). Used
    by cron, whose jobs write to /var/log/cron.log, never the screen."""
    global _capture_buf, _capture_owner
    if _capture_lock:
        _capture_lock.acquire()
    try:
        _capture_buf = []
        _capture_owner = _current_thread_ident()
        try:
            new_cwd, _running = _dispatch(line, cwd)
        except Exception as e:
            _capture_buf.append("error: %s\n" % e)
            new_cwd = cwd
        text = "".join(_capture_buf)
    finally:
        _capture_buf = None
        _capture_owner = None
        if _capture_lock:
            _capture_lock.release()
    return text, new_cwd


def _exec_or_run(orig_name, args, cwd):
    """Not a builtin - resolve via _find_executable (cwd, then
    $PATH/bin) and run it, the same as a real shell execing a
    command it found on PATH."""
    found = _find_executable(orig_name, cwd)
    base = orig_name.rsplit("/", 1)[-1].split(".")[0].lower()
    if base in _KEYBOARD_COMMANDS and found and found.startswith("/bin/") and _no_keyboard() \
            and not (base == "nc" and (_piped() or "-u" in args)):
        _err("%s needs the keyboard and screen - run it at the prompt" % base)
        return cwd
    if found and _pin_lock is not None and base in _PIN_COMMANDS and not _in_lib(found) \
            and _pin_holder[0] != _current_thread_ident():   # not twice (pins.sh -> pins)
        _pin_lock.acquire()
        _pin_holder[0] = _current_thread_ident()
        try:
            return _run_found(found, orig_name, args, cwd)
        finally:
            _pin_holder[0] = None
            _pin_lock.release()
    return _run_found(found, orig_name, args, cwd)


def _exit_status(e):
    """sys.exit(n) in a program ends just that program: n is its $?."""
    code = e.args[0] if e.args else 0
    if code is None:
        code = 0
    elif not isinstance(code, int):
        _err(str(code))
        code = 1
    _set_status(code)


def _run_found(found, orig_name, args, cwd):
    if found and _in_lib(found):
        _err("%s is a library module, not a command" % found)
    elif found and found.endswith(".py"):
        try:
            cwd = _exec_pyfile(found, args, cwd)
        except SystemExit as e:
            _exit_status(e)
        except MemoryError:
            gc.collect()
            _err("out of memory running %s" % orig_name)
        except Exception as e:
            _err("%s failed" % orig_name, e)
        gc.collect()
    elif found and found.endswith(".mpy"):
        try:
            cwd = _exec_mpy(found, args, cwd)
        except SystemExit as e:
            _exit_status(e)
        except MemoryError:
            gc.collect()
            _err("out of memory running %s" % orig_name)
        except Exception as e:
            _err("%s failed" % orig_name, e)
        gc.collect()
    elif found and found.endswith(".sh"):
        cwd = _run_batch(found, cwd, args)
    elif found:
        _err("%s is not a command (only .py, .mpy and .sh files run)" % found)
    else:
        _err("command not found", orig_name)
    return cwd


# --- shell scripting lives in /lib/script.py: loaded the first time a
# script, function or `.` runs (and dropped again when RAM runs low).

def _run_batch(path, cwd, args=None):
    """Runs a .sh script - see script.py."""
    import script
    return script._run_batch(path, cwd, args)


# Modules that hold no state of their own, dropped from RAM when free
# memory runs low and loaded again by the next command that needs them -
# big and rarely used ones, biggest first. Only as many as needed go:
# every unload and reload leaves holes in the RAM.
_UNLOADABLE = ("editor", "script", "syntax", "tui", "view", "hexfmt")
# Small ones used all the time (Tab, cron's log, export/history, $(..),
# cp -r): unloading them saves little and they'd be back at once, so
# they go only when RAM has run out completely (MemoryError).
_KEEP = ("logs", "tabcomp", "shbuiltin", "subst", "fileops")
_ram_low = [False]


def _mem_low_limit():
    try:
        return int(ENV.get("MEM_LOW", "24576"))
    except ValueError:
        return 24576


def _background_busy():
    jobs = sys.modules.get("jobctl")
    tasks = sys.modules.get("tasksched")
    return bool((jobs and jobs.running()) or (tasks and tasks.running())
                or _capture_buf is not None)


def _trim_memory(everything=False):
    """After every command at the prompt: collect garbage, and if free
    RAM is under MEM_LOW, unload modules from _UNLOADABLE, biggest
    first, until a third above MEM_LOW is free again (not while a
    background job, tasks or a cron job might be using them).
    everything=True (out of memory): _KEEP goes too. Sets the flag the
    prompt shows as (low RAM) - on below MEM_LOW, off again only above
    MEM_LOW + a third, so it doesn't flip with every command."""
    gc.collect()
    if not hasattr(gc, "mem_free"):
        return
    low = _mem_low_limit()
    enough = low + low // 3
    free = gc.mem_free()
    if (free < low or everything) and not _background_busy():
        for name in _UNLOADABLE + (_KEEP if everything else ()):
            if sys.modules.pop(name, None) is not None:
                gc.collect()
                free = gc.mem_free()
                if free >= enough and not everything:
                    break
    if free < low:
        _ram_low[0] = True
    elif free >= enough:
        _ram_low[0] = False


def _build_prompt(cwd):
    """Default prompt is "cwd $ " (classic *NIX style), with [N] while
    background job N runs and (N) while N scheduler tasks run. PS1, if
    set, is expanded (so $VAR/$((expr)) work in it) with the literal
    "\\w" replaced by cwd and "\\j" by those markers."""
    color = ENV.get("COLOR", "on").lower() != "off"

    def paint(code, text):
        return ("\x1b[%sm%s\x1b[0m" % (code, text)) if color else text
    marks = ""
    if "jobctl" in sys.modules and sys.modules["jobctl"].running():
        marks += " " + paint(YELLOW, "[%d]" % sys.modules["jobctl"].job["n"])
    if "tasksched" in sys.modules:
        n = sys.modules["tasksched"].count()
        if n:
            marks += " " + paint(CYAN, "(%d)" % n)
    if _ram_low[0]:
        marks += " " + paint(RED, "(low RAM)")
    template = ENV.get("PS1")
    if not template:
        return paint(BLUE_BOLD, cwd) + marks + " $ "
    return _expand(template).replace("\\w", cwd).replace("\\j", marks.strip()) + " "


_BUILTINS = ("cd", "pwd", "echo", "export", "unset", "read", "let", "exit",
             "alias", "unalias", "history", "time", "source")
# builtins kept in /lib/shbuiltin.py, loaded only when used
_RARE_BUILTINS = ("export", "unset", "read", "let", "alias", "unalias", "history", "time")
LIB_DIRS = ("/lib",)    # modules, not commands - never run or offered as one


def _in_lib(path):
    folder = path.rsplit("/", 1)[0] or "/"
    return folder in LIB_DIRS


def _complete(before, cwd):
    """Tab key: the completion itself is in /lib/tabcomp.py."""
    import tabcomp
    return tabcomp.complete(before, cwd)


def _job_news(nl):
    """New output lines of the background job ([N] in front) and, once
    it has ended, its done notice - as one text ending in nl, or ""."""
    jobs = sys.modules.get("jobctl")
    if jobs is None or jobs.job is None:
        return ""
    lines = []
    n = jobs.job["n"]
    for line in jobs.new_output(max_lines=40):
        lines.append("[%d] %s" % (n, line))
    if jobs.job["state"] != "running":
        try:
            left = os.stat(jobs.LOG)[6] - jobs.job["shown"]
        except OSError:
            left = 0
        if left > 0:                    # don't flood the screen at the end
            jobs.job["shown"] += left
            lines.append("[%d] ... %d more bytes in %s" % (n, left, jobs.LOG))
        for j in jobs.finished():
            lines.append(jobs.describe(j))
    return (nl.join(lines) + nl) if lines else ""


def _history_file():
    path = ENV.get("HISTFILE", "")
    if path.lower() == "none" or not _on("HISTORY"):
        return None
    return path or _join(ENV.get("HOME", "/root"), ".history")


def _history_size():
    if not _on("HISTORY"):
        return 0                # HISTORY=off: none in RAM, none saved
    try:
        return max(0, int(ENV.get("HISTSIZE", "50")))
    except ValueError:
        return 50


def _load_history():
    """Last HISTSIZE lines of HISTFILE. The file is only appended to
    while the shell runs; it is trimmed back here, at shell start,
    once it grows past twice HISTSIZE."""
    path = _history_file()
    size = _history_size()
    if not path or size == 0:
        return []
    # two passes: count, then keep only the last `size` lines - the
    # older ones are never held, so they leave no holes behind
    try:
        with open(path) as f:
            total = 0
            for ln in f:
                if ln.strip():
                    total += 1
            f.seek(0)
            skip = total - size
            lines = []
            for ln in f:
                if ln.strip():
                    if skip > 0:
                        skip -= 1
                    else:
                        lines.append(ln.rstrip("\n"))
    except OSError:
        return []
    if total > 2 * size:
        try:
            with open(path, "w") as f:
                for ln in lines:
                    f.write(ln + "\n")
        except OSError:
            pass
    return lines[-size:]


def _save_history_line(line):
    path = _history_file()
    if not path or _history_size() == 0:
        return
    for _ in range(2):
        try:
            fs_begin()
            try:
                with open(path, "a") as f:
                    f.write(line + "\n")
            finally:
                fs_end()
            return
        except OSError:
            # folder missing (e.g. HISTFILE=/var/history on a fresh board)
            cur = ""
            for part in path.split("/")[1:-1]:
                cur += "/" + part
                try:
                    os.mkdir(cur)
                except OSError:
                    pass


def run():
    """Entry point called by main.py when the shell is selected at
    boot. Starts from a clean ENV and $? every time (this module stays
    imported, so without the reset a restarted shell would inherit the
    previous session's variables), loads /etc/profile, cd's to $HOME,
    runs /etc/startup as a script, then loops reading and dispatching
    lines until `exit` - then returns, and main.py starts a fresh
    shell. The prompt has history (Up/Down, saved to HISTFILE) and
    Tab completion - see lineedit.py. Ctrl-C while a command runs
    stops that command; Ctrl-C at the prompt leaves to the raw
    MicroPython REPL.

    Ctrl-C is MicroPython's keyboard interrupt, so it can arrive
    anywhere - even inside a command's own cleanup. A command that
    must always clean up (switch something off) should use
    try/finally, which still runs."""
    global _last_status
    ENV.clear()
    ALIASES.clear()
    FUNCTIONS.clear()
    _last_status = "0"
    _load_config()
    if ENV.get("WATCHDOG", "off").lower() == "on" and not SAFE:
        try:
            gc.collect()
            import watchdog
            why = watchdog.start(ENV.get("WATCHDOG_HANG"))
        except Exception as e:
            why = str(e)
        if why:
            wd_note = "watchdog: " + why
        else:
            wd_note = None
    else:
        wd_note = None
    try:
        os.chdir(ENV.get("HOME", "/root"))
    except OSError:
        pass
    cwd = os.getcwd()
    global TERM_WIDTH
    if "COLUMNS" not in ENV:
        try:
            import lineedit
            TERM_WIDTH, _rows = lineedit.terminal_size()
        except Exception:
            pass
    sys.stdout.write("\x1b[2J\x1b[H")
    _out(_banner())
    _out("(c) 2026 %s. MIT License - type 'license' for details." % AUTHOR)
    _out("type help for a list of commands, man for the full guide.")
    _out()
    if NOTICE:
        _out(_c(YELLOW, NOTICE))
        _out()
    if wd_note:
        _err(wd_note)

    if not SAFE and _on("STARTUP"):
        try:
            cwd = _run_batch(_join(cwd, STARTUP), cwd)
        except KeyboardInterrupt:
            _out("^C - startup script stopped")

    import lineedit
    tick = None
    try:
        if not SAFE and _on("CRONTAB"):
            gc.collect()        # the jobs stay in RAM: pack them low
            import crond as cron
            cron.load()
            cron.boot()
            tick = cron.tick
    except ImportError:
        pass
    except Exception as e:
        _err("cron", e)

    def idle():
        """Called by the line editor about once a second at an idle
        prompt: runs due cron jobs, and returns the background job's new
        output (and its done notice) to be printed above the prompt."""
        _beat[0] = time.ticks_ms()
        uptime_ms()
        tel = sys.modules.get("telnetsrv")
        if tel is not None:
            tel.poll()                  # a telnet client waiting to connect
        ts = sys.modules.get("tasksched")
        if ts is not None:
            ts.flush()                  # tasks' print() output, RAM -> log
        if tick is not None:
            tick()
        return _job_news("\r\n")
    gc.collect()                # history stays in RAM: pack it low
    HISTORY[:] = _load_history()
    history = HISTORY
    hist_max = _history_size()

    running = True
    while running:
        news = _job_news("\n")
        if news:
            _write(news)
        # Ctrl-C here, at the prompt, is not caught: it leaves to the
        # raw REPL (Thonny and mpremote rely on that to connect)
        try:
            line = lineedit.readline(lambda: _build_prompt(cwd), history,
                                     lambda before: _complete(before, cwd), TERM_WIDTH, idle)
        except MemoryError:
            # even the prompt couldn't get RAM: free what we can, retry
            HISTORY[:] = HISTORY[-10:]
            _trim_memory(True)
            _write("\nout of memory - history shortened, unused modules unloaded\n")
            continue
        stripped = line.strip()
        if stripped.startswith("!") and len(stripped) > 1:
            import shbuiltin
            recalled = shbuiltin.history_recall(stripped)
            if recalled is None:
                continue
            _out(recalled)
            line = stripped = recalled
        if stripped and hist_max and (not history or history[-1] != stripped):
            history.append(stripped)
            if len(history) > hist_max:
                del history[0]
            _save_history_line(stripped)
        try:
            cwd, running = _dispatch(line, cwd)
        except KeyboardInterrupt:
            # Ctrl-C while a command runs stops just that command
            _write("^C\n")
            _set_status(130)
        except SystemExit as e:
            _exit_status(e)
        except MemoryError:
            gc.collect()
            _err("out of memory")
        except Exception as e:
            # mirrors _batch_exec_line's same protection - one bad
            # command shouldn't kill the whole interactive session
            _err("shell error", e)
        try:
            _trim_memory()
        except MemoryError:
            pass

    _out("restarting shell.")
