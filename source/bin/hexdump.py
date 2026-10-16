"""hexdump - show a file's bytes in hex and as text, coloured by kind.

  hexdump [-s START] [-n LENGTH] [-p] <file>
  ... | hexdump [-n LENGTH] [-p]

  -s START   begin at this byte (decimal or 0x hex)
  -n LENGTH  show only this many bytes
  -p         plain: no colour

See /lib/hexfmt.py for the layout and colours. Streams 256 bytes at
a time, so any file size works.
"""

import shell
import hexfmt


def _number(text):
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def run(args, cwd):
    start = 0
    length = None
    plain = False
    rest = []
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == "-s" and i + 1 < len(args):
                start = _number(args[i + 1])
                i += 2
            elif a == "-n" and i + 1 < len(args):
                length = _number(args[i + 1])
                i += 2
            elif a == "-p":
                plain = True
                i += 1
            else:
                rest.append(a)
                i += 1
    except ValueError:
        shell._err("-s and -n need numbers (decimal or 0x hex)")
        return
    if start < 0 or (length is not None and length < 0):
        shell._err("-s and -n can't be negative")
        return
    try:
        f = shell._input(cwd, rest[0] if rest else None, binary=True)
    except OSError:
        shell._err("file not found", shell._join(cwd, rest[0]))
        return
    if f is None:
        shell._out("usage: hexdump [-s START] [-n LENGTH] [-p] <file>")
        return
    d = hexfmt.Dumper(start, plain)
    with f:
        if start:
            try:
                f.seek(start)
            except (OSError, AttributeError):
                skip = start
                while skip > 0:
                    got = f.read(min(256, skip))
                    if not got:
                        break
                    skip -= len(got)
        left = length
        while left is None or left > 0:
            chunk = f.read(256 if left is None else min(256, left))
            if not chunk:
                break
            d.feed(chunk)
            if left is not None:
                left -= len(chunk)
    d.end()
