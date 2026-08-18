"""
Walks the live-data chain hop by hop and tells you exactly where it breaks.

    python3 preflight.py

Every hop between the radio and the dashboard can fail silently in this
stack. This makes each one say so out loud.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "
HERE = os.path.dirname(os.path.abspath(__file__))

fails = []


def say(state, name, detail=""):
    print(f"[{state}] {name}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    if state == BAD:
        fails.append(name)


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


# ---------------------------------------------------------------- hop 0: wiring
print("\n--- hop 0: is the dashboard even wired to the live path? ---")
app = os.path.join(HERE, "app.py")
if not os.path.exists(app):
    say(WARN, "app.py not found next to preflight.py", HERE)
else:
    src = open(app).read()
    if "get_devices" in src:
        say(OK, "app.py calls data_source.get_devices()")
    else:
        say(BAD, "app.py never calls get_devices()",
            "It builds its devices from synthetic_generator directly.\n"
            "No amount of fixing the radio will change what it displays.")

# ---------------------------------------------------------------- hop 1: radio
print("\n--- hop 1: the radio ---")
if not shutil.which("iw"):
    say(BAD, "`iw` not installed", "sudo apt install iw")
    IFACE = None
else:
    rc, out, err = run(["iw", "dev"])
    ifaces = re.findall(r"Interface (\S+)", out)
    modes = dict(re.findall(r"Interface (\S+)[\s\S]*?type (\S+)", out))
    say(OK if ifaces else BAD, f"interfaces visible: {ifaces or 'none'}")

    IFACE = os.environ.get("WBA_IFACE")
    ap_ifaces = [i for i, m in modes.items() if m == "AP"]
    if not IFACE:
        IFACE = ap_ifaces[0] if ap_ifaces else (ifaces[0] if ifaces else None)

    if ap_ifaces:
        say(OK, f"AP-mode interface: {ap_ifaces}")
    else:
        say(BAD, "no interface is in AP mode",
            f"types seen: {modes}\n"
            "hostapd is not running, or NetworkManager took the card back.\n"
            "  sudo nmcli device set <iface> managed no\n"
            "  sudo hostapd hostapd-24.conf")

    # what the poller thinks it is talking to
    try:
        poller_src = open(os.path.join(HERE, "poller.py")).read()
        m = re.search(r'^IFACE\s*=\s*["\'](\S+)["\']', poller_src, re.M)
        if m and IFACE and m.group(1) != IFACE:
            say(BAD, "poller.py IFACE does not match the real interface",
                f"poller.py says {m.group(1)!r}, the card is {IFACE!r}")
        elif m:
            say(OK, f"poller.py IFACE = {m.group(1)}")
    except OSError:
        pass

rc, out, _ = run(["pgrep", "-a", "hostapd"])
say(OK if rc == 0 else BAD, "hostapd process",
    out.strip() or "not running — clients have nothing to associate to")

rc, out, _ = run(["pgrep", "-a", "dnsmasq"])
say(OK if rc == 0 else WARN, "dnsmasq process",
    out.strip() or "not running — clients get no IP and will disassociate")

# ------------------------------------------------------------- hop 2: stations
print("\n--- hop 2: can we read station telemetry? ---")
if IFACE:
    rc, out, err = run(["iw", "dev", IFACE, "station", "dump"])
    if rc != 0:
        say(BAD, "`iw station dump` without sudo", err.strip() or f"exit {rc}")
        rc2, out2, err2 = run(["sudo", "-n", "iw", "dev", IFACE, "station", "dump"])
        if rc2 == 0:
            say(WARN, "but it works with sudo",
                "poller.py calls plain `iw`, so it reads nothing and posts nothing.\n"
                "Use the patched poller.py, which calls sudo.")
            out = out2
        else:
            say(BAD, "`sudo -n iw station dump` also fails", err2.strip() or f"exit {rc2}")
    else:
        say(OK, "`iw station dump` readable")

    n = out.count("Station ")
    if n:
        say(OK, f"{n} client(s) associated")
        if "signal:" not in out:
            say(BAD, "no `signal:` line in the dump",
                "poller.py skips every device with rssi=None. Needs root.")
    else:
        say(BAD, "0 clients associated",
            "Phone: turn mobile data OFF, MAC randomisation OFF, then rejoin.\n"
            "A client with no internet route disassociates on its own.")

# --------------------------------------------------------------- hop 3: poller
print("\n--- hop 3: the poller ---")
sys.path.insert(0, HERE)
try:
    import poller
    # poller.IFACE is only resolved inside its __main__ block; set it here
    # or poll() dies with an unhelpful TypeError on None.
    poller.IFACE = poller.IFACE or IFACE
    if not poller.IFACE:
        raise RuntimeError("no interface to poll — fix hop 1 first")
    devs = poller.poll()
    if devs:
        say(OK, f"poll() returned {len(devs)} device(s)",
            json.dumps(devs[0], indent=2)[:400])
    else:
        say(BAD, "poll() returned an empty list",
            "poller.py only POSTs when this is non-empty, so the server\n"
            "is never told anything at all — not even that it is empty.")
except Exception as e:
    say(BAD, "poll() raised", f"{type(e).__name__}: {e}")

# ------------------------------------------------------- hop 4: telemetry server
print("\n--- hop 4: telemetry server ---")
try:
    import requests
    try:
        r = requests.get("http://localhost:5000/telemetry", timeout=2)
        body = r.json()
        payload = body.get("devices", body) if isinstance(body, dict) else body
        if payload:
            ages = [time.time() - d.get("timestamp", 0) for d in payload
                    if isinstance(d, dict) and d.get("timestamp")]
            age = min(ages) if ages else None
            if age is not None and age > 15:
                say(BAD, f"server is serving data {age:.0f}s old",
                    "The poller has stopped. The old server never expires this,\n"
                    "so the dashboard would label stale numbers as live.")
            else:
                say(OK, f"{len(payload)} device(s), fresh"
                       + (f" ({age:.1f}s)" if age is not None else ""))
        else:
            say(BAD, "server up but holding no devices",
                "Nothing has ever POSTed to it. Start poller.py.")
    except requests.exceptions.ConnectionError:
        say(BAD, "nothing listening on :5000", "python3 telemetry_server.py")
    except Exception as e:
        say(BAD, "server responded badly", f"{type(e).__name__}: {e}")
except ImportError:
    say(BAD, "requests not installed", "pip install -r requirements.txt")

# ---------------------------------------------------------- hop 5: data_source
print("\n--- hop 5: what the dashboard would receive ---")
try:
    from data_source import get_devices
    result = get_devices()
    devices, status = result if isinstance(result, tuple) else (result, None)
    src = status["source"] if status else devices[0].get("source", "?")
    if src == "live":
        say(OK, f"data_source returns LIVE ({len(devices)} devices)")
    else:
        say(BAD, f"data_source falls back to {src.upper()}",
            (status or {}).get("detail", "the live path is not producing data"))
except Exception as e:
    say(BAD, "data_source.get_devices() raised", f"{type(e).__name__}: {e}")

# ------------------------------------------------------------------- verdict
print("\n" + "=" * 62)
if fails:
    print(f"{len(fails)} broken hop(s). Fix the FIRST one listed — the rest\n"
          "are usually downstream symptoms of it:\n")
    for f in fails:
        print(f"  - {f}")
else:
    print("Whole chain is live. If the dashboard still shows synthetic data,\n"
          "restart Streamlit — session_state caches the device list.")
print("=" * 62)
raise SystemExit(1 if fails else 0)
