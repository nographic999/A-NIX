"""ble - scan for nearby BLE devices, or advertise as a peripheral
(W boards; needs firmware with Bluetooth).

  ble scan [seconds]          list devices (default 5 s)
  ble advertise <name> [s]    advertise; without seconds until stopped
  ble advertise stop
  ble status                  radio on/off
  ble off                     switch the radio off

The BLE radio state lives in shell.py (like pins/uarts) so it
persists across separate calls instead of resetting every command.

Uses the low-level `bluetooth` module directly (event codes and
raw advertising-data bytes, not a higher-level GATT wrapper) - this
is discovery and simple advertising only, no GATT client/server.
"""

import time
import shell

try:
    import bluetooth
except ImportError:
    bluetooth = None

# event codes bluetooth.BLE().irq() delivers - these two are the
# only ones this module cares about (out of many more real ones for
# connections, GATT reads/writes, etc., unused here)
_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6
_MAX_DEVICES = 50       # a busy place sends thousands of adverts
_MAX_NAME = 26          # 31-byte advert - flags (3) - name header (2)


def _get_ble():
    """Creates the radio once and registers _irq as its callback -
    every later call just returns the same object, so the radio
    stays active (and _irq stays registered) for the rest of the
    session rather than re-initializing on every "ble" command."""
    if shell._ble is None:
        shell._ble = bluetooth.BLE()
        shell._ble.active(True)
        shell._ble.irq(_irq)
    return shell._ble


def _irq(event, data):
    """Called by the BLE stack itself, asynchronously, whenever
    something happens during a scan - not called directly by any
    code in this file. Writes into shell._ble_scan_results/
    _ble_scan_done (not a local variable) because this function gets
    redefined fresh every time ble.py is exec'd, but the scan loop
    that's *waiting* on the results is a separate, later invocation
    reading from shell.py's persistent state - only that shared
    state is guaranteed to still be there when the results arrive."""
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        addr_hex = ":".join("%02X" % b for b in bytes(addr))
        name = _decode_name(bytes(adv_data))
        results = shell._ble_scan_results
        # one entry per device: keep the strongest signal and any name
        for i, (a, n, r) in enumerate(results):
            if a == addr_hex:
                results[i] = (a, name or n, max(r, rssi))
                return
        if len(results) < _MAX_DEVICES:
            results.append((addr_hex, name, rssi))
    elif event == _IRQ_SCAN_DONE:
        shell._ble_scan_done[0] = True


def _decode_name(adv_data):
    """BLE advertising data is a sequence of (length, type, ...data)
    chunks packed back to back - this walks that structure looking
    for a "shortened" (0x08) or "complete" (0x09) local name chunk,
    the two AD types that carry a human-readable device name."""
    i = 0
    while i + 1 < len(adv_data):
        length = adv_data[i]
        if length == 0 or i + 1 + length > len(adv_data):
            break               # end, or a damaged advert
        if adv_data[i + 1] in (0x08, 0x09):  # shortened/complete local name
            return adv_data[i + 2:i + 1 + length].decode("utf-8", "replace")
        i += 1 + length
    return None


def _build_adv_payload(name):
    """Builds the same kind of (length, type, data) chunked structure
    _decode_name reads: a flags chunk (general discoverable, classic
    Bluetooth/BR-EDR not supported - standard for a BLE-only Pico W
    peripheral) followed by a complete local name chunk."""
    payload = bytearray((2, 0x01, 0x06))  # flags: general discoverable, no BR/EDR
    name_bytes = name.encode()
    payload += bytes((len(name_bytes) + 1, 0x09)) + name_bytes
    return payload


def run(args, cwd):
    if not bluetooth:
        shell._err("bluetooth not supported on this platform")
        return
    if not args:
        shell._out("usage: ble scan [seconds]")
        shell._out("       ble advertise <name> [seconds]")
        shell._out("       ble advertise stop")
        shell._out("       ble status  |  ble off")
        return
    action = args[0].lower()

    if action == "status":
        on = shell._ble is not None and shell._ble.active()
        shell._out("BLE active" if on else "BLE off")
        return

    if action == "off":
        if shell._ble is not None:
            try:
                shell._ble.gap_advertise(None)
            except Exception:
                pass
            shell._ble.active(False)
            shell._ble = None
        shell._out("BLE off")
        return

    if action == "scan":
        try:
            seconds = float(args[1]) if len(args) > 1 else 5.0
        except ValueError:
            seconds = -1.0
        if not 0 < seconds <= 3600:
            shell._err("seconds must be more than 0, at most 3600")
            return
        ble = _get_ble()
        shell._ble_scan_results.clear()
        shell._ble_scan_done[0] = False
        duration_ms = int(seconds * 1000)
        try:
            ble.gap_scan(duration_ms, 30000, 30000)
        except Exception as e:
            shell._err("scan failed to start", e)
            return
        shell._out("scanning for %.1fs..." % seconds)
        # gap_scan() itself returns immediately - results trickle in
        # via _irq asynchronously as the radio finds devices, so this
        # blocks (checking every 50ms) until the radio signals it's
        # done, with a 1s grace period in case the done event is late
        start = time.ticks_ms()
        try:
            while not shell._ble_scan_done[0] and time.ticks_diff(time.ticks_ms(), start) < duration_ms + 1000:
                time.sleep_ms(50)
        finally:
            try:
                ble.gap_scan(None)      # stop early on Ctrl-C
            except Exception:
                pass
        if not shell._ble_scan_results:
            shell._out("no devices found")
            shell._set_status(1)
            return
        for addr, name, rssi in sorted(shell._ble_scan_results, key=lambda r: -r[2]):
            shell._out("%-17s  %-20s  %d dBm" % (addr, name or "(unnamed)", rssi))
        return

    if action == "advertise":
        if len(args) < 2:
            shell._out("usage: ble advertise <name> [seconds]  |  ble advertise stop")
            return
        ble = _get_ble()
        if args[1].lower() == "stop":
            try:
                ble.gap_advertise(None)
                shell._out("advertising stopped")
            except Exception as e:
                shell._err("could not stop advertising", e)
            return
        name = args[1]
        if len(name.encode()) > _MAX_NAME:
            shell._err("name too long - max %d bytes" % _MAX_NAME)
            return
        try:
            seconds = float(args[2]) if len(args) > 2 else None
        except ValueError:
            seconds = -1.0
        if seconds is not None and not 0 < seconds <= 86400:
            shell._err("seconds must be more than 0, at most 86400")
            return
        try:
            ble.gap_advertise(100000, _build_adv_payload(name))
        except Exception as e:
            shell._err("could not start advertising", e)
            return
        if seconds is None:
            shell._out("advertising as '%s' - stop with: ble advertise stop" % name)
        else:
            shell._out("advertising as '%s' for %.1fs..." % (name, seconds))
            try:
                time.sleep_ms(int(seconds * 1000))
            finally:
                try:
                    ble.gap_advertise(None)     # also on Ctrl-C
                except Exception:
                    pass
            shell._out("advertising stopped")
        return

    shell._err("unknown action - %s" % action)
