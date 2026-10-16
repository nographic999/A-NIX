"""license - show the MIT license text in the full-screen viewer, the
same way `man` shows the manual. q to exit.
"""

import shell


def run(args, cwd):
    import view
    if not view.start(shell.LICENSE_PATH, 1, "license"):
        shell._err("license file not found", shell.LICENSE_PATH)
