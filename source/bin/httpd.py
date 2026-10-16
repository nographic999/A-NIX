"""httpd - web control panel: pin/LED=output, PWMn=pwm, INn=input,
ADCn=analog, plus a file browser. Runs on core 0 like telnetd: it
answers at once while the shell waits at its prompt (not while a
command runs), and core 1 stays free. `httpd status` says whether it
runs, `httpd stop` ends it.

The panel uses the shell's own pin state (the same objects `out`,
`in`, `pwm`, `adc` and `pins` use), set up here on core 0 before the
server starts: reserved pins are refused, a pin is released from any
other mode first (see /lib/gpio.py), outputs that are already set
keep their level and new ones start low. Inputs use the pull-down,
like `in` does by default. ADC accepts ADC0-2 or GPIO26-28.

A password is required: `-p <password>`, else HTTPD_PASS in
/etc/anix.conf. The browser then asks for a login - any user name,
that password. Plain HTTP, so the login is only base64, not
encrypted: it keeps out anyone who doesn't know it, not someone
capturing traffic on the same network.

The panel also has a file browser (Files link, or /files): the
whole filesystem from / - download, view, upload, new folder, rename,
delete. `conf HTTPD_FILES off` leaves it out. See /lib/webfiles.py.

A big download or upload holds the prompt for its few seconds; typed
keys wait meanwhile and are not lost.
"""

import shell
import net
import machine
import gpio

ADC_PINS = (26, 27, 28)


def _out_pin(key):
    if key != "LED" and not gpio.check(key):
        return None
    if shell._pin_modes.get(key) != "out":
        gpio.release(key, "pin")
        if key == "LED":
            p = shell._make_led_pin(machine.Pin.OUT)
            p.value(0)
        else:
            p = machine.Pin(key, machine.Pin.OUT, value=0)
        shell._pins[key] = p
        shell._pin_modes[key] = "out"
    return shell._pins[key]


def _in_pin(pin):
    if not gpio.check(pin):
        return None
    if not str(shell._pin_modes.get(pin, "")).startswith("in"):
        gpio.release(pin, "pin")
        shell._pins[pin] = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_DOWN)
        shell._pin_modes[pin] = "in-down"
    return shell._pins[pin]


def _adc(pin):
    if pin not in ADC_PINS:
        shell._err("ADC%d: ADC pins are 26, 27 and 28 (or ADC0-2)" % pin)
        return None
    if pin not in shell._adcs:
        gpio.release(pin, "adc")
        shell._adcs[pin] = machine.ADC(pin)
    return shell._adcs[pin]


def _pwm(pin):
    if not gpio.check(pin):
        return None
    if pin not in shell._pwms:
        gpio.release(pin, "pwm")
        p = machine.PWM(machine.Pin(pin))
        p.freq(1000)
        p.duty_u16(0)
        shell._pwms[pin] = p
    return shell._pwms[pin]


def run(args, cwd):
    if not net.available():
        shell._err(net.NO_WIFI)
        return
    import server

    if args and args[0].lower() == "status":
        if server.is_running():
            ip = net.local_ip()
            where = ("http://%s/" % shell._c(shell.MAGENTA, ip)) if ip else \
                "no WiFi yet - reachable once `wifi` connects"
            shell._out("httpd %s - %s" % (shell._c(shell.GREEN, "running"), where))
        else:
            shell._out("httpd is " + shell._c(shell.GREY, "not running"))
        last = server.last_note()
        if last and not last.startswith("listening"):
            shell._out("last: %s" % shell._c(shell.YELLOW, last))
        return
    if args and args[0].lower() == "stop":
        if server.stop():
            shell._out("web server stopped.")
        else:
            shell._out("no web server is currently running.")
        return

    if server.is_running():
        shell._out("web server already running. use: httpd stop")
        return

    plain = None
    if args and args[0] == "-p":
        if len(args) < 2:
            shell._err("usage: httpd -p <password> [pins...]")
            return
        plain, args = args[1], args[2:]
    password = plain or shell.ENV.get("HTTPD_PASS", "")
    if not password or password == "none":
        shell._err("a password is required: conf HTTPD_PASS <password>, or httpd -p <password> [pins...]")
        return

    if args:
        raw_args = args
    else:
        cfg = shell.ENV.get("WEB_PINS", "")
        if cfg.strip().lower() == "none":
            raw_args = []               # no pins: only the file browser
        else:
            raw_args = [p.strip() for p in cfg.split(",") if p.strip()] or ["LED"]

    for a in raw_args:                  # all valid? (nothing is set up yet)
        au = a.upper()
        n = au[3:] if au[:3] in ("ADC", "PWM") else (au[2:] if au[:2] == "IN" else None)
        if (n is not None and not n.isdigit()) or (n is None and shell._pin_key(a) is None):
            shell._err("unknown pin %s - use LED, a GPIO number, INn, PWMn or ADCn" % a)
            return

    pins, inputs, adcs, pwms = {}, {}, {}, {}
    for a in raw_args:
        au = a.upper()
        try:
            if au.startswith("ADC") and au[3:].isdigit():
                n = int(au[3:])
                gpio_num = 26 + n if n < 3 else n
                obj = _adc(gpio_num)
                if obj is not None:
                    adcs[str(gpio_num - 26)] = obj
            elif au.startswith("IN") and au[2:].isdigit():
                obj = _in_pin(int(au[2:]))
                if obj is not None:
                    inputs[au[2:]] = obj
            elif au.startswith("PWM") and au[3:].isdigit():
                obj = _pwm(int(au[3:]))
                if obj is not None:
                    pwms[au[3:]] = obj
            else:
                key = shell._pin_key(a)
                if key is None:
                    shell._err("unknown pin %s" % a)
                    continue
                obj = _out_pin(key)
                if obj is not None:
                    pins[str(key)] = obj
        except Exception as e:
            shell._err("could not set up %s" % a, e)

    files = shell.ENV.get("HTTPD_FILES", "on").lower() != "off"
    if not (pins or inputs or adcs or pwms or files):
        shell._err("no usable pins to serve")
        return

    parts_desc = []
    if pins:
        parts_desc.append("outputs: %s" % ", ".join(pins))
    if pwms:
        parts_desc.append("pwm: %s" % ", ".join("GPIO" + k for k in pwms))
    if inputs:
        parts_desc.append("inputs: %s" % ", ".join("GPIO" + k for k in inputs))
    if adcs:
        parts_desc.append("adc: %s" % ", ".join("ADC" + k for k in adcs))
    if files:
        parts_desc.append("files: / (full access)")
    shell._out(" | ".join(parts_desc))
    shell._out(net.status())

    try:
        started, reason = server.start([], prebuilt=(pins, inputs, adcs, pwms),
                                       password=password, files=files)
    except Exception as e:
        shell._err("web server failed", e)
        return
    if not started:
        shell._err(reason)
        return
    shell._out("web server started - it answers while the prompt waits. use: httpd stop")
    ip = net.local_ip()
    if ip:
        shell._out("open http://%s/ - login: any user name, your httpd password" % ip)
    else:
        shell._out("no WiFi yet - the panel is reachable once `wifi` connects")
