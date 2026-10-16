"""boot - early system setup (Raspberry Pi Pico, Pico W, Pico 2,
Pico 2 W).

Runs automatically before main.py, on every power-up and reset -
this is a MicroPython convention (boot.py always runs first if
present), not something this project wires up itself.

Drives low any output pin left high, then sets up the globals
main.py uses as bare names - boot.py and main.py run in the same
top-level namespace, so no import is needed:
  reset_outputs - function, run once here at every start (not when
                  the shell restarts: a background job's pins stay).
  startup_key   - rp2.bootsel_button: True while BOOTSEL is held.
  status_led    - Pin for the onboard LED (GPIO25 on Pico/Pico 2,
                  driven through the wireless chip on the W boards).
  wdt, wdt_timer - the hardware watchdog and the timer feeding it,
                  when WATCHDOG=on (else None) - the shell takes them
                  over (lib/watchdog.py).

Keep this file error-free: if boot.py raises an exception,
MicroPython stops at the REPL and main.py is not run at all.
"""

import machine
import os
import rp2

# Never touched by reset_outputs(). On the W boards: GPIO23 wireless
# power, 24 data, 25 select, 29 clock - driving them low kills WiFi
# and the LED. On Pico/Pico 2: SMPS mode, VBUS sense, LED, VSYS
# sense. Same pins on all four boards, so one list covers them.
RESERVED_PINS = (23, 24, 25, 29)

# SIO register addresses (GPIO_OUT, GPIO_OUT_CLR, GPIO_OE) differ
# between the two chips.
_chip = os.uname().machine
if "RP2040" in _chip:                   # Pico, Pico W
    _SIO = (0xD0000010, 0xD0000018, 0xD0000020)
elif "RP2350" in _chip:                 # Pico 2, Pico 2 W
    _SIO = (0xD0000010, 0xD0000020, 0xD0000030)
else:
    _SIO = None

_MASK = 0x3FFFFFFF                      # GPIO0-29
for _p in RESERVED_PINS:
    _MASK &= ~(1 << _p)


def reset_outputs():
    """Drives low every GPIO that is currently an output set high.
    Inputs are left alone (driving an input low could short whatever
    is driving it from outside). Pins under PWM/UART/SPI/I2C/PIO
    control are not affected. Does nothing on an unknown chip."""
    if _SIO is None:
        return
    out, out_clr, oe = _SIO
    machine.mem32[out_clr] = machine.mem32[oe] & machine.mem32[out] & _MASK


# After a power-on everything is already low; after a soft reset
# (Ctrl-D) outputs keep their state, so clear them here.
reset_outputs()

startup_key = rp2.bootsel_button

status_led = machine.Pin("LED", machine.Pin.OUT)
status_led.off()


def _setting_on(key):
    """True if /etc/anix.conf has KEY=on (read here, before the shell)."""
    try:
        with open("/etc/anix.conf") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line[len(key) + 1:].strip().lower() == "on"
    except OSError:
        pass
    return False


# The hardware watchdog (WATCHDOG=on). Started here because boot.py
# runs at EVERY start - also after a soft reset from Thonny, mpremote
# or the PC menu, whose raw REPL skips main.py. A watchdog that is
# already running can't be stopped, so without this the board would
# reset 8 s into every file upload. A soft timer feeds it once a
# second: it only runs while MicroPython is alive, so a frozen board
# still resets. Not with BOOTSEL held (safe mode).
wdt = None
wdt_timer = None
if not startup_key() and _setting_on("WATCHDOG"):
    try:
        wdt = machine.WDT(timeout=8000)
        wdt_timer = machine.Timer(period=1000, mode=machine.Timer.PERIODIC,
                                  callback=lambda _t: wdt.feed())
    except Exception:
        pass
