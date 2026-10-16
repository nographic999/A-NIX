"""wget - download a file from the web to the board (W boards).

  wget <url> [file]

http:// or https://. Without a file name, the last part of the URL
is used (index.html if there is none). Streams straight to flash, so
the size is limited by free flash space, not RAM. Follows redirects,
checks free space first when the server tells the size, and never
leaves a half-written file behind - see net.download(). https is
encrypted but the server's certificate isn't checked.
"""

import sys
import shell
import net


def _screen(text):
    """Progress goes straight to the terminal (not into a > file), and
    not at all from cron or a background job (no screen there)."""
    if shell._to_screen():
        sys.stdout.write(text)


def _progress(done, total):
    if not shell._to_screen():
        return
    if total:
        sys.stdout.write("\r%d KB / %d KB" % (done // 1024, total // 1024))
    else:
        sys.stdout.write("\r%d KB" % (done // 1024))


def run(args, cwd):
    if not args or len(args) > 2:
        shell._out("usage: wget <url> [file]")
        return
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    url = args[0]
    if len(args) == 2:
        name = args[1]
    else:
        rest = url.split("://", 1)[-1].split("?", 1)[0]
        name = rest.rstrip("/").rsplit("/", 1)[-1] if "/" in rest.rstrip("/") else ""
        if not name:
            name = "index.html"
    path = shell._join(cwd, name)
    if shell._is_dir(path):
        shell._err("%s is a folder, not a file" % path)
        return
    shell._out("downloading %s -> %s" % (url, path))
    try:
        size, final_url = net.download(url, path, _progress)
    except ValueError as e:
        _screen("\r\x1b[K")
        shell._err(str(e))
        return
    except OSError as e:
        _screen("\r\x1b[K")
        shell._err("download failed", e)
        return
    _screen("\r\x1b[K")
    shell._out("saved %s (%d bytes)" % (path, size))
