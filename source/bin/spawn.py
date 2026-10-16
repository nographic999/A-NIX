"""spawn - start one of your async programs as a task on core 1.

  spawn <file.py | file.mpy> [args...]

The file needs `async def run(args):` that waits with await (see
/lib/tasksched.py for a full example). Several tasks run together;
`tasks` lists them, `stop N` / `stop all` ends them. print() inside
a task goes to /var/log/tasks.log.
"""

import shell
import tasksched as tasks
def run(args, cwd):
    if not args:
        shell._out("usage: spawn <file.py> [args...]")
        return
    path = shell._find_executable(args[0], cwd)
    if path is None or not (path.endswith(".py") or path.endswith(".mpy")):
        shell._err("no such program: %s (a .py or .mpy file)" % args[0])
        return
    if shell._in_lib(path):
        shell._err("%s is a library module, not a program" % path)
        return
    n, why = tasks.spawn(path, args[1:])
    if n is None:
        shell._err(why)
    else:
        shell._out("[task %d] %s started - tasks lists them, stop %d ends it" % (n, args[0], n))
