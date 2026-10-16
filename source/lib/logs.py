"""logs - one place that writes and trims the system logs in /var/log
(boot.log, cron.log, tasks.log, job.log), so none of them can fill
the flash.

    append(path, text)    add text; trims the file first if needed
    trim(path)            keep only the newest part once it's too big

The size limit is LOG_MAX in /etc/anix.conf (bytes, default 16384).
A log that grows past it keeps its newest half, cut at a line start.
Trimming reads only that half (never the whole file into RAM) and
writes it to a temporary file that replaces the log when complete,
so a power cut can't leave a half-written log.
"""

import os
import sys

DEFAULT_MAX = 16384


def limit():
    # the shell only if it's already loaded: main.py trims the boot log
    # before it, and importing it there would cost a program its RAM
    shell = sys.modules.get("shell")
    try:
        n = int(shell.ENV.get("LOG_MAX", DEFAULT_MAX)) if shell else DEFAULT_MAX
        return n if n >= 1024 else 1024
    except ValueError:
        return DEFAULT_MAX


def _folders(path):
    parts = path.split("/")[1:-1]
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            os.mkdir(cur)
        except OSError:
            pass


def trim(path, max_bytes=None):
    """Keeps the newest half of the log once it passes max_bytes."""
    if max_bytes is None:
        max_bytes = limit()
    try:
        size = os.stat(path)[6]
    except OSError:
        return
    if size <= max_bytes:
        return
    keep = max_bytes // 2
    tmp = path + ".tmp"
    try:
        with open(path, "rb") as src:
            src.seek(size - keep)
            src.readline()                  # drop the cut-off first line
            with open(tmp, "wb") as dst:
                while True:
                    chunk = src.read(512)
                    if not chunk:
                        break
                    dst.write(chunk)
        try:
            os.rename(tmp, path)
        except OSError:
            os.remove(path)
            os.rename(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def append(path, text, max_bytes=None):
    """Appends text to the log (creating /var/log if needed). Holds the
    shell's filesystem lock, so core 1 never loads a command meanwhile."""
    shell = sys.modules.get("shell")
    if shell is not None:
        shell.fs_begin()
    try:
        _folders(path)
        trim(path, max_bytes)
        with open(path, "a") as f:
            f.write(text)
    except OSError:
        pass
    finally:
        if shell is not None:
            shell.fs_end()
