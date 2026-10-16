"""cron - show and control scheduled jobs from /etc/crontab.

  cron              list jobs: schedule, next run, last run and $?
  cron log [N]      the last N lines of the job log (default 20)
  cron run N        run job N now and show its output
  cron reload       re-read /etc/crontab (after editing it)
  cron off | on     pause / resume all jobs

/etc/crontab lines:
  @boot <command>           once when the board starts
  every <N>s|m|h|d <command>
  at HH:MM <command>        daily, needs the clock (date ntp)
Jobs run while the shell waits at its prompt; output goes to
/var/log/cron.log. See /lib/crond.py.
"""

import shell
import crond as cron
def run(args, cwd):
    if not shell._on("CRONTAB") or shell.SAFE:
        shell._out("cron is not loaded: %s - jobs don't run" %
                   ("safe mode" if shell.SAFE else "CRONTAB=off in " + shell.CONF))
        if not shell.SAFE:
            shell._out("to use it: conf CRONTAB on, then reboot")
        return
    action = args[0].lower() if args else "list"
    if action == "list":
        if not cron.jobs:
            shell._out("no jobs - add lines to /etc/crontab, then: cron reload")
        else:
            shell._out("cron is %s" % (shell._c(shell.GREEN, "on") if cron.enabled
                                        else shell._c(shell.RED_BOLD, "OFF") + " (cron on)"))
            for i, job in enumerate(cron.jobs, 1):
                last = ("%s %s" % (job["last"], shell._c_status("[$?=%s]" % job["status"],
                                                             job["status"] == "0"))
                        if job["last"] else "not yet")
                shell._out("%2d  %s %s" % (i, shell._c(shell.CYAN, "%-12s" % job["spec"]), job["cmd"]))
                shell._out("    next: %-26s last: %s" % (cron.next_text(job), last))
        for e in cron.errors:
            shell._err("/etc/crontab " + e)
    elif action == "reload":
        cron.load()
        shell._out("%d job(s) loaded from %s" % (len(cron.jobs), cron.CRONTAB))
        for e in cron.errors:
            shell._err("/etc/crontab " + e)
    elif action in ("on", "off"):
        cron.enabled = action == "on"
        shell._out("cron %s" % action)
    elif action == "run":
        try:
            job = cron.jobs[int(args[1]) - 1]
        except (IndexError, ValueError):
            shell._err("usage: cron run <job number> (see: cron)")
            return
        shell._write(cron.run_job(job))
        shell._out(shell._c_status("[$?=%s]" % job["status"], job["status"] == "0"))
    elif action == "log":
        try:
            n = int(args[1]) if len(args) > 1 else 20
        except ValueError:
            n = 20
        keep = []
        try:
            with open(cron.LOG) as f:
                for line in f:
                    keep.append(line)
                    if len(keep) > n:
                        del keep[0]
        except OSError:
            shell._out("no job has run yet")
            return
        color = shell._colors()
        for line in keep:
            if color and "[$?=" in line and not line.startswith(" "):
                k = line.rindex("[$?=")
                st = line[k:].rstrip()
                head, sep, cmd = line[:k].partition("  ")     # time  command
                line = "%s%s%s%s\n" % (shell._c(shell.GREEN, head), sep, cmd,
                                        shell._c_status(st, st == "[$?=0]"))
            shell._write(line)
    else:
        shell._out("usage: cron [log [N] | run N | reload | on | off]")
