"""Synthetic devices for demoing without an access point running.

Each profile declares its own ground truth for capability and band history,
so the engine's confidence gating behaves the same way it does on live data.
Every profile maps to exactly one expected diagnosis — see test_classify.py.
"""
import random
import time

PROFILES = {
    # rssi/snr/retry ranges, plus explicit ground-truth fields
    "optimal": {
        "rssi": (-55, -40), "snr": (25, 40), "retry": (0, 5),
    },
    "hardware": {
        "rssi": (-55, -40), "snr": (25, 40), "retry": (0, 5),
        "std": "wifi4", "band": "2.4GHz",
        "supports_5ghz": False, "ap_offered_5ghz": True,
    },
    "attenuated": {
        "rssi": (-80, -70), "snr": (8, 15), "retry": (5, 15),
    },
    "distance": {
        "rssi": (-85, -75), "snr": (15, 22), "retry": (0, 5),
    },
    "congested": {
        "rssi": (-55, -45), "snr": (20, 30), "retry": (20, 40),
    },
    # A capable device that fell back to 2.4 GHz behind a wall — the flagship
    # case. band_rssi carries both readings so the cross-band test can fire.
    "wall_fallback": {
        "rssi": (-62, -55), "snr": (25, 35), "retry": (0, 5),
        "band": "2.4GHz", "supports_5ghz": True, "ap_offered_5ghz": True,
        "cross_band_gap": (18, 28),
    },
}

DEVICE_PROFILES = PROFILES  # alias so existing imports still work


def generate(device_id, profile):
    p = PROFILES[profile]
    band = p.get("band", "5GHz")
    std = p.get("std", "wifi6")
    rssi = round(random.uniform(*p["rssi"]), 1)
    snr = round(random.uniform(*p["snr"]), 1)
    retry = round(random.uniform(*p["retry"]), 1)

    d = {
        "device_id": device_id, "profile": profile, "band": band,
        "standard": std, "rssi": rssi, "snr": snr, "retry_rate": retry,
        "rssi_raw": rssi, "snr_raw": snr, "timestamp": time.time(),
    }

    for key in ("supports_5ghz", "ap_offered_5ghz"):
        if key in p:
            d[key] = p[key]

    if "cross_band_gap" in p:
        gap = round(random.uniform(*p["cross_band_gap"]), 1)
        d["band_rssi"] = {"2.4GHz": rssi, "5GHz": round(rssi - gap, 1)}

    return d


def generate_device(device_id, profile):
    return generate(device_id, profile)


if __name__ == "__main__":
    for i, p in enumerate(PROFILES):
        print(generate_device(f"dev{i}", p))
