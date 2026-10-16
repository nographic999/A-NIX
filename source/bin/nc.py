"""nc - netcat: talk raw TCP or UDP to another device (W boards).

  nc <host> <port>          connect; what you type goes out, what comes
                            back is shown. Ctrl+] leaves.
  nc -l <port>              wait for one device to connect, then the same
  ... | nc <host> <port>    send the piped text, show the reply, end
                            when the other side closes or is quiet for
                            -w seconds (default 3)
  nc -u <host> <port> [text]   send one UDP packet (text, or the pipe),
                            show a reply if one comes within -w seconds

Files (any kind, any size - raw bytes, 1 KB at a time):
  nc -l <port> -o <file>    receive: save what the other side sends; done
                            when it closes the connection
  nc -l <port> -i <file>    serve: send the file to whoever connects
  nc <host> <port> -i <file>   send the file to a listening PC
  nc <host> <port> -o <file>   fetch what a PC sends into the file
A received file is written to <file>.tmp and only renamed when the
transfer ended normally, so a broken one never replaces a file. On the
PC use ncat (comes with Nmap), e.g.:
  board: nc -l 2323 -o fw.bin      PC: ncat --send-only IP 2323 < fw.bin
  board: nc -l 2323 -i log.csv     PC: ncat --recv-only IP 2323 > log.csv

Enter sends a bare LF (\\n) like the real nc; add -crlf for devices
that want CR LF (HTTP, SMTP, AT modems).
Ctrl-C goes to the other side as a byte while connected.
Example: echo "GET / HTTP/1.0" | nc -crlf example.com 80
"""

import sys
import time
import socket
import shell
import net

try:
    import select
except ImportError:
    import uselect as select

_ESC = "\x1d"       # Ctrl+]


_last = [b"\n"]


def _show(data):
    if data:
        _last[0] = data[-1:]
    screen = getattr(sys.stdout, "buffer", None)
    if shell._to_screen() and screen is not None:
        screen.write(data)
    else:
        shell._write(data.decode("utf-8", "replace"))


def _end_line():
    """A reply without a final newline would glue the prompt to it."""
    if _last[0] not in (b"\n", b"\r"):
        shell._write("\n")


def _send(sock, data):
    while data:
        n = sock.write(data)
        data = data[n or 0:]


def _drain(sock, wait_s):
    """Shows what arrives until the peer closes or is quiet wait_s."""
    p = select.poll()
    p.register(sock, select.POLLIN)
    while p.poll(int(wait_s * 1000)):
        try:
            data = sock.recv(512)
        except OSError:
            break
        if not data:
            break
        _show(data)


def _interactive(sock, crlf):
    import micropython
    shell._out("connected - Ctrl+] to leave")
    p = select.poll()
    p.register(sock, select.POLLIN)
    keys = select.poll()
    keys.register(sys.stdin, select.POLLIN)
    micropython.kbd_intr(-1)
    try:
        while True:
            busy = False
            if keys.poll(0):
                ch = sys.stdin.read(1)
                if ch == _ESC:
                    break
                if ch == "\r":
                    ch = "\r\n" if crlf else "\n"
                    _show(b"\r\n")      # the terminal sent CR only - move down
                _send(sock, ch.encode())
                busy = True
            if p.poll(0):
                data = sock.recv(512)
                if not data:
                    shell._out("\r\nconnection closed by the other side")
                    break
                _show(data)
                busy = True
            if not busy:
                time.sleep_ms(5)
    finally:
        micropython.kbd_intr(3)
    shell._out()


def _send_file(sock, path):
    """Streams a file out raw. Returns bytes sent."""
    import os
    total = os.stat(path)[6]
    sent = 0
    buf = bytearray(1024)
    t0 = time.ticks_ms()
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            _send(sock, memoryview(buf)[:n])
            sent += n
    return sent, total, time.ticks_diff(time.ticks_ms(), t0)


def _recv_file(sock, path):
    """Saves everything until the other side closes. Returns bytes."""
    import os
    tmp = path + ".tmp"
    got = 0
    ok = False
    buf = bytearray(1024)
    t0 = time.ticks_ms()
    try:
        with open(tmp, "wb") as f:
            while True:
                n = sock.readinto(buf)
                if not n:
                    break               # closed by the other side: done
                f.write(memoryview(buf)[:n])
                got += n
        shell._replace_file(tmp, path)
        ok = True
    finally:
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return got, time.ticks_diff(time.ticks_ms(), t0)


def _rate(n, ms):
    return "%d bytes in %.1f s (%.1f KB/s)" % (n, ms / 1000, n / 1024 / max(ms, 1) * 1000)


def run(args, cwd):
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    listen = udp = crlf = False
    infile = outfile = None
    wait_s = 3.0
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-l":
            listen = True
        elif a == "-u":
            udp = True
        elif a == "-crlf":
            crlf = True
        elif a in ("-i", "-o") and i + 1 < len(args):
            if a == "-i":
                infile = shell._join(cwd, args[i + 1])
            else:
                outfile = shell._join(cwd, args[i + 1])
            i += 1
        elif a == "-w" and i + 1 < len(args):
            try:
                wait_s = float(args[i + 1])
            except ValueError:
                wait_s = -1.0
            if not 0 <= wait_s <= 3600:
                shell._err("-w needs seconds, 0 to 3600")
                return
            i += 1
        else:
            rest.append(a)
        i += 1
    usage = ("usage: nc [-crlf] [-w s] <host> <port> | nc -l <port> | nc -u <host> <port> [text]\n"
             "       nc [-l] [host] <port> -i <file> (send) | -o <file> (receive)")
    if infile and outfile:
        shell._err("-i and -o together: one direction at a time")
        return
    if infile is not None:
        if shell._is_dir(infile):
            shell._err("%s is a folder" % infile)
            return
        try:
            import os
            os.stat(infile)
        except OSError:
            shell._err("file not found", infile)
            return
    if outfile is not None and shell._is_dir(outfile):
        shell._err("%s is a folder" % outfile)
        return
    try:
        if listen:
            port = int(rest[0])
            host = None
        else:
            host, port = rest[0], int(rest[1])
    except (IndexError, ValueError):
        shell._out(usage)
        return
    piped = shell._piped()

    if udp:
        text = " ".join(rest[2:])
        if not text and piped:
            with shell._input(cwd) as f:
                text = f.read()
        if not text:
            shell._out(usage)
            return
        if crlf:
            text = text.replace("\n", "\r\n")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto(text.encode(), socket.getaddrinfo(host, port)[0][-1])
            p = select.poll()
            p.register(s, select.POLLIN)
            if p.poll(int(wait_s * 1000)):
                _show(s.recv(1500))
                _end_line()
        except OSError as e:
            shell._err("udp to %s:%d failed" % (host, port), e)
        finally:
            s.close()
        return

    s = socket.socket()
    try:
        if listen:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
            s.listen(1)
            shell._out("waiting for a connection on port %d (Ctrl-C stops)" % port)
            conn, addr = s.accept()
            s.close()
            s = conn
            shell._out("connection from %s" % (addr[0] if isinstance(addr, tuple) else "a client"))
        else:
            s.settimeout(10)
            s.connect(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1])
            s.settimeout(None)
        if infile is not None:
            sent, total, ms = _send_file(s, infile)
            shell._out("sent %s" % _rate(sent, ms))
            if sent != total:
                shell._err("file changed while sending (%d of %d bytes)" % (sent, total))
        elif outfile is not None:
            got, ms = _recv_file(s, outfile)
            shell._out("received %s -> %s" % (_rate(got, ms), outfile))
        elif piped:
            with shell._input(cwd, binary=True) as f:
                data = f.read()
            if crlf:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            _send(s, data)
            _drain(s, wait_s)
            _end_line()
        else:
            _interactive(s, crlf)
    except OSError as e:
        shell._err("connection to %s:%d failed" % (host or "*", port), e)
    finally:
        s.close()
