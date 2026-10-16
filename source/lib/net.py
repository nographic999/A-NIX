"""net - small network toolkit for the WiFi boards (Pico W, Pico 2 W):
wifi connect/scan/status, a TCP-connect-timing ping (no raw ICMP on
MicroPython), and an HTTP/HTTPS GET. Imported by the wifi/scan/
ping/curl /bin commands, and checked by httpd.

On a board without WiFi (Pico, Pico 2) importing this still works:
available() returns False and every network function raises
OSError("no WiFi on this board"), so commands can print one clear
message instead of crashing on `import network`.

WIFI_COUNTRY in /etc/anix.conf (e.g. WIFI_COUNTRY=LT) sets the radio's
country before it is switched on. Without it the radio uses
worldwide settings and may not see networks on channels 12-13,
which are allowed in Europe.

Every socket is closed in a finally block - the board only has a
few, and leaking them on errors used to break all network commands
until a reboot.
"""

import time

try:
    import network
    import socket
except ImportError:
    network = None
    socket = None

NO_WIFI = "no WiFi on this board"

# wlan.status() codes - names exist on recent firmware, numbers are
# the cyw43 values as a fallback
_STAT_CONNECT_FAIL = getattr(network, "STAT_CONNECT_FAIL", -1) if network else -1
_STAT_NO_AP_FOUND = getattr(network, "STAT_NO_AP_FOUND", -2) if network else -2
_STAT_WRONG_PASSWORD = getattr(network, "STAT_WRONG_PASSWORD", -3) if network else -3

_wlan = None


def available():
    return network is not None


def _need_wifi():
    if network is None:
        raise OSError(NO_WIFI)


def _env(name, default=""):
    try:
        import shell
        return shell.ENV.get(name, default)
    except Exception:
        return default


def _set_country():
    code = _env("WIFI_COUNTRY", "").strip().upper()
    if not code or code == "NONE":
        return
    try:
        network.country(code)
    except Exception:
        try:
            import rp2
            rp2.country(code)
        except Exception:
            pass


def _get_wlan():
    """One station interface for the whole session. Switched (back)
    on whenever it is off - `wifi off` turns the radio off, and the
    next `wifi`/`scan` must work again without a reboot. The country
    is applied right before switching on, as the radio requires."""
    global _wlan
    _need_wifi()
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
    if not _wlan.active():
        _set_country()
        _wlan.active(True)
    return _wlan


def _current_ssid(wlan):
    for key in ("ssid", "essid"):
        try:
            return wlan.config(key)
        except Exception:
            pass
    return None


def connect(ssid, password, timeout=15):
    """Joins a network. Returns (True, ip) or (False, reason).

    Already connected to this same network: returns at once. Connected
    to a different one: disconnects first, then joins the new one.
    Fails fast on a wrong password / network not found / connection
    failure instead of waiting out the whole timeout, and cancels the
    attempt on timeout so the radio doesn't keep trying in the
    background."""
    wlan = _get_wlan()
    if wlan.isconnected():
        if _current_ssid(wlan) == ssid:
            return True, wlan.ifconfig()[0]
        wlan.disconnect()
        t0 = time.ticks_ms()
        while wlan.isconnected() and time.ticks_diff(time.ticks_ms(), t0) < 2000:
            time.sleep_ms(100)

    wlan.connect(ssid, password)
    t0 = time.ticks_ms()
    while True:
        if wlan.isconnected():
            return True, wlan.ifconfig()[0]
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        st = wlan.status()
        # the first second can still show the previous attempt's state
        if elapsed > 1000:
            reason = None
            if st == _STAT_WRONG_PASSWORD:
                reason = "wrong password for %s" % ssid
            elif st == _STAT_NO_AP_FOUND:
                reason = "network %s not found" % ssid
            elif st == _STAT_CONNECT_FAIL:
                reason = "connection to %s failed" % ssid
            if reason:
                wlan.disconnect()
                return False, reason
        if elapsed > timeout * 1000:
            wlan.disconnect()
            return False, "timed out connecting to %s" % ssid
        time.sleep_ms(250)


def disconnect():
    """Disconnects and switches the radio off. Does nothing if WiFi
    was never used this session."""
    _need_wifi()
    if _wlan is None:
        return
    try:
        _wlan.disconnect()
    except Exception:
        pass
    _wlan.active(False)


def status():
    """Always returns a string, never raises."""
    if network is None:
        return NO_WIFI
    if _wlan is None or not _wlan.active():
        return "WiFi off"
    if not _wlan.isconnected():
        return "Not connected"
    ip, subnet, gateway, dns = _wlan.ifconfig()
    text = "Connected"
    ssid = _current_ssid(_wlan)
    if ssid:
        text += " to %s" % ssid
    text += " - IP %s  Gateway %s  DNS %s" % (ip, gateway, dns)
    try:
        text += "  Signal %d dBm" % _wlan.status("rssi")
    except Exception:
        pass
    return text


def scan():
    """Returns a list of (ssid, rssi, channel, secured) - one entry per
    network name, keeping its strongest access point (a router with
    several APs or bands otherwise shows up several times). Hidden
    networks are merged into one "" entry. Sorted strongest first."""
    wlan = _get_wlan()
    best = {}
    for n in wlan.scan():
        ssid = n[0]
        if isinstance(ssid, bytes):
            ssid = ssid.decode("utf-8", "replace")
        channel, rssi, security = n[2], n[3], n[4]
        if ssid not in best or rssi > best[ssid][1]:
            best[ssid] = (ssid, rssi, channel, security != 0)
    return sorted(best.values(), key=lambda r: -r[1])


def resolve(host, port):
    """(address, ms) - DNS lookup on its own, so ping can time it
    separately from the connections."""
    _need_wifi()
    t0 = time.ticks_ms()
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    return addr, time.ticks_diff(time.ticks_ms(), t0)


def tcp_ping(addr, count=4, timeout=2):
    """Times a TCP connect to an already-resolved address `count`
    times. Returns a list: round-trip ms (int) on success, or the
    error text (str) on failure."""
    _need_wifi()
    results = []
    for _ in range(count):
        s = None
        t0 = time.ticks_ms()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(addr)
            results.append(time.ticks_diff(time.ticks_ms(), t0))
        except Exception as e:
            results.append(str(e) or e.__class__.__name__)
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        time.sleep_ms(200)
    return results


def _parse_url(url):
    if url.startswith("https://"):
        tls, rest, port = True, url[8:], 443
    elif url.startswith("http://"):
        tls, rest, port = False, url[7:], 80
    else:
        raise ValueError("URL must start with http:// or https://")
    cut = len(rest)
    for ch in "/?#":
        k = rest.find(ch)
        if k != -1 and k < cut:
            cut = k
    host, path = rest[:cut], rest[cut:]
    if "#" in path:
        path = path.split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path               # http://h?x=1 -> /?x=1
    path = path.replace(" ", "%20")
    if ":" in host:
        host, port_s = host.split(":", 1)
        if port_s:
            try:
                port = int(port_s)
            except ValueError:
                raise ValueError("bad port in URL: %s" % port_s)
    if not host:
        raise ValueError("no host in URL")
    return tls, host, port, path


def _wrap_tls(s, host):
    """TLS without certificate checking - the Pico has no CA store, so
    this encrypts the connection but does not prove who the server
    is. Fine for fetching data, not for anything secret."""
    try:
        import ssl
    except ImportError:
        import ussl as ssl
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE
        return ctx.wrap_socket(s, server_hostname=host)
    except AttributeError:
        return ssl.wrap_socket(s, server_hostname=host)


def _request(url, timeout=10):
    """Sends an HTTP/1.0 GET (http:// or https://) and reads the
    response headers. Returns (sock, code, reason, headers, rest):
    sock is still open (the caller reads the body from it and must
    close it), headers is a dict with lowercase names, rest is the
    part of the body that arrived together with the headers."""
    _need_wifi()
    tls, host, port, path = _parse_url(url)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(addr)
        if tls:
            s = _wrap_tls(s, host)
        req = "GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: A-NIX\r\nConnection: close\r\n\r\n" % (path, host)
        s.write(req.encode())
        data = b""
        while b"\r\n\r\n" not in data and b"\n\n" not in data:
            chunk = s.read(256)
            if not chunk:
                break
            data += chunk
            if len(data) > 8192:
                raise OSError("response headers too long")
    except BaseException:
        try:
            s.close()
        except Exception:
            pass
        raise
    k1 = data.find(b"\r\n\r\n")
    k2 = data.find(b"\n\n")
    if k1 != -1 and (k2 == -1 or k1 < k2):
        head, rest = data[:k1], data[k1 + 4:]
    elif k2 != -1:
        head, rest = data[:k2], data[k2 + 2:]       # LF-only server
    else:
        head, rest = data, b""
    lines = [ln.rstrip("\r") for ln in head.decode("utf-8", "replace").split("\n")]
    status_parts = lines[0].split(" ", 2)
    try:
        code = int(status_parts[1])
    except (IndexError, ValueError):
        code = 0
    reason = status_parts[2] if len(status_parts) > 2 else ""
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return s, code, reason, headers, rest


class _Body:
    """The response body as a stream: plain, or chunked transfer
    encoding decoded (some servers answer HTTP/1.1 chunked even to a
    1.0 request). read(n) returns b"" at the end."""

    def __init__(self, s, first, chunked):
        self.s = s
        self.buf = first
        self.chunked = chunked
        self.left = 0                   # bytes left in the current chunk
        self.done = False

    def _fill(self, n):
        while len(self.buf) < n:
            more = self.s.read(512)
            if not more:
                return False
            self.buf += more
        return True

    def _line(self):
        while b"\n" not in self.buf:
            more = self.s.read(512)
            if not more:
                raise OSError("connection closed inside chunked data")
            self.buf += more
        line, self.buf = self.buf.split(b"\n", 1)
        return line.strip()

    def read(self, n=512):
        if not self.chunked:
            if self.buf:
                out, self.buf = self.buf[:n], self.buf[n:]
                return out
            return self.s.read(n)
        if self.done:
            return b""
        if self.left == 0:
            size = self._line().split(b";", 1)[0]
            try:
                self.left = int(size, 16)
            except ValueError:
                raise OSError("bad chunked data")
            if self.left == 0:
                self.done = True
                return b""
        if not self.buf:
            self._fill(1)
        out = self.buf[:min(n, self.left)]
        if not out:
            raise OSError("connection closed inside chunked data")
        self.buf = self.buf[len(out):]
        self.left -= len(out)
        if self.left == 0:
            self._line()                # the CR LF after each chunk
        return out


def resolve_location(url, location):
    """Absolute URL for a redirect's Location header (which may be
    relative to the current URL)."""
    if location.startswith("http://") or location.startswith("https://"):
        return location
    tls, host, port, path = _parse_url(url)
    scheme = "https:" if tls else "http:"
    if location.startswith("//"):
        return scheme + location        # same scheme, other host
    base = scheme + "//" + host
    if (tls and port != 443) or (not tls and port != 80):
        base += ":%d" % port
    if location.startswith("/"):
        return base + location
    path = path.split("?", 1)[0]
    if location.startswith("?"):
        return base + path + location
    return base + path.rsplit("/", 1)[0] + "/" + location


def http_get(url, timeout=10, max_bytes=8192):
    """HTTP/1.0 GET, http:// or https://. Returns
    (status_code, reason, headers, body, truncated) - headers is a
    dict with lowercase names, body is text without the headers,
    truncated is True if the body was longer than max_bytes (only
    max_bytes are kept, to protect RAM - use `wget` to save bigger
    files). HTTP/1.0 with "Connection: close" means the server closes
    the connection at the end, so no Content-Length/chunked parsing
    is needed. https needs roughly 30-40 KB of free RAM."""
    s, code, reason, headers, first = _request(url, timeout)
    body = _Body(s, first, "chunked" in headers.get("transfer-encoding", "").lower())
    truncated = False
    data = b""
    try:
        while not truncated:
            chunk = body.read(512)
            if not chunk:
                break
            if len(data) + len(chunk) > max_bytes:
                data += chunk[:max_bytes - len(data)]
                truncated = True
                break
            data += chunk
    finally:
        try:
            s.close()
        except Exception:
            pass
    return code, reason, headers, data.decode("utf-8", "replace"), truncated


def download(url, path, progress=None, timeout=10, max_redirects=5):
    """Saves url to path, streaming 512 bytes at a time - file size is
    limited by free flash, not RAM. Follows up to max_redirects
    redirects. Writes path + ".tmp" first and renames it at the end,
    so a failed or interrupted download never leaves a half file
    (the .tmp is removed). Checks free space first when the server
    says the size. progress(done, total_or_None) is called about
    every 4 KB. Returns (bytes, final_url); raises OSError with a
    readable message on any failure."""
    import os
    for _ in range(max_redirects + 1):
        s, code, reason, headers, data = _request(url, timeout)
        if code in (301, 302, 303, 307, 308) and "location" in headers:
            s.close()
            url = resolve_location(url, headers["location"])
            continue
        break
    else:
        raise OSError("too many redirects")
    if code != 200:
        s.close()
        raise OSError("server answered %d %s" % (code, reason))

    total = None
    try:
        total = int(headers.get("content-length", ""))
    except ValueError:
        pass
    if total is not None:
        folder = path.rsplit("/", 1)[0] or "/"
        try:
            st = os.statvfs(folder)
            free = st[0] * st[3]
            if total > free - 4096:
                s.close()
                raise OSError("not enough flash space (%d KB needed, %d KB free)" %
                              (total // 1024, free // 1024))
        except OSError as e:
            if "flash" in str(e):
                raise

    tmp = path + ".tmp"
    done = 0
    ok = False
    body = _Body(s, data, "chunked" in headers.get("transfer-encoding", "").lower())
    try:
        with open(tmp, "wb") as f:
            next_report = 4096
            while True:
                chunk = body.read(512)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress is not None and done >= next_report:
                    progress(done, total)
                    next_report = done + 4096
        if total is not None and done < total:
            raise OSError("connection closed early (%d of %d bytes)" % (done, total))
        try:
            os.rename(tmp, path)
        except OSError:
            os.remove(path)
            os.rename(tmp, path)
        ok = True
    finally:
        try:
            s.close()
        except Exception:
            pass
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return done, url


def ntp_time(host="pool.ntp.org", timeout=5):
    """Current UTC time from an NTP server, as epoch seconds (since
    1970). One plain SNTP request over UDP port 123."""
    _need_wifi()
    import struct
    addr = socket.getaddrinfo(host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        packet = bytearray(48)
        packet[0] = 0x1B            # client request, NTP version 3
        s.sendto(packet, addr)
        msg = s.recv(48)
    finally:
        s.close()
    if len(msg) < 48:
        raise OSError("bad answer from %s" % host)
    seconds = struct.unpack("!I", msg[40:44])[0]
    if seconds == 0:
        raise OSError("no time from %s" % host)
    return seconds - 2208988800     # NTP counts from 1900


def local_ip():
    """The board's own IP on the WiFi network it joined (or an access
    point set up by your own program), else None."""
    if network is None:
        return None
    for iface in (network.STA_IF, network.AP_IF):
        try:
            w = network.WLAN(iface)
            if w.active() and w.ifconfig()[0] != "0.0.0.0":
                return w.ifconfig()[0]
        except Exception:
            pass
    return None
