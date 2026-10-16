"""jobs - the background job (started with `command &`).

  jobs       number, state, how long it has run, where its output goes
  jobs -f    follow its output live (like tail -f) until it ends or
             you press a key - the job keeps running either way

While you sit at the prompt, new output of the job is shown above the
prompt by itself ([1] in front); jobs -f is for watching it closely.
See /lib/jobctl.py.
"""

import sys
import shell
import jobctl as jobs
def run(args, cwd):
    if jobs.job is None:
        shell._out("no background job yet - start one with: command &")
        return
    if args and args[0] == "-f":
        if shell._capture_buf is not None:
            shell._err("jobs -f needs the console")
            return
        try:
            import select
        except ImportError:
            import uselect as select
        p = select.poll()
        p.register(sys.stdin, select.POLLIN)

        def key(ms):
            if p.poll(ms):
                sys.stdin.read(1)
                return True
            return False

        shell._out("following job %d - press any key to stop following" % jobs.job["n"])
        why = jobs.follow(key)
        if why == "ended":
            for j in jobs.finished():
                shell._out(jobs.describe(j))
        return
    shell._out(jobs.describe(jobs.job))
