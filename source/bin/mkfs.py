"""mkfs - wipe files.

  mkfs       erases everything inside /root (your own files and
             scripts) and keeps A-NIX itself working.
  mkfs -a    erases the WHOLE filesystem, A-NIX included (/bin, /lib,
             /etc, boot.py, main.py). Afterwards the board starts to
             the bare MicroPython REPL, and A-NIX has to be copied
             back with Thonny or mpremote.

Always asks for confirmation first - there's no undo.
"""

import os
import shell


def _rm(path):
    """Recursively removes path (file or directory), returning
    (files_removed, dirs_removed)."""
    files = dirs = 0
    try:
        os.remove(path)
        return 1, 0
    except OSError:
        pass
    for name in os.listdir(path):
        f, d = _rm(path + "/" + name if path != "/" else "/" + name)
        files += f
        dirs += d
    os.rmdir(path)
    return files, dirs + 1


def _wipe_inside(path):
    files = dirs = 0
    for name in os.listdir(path):
        f, d = _rm(path.rstrip("/") + "/" + name)
        files += f
        dirs += d
    return files, dirs


def run(args, cwd):
    everything = bool(args) and args[0] == "-a"
    if everything:
        shell._out("WARNING: THE WHOLE FILESYSTEM WILL BE ERASED, A-NIX INCLUDED!")
        shell._out("The board will start to the bare REPL; A-NIX must be copied back.")
        target = "/"
    else:
        target = shell.ENV.get("HOME", "/root").rstrip("/") or "/"
        if target == "/":
            shell._err("$HOME is / - use mkfs -a if you really mean everything")
            return
        shell._out("WARNING: everything inside %s will be erased." % target)
        shell._out("(A-NIX itself is kept. Use mkfs -a to erase everything.)")
    try:
        answer = input("Are you sure you want to continue? (y/n) ")
    except EOFError:
        answer = ""
    if answer.strip().lower() != "y":
        shell._out("Operation cancelled. Nothing was erased.")
        return

    shell._out("Erasing...")
    try:
        files, dirs = _wipe_inside(target)
    except OSError as e:
        shell._err("erase stopped", e)
        return
    shell._out("Operation complete.")
    shell._out("%d files removed." % files)
    shell._out("%d directories removed." % dirs)
