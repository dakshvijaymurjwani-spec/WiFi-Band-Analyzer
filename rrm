"""802.11k / 802.11v support, driven through hostapd_cli.

What this buys the project
--------------------------
Everything poller.py reads from `iw station dump` is the UPLINK: how well the
laptop hears the phone. Its SNR is derived by subtracting an ASSUMED noise
floor, because the driver has no survey support. Both are documented
assumptions in the README, and both are what an 802.11k beacon report
removes: the client reports its OWN measured RSSI and the actual noise it
sees, on the channel it sees it.

802.11v BSS Transition Management replaces the manual half of the cross-band
test. The current procedure is "Ctrl-C hostapd, start the other config, hope
the phone comes back". A transition request asks it to move.

Honest limits with one radio
----------------------------
  * Band steering does not work. Steering means offering a better BSS on
    another channel, and a single radio can only beacon on one at a time.
    `request_transition()` therefore uses disassoc_imminent to force a
    re-scan, which is enough for the sequential cross-band procedure but is
    not true 802.11v steering.
  * Neighbour reports will be empty. There are no neighbours.
  * Client support is optional. Most Android phones and recent iPhones
    implement 802.11k beacon reports; plenty of IoT devices do not. Every
    function here degrades to a clear "unsupported" rather than an exception.

Requires `ctrl_interface=/var/run/hostapd` in the hostapd config.
"""
import re
import shutil
import subprocess
import time

CTRL_IFACE = "/var/run/hostapd"

# Global operating classes (802.11 Annex E). Channel 0 means "every channel
# in this class", which is what makes a single request scan a whole band.
OPERATING_CLASS = {"2.4GHz": 81, "5GHz": 115, "6GHz": 131}

# Beacon request measurement modes.
MODE_PASSIVE, MODE_ACTIVE, MODE_TABLE = 0, 1, 2


def available():
    return shutil.which("hostapd_cli") is not None


def _cli(iface, *args, timeout=8):
    """Run hostapd_cli. Returns (ok, output). Never raises."""
    if not available():
        return False, "hostapd_cli not installed (apt install hostapd)"
    cmd = ["sudo", "-n", "hostapd_cli", "-p", CTRL_IFACE, "-i", iface, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "hostapd_cli timed out"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL"):
        return False, (p.stderr or out or f"exit {p.returncode}").strip()
    return True, out


def supports_rrm(iface, mac):
    """Does this client advertise 802.11k beacon-report capability?

    hostapd exposes the RRM capability bits in `sta <mac>`. A client that
    does not advertise them will silently ignore a beacon request, so this
    check is what separates "unsupported" from "no answer yet".
    """
    ok, out = _cli(iface, "sta", mac)
    if not ok:
        return None, out
    for line in out.splitlines():
        if line.startswith("rrm_capabilities="):
            caps = line.split("=", 1)[1].strip()
            # non-zero capability bitmap means some RRM support
            return (caps not in ("", "0", "00000000000000000000")), caps
    return False, "no rrm_capabilities reported"


def _beacon_request_hex(band, mode=MODE_TABLE, duration=50, channel=0):
    """Build the Measurement Request element body for a beacon request.

    Layout per 802.11-2020 9.4.2.20.7:
      operating class (1) | channel (1) | randomisation interval (2)
      | duration (2) | mode (1) | BSSID (6)

    Wildcard BSSID (all ff) means "report every BSS you can see".
    """
    op_class = OPERATING_CLASS.get(band, 115)
    return (f"{op_class:02x}{channel:02x}0000{duration:04x}{mode:02x}"
            f"ffffffffffff")


def request_beacon_report(iface, mac, band="5GHz", mode=MODE_TABLE,
                          duration=50, wait=3.0):
    """Ask a client for a beacon report. Returns a result dict.

    On success the report carries the client's own RSSI (rcpi) and noise
    (rsni) per BSS — the downlink measurement the passive pipeline cannot
    obtain. RCPI and RSNI are reported in 802.11 units; convert with
    rcpi_to_dbm() before comparing against anything from `iw`.
    """
    supported, caps = supports_rrm(iface, mac)
    if supported is False:
        return {"ok": False, "reason": "unsupported",
                "detail": f"{mac} does not advertise 802.11k RRM ({caps}). "
                          f"Falling back to the assumed noise floor."}

    ok, out = _cli(iface, "req_beacon", mac,
                   _beacon_request_hex(band, mode, duration))
    if not ok:
        return {"ok": False, "reason": "request-failed", "detail": out}

    # The response arrives asynchronously as a BEACON-RESP-RX control event.
    time.sleep(wait)
    ok2, events = _cli(iface, "raw", "ATTACH", timeout=2)
    return {"ok": True, "reason": "requested", "token": out,
            "detail": f"beacon request accepted for {mac} on {band}; "
                      f"responses surface as BEACON-RESP-RX events. Run "
                      f"`hostapd_cli -i {iface}` interactively to watch them.",
            "events": events if ok2 else None}


def parse_beacon_response(event_line):
    """Parse one BEACON-RESP-RX control event into a dict.

    Format: BEACON-RESP-RX <addr> <token> <rep_mode> <report hexdump>
    The report body carries operating class, channel, RCPI, RSNI and BSSID.
    """
    m = re.match(r"<?\d*>?BEACON-RESP-RX\s+(\S+)\s+(\d+)\s+(\d+)\s+([0-9a-fA-F]+)",
                 event_line.strip())
    if not m:
        return None
    mac, token, rep_mode, body = m.groups()
    if len(body) < 26:
        return {"device_id": mac, "token": int(token), "ok": False,
                "detail": "report body too short"}
    op_class = int(body[0:2], 16)
    channel = int(body[2:4], 16)
    rcpi = int(body[20:22], 16)
    rsni = int(body[22:24], 16)
    return {"device_id": mac, "token": int(token), "rep_mode": int(rep_mode),
            "operating_class": op_class, "channel": channel,
            "rcpi": rcpi, "rsni": rsni,
            "client_rssi_dbm": rcpi_to_dbm(rcpi),
            "client_snr_db": rsni_to_db(rsni),
            "source": "80211k", "ok": True}


def rcpi_to_dbm(rcpi):
    """RCPI is in half-dBm steps offset by 110 dBm (802.11 9.4.2.38)."""
    if rcpi in (255, None):
        return None
    return round(rcpi / 2.0 - 110.0, 1)


def rsni_to_db(rsni):
    """RSNI is in half-dB steps offset by 10 dB."""
    if rsni in (255, None):
        return None
    return round(rsni / 2.0 - 10.0, 1)


def request_transition(iface, mac, disassoc_timer=30, abridged=True):
    """802.11v BSS Transition Management request — ask a client to move.

    With one radio this cannot steer between bands; it forces a re-scan and
    re-association, which is what the sequential cross-band test needs.
    Prefer this over killing hostapd: the client keeps its association state
    and, critically, its MAC, so band_rssi pairing survives.
    """
    args = ["bss_tm_req", mac, f"disassoc_timer={disassoc_timer}"]
    if abridged:
        args.append("abridged=1")
    ok, out = _cli(iface, *args)
    return {"ok": ok,
            "detail": out if ok else f"transition request failed: {out}"}


def neighbor_report(iface):
    """List advertised neighbour APs. Expected to be empty on a single radio."""
    ok, out = _cli(iface, "show_neighbor")
    if not ok:
        return {"ok": False, "neighbors": [], "detail": out}
    rows = [l for l in out.splitlines() if l.strip()]
    return {"ok": True, "neighbors": rows,
            "detail": f"{len(rows)} neighbour(s)"
                      + ("" if rows else " — expected with one radio")}


if __name__ == "__main__":
    import sys
    iface = sys.argv[1] if len(sys.argv) > 1 else "wlp3s0"
    print("hostapd_cli:", "found" if available() else "NOT INSTALLED")
    print("neighbours :", neighbor_report(iface)["detail"])
    ok, out = _cli(iface, "all_sta")
    macs = re.findall(r"^([0-9a-f:]{17})$", out, re.M) if ok else []
    print("clients    :", macs or "none associated")
    for mac in macs:
        sup, caps = supports_rrm(iface, mac)
        print(f"  {mac}  802.11k: {sup}  caps={caps}")
        if sup:
            print("   ", request_beacon_report(iface, mac)["detail"])
