"""stop - end a task started with `spawn`.

  stop <N>     the task with that number (see: tasks)
  stop all     every task

A task ends at its next `await`.
"""

import shell
import tasksched as tasks
def run(args, cwd):
    if not args:
        shell._out("usage: stop <task number> | stop all")
        return
    if args[0] == "all":
        n = tasks.stop()
        shell._out("%d task(s) asked to stop" % n)
        return
    try:
        k = int(args[0])
    except ValueError:
        shell._out("usage: stop <task number> | stop all")
        return
    if tasks.stop(k):
        shell._out("task %d asked to stop" % k)
    else:
        shell._err("no running task %d (see: tasks)" % k)
