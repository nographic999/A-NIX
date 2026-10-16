"""subst - $((expr)), `let` arithmetic and $(command), split out of
shell.py so it is only in RAM while they are used.
"""

import os
from shell import (ENV, _is_word_char, _current_thread_ident, _PipeBuf, _redirects,
                   _pipe_in, _dispatch, _sub_count)


def eval_arithmetic(expr):
    """Backs $((expr)) and `let`. Runs on a real Python eval() rather
    than a hand-rolled arithmetic parser, but sandboxed: __builtins__
    is stripped from the namespace so expr can't call arbitrary
    functions (open, import, etc.) - only do arithmetic on the
    numbers handed to it via ENV. Env vars that parse as numbers are
    exposed as actual int/float values (not strings) so `X + 1` works
    instead of needing an explicit conversion."""
    expr = expr.strip()             # " X + 1 ": eval() refuses a leading space
    ns = {"__builtins__": {}}
    for k, v in ENV.items():
        try:
            ns[k] = int(v)
        except ValueError:
            try:
                ns[k] = float(v)
            except ValueError:
                pass
    # MicroPython ignores the __builtins__ trick (open() etc. stay
    # reachable), so only numbers, operators and number variables pass
    word = ""
    for ch in expr + " ":
        if _is_word_char(ch):
            word += ch
            continue
        if word and not ("0" <= word[0] <= "9") and word not in ns \
                and word not in ("and", "or", "not"):
            return None
        word = ""
        if ch not in " \t+-*/%()<>=!.&|^~,":
            return None
    try:
        result = eval(expr, ns)
        if isinstance(result, float) and result == int(result):
            result = int(result)  # "4.0" -> "4", so whole-number results look normal
    except Exception:
        return None
    return str(result)


def matching_paren(line, start):
    """Index of the ) closing the ( at start, skipping quoted text and
    nested ( ); -1 if there is none."""
    depth = 0
    quote = None
    for k in range(start, len(line)):
        ch = line[k]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return k
    return -1


def substitute(cmd, cwd=None):
    """$(cmd): runs cmd, returns its output with newlines as spaces and
    the trailing ones removed. Errors still reach the screen."""
    if not cmd.strip():
        return ""
    me = _current_thread_ident()
    _sub_count[0] += 1
    buf = _PipeBuf(100 + _sub_count[0])
    saved_out = _redirects.get(me)
    saved_in = _pipe_in.pop(me, None)
    _redirects[me] = buf
    try:
        if cwd is None:
            try:
                cwd = os.getcwd()
            except OSError:
                cwd = "/"
        _dispatch(cmd, cwd)
    finally:
        if saved_out is None:
            _redirects.pop(me, None)
        else:
            _redirects[me] = saved_out
        if saved_in is not None:
            _pipe_in[me] = saved_in
        buf.finish()
    try:
        f = buf.reader()
        text = f.read()
        f.close()
    finally:
        buf.discard()
    return " ".join(text.split("\n")).strip()
