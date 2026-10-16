"""tasks - list the tasks started with `spawn`: number, state
(running, done, stopped, failed), how long, program and arguments.

  tasks          list
  tasks log [N]  the last N lines they printed (default 20)
  tasks clean    forget the finished ones
"""

import shell
import tasksched as tasks
def run(args, cwd):
    if args and args[0] == "log":
        tasks.flush()
        try:
            n = int(args[1]) if len(args) > 1 else 20
        except ValueError:
            n = 20
        keep = []
        try:
            with open(tasks.LOG) as f:
                for line in f:
                    keep.append(line)
                    if len(keep) > n:
                        del keep[0]
        except OSError:
            shell._out("no task has printed anything yet")
            return
        for line in keep:
            shell._write(line)
        return
    if args and args[0] == "clean":
        tasks.forget_finished()
        return
    rows = tasks.listing()
    if not rows:
        shell._out("no tasks - start one with: spawn <file.py>")
        return
    shell._out("  #  state       time  program")
    for r in rows:
        for word, code in (("running", shell.GREEN), ("failed", shell.RED_BOLD),
                           ("stopped", shell.GREY), ("done", shell.GREY)):
            k = r.find(" " + word + " ")
            if 0 <= k < 8:              # the state column only
                r = r[:k + 1] + shell._c(code, word) + r[k + 1 + len(word):]
                break
        shell._out(r)
    shell._out("scheduler on core 1: %s" % (shell._c(shell.GREEN, "running") if tasks.running()
                                           else "stopped"))
