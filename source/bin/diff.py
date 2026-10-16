"""diff - compare two files line by line, like the real diff: finds
the longest common subsequence of lines, so an inserted or deleted
line shows up as just that one change instead of making every line
after it look different.

Output is the classic "normal" diff format:
  3c3        line 3 changed       < old line  ---  > new line
  5a6,7      lines 6-7 of file2 added after line 5 of file1
  8,9d9      lines 8-9 of file1 deleted (file2 continues after its line 9)

Like the real diff it prints nothing when the files are identical,
and sets $?: 0 = identical, 1 = different, 2 = trouble (file
missing, or too much to compare).

Memory: common lines at the start and end are skipped first, then
the remaining block needs one byte per (line1 x line2) pair - e.g.
200 changed lines against 200 needs 40 KB. Above MAX_CELLS it
refuses rather than running the Pico out of RAM.
"""

import shell

MAX_CELLS = 40000


def _read(path):
    with open(path) as f:
        return [line.rstrip("\n").rstrip("\r") for line in f]


def _rng(start, end):
    """1-based line range as diff prints it: "5" or "5,7"."""
    if end - start == 1:
        return "%d" % (start + 1)
    return "%d,%d" % (start + 1, end)


def _blocks(a, b):
    """Yields (a_start, a_end, b_start, b_end) for each changed block."""
    # skip common prefix / suffix - cheap, and usually most of the file
    p = 0
    while p < len(a) and p < len(b) and a[p] == b[p]:
        p += 1
    sa, sb = len(a), len(b)
    while sa > p and sb > p and a[sa - 1] == b[sb - 1]:
        sa -= 1
        sb -= 1
    n, m = sa - p, sb - p
    if n * m > MAX_CELLS:
        raise MemoryError("%d x %d changed lines" % (n, m))

    # LCS table, filled from the end; only the move taken is kept
    # per cell (0 = match, 1 = skip line in a, 2 = skip line in b)
    moves = bytearray(n * m)
    prev = [0] * (m + 1)
    for i in range(n - 1, -1, -1):
        cur = [0] * (m + 1)
        ai = a[p + i]
        row = i * m
        for j in range(m - 1, -1, -1):
            if ai == b[p + j]:
                cur[j] = prev[j + 1] + 1
            elif prev[j] >= cur[j + 1]:
                cur[j] = prev[j]
                moves[row + j] = 1
            else:
                cur[j] = cur[j + 1]
                moves[row + j] = 2
        prev = cur

    # walk the table, grouping consecutive non-matches into blocks
    i = j = 0
    while i < n or j < m:
        if i < n and j < m and moves[i * m + j] == 0:
            i += 1
            j += 1
            continue
        si, sj = i, j
        while i < n or j < m:
            if i < n and j < m and moves[i * m + j] == 0:
                break
            if i >= n:
                j += 1
            elif j >= m or moves[i * m + j] == 1:
                i += 1
            else:
                j += 1
        yield p + si, p + i, p + sj, p + j


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: diff <file1> <file2>")
        return
    path1, path2 = shell._join(cwd, args[0]), shell._join(cwd, args[1])
    try:
        a = _read(path1)
    except OSError:
        shell._err("file not found", path1)
        shell._set_status(2)
        return
    try:
        b = _read(path2)
    except OSError:
        shell._err("file not found", path2)
        shell._set_status(2)
        return

    changed = False
    c = shell._c
    try:
        for a0, a1, b0, b1 in _blocks(a, b):
            changed = True
            if a1 > a0 and b1 > b0:
                shell._out(c(shell.CYAN, "%sc%s" % (_rng(a0, a1), _rng(b0, b1))))
            elif a1 > a0:
                shell._out(c(shell.CYAN, "%sd%d" % (_rng(a0, a1), b0)))
            else:
                shell._out(c(shell.CYAN, "%da%s" % (a0, _rng(b0, b1))))
            for k in range(a0, a1):
                shell._out(c(shell.RED, "< " + a[k]))
            if a1 > a0 and b1 > b0:
                shell._out("---")
            for k in range(b0, b1):
                shell._out(c(shell.GREEN, "> " + b[k]))
    except MemoryError as e:
        shell._err("files too different to compare in RAM", e)
        shell._set_status(2)
        return
    shell._set_status(1 if changed else 0)
