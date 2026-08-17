"""Reads live per-client telemetry from the AP and posts it to telemetry_server.

Run this while hostapd is up. `iw station dump` needs root for signal readings,
so the iw calls are prefixed with sudo rather than running all of Python as root
(that way `requests` resolves from your normal user site-packages).

    python3 poller.py --once --no-post   # one poll, print only
    python3 poller.py                    # loop, post to telemetry_server
"""
import os
import subprocess
import sys
import time

import requests

IFACE = "wlp3s0"
SERVER = "http://localhost:5000/telemetry"

# Assumed noise floor: this driver has no survey support, so SNR is derived,
# not measured. Documented as an assumption in the README.
NOISE_FLOOR = {"2.4GHz": -90, "5GHz": -95, "6GHz": -95}

# iw needs root to report signal; prefix only the iw calls, not the interpreter.
SUDO = [] if os.geteuid() == 0 else ["sudo", "-n"]

_prev = {}       # per-MAC cumulative counters from the previous poll
_band_seen = {}  # per-MAC RSSI per band, for the wall-vs-distance delta
_ap_bands = set()  # every band THIS AP has beaconed on since the poller started

# A reading this strong means the client is practically touching the antenna.
# Near-field RSSI is not comparable to the thresholds in diagnostic_engine.
NEAR_FIELD_DBM = -25


def _iw(*args):
    return subprocess.run(SUDO + ["iw", "dev", IFACE, *args],
                          capture_output=True, text=True).stdout


def current_band():
    """Which band is our AP beaconing on right now."""
    for line in _iw("info").splitlines():
        if "channel" in line and "MHz" in line:
            try:
                mhz = int(line.split("(")[1].split()[0])
            except (IndexError, ValueError):
                continue
            if mhz > 5900:
                return "6GHz"
            if mhz > 3000:
                return "5GHz"
            return "2.4GHz"
    return "5GHz"


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
    out = _iw("station", "dump")
    band = current_band()
    _ap_bands.add(band)
    ap_offered_5ghz = any(b in _ap_bands for b in ("5GHz", "6GHz"))
    noise = NOISE_FLOOR[band]
    devices = []

    for block in out.split("Station ")[1:]:
        lines = block.splitlines()
        mac = lines[0].split()[0]

        d = {"device_id": mac, "band": band, "standard": "legacy",
             "rssi": None, "retry_rate": 0.0, "source": "live",
             "timestamp": time.time()}
        retries = packets = 0

        for line in lines[1:]:
            s = line.strip()
            if s.startswith("signal:"):
                d["rssi"] = int(s.split()[1])
            elif s.startswith("tx bitrate:"):
                d["tx_rate_mbps"] = float(s.split()[2])
                d["standard"] = phy_to_standard(s)
            elif s.startswith("tx retries:"):
                retries = int(s.split()[2])
            elif s.startswith("tx packets:"):
                packets = int(s.split()[2])
            elif s.startswith("connected time:"):
                d["connected_time"] = int(s.split()[2])

        if d["rssi"] is None:
            continue  # no signal reading means the sample is unusable

        # tx retries is CUMULATIVE. The rate is the delta between polls,
        # so the first poll for a device always reports 0.0.
        p = _prev.get(mac)
        if p:
            dp = packets - p["packets"]
            dr = retries - p["retries"]
            if dp > 0:
                d["retry_rate"] = round(dr / dp * 100, 1)
        _prev[mac] = {"packets": packets, "retries": retries}

        d["rssi_raw"] = d["rssi"]
        d["snr"] = d["rssi"] - noise
        d["snr_raw"] = d["snr"]

        # Remember this band's RSSI so classify() can compare bands later.
        # This survives an AP band switch as long as the poller keeps running.
        _band_seen.setdefault(mac, {})[band] = d["rssi"]
        d["band_rssi"] = dict(_band_seen[mac])

        # Capability. Only two things are real evidence:
        #   - we have SEEN the device on 5/6 GHz  -> capable, observed
        #   - the AP has OFFERED 5/6 GHz and the device never appeared there
        #     while negotiating only HT/legacy    -> not capable, observed
        # Anything else is untested: an AP that has only ever beaconed 2.4 GHz
        # cannot tell you whether a client supports 5 GHz.
        seen_high = any(b in _band_seen[mac] for b in ("5GHz", "6GHz"))
        d["ap_offered_5ghz"] = ap_offered_5ghz
        if seen_high:
            d["supports_5ghz"] = True
            d["capability_confidence"] = "observed"
        elif ap_offered_5ghz:
            d["supports_5ghz"] = False
            d["capability_confidence"] = "observed-absence"
        else:
            d["capability_confidence"] = "untested"

        # Data-quality flag rather than a silent bad reading
        if d["rssi"] > NEAR_FIELD_DBM:
            d["data_quality"] = (
                f"near-field: {d['rssi']}dBm is stronger than "
                f"{NEAR_FIELD_DBM}dBm — move the device several metres away"
            )

        devices.append(d)

    return devices


if __name__ == "__main__":
    post = "--no-post" not in sys.argv
    while True:
        try:
            devs = poll()
            for d in devs:
                print(f"{d['device_id']}  {d['band']:6s} {d['standard']:7s} "
                      f"rssi={d['rssi']:4d}  snr={d['snr']:3d}  "
                      f"retry={d['retry_rate']:5.1f}%  bands={list(d['band_rssi'])}")
            if post and devs:
                requests.post(SERVER, json=devs, timeout=2)
            print(f"-- {len(devs)} device(s) --")
        except Exception as e:
            print("poll error:", e)
        if "--once" in sys.argv:
            break
        time.sleep(2)
