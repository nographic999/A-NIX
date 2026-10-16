"""pg - page a file, LINES lines at a time (the classic *NIX pager
`pg`). Streams the file a page at a time rather
than loading it all up front, so it can page files too large for
`edit` to hold in memory.
"""

import sys
import shell


def run(args, cwd):
    if not args:
        shell._out("usage: pg <file>")
        return
    path = shell._join(cwd, args[0])
    try:
        page_size = shell._setting_int("LINES", 20)
    except ValueError:
        page_size = 20
    if page_size < 1:
        page_size = 20

    if shell._is_dir(path):
        shell._err("%s is a folder, not a file" % path)
        return
    try:
        f = open(path)
    except OSError:
        shell._err("file not found", path)
        return

    try:
        total = 0
        for _ in f:
            total += 1
        f.seek(0)

        shown = 0
        while True:
            page = []
            for _ in range(page_size):
                line = f.readline()
                if not line:
                    break
                page.append(line)
            if not page:
                break
            for ln in page:
                sys.stdout.write(ln if ln.endswith("\n") else ln + "\n")
            shown += len(page)
            if shown >= total:
                break
            try:
                ans = input("-- pg (%d%%) - Enter to continue, q to quit -- " %
                             int(shown * 100 / total))
            except EOFError:
                return
            if ans.strip().lower() == "q":
                return
    finally:
        f.close()
