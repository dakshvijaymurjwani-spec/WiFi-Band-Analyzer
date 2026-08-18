import random, time

PROFILES = {
    "optimal":    {"rssi": (-55,-40), "snr": (25,40), "retry": (0,5)},
    "hardware":   {"rssi": (-55,-40), "snr": (25,40), "retry": (0,5), "std": "wifi4"},
    "attenuated": {"rssi": (-80,-70), "snr": (8,15),  "retry": (5,15)},
    "distance":   {"rssi": (-85,-75), "snr": (15,22), "retry": (0,5)},
    "congested":  {"rssi": (-55,-45), "snr": (20,30), "retry": (20,40)},
}

DEVICE_PROFILES = PROFILES  # alias so existing imports still work

def generate(device_id, profile):
    p = PROFILES[profile]
    band = "2.4GHz" if profile == "hardware" else "5GHz"
    std = p.get("std", "wifi6")
    rssi = round(random.uniform(*p["rssi"]), 1)
    snr = round(random.uniform(*p["snr"]), 1)
    retry = round(random.uniform(*p["retry"]), 1)
    return {"device_id": device_id, "profile": profile, "band": band, "standard": std,
            "rssi": rssi, "snr": snr, "retry_rate": retry, "timestamp": time.time()}

def generate_device(device_id, profile):
    return generate(device_id, profile)

if __name__ == "__main__":
    devices = [generate_device(f"dev{i}", p) for i, p in enumerate(PROFILES.keys())]
    for d in devices:
        print(d)
