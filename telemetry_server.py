from flask import Flask, request, jsonify

app = Flask(__name__)
latest_data = []

@app.route("/telemetry", methods=["POST"])
def receive():
    global latest_data
    latest_data = request.json
    return jsonify({"status": "ok"})

@app.route("/telemetry", methods=["GET"])
def send():
    return jsonify(latest_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
