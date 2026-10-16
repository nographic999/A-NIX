"""scan - list nearby WiFi networks, strongest signal first.

net.scan() does the work (see /lib/net.py) - each network name is
listed once, with its strongest access point. RSSI is signal
strength in dBm: closer to 0 is stronger (-40 strong, -80 weak).
"""

import shell
import net


def run(args, cwd):
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    shell._out("scanning for networks...")
    try:
        results = net.scan()
    except Exception as e:
        shell._err("scan failed", e)
        return
    if not results:
        shell._out("no networks found")
        return
    shell._out("%-32s  %8s  %4s  %s" % ("SSID", "SIGNAL", "CH", "SECURITY"))
    for ssid, rssi, channel, secured in results:
        shell._out("%s  %s  %4d  %s" %
                   (shell._c(shell.BOLD, "%-32s" % (ssid or "(hidden)")),
                    shell._c_signal(rssi, "%4d dBm" % rssi), channel,
                    "secured" if secured else shell._c(shell.YELLOW, "open")))
