"""tail - print the last lines (default 10).

  tail [-n N | -N] <file>        ... | tail [-n N]

Reads once, keeping only the last N lines in memory, so it works on
files of any size.
"""

import shell


def run(args, cwd):
    n = 10
    if args and args[0][:1] == "-" and args[0][1:].isdigit():
        n, args = int(args[0][1:]), args[1:]       # tail -5 = tail -n 5
    elif len(args) >= 2 and args[0] == "-n":
        try:
            n = int(args[1])
        except ValueError:
            shell._err("-n needs a number")
            return
        args = args[2:]
    try:
        f = shell._input(cwd, args[0] if args else None)
    except OSError:
        shell._err("file not found", shell._join(cwd, args[0]))
        return
    if f is None:
        shell._out("usage: tail [-n N] <file>")
        return
    keep = []
    with f:
        if n > 0:
            for line in f:
                keep.append(line)
                if len(keep) > n:
                    del keep[0]
    for line in keep:
        shell._write(line if line.endswith("\n") else line + "\n")
