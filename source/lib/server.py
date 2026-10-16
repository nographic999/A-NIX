"""server - tiny HTTP control panel: ON/OFF for output pins, a
duty-cycle Set for PWM, read-only rows for inputs/ADCs, and a file
browser for the whole filesystem (/files, see webfiles.py). Runs on
core 0 like telnetd: the prompt watches the server socket and answers
a browser at once while it waits for keys - not while a command runs.
Core 1 stays free, and the panel never uses files or pins at the same
moment as the shell. Imported by the httpd /bin command - see
`man httpd` for usage.
"""

import socket

try:
    import machine
except ImportError:
    machine = None

try:
    import _thread
except ImportError:
    _thread = None

_lock = _thread.allocate_lock() if _thread else None
_state = {"running": False, "stop": False, "loud": False, "last": ""}


def _note(msg):
    """A message from the server. Started by httpd it is only kept for
    `httpd status` - printing it would land in the middle of whatever is
    being typed at the prompt. The blocking run() prints it as well."""
    _set_state(last=msg)
    if _get_state("loud"):
        print(msg)


def last_note():
    return _get_state("last")


def _set_state(**kw):
    """The server's state goes through _state, guarded by _lock - the
    blocking run() can be stopped from another thread, and two cores
    touching a plain dict at the same instant is a real race on this
    hardware."""
    if _lock:
        _lock.acquire()
    try:
        _state.update(kw)
    finally:
        if _lock:
            _lock.release()


def _get_state(key):
    if _lock:
        _lock.acquire()
    try:
        return _state[key]
    finally:
        if _lock:
            _lock.release()


def is_running():
    return _get_state("running")


def stop():
    """Stops the server at once. Returns False if none was running."""
    c = _ctx.pop("c", None)
    if c is None:
        if not is_running():
            return False
        _set_state(stop=True)           # the blocking run(): ends within a second
        return True
    try:
        import lineedit
        lineedit.unwatch(c["s"])
    except ImportError:
        pass
    try:
        c["s"].close()
    except Exception:
        pass
    _release(c)
    _set_state(running=False, stop=False)
    _note("stopped")
    return True


def _resolve_out_pin(key):
    """key is always a string here (it comes from httpd.py's parsed
    command-line args, or a URL query param) - "LED" or a GPIO
    number as text, same convention as shell._pin_key elsewhere in
    this project, just duplicated locally since this module doesn't
    import shell (it's meant to be usable standalone)."""
    if key == "LED":
        try:
            return machine.Pin("LED", machine.Pin.OUT)
        except (TypeError, ValueError):
            return machine.Pin(25, machine.Pin.OUT)
    return machine.Pin(int(key), machine.Pin.OUT)


def _resolve_in_pin(key):
    return machine.Pin(int(key), machine.Pin.IN, machine.Pin.PULL_DOWN)


def _label(key):
    return "LED" if key == "LED" else "GPIO%s" % key


def _pin_lock():
    try:
        import shell
        return shell._pin_lock
    except Exception:
        return None


def _authorized(request_text, password):
    """HTTP Basic auth check - the browser shows its own login box
    and then sends "Authorization: Basic <base64 of user:password>"
    with every request. Any user name is accepted; only the password
    is checked. password=None means no login (standalone run())."""
    if password is None:
        return True
    for line in request_text.split("\r\n")[1:]:
        if not line:
            break
        if line.lower().startswith("authorization:"):
            value = line.split(":", 1)[1].strip()
            if not value.lower().startswith("basic "):
                return False
            try:
                import binascii
                decoded = binascii.a2b_base64(value[6:].strip()).decode()
            except Exception:
                return False
            typed = decoded.split(":", 1)[-1]
            return password(typed) if callable(password) else typed == password
    return False


_UNAUTHORIZED = ("HTTP/1.0 401 Unauthorized\r\n"
                 "WWW-Authenticate: Basic realm=\"A-NIX\"\r\n"
                 "Content-Type: text/plain\r\nConnection: close\r\n\r\n"
                 "login required\n")


def _read_request(cl):
    """Reads until the end of the headers (the Authorization header
    can push a request past one 1024-byte recv). Returns the headers
    as text and the bytes of the body read with them (an upload)."""
    data = cl.recv(1024)
    while b"\r\n\r\n" not in data and len(data) < 4096:
        more = cl.recv(1024)
        if not more:
            break
        data += more
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        return None, b""                # headers too big or cut off
    return head.decode("utf-8", "replace"), rest


_FILE_ROUTES = ("/files", "/get", "/up", "/mkdir", "/ren", "/del")
_CHANGING = ("/up", "/mkdir", "/ren", "/del", "/on", "/off", "/pwmset")


def _header(request_text, name):
    name = name.lower() + ":"
    for line in request_text.split("\r\n")[1:]:
        if line.lower().startswith(name):
            return line.split(":", 1)[1].strip()
    return None


def _same_origin(request_text):
    """For requests that change something: they must come from this
    panel's own pages. The browser resends the saved login to any site
    that links here, so without this a web page elsewhere could switch
    pins or delete files (CSRF). Origin, else Referer, must name this
    board; a request with neither (typed into the address bar) is
    refused too."""
    host = _header(request_text, "Host")
    src = _header(request_text, "Origin") or _header(request_text, "Referer")
    if not host or not src:
        return False
    src = src.split("://", 1)[-1].split("/", 1)[0]
    return src == host


def _send_all(cl, data):
    while data:
        n = cl.write(data)
        data = data[n or 0:]


def parse_request(request_text):
    """Pulls the route and query params out of a raw HTTP request's
    first line, e.g. "GET /on?pin=16 HTTP/1.1" -> ("/on", {"pin": "16"}).
    Split out from the socket loop so it can be tested without a
    real socket."""
    first_line = request_text.split("\r\n", 1)[0]
    parts = first_line.split(" ")
    path = parts[1] if len(parts) > 1 else "/"
    if "?" in path:
        route, query = path.split("?", 1)
    else:
        route, query = path, ""
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[k] = v
    return route, params


def render_page(pins, inputs=None, adcs=None, pwms=None, files=False):
    """Builds the whole page fresh on every request - no templates,
    just string concatenation, and no client-side state at all
    (every ON/OFF/duty value shown is read live from the actual pin
    objects each time, so the page can never show a stale value)."""
    inputs = inputs or {}
    adcs = adcs or {}
    pwms = pwms or {}

    out_rows = ""
    for key, pin in pins.items():
        try:
            state = pin.value()
        except Exception:
            state = None
        status = "ON" if state == 1 else "OFF"
        out_rows += (
            "<tr><td>%s</td><td><b>%s</b></td><td>"
            '<a href="/on?pin=%s"><button>ON</button></a> '
            '<a href="/off?pin=%s"><button>OFF</button></a>'
            "</td></tr>\n" % (_label(key), status, key, key)
        )

    in_rows = ""
    for key, pin in inputs.items():
        try:
            state = pin.value()
            status = "HIGH" if state == 1 else "LOW"
        except Exception as e:
            status = "error - %s" % e
        in_rows += "<tr><td>GPIO%s</td><td><b>%s</b></td></tr>\n" % (key, status)

    adc_rows = ""
    for key, adc in adcs.items():
        try:
            raw = adc.read_u16()
            volts = raw / 65535 * 3.3
            adc_rows += "<tr><td>ADC%s</td><td>%d</td><td>%.3f V</td></tr>\n" % (key, raw, volts)
        except Exception as e:
            adc_rows += "<tr><td>ADC%s</td><td colspan='2'>error - %s</td></tr>\n" % (key, e)

    pwm_rows = ""
    for key, p in pwms.items():
        try:
            pct = round(p.duty_u16() / 65535 * 100)
        except Exception:
            pct = 0
        pwm_rows += (
            "<tr><td>GPIO%s</td><td>%d%%</td><td>"
            '<form method="GET" action="/pwmset" style="display:inline">'
            '<input type="hidden" name="pin" value="%s">'
            '<input type="number" name="duty" min="0" max="100" value="%d" style="width:4em">'
            "<button type=\"submit\">Set</button>"
            "</form></td></tr>\n" % (key, pct, key, pct)
        )

    sections = ""
    if pins:
        sections += (
            "<h2>Digital outputs</h2>"
            "<table border='1' cellpadding='8'>"
            "<tr><th>Pin</th><th>State</th><th>Action</th></tr>"
            + out_rows + "</table>"
        )
    if pwms:
        sections += (
            "<h2>PWM outputs</h2>"
            "<table border='1' cellpadding='8'>"
            "<tr><th>Pin</th><th>Duty</th><th>Set (0-100)</th></tr>"
            + pwm_rows + "</table>"
        )
    if inputs:
        sections += (
            "<h2>Digital inputs</h2>"
            "<table border='1' cellpadding='8'>"
            "<tr><th>Pin</th><th>State</th></tr>"
            + in_rows + "</table>"
        )
    if adcs:
        sections += (
            "<h2>Analog inputs</h2>"
            "<table border='1' cellpadding='8'>"
            "<tr><th>Pin</th><th>Raw</th><th>Voltage</th></tr>"
            + adc_rows + "</table>"
        )

    # Inputs/ADCs change on their own with no JS to push updates, so
    # auto-refresh the whole page while any of those are present.
    # PWM outputs only change when the user submits the form, so they
    # don't need to trigger this on their own.
    refresh_tag = "<meta http-equiv='refresh' content='2'>" if (inputs or adcs) else ""

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>" + refresh_tag +
        "<title>A-NIX Pin Control</title></head><body>"
        "<h1>A-NIX Pin Control</h1>"
        + ("<p><a href='/files?p=/'>&#128193; Files</a></p>" if files else "")
        + sections +
        "</body></html>"
    )


def handle(pins, inputs, adcs, pwms, request_text, files=False):
    """Applies any ON/OFF action from the request (outputs only -
    inputs and ADCs are read-only and never acted on), or a PWM
    duty-cycle change, then returns the HTML for the current state
    of everything. Kept separate from the socket loop for
    testability."""
    route, params = parse_request(request_text)
    key = params.get("pin")
    if key is not None and key in pins:
        if route == "/on":
            pins[key].value(1)
        elif route == "/off":
            pins[key].value(0)
    if route == "/pwmset" and key is not None and key in pwms:
        try:
            duty_pct = int(params.get("duty", "0"))
        except ValueError:
            duty_pct = 0
        duty_pct = max(0, min(100, duty_pct))
        pwms[key].duty_u16(int(duty_pct / 100 * 65535))
    return render_page(pins, inputs, adcs, pwms, files)


def _setup(pin_keys, in_keys, adc_keys, pwm_keys):
    """Standalone pin setup from key lists (used by run(), or start()
    without prebuilt objects) - skips any pin that fails rather than
    aborting the whole server over one bad pin number."""
    pins = {}
    for k in pin_keys:
        try:
            pins[k] = _resolve_out_pin(k)
        except Exception as e:
            print("Could not set up output pin %s - %s" % (k, e))

    inputs = {}
    for k in (in_keys or []):
        try:
            inputs[k] = _resolve_in_pin(k)
        except Exception as e:
            print("Could not set up input pin %s - %s" % (k, e))

    adcs = {}
    for k in (adc_keys or []):
        try:
            adcs[k] = machine.ADC(int(k))
        except Exception as e:
            print("Could not set up ADC%s - %s" % (k, e))

    pwms = {}
    for k in (pwm_keys or []):
        try:
            p = machine.PWM(machine.Pin(int(k)))
            p.freq(1000)
            p.duty_u16(0)
            pwms[k] = p
        except Exception as e:
            print("Could not set up PWM pin %s - %s" % (k, e))
    return pins, inputs, adcs, pwms


_ctx = {}       # the running server: its socket and what it serves


def _open(port):
    addr = socket.getaddrinfo("0.0.0.0", port)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    return s


def _release(c):
    """Only PWMs this module created itself - pins handed in by httpd
    belong to the shell and stay as they are."""
    if c["owned"]:
        for p in c["pwms"].values():
            try:
                p.deinit()
            except Exception:
                pass


def _handle(cl, c):
    """Answers one request on client socket cl (c = the server's
    settings). With a password, every request without the right login
    gets 401 and nothing is switched. Errors only end this request."""
    pins, inputs, adcs, pwms = c["pins"], c["inputs"], c["adcs"], c["pwms"]
    password, files = c["password"], c["files"]
    try:
        cl.settimeout(5)
        request_text, rest = _read_request(cl)
        if request_text is None:
            _send_all(cl, b"HTTP/1.0 431 Request Header Fields Too Large\r\n"
                          b"Connection: close\r\n\r\n")
            return
        if not _authorized(request_text, password):
            _send_all(cl, _UNAUTHORIZED.encode())
            return
        route, params = parse_request(request_text)
        if route in _CHANGING and not _same_origin(request_text):
            _send_all(cl, b"HTTP/1.0 403 Forbidden\r\nContent-Type: text/plain\r\n"
                          b"Connection: close\r\n\r\nuse the buttons on the panel\n")
            return
        if files and route == "/" and not (pins or inputs or adcs or pwms):
            route, params = "/files", {"p": "/"}   # files only: open them
        if files and route in _FILE_ROUTES:
            import webfiles
            webfiles.pins_link = bool(pins or inputs or adcs or pwms)
            webfiles.handle(cl, route, params, request_text, rest)
            return
        # the shell's pin commands hold the same lock, so a click
        # here and `out`/`pwm` in the shell never collide
        lock = _pin_lock()
        if lock is not None:
            lock.acquire()
        try:
            html = handle(pins, inputs, adcs, pwms, request_text, files)
        finally:
            if lock is not None:
                lock.release()
        response = ("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n"
                    "Connection: close\r\n\r\n" + html)
        _send_all(cl, response.encode())
    except Exception as e:
        _note("request error - %s" % e)
    finally:
        cl.close()


def poll():
    """Answers the browsers that are waiting. Called on core 0 by the
    prompt (lineedit watches the server socket), like telnetd - so the
    web panel and the shell never use files or pins at the same time,
    and core 1 stays free for your own programs."""
    c = _ctx.get("c")
    if c is None:
        return
    for _ in range(4):                  # a page and its favicon request
        try:
            cl, _addr = c["s"].accept()
        except OSError:
            return                      # nobody waiting
        _handle(cl, c)


def start(pin_keys, in_keys=None, adc_keys=None, pwm_keys=None, port=80,
          prebuilt=None, password=None, files=False):
    """Starts the server on core 0: it answers whenever the shell waits
    at its prompt (not while a command runs). prebuilt, if given, is a
    ready (pins, inputs, adcs, pwms) tuple of dicts keyed by the
    strings used in URLs - httpd passes the shell's own pin objects
    this way, so the panel and the shell's out/in/pwm/adc/pins
    commands always agree on every pin's mode and value. password, if
    given, makes the browser ask for a login (any user name, this
    password) before showing or switching anything.

    Returns (True, "") if started, or (False, reason)."""
    if is_running():
        return False, "already running - use: httpd stop"
    if prebuilt is not None:
        pins, inputs, adcs, pwms = prebuilt
        owned = False
    else:
        pins, inputs, adcs, pwms = _setup(pin_keys, in_keys, adc_keys, pwm_keys)
        owned = True
    c = {"pins": pins, "inputs": inputs, "adcs": adcs, "pwms": pwms, "owned": owned,
         "password": password, "files": files, "s": None}
    if not pins and not inputs and not adcs and not pwms and not files:
        return False, "no usable pins/inputs/ADCs/PWM to serve - nothing to do"
    try:
        c["s"] = _open(port)
        c["s"].settimeout(0)            # accept() never waits
    except Exception as e:
        _release(c)
        return False, "could not start - %s" % e
    _ctx["c"] = c
    _set_state(running=True, stop=False, loud=False, last="")
    try:
        import lineedit
        lineedit.watch(c["s"], poll)    # answered while the prompt waits
    except ImportError:
        pass                            # without the shell: call poll() yourself
    _note("listening on port %d" % port)
    return True, ""


def run(pin_keys, in_keys=None, adc_keys=None, pwm_keys=None, port=80, password=None):
    """Blocking version, without the shell - answers requests until
    stop() is called (e.g. from a timer) or Ctrl-C. Prefer start()."""
    pins, inputs, adcs, pwms = _setup(pin_keys, in_keys, adc_keys, pwm_keys)
    c = {"pins": pins, "inputs": inputs, "adcs": adcs, "pwms": pwms, "owned": True,
         "password": password, "files": False, "s": None}
    _set_state(running=True, stop=False, loud=True, last="")
    try:
        if not pins and not inputs and not adcs and not pwms:
            _note("no usable pins/inputs/ADCs/PWM to serve - nothing to do")
            return
        try:
            s = _open(port)
        except Exception as e:
            _note("could not start - %s" % e)
            return
        s.settimeout(1)                 # wakes up once a second for stop()
        _note("listening on port %d" % port)
        try:
            while not _get_state("stop"):
                try:
                    cl, _addr = s.accept()
                except OSError:
                    continue
                _handle(cl, c)
        finally:
            s.close()
    finally:
        _release(c)
        _set_state(running=False, stop=False)
        _note("stopped")
