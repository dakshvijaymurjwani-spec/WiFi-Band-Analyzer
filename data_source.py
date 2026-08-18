"""Single place that decides whether the app reads live or synthetic data.

Returns (devices, status). The status dict is what stops a silent fallback:
the old version swallowed every failure into `except: pass`, so a dead
poller and a healthy one were indistinguishable from the dashboard.
"""
import time

import requests

from synthetic_generator import DEVICE_PROFILES, generate_device

TELEMETRY_URL = "http://localhost:5000/telemetry"

# A sample older than this is not live data, it is a souvenir.
MAX_AGE_S = 15


def _synthetic(reason, detail):
    devices = [generate_device(f"dev{i}", p)
               for i, p in enumerate(DEVICE_PROFILES.keys())]
    for d in devices:
        d["source"] = "synthetic"
    return devices, {"source": "synthetic", "reason": reason, "detail": detail}


def get_devices():
    """
    Live data if the poller is running and its data is fresh, synthetic
    otherwise. Every sample carries a 'source' field so the UI can never
    present synthetic numbers as measured.
    """
    try:
        r = requests.get(TELEMETRY_URL, timeout=2)
    except requests.exceptions.ConnectionError:
        return _synthetic("server-down",
                          "Nothing listening on :5000 — start telemetry_server.py")
    except Exception as e:
        return _synthetic("server-error", f"{type(e).__name__}: {e}")

    if not r.ok:
        return _synthetic("server-error", f"HTTP {r.status_code}")

    body = r.json()
    # New server wraps the list; old server returned a bare list.
    devices = body.get("devices", []) if isinstance(body, dict) else body
    posted_at = body.get("posted_at") if isinstance(body, dict) else None

    posts = body.get("post_count", 0) if isinstance(body, dict) else 0
    if not devices:
        if posts:
            return _synthetic("no-clients",
                              f"Poller is alive ({posts} posts) but no client is "
                              "associated to the AP. Phone: mobile data OFF, MAC "
                              "randomisation OFF, rejoin the SSID.")
        return _synthetic("never-posted",
                          "Server is up but nothing has ever posted to it. "
                          "Start poller.py.")

    if posted_at is None:
        stamps = [d.get("timestamp") for d in devices if d.get("timestamp")]
        posted_at = max(stamps) if stamps else None

    # Two clocks, and the worst of the two wins. posted_at catches a dead
    # poller; the device timestamps catch a poller that is looping but
    # replaying old readings.
    now = time.time()
    ages = [now - posted_at] if posted_at else []
    ages += [now - d["timestamp"] for d in devices if d.get("timestamp")]
    age = max(ages) if ages else None
    if age is not None and age > MAX_AGE_S:
        return _synthetic("stale",
                          f"Last live sample is {age:.0f}s old — the poller has "
                          f"stopped. Refusing to label stale data as live.")

    for d in devices:
        d.setdefault("source", "live")
    return devices, {"source": "live", "reason": "ok",
                     "detail": f"{len(devices)} client(s), {age:.1f}s old"
                     if age is not None else f"{len(devices)} client(s)"}
