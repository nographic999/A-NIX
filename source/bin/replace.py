"""replace - replace text, like a simple sed s/old/new/g.

  replace [-i] "old" "new" <file>   change the file itself; prints how
                                    many places changed
  ... | replace [-i] "old" "new"    change the piped text, pass it on

  -i  ignore upper/lower case when looking for old

The file is rewritten safely (a temporary file replaces it only when
done), one line at a time, so its size doesn't matter. Quote texts
with spaces. "new" may be "" to delete old.
"""

import shell


def _sub(line, old, new, nocase):
    if not nocase:
        n = line.count(old)
        return (line.replace(old, new) if n else line), n
    low = line.lower()
    key = old.lower()
    out = []
    i = 0
    n = 0
    while True:
        k = low.find(key, i)
        if k < 0:
            break
        out.append(line[i:k])
        out.append(new)
        i = k + len(old)
        n += 1
    out.append(line[i:])
    return "".join(out), n


def run(args, cwd):
    nocase = "-i" in args
    args = [a for a in args if a != "-i"]
    if len(args) < 2 or not args[0]:
        shell._out('usage: replace [-i] "old" "new" <file>  |  ... | replace "old" "new"')
        return
    old, new = args[0], args[1]
    if len(args) == 2:
        f = shell._input(cwd)
        if f is None:
            shell._out('usage: replace [-i] "old" "new" <file>  |  ... | replace "old" "new"')
            return
        with f:
            for line in f:
                shell._write(_sub(line, old, new, nocase)[0])
        return
    path = shell._join(cwd, args[2])
    total = 0
    out = None
    try:
        with open(path) as f:
            out = shell._SafeFile(path)
            for line in f:
                text, n = _sub(line, old, new, nocase)
                total += n
                out.write(text)
    except OSError:
        if out is not None:
            out.abort()
        shell._err("file not found", path)
        return
    except BaseException:
        if out is not None:
            out.abort()
        raise
    if total:
        out.commit()
    else:
        out.abort()
        shell._set_status(1)
    shell._out("%d replacement(s) in %s" % (total, args[2]))
