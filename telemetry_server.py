"""Telemetry sink. Demo-only: no auth.

Two changes from the original, both about not lying downstream:

  - the payload is wrapped with a server-side `posted_at`, so a consumer
    can tell fresh data from a snapshot left behind by a dead poller.
    The old version held its last payload forever.
  - `debug=True` is off. The reloader forks a second process, and only
    one of them holds the POSTed data — which produces a server that
    answers with devices on one request and an empty list on the next.
"""
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

latest = {"devices": [], "posted_at": None, "post_count": 0}


@app.route("/telemetry", methods=["POST"])
def receive():
    payload = request.get_json(silent=True)
    if not isinstance(payload, list):
        return jsonify({"status": "error",
                        "message": "expected a JSON list of device dicts"}), 400
    latest["devices"] = payload
    latest["posted_at"] = time.time()
    latest["post_count"] += 1
    return jsonify({"status": "ok", "received": len(payload)})


@app.route("/telemetry", methods=["GET"])
def send():
    return jsonify(latest)


@app.route("/health", methods=["GET"])
def health():
    age = time.time() - latest["posted_at"] if latest["posted_at"] else None
    return jsonify({
        "devices": len(latest["devices"]),
        "posts_received": latest["post_count"],
        "seconds_since_last_post": round(age, 1) if age is not None else None,
        "verdict": "never posted" if age is None
                   else ("fresh" if age < 15 else "STALE — poller stopped"),
    })


if __name__ == "__main__":
    print("telemetry_server on :5000  (GET /health for a liveness summary)")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
