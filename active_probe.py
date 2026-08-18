"""Active measurements: things we *do* to the network, not just observe.

The passive pipeline (poller -> classify) only reports what the radio says.
These probes generate traffic to answer questions the station dump cannot:
is name resolution working, and what throughput does the link actually carry.

Every function returns a dict with an "ok" flag and a "detail" string rather
than raising or returning None, because the caller is a Streamlit panel that
has to render *something* for every outcome.
"""
import json
import shutil
import socket
import subprocess
import time

import requests

TICKET_ENDPOINT = "http://localhost:6000/ticket"


def check_dns(host="google.com", timeout=2.0):
    """Time a DNS resolution. Measures the AP's uplink, not any one client.

    Uses a per-socket timeout rather than socket.setdefaulttimeout(), which
    is process-global and would silently apply to every requests call in the
    dashboard.
    """
    start = time.perf_counter()
    try:
        socket.getaddrinfo(host, 80, proto=socket.IPPROTO_TCP)
        ms = round((time.perf_counter() - start) * 1000, 1)
        return {"ok": True, "ms": ms, "host": host,
                "detail": f"resolved in {ms} ms"}
    except socket.gaierror as e:
        return {"ok": False, "ms": None, "host": host,
                "detail": f"resolution failed: {e.strerror or e}"}
    except Exception as e:
        return {"ok": False, "ms": None, "host": host,
                "detail": f"{type(e).__name__}: {e}"}


def iperf3_available():
    return shutil.which("iperf3") is not None


def run_throughput_test(server=None, duration=3, reverse=False):
    """Run iperf3 against a server and return parsed Mbps.

    NOTE ON WHAT THIS MEASURES. Run on the AP laptop with an external
    server, this measures the laptop's *uplink* (the USB tether) — not any
    client's Wi-Fi throughput. To measure a client's Wi-Fi link you must run
    `iperf3 -s` here and an iperf3 client on the phone against 192.168.50.1.
    """
    if not server:
        return {"ok": False, "mbps": None,
                "detail": "No server set. Enter an iperf3 host, or run "
                          "`iperf3 -s` on this laptop and point a phone at "
                          "192.168.50.1 to measure the Wi-Fi link itself."}
    if not iperf3_available():
        return {"ok": False, "mbps": None,
                "detail": "iperf3 is not installed — sudo apt install iperf3"}

    cmd = ["iperf3", "-c", server, "-t", str(duration), "-J"]
    if reverse:
        cmd.append("-R")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=duration + 10)
    except subprocess.TimeoutExpired:
        return {"ok": False, "mbps": None,
                "detail": f"iperf3 timed out against {server}"}
    except Exception as e:
        return {"ok": False, "mbps": None, "detail": f"{type(e).__name__}: {e}"}

    if p.returncode != 0:
        msg = p.stderr.strip() or p.stdout.strip() or f"exit {p.returncode}"
        try:                      # iperf3 -J reports errors as JSON too
            msg = json.loads(p.stdout).get("error", msg)
        except Exception:
            pass
        return {"ok": False, "mbps": None, "detail": msg[:200]}

    try:
        data = json.loads(p.stdout)
        end = data["end"]
        stream = end["sum_received"] if "sum_received" in end else end["sum_sent"]
        mbps = round(stream["bits_per_second"] / 1e6, 1)
        retx = end.get("sum_sent", {}).get("retransmits")
        return {"ok": True, "mbps": mbps, "retransmits": retx,
                "direction": "download" if reverse else "upload",
                "detail": f"{mbps} Mbps"
                          + (f", {retx} retransmits" if retx is not None else "")}
    except (KeyError, ValueError) as e:
        return {"ok": False, "mbps": None,
                "detail": f"could not parse iperf3 output: {e}"}


def file_ticket(payload, ticket_endpoint=TICKET_ENDPOINT):
    """Escalate to the ISP (mock_isp_server.py on :6000).

    Distinct from app.py's own file_ticket(), which only appends to the
    dashboard's in-session list. This one leaves the process.
    """
    try:
        r = requests.post(ticket_endpoint, json=payload, timeout=3)
        r.raise_for_status()
        body = r.json()
        return {"ok": True, "response": body,
                "detail": f"ISP ticket #{body.get('ticket_id', '?')} "
                          f"({body.get('status', 'unknown')})"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "response": None,
                "detail": "mock_isp_server not reachable on :6000 — "
                          "run `python3 mock_isp_server.py`"}
    except Exception as e:
        return {"ok": False, "response": None,
                "detail": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print("DNS       :", check_dns()["detail"])
    print("iperf3    :", "installed" if iperf3_available() else "not installed")
    print("throughput:", run_throughput_test()["detail"])
    print("ISP ticket:", file_ticket(
        {"device_id": "probe-selftest", "issue": "connectivity check"})["detail"])