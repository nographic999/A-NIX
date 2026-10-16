"""cron - run commands on a schedule, from /etc/crontab.

    # comment
    @boot wifi                once, when the shell starts
    every 10m date ntp        every 10 minutes (s, m, h or d)
    at 07:30 wifi             every day at 07:30 (needs the clock set)

Jobs run while the shell waits at its prompt with nothing typed (the
line editor calls tick() about once a second), on core 0 - so a job
never runs in the middle of another command, and never collides with
httpd on core 1. While a job runs, typing waits until it ends.

Output never reaches the screen (it would garble what you type); it
goes to /var/log/cron.log with the time and exit status (kept under
LOG_MAX bytes, see /lib/logs.py) - by default only for jobs that
failed (CRON_LOG=errors), so a job every minute doesn't write to flash
every minute; CRON_LOG=all logs every run, off nothing. `cron` always
shows each job's last run and $?. Jobs run in
$HOME. Commands that wait for keys (edit, read, choice, ...) are
refused. Nothing runs while a command is running. In safe mode
(BOOTSEL held at start) /etc/crontab isn't read at all.
"""

import time
import shell

CRONTAB = "/etc/crontab"
LOG = "/var/log/cron.log"
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_INTERACTIVE = ("edit", "whiptail", "python", "choice", "read",
                "uartterm", "man", "pg", "mkfs", "license", "watch",
                "clear", "nc")

jobs = []           # dicts: kind, spec, cmd, next/day, last, status
errors = []
enabled = True
_booted = False


def _now_ms():
    return time.ticks_ms()


def _clock_set():
    return time.localtime()[0] >= 2024


def _stamp():
    t = time.localtime()
    if t[0] < 2024:
        return "uptime %ds" % (shell.uptime_ms() // 1000)
    return "%04d-%02d-%02d %02d:%02d:%02d" % t[:6]


def _interval(text):
    if len(text) < 2 or text[-1] not in _UNITS:
        raise ValueError
    n = int(text[:-1])
    sec = n * _UNITS[text[-1]]
    # ticks_ms wraps every ~12.4 days, so a time difference is only
    # reliable up to half of that
    if n <= 0 or sec > 6 * 86400:
        raise ValueError
    return sec


def load(path=None):
    """(Re)reads the crontab. Bad lines are kept in `errors`."""
    path = path or CRONTAB
    del jobs[:]
    del errors[:]
    try:
        f = open(path)
    except OSError:
        return
    with f:
        _parse(f)


def _parse(f):
    """One line at a time: comments never sit in RAM."""
    now = _now_ms()
    for n, line in enumerate(f, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        try:
            if parts[0] == "@boot" and len(parts) >= 2:
                jobs.append({"kind": "boot", "spec": "@boot",
                             "cmd": line.split(None, 1)[1], "last": None, "status": None})
            elif parts[0] == "every" and len(parts) == 3:
                sec = _interval(parts[1])
                jobs.append({"kind": "every", "spec": "every " + parts[1], "sec": sec,
                             "next": time.ticks_add(now, sec * 1000),
                             "cmd": parts[2], "last": None, "status": None})
            elif parts[0] == "at" and len(parts) == 3:
                h, m = parts[1].split(":")
                h, m = int(h), int(m)
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
                jobs.append({"kind": "at", "spec": "at %02d:%02d" % (h, m), "hm": (h, m),
                             "day": None, "cmd": parts[2], "last": None, "status": None})
            else:
                raise ValueError
        except (ValueError, IndexError):
            errors.append("line %d: %s" % (n, line))


def _log(text):
    import logs
    logs.append(LOG, text)


def run_job(job):
    """Runs one job, logs it, returns its output text."""
    cmd = job["cmd"]
    saved = shell._last_status
    bad = [w for w in shell._first_words(cmd) if w in _INTERACTIVE]
    try:
        if bad:
            text, status = "refused - %s waits for keys\n" % bad[0], "1"
        else:
            home = shell.ENV.get("HOME", "/root")
            try:
                text, _cwd = shell._dispatch_captured(cmd, home)
            except KeyboardInterrupt:
                text = "stopped with Ctrl-C\n"
            except Exception as e:
                text = "error: %s\n" % e
            status = shell._last_status
    finally:
        shell._last_status = saved
    job["last"] = _stamp()
    job["status"] = status
    mode = shell.ENV.get("CRON_LOG", "errors").lower()
    if mode == "off" or (mode != "all" and status == "0"):
        return text                     # nothing to flash (see CRON_LOG)
    body = "".join("    " + ln + "\n" for ln in text.rstrip("\n").split("\n")) if text.strip() else ""
    _log("%s  %s  [$?=%s]\n%s" % (job["last"], cmd, status, body))
    return text


def boot():
    """Runs the @boot jobs once per board start (not again on `exit`)."""
    global _booted
    if _booted:
        return
    _booted = True
    for job in jobs:
        if job["kind"] == "boot" and enabled:
            run_job(job)


def tick():
    """Called about once a second from the idle prompt."""
    if not enabled or not jobs:
        return
    now = _now_ms()
    t = None
    for job in jobs:
        if job["kind"] == "every":
            if time.ticks_diff(now, job["next"]) >= 0:
                job["next"] = time.ticks_add(now, job["sec"] * 1000)    # first:
                run_job(job)                    # a failing job can't repeat at once
        elif job["kind"] == "at":
            if t is None:
                t = time.localtime()
            if t[0] < 2024:
                continue
            today = (t[0], t[1], t[2])
            if (t[3], t[4]) == job["hm"] and job["day"] != today:
                job["day"] = today
                run_job(job)


def next_text(job):
    if job["kind"] == "boot":
        return "at start"
    if job["kind"] == "every":
        left = max(0, time.ticks_diff(job["next"], _now_ms()) // 1000)
        return "in %dm %02ds" % divmod(left, 60) if left < 3600 else "in %dh %02dm" % (left // 3600, left % 3600 // 60)
    if not _clock_set():
        return "clock not set (date ntp)"
    return "daily"
