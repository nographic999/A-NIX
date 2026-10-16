"""kill - stop the background job (`command &`). It stops at its next
line of output or before its next command; a command that is busy
without printing (a long wget) finishes that step first.
"""

import shell
import jobctl as jobs
def run(args, cwd):
    n = jobs.kill()
    if n is None:
        shell._out("no background job is running")
    else:
        shell._out("[%d] asked to stop" % n)
