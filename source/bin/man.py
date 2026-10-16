"""man - show the manual in the full-screen viewer (lib/view.py:
arrows, PgUp/PgDn, / to search, n next, q to quit). With a topic,
jumps straight to that command's CMD(1) entry. The viewer reads the
page a screen at a time, so the manual's size doesn't matter.
"""

import shell

MAN_PAGE = shell.MAN_PAGE


def _find_topic_line(path, topic):
    """The line of a command's entry (LS(1)), else of a section heading
    (man colours -> COLOURS, man settings -> SETTINGS)."""
    up = topic.upper()
    marker = up + "(1)"
    section = None
    try:
        with open(path) as f:
            for i, line in enumerate(f, 1):
                if marker in [p.strip() for p in line.strip().split(",")]:
                    return i
                head = line.rstrip()
                if section is None and head and head[0] != " " and \
                        (head == up or head.startswith(up + " (")):
                    section = i
    except OSError:
        return None
    return section


def run(args, cwd):
    start_line = 1
    if args:
        found = _find_topic_line(MAN_PAGE, args[0])
        if found is None:
            shell._err("no manual entry for %s" % args[0])
            return
        start_line = found
    import view
    if not view.start(MAN_PAGE, start_line, "A-NIX manual", man=True):
        shell._err("manual not found", MAN_PAGE)
