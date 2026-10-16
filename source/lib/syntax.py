"""syntax - colours for `edit`, like nano's syntax highlighting.

Loaded only when a file of a known kind is opened and COLOR isn't
off; dropped again when RAM runs low.

    .py                    Python
    .sh, /etc/startup      A-NIX scripts
    /etc/crontab           cron lines
    .conf .cfg .ini, /etc/profile   KEY=VALUE settings

Each line is split into spans (start, end, colour) once and kept in a
small cache, so typing on one line doesn't re-colour the whole screen.
A Python string with three quotes can run over several lines: where
the screen starts inside one is worked out from up to 200 lines above.
"""

# colours (SGR codes)
KEYWORD = "01;36"       # bold cyan:    if, def, for, done ...
DEFNAME = "01;34"       # bold blue:    the name after def / class / function
CALL = "33"             # yellow:       a function call  name(
VARIABLE = "01;37"      # bold white:   x = ...   (Python); $VAR is green (scripts)
SHVAR = "32"            # green:        $VAR ${VAR} $1 $? $(...)
STRING = "32"           # green:        "text" 'text'
NUMBER = "31"           # red:          42 0x1F 3.5
CONST = "35"            # magenta:      True False None self, on/off/none
COMMENT = "36"          # cyan:         # comment   (nano's default)
DECOR = "01;35"         # bold magenta: @decorator
COMMAND = "01;34"       # bold blue:    the command word of a script line
LABEL = "01;33"         # bold yellow:  :label, goto label, @boot every at
OPERATOR = "35"         # magenta:      | ; && || > >> < == !=
SHSTRING = "33"         # yellow:       "text" in scripts (so $VAR stands out)
KEY = "01;36"           # bold cyan:    KEY= in settings
SECTION = "01;33"       # bold yellow:  [section]

_PY_KW = ("False", "None", "True", "and", "as", "assert", "async", "await", "break",
          "class", "continue", "def", "del", "elif", "else", "except", "finally", "for",
          "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or",
          "pass", "raise", "return", "try", "while", "with", "yield")
_PY_CONST = ("True", "False", "None", "self", "cls")
_SH_KW = ("if", "elif", "else", "fi", "then", "for", "while", "do", "done", "function",
          "end", "return", "break", "continue", "goto", "exit", "set", "not", "and", "or",
          "exist", "source", ".")
_CONF_CONST = ("on", "off", "none", "true", "false", "yes", "no", "high", "low")

_CACHE_MAX = 80           # rows kept coloured (a screen is 20-50)


def kind_for(path):
    """"py", "sh", "cron", "conf" or None, from the file name."""
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith(".py"):
        return "py"
    if name.endswith(".sh") or name == "startup":
        return "sh"
    if name == "crontab":
        return "cron"
    if name == "profile" or name.endswith(".conf") or name.endswith(".cfg") \
            or name.endswith(".ini"):
        return "conf"
    return None


def _word_char(ch):
    return ch.isalpha() or ch.isdigit() or ch == "_"


def _num_end(line, i):
    n = len(line)
    while i < n and (_word_char(line[i]) or line[i] == "."):
        i += 1
    return i


# --- Python ---------------------------------------------------------

def _py_string(line, i, spans):
    """A string starting at i (the quote). Returns (next_i, open_triple)."""
    n = len(line)
    q3 = line[i:i + 3]
    if q3 == '"""' or q3 == "'''":
        j = line.find(q3, i + 3)
        if j < 0:
            spans.append((i, n, STRING))
            return n, q3
        spans.append((i, j + 3, STRING))
        return j + 3, None
    q = line[i]
    j = i + 1
    while j < n and line[j] != q:
        if line[j] == "\\":
            j += 1
        j += 1
    j = min(j + 1, n)
    spans.append((i, j, STRING))
    return j, None


def _py(line, state):
    spans = []
    n = len(line)
    i = 0
    if state:
        j = line.find(state)
        if j < 0:
            return [(0, n, STRING)], state
        spans.append((0, j + 3, STRING))
        i = j + 3
        state = None
    expect_name = False         # after def / class
    expect_var = False          # after for
    while i < n:
        ch = line[i]
        if ch == "#":
            spans.append((i, n, COMMENT))
            break
        if ch == '"' or ch == "'":
            i, state = _py_string(line, i, spans)
            if state:
                return spans, state
            continue
        if ch.isdigit():
            j = _num_end(line, i)
            spans.append((i, j, NUMBER))
            i = j
            continue
        if ch == "@" and not line[:i].strip():
            j = i + 1
            while j < n and (_word_char(line[j]) or line[j] == "."):
                j += 1
            spans.append((i, j, DECOR))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and _word_char(line[j]):
                j += 1
            w = line[i:j]
            if j < n and line[j] in "\"'" and w.lower() in ("f", "r", "b", "u", "rb", "br", "fr", "rf"):
                i, state = _py_string(line, j, spans)       # f"..." r'...'
                spans[-1] = (j - len(w), spans[-1][1], STRING)
                if state:
                    return spans, state
                continue
            k = j
            while k < n and line[k] == " ":
                k += 1
            nxt = line[k:k + 2]
            code = None
            if expect_name:
                code, expect_name = DEFNAME, False
            elif expect_var:
                code, expect_var = VARIABLE, False
            elif w in _PY_CONST:
                code = CONST
            elif w in _PY_KW:
                code = KEYWORD
                expect_name = w in ("def", "class")
                expect_var = w == "for"
            elif nxt[:1] == "(":
                code = CALL
            elif (nxt[:1] == "=" and nxt != "==") or (nxt[1:2] == "=" and nxt[:1] in "+-*/%|&"):
                before = line[:i].rstrip()
                if not before or before.endswith(",") or before.endswith("."):
                    code = VARIABLE                 # x = 1   a, b = ...   self.x = ...
            if code:
                spans.append((i, j, code))
            i = j
            continue
        i += 1
    return spans, None


def _triple_state(line, state):
    """Just the open-triple-quote state after line (for lines above
    the screen) - quicker than a full _py()."""
    i = 0
    while True:
        if state:
            j = line.find(state, i)
            if j < 0:
                return state
            i, state = j + 3, None
        else:
            a = line.find('"""', i)
            b = line.find("'''", i)
            if a < 0 and b < 0:
                return None
            j = a if (b < 0 or (0 <= a < b)) else b
            h = line.find("#", i)
            if 0 <= h < j and line.count('"', i, h) % 2 == 0 and line.count("'", i, h) % 2 == 0:
                return None             # the quotes are inside a comment
            state = line[j:j + 3]
            i = j + 3


# --- A-NIX scripts --------------------------------------------------

def _sh_var(line, i, spans):
    """$VAR ${VAR} $1 $? $(...) $((...)) at i. Returns the next i."""
    n = len(line)
    if i + 1 >= n:
        return i + 1
    nxt = line[i + 1]
    if nxt == "(":
        depth = 0
        j = i + 1
        while j < n:
            if line[j] == "(":
                depth += 1
            elif line[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        j = min(j + 1, n)
    elif nxt == "{":
        j = line.find("}", i)
        j = n if j < 0 else j + 1
    elif nxt in "?#@" or nxt.isdigit():
        j = i + 2
    elif _word_char(nxt):
        j = i + 1
        while j < n and _word_char(line[j]):
            j += 1
    else:
        return i + 1
    spans.append((i, j, SHVAR))
    return j


def _sh(line, state, start=0):
    spans = []
    n = len(line)
    i = start
    while i < n and line[i] in " \t":
        i += 1
    if i >= n:
        return spans, None
    if line[i] == "#":
        return [(i, n, COMMENT)], None
    if line[i] == ":":
        return [(i, n, LABEL)], None
    if line[i] == "@":
        i += 1
    expect = "cmd"              # what the next word is: cmd, var, name, label, None
    while i < n:
        ch = line[i]
        if ch in " \t":
            i += 1
            continue
        if ch == '"' or ch == "'":
            j = line.find(ch, i + 1)
            j = n if j < 0 else j + 1
            spans.append((i, j, SHSTRING))
            if ch == '"':                           # $VAR inside "..." still green
                k = i
                while True:
                    k = line.find("$", k, j)
                    if k < 0:
                        break
                    k = _sh_var(line, k, spans)
            i = j
            if expect == "cmd":
                expect = None
            continue
        if ch == "$":
            i = _sh_var(line, i, spans)
            if expect == "cmd":
                expect = None
            continue
        if ch in "|;&<>":
            j = i
            while j < n and line[j] in "|;&<>":
                j += 1
            spans.append((i, j, OPERATOR))
            if ch in "|;&":
                expect = "cmd"
            i = j
            continue
        j = i
        while j < n and line[j] not in " \t|;&<>\"'$":
            j += 1
        w = line[i:j]
        low = w.lower()
        code = None
        if w in ("==", "!=", "<=", ">="):
            code = OPERATOR
        elif expect == "var":
            code, expect = SHVAR, None
        elif expect == "name":
            code, expect = DEFNAME, None
        elif expect == "label":
            code, expect = LABEL, None
        elif low in _SH_KW and (expect == "cmd" or low in ("then", "do", "and", "or", "not")):
            code = KEYWORD
            if low == "for":
                expect = "var"
            elif low == "function":
                expect = "name"
            elif low == "goto":
                expect = "label"
            elif low in ("exit", "return", "set", "exist", "source", "."):
                expect = None
            else:
                expect = "cmd"                      # if grep ...  and not x ...
        elif expect == "cmd":
            code, expect = COMMAND, None
        elif w[:1].isdigit() and w.replace(".", "").isdigit():
            code = NUMBER
        if code:
            spans.append((i, j, code))
        i = j
    return spans, None


# --- crontab / settings ---------------------------------------------

def _cron(line, state):
    s = line.lstrip()
    if not s:
        return [], None
    i = len(line) - len(s)
    if s[0] == "#":
        return [(i, len(line), COMMENT)], None
    word = s.split(None, 1)[0]
    if word not in ("@boot", "every", "at"):
        return _sh(line, None, i)
    spans = [(i, i + len(word), LABEL)]
    j = i + len(word)
    if word != "@boot":                             # every 30m / at 07:30
        while j < len(line) and line[j] == " ":
            j += 1
        k = j
        while k < len(line) and line[k] != " ":
            k += 1
        spans.append((j, k, CONST))
        j = k
    more, _ = _sh(line, None, j)
    return spans + more, None


def _conf(line, state):
    s = line.lstrip()
    n = len(line)
    if not s:
        return [], None
    i = n - len(s)
    if s[0] in "#;":
        return [(i, n, COMMENT)], None
    if s[0] == "[":
        return [(i, n, SECTION)], None
    spans = []
    low = s.lower()
    for kw in ("export ", "alias "):
        if low.startswith(kw):
            spans.append((i, i + len(kw) - 1, KEYWORD))
            i += len(kw)
            break
    eq = line.find("=", i)
    if eq < 0:
        return spans, None
    spans.append((i, eq, KEY))
    v = line[eq + 1:].strip()
    vs = line.find(v, eq + 1) if v else n
    if v[:1] in "\"'":
        spans.append((vs, n, STRING))
    elif v.lower() in _CONF_CONST:
        spans.append((vs, vs + len(v), CONST))
    elif v and v.lstrip("-").replace(".", "").isdigit():
        spans.append((vs, vs + len(v), NUMBER))
    return spans, None


_RULES = {"py": _py, "sh": _sh, "cron": _cron, "conf": _conf}


class Highlighter:
    def __init__(self, kind):
        self.kind = kind
        self.rule = _RULES[kind]
        self.cache = {}
        self.rows = {}          # finished rows: (state, line, left, width) -> text

    def state_at(self, lines, top):
        """The open-string state at the start of line `top`."""
        if self.kind != "py":
            return None
        state = None
        try:
            for idx in range(max(0, top - 200), top):
                ln = lines[idx]
                if state or '"""' in ln or "'''" in ln:
                    state = _triple_state(ln, state)
        except Exception:
            return None
        return state

    def spans(self, line, state):
        """(spans, state after the line), cached."""
        key = (state, line)
        hit = self.cache.get(key)
        if hit is None:
            if len(self.cache) >= _CACHE_MAX:
                self.cache.clear()
            hit = self.rule(line, state)
            self.cache[key] = hit
        return hit

    def row(self, line, state, left, width, sel=None):
        """One screen row: (coloured text, state after the line). Rows
        without a selection are cached, so only the line being typed
        on is coloured again."""
        try:
            return self._row(line, state, left, width, sel)
        except Exception:               # MemoryError, or a bug here: never
            self.cache.clear()          # let colouring break the editor -
            self.rows.clear()           # show this row without colours
            text = line[left:left + width]
            if sel:
                text = (text[:sel[0]] + "\x1b[7m" + text[sel[0]:sel[1]] + "\x1b[0m"
                        + text[sel[1]:])
            return text, state

    def _row(self, line, state, left, width, sel):
        spans, after = self.spans(line, state)
        if sel:
            return self.paint(line, left, width, spans, sel), after
        key = (state, line, left, width)
        text = self.rows.get(key)
        if text is None:
            if len(self.rows) >= _CACHE_MAX:
                self.rows.clear()
            text = self.paint(line, left, width, spans)
            self.rows[key] = text
        return text, after

    def paint(self, line, left, width, spans, sel=None):
        """The visible part line[left:left+width] with colour codes;
        sel = (start, end) inside it is shown inverse (a selection)."""
        text = line[left:left + width]
        if not text:
            return ""
        codes = [None] * len(text)
        for s, e, code in spans:
            s = max(s - left, 0)
            e = min(e - left, len(text))
            for k in range(s, e):
                codes[k] = code
        if sel:
            for k in range(max(sel[0], 0), min(sel[1], len(text))):
                codes[k] = "7"
        out = []
        cur = None
        start = 0
        for k in range(len(text) + 1):
            c = codes[k] if k < len(text) else "end"
            if c != cur:
                if k > start:
                    piece = text[start:k]
                    out.append(("\x1b[%sm%s\x1b[0m" % (cur, piece)) if cur else piece)
                cur = c
                start = k
        return "".join(out)
