from flask import Flask, request, jsonify
app = Flask(__name__)
tickets = []

@app.route("/ticket", methods=["POST"])
def create_ticket():
    tickets.append(request.json)
    return jsonify({"ticket_id": len(tickets), "status": "received"})

if __name__ == "__main__":
    app.run(port=6000)