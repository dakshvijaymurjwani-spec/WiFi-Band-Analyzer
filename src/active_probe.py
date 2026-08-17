import subprocess
import json
import requests
import time
import socket

def run_throughput_test(server="iperf3-server-ip"):
    result = subprocess.run(["iperf3", "-c", server, "-t", "3", "-J"], capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 else None

def check_dns(host="google.com"):
    start = time.time()
    try:
        socket.setdefaulttimeout(2.0)
        socket.gethostbyname(host)
        return time.time() - start
    except Exception:
        return None

def file_ticket(payload, ticket_endpoint="http://localhost:6000/ticket"):
    return requests.post(ticket_endpoint, json=payload)