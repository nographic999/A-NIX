"""plot - draw numbers as a chart in the terminal.

  plot [-f N] [-d SEP] [-h ROWS] [-b] [file]      ... | plot ...

Reads one number per line - the first number found on the line, or
with -f N the N-th field (split at -d SEP, default comma), so a CSV
from `log` works directly:
    plot -f 2 /root/temp.csv
    seq 1 20 | plot
-h sets the height (default 12 rows), -b draws bars instead of
points. More values than fit across the screen are averaged into
columns. Below the chart: how many values, min, max, average.
Plain ASCII, so it works in any terminal.
"""

import shell


def _first_number(text):
    num = ""
    for ch in text + " ":
        if ch.isdigit() or (ch in "+-." and not num) or (ch in ".eE" and num) or \
                (ch in "+-" and num and num[-1] in "eE"):
            num += ch
        elif num:
            try:
                return float(num)
            except ValueError:
                num = ""
    return None


def run(args, cwd):
    field = None
    sep = ","
    rows = 12
    bars = False
    files = []
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == "-f":
                field = int(args[i + 1])
                i += 2
            elif a == "-d":
                sep = args[i + 1] or None   # "" -> split on spaces
                i += 2
            elif a == "-h":
                rows = max(3, min(40, int(args[i + 1])))
                i += 2
            elif a == "-b":
                bars = True
                i += 1
            else:
                files.append(a)
                i += 1
    except (IndexError, ValueError):
        shell._out("usage: plot [-f N] [-d SEP] [-h ROWS] [-b] [file]")
        return
    try:
        f = shell._input(cwd, files[0] if files else None)
    except OSError:
        shell._err("file not found", shell._join(cwd, files[0]))
        return
    if f is None:
        shell._out("usage: plot [-f N] [-d SEP] [-h ROWS] [-b] [file]")
        return
    values = []
    with f:
        for line in f:
            if field is not None:
                parts = line.split(sep)
                v = _first_number(parts[field - 1]) if 0 < field <= len(parts) else None
            else:
                v = _first_number(line)
            if v is not None:
                values.append(v)
                if len(values) > 5000:
                    del values[0]
    if not values:
        shell._err("no numbers found")
        return

    width = max(10, shell.TERM_WIDTH - 12)
    cols = values
    if len(values) > width:
        per = len(values) / width
        cols = []
        for c in range(width):
            part = values[int(c * per):max(int(c * per) + 1, int((c + 1) * per))]
            cols.append(sum(part) / len(part))
    lo, hi = min(cols), max(cols)
    span = (hi - lo) or 1.0
    level = [int(round((v - lo) / span * (rows - 1))) for v in cols]
    for r in range(rows - 1, -1, -1):
        if r == rows - 1:
            label = "%9.4g |" % hi
        elif r == 0:
            label = "%9.4g |" % lo
        else:
            label = "          |"
        line = []
        for lv in level:
            if bars:
                line.append("#" if lv >= r else " ")
            else:
                line.append("*" if lv == r else " ")
        shell._out(label + "".join(line).rstrip())
    shell._out("          +" + "-" * len(cols))
    note = "" if cols is values else " (averaged into %d columns)" % len(cols)
    shell._out("%d values%s  min %.4g  max %.4g  avg %.4g" %
                (len(values), note, min(values), max(values), sum(values) / len(values)))
