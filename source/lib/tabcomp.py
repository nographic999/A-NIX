"""tabcomp - Tab completion for the prompt, split out of shell.py so
it is only in RAM after Tab is pressed.
"""

import os
from shell import ENV, ALIASES, FUNCTIONS, _BUILTINS, _join, _is_dir, _in_lib


def complete(before, cwd):
    """Tab completion for lineedit: the first word completes to a
    command (builtin, or a .py/.mpy/.sh name on $PATH or in cwd - never
    a /lib module), any other word to a file or directory name
    (directories end in /, so you can still Tab your way through
    /lib as an argument: cat /lib/sh<Tab>)."""
    word = before[before.rfind(" ") + 1:]
    first = " " not in before.strip() and not before.startswith(" ")
    if "/" in word:
        dir_part, prefix = word.rsplit("/", 1)
        search = _join(cwd, dir_part) if dir_part else "/"
        lead = dir_part + "/"
    else:
        prefix, search, lead = word, cwd, ""
    found = set()
    try:
        for name in os.listdir(search):
            if name.startswith(prefix):
                full = _join(search, name)
                if _is_dir(full):
                    found.add(lead + name + "/")
                elif not first:
                    found.add(lead + name)
                elif (name.endswith(".py") or name.endswith(".sh") or name.endswith(".mpy")) \
                        and not _in_lib(full):
                    found.add(lead + name)
    except OSError:
        pass
    if first and "/" not in word:
        for b in _BUILTINS + tuple(ALIASES) + tuple(FUNCTIONS):
            if b.startswith(prefix):
                found.add(b)
        for d in ENV.get("PATH", "/bin").split(":"):
            try:
                for name in os.listdir(d.strip() or "/bin"):
                    for ext in (".py", ".mpy", ".sh"):
                        if name.endswith(ext) and name.startswith(prefix):
                            found.add(name[:-len(ext)])
            except OSError:
                pass
    return sorted(found)
