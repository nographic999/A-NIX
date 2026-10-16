"""cut - take out columns of each line.

  cut -f LIST [-d SEP] [file]   fields split at SEP (default: tab;
                                -d " " for spaces, -d , for CSV)
  cut -c LIST [file]            characters
  ... | cut ...

LIST: numbers from 1 - "2", "1,3", "2-4", "3-" (3 to the end).
Example: cat data.csv | cut -d , -f 2
"""

import shell


def _ranges(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.append((int(a) if a else 1, int(b) if b else None))
        else:
            n = int(part)
            out.append((n, n))
    for a, b in out:
        if a < 1 or (b is not None and b < a):
            raise ValueError
    return out


def _pick(items, ranges):
    picked = []
    for a, b in ranges:
        picked.extend(items[a - 1:b])
    return picked


def run(args, cwd):
    mode = None
    spec = None
    sep = "\t"
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-f", "-c") and i + 1 < len(args):
            mode, spec = a[1], args[i + 1]
            i += 2
        elif a == "-d" and i + 1 < len(args):
            sep = args[i + 1]
            i += 2
        else:
            files.append(a)
            i += 1
    if mode is None:
        shell._out("usage: cut -f LIST [-d SEP] <file>  |  cut -c LIST <file>")
        return
    if not sep:
        shell._err("-d needs a separator character")
        return
    try:
        ranges = _ranges(spec)
    except ValueError:
        shell._err("LIST is like 2, 1,3, 2-4 or 3- (counting from 1)")
        return
    try:
        f = shell._input(cwd, files[0] if files else None)
    except OSError:
        shell._err("file not found", shell._join(cwd, files[0]))
        return
    if f is None:
        shell._out("usage: cut -f LIST [-d SEP] <file>  |  cut -c LIST <file>")
        return
    with f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if mode == "c":
                shell._out("".join(_pick(list(line), ranges)))
            elif sep not in line:
                shell._out(line)            # like real cut: no separator, whole line
            else:
                shell._out(sep.join(_pick(line.split(sep), ranges)))
