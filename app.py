import sys, os, threading, subprocess
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
TRADE_ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_engine.py")

def run_trade_engine(ssid, uid, account):
    try:
        subprocess.run([sys.executable, TRADE_ENGINE, ssid, uid, account], check=False)
    except Exception as e:
        print("[ERR] " + str(e))

@app.route("/")
def index():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    ssid = (data.get("ssid") or "").strip()
    uid = (data.get("uid") or "").strip()
    account = (data.get("account") or "demo").strip().lower()
    if not ssid or len(ssid) < 15:
        return jsonify({"error": "Invalid token"}), 400
    if not uid or not uid.isdigit():
        return jsonify({"error": "uid must be a number"}), 400
    if account not in ["demo", "real"]:
        return jsonify({"error": "Invalid account type"}), 400
    t = threading.Thread(target=run_trade_engine, args=(ssid, uid, account))
    t.daemon = True
    t.start()
    return jsonify({"message": "Bot started for uid " + uid}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
