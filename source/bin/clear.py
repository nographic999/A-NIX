"""clear - clear the screen.

Just the ANSI "clear screen + home cursor" escape sequence - the
same two codes the editor and the shell's start-up banner use.
"""

import sys


def run(args, cwd):
    sys.stdout.write("\x1b[2J\x1b[H")
