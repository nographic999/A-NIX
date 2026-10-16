"""date - show or set the date/time from the board's RTC.

  date                          show weekday, date and time
  date YYYY-MM-DD [HH:MM:SS]    set the date (and time)
  date HH:MM:SS                 set only the time
  date ntp [server]             set from the internet (W boards)

The RTC has no battery: it resets when power is lost, and keeps
counting through soft resets. `date ntp` gets UTC from an NTP server
(default pool.ntp.org) and adds TZ hours from /etc/anix.conf - e.g.
`conf TZ 2` for Lithuanian winter time, 3 for summer time (no
automatic daylight saving switch).

When the date is set, the weekday is calculated from it (the RTC
stores the weekday separately and doesn't work it out itself).
"""

import time
import machine
import shell

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _ntp(rtc, server):
    import net
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    try:
        tz = float(shell.ENV.get("TZ", "0"))
    except ValueError:
        shell._err("TZ must be a number of hours, e.g. 2 or -5.5")
        return
    try:
        epoch = net.ntp_time(server)
    except Exception as e:
        shell._err("could not get time from %s (connected to WiFi?)" % server, e)
        return
    t = epoch + int(tz * 3600)
    if time.gmtime(0)[0] == 2000:       # firmware counting from 2000
        t -= 946684800
    y, mo, d, h, mi, s, wd, _yd = time.gmtime(t)
    rtc.datetime((y, mo, d, wd, h, mi, s, 0))
    shell._out("date set from %s: %s %04d-%02d-%02d %02d:%02d:%02d (TZ %+g)" %
                (server, _DAYS[wd], y, mo, d, h, mi, s, tz))


def run(args, cwd):
    rtc = machine.RTC()
    if args and args[0].lower() == "ntp":
        _ntp(rtc, args[1] if len(args) > 1 else "pool.ntp.org")
        return
    if not args:
        y, mo, d, wd, h, mi, s, sub = rtc.datetime()
        shell._out("%s %04d-%02d-%02d %02d:%02d:%02d" % (_DAYS[wd % 7], y, mo, d, h, mi, s))
        return

    # accepts a date, a time, or both together - figure out which
    # from what punctuation is present
    text = " ".join(args)
    date_part = time_part = None
    if " " in text:
        date_part, time_part = text.split(" ", 1)
    elif "-" in text:
        date_part = text
    elif ":" in text:
        time_part = text
    else:
        shell._out("usage: date [YYYY-MM-DD] [HH:MM:SS]")
        return

    # start from the current value so setting just the date (or just
    # the time) doesn't clobber the other half back to zero
    y, mo, d, wd, h, mi, s, sub = rtc.datetime()
    if date_part:
        try:
            parts = date_part.split("-")
            y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            shell._err("invalid date - use YYYY-MM-DD")
            return
        if not (2000 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31):
            shell._err("invalid date - use YYYY-MM-DD")
            return
    if time_part:
        try:
            parts = time_part.split(":")
            h = int(parts[0])
            mi = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            shell._err("invalid time - use HH:MM:SS")
            return
        if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
            shell._err("invalid time - use HH:MM:SS")
            return

    # mktime/localtime round trip: gives the weekday (0 = Monday) and
    # rejects impossible dates like 2026-02-30 by normalising them
    t = time.localtime(time.mktime((y, mo, d, h, mi, s, 0, 0)))
    if (t[0], t[1], t[2]) != (y, mo, d):
        shell._err("invalid date - %04d-%02d-%02d doesn't exist" % (y, mo, d))
        return
    wd = t[6]

    rtc.datetime((y, mo, d, wd, h, mi, s, 0))
    shell._out("date set to %s %04d-%02d-%02d %02d:%02d:%02d" % (_DAYS[wd], y, mo, d, h, mi, s))
