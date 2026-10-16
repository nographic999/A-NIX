"""in - read a GPIO pin or the onboard LED as input. Not importable
by name ("in" is a Python keyword) - the shell always runs it via
exec, never "import in", so that's fine.

  in <pin> [up|down|none]                 read it now
  in -w <pin> [up|down|none] [rise|fall|any] [-t seconds]
                                          wait until it changes

The optional pull picks the internal resistor: down (the default -
an unconnected pin reads 0), up (an unconnected pin reads 1 - use
this for a switch or button wired to GND), or none (for a pin
already driven by something external, e.g. a sensor output).
Reserved pins are refused, and a pin previously used as output, PWM
or ADC is released from that mode first (see /lib/gpio.py).

-w waits for a change, using the pin's interrupt (no busy polling):
rise = 0->1, fall = 1->0, any (default). A button wired to GND with
`up` gives fall when pressed. The change must stay for 20 ms
(debounce), so switch bounce doesn't count. -t gives up after that
many seconds ($? = 1). Ctrl-C stops waiting. While waiting, the web
panel and other pin commands are not held up.

The value also goes into $IN<pin> so scripts can do:
if $IN14==1 then ... fi
"""

import time
import shell
import machine
import gpio

_PULLS = {"down": "in-down", "up": "in-up", "none": "in"}


def _setup(key, pull):
    mode = "in" if key == "LED" else _PULLS[pull]
    if shell._pin_modes.get(key) != mode:
        gpio.release(key, "pin")
        if key == "LED":
            shell._pins[key] = shell._make_led_pin(machine.Pin.IN)
        elif pull == "up":
            shell._pins[key] = machine.Pin(key, machine.Pin.IN, machine.Pin.PULL_UP)
        elif pull == "down":
            shell._pins[key] = machine.Pin(key, machine.Pin.IN, machine.Pin.PULL_DOWN)
        else:
            shell._pins[key] = machine.Pin(key, machine.Pin.IN)
        shell._pin_modes[key] = mode
    return shell._pins[key]


def _wait(pin, edge, timeout_s):
    """Returns the new value after a debounced change, or None on
    timeout."""
    flag = [False]

    def irq(_p):
        flag[0] = True

    trig = {"rise": machine.Pin.IRQ_RISING, "fall": machine.Pin.IRQ_FALLING,
            "any": machine.Pin.IRQ_RISING | machine.Pin.IRQ_FALLING}[edge]
    want = {"rise": 1, "fall": 0, "any": None}[edge]
    start_val = pin.value()
    end = None if timeout_s is None else time.ticks_add(time.ticks_ms(), int(timeout_s * 1000))
    pin.irq(handler=irq, trigger=trig)
    lock = shell._pin_lock
    me = shell._current_thread_ident()
    if lock is not None and shell._pin_holder[0] == me:
        shell._pin_holder[0] = None
        lock.release()          # don't hold up httpd / other pin commands
    else:
        lock = None
    try:
        while True:
            if flag[0]:
                flag[0] = False
                time.sleep_ms(20)               # debounce
                v = pin.value()
                if (want is None and v != start_val) or (want is not None and v == want):
                    return v
                start_val = v
            if end is not None and time.ticks_diff(end, time.ticks_ms()) <= 0:
                return None
            shell.alive()               # waiting on purpose: not "stuck"
            time.sleep_ms(5)
    finally:
        if lock is not None:
            lock.acquire()
            shell._pin_holder[0] = me
        pin.irq(handler=None)


def run(args, cwd):
    wait = "-w" in args
    args = [a for a in args if a != "-w"]
    timeout_s = None
    if "-t" in args:
        k = args.index("-t")
        try:
            timeout_s = float(args[k + 1])
        except (IndexError, ValueError):
            timeout_s = -1.0
        if not 0 <= timeout_s <= 86400:
            shell._err("-t needs seconds, 0 to 86400")
            return
        args = args[:k] + args[k + 2:]
    if not args:
        shell._out("usage: in <pin>|LED [up|down|none]")
        shell._out("       in -w <pin> [up|down|none] [rise|fall|any] [-t seconds]")
        return
    key = shell._pin_key(args[0])
    if key is None:
        shell._err("pin must be a number or LED")
        return
    pull = "down"
    edge = "any"
    for a in args[1:]:
        a = a.lower()
        if a in _PULLS:
            pull = a
        elif a in ("rise", "fall", "any"):
            edge = a
        else:
            shell._err("unknown option %s - pulls: up down none, edges: rise fall any" % a)
            return
    if key != "LED" and not gpio.check(key):
        return
    if wait and key == "LED":
        shell._err("-w needs a GPIO number")
        return
    label = "LED" if key == "LED" else "GPIO%d" % key
    try:
        pin = _setup(key, pull)
        if wait:
            val = _wait(pin, edge, timeout_s)
            if val is None:
                shell._out("%s: no change within %gs" % (label, timeout_s))
                shell._set_status(1)
                return
        else:
            val = pin.value()
        shell._out("%s = %d" % (label, val))
        shell.ENV["IN%s" % key] = str(val)
    except Exception as e:
        shell._err("could not read pin %s" % key, e)
