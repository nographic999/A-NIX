"""jobs - one background job: `command &` runs it on core 1 while the
shell stays free on core 0.

The Pico has two cores: core 0 runs the shell, core 1 is free for
ONE extra program - also used by the task scheduler and your own
programs (all started through /lib/core1.py). So:
  - one background job at a time
  - not while tasks or another core-1 program run
  - its output is kept in RAM and written to /var/log/job.log by the
    shell on core 0 (core 1 never writes the log - two cores in the
    filesystem at once can freeze the board), unless the command has
    its own > or >>; the shell shows new lines of it above the prompt
    while you aren't typing, and `jobs -f` follows it live
  - commands that need the keyboard or the screen are refused
  - `kill` stops it at its next line of output or before its next
    command (a command busy without printing - a long wget - ends
    first)
  - its $? is its own; when it ends, the shell says so at the next
    prompt
Everything is lost on a soft reset or reboot, like any running
command.
"""

import time
import shell

try:
    import _thread
except ImportError:
    _thread = None

LOG = "/var/log/job.log"
_REFUSED = ("edit", "whiptail", "python", "choice", "read", "uartterm",
            "man", "pg", "mkfs", "license", "watch", "clear",
            "exit", "httpd", "telnetd", "nc")

_count = 0
job = None          # the current or last job (dict), or None
_report = []        # finished jobs not yet announced at the prompt


_pending = []       # output the job wrote, not yet in the log file
_plock = _thread.allocate_lock() if _thread else None
_PENDING_MAX = 4096  # RAM held while the shell is busy; more waits a moment


class _RamLog:
    """Where the job's output goes (on core 1): a list in RAM. The
    shell on core 0 moves it to /var/log/job.log (flush()), so only
    core 0 writes the flash. The log stops growing at 4 x LOG_MAX
    (64 KB by default), so a chatty job can't fill the flash - the rest
    of its output is dropped. While the shell is busy with a long
    command and can't flush, a job that has filled _PENDING_MAX waits
    (its next line blocks) instead of using up the RAM."""

    def __init__(self):
        try:
            import logs
            self.room = 4 * logs.limit()
        except ImportError:
            self.room = 65536

    def write(self, text):
        if self.room <= 0:
            return
        self.room -= len(text)
        if self.room <= 0:
            text = "\n[log full - the rest of the output is dropped]\n"
        while _pending_size() > _PENDING_MAX:
            if shell._kill.get(shell._current_thread_ident()):
                raise shell._Killed()
            time.sleep_ms(50)           # the shell on core 0 empties it
        _plock.acquire()
        try:
            _pending.append(text)
        finally:
            _plock.release()

    def close(self):
        pass


def _pending_size():
    _plock.acquire()
    try:
        return sum(len(t) for t in _pending)
    finally:
        _plock.release()


def flush():
    """On core 0: moves the job's buffered output into the log file."""
    if not _pending:
        return
    _plock.acquire()
    try:
        text = "".join(_pending)
        del _pending[:]
    finally:
        _plock.release()
    shell.fs_begin()
    try:
        with open(LOG, "a") as f:
            f.write(text)
    except OSError:
        pass
    finally:
        shell.fs_end()


def running():
    return job is not None and job["state"] == "running"


def core1_busy():
    """What is using core 1, or None (see /lib/core1.py)."""
    import core1
    return core1.busy()


def _run(j):
    me = shell._current_thread_ident()
    shell._kill.pop(me, None)           # never a flag left from an old job
    j["ident"] = me
    if j.get("kill"):
        shell._kill[me] = True          # `kill` came before we started
    out = None
    state, status = "done", "0"
    try:
        # output AND errors go to the log (a command's own > or 2>
        # inside the line still wins while it runs)
        out = _RamLog()
        shell._redirects[me] = out
        shell._err_redirects[me] = out
        shell._dispatch(j["cmd"], j["cwd"])
        status = shell._status()
    except shell._Killed:
        state, status = "killed", "130"
    except BaseException as e:
        state, status = "failed: %r" % e, "1"
    finally:
        shell._redirects.pop(me, None)
        shell._err_redirects.pop(me, None)
        shell._kill.pop(me, None)
        shell._thread_status.pop(me, None)
        if out is not None:
            try:
                out.close()
            except OSError:
                pass
        j["ended"] = time.ticks_ms()
        j["status"] = status
        _report.append(j)
        j["state"] = state              # last: the job counts as running until here


def start(cmd, cwd):
    """Starts cmd in the background. Returns (job_number, "") or
    (None, reason)."""
    global job, _count
    if _thread is None:
        return None, "this firmware has no threads"
    if running():
        return None, "job %d is still running (jobs / kill) - one at a time" % job["n"]
    busy = core1_busy()
    if busy:
        return None, "core 1 is busy with %s - stop it first" % busy
    for word in shell._first_words(cmd):
        if word in _REFUSED:
            return None, "%s can't run in the background" % word
    j = {"n": _count + 1, "cmd": cmd, "cwd": cwd, "state": "running", "status": None,
         "started": time.ticks_ms(), "ended": None, "ident": None,
         "shown": 0}
    # emptied here, not in the thread: the prompt may look for new
    # lines before the thread has even started
    import os
    for d in ("/var", "/var/log"):
        try:
            os.mkdir(d)
        except OSError:
            pass
    try:
        open(LOG, "w").close()
    except OSError as e:
        return None, "can't write %s: %s" % (LOG, e)
    del _pending[:]
    _count += 1
    j["n"] = _count
    job = j
    import core1
    kb, why = core1.start(_run, (j,), "background job %d" % _count, core1.SHELL_SIZES)
    if not kb:
        job["state"] = "failed"
        job["status"] = "1"
        job["ended"] = time.ticks_ms()
        return None, why
    return _count, ""


def kill():
    """Asks the running job to stop. Returns its number, or None."""
    if not running():
        return None
    job["kill"] = True                  # seen by _run if it hasn't started yet
    ident = job["ident"]
    if ident is not None:
        shell._kill[ident] = True
    return job["n"]


def new_output(limit=2048, max_lines=None):
    """Lines the job wrote to its log that haven't been shown yet (whole
    lines only while it runs; everything once it has ended), at most
    max_lines of them. Marks exactly those as shown."""
    j = job
    if j is None:
        return []
    flush()
    try:
        with open(LOG, "rb") as f:
            f.seek(j["shown"])
            data = f.read(limit)
    except OSError:
        return []
    if not data:
        return []
    if j["state"] == "running" or len(data) == limit:
        cut = data.rfind(b"\n")
        if cut >= 0:
            data = data[:cut + 1]
        elif len(data) < limit:
            return []                   # half a line: wait for the rest
        # else one line longer than limit: show it in pieces
    if max_lines is not None:
        k = -1
        for _ in range(max_lines):
            k = data.find(b"\n", k + 1)
            if k < 0:
                break
        if k >= 0:
            data = data[:k + 1]
    j["shown"] += len(data)
    text = data.decode("utf-8", "replace")
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def follow(poll_key):
    """jobs -f: prints the job's output as it comes, until the job ends
    or poll_key() says a key was pressed. Returns why it stopped."""
    while True:
        for line in new_output():
            shell._out(line)
        if job is None or job["state"] != "running":
            for line in new_output():
                shell._out(line)
            return "ended"
        if poll_key(200):
            return "key"


def finished():
    """Jobs that ended since the last call (for the prompt notice)."""
    out = []
    while _report:
        out.append(_report.pop(0))     # one by one: the job may append meanwhile
    return out


def describe(j):
    ms = time.ticks_diff(j["ended"] or time.ticks_ms(), j["started"])
    state = j["state"]
    if state != "running":
        state = "%s [$?=%s]" % (state, j["status"])
    shown = shell._c_status("%-22s" % state, state == "running" or j["status"] == "0")
    where = "   (output: %s)" % LOG
    return "[%d] %s %4ds  %s%s" % (j["n"], shown, ms // 1000, j["cmd"], where)
