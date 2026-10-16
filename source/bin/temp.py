"""temp - read the chip's own temperature sensor (RP2040 / RP2350).

The sensor lives on ADC channel 4 (a fixed, chip-internal channel,
not a physical GPIO pin like ADC0-2 are). Conversion formula is
from the RP2040 datasheet (the RP2350's is the same): ~0.706V at 27C with
a slope of -1.721mV/C, so solving for temperature from a measured
voltage gives the line below.
"""

import shell
import machine


def run(args, cwd):
    try:
        sensor = machine.ADC(4)
        volts = sensor.read_u16() * 3.3 / 65535   # 16-bit reading -> volts
        celsius = 27 - (volts - 0.706) / 0.001721
        shell._out("%.1f C  (%.1f F)" % (celsius, celsius * 9 / 5 + 32))
    except Exception as e:
        shell._err("could not read onboard temperature sensor", e)
