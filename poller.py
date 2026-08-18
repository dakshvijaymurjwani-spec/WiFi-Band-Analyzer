"""Reads live per-client telemetry from the AP and posts it to telemetry_server.

Changes from the original, all of them about failing loudly:

  - calls `sudo -n iw`. `iw station dump` needs CAP_NET_ADMIN to report
    signal. Without it the command exits non-zero, subprocess does NOT
    raise, stdout is empty, the parse loop finds zero stations, and the
    original `if post and devs:` guard meant nothing was ever POSTed.
    Three layers of silence over one permissions error.
  - autodetects the AP interface instead of hardcoding wlp3s0.
  - POSTs even an empty list, so the server can distinguish "poller is
    running and sees nobody" from "poller is dead".
  - captures the real channel and negotiated PHY rate.
"""
import os
import re
import subprocess
import sys
import time

import requests

IFACE = os.environ.get("WBA_IFACE")        # autodetected if unset
SERVER = os.environ.get("WBA_SERVER", "http://localhost:5000/telemetry")

# Assumed noise floor: this driver has no survey support, so SNR is derived,
# not measured. Documented as an assumption in the README.
NOISE_FLOOR = {"2.4GHz": -90, "5GHz": -95, "6GHz": -95}

_prev = {}        # per-MAC cumulative counters from the previous poll
_band_seen = {}   # per-MAC RSSI per band, for the wall-vs-distance delta
_ap_bands = set() # bands THIS AP has beaconed on during the session


def sh(*args):
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{args[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def iw(*args):
    """iw needs root for signal data. sudo -n so it fails fast, not hangs."""
    rc, out, err = sh("sudo", "-n", "iw", *args)
    if rc != 0 and "password" in err.lower():
        raise PermissionError(
            "sudo wants a password for iw. Grant it once:\n"
            '  echo "$USER ALL=(root) NOPASSWD: $(which iw)" '
            "| sudo tee /etc/sudoers.d/wba")
    if rc != 0:
        raise RuntimeError(f"iw {' '.join(args)} failed: {err.strip() or rc}")
    return out


def detect_iface():
    """First interface in AP mode; that is the one hostapd is driving."""
    rc, out, _ = sh("iw", "dev")
    pairs = re.findall(r"Interface (\S+)[\s\S]*?type (\S+)", out)
    for name, mode in pairs:
        if mode == "AP":
            return name
    raise RuntimeError(
        "No interface is in AP mode. hostapd is not running, or "
        "NetworkManager reclaimed the card:\n"
        "  sudo nmcli device set <iface> managed no\n"
        f"  interfaces seen: {pairs or 'none'}")


def band_and_channel():
    """Parse the AP's operating frequency out of `iw dev <iface> info`."""
    out = iw("dev", IFACE, "info")
    chan = None
    for line in out.splitlines():
        if "channel" in line and "MHz" in line:
            parts = line.split()
            try:
                chan = int(parts[parts.index("channel") + 1])
            except (ValueError, IndexError):
                pass
            mhz = int(line.split("(")[1].split()[0])
            if mhz > 5900:
                return "6GHz", chan
            if mhz > 3000:
                return "5GHz", chan
            return "2.4GHz", chan
    return "5GHz", chan


def phy_to_standard(line):
    """The negotiated bitrate string reveals the client's Wi-Fi generation."""
    if "EHT-" in line:
        return "wifi7"
    if "HE-" in line:
        return "wifi6"
    if "VHT-" in line:
        return "wifi5"
    if "MCS" in line:
        return "wifi4"
    return "legacy"


def poll():
    out = iw("dev", IFACE, "station", "dump")
    band, channel = band_and_channel()
    _ap_bands.add(band)
    # Whether the AP ever offered 5/6 GHz decides whether "never seen on
    # 5 GHz" is evidence of a 2.4-only radio or merely evidence that we
    # never gave the device the chance. Without this, a 2.4 GHz-only
    # session labels every client Hardware Limited.
    ap_offered_5 = any(b in _ap_bands for b in ("5GHz", "6GHz"))
    noise = NOISE_FLOOR[band]
    devices = []

    for block in out.split("Station ")[1:]:
        lines = block.splitlines()
        mac = lines[0].split()[0]

        d = {"device_id": mac, "band": band, "channel": channel,
             "standard": "legacy", "rssi": None, "retry_rate": 0.0,
             "profile": "live", "source": "live",
             "ap_offered_5ghz": ap_offered_5, "timestamp": time.time()}
        retries = packets = 0

        for line in lines[1:]:
            s = line.strip()
            if s.startswith("signal:"):
                # some drivers print -37, others -37.00 — float then round
                d["rssi"] = round(float(s.split()[1]))
            elif s.startswith("tx bitrate:"):
                rate = float(s.split()[2])
                d["tx_rate_mbps"] = rate
                d["phy_rate"] = rate          # what diagnostic_engine looks for
                d["standard"] = phy_to_standard(s)
            elif s.startswith("tx retries:"):
                retries = int(s.split()[2])
            elif s.startswith("tx packets:"):
                packets = int(s.split()[2])
            elif s.startswith("connected time:"):
                d["connected_time"] = int(s.split()[2])

        if d["rssi"] is None:
            print(f"  ! {mac}: no signal line — running without root?")
            continue

        # tx retries is CUMULATIVE. The rate is the delta between polls.
        p = _prev.get(mac)
        if p:
            dp = packets - p["packets"]
            dr = retries - p["retries"]
            if dp > 0:
                d["retry_rate"] = round(dr / dp * 100, 1)
        _prev[mac] = {"packets": packets, "retries": retries}

        d["rssi_raw"] = d["rssi"]
        d["snr"] = d["rssi"] - noise

        # Remember this band's RSSI so classify() can compare bands later
        _band_seen.setdefault(mac, {})[band] = d["rssi"]
        d["band_rssi"] = dict(_band_seen[mac])

        # Capability: if we've ever seen this device on 5 or 6 GHz, it supports it
        d["supports_5ghz"] = any(b in _band_seen[mac] for b in ("5GHz", "6GHz"))
        d["capability_confidence"] = "observed" if d["supports_5ghz"] else "inferred"

        devices.append(d)

    return devices


if __name__ == "__main__":
    post = "--no-post" not in sys.argv

    if not IFACE:
        try:
            IFACE = detect_iface()
        except RuntimeError as e:
            print(f"FATAL: {e}")
            raise SystemExit(1)
    print(f"polling {IFACE} -> {SERVER if post else '(no post)'}\n")

    empty_streak = 0
    while True:
        try:
            devs = poll()
            for d in devs:
                print(f"{d['device_id']}  {d['band']:6s} {d['standard']:7s} "
                      f"rssi={d['rssi']:4d}  snr={d['snr']:3d}  "
                      f"retry={d['retry_rate']:5.1f}%")

            if devs:
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak in (1, 5, 20):
                    print("-- 0 clients associated. Phone: mobile data OFF, "
                          "MAC randomisation OFF, rejoin the SSID. --")

            # POST even when empty: an empty post proves the poller is alive.
            if post:
                try:
                    requests.post(SERVER, json=devs, timeout=2)
                except requests.exceptions.ConnectionError:
                    print("-- telemetry_server not reachable on :5000 --")

            print(f"-- {len(devs)} device(s) --")
        except PermissionError as e:
            print(f"FATAL: {e}")
            raise SystemExit(1)
        except Exception as e:
            print(f"poll error: {type(e).__name__}: {e}")

        if "--once" in sys.argv:
            break
        time.sleep(2)