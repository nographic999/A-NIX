"""telnetd - the A-NIX console over Wi-Fi, for any telnet client
(PuTTY: connection type Telnet, port 23).

How it works: the client's connection is attached to MicroPython's
console with os.dupterm - the same mechanism the official WebREPL
uses. Everything the shell prints goes to USB AND the network; keys
from either arrive as keyboard input. So it is ONE shared session,
running on core 0 next to everything else (core 1 stays free for
httpd). A new client is picked up while the shell waits at its
prompt (it checks about once a second) - not while a command runs.

A new client first gets a password prompt; until it's right, nothing
of the console reaches it and nothing it types reaches the shell.
Three wrong tries close the connection. One client at a time.

Telnet details handled here: IAC command sequences from the client
are filtered out; the server announces WILL ECHO + WILL SUPPRESS-GO-
AHEAD so the client sends each key at once (character mode) instead
of whole lines - needed for arrows, Tab and the editor; Enter, which
telnet sends as CR LF or CR NUL, becomes a single CR; a 0xFF byte in
the output is doubled as the protocol requires.

Not encrypted: the password and everything typed travel as plain
text. Fine at home, not on public networks. Lost on a soft reset
(Ctrl-D) or reboot - `@boot telnetd` in /etc/crontab starts it at
every boot.
"""

import io
import os
import sys
import time
import socket

import select

_IAC, _DONT, _DO, _WONT, _WILL, _SB, _SE = 255, 254, 253, 252, 251, 250, 240
_ECHO, _SGA = 1, 3
_POLL, _CLOSE = 3, 4            # MicroPython stream ioctl requests
_POLLIN, _POLLOUT = 1, 4

_listen = None
_session = None
last_error = None       # what went wrong last (telnetd status shows it)
_check = None           # typed password -> True/False (set by telnetd)
_port = 23


def _note(what, e):
    global last_error
    last_error = ("%s: %s" if isinstance(e, str) else "%s: %r") % (what, e)


class _Session(io.IOBase):
    def __init__(self, sock, addr, check):
        self.sock = sock
        self.addr = addr
        self.check = check
        self.authed = False
        self.typed = ""
        self.tries = 0
        self.inbuf = b""
        self.state = 0          # telnet IAC parser state
        self.skip_after_cr = False
        self.closed = False
        self.eof = False
        self.last_rx = time.ticks_ms()  # for replacing a dead/idle session
        sock.settimeout(2)
        self.poller = select.poll()
        self.poller.register(sock, select.POLLIN)
        self._send(bytes((_IAC, _WILL, _ECHO, _IAC, _WILL, _SGA, _IAC, _DO, _SGA)))
        import shell
        color = shell.ENV.get("COLOR", "on").lower() != "off"
        tag = "\x1b[01;35mTELNET\x1b[0m" if color else "TELNET"
        self._send(("\r\n%s - %s\r\n" % (shell._banner(color), tag)).encode())
        self._send(b"password: ")

    def _send(self, data):
        if self.closed:
            return
        try:
            tries = 0
            while data:
                n = self.sock.write(data)
                if not n:               # buffer full: wait a little, not forever
                    tries += 1
                    if tries > 200:
                        raise OSError("send stalled")
                    time.sleep_ms(10)
                    continue
                data = data[n:]
        except OSError as e:
            _note("send to client", e)
            self.closed = True

    def _welcome(self):
        """After login: the prompt (and anything half-typed on it) at
        once, so there's no need to press Enter. While a command runs
        there is no prompt - its output simply follows."""
        self._send(b"\r\n")             # end the password line
        try:
            le = sys.modules.get("lineedit")
            shown = le.on_screen() if le else None
        except Exception:               # never let an error out of a read:
            shown = None                # MicroPython would drop the session
        if shown:
            self._send(shown.encode())

    def _filter(self, raw):
        """Telnet bytes -> plain keyboard bytes."""
        out = bytearray()
        for b in raw:
            st = self.state
            if st == 0:
                if b == _IAC:
                    self.state = 1
                elif self.skip_after_cr and b in (0, 10):
                    self.skip_after_cr = False
                else:
                    self.skip_after_cr = b == 13
                    out.append(b)
            elif st == 1:
                if b == _IAC:
                    out.append(_IAC)        # escaped 0xFF
                    self.state = 0
                elif b in (_WILL, _WONT, _DO, _DONT):
                    self.state = 2
                elif b == _SB:
                    self.state = 3
                else:
                    self.state = 0          # 2-byte command (NOP, AYT ...)
            elif st == 2:
                self.state = 0              # option byte of WILL/DO/...
            elif st == 3:
                if b == _IAC:
                    self.state = 4
            elif st == 4:
                self.state = 0 if b == _SE else 3
        return bytes(out)

    def _login(self, data):
        """Collects the password. Returns True when the session must end.
        Keys typed after the password (in the same packet) are kept."""
        for i, b in enumerate(data):
            if b in (13, 10):
                if self.check(self.typed):
                    self.authed = True
                    self.typed = ""
                    self._welcome()
                    self.inbuf += data[i + 1:]
                    return False
                self.tries += 1
                self.typed = ""
                if self.tries >= 3:
                    self._send(b"\r\nwrong password - bye\r\n")
                    return True
                self._send(b"\r\nwrong password\r\npassword: ")
            elif b in (8, 127):
                if self.typed:
                    self.typed = self.typed[:-1]
                    self._send(b"\b \b")
            elif b == 3:
                return True
            elif 32 <= b < 127 and len(self.typed) < 64:
                self.typed += chr(b)
                self._send(b"*")
        return False

    def _fill(self):
        """Reads what the client sent. False if the client is gone."""
        if self.closed or self.eof:
            return False
        try:
            if not self.poller.poll(0):
                return True
            raw = self.sock.recv(64)
        except OSError as e:
            if e.args and e.args[0] == 11:      # EAGAIN: nothing after all
                return True
            if e.args and e.args[0] == 104:     # ECONNRESET: the client just left
                _note("client %s" % self.addr[0], "left before logging in (a network scan "
                      "or a closed window)" if not self.authed else "closed the connection")
            else:
                _note("read from client", e)
            return False
        if not raw:
            _note("client %s" % self.addr[0], "left before logging in" if not self.authed
                  else "closed the connection")
            return False
        self.last_rx = time.ticks_ms()
        if not self.authed and raw.startswith(b"SSH-"):
            # PuTTY set to SSH: it shows no text from a non-SSH server, so
            # just drop it and leave the reason for `telnetd status`
            _note("client", "spoke SSH - PuTTY must be set to Telnet")
            return False
        data = self._filter(raw)
        if not self.authed:
            if self._login(data):
                return False
            return True
        self.inbuf += data
        return True

    # --- stream interface used by os.dupterm ---

    def readinto(self, buf):
        if not self.inbuf:
            if not self._fill():
                # the client is gone: report "nothing" instead of EOF (EOF
                # makes MicroPython print "dupterm: EOF received,
                # deactivating"); poll() detaches and cleans up quietly
                self.eof = True
                return None
            if not self.inbuf:
                return None                 # nothing (yet)
        n = min(len(buf), len(self.inbuf))
        buf[:n] = self.inbuf[:n]
        self.inbuf = self.inbuf[n:]
        return n

    def write(self, buf):
        if self.authed and not self.closed:
            data = bytes(buf)
            if _IAC in data:
                data = data.replace(bytes((_IAC,)), bytes((_IAC, _IAC)))
            self._send(data)
        return len(buf)

    def ioctl(self, req, arg):
        if req == _POLL:
            # "a key is ready" only for real keys: the bytes are taken in
            # here, so the password, telnet negotiation or a client that
            # left never make the shell wait in a read that gets nothing
            ret = 0
            if arg & _POLLIN:
                if not self.inbuf and not self._fill():
                    self.eof = True
                if self.inbuf:
                    ret |= _POLLIN
            if arg & _POLLOUT:
                ret |= _POLLOUT
            return ret
        if req == _CLOSE:
            self.close()
            return 0
        return 0

    def close(self):
        global _session
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        if _session is self:
            _session = None


def poll():
    """Called by the shell about once a second while it waits at the
    prompt: takes a waiting client, if any. Done here, in the shell's
    own context, rather than from an lwIP socket callback - on the
    Pico W, output written from inside that callback never reached
    the client."""
    if _listen is None:
        return
    if _session is not None and (_session.eof or _session.closed):
        _drop(_session)                 # client gone: detach quietly
    try:
        cl, addr = _listen.accept()
    except OSError:
        return                          # nobody waiting
    _attach(cl, addr)


def _attach(cl, addr):
    global _session
    try:
        if _session is not None:           # (a gone one was dropped by poll)
            idle = time.ticks_diff(time.ticks_ms(), _session.last_rx)
            # a client that never logged in within 30 s, or one silent
            # for 10 min (gone without closing), gives way to a new one
            if (not _session.authed and idle > 30000) or idle > 600000:
                _drop(_session)
            else:
                cl.write(b"A-NIX: another telnet session is open - try later\r\n")
                cl.close()
                return
        prev = os.dupterm(None)
        if isinstance(prev, _Session):
            prev.close()                    # an old telnet session left in the slot
            prev = None
        if prev is not None:
            os.dupterm(prev)                # someone else (WebREPL?) has the slot
            cl.write(b"A-NIX: the console is taken (WebREPL running?)\r\n")
            cl.close()
            return
        sess = _Session(cl, addr, _check)
        if sess.closed:
            # the greeting couldn't be sent - say why, on the USB console
            print("telnetd: client %s - %s" % (addr[0], last_error))
            sess.close()
            return
        _session = sess
        os.dupterm(sess)
    except Exception as e:
        _note("attach", e)
        try:
            cl.close()
        except OSError:
            pass
        _session = None
        print("telnetd: could not attach a client -", e)


def _drop(sess):
    """Detaches and closes a session."""
    global _session
    try:
        cur = os.dupterm(None)
        if cur is not None and cur is not sess and not isinstance(cur, _Session):
            os.dupterm(cur)
    except Exception:
        pass
    sess.close()
    _session = None


def supported():
    return hasattr(os, "dupterm")


def start(check, port=23):
    """Starts listening. check(typed) -> True/False decides logins.
    Returns (True, "") or (False, reason)."""
    global _listen, _check, _port
    if _listen is not None:
        return False, "already running on port %d - telnetd stop first" % _port
    if not supported():
        return False, "this firmware has no os.dupterm"
    _check = check
    _port = port
    s = socket.socket()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
        s.listen(1)
        s.setblocking(False)            # poll() just looks, never waits
    except Exception as e:
        s.close()
        return False, "could not listen on port %d - %s" % (port, e)
    _listen = s
    return True, ""


def stop():
    """Closes the session (if any) and stops listening."""
    global _listen
    was = _listen is not None
    if _session is not None:
        _drop(_session)
    if _listen is not None:
        _listen.close()
        _listen = None
    return was


def running():
    return _listen is not None


def client_address():
    """The connected client's (ip, port), or None."""
    if _session is not None and not _session.closed and not _session.eof:
        return _session.addr
    return None


def port():
    return _port
