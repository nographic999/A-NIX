"""gpio - shared pin helpers for the out/in/pwm/adc /bin commands.

A GPIO pin can only be in one mode at a time (digital out, digital
in, PWM or ADC), but each mode keeps its objects in its own dict in
shell.py (_pins/_pin_modes, _pwms, _adcs). release() removes a pin
from every dict except the one the calling command is about to use,
so `pins` never lists one pin twice and a PWM is properly stopped
before the pin is reused.

RESERVED_PINS is the same list as in boot.py - keep the two in sync.
On the Pico W / Pico 2 W these pins drive the wireless chip (23
power, 24 data, 25 select, 29 clock): driving them by hand kills
WiFi and the LED. On the Pico / Pico 2 they are SMPS mode, VBUS
sense, LED and VSYS sense. The onboard LED stays reachable by name
as LED on every board.
"""

import shell
import machine

RESERVED_PINS = (23, 24, 25, 29)


def check(pin):
    """True if pin may be used; prints an error and returns False if
    it is reserved."""
    if pin in RESERVED_PINS:
        shell._err("GPIO%d is reserved for board use - use LED for the onboard LED" % pin)
        return False
    return True


def release(key, keep):
    """Drops key from every mode dict except keep ("pin", "pwm" or
    "adc"). A PWM being dropped is stopped and its pin set back to a
    pulled-down input, so it can't stay stuck at its last level."""
    if keep != "pin":
        shell._pins.pop(key, None)
        shell._pin_modes.pop(key, None)
    if keep != "pwm":
        p = shell._pwms.pop(key, None)
        if p is not None:
            try:
                p.deinit()
            except Exception:
                pass
            try:
                machine.Pin(key, machine.Pin.IN, machine.Pin.PULL_DOWN)
            except Exception:
                pass
    if keep != "adc":
        shell._adcs.pop(key, None)
