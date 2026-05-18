#!/usr/bin/env python3
"""
Stasis Hackathon — Public Leaderboard
Run:  pip install flask
      python app.py
Open: http://localhost:5000
"""

from flask import Flask, render_template
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "nfc-scanner", "badge_scans.db")
)


def get_leaderboard():
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT COALESCE(name, uid) AS display_name,
                   COALESCE(points, 0)  AS pts
            FROM   badges
            ORDER  BY pts DESC, last_seen DESC
            """
        ).fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"DB error: {e}")
        return []


@app.route("/")
def index():
    return render_template(
        "index.html",
        players=get_leaderboard(),
        updated_at=datetime.now().strftime("%H:%M:%S"),
    )


if __name__ == "__main__":
    print(f"  Leaderboard → http://localhost:5000")
    print(f"  Database    → {DB_PATH}")
    app.run(host="0.0.0.0", port=5000, debug=False)
