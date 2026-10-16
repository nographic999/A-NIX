"""watch - run a command again and again.

  watch <seconds> <command> [args...]

Clears the screen, runs the command, waits, repeats - e.g.
`watch 1 in 14` or `watch 2 adc 26`. q or Ctrl-C stops it. Keys are
read while waiting, so Ctrl-C also works over telnet.
"""

import sys
import time
import shell

try:
    import select
except ImportError:
    import uselect as select


def _wait(ms, poll):
    """Waits ms; True if q was pressed. Reading the key is also what
    lets a Ctrl-C from a telnet session interrupt."""
    end = time.ticks_add(time.ticks_ms(), ms)
    while True:
        left = time.ticks_diff(end, time.ticks_ms())
        if left <= 0:
            return False
        if poll.poll(min(left, 100)):
            if sys.stdin.read(1) in ("q", "Q"):
                return True


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: watch <seconds> <command> [args...]")
        return
    try:
        seconds = float(args[0])
    except ValueError:
        shell._err("seconds must be a number")
        return
    if not 0 <= seconds <= 86400:       # ticks_add can't go past ~6 days
        shell._err("seconds must be 0.1 to 86400")
        return
    seconds = max(0.1, seconds)
    # re-quote arguments that contained spaces (the shell removed the quotes)
    line = " ".join(('"%s"' % a) if " " in a else a for a in args[1:])
    if args[1].lower() in ("watch", "exit"):
        shell._err("watch can't run %s" % args[1])
        return
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    while True:
        sys.stdout.write("\x1b[2J\x1b[H")
        shell._out("every %gs: %s   (q or Ctrl-C to stop)" % (seconds, line))
        shell._out()
        try:
            cwd, _running = shell._dispatch(line, cwd)
        except Exception as e:
            shell._err("shell error", e)
        if _wait(int(seconds * 1000), poll):
            return
