import pcsclite_backend
import argparse
import sqlite3
from datetime import datetime
from smartcard.util import toHexString
import subprocess
import sys
import Database
import Player

DB_PATH = "badge_scans.db"

def init_database():
    """Initialize the database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS badges (
        uid TEXT PRIMARY KEY,
        atqa TEXT,
        sak TEXT,
        ats TEXT,
        historical_bytes TEXT,
        card_type_guess TEXT,
        created_at TEXT,
        last_seen TEXT,
        points INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS badge_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT NOT NULL,
        scanned_at TEXT NOT NULL,
        apdu TEXT,
        response TEXT,
        status_words TEXT,
        reader_name TEXT,
        FOREIGN KEY(uid) REFERENCES badges(uid)
    )
    """)
    
    conn.commit()
    conn.close()


def badge_exists(uid):
    """Return True if a badge record already exists for `uid`."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM badges WHERE uid = ?", (uid,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def ensure_badge_exists(uid):
    """Ensure a badge row exists for `uid` with default points.

    If the badge already exists, only update the last_seen timestamp.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    if badge_exists(uid):
        cursor.execute(
            """
            UPDATE badges SET last_seen = ? WHERE uid = ?
            """,
            (now, uid),
        )
    else:
        cursor.execute(
            """
            INSERT INTO badges (uid, created_at, last_seen, points)
            VALUES (?, ?, ?, 0)
            """,
            (uid, now, now),
        )

    conn.commit()
    conn.close()


def get_points(uid):
    """Return integer points for the given uid, or 0 if not found."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM badges WHERE uid = ?", (uid,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0] is not None:
        try:
            return int(row[0])
        except Exception:
            return 0
    return 0


def record_scan(uid, apdu_bytes, response_bytes, status_words, reader_name):
    """Insert a row into badge_scans for this scan event."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        """
        INSERT INTO badge_scans (uid, scanned_at, apdu, response, status_words, reader_name)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            now,
            apdu_bytes,
            response_bytes,
            status_words,
            reader_name,
        ),
    )
    conn.commit()
    conn.close()


def is_faulty_read(response):
    """Return True for faulty badge reads whose UID/response is 63 00."""
    if response is None:
        return False
    if isinstance(response, (bytes, bytearray)):
        return response == b"\x63\x00"
    if isinstance(response, list) and len(response) == 2:
        return response[0] == 0x63 and response[1] == 0x00
    try:
        uid_hex = toHexString(response)
        return uid_hex.replace(" ", "").upper() == "6300"
    except Exception:
        return False


def get_leaderboard(limit=None):
    """Return leaderboard rows sorted from greatest to least by points."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = "SELECT uid, points, last_seen FROM badges ORDER BY points DESC, last_seen DESC"
    if limit is not None:
        cursor.execute(query + " LIMIT ?", (limit,))
    else:
        cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    return rows


def print_leaderboard(limit=10):
    leaderboard = get_leaderboard(limit)
    if not leaderboard:
        print("Leaderboard is empty. No players have points yet.")
        return

    print("=== Leaderboard ===")
    for rank, (uid, points, last_seen) in enumerate(leaderboard, start=1):
        points_display = points if points is not None else 0
        print(f"{rank:>2}. {uid} — {points_display} points (last seen {last_seen})")


def show_notification(title, subtitle="", message=""):
    """Show a native notification (macOS/Linux) or fallback to console."""
    try:
        if sys.platform == "darwin":
            t = title.replace('"', '\\"')
            s = subtitle.replace('"', '\\"')
            m = message.replace('"', '\\"')
            cmd = f'display notification "{m}" with title "{t}" subtitle "{s}"'
            subprocess.run(["osascript", "-e", cmd], check=False)
        elif sys.platform.startswith("linux"):
            body = message or subtitle
            subprocess.run(["notify-send", title, body], check=False)
        else:
            print(title)
            if subtitle:
                print(subtitle)
            if message:
                print(message)
    except Exception:
        pass


def console_greeting(uid, points):
    """Always print a terminal fallback greeting for scanned cards."""
    print("=== Badge scanned ===")
    print(f"Hello, user {uid}!")
    print(f"You have {points} points!")


def notify_greeting(uid, points):
    title = "Badge scanned"
    message = f"Hello, user {uid}!\nYou have {points} points"
    show_notification(title, "", message)
    console_greeting(uid, points)

def insert_badge(uid, atqa, sak, ats, historical_bytes):
    """Insert or update a badge record in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
    INSERT INTO badges (uid, atqa, sak, ats, historical_bytes, card_type_guess, created_at, last_seen)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(uid) DO UPDATE SET
        atqa=excluded.atqa,
        sak=excluded.sak,
        ats=excluded.ats,
        historical_bytes=excluded.historical_bytes,
        card_type_guess=excluded.card_type_guess,
        last_seen=excluded.last_seen
    """, (
        uid,
        atqa,
        sak,
        ats,
        historical_bytes,
        "ISO 14443-A contactless badge",
        now,
        now
    ))
    
    conn.commit()
    conn.close()

def main(timeout=0, show_leaderboard=False, leaderboard_limit=10):
    # Initialize database early so the leaderboard works before scanning.
    init_database()

    # Local live view of player UIDs (reflects `Database.players` keys).
    players = Database.players

    if show_leaderboard:
        print_leaderboard(limit=leaderboard_limit)
        return 0

    hcontext = pcsclite_backend.establish_context()
    
    try:
        readers = pcsclite_backend.list_readers(hcontext)

        if not readers:
            print("No smart card readers found.")
            return 1

        print("Readers found:")
        for r in readers:
            print(" -", r)

        reader = readers[0]
        print("\nUsing:", reader)

        while True:
            try:
                print("Waiting for card insertion... (press Ctrl-C to cancel)")
                if not pcsclite_backend.wait_for_card(hcontext, reader, timeout=timeout):
                    print(f"Timed out waiting for card after {timeout} seconds")
                    return 1

                hcard, active_protocol = pcsclite_backend.connect_with_retry(hcontext, reader)
                try:
                    reader_name = reader
                    protocol = active_protocol

                    for label, apdu_cmd in [
                        ("Get ATS", [0xFF, 0xCA, 0x01, 0x00, 0x00]),
                        ("Get Historical Bytes", [0xFF, 0xCA, 0x02, 0x00, 0x00]),
                        (
                            "Select NDEF App",
                            [
                                0x00, 0xA4, 0x04, 0x00,
                                0x07,
                                0xD2, 0x76, 0x00, 0x00,
                                0x85, 0x01, 0x01,
                            ],
                        ),
                    ]:
                        try:
                            pcsclite_backend.transmit_apdu(hcard, active_protocol, apdu_cmd, label)
                        except Exception as exc:
                            print(f"Warning: {label} failed, continuing: {exc}")

                    try:
                        reader_name, state, protocol, atr = pcsclite_backend.status(hcard)
                        print("ATR:", toHexString(atr))
                        print("Protocol:", protocol)
                    except Exception as exc:
                        print(f"Warning: card status failed, continuing with active protocol: {exc}")
                        protocol = active_protocol

                    apdu = [0xFF, 0xCA, 0x00, 0x00, 0x00]
                    try:
                        response = pcsclite_backend.transmit(hcard, protocol, apdu)
                    except Exception as exc:
                        print(f"Transient scan failed while reading badge UID: {exc}")
                        continue

                    print("APDU response:", toHexString(response))
                    # Faulty reads with UID/APDU value 63 00 should not be registered.
                    if is_faulty_read(response):
                        print("Faulty read detected (63 00). Skipping registration.")
                        continue

                    # Record the scan and greet the user
                    try:
                        uid_hex = toHexString(response)
                    except Exception:
                        uid_hex = str(response)
                    # Display the leaderboard
                    print_leaderboard(limit=leaderboard_limit)
                    print(f"Players: {list(Database.players)}")
                    # Determine whether this is the first time we see this badge.
                    is_new_badge = not badge_exists(uid_hex)
                    ensure_badge_exists(uid_hex)
                    if is_new_badge:
                        Database.newPlayer(uid_hex)

                    # Record the scan event
                    apdu_hex = toHexString(apdu)
                    response_hex = toHexString(response)
                    status_words = ""
                    rn = reader_name if 'reader_name' in locals() else reader
                    record_scan(uid_hex, apdu_hex, response_hex, status_words, rn)

                    # Fetch points and notify the user
                    points = get_points(uid_hex)
                    try:
                        notify_greeting(uid_hex, points)
                    except Exception:
                        print(f"Hello, user {uid_hex}!\nYou have {points} points!")

                finally:
                    pcsclite_backend.disconnect(hcard)

            except KeyboardInterrupt:
                print("Cancelled by user.")
                break
            except Exception as exc:
                print(f"Unexpected scan error, retrying: {exc}")
                continue

    finally:
        pcsclite_backend.release_context(hcontext)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for an NFC card and connect through PC/SC Lite.")
    parser.add_argument("--timeout", type=int, default=0, help="Timeout in seconds (0 = wait forever)")
    parser.add_argument("--leaderboard", action="store_true", help="Show the leaderboard and exit")
    parser.add_argument("--leaderboard-limit", type=int, default=10, help="Number of rows to show from the leaderboard")
    args = parser.parse_args()

    raise SystemExit(main(timeout=args.timeout, show_leaderboard=args.leaderboard, leaderboard_limit=args.leaderboard_limit))