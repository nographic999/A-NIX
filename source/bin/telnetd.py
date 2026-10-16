"""telnetd - use the A-NIX console over Wi-Fi from PuTTY (W boards).

  telnetd [-p password] [port]   start (default port 23)
  telnetd status                 running? who is connected?
  telnetd stop                   close the session and stop

The password: -p, else TELNET_PASS in /etc/anix.conf - one is
required. In PuTTY: connection type Other -> Telnet (NOT SSH), host =
the board's IP, port 23. The session is the SAME console as USB (both
see everything); one client at a time; not encrypted. See
/lib/telnetsrv.py. To have it after every boot: `@boot telnetd` in
/etc/crontab (after `@boot wifi -r 5`).
"""

import shell
import net


def run(args, cwd):
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    import telnetsrv as telnetd
    if args and args[0].lower() == "stop":
        shell._out("telnetd stopped" if telnetd.stop() else "telnetd is not running")
        return
    if args and args[0].lower() == "status":
        if not telnetd.running():
            shell._out("telnetd is " + shell._c(shell.GREY, "not running"))
            return
        who = telnetd.client_address()
        shell._out("telnetd %s on port %d, %s" % (shell._c(shell.GREEN, "running"), telnetd.port(),
                    ("client %s connected" % shell._c(shell.MAGENTA, "%s:%d" % who))
                    if who else "no client connected"))
        if telnetd.last_error:
            shell._out("last problem: %s" % shell._c(shell.YELLOW, telnetd.last_error))
        return

    password = None
    port = 23
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "-p" and i + 1 < len(args):
            password = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    if rest:
        try:
            port = int(rest[0])
        except ValueError:
            shell._err("port must be a number")
            return
    if password is None:
        password = shell.ENV.get("TELNET_PASS", "")
    if not password or password == "none":
        shell._err("a password is required: conf TELNET_PASS <password>, or telnetd -p <password>")
        return
    check = lambda typed: typed == password
    ip = net.local_ip()
    if ip is None:
        shell._err("no network - connect first (wifi)")
        return
    ok, why = telnetd.start(check, port)
    if not ok:
        shell._err(why)
        return
    shell._out("telnetd listening - in PuTTY: Other -> Telnet (not SSH), host %s, port %d" % (ip, port))
