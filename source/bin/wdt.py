"""wdt - hardware watchdog timer. RP2040/RP2350 constraint: once
started it CANNOT be stopped or reconfigured - feed it (yourself,
or from a script) before the timeout or the board resets.
"""

import shell
import machine


def run(args, cwd):
    if not args:
        shell._out("usage: wdt start [timeout_ms]  |  wdt feed  |  wdt status")
        return
    action = args[0].lower()

    if action == "start":
        if shell._wdt is not None:
            shell._err("watchdog already running - it cannot be restarted or stopped")
            return
        try:
            timeout_ms = int(args[1]) if len(args) > 1 else 8000
        except ValueError:
            shell._err("timeout_ms must be a number")
            return
        try:
            shell._wdt = machine.WDT(timeout=timeout_ms)
            shell._out("watchdog armed at %dms - feed it (wdt feed) or the board will reset" % timeout_ms)
        except Exception as e:
            shell._err("could not start watchdog", e)
        return

    if action == "feed":
        if shell._wdt is None:
            shell._err("watchdog not running - start it with: wdt start [timeout_ms]")
            return
        try:
            shell._wdt.feed()
            shell._out("fed")
        except Exception as e:
            shell._err("could not feed watchdog", e)
        return

    if action == "status":
        wd = __import__("sys").modules.get("watchdog")
        if wd is not None and wd.running():
            h = wd.hang_minutes()
            shell._out("shell watchdog running (WATCHDOG=on) - fed automatically%s"
                       % (", resets after %d min without activity" % h if h else ""))
        elif shell._wdt is not None:
            shell._out("watchdog running - feed regularly or the board will reset")
        else:
            shell._out("watchdog not running")
        return

    shell._err("unknown action - %s" % action)
