"""choice - ask the user to pick one option (default Y/N).

Used in scripts for a menu-style prompt: `choice` alone offers Y/N;
`choice y n cancel` offers any set of words you like. Loops until
a valid option is entered (case-insensitively matched, but stored
uppercase in $CHOICE either way) rather than giving up after one
bad answer.
"""

import shell


def run(args, cwd):
    options = [a.upper() for a in args] if args else ["Y", "N"]
    while True:
        try:
            ans = input("[%s]? " % "/".join(options))
        except EOFError:
            shell._out()
            return
        ans = ans.strip().upper()
        if ans in options:
            shell.ENV["CHOICE"] = ans
            shell._out("you chose: %s" % ans)
            shell._set_status(0)        # an earlier wrong answer doesn't count
            return
        shell._err("invalid choice")
