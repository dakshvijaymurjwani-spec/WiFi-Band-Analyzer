"""Single place that decides whether the app reads live or synthetic data."""
import requests

from synthetic_generator import DEVICE_PROFILES, generate_device

TELEMETRY_URL = "http://localhost:5000/telemetry"


def get_devices():
    """
    Live data if the poller is running, synthetic otherwise.
    Every sample carries a 'source' field so the UI can never
    present synthetic numbers as measured.
    """
    try:
        r = requests.get(TELEMETRY_URL, timeout=2)
        if r.ok:
            data = r.json()
            if data:
                for d in data:
                    d.setdefault("source", "live")
                return data
    except Exception:
        pass

    devices = [generate_device(f"dev{i}", p)
               for i, p in enumerate(DEVICE_PROFILES.keys())]
    for d in devices:
        d["source"] = "synthetic"
    return devices
