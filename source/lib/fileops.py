"""fileops - copying and removing whole folders (cp, cp -r, rm -r),
split out of shell.py so it is only in RAM while those commands run.
"""

import os
from shell import _SafeFile, _err, _join, _is_dir


def copy_file(src, dst):
    """Streams src to dst in 256-byte chunks - never holds more than
    one chunk in memory, so copying doesn't care how big the file is
    (same reasoning as cat's chunked read, or pg's page-at-a-time
    approach; see edit.py's docstring for what happens when a command
    *doesn't* do this).
    Written through _SafeFile: an interrupted copy never leaves a
    half-written destination."""
    out = None
    try:
        with open(src, "rb") as fin:
            out = _SafeFile(dst, binary=True)
            while True:
                chunk = fin.read(256)
                if not chunk:
                    break
                out.write(chunk)
        out.commit()
        return True
    except OSError as e:
        if out is not None:
            out.abort()
        _err("could not copy %s" % src, e)
        return False
    except BaseException:
        if out is not None:
            out.abort()
        raise


def copy_tree(src, dst):
    """Recursive `cp -r` - creates dst if it doesn't exist, or merges
    into it if it does (so copying into an existing directory doesn't
    fail the way a naive mkdir-or-die approach would). Refuses to copy
    a directory into itself, which would never end."""
    if (dst + "/").startswith(src.rstrip("/") + "/"):
        _err("cannot copy %s into itself" % src)
        return False
    try:
        os.mkdir(dst)
    except OSError:
        pass  # exists already - merge into it, like real cp -r
    try:
        entries = os.listdir(src)
    except OSError as e:
        _err("could not read directory %s" % src, e)
        return False
    ok = True
    for name in entries:
        s, d = _join(src, name), _join(dst, name)
        if _is_dir(s):
            ok = copy_tree(s, d) and ok
        else:
            ok = copy_file(s, d) and ok
    return ok


def remove_tree(path):
    """Recursive `rm -r` - removes every file first, then the now-
    empty directories on the way back up (a directory can't be
    rmdir'd while it still has anything in it). Refuses "/" - use
    `mkfs -a` to really erase everything."""
    if path.rstrip("/") == "":
        _err("refusing to remove / - use mkfs -a to erase everything")
        return False
    try:
        entries = os.listdir(path)
    except OSError as e:
        _err("could not read directory %s" % path, e)
        return False
    ok = True
    for name in entries:
        full = _join(path, name)
        if _is_dir(full):
            ok = remove_tree(full) and ok
        else:
            try:
                os.remove(full)
            except OSError as e:
                _err("could not remove %s" % full, e)
                ok = False
    if ok:
        try:
            os.rmdir(path)
        except OSError as e:
            _err("could not remove directory %s" % path, e)
            ok = False
    return ok
