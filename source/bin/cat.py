"""cat - print the contents of files, like the real cat.

  cat <file> [file2 ...]
  ... | cat

Streams 256 bytes at a time, so file size doesn't matter, and goes
through shell._write, so `cat a > b` and pipes work.
"""

import shell


def _copy(f, screen):
    last = ""
    while True:
        chunk = f.read(256)
        if not chunk:
            break
        if isinstance(chunk, bytes):
            # MicroPython's decode doesn't reject bad UTF-8: binary
            # files pass through instead of failing
            chunk = chunk.decode("utf-8", "replace")
        shell._write(chunk)
        last = chunk
    if screen and last and not last.endswith("\n"):
        shell._write("\n")             # keep the prompt on its own line


def run(args, cwd):
    if not args:
        f = shell._input(cwd)
        if f is None:
            shell._out("usage: cat <file> [file2 ...]")
            return
        with f:
            _copy(f, shell._to_screen())
        return
    for a in args:
        path = shell._join(cwd, a)
        if shell._is_dir(path):
            shell._err("%s is a folder, not a file" % path)
            continue
        try:
            with open(path, "rb") as f:
                _copy(f, shell._to_screen())
        except OSError:
            shell._err("file not found", path)
