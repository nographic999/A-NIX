"""wifi - connect to a WiFi network (or check/drop the connection).

`wifi` with no arguments reads WIFI_SSID/WIFI_PASS from /etc/anix.conf
so a board that always joins the same network doesn't need the
credentials typed every session. WIFI_COUNTRY there (e.g. LT) sets
the radio's country - see /lib/net.py for that and for the actual
connection handshake.

`wifi -r N` tries up to N times, RETRY_WAIT seconds apart, and sets
$? to 1 if all failed - for /etc/crontab:  @boot wifi -r 5 && telnetd
"""

import time
import shell
import net

RETRY_WAIT = 5      # seconds between -r tries


def _paint_status(text):
    """Like `ip -c`: Connected green, addresses magenta, the signal by
    strength; Not connected / WiFi off red."""
    if not shell._colors():
        return text
    c = shell._c
    if not text.startswith("Connected"):
        return c(shell.RED_BOLD, text)
    out = []
    for word in text.split(" "):
        if word == "Connected":
            word = c(shell.GREEN, word)
        elif word.count(".") == 3 and word.replace(".", "").isdigit():
            word = c(shell.MAGENTA, word)
        elif word.lstrip("-").isdigit() and int(word) < 0:
            word = shell._c_signal(int(word), word)
        out.append(word)
    return " ".join(out)


def run(args, cwd):
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    if len(args) == 1 and args[0].lower() == "status":
        shell._out(_paint_status(net.status()))
        return
    if len(args) == 1 and args[0].lower() == "off":
        try:
            net.disconnect()
            shell._out("wifi disconnected, radio off")
        except Exception as e:
            shell._err("could not disconnect", e)
        return

    tries = 1
    if len(args) >= 2 and args[0] == "-r":
        try:
            tries = max(1, int(args[1]))
        except ValueError:
            shell._err("-r needs a number of tries")
            return
        args = args[2:]

    if args:
        ssid = args[0]
        password = args[1] if len(args) > 1 else shell.ENV.get("WIFI_PASS", "")
    else:
        ssid = shell.ENV.get("WIFI_SSID", "")
        password = shell.ENV.get("WIFI_PASS", "")
        if password == "none":
            password = ""
        if not ssid or ssid == "none":
            shell._out("usage: wifi [-r tries] [<ssid> [password]]  |  wifi status  |  wifi off")
            shell._out("(or set WIFI_SSID / WIFI_PASS in /etc/anix.conf to use wifi with no args)")
            shell._put_status("1")
            return

    for n in range(1, tries + 1):
        if tries > 1:
            shell._out("connecting to %s ... (try %d of %d)" % (ssid, n, tries))
        else:
            shell._out("connecting to %s ..." % ssid)
        try:
            ok, result = net.connect(ssid, password)
        except Exception as e:
            ok, result = False, "could not connect - %s" % e
        if ok:
            shell._out("%s - ip %s" % (shell._c(shell.GREEN, "connected"),
                                       shell._c(shell.MAGENTA, result)))
            return
        if n < tries:
            shell._out(result + " - next try in %d s" % RETRY_WAIT)
            time.sleep(RETRY_WAIT)
    shell._err(result)
