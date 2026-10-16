"""log - append a time-stamped line to a CSV file (data logging).

  log [-n] <file> [value ...]       ... | log [-n] <file>

Writes "2026-10-07 10:30:00,value,value" to the end of the file. The
values are the arguments, or the first line of the pipe. -n keeps
only the numbers from that text, each as its own column - handy for
command output:
    temp | log -n /root/temp.csv           -> time,21.3,70.3
With cron, every 10 minutes:
    every 10m temp | log -n /root/temp.csv
Then look at it: plot -f 2 /root/temp.csv
If the clock isn't set (no date / date ntp since power-up) the time
column says "+<seconds since power-up>s" instead.
"""

import time
import shell


def _numbers(text):
    out = []
    num = ""
    for ch in text + " ":
        if ch.isdigit() or ch == "." or (ch == "-" and not num):
            num += ch
        else:
            if num not in ("", "-", ".", "-."):
                out.append(num)
            num = ""
    return out


def run(args, cwd):
    nums = "-n" in args
    args = [a for a in args if a != "-n"]
    if not args:
        shell._out("usage: log [-n] <file> [value ...]   |   ... | log [-n] <file>")
        return
    path = shell._join(cwd, args[0])
    if len(args) > 1:
        text = " ".join(args[1:])
    else:
        f = shell._input(cwd)
        if f is None:
            shell._err("nothing to log - give values or pipe them in")
            return
        with f:
            text = f.readline().strip()
    values = _numbers(text) if nums else [v.strip() for v in text.replace(";", ",").split(",")] \
        if "," in text else text.split()
    if not values:
        shell._err("nothing to log")
        return
    t = time.localtime()
    stamp = ("%04d-%02d-%02d %02d:%02d:%02d" % t[:6]) if t[0] >= 2024 else \
        "+%ds" % (shell.uptime_ms() // 1000)
    try:
        with shell._open_append(path) as out:
            out.write(stamp + "," + ",".join(values) + "\n")
    except OSError as e:
        shell._err("could not write %s" % path, e)
