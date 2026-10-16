"""which - what a command name runs: an alias, a shell builtin, or which
file on $PATH (or in the current folder).

  which <name> [name2 ...]

$? is 1 if a name isn't found.
"""

import shell


def run(args, cwd):
    if not args:
        shell._out("usage: which <command> [command2 ...]")
        return
    missing = False
    for name in args:
        if name in shell.ALIASES:
            shell._out("%s: alias for %s" % (name, shell.ALIASES[name]))
        elif name in shell.FUNCTIONS:
            shell._out("%s: function (defined by a script)" % name)
        elif name.lower() in shell._BUILTINS or name == ".":
            shell._out("%s: shell builtin" % name)
        else:
            found = shell._find_executable(name, cwd)
            if found and not shell._in_lib(found):
                shell._out(found)
            else:
                shell._out("%s: not found" % name)
                missing = True
    if missing:
        shell._set_status(1)
