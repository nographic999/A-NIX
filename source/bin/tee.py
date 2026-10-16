"""tee - pass a pipe through to the screen (or next command) AND save
a copy in a file.

  ... | tee [-a] <file>      -a appends instead of replacing

Example: ls -l /bin | tee list.txt | wc
"""

import shell


def run(args, cwd):
    append = "-a" in args
    files = [a for a in args if a != "-a"]
    if not files or not shell._piped():
        shell._out("usage: ... | tee [-a] <file>")
        return
    path = shell._join(cwd, files[0])
    if shell._is_dir(path):
        shell._err("%s is a folder" % path)
        return
    src = shell._input(cwd)
    try:
        out = shell._open_append(path) if append else shell._SafeFile(path)
    except OSError as e:
        shell._err("could not write %s" % path, e)
        return
    ok = False
    try:
        with src:
            while True:
                chunk = src.read(256)
                if not chunk:
                    break
                out.write(chunk)
                shell._write(chunk)
        ok = True
    finally:
        if append:
            out.close()
        elif ok:
            try:
                out.commit()
            except OSError as e:
                out.abort()
                shell._err("could not write %s" % path, e)
        else:
            out.abort()
