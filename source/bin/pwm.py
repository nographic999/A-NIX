"""pwm - drive a PWM output (default 1000Hz). Stays in PWM mode until
"pwm <pin> off" - it's a separate peripheral, not a digital mode.

"off" stops the PWM and sets the pin back to a pulled-down input,
so it can't stay stuck at its last level. Reserved pins are refused,
and a pin previously used as output, input or ADC is released from
that mode first (see /lib/gpio.py).

Pins come in pairs that share one PWM slice (GPIO0+1, 2+3, ... -
slice = (pin >> 1) & 7 on every Pico board): both pins of a pair
always run at the SAME frequency, setting one changes the other.
Duty is independent per pin.
"""

import shell
import machine
import gpio


def _slice(pin):
    return (pin >> 1) & 7


def run(args, cwd):
    if len(args) < 2:
        shell._out("usage: pwm <pin> <duty0-100>|off [freq_hz]")
        return
    try:
        pin_num = int(args[0])
    except ValueError:
        shell._err("pin must be a number")
        return
    if not gpio.check(pin_num):
        return

    if args[1].lower() == "off":
        if pin_num in shell._pwms:
            gpio.release(pin_num, None)
            shell._out("GPIO%d PWM stopped" % pin_num)
        else:
            shell._out("GPIO%d is not running PWM" % pin_num)
        return

    try:
        duty_pct = float(args[1])
    except ValueError:
        shell._err("duty must be a number 0-100, or 'off'")
        return
    duty_pct = max(0.0, min(100.0, duty_pct))

    freq_hz = 1000
    if len(args) > 2:
        try:
            freq_hz = int(args[2])
        except ValueError:
            shell._err("frequency must be a whole number of Hz")
            return

    try:
        p = shell._pwms.get(pin_num)
        if p is None:
            gpio.release(pin_num, "pwm")
            p = machine.PWM(machine.Pin(pin_num))
            shell._pwms[pin_num] = p
        p.freq(freq_hz)
        p.duty_u16(int(duty_pct / 100 * 65535))
        shell._out("GPIO%d PWM: %s%% duty @ %d Hz" % (pin_num, "%g" % duty_pct, freq_hz))
        for other in shell._pwms:
            if other != pin_num and _slice(other) == _slice(pin_num):
                shell._out("note: GPIO%d shares this PWM slice - it now also runs at %d Hz" %
                            (other, freq_hz))
    except Exception as e:
        shell._err("could not set PWM on pin %d" % pin_num, e)
