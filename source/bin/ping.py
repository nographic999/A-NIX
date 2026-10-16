"""ping - TCP-connect reachability/timing test. MicroPython has no raw
ICMP socket, so this times a TCP connection instead of a real ping.

The host name is looked up once (that time is shown separately), so
the per-attempt times are pure connection times. The default port is
80; many hosts only answer on others, e.g. `ping 8.8.8.8:53` or
`ping example.com:443`.
"""

import shell
import net


def run(args, cwd):
    if not args:
        shell._out("usage: ping <host>[:port] [count]")
        return
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    host, port = args[0], 80
    if ":" in host:
        host, port_s = host.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            shell._err("port must be a number")
            return
    count = max(1, int(args[1])) if len(args) > 1 and args[1].isdigit() else 4

    try:
        addr, dns_ms = net.resolve(host, port)
    except Exception as e:
        shell._err("could not resolve %s" % host, e)
        return
    shell._out("pinging %s port %d (tcp connect test, %d attempts, dns %d ms):" %
                (host, port, count, dns_ms))
    try:
        results = net.tcp_ping(addr, count=count)
    except Exception as e:
        shell._err("ping failed", e)
        return
    ok_times = [r for r in results if isinstance(r, int)]
    for i, r in enumerate(results, 1):
        if isinstance(r, int):
            shell._out("  attempt %d: %d ms" % (i, r))
        else:
            shell._out("  attempt %d: failed - %s" % (i, r))
    if ok_times:
        shell._out("%d/%d succeeded, avg %d ms" %
                    (len(ok_times), len(results), sum(ok_times) // len(ok_times)))
    else:
        shell._out("0/%d succeeded" % len(results))
        shell._set_status(1)
