"""free - show total/used/free RAM, in kilobytes (1 KB = 1024 bytes)
by default, or in bytes with -b.

  free          total, used, free and the largest free block
  free -b       the same in bytes
  free -m       MicroPython's map of the whole RAM: . = free

gc.collect() runs first so the numbers reflect what's actually
reclaimable right now, not whatever hasn't been swept up yet -
MicroPython's collector runs on demand (when an allocation needs
the space) rather than proactively after every command, so without
forcing a collect here the reading could look falsely tight.

The largest free block is what one big allocation (a core-1 stack,
a file read into RAM) can get: free RAM in pieces adds up, but each
piece must fit on its own. It is found by trying to allocate - so it
is skipped while core 1 runs a program, which then can't be starved
of memory for a moment by this test.
"""

import gc
import sys
import shell


def _core1_busy():
    """True if something runs on core 1 (see /lib/core1.py)."""
    mod = sys.modules.get("core1")
    return mod is not None and mod.busy() is not None


def _largest_block(free):
    """Biggest single allocation that succeeds, to within 256 bytes."""
    lo, hi = 0, free
    while hi - lo > 256:
        mid = (lo + hi) // 2
        try:
            bytearray(mid)              # freed again at once
            lo = mid
        except MemoryError:
            hi = mid
    gc.collect()
    return lo


def run(args, cwd):
    if "-m" in args:
        import micropython
        gc.collect()
        shell._out("RAM map: one character = 16 bytes, . = free,")
        shell._out("letters = used (h = start of an object, = = its rest)")
        micropython.mem_info(1)
        return
    in_bytes = "-b" in args
    gc.collect()
    free = gc.mem_free()
    used = gc.mem_alloc()
    total = free + used
    if in_bytes:
        unit, div = "bytes", 1
    else:
        unit, div = "KB", 1024
    shell._out("%10d %s total" % (total // div, unit))
    shell._out("%10d %s used" % (used // div, unit))
    shell._out("%10d %s free" % (free // div, unit))
    if _core1_busy():
        shell._out("%10s    largest free block: not measured while core 1 runs" % "")
        return
    big = _largest_block(free)
    shell._out("%10d %s largest free block" % (big // div, unit))
