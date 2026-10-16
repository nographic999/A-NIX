"""conf - show and change the A-NIX settings in /etc/anix.conf.

  conf                  all settings and their values
  conf KEY              one setting
  conf KEY VALUE        change it: takes effect at once and is saved
  conf KEY none         unset it (a command then uses its default)

Keys are not case-sensitive. Values ending in _PASS are shown as ***.
A few settings are only read
when something starts: WATCHDOG, PROFILE, STARTUP, CRONTAB and HISTORY
at the next shell start, WIFI_COUNTRY
at the next `wifi`. The file keeps its comments - edit it directly
with `edit /etc/anix.conf` to see what each setting does.
"""

import shell


def _read():
    try:
        with open(shell.CONF) as f:
            return [ln.rstrip("\r\n") for ln in f.readlines()]
    except OSError:
        return []


def _key_of(line):
    t = line.strip()
    if not t or t.startswith("#") or "=" not in t:
        return None
    if t.lower().startswith("export "):
        t = t[7:].strip()
    return t.split("=", 1)[0].strip()


def _show(key, value):
    if key.endswith("_PASS") and value not in ("", "none"):
        value = "***"
    shell._out("%-14s %s" % (key, value))


def run(args, cwd):
    lines = _read()
    if not args:
        if not lines:
            shell._err("no settings file - %s is missing" % shell.CONF)
            return
        for ln in lines:
            k = _key_of(ln)
            if k is not None:
                _show(k, shell.ENV.get(k, ln.split("=", 1)[1].strip()))
        return
    key = args[0].upper()
    if not key or not (key[0].isalpha() or key[0] == "_") or \
            not all(c.isalpha() or c.isdigit() or c == "_" for c in key):
        shell._err("bad setting name: %s (letters, digits and _)" % args[0])
        return
    if len(args) == 1:
        if key not in shell.ENV and not any(_key_of(ln) == key for ln in lines):
            shell._err("no setting %s (conf lists them)" % key)
            return
        _show(key, shell.ENV.get(key, "none"))
        return
    value = " ".join(args[1:])
    if "\n" in value:
        shell._err("a value must be one line")
        return
    new = "%s=%s" % (key, value)
    done = False
    for i, ln in enumerate(lines):
        if _key_of(ln) == key:
            lines[i] = new
            done = True
            break
    if not done:
        lines.append(new)
        shell._out("note: %s is a new setting - A-NIX itself doesn't use it (typo?)" % key)
    f = None
    try:
        f = shell._SafeFile(shell.CONF)
        for ln in lines:
            f.write(ln + "\n")
        f.commit()
    except OSError as e:
        if f is not None:
            f.abort()
        shell._err("could not save %s" % shell.CONF, e)
        return
    shell.ENV[key] = value
    _show(key, value)
    if key in ("WATCHDOG", "PROFILE", "STARTUP", "CRONTAB", "HISTORY"):
        shell._out("(takes effect at the next shell start)")
