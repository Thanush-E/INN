
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "alerts.db"

DATA_DIR.mkdir(exist_ok=True)


def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def current_time():
    return datetime.now(timezone.utc).isoformat()


def initialize_database():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS cs_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guardian_state TEXT,
                child_state TEXT,
                rssi INTEGER,
                buzzer INTEGER DEFAULT 0,
                received_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS cs_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                state TEXT,
                source TEXT DEFAULT 'HARDWARE',
                rssi INTEGER,
                priority TEXT DEFAULT 'NORMAL',
                acknowledged INTEGER DEFAULT 0,
                event_time TEXT NOT NULL,
                acknowledged_at TEXT,
                response_seconds REAL
            )
        """)

        db.commit()


initialize_database()


def get_latest_telemetry():
    with get_db() as db:
        row = db.execute("""
            SELECT * FROM cs_telemetry
            ORDER BY id DESC LIMIT 1
        """).fetchone()

    return dict(row) if row else None


def create_alert(event_type, state, rssi, priority):
    with get_db() as db:
        db.execute("""
            INSERT INTO cs_alerts
            (event_type, state, source, rssi, priority, event_time)
            VALUES (?, ?, 'HARDWARE', ?, ?, ?)
        """, (event_type, state, rssi, priority, current_time()))
        db.commit()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "database": "connected"
    })


@app.route("/api/device-health")
def device_health():
    latest = get_latest_telemetry()

    if not latest:
        return jsonify({
            "connection_status": "DISCONNECTED",
            "message": "Waiting for Guardian telemetry.",
            "last_seen": None
        })

    try:
        last_seen = datetime.fromisoformat(latest["received_at"])
        now = datetime.now(timezone.utc)

        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        age = (now - last_seen).total_seconds()
    except (ValueError, TypeError):
        age = 999999

    connected = age <= 15

    return jsonify({
        "connection_status": "CONNECTED" if connected else "DISCONNECTED",
        "message": (
            "Guardian telemetry is being received."
            if connected else
            "No recent Guardian telemetry received."
        ),
        "last_seen": latest["received_at"]
    })


@app.route("/api/status")
def status():
    latest = get_latest_telemetry()

    if not latest:
        return jsonify({
            "guardian_state": "SEARCHING",
            "child_status": "SEARCHING",
            "rssi": None,
            "buzzer": False,
            "message": "Waiting for Guardian device.",
            "simulated": False
        })

    return jsonify({
        "guardian_state": latest["guardian_state"],
        "child_status": latest["child_state"],
        "rssi": latest["rssi"],
        "buzzer": bool(latest["buzzer"]),
        "message": (
            "Child is connected."
            if latest["child_state"] == "SAFE"
            else f"Child state: {latest['child_state']}"
        ),
        "simulated": False
    })


@app.route("/api/telemetry", methods=["POST"])
def receive_telemetry():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON telemetry"}), 400

    guardian_state = str(
        data.get("guardian_state", data.get("state", "SEARCHING"))
    ).upper()

    child_state = str(
        data.get("child_state", "SAFE")
    ).upper()

    rssi = data.get("rssi")
    buzzer = bool(data.get("buzzer", False))

    allowed_guardian = {
        "SEARCHING", "CONNECTED", "SEPARATION_ALERT"
    }

    allowed_child = {
        "SAFE", "TILT", "FALL"
    }

    if guardian_state not in allowed_guardian:
        return jsonify({"error": "Unknown guardian_state"}), 400

    if child_state not in allowed_child:
        return jsonify({"error": "Unknown child_state"}), 400

    try:
        rssi = int(rssi) if rssi is not None else None
    except (ValueError, TypeError):
        return jsonify({"error": "RSSI must be an integer"}), 400

    timestamp = current_time()
    previous = get_latest_telemetry()

    with get_db() as db:
        db.execute("""
            INSERT INTO cs_telemetry
            (guardian_state, child_state, rssi, buzzer, received_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            guardian_state,
            child_state,
            rssi,
            int(buzzer),
            timestamp
        ))
        db.commit()

    previous_guardian = previous["guardian_state"] if previous else None
    previous_child = previous["child_state"] if previous else None

    if guardian_state == "SEPARATION_ALERT":
        if previous_guardian != "SEPARATION_ALERT":
            create_alert(
                "SEPARATION",
                guardian_state,
                rssi,
                "HIGH"
            )

    if child_state == "FALL":
        if previous_child != "FALL":
            create_alert(
                "FALL",
                child_state,
                rssi,
                "CRITICAL"
            )

    if child_state == "TILT":
        if previous_child != "TILT":
            create_alert(
                "MOTION",
                child_state,
                rssi,
                "NORMAL"
            )

    return jsonify({
        "success": True,
        "message": "Telemetry stored successfully."
    }), 201


@app.route("/api/alerts")
def alerts():
    try:
        limit = int(request.args.get("limit", 100))
        limit = max(1, min(limit, 500))
    except ValueError:
        limit = 100

    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM cs_alerts
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
def acknowledge_alert(alert_id):
    now = datetime.now(timezone.utc)

    with get_db() as db:
        row = db.execute("""
            SELECT * FROM cs_alerts WHERE id = ?
        """, (alert_id,)).fetchone()

        if row is None:
            return jsonify({"error": "Alert not found"}), 404

        if not row["acknowledged"]:
            try:
                event_time = datetime.fromisoformat(row["event_time"])
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)

                response_seconds = max(
                    0, (now - event_time).total_seconds()
                )
            except (ValueError, TypeError):
                response_seconds = None

            db.execute("""
                UPDATE cs_alerts
                SET acknowledged = 1,
                    acknowledged_at = ?,
                    response_seconds = ?
                WHERE id = ?
            """, (now.isoformat(), response_seconds, alert_id))

            db.commit()

    return jsonify({
        "success": True,
        "message": "Alert acknowledged."
    })


@app.route("/api/analytics")
def analytics():
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM cs_alerts"
        ).fetchone()[0]

        falls = db.execute(
            "SELECT COUNT(*) FROM cs_alerts WHERE event_type='FALL'"
        ).fetchone()[0]

        separations = db.execute(
            "SELECT COUNT(*) FROM cs_alerts WHERE event_type='SEPARATION'"
        ).fetchone()[0]

        motions = db.execute(
            "SELECT COUNT(*) FROM cs_alerts WHERE event_type='MOTION'"
        ).fetchone()[0]

        acknowledged = db.execute(
            "SELECT COUNT(*) FROM cs_alerts WHERE acknowledged=1"
        ).fetchone()[0]

        pending = db.execute(
            "SELECT COUNT(*) FROM cs_alerts WHERE acknowledged=0"
        ).fetchone()[0]

        average = db.execute("""
            SELECT AVG(response_seconds)
            FROM cs_alerts
            WHERE acknowledged=1
              AND response_seconds IS NOT NULL
        """).fetchone()[0]

    return jsonify({
        "total": total,
        "falls": falls,
        "separations": separations,
        "motions": motions,
        "acknowledged": acknowledged,
        "unacknowledged": pending,
        "average_response_seconds": average
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
