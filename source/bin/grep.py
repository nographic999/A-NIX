"""grep - print the lines that contain a text.

  grep [-i] [-v] [-n] [-c] "text" <file> [file2 ...]
  ... | grep [-i] [-v] [-n] [-c] "text"

  -i  ignore upper/lower case     -v  lines that do NOT contain it
  -n  show line numbers           -c  only count matching lines
  -q  print nothing, only set $? - for scripts: if grep -q x f then

Quote text with spaces. $? is 0 if something matched, 1 if not.
"""

import shell


def _mark(line, needle, ignore_case):
    """The line with every match in bold red (like grep --color)."""
    if not needle:
        return line
    hay = line.lower() if ignore_case else line
    out = []
    k = 0
    while True:
        j = hay.find(needle, k)
        if j < 0:
            break
        out.append(line[k:j])
        out.append("\x1b[01;31m" + line[j:j + len(needle)] + "\x1b[0m")
        k = j + len(needle)
    out.append(line[k:])
    return "".join(out)


def _scan(f, needle, opts, prefix):
    count = 0
    color = shell._colors()
    if color and prefix:
        prefix = "\x1b[35m%s\x1b[36m:\x1b[0m" % prefix[:-1]
    for i, line in enumerate(f, 1):
        hay = line.lower() if "i" in opts else line
        hit = needle in hay
        if "v" in opts:
            hit = not hit
        if hit:
            count += 1
            if "c" not in opts and "q" not in opts:
                num = ("%d:" % i) if "n" in opts else ""
                text = line.rstrip("\n").rstrip("\r")
                if color:
                    if num:
                        num = "\x1b[32m%d\x1b[36m:\x1b[0m" % i
                    if "v" not in opts:
                        text = _mark(text, needle, "i" in opts)
                shell._out(prefix + num + text)
    return count


def run(args, cwd):
    opts = ""
    while args and len(args[0]) > 1 and args[0][0] == "-" and all(c in "ivncq" for c in args[0][1:]):
        opts += args[0][1:]
        args = args[1:]
    if not args:
        shell._out('usage: grep [-i] [-v] [-n] [-c] [-q] "text" <file> [file2 ...]')
        return
    needle = args[0].lower() if "i" in opts else args[0]
    files = args[1:]
    total = 0
    if not files:
        f = shell._input(cwd)
        if f is None:
            shell._out('usage: grep [-i] [-v] [-n] [-c] "text" <file> [file2 ...]')
            return
        with f:
            total = _scan(f, needle, opts, "")
        if "c" in opts and "q" not in opts:
            shell._out(total)
    for name in files:
        path = shell._join(cwd, name)
        try:
            with open(path) as f:
                n = _scan(f, needle, opts, ("%s:" % name) if len(files) > 1 else "")
        except OSError:
            shell._err("file not found", path)
            continue
        total += n
        if "c" in opts and "q" not in opts:
            shell._out(("%s:%d" % (name, n)) if len(files) > 1 else n)
    if total == 0:
        shell._set_status(1)
