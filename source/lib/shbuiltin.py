"""shbuiltin - the builtins typed only now and then (export, unset,
let, read, alias, unalias, history, !!, time), split out of shell.py so
they are only in RAM while used. All state (ENV, ALIASES, HISTORY)
stays in shell.py, so this module can be unloaded at any time.
"""

import os
import time
import subst
from shell import (ENV, ALIASES, HISTORY, _out, _err, _write, _piped, _no_keyboard,
                   _input_line, _pipe_in, _current_thread_ident, _set_alias,
                   _history_file, _dispatch)


def cmd_export(args, cwd):
    """No args: list every variable. One arg with no "=": show that
    one variable's value. "KEY=VALUE": set it. All three share one
    command the way real sh's export does, distinguished purely by
    what's in args rather than needing separate subcommands."""
    if not args:
        if not ENV:
            _out("no variables set")
            return
        for key in sorted(ENV):
            _out("export %s=%s" % (key, ENV[key]))
        return
    joined = " ".join(args)
    if "=" not in joined:
        if joined in ENV:
            _out("%s=%s" % (joined, ENV[joined]))
        else:
            _err("variable %s not defined" % joined)
        return
    if len(args) > 1 and all("=" in a for a in args):
        for a in args:                  # export A=1 B=2
            key, _, value = a.partition("=")
            ENV[key.strip()] = value
        return
    key, _, value = joined.partition("=")
    ENV[key.strip()] = value.strip()


def cmd_unset(args, cwd):
    if not args:
        _out("usage: unset <var>")
        return
    for key in args:
        ENV.pop(key, None)


def cmd_let(args, cwd):
    """VAR=expression, using the same restricted-eval arithmetic as
    $((expr)) - see subst.eval_arithmetic's docstring for the sandboxing.
    Modeled on ksh's `let`, since plain Bourne sh has no arithmetic."""
    if not args:
        _out("usage: let VAR=expression")
        return
    joined = " ".join(args)
    if "=" not in joined:
        _err("usage: let VAR=expression")
        return
    key, _, expr = joined.partition("=")
    result = subst.eval_arithmetic(expr.strip())
    if result is None:
        _err("could not evaluate expression")
        return
    ENV[key.strip()] = result


def cmd_read(args, cwd):
    """No args: just waits for Enter (a "press any key" style pause).
    With a name: captures one line of input into that variable. No
    prompt text of its own - echo one yourself first if you want the
    user to know what they're being asked for."""
    if not _piped() and _no_keyboard():
        _err("read needs the keyboard (or < file / a pipe) - not in a background job or cron")
        return
    if not args:
        _out("press enter to continue . . .")
        try:
            _input_line()
        except EOFError:
            _out()
        return
    if _piped():
        # one reader per pipe/file, kept on it: `read A; read B` in a
        # script fed by a pipe gets line 1, then line 2
        src = _pipe_in.get(_current_thread_ident())
        rd = getattr(src, "rd", None)
        if rd is None:
            rd = src.rd = src.reader()
        value = rd.readline().rstrip("\r\n")
    else:
        try:
            value = _input_line()
        except EOFError:
            _out()
            value = ""
    ENV[args[0]] = value


def cmd_alias(args, cwd):
    """alias              list all aliases
    alias name          show one
    alias name=command  define: `alias ll=ls -l` - then `ll /bin`
                        runs `ls -l /bin`. Put alias lines in
                        /etc/profile to keep them."""
    if not args:
        if not ALIASES:
            _out("no aliases set")
        for name in sorted(ALIASES):
            _out("alias %s=%s" % (name, ALIASES[name]))
        return
    joined = " ".join(args)
    if "=" not in joined:
        if joined in ALIASES:
            _out("alias %s=%s" % (joined, ALIASES[joined]))
        else:
            _err("no alias %s" % joined)
        return
    if not _set_alias(joined):
        _err("usage: alias name=command")


def cmd_unalias(args, cwd):
    if not args:
        _out("usage: unalias <name>")
        return
    for name in args:
        if ALIASES.pop(name, None) is None:
            _err("no alias %s" % name)


def cmd_history(args, cwd):
    """history        numbered list of earlier commands
    history N      only the last N
    history -c     clear it (and the saved file)
    At the prompt: !! repeats the last command, !N command number N,
    !-N the N-th last, !text the last command starting with text."""
    if args and args[0] == "-c":
        del HISTORY[:]
        path = _history_file()
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        return
    if not HISTORY and ENV.get("HISTORY", "on").lower() == "off":
        _out("history is off (HISTORY=off in /etc/anix.conf)")
        return
    start = 0
    if args:
        try:
            start = max(0, len(HISTORY) - int(args[0]))
        except ValueError:
            _err("usage: history [N | -c]")
            return
    for i in range(start, len(HISTORY)):
        _out("%5d  %s" % (i + 1, HISTORY[i]))


def history_recall(line):
    """Expands !!, !N, !-N and !text at the start of a prompt line.
    Returns the command to run, or None (with an error) if there's no
    such entry."""
    ref = line[1:].strip()
    if not HISTORY:
        _err("history is empty")
        return None
    if ref == "!":
        return HISTORY[-1]
    try:
        n = int(ref)
        idx = n - 1 if n > 0 else len(HISTORY) + n
        if 0 <= idx < len(HISTORY):
            return HISTORY[idx]
        _err("no history entry %s" % ref)
        return None
    except ValueError:
        pass
    for entry in reversed(HISTORY):
        if entry.startswith(ref):
            return entry
    _err("no earlier command starting with %s" % ref)
    return None


def _requote(arg):
    """An argument as text that tokenizes back to the same argument."""
    for ch in " <>|;&$\"'":
        if ch in arg:
            q = "'" if '"' in arg else '"'
            return q + arg + q
    return arg


def cmd_time(args, cwd):
    """time <command> [args...] - runs the command and prints how long
    it took. A builtin, not a /bin file: a /bin/time.py would hide
    MicroPython's own `time` module from every import. For a pipe,
    quote it: time "cat big.txt | wc"."""
    if not args:
        _out("usage: time <command> [args...]")
        return cwd
    if len(args) == 1 and " " in args[0]:
        line = args[0]
    else:
        line = " ".join(_requote(a) for a in args)
    t0 = time.ticks_ms()
    try:
        cwd, _running = _dispatch(line, cwd)
    finally:
        ms = time.ticks_diff(time.ticks_ms(), t0)
        _write("real %d.%03d s\n" % (ms // 1000, ms % 1000), is_error=True)
    return cwd
