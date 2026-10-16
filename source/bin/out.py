"""out - drive a GPIO pin or the onboard LED. Pin state lives in
shell.py (shared with in/pins), not here - each /bin command execs
fresh, so a local variable here would be forgotten the instant this
command finishes; the shared dicts in shell.py are what let a pin
you set here still be readable by `in`/`pins` in a later command.

Reserved pins are refused, and a pin previously used as input, PWM
or ADC is released from that mode first (see /lib/gpio.py). A new
output is created already at the requested level, so it never
briefly shows its previous level.
"""

import shell
import machine
import gpio


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: out <pin>|LED <0|1>")
        return
    key = shell._pin_key(args[0])
    if key is None:
        shell._err("pin must be a number or LED")
        return
    if args[1] not in ("0", "1"):
        shell._err("value must be 0 or 1")
        return
    value = int(args[1])
    if key != "LED" and not gpio.check(key):
        return
    try:
        if shell._pin_modes.get(key) == "out":
            shell._pins[key].value(value)
        else:
            gpio.release(key, "pin")
            if key == "LED":
                p = shell._make_led_pin(machine.Pin.OUT)
                p.value(value)
            else:
                p = machine.Pin(key, machine.Pin.OUT, value=value)
            shell._pins[key] = p
            shell._pin_modes[key] = "out"
        label = "LED" if key == "LED" else "GPIO%d" % key
        shell._out("%s set %s" % (label, "high" if value else "low"))
    except Exception as e:
        shell._err("could not set pin %s" % key, e)
