"""Reads live per-client telemetry from the AP and posts it to telemetry_server."""
import subprocess, time, sys, requests

IFACE  = "wlp3s0"
SERVER = "http://localhost:5000/telemetry"

# Assumed noise floor: this driver has no survey support, so SNR is derived,
# not measured. Documented as an assumption in the README.
NOISE_FLOOR = {"2.4GHz": -90, "5GHz": -95, "6GHz": -95}

_prev = {}        # per-MAC cumulative counters from the previous poll
_band_seen = {}   # per-MAC RSSI per band, for the wall-vs-distance delta


def current_band():
    out = subprocess.run(["iw", "dev", IFACE, "info"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "channel" in line and "MHz" in line:
            mhz = int(line.split("(")[1].split()[0])
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
    out = subprocess.run(["iw", "dev", IFACE, "station", "dump"],
                         capture_output=True, text=True).stdout
    band = current_band()
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
            continue    # no signal reading means the sample is unusable

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
    while True:
        try:
            devs = poll()
            for d in devs:
                print(f"{d['device_id']}  {d['band']:6s} {d['standard']:7s} "
                      f"rssi={d['rssi']:4d}  snr={d['snr']:3d}  "
                      f"retry={d['retry_rate']:5.1f}%")
            if post and devs:
                requests.post(SERVER, json=devs, timeout=2)
            print(f"-- {len(devs)} device(s) --")
        except Exception as e:
            print("poll error:", e)
        if "--once" in sys.argv:
            break
        time.sleep(2)
