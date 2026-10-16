"""tasks - a cooperative scheduler on core 1: several of your own
programs running at the same time, while the shell stays free on
core 0.

    spawn blink.py          start a task
    tasks                   list them
    stop 2  /  stop all     stop one / all

A task is a .py (or .mpy) file with an async run function, which
gives the others a turn at every `await`:

    import asyncio, machine
    async def run(args):
        led = machine.Pin("LED", machine.Pin.OUT)
        while True:
            led.toggle()
            await asyncio.sleep(0.5)

How it works: one asyncio event loop runs in a thread on core 1 and
all tasks share it. Requests from the shell (spawn, stop) go into a
queue the loop picks up, because asyncio objects may only be touched
from the loop's own thread. When the last task ends, the loop and the
thread end too, and core 1 is free again.

Rules for task code:
  - wait with `await asyncio.sleep(...)`, never time.sleep() or a long
    loop without an await: that freezes ALL tasks until it returns
  - print() goes to /var/log/tasks.log, prefixed with the task number
    (core 1 can't share the screen with the shell). It is kept in RAM
    first and written by the shell on core 0 (flush()), so core 1
    never writes the flash; while the shell is busy with a long
    command, more than 4 KB of it is dropped with a note
  - tasks should not use files themselves: two cores in the
    filesystem at once can freeze the board
  - an error ends only that task; it's logged with its traceback
  - args are the words after the file name in `spawn`
Core 1 is shared (see /lib/core1.py): no `cmd &` job or other core-1
program while tasks run, and the other way round. Nothing survives a soft reset or reboot -
start tasks from /etc/startup or with `@boot spawn x.py` in crontab.
"""

import time
import shell

try:
    import _thread
except ImportError:
    _thread = None

LOG = "/var/log/tasks.log"

_tasks = {}         # n -> dict(name, args, state, started, ended, task)
_requests = []      # ("spawn", n, fn, args) / ("stop", n) - for the loop thread
_count = 0
_running = [False]  # the loop thread is alive
_lock = _thread.allocate_lock() if _thread else None   # spawn vs loop shutdown


def count():
    """Tasks that are running (or about to start)."""
    return sum(1 for t in _tasks.values() if t["state"] in ("starting", "running"))


def running():
    return _running[0]


_pending = []       # what tasks printed, not yet in the log file
_plock = _thread.allocate_lock() if _thread else None
_PENDING_MAX = 4096
_dropped = [0]


def _log(text):
    """From core 1: into RAM (flush() writes it on core 0)."""
    if _plock is None:
        import logs
        logs.append(LOG, text)
        return
    _plock.acquire()
    try:
        if sum(len(t) for t in _pending) + len(text) > _PENDING_MAX:
            _dropped[0] += 1
        else:
            _pending.append(text)
    finally:
        _plock.release()


def flush():
    """On core 0 (the idle prompt, `tasks log`): writes what the tasks
    printed to /var/log/tasks.log."""
    if not _pending and not _dropped[0]:
        return
    _plock.acquire()
    try:
        text = "".join(_pending)
        del _pending[:]
        if _dropped[0]:
            text += "[%d message(s) dropped - the shell was busy]\n" % _dropped[0]
            _dropped[0] = 0
    finally:
        _plock.release()
    import logs
    logs.append(LOG, text)


def _printer(n):
    """print() replacement for task n."""
    def p(*args, **kw):
        sep = kw.get("sep", " ")
        end = kw.get("end", "\n")
        _log("[%d] %s%s" % (n, sep.join(str(a) for a in args), end))
    return p


def _load(path, n):
    """Returns the task's async run function, or raises ValueError."""
    if path.endswith(".mpy"):
        mod = shell._import_file(path)
        name = path.rsplit("/", 1)[1][:-4]
        shell._unload(name, mod)        # the task keeps its own reference
        mod.print = _printer(n)
        fn = getattr(mod, "run", None)
    else:
        g = {"__name__": "__task__", "print": _printer(n), "ENV": shell.ENV}
        with open(path) as f:
            src = f.read()
        exec(src, g)
        fn = g.get("run")
    if fn is None:
        raise ValueError("has no run() function")
    if type(fn).__name__ == "function":
        raise ValueError("run() must be `async def run(args):` - a plain function would block all tasks")
    return fn


async def _wrap(n, fn, args):
    import asyncio
    t = _tasks[n]
    t["state"] = "running"
    try:
        try:
            co = fn(args)
        except TypeError:
            co = fn()                   # async def run(): without args
        await co
        t["state"] = "done"
    except asyncio.CancelledError:
        t["state"] = "stopped"
    except Exception as e:
        t["state"] = "failed"
        try:
            import io
            import sys
            buf = io.StringIO()
            sys.print_exception(e, buf)
            _log("[%d] %s failed:\n%s" % (n, t["name"], buf.getvalue()))
        except Exception:
            _log("[%d] %s failed: %r\n" % (n, t["name"], e))
    finally:
        t["ended"] = time.ticks_ms()
        t["task"] = None


async def _main():
    import asyncio
    while True:
        while _requests:
            req = _requests.pop(0)
            if req[0] == "spawn":
                _, n, fn, args = req
                _tasks[n]["task"] = asyncio.create_task(_wrap(n, fn, args))
            elif req[0] == "stop":
                t = _tasks.get(req[1])
                if t is not None and t["task"] is not None:
                    t["task"].cancel()
                    if t["state"] == "starting":
                        # cancelled before its first step: _wrap never
                        # runs, so mark it here or it counts forever
                        t["state"] = "stopped"
                        t["ended"] = time.ticks_ms()
                        t["task"] = None
        _lock.acquire()
        try:
            if not _requests and count() == 0:
                _running[0] = False     # under the lock: a new spawn restarts us
                return
        finally:
            _lock.release()
        await asyncio.sleep_ms(50)


def _loop_thread():
    try:
        import asyncio
        asyncio.run(_main())
    except Exception as e:
        _log("scheduler stopped: %r\n" % e)
        _lock.acquire()
        try:
            _running[0] = False         # crashed: _main didn't clear it
            for t in _tasks.values():
                if t["state"] in ("starting", "running"):
                    t["state"] = "failed"
        finally:
            _lock.release()


def core1_busy():
    """What is using core 1, or None (see /lib/core1.py)."""
    import core1
    return core1.busy()


def spawn(path, args):
    """Starts a task. Returns (n, "") or (None, reason)."""
    global _count
    if _thread is None:
        return None, "this firmware has no threads"
    try:
        import asyncio
        asyncio.sleep_ms
    except (ImportError, AttributeError):
        return None, "this firmware has no asyncio"
    if not _running[0]:
        busy = core1_busy()
        if busy:
            return None, "core 1 is busy with %s - stop it first" % busy
    n = _count + 1
    try:
        fn = _load(path, n)
    except ValueError as e:
        return None, "%s %s" % (path.rsplit("/", 1)[-1], e)
    except SyntaxError as e:
        return None, "%s: syntax error - %s" % (path, e)
    _count = n
    _tasks[n] = {"name": path.rsplit("/", 1)[-1], "args": args, "state": "starting",
                 "started": time.ticks_ms(), "ended": None, "task": None}
    _lock.acquire()
    try:
        _requests.append(("spawn", n, fn, args))
        start = not _running[0]
        if start:
            _running[0] = True
    finally:
        _lock.release()
    if start:
        import core1
        kb, why = core1.start(_loop_thread, (), "the task scheduler (stop all)",
                              core1.SHELL_SIZES)
        if not kb:
            _running[0] = False
            del _requests[:]
            _tasks[n]["state"] = "failed"
            return None, why
    return n, ""


def stop(n=None):
    """Stops task n, or all. Returns how many were asked to stop."""
    hit = 0
    for k, t in _tasks.items():
        if (n is None or k == n) and t["state"] in ("starting", "running"):
            _requests.append(("stop", k))
            hit += 1
    return hit


def listing():
    rows = []
    for k in sorted(_tasks):
        t = _tasks[k]
        secs = time.ticks_diff(t["ended"] or time.ticks_ms(), t["started"]) // 1000
        rows.append(("%3d  %-9s %6ds  %s %s" % (k, t["state"], secs, t["name"],
                                                 " ".join(t["args"]))).rstrip())
    return rows


def forget_finished():
    for k in [k for k, t in _tasks.items() if t["state"] not in ("starting", "running")]:
        del _tasks[k]
