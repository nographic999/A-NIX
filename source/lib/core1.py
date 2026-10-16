"""core1 - the one place that starts programs on core 1: the background
job (cmd &), the task scheduler (spawn) and your own programs.

    start(fn, args, label)  run fn(*args) on core 1
                            -> (kb, "")   started, with a kb-KB stack
                            -> (0, why)   not started, why says it
    busy()                  what runs on core 1 (its label), or None

Only one program runs on core 1 at a time.

Why one place for this:
  - core 1's stack must be ONE free block of RAM. After WiFi, telnet
    and a while at the prompt the free RAM is in pieces: `free` can
    show plenty while no single piece is 16 KB.
  - MicroPython 1.29 (rp2) has a bug: when start_new_thread can't get
    that block, core 1 stays marked "in use" until the next reset, and
    every later start fails with "core1 in use".
So start() first tests with a bytearray that a free block of that size
exists - 16 KB, else 12, else 8 - frees it, and only then starts the
thread, which gets that block. The firmware is never asked for a stack
it can't have. 8 KB is enough for a simple loop of your own; the
background job and the task scheduler need at least 12 (a script runs
commands several calls deep) and ask for (16, 12) only.

Programs on core 1 should not use files: the filesystem is not safe
with both cores in it at once. Load what's needed on core 0 first and
keep output in RAM (the background job and the task scheduler do that).
"""

import gc

try:
    import _thread
except ImportError:
    _thread = None

SIZES = (16, 12, 8)         # KB, tried in this order (own programs)
SHELL_SIZES = (16, 12)      # jobs and tasks: scripts need the depth
_owner = [None]             # label of what runs on core 1


def busy():
    return _owner[0]


def _block_for(sizes):
    """The biggest size (KB) of which a free block exists, or 0."""
    for kb in sizes:
        gc.collect()
        try:
            bytearray(kb * 1024 + 256)  # + room for the thread's own data
        except MemoryError:
            continue
        gc.collect()                    # free the test block again
        return kb
    return 0


def start(fn, args=(), label="a program", sizes=SIZES):
    """Starts fn(*args) on core 1. Returns (kb, "") or (0, reason)."""
    if _thread is None:
        return 0, "this firmware has no threads"
    if _owner[0] is not None:
        return 0, "core 1 is busy with %s - stop it first" % _owner[0]
    kb = _block_for(sizes)
    if not kb:
        return 0, ("no free block of %d KB in RAM for core 1 (free RAM is in "
                   "pieces) - reboot, and start it before WiFi" % sizes[-1])

    def run_it():
        try:
            fn(*args)
        finally:
            _owner[0] = None            # core 1 is free again

    _owner[0] = label
    old = None
    try:
        old = _thread.stack_size(kb * 1024)
    except (AttributeError, ValueError):
        pass
    try:
        _thread.start_new_thread(run_it, ())
    except BaseException as e:
        _owner[0] = None
        if "in use" in str(e):
            return 0, "core 1 is blocked (a start failed earlier) - reboot"
        return 0, "could not start on core 1: %s" % e
    finally:
        if old is not None:
            try:
                _thread.stack_size(old)
            except (AttributeError, ValueError):
                pass
    return kb, ""
