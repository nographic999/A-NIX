"""uname - show the shell version (the banner also printed at login).
"""

import shell


def run(args, cwd):
    shell._out(shell._banner())
