"""seq - print a sequence of numbers, one per line.

  seq LAST            1 .. LAST
  seq FIRST LAST
  seq FIRST STEP LAST

Example: seq 1 5 | tee steps.txt   or in a script with for/while.
Numbers can be decimals (seq 0 0.5 2). At most 10000 lines.
"""

import shell


def _num(text):
    v = float(text)
    return int(v) if v == int(v) and "." not in text else v


def run(args, cwd):
    try:
        if len(args) == 1:
            first, step, last = 1, 1, _num(args[0])
        elif len(args) == 2:
            first, step, last = _num(args[0]), 1, _num(args[1])
        elif len(args) == 3:
            first, step, last = _num(args[0]), _num(args[1]), _num(args[2])
        else:
            raise ValueError
    except (ValueError, OverflowError):
        shell._out("usage: seq LAST | seq FIRST LAST | seq FIRST STEP LAST")
        return
    if step == 0:
        shell._err("step can't be 0")
        return
    if len(args) == 2 and last < first:
        step = -1
    # first + n*step, not a running sum: the Pico's floats are single
    # precision and adding 0.1 ten times misses 1.0
    tol = abs(step) * 1e-4
    n = 0
    while True:
        v = first + n * step
        if (step > 0 and v > last + tol) or (step < 0 and v < last - tol):
            break
        shell._out(("%g" % v) if isinstance(v, float) else v)
        n += 1
        if n >= 10000:
            shell._err("stopped after 10000 numbers")
            break
