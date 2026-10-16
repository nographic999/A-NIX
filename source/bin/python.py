"""python - a nested Python console; `exit` alone returns to the shell.

Works like the real REPL: an expression prints its value (1+1 -> 2),
a statement just runs (x = 5). Blocks work too - a line ending in ":"
(def, for, if, while, class, with, try...) or with an unclosed (, [
or { switches to "... " continuation lines until an empty line ends
the block:

    >>> for i in range(3):
    ...     print(i)
    ...
    0 1 2 (each on its own line)

ENV is the shell's variable dict, so the console and scripts share
variables. Ctrl-C stops a running statement and returns to the shell.
"""

import shell


def _open_brackets(text):
    depth = 0
    quote = None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth > 0


def _needs_more(text):
    last = text.rstrip().split("\n")[-1]
    code = last.split("#", 1)[0].rstrip()
    return code.endswith(":") or code.endswith("\\") or _open_brackets(text)


def run(args, cwd):
    shell._out("python console - type exit alone to return to the shell")
    g = {"__name__": "__console__", "ENV": shell.ENV}
    while True:
        try:
            line = input(">>> ")
        except EOFError:
            shell._out()
            return                      # Ctrl-D leaves, like the real REPL
        if line.strip() == "exit":
            return
        if not line.strip():
            continue
        source = line
        block = line.split("#", 1)[0].rstrip().endswith(":")
        while _needs_more(source) or block:
            try:
                more = input("... ")
            except EOFError:
                more = ""
            if not more.strip():
                if block:
                    break           # empty line ends a block
                continue
            source += "\n" + more
            if more.split("#", 1)[0].rstrip().endswith(":"):
                block = True
        try:
            try:
                result = eval(source, g)
            except SyntaxError:
                exec(source, g)
            else:
                if result is not None:
                    shell._out(repr(result))
        except Exception as e:
            shell._err("%s: %s" % (e.__class__.__name__, e))
