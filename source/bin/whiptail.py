"""whiptail - text-mode dialog boxes (menu/msgbox/yesno/inputbox),
like the real whiptail behind raspi-config's menus. See `man
whiptail` for full usage; `tui` (in /lib) is the actual drawing
engine if you want these dialogs from your own program instead.

The answer goes in $WHIPTAIL (the chosen menu tag, the typed text,
YES/NO) - a dialog draws on the screen, so it can't also be the
output that $(...) captures. $? is 0 for confirmed, 1 for cancelled,
so a script can branch with `if $? == 1 then`. Multi-word text needs
quotes: whiptail msgbox "Saved."
"""

import sys
import shell
import tui


def _finish():
    """Every dialog draws as an overlay wherever the cursor happened
    to be (see tui.py's header for why - no full-screen clear during
    the dialog itself), but leaving the box on screen once it's done
    would leave the next shell prompt landing awkwardly inside it.
    Clearing here, once, after any dialog closes, is simpler and
    safer than trying to track exactly where to put the cursor back."""
    sys.stdout.write("\x1b[2J\x1b[H")


def run(args, cwd):
    if not args:
        shell._out("usage: whiptail msgbox <text>")
        shell._out("       whiptail yesno <text>")
        shell._out("       whiptail inputbox <prompt> [default]")
        shell._out("       whiptail menu <title> <tag1> <text1> [tag2 text2 ...]")
        return

    kind = args[0].lower()
    rest = args[1:]

    if kind == "msgbox":
        if not rest:
            shell._out("usage: whiptail msgbox <text>")
            return
        tui.msgbox(rest[0])
        _finish()

    elif kind == "yesno":
        if not rest:
            shell._out("usage: whiptail yesno <text>")
            return
        result = tui.yesno(rest[0])
        _finish()
        shell.ENV["WHIPTAIL"] = "YES" if result else "NO"
        shell._set_status(0 if result else 1)

    elif kind == "inputbox":
        if not rest:
            shell._out("usage: whiptail inputbox <prompt> [default]")
            return
        prompt = rest[0]
        default = rest[1] if len(rest) > 1 else ""
        result = tui.inputbox(prompt, default)
        _finish()
        if result is None:
            shell._set_status(1)
        else:
            shell.ENV["WHIPTAIL"] = result
            shell._set_status(0)

    elif kind == "menu":
        if len(rest) < 3 or len(rest) % 2 == 0:
            shell._out("usage: whiptail menu <title> <tag1> <text1> [tag2 text2 ...]")
            return
        title = rest[0]
        pairs = rest[1:]
        items = [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)]
        result = tui.menu(items, title=title)
        _finish()
        if result is None:
            shell._set_status(1)
        else:
            shell.ENV["WHIPTAIL"] = result
            shell._set_status(0)

    else:
        shell._err("unknown dialog type - %s" % kind)
