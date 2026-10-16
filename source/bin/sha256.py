"""sha256 - SHA-256 checksum of files, like sha256sum.

  sha256 <file> [file2 ...]     print "checksum  file"
  sha256 <file> <checksum>      check a file against a known checksum
                                (e.g. from a download page): OK/FAILED
  ... | sha256                  checksum of the piped text

$? is 1 if a check failed or a file was missing.
"""

import shell

try:
    import hashlib
except ImportError:
    hashlib = None


def _digest(f):
    h = hashlib.sha256()
    while True:
        chunk = f.read(512)
        if not chunk:
            break
        h.update(chunk)
    return "".join("%02x" % b for b in h.digest())


def _is_hash(text):
    return len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text)


def run(args, cwd):
    if hashlib is None:
        shell._err("this firmware has no hashlib")
        return
    if not args:
        f = shell._input(cwd, binary=True)
        if f is None:
            shell._out("usage: sha256 <file> [file2 ...]  |  sha256 <file> <checksum>")
            return
        with f:
            shell._out("%s  -" % _digest(f))
        return
    if len(args) == 2 and _is_hash(args[1]):
        path = shell._join(cwd, args[0])
        try:
            with open(path, "rb") as f:
                got = _digest(f)
        except OSError:
            shell._err("file not found", path)
            return
        if got == args[1].lower():
            shell._out("%s: OK" % args[0])
        else:
            shell._out("%s: FAILED" % args[0])
            shell._out("  expected %s" % args[1].lower())
            shell._out("  got      %s" % got)
            shell._set_status(1)
        return
    for a in args:
        path = shell._join(cwd, a)
        if shell._is_dir(path):
            shell._err("%s is a folder, not a file" % path)
            continue
        try:
            with open(path, "rb") as f:
                shell._out("%s  %s" % (_digest(f), a))
        except OSError:
            shell._err("file not found", path)
