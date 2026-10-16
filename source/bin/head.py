"""head - print the first lines (default 10).

  head [-n N | -N] <file>        ... | head [-n N]
"""

import shell


def run(args, cwd):
    n = 10
    if args and args[0][:1] == "-" and args[0][1:].isdigit():
        n, args = int(args[0][1:]), args[1:]       # head -5 = head -n 5
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
        shell._out("usage: head [-n N] <file>")
        return
    with f:
        for i, line in enumerate(f):
            if i >= n:
                break
            shell._write(line if line.endswith("\n") else line + "\n")
