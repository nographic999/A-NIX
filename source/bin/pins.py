"""pins - list configured pin modes/values.

Reads the shared state in shell.py (_pins/_adcs/_pwms) rather than
holding any of its own - see shell.py's comment on that dict for
why it has to live there: each /bin command is exec'd fresh, so
state that must survive between separate commands (e.g. a pin you
configured with `out` earlier) can only persist in the one module
that stays loaded for the whole session.
"""

import shell


def run(args, cwd):
    if not shell._pins and not shell._adcs and not shell._pwms:
        shell._out("no pins configured yet")
        return
    # sort key: group plain ints together (numeric order), "LED" last
    for key in sorted(shell._pins, key=lambda k: (isinstance(k, str), k)):
        try:
            val = shell._pins[key].value()
        except Exception:
            val = "?"
        label = "LED" if key == "LED" else "GPIO%s" % key
        shown = shell._c(shell.GREEN_BOLD, "1") if val == 1 else str(val)
        shell._out("%s  mode=%s  value=%s" % (label, shell._pin_modes.get(key, "?"), shown))
    for pin_num in sorted(shell._adcs):
        shell._out("GPIO%d  mode=adc" % pin_num)
    for pin_num in sorted(shell._pwms):
        shell._out("GPIO%d  mode=pwm" % pin_num)
