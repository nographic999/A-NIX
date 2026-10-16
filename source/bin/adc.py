"""adc - read an analog input on GPIO26-28 (ADC0-2), the analog pins
available on every Pico board. GPIO29 (ADC3) is not offered: on the
W boards it is the wireless chip's clock pin, on the others it
measures VSYS. For the chip's own temperature sensor use `temp`.

Only GPIO numbers are accepted (not ADC channel numbers 0-3), so
`adc 0` can't silently mean GPIO26. A pin previously used as
output, input or PWM is released from that mode first (see
/lib/gpio.py).

ADC objects are cached per-pin in shell._adcs (shared state, same
reasoning as pins.py) purely so repeated reads on the same pin
don't keep re-initializing the peripheral.
"""

import shell
import machine
import gpio

ADC_PINS = (26, 27, 28)


def run(args, cwd):
    if not args:
        shell._out("usage: adc <pin>  (26, 27 or 28)")
        return
    try:
        pin_num = int(args[0])
    except ValueError:
        shell._err("pin must be a number")
        return
    if pin_num not in ADC_PINS:
        shell._err("ADC pins are 26, 27 and 28")
        return
    try:
        a = shell._adcs.get(pin_num)
        if a is None:
            gpio.release(pin_num, "adc")
            a = machine.ADC(pin_num)
            shell._adcs[pin_num] = a
        raw = a.read_u16()                # 0-65535 across the ADC's full range
        volts = raw / 65535 * 3.3          # ADC reference is 3.3V on every Pico board
        shell._out("ADC%d (GPIO%d) raw=%d  volts=%.3f" % (pin_num - 26, pin_num, raw, volts))
    except Exception as e:
        shell._err("could not read ADC on pin %d" % pin_num, e)
