"""edit - the full-screen editor; a thin wrapper around /lib/editor.py,
which holds the real editor (also used by man and license).
`ed` is an alias for this in /etc/profile.
"""

import editor as ed
def run(args, cwd):
    # CLI entry point called by the shell's dispatcher.
    if not args:
        import shell
        shell._out("usage: edit <file>")
        return
    import shell
    ed.start(shell._join(cwd, args[0]))
