"""curl - fetch a URL with HTTP GET, http:// or https://.

Shows the status line and the page body (headers hidden; a redirect
shows where it points). Only the first 8 KB of a response are kept,
to protect RAM, and the first 500 characters are printed so a big
page doesn't scroll everything off the screen - both limits are
reported when they apply. https encrypts the connection but does
not check the server's certificate (the Pico has no certificate
store) - see /lib/net.py.
"""

import shell
import net

SHOW_CHARS = 500


def run(args, cwd):
    if not args:
        shell._out("usage: curl <http://url | https://url>")
        return
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    try:
        code, reason, headers, body, truncated = net.http_get(args[0])
    except ValueError as e:
        shell._err(str(e))
        return
    except Exception as e:
        shell._err("request failed", e)
        return
    shell._out("HTTP %d %s" % (code, reason))
    if 300 <= code < 400 and "location" in headers:
        shell._out("redirects to: %s" % headers["location"])
    if body:
        shell._out(body[:SHOW_CHARS])
    if len(body) > SHOW_CHARS:
        shell._out("... (showing %d of %d characters)" % (SHOW_CHARS, len(body)))
    if truncated:
        shell._out("... (response longer than 8 KB - the rest was not downloaded)")
    if code >= 400 or code == 0:
        shell._set_status(1)
