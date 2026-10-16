"""script - the A-NIX script language, split out of shell.py so it is
only in RAM while scripts are used.

    if / elif / else / fi     for VAR A B [STEP] ... done
    while COND ... done       break, continue
    :label + goto             function NAME ... end, return [N]
    set -x / set +x           show lines as they run
    @command                  never shown

A script is parsed into a small tree first (so a missing fi/done is
reported with its line number before anything runs), then executed.
All state - variables, functions, $? - stays in shell.py, so this
module can be unloaded and loaded again at any time.
"""

import gc
import os
from shell import (ENV, ALIASES, FUNCTIONS, STARTUP, _BUILTINS, _expand, _dispatch,
                   _status, _put_status, _out, _err, _join, _find_executable,
                   _in_lib, _push_args, _pop_args, fs_begin, fs_end)



def _num(text):
    try:
        return float(text)
    except ValueError:
        return None


def _unquote(text):
    text = text.strip()
    if len(text) > 1 and text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1]
    return text


def _find_outside(text, words, start=0):
    """Position and word of the first of words in text that is outside
    quotes and parentheses ($(..), $((..))), or (-1, None)."""
    quote = None
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth:
                depth -= 1
        elif not depth:
            low = text[i:i + 6].lower()
            for w in words:
                if low.startswith(w) if w[0] == " " else text.startswith(w, i):
                    return i, w
        i += 1
    return -1, None


def _value(text):
    """One side of a comparison: variables expanded, outer quotes off."""
    return _unquote(_expand(text.strip()))


def _eval_condition(cond_text, cwd):
    """A script condition, as written (variables are expanded only
    after it has been split up, so a value can't change its meaning):
        exist PATH          file or directory exists
        A == B   A != B     equal / not equal (as numbers if both are)
        A < B  A > B  A <= B  A >= B   compare (as numbers if both
                            are numbers, else as text)
        not COND            negate
        C1 and C2   C1 or C2   combine (or binds weaker than and)
        COMMAND [args]      run it: true if its $? is 0 - when the first
                            word is a command, alias or function
    Quotes are optional around values; and/or and operators inside
    quotes are plain text. Anything else is false."""
    text = cond_text.strip()
    k, w = _find_outside(text, (" or ",))
    if k != -1:
        return _eval_condition(text[:k], cwd) or _eval_condition(text[k + 4:], cwd)
    k, w = _find_outside(text, (" and ",))
    if k != -1:
        return _eval_condition(text[:k], cwd) and _eval_condition(text[k + 5:], cwd)
    low = text.lower()
    if low.startswith("not "):
        return not _eval_condition(text[4:], cwd)
    if low.startswith("exist "):
        try:
            os.stat(_join(cwd, _value(text[6:])))
            return True
        except OSError:
            return False
    k, op = _find_outside(text, ("==", "!=", "<=", ">=", "<", ">"))
    if k != -1 and not _is_command_word(text, cwd):
        a, b = _value(text[:k]), _value(text[k + len(op):])
        na, nb = _num(a), _num(b)
        if na is not None and nb is not None:
            a, b = na, nb
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if type(a) != type(b):
            a, b = str(a), str(b)
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
        if op == "<":
            return a < b
        return a > b
    if _is_command_word(text, cwd):
        _dispatch(text, cwd)            # expanded there, once
        return _status() == "0"
    return False


def _is_command_word(text, cwd):
    """True if the condition's first word, as written, names something
    runnable - never a $variable (`if $ans == y` must compare, not run
    whatever $ans holds) and never when the next word is an operator."""
    parts = text.split(None, 2)
    word = parts[0] if parts else ""
    if not word or word[0] in "\"'$" or _num(word) is not None:
        return False
    if len(parts) > 1 and parts[1] in ("==", "!=", "<", ">", "<=", ">="):
        return False
    for op in ("==", "!=", "<", ">"):
        if op in word:
            return False
    if word in FUNCTIONS or word in ALIASES or word.lower() in _BUILTINS:
        return True
    found = _find_executable(word, cwd)
    return found is not None and not _in_lib(found)


def _strip_trailing_word(text, word):
    """Strips an optional trailing keyword ("then" off an if line,
    "do" off a for/while line), case-insensitively."""
    t = text.rstrip()
    if t.lower() == word:
        return ""
    if t.lower().endswith(" " + word):
        t = t[: -(len(word) + 1)].rstrip()
    return t.rstrip(";").rstrip()      # if A == 1; then


class _ScriptError(Exception):
    pass


class _Goto(Exception):
    def __init__(self, target):
        self.target = target


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _ExitScript(Exception):
    pass


class _Return(Exception):
    def __init__(self, status):
        self.status = status


def _parse_script(lines):
    """Turns script lines into a list of nodes:
        ("cmd", text)  ("label", name)  ("goto", name)
        ("if", [(cond, body), ...], else_body)
        ("for", var, start, end, step, body)  ("while", cond, body)
        ("break",)  ("continue",)  ("func", name, body)  ("return", n)
    Raises _ScriptError("line N: ...") for a block that isn't closed or
    a fi/done/else without its opening line."""
    n = len(lines)
    pos = [0]

    def first_word(raw):
        w = raw.split(None, 1)
        return w[0].lower() if w else ""

    def block(enders):
        nodes = []
        while pos[0] < n:
            raw = lines[pos[0]].strip()
            if not raw or raw.startswith("#"):
                pos[0] += 1
                continue
            word = first_word(raw)
            if word in enders:
                rest = raw.split(None, 1)[1:]
                if word != "elif" and rest and not rest[0].startswith("#"):
                    raise _ScriptError("line %d: put what follows %s on its own line"
                                       % (pos[0] + 1, word))
                return nodes, word
            line_no = pos[0] + 1
            pos[0] += 1
            if raw.startswith(":"):
                nodes.append(("label", raw[1:].strip().lower()))
            elif word == "if":
                branches = []
                cond = _strip_trailing_word(raw[2:], "then")
                body, end = block(("elif", "else", "fi"))
                branches.append((cond, body))
                while end == "elif":
                    raw2 = lines[pos[0]].strip()
                    pos[0] += 1
                    cond = _strip_trailing_word(raw2[4:], "then")
                    body, end = block(("elif", "else", "fi"))
                    branches.append((cond, body))
                else_body = []
                if end == "else":
                    pos[0] += 1
                    else_body, end = block(("fi",))
                if end != "fi":
                    raise _ScriptError("line %d: if without fi" % line_no)
                pos[0] += 1
                nodes.append(("if", branches, else_body))
            elif word == "for":
                parts = _strip_trailing_word(raw, "do").split()
                if len(parts) not in (4, 5):
                    raise _ScriptError("line %d: usage: for VAR START END [STEP] [do]" % line_no)
                body, end = block(("done",))
                if end != "done":
                    raise _ScriptError("line %d: for without done" % line_no)
                pos[0] += 1
                nodes.append(("for", parts[1], parts[2], parts[3],
                              parts[4] if len(parts) == 5 else None, body))
            elif word == "while":
                cond = _strip_trailing_word(raw[5:], "do")
                body, end = block(("done",))
                if end != "done":
                    raise _ScriptError("line %d: while without done" % line_no)
                pos[0] += 1
                nodes.append(("while", cond, body))
            elif word == "function":
                parts = raw.split()
                if len(parts) != 2:
                    raise _ScriptError("line %d: usage: function NAME ... end" % line_no)
                body, end = block(("end",))
                if end != "end":
                    raise _ScriptError("line %d: function without end" % line_no)
                pos[0] += 1
                nodes.append(("func", parts[1], body))
            elif word == "return":
                rest = raw.split()
                nodes.append(("return", rest[1] if len(rest) > 1 else None))
            elif word in ("fi", "done", "else", "elif", "end"):
                raise _ScriptError("line %d: %s without its if/for/while/function" % (line_no, word))
            elif word == "goto":
                nodes.append(("goto", raw[4:].strip().lower()))
            elif word in ("break", "continue") and raw.lower() == word:
                nodes.append((word,))
            else:
                nodes.append(("cmd", raw))
        return nodes, None

    nodes, _end = block(())
    return nodes


def _to_int(text, what):
    try:
        return int(_expand(text))
    except ValueError:
        raise _ScriptError("for %s must be a whole number, not %s" % (what, _expand(text)))


def _exec_nodes(nodes, ctx):
    for node in nodes:
        _exec_node(node, ctx)


def _exec_node(node, ctx):
    kind = node[0]
    if kind == "cmd":
        cwd, running = _batch_exec_line(node[1], ctx["cwd"], ctx["echo"])
        ctx["cwd"] = cwd
        if not running:
            raise _ExitScript()
    elif kind == "if":
        for cond, body in node[1]:
            if _eval_condition(cond, ctx["cwd"]):
                _exec_nodes(body, ctx)
                return
        _exec_nodes(node[2], ctx)
    elif kind == "for":
        _k, var, start, end, step, body = node
        v = _to_int(start, "start")
        stop = _to_int(end, "end")
        st = _to_int(step, "step") if step is not None else (1 if stop >= v else -1)
        if st == 0:
            raise _ScriptError("for step can't be 0")
        while (st > 0 and v <= stop) or (st < 0 and v >= stop):
            ENV[var] = str(v)
            try:
                _exec_nodes(body, ctx)
            except _Break:
                break
            except _Continue:
                pass
            v += st
    elif kind == "while":
        while _eval_condition(node[1], ctx["cwd"]):
            try:
                _exec_nodes(node[2], ctx)
            except _Break:
                break
            except _Continue:
                pass
    elif kind == "func":
        FUNCTIONS[node[1]] = node[2]
    elif kind == "return":
        st = _status() if node[1] is None else _expand(node[1])
        raise _Return(st)
    elif kind == "goto":
        raise _Goto(node[1])
    elif kind == "break":
        raise _Break()
    elif kind == "continue":
        raise _Continue()
    # "label": nothing to do


def _batch_exec_line(line, cwd, echo_flag):
    """Runs one already-unwrapped script line through _dispatch,
    handling the two things specific to script execution rather than
    interactive typing: a leading @ silences just that one line's
    echo (like DOS batch files' @, kept as a familiar convenience),
    and "set -x"/"set +x" toggle echo_flag for every line after it.
    echo_flag is a one-item list, not a plain bool, purely so this
    function and its caller can share and mutate the same flag
    without needing a `global` (there's no single module-level
    "current echo state" - each _run_batch call has its own, since
    scripts can call other scripts)."""
    suppress = line.startswith("@")
    if suppress:
        line = line[1:]
    lower = line.lower()
    if lower in ("set -x", "set +x"):
        if echo_flag[0] and not suppress:
            _out(cwd + " $ " + line)
        echo_flag[0] = (lower == "set -x")
        return cwd, True
    if echo_flag[0] and not suppress:
        _out(cwd + " $ " + line)
    try:
        cwd, running = _dispatch(line, cwd)
    except Exception as e:
        # a command raising an unexpected exception shouldn't take
        # the whole script down with it - report it and keep going,
        # the same way a real shell survives one failed command
        _err("shell error", e)
        running = True
    return cwd, running


_batch_depth = [0]


def _run_batch(path, cwd, args=None):
    if _batch_depth[0] >= 10:
        _err("%s: scripts nested more than 10 deep (a script running itself?)" % path)
        return cwd
    _batch_depth[0] += 1
    try:
        return _run_batch_inner(path, cwd, args)
    finally:
        _batch_depth[0] -= 1


def _run_batch_inner(path, cwd, args=None):
    """Runs a .sh script - see _parse_script for the syntax. The whole
    script is parsed first, so a missing fi/done is reported before
    any line runs. goto jumps to a top-level :label (from anywhere,
    also out of loops); labels inside a block can't be jumped to.
    Commands are not shown as they run unless `set -x` is on. `exit`
    ends the script (not the shell); Ctrl-C stops it."""
    try:
        fs_begin()
        try:
            with open(path) as f:
                # comments become "" while reading: never held in RAM,
                # and line numbers in error messages stay right
                lines = []
                for ln in f:
                    if ln.lstrip().startswith("#"):
                        lines.append("")
                    else:
                        lines.append(ln.rstrip("\n").rstrip("\r"))
        finally:
            fs_end()
    except OSError:
        if path != _join(cwd, STARTUP) and path != STARTUP:
            _err("script not found", path)
        return cwd
    try:
        nodes = _parse_script(lines)
    except _ScriptError as e:
        _err("%s: %s" % (path, e))
        return cwd
    labels = {}
    for idx, node in enumerate(nodes):
        if node[0] == "label":
            labels[node[1]] = idx

    ctx = {"cwd": cwd, "echo": [False]}     # off like real sh; set -x turns it on
    saved_args = _push_args(path.rsplit("/", 1)[-1], args or [])
    try:
        _run_nodes(nodes, labels, ctx, path)
    finally:
        _pop_args(saved_args)
    return ctx["cwd"]


def _run_nodes(nodes, labels, ctx, path):
    idx = 0
    jumps = 0
    while idx < len(nodes):
        try:
            _exec_node(nodes[idx], ctx)
            idx += 1
        except _Goto as g:
            if g.target in labels:
                idx = labels[g.target] + 1
                jumps += 1
                if jumps % 100 == 0:
                    gc.collect()
            else:
                _err("%s: label not found - %s" % (path, g.target))
                idx += 1
        except (_Break, _Continue):
            _err("%s: break/continue outside a loop" % path)
            idx += 1
        except _ExitScript:
            break
        except _Return as r:
            _put_status(str(r.status))      # return in a script: end it
            break
        except _ScriptError as e:
            _err("%s: %s" % (path, e))
            break
    return ctx["cwd"]


_call_depth = [0]


def _call_function(name, args, cwd):
    """Runs a script function: $1.. are its arguments, `return [n]`
    leaves it (n becomes $?), cd inside it stays in effect."""
    if _call_depth[0] >= 20:
        _err("%s: functions nested more than 20 deep" % name)
        return cwd, True
    saved = _push_args(name, args)
    ctx = {"cwd": cwd, "echo": [False]}
    _call_depth[0] += 1
    running = True
    try:
        _exec_nodes(FUNCTIONS[name], ctx)
    except _Return as r:
        _put_status(str(r.status))
    except _ExitScript:
        running = False
    except _Goto as g:
        _err("%s: goto %s can't leave a function" % (name, g.target))
    except (_Break, _Continue):
        _err("%s: break/continue outside a loop" % name)
    except _ScriptError as e:
        _err("%s: %s" % (name, e))
    finally:
        _call_depth[0] -= 1
        _pop_args(saved)
    return ctx["cwd"], running
