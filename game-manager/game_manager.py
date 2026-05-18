#!/usr/bin/env python3
"""
Stasis Hackathon — Game Manager
Tkinter dashboard for NFC-badge-based game management.
"""

import tkinter as tk
import sqlite3
import threading
import queue
import time
import sys
import os
import subprocess
import uuid
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
PCSCLITE_DIR = os.path.abspath(os.path.join(ROOT, ".."))
sys.path.insert(0, PCSCLITE_DIR)

DB_PATH = os.path.join(PCSCLITE_DIR, "badge_scans.db")
PIANO_SCRIPT = os.path.join(PCSCLITE_DIR, "piano-game", "game.py")
DUCK_SCRIPT = os.path.join(ROOT, "..", "duck-hunt", "main.py")  # update if path differs

# ── NFC import (graceful fallback for dev without hardware) ────────────────────
try:
    import pcsclite_backend
    from smartcard.util import toHexString
    NFC_AVAILABLE = True
except ImportError:
    NFC_AVAILABLE = False

# ── Theme ──────────────────────────────────────────────────────────────────────
BG       = "#0d0d1a"
CARD_BG  = "#004191"
PANEL_BG = "#1a1a2e"
ACCENT   = "#e94560"
BLUE     = "#004191"
TEXT     = "#ffffff"
MUTED    = "#8888aa"
GREEN    = "#4caf50"
YELLOW   = "#f0c040"

F_TITLE   = ("Helvetica", 28, "bold")
F_HEAD    = ("Helvetica", 18, "bold")
F_SUBHEAD = ("Helvetica", 14, "bold")
F_BODY    = ("Helvetica", 13)
F_MUTED   = ("Helvetica", 11)
F_NUM     = ("Helvetica", 36, "bold")
F_BTN     = ("Helvetica", 14, "bold")
F_BTN_SM  = ("Helvetica", 12, "bold")

STARTING_POINTS = 1000

# ── Database ───────────────────────────────────────────────────────────────────

def _db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS badges (
                uid TEXT PRIMARY KEY,
                atqa TEXT, sak TEXT, ats TEXT, historical_bytes TEXT,
                card_type_guess TEXT, created_at TEXT, last_seen TEXT,
                points INTEGER DEFAULT 0, name TEXT
            )
        """)
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(badges)")]
        if "name" not in existing_cols:
            conn.execute("ALTER TABLE badges ADD COLUMN name TEXT")

def get_user(uid):
    """Return (name, points) tuple, or None if uid not in DB."""
    with _db() as conn:
        return conn.execute(
            "SELECT name, points FROM badges WHERE uid=?", (uid,)
        ).fetchone()

def create_user(uid, name):
    now = datetime.now().isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO badges (uid, created_at, last_seen, points, name) "
            "VALUES (?,?,?,?,?)",
            (uid, now, now, STARTING_POINTS, name),
        )
        conn.execute(
            "UPDATE badges SET name=?, last_seen=? WHERE uid=?", (name, now, uid)
        )

def refresh_points(uid):
    with _db() as conn:
        row = conn.execute("SELECT points FROM badges WHERE uid=?", (uid,)).fetchone()
    return row[0] if row else 0

def apply_points(uid, delta):
    with _db() as conn:
        conn.execute(
            "UPDATE badges SET points = MAX(0, points + ?) WHERE uid=?", (delta, uid)
        )

# ── NFC Scanner thread ─────────────────────────────────────────────────────────

class NFCScanner:
    def __init__(self, scan_queue):
        self.q = scan_queue
        self._stop = threading.Event()
        self._thread = None
        self.active = False

    def start(self):
        if self.active:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.active = True

    def stop(self):
        self._stop.set()
        self.active = False

    def _is_faulty(self, r):
        if isinstance(r, (bytes, bytearray)):
            return r == b"\x63\x00"
        if isinstance(r, list) and len(r) == 2:
            return r[0] == 0x63 and r[1] == 0x00
        return False

    def _loop(self):
        if not NFC_AVAILABLE:
            return
        try:
            ctx = pcsclite_backend.establish_context()
        except Exception as e:
            print(f"NFC context error: {e}")
            return
        try:
            while not self._stop.is_set():
                try:
                    readers = pcsclite_backend.list_readers(ctx)
                    if not readers:
                        time.sleep(1)
                        continue
                    reader = readers[0]
                    if not pcsclite_backend.wait_for_card(ctx, reader, timeout=1):
                        continue
                    if self._stop.is_set():
                        break
                    hcard, proto = pcsclite_backend.connect_with_retry(ctx, reader)
                    try:
                        resp = pcsclite_backend.transmit(
                            hcard, proto, [0xFF, 0xCA, 0x00, 0x00, 0x00]
                        )
                        if resp and not self._is_faulty(resp):
                            self.q.put(toHexString(resp))
                            time.sleep(1.5)  # debounce — prevent duplicate scans
                    finally:
                        pcsclite_backend.disconnect(hcard)
                except Exception:
                    time.sleep(0.5)
        finally:
            try:
                pcsclite_backend.release_context(ctx)
            except Exception:
                pass

# ── Widget helpers ─────────────────────────────────────────────────────────────

def _btn(parent, text, command, color=ACCENT, fg=TEXT, font=None, **kw):
    return tk.Button(
        parent, text=text, command=command,
        bg=color, fg=fg, font=font or F_BTN,
        relief="flat", cursor="hand2",
        padx=16, pady=9,
        activebackground=color, activeforeground=fg,
        **kw,
    )

def _lbl(parent, text, color=TEXT, bg=None, font=None, anchor="center", **kw):
    return tk.Label(
        parent, text=text, fg=color, bg=bg or PANEL_BG,
        font=font or F_BODY, anchor=anchor, **kw,
    )

def _card(parent, **kw):
    return tk.Frame(parent, bg=CARD_BG, bd=0, relief="flat", **kw)

# ── Main app ───────────────────────────────────────────────────────────────────

class GameManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Stasis Hackathon — Game Manager")
        self.configure(bg=PANEL_BG)
        self.geometry("960x620")
        self.resizable(False, False)

        # players[0] = P1, players[1] = P2 (or None)
        # each entry: {uid, name, points, bet, is_new}
        self.players = [None, None]
        self.selected_game = None
        self._scan_slot = None        # which slot we're waiting to fill
        self._game_proc = None

        self.scan_q = queue.Queue()
        self.nfc = NFCScanner(self.scan_q)

        self._build_header()
        self.body = tk.Frame(self, bg=PANEL_BG)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.after(200, self._poll_scanner)
        self.show_idle()

    # ── Header (always visible) ────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=BLUE, height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        _lbl(hdr, "STASIS HACKATHON", font=F_HEAD, bg=BLUE).pack(
            side=tk.LEFT, padx=18, pady=10
        )
        _lbl(hdr, "Game Manager", color=MUTED, font=F_BODY, bg=BLUE).pack(
            side=tk.LEFT, pady=10
        )

        self._scan_btn_text = tk.StringVar(value="Scanner: OFF  ○")
        self._scan_btn = tk.Button(
            hdr, textvariable=self._scan_btn_text,
            command=self._toggle_scanner,
            bg=MUTED, fg=TEXT, font=F_BTN_SM,
            relief="flat", cursor="hand2",
            padx=12, pady=6,
            activebackground=MUTED, activeforeground=TEXT,
        )
        self._scan_btn.pack(side=tk.RIGHT, padx=18, pady=10)

    def _toggle_scanner(self):
        if self.nfc.active:
            self.nfc.stop()
            self._scan_btn_text.set("Scanner: OFF  ○")
            self._scan_btn.config(bg=MUTED, activebackground=MUTED)
        else:
            self.nfc.start()
            self._scan_btn_text.set("Scanner: ON  ●")
            self._scan_btn.config(bg=GREEN, activebackground=GREEN)

    # ── Scanner polling ────────────────────────────────────────────────────────

    def _poll_scanner(self):
        try:
            uid = self.scan_q.get_nowait()
            if self._scan_slot is not None:
                self._handle_scan(uid)
        except queue.Empty:
            pass
        self.after(200, self._poll_scanner)

    def _handle_scan(self, uid):
        slot = self._scan_slot
        self._scan_slot = None
        row = get_user(uid)

        if row is None or row[0] is None:
            # New user — collect their name first
            self._new_uid = uid
            self._new_slot = slot
            self.show_name_entry(uid, slot)
        else:
            name, points = row
            self.players[slot] = {
                "uid": uid, "name": name, "points": points, "bet": 0, "is_new": False
            }
            if slot == 0:
                self.show_welcome()
            else:
                self.show_welcome_split()

    # ── Screen utilities ───────────────────────────────────────────────────────

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _center(self):
        """Return a frame centered in body."""
        f = tk.Frame(self.body, bg=PANEL_BG)
        f.place(relx=0.5, rely=0.5, anchor="center")
        return f

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Idle — waiting for P1 scan
    # ══════════════════════════════════════════════════════════════════════════

    def show_idle(self):
        self._clear()
        self.players = [None, None]
        self.selected_game = None
        self._scan_slot = 0

        f = self._center()
        _lbl(f, "GAME MANAGER", font=F_TITLE).pack(pady=(0, 4))
        _lbl(f, "Scan your badge to begin", color=MUTED, font=F_HEAD).pack(pady=(0, 28))
        _lbl(f, "◎", color=ACCENT, font=("Helvetica", 72)).pack(pady=(0, 28))

        if not NFC_AVAILABLE:
            _lbl(f, "NFC hardware not detected — using dev mode", color=YELLOW,
                 font=F_MUTED).pack(pady=(0, 10))
            _btn(f, "Simulate: New User",
                 lambda: self._handle_scan(uuid.uuid4().hex[:8].upper()),
                 color=BLUE).pack(pady=3)
            _btn(f, "Simulate: Returning User", lambda: self._handle_scan("11:22:33:44"),
                 color=BLUE).pack(pady=3)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Name entry — for a brand-new badge
    # ══════════════════════════════════════════════════════════════════════════

    def show_name_entry(self, uid, slot):
        self._clear()
        player_label = "Player 1" if slot == 0 else "Player 2"
        f = self._center()

        _lbl(f, f"Welcome, {player_label}!", font=F_TITLE).pack(pady=(0, 4))
        _lbl(f, f"Badge ID: {uid}", color=MUTED, font=F_MUTED).pack(pady=(0, 20))
        _lbl(f, "Enter your name:").pack()

        name_var = tk.StringVar()
        entry = tk.Entry(
            f, textvariable=name_var, font=F_HEAD,
            bg=CARD_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", width=22, justify="center",
        )
        entry.pack(pady=8, ipady=8)
        entry.focus_set()

        _lbl(f, f"You'll start with {STARTING_POINTS:,} points",
             color=YELLOW, font=F_BODY).pack(pady=(0, 20))

        def submit():
            name = name_var.get().strip()
            if not name:
                return
            create_user(uid, name)
            self.players[slot] = {
                "uid": uid, "name": name,
                "points": STARTING_POINTS, "bet": 0, "is_new": True,
            }
            if slot == 0:
                self.show_welcome()
            else:
                self.show_welcome_split()

        _btn(f, "Let's Play →", submit).pack(pady=4)
        entry.bind("<Return>", lambda _e: submit())

        if slot == 1:
            _btn(f, "← Cancel", self.show_welcome, color=MUTED,
                 font=F_BTN_SM).pack(pady=(8, 0))

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Welcome (single player, P1 only)
    # ══════════════════════════════════════════════════════════════════════════

    def show_welcome(self):
        self._clear()
        p = self.players[0]
        f = self._center()

        greeting = f"Welcome, {p['name']}!" if p['is_new'] else f"Welcome back, {p['name']}!"
        _lbl(f, greeting, font=F_TITLE).pack(pady=(0, 16))

        c = _card(f, width=320, height=150)
        c.pack(pady=(0, 20))
        c.pack_propagate(False)
        _lbl(c, f"{p['points']:,}", font=F_NUM, color=YELLOW, bg=CARD_BG).pack(pady=(18, 0))
        _lbl(c, "points", color=MUTED, bg=CARD_BG, font=F_BODY).pack()
        _lbl(c, f"UID: {p['uid']}", color=MUTED, bg=CARD_BG, font=F_MUTED).pack(pady=(4, 0))

        btn_row = tk.Frame(f, bg=PANEL_BG)
        btn_row.pack(pady=4)
        _btn(btn_row, "Add Player 2", self._start_p2_scan,
             color=BLUE).pack(side=tk.LEFT, padx=8)
        _btn(btn_row, "Continue →", self.show_game_select).pack(side=tk.LEFT, padx=8)

        _btn(f, "← Start Over", self.show_idle, color=MUTED,
             font=F_BTN_SM).pack(pady=(12, 0))

    def _start_p2_scan(self):
        self._clear()
        self._scan_slot = 1
        f = self._center()

        _lbl(f, "Scan Player 2's Badge", font=F_TITLE).pack(pady=(0, 8))
        _lbl(f, "◎", color=BLUE, font=("Helvetica", 72)).pack(pady=20)

        if not NFC_AVAILABLE:
            _btn(f, "Simulate P2: New User", lambda: self._handle_scan("FF:EE:DD:CC"),
                 color=BLUE).pack(pady=3)
            _btn(f, "Simulate P2: Returning", lambda: self._handle_scan("22:33:44:55"),
                 color=BLUE).pack(pady=3)

        _btn(f, "← Cancel", self.show_welcome, color=MUTED,
             font=F_BTN_SM).pack(pady=16)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Welcome Split (both players loaded)
    # ══════════════════════════════════════════════════════════════════════════

    def show_welcome_split(self):
        self._clear()

        top = tk.Frame(self.body, bg=PANEL_BG)
        top.pack(fill=tk.X, pady=(20, 0))
        _lbl(top, "Players Ready!", font=F_TITLE).pack()

        mid = tk.Frame(self.body, bg=PANEL_BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=40, pady=16)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)

        for i, p in enumerate(self.players):
            if p is None:
                continue
            col = tk.Frame(mid, bg=PANEL_BG)
            col.grid(row=0, column=i, sticky="nsew", padx=12)

            _lbl(col, f"Player {i + 1}", color=MUTED, font=F_SUBHEAD).pack(pady=(0, 4))
            _lbl(col, p["name"], font=F_HEAD).pack()

            c = _card(col)
            c.pack(fill=tk.X, pady=10)
            _lbl(c, f"{p['points']:,}", font=F_NUM, color=YELLOW, bg=CARD_BG).pack(pady=(14, 0))
            _lbl(c, "points", color=MUTED, bg=CARD_BG, font=F_BODY).pack()
            _lbl(c, f"UID: {p['uid']}", color=MUTED, bg=CARD_BG, font=F_MUTED).pack(pady=(4, 12))

            if p.get("is_new"):
                _lbl(col, "New player!", color=GREEN, font=F_MUTED).pack()

        bot = tk.Frame(self.body, bg=PANEL_BG)
        bot.pack(pady=10)
        _btn(bot, "Continue →", self.show_game_select).pack(side=tk.LEFT, padx=8)
        _btn(bot, "← Back", self.show_welcome, color=MUTED,
             font=F_BTN_SM).pack(side=tk.LEFT, padx=8)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Game Select
    # ══════════════════════════════════════════════════════════════════════════

    def show_game_select(self):
        self._clear()
        two_player = self.players[1] is not None
        f = self._center()

        _lbl(f, "Select a Game", font=F_TITLE).pack(pady=(0, 24))

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack()

        self._make_game_card(
            row, "Piano Battle", "🎹", "2 Players",
            enabled=two_player,
            disabled_hint="Need 2 players",
            on_select=lambda: self._pick_game("piano"),
        ).pack(side=tk.LEFT, padx=14)

        self._make_game_card(
            row, "Duck Hunt", "🦆", "1 Player",
            enabled=True,
            on_select=lambda: self._pick_game("duck_hunt"),
        ).pack(side=tk.LEFT, padx=14)

        def go_back():
            if two_player:
                self.show_welcome_split()
            else:
                self.show_welcome()

        _btn(f, "← Back", go_back, color=MUTED, font=F_BTN_SM).pack(pady=20)

    def _make_game_card(self, parent, title, emoji, players_text,
                        enabled, on_select, disabled_hint=""):
        c = _card(parent, width=220, height=210)
        c.pack_propagate(False)
        _lbl(c, emoji, font=("Helvetica", 48), bg=CARD_BG).pack(pady=(16, 4))
        _lbl(c, title, font=F_SUBHEAD, bg=CARD_BG).pack()
        _lbl(c, players_text, color=MUTED, bg=CARD_BG, font=F_MUTED).pack(pady=2)

        if enabled:
            tk.Button(
                c, text="Select", command=on_select,
                bg=ACCENT, fg=TEXT, font=F_BTN_SM,
                relief="flat", cursor="hand2", padx=12, pady=6,
                activebackground=ACCENT, activeforeground=TEXT,
            ).pack(pady=10)
        else:
            _lbl(c, disabled_hint, color=ACCENT, bg=CARD_BG, font=F_MUTED).pack(pady=(6, 0))
            tk.Button(
                c, text="Select", state=tk.DISABLED,
                bg=MUTED, fg=TEXT, font=F_BTN_SM,
                relief="flat", padx=12, pady=6,
                disabledforeground=TEXT,
            ).pack(pady=4)
        return c

    def _pick_game(self, game):
        self.selected_game = game
        self.show_bet()

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Bet
    # ══════════════════════════════════════════════════════════════════════════

    def show_bet(self):
        self._clear()
        f = self._center()

        game_name = "Piano Battle 🎹" if self.selected_game == "piano" else "Duck Hunt 🦆"
        _lbl(f, "Place Your Bets", font=F_TITLE).pack(pady=(0, 4))
        _lbl(f, game_name, color=ACCENT, font=F_SUBHEAD).pack(pady=(0, 20))

        self._bet_vars = []
        slots_row = tk.Frame(f, bg=PANEL_BG)
        slots_row.pack()

        for i, p in enumerate(self.players):
            if p is None:
                continue
            col = tk.Frame(slots_row, bg=PANEL_BG)
            col.pack(side=tk.LEFT, padx=24)

            _lbl(col, p["name"], font=F_SUBHEAD).pack()
            _lbl(col, f"Balance: {p['points']:,} pts", color=YELLOW, font=F_BODY).pack(pady=2)
            _lbl(col, "Bet (0 – max):", font=F_MUTED, color=MUTED).pack(pady=(12, 2))

            var = tk.IntVar(value=0)
            self._bet_vars.append((i, var))

            max_pts = max(p["points"], 1)

            tk.Scale(
                col, from_=0, to=max_pts,
                orient=tk.HORIZONTAL, variable=var, length=220,
                bg=PANEL_BG, fg=TEXT, troughcolor=CARD_BG,
                highlightthickness=0, sliderlength=22,
                activebackground=ACCENT,
            ).pack()

            # Custom value entry — synced with the slider
            entry_var = tk.StringVar(value="0")
            entry = tk.Entry(
                col, textvariable=entry_var, font=F_BODY,
                bg=CARD_BG, fg=TEXT, insertbackground=TEXT,
                relief="flat", width=10, justify="center",
            )
            entry.pack(pady=(4, 0), ipady=5)

            def _make_sync(sv, iv, mp):
                def slider_to_entry(*_):
                    sv.set(str(iv.get()))
                def entry_to_slider(*_):
                    try:
                        v = max(0, min(int(sv.get()), mp))
                        iv.set(v)
                    except ValueError:
                        pass
                return slider_to_entry, entry_to_slider

            s2e, e2s = _make_sync(entry_var, var, max_pts)
            var.trace_add("write", s2e)
            entry_var.trace_add("write", e2s)

        _btn(f, "Launch Game →", self._launch_game).pack(pady=20)
        _btn(f, "← Back", self.show_game_select, color=MUTED,
             font=F_BTN_SM).pack(pady=2)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Launching game
    # ══════════════════════════════════════════════════════════════════════════

    def _launch_game(self):
        for i, var in self._bet_vars:
            self.players[i]["bet"] = var.get()

        self._clear()
        f = self._center()
        game_name = "Piano Battle 🎹" if self.selected_game == "piano" else "Duck Hunt 🦆"
        _lbl(f, "Game in Progress", font=F_TITLE).pack(pady=(0, 8))
        _lbl(f, game_name, color=ACCENT, font=F_HEAD).pack(pady=(0, 24))
        _lbl(f, "◎", color=GREEN, font=("Helvetica", 56)).pack(pady=(0, 24))

        script = PIANO_SCRIPT if self.selected_game == "piano" else DUCK_SCRIPT
        self._game_proc = None

        if os.path.exists(script):
            try:
                self._game_proc = subprocess.Popen([sys.executable, script])
                self.after(1000, self._watch_game)
            except Exception as e:
                _lbl(f, f"Error launching: {e}", color=ACCENT, font=F_MUTED).pack()
        else:
            _lbl(f, f"Script not found:\n{script}", color=YELLOW, font=F_MUTED).pack()

        _btn(f, "Record Outcome →", self.show_outcome, color=GREEN).pack(pady=16)

    def _watch_game(self):
        if self._game_proc and self._game_proc.poll() is not None:
            self.show_outcome()
        else:
            self.after(1000, self._watch_game)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Outcome selection
    # ══════════════════════════════════════════════════════════════════════════

    def show_outcome(self):
        self._clear()
        if self._game_proc:
            try:
                self._game_proc.terminate()
            except Exception:
                pass

        p1 = self.players[0]
        p2 = self.players[1]

        top = tk.Frame(self.body, bg=PANEL_BG)
        top.pack(pady=(20, 8))
        _lbl(top, "Game Over!", font=F_TITLE).pack()
        _lbl(top, "Select the outcome:", color=MUTED, font=F_HEAD).pack()

        if p2:
            # ── Piano: two-column layout ───────────────────────────────────
            cols_frame = tk.Frame(self.body, bg=PANEL_BG)
            cols_frame.pack(fill=tk.BOTH, expand=True, padx=50, pady=10)
            cols_frame.columnconfigure(0, weight=1)
            cols_frame.columnconfigure(1, weight=1)

            for idx, (p, other) in enumerate([(p1, p2), (p2, p1)]):
                col = tk.Frame(cols_frame, bg=PANEL_BG)
                col.grid(row=0, column=idx, sticky="n", padx=16)

                _lbl(col, p["name"], font=F_HEAD).pack(pady=(0, 4))
                _lbl(col, f"Bet: {p['bet']:,} pts", color=MUTED, font=F_MUTED).pack(pady=(0, 12))

                win_delta  = other["bet"]
                lose_delta = p["bet"]

                _btn(col,
                     f"win   +{win_delta:,} points",
                     lambda i=idx: self._apply_outcome(i),
                     color=GREEN, font=F_BTN_SM).pack(fill=tk.X, pady=4)
                _btn(col,
                     "draw   +0 points",
                     lambda: self._apply_outcome("draw"),
                     color=YELLOW, fg="#000000", font=F_BTN_SM).pack(fill=tk.X, pady=4)
                _btn(col,
                     f"lose   -{lose_delta:,} points",
                     lambda i=1 - idx: self._apply_outcome(i),
                     color=ACCENT, font=F_BTN_SM).pack(fill=tk.X, pady=4)
        else:
            # ── Duck Hunt: single-column layout ───────────────────────────
            f = tk.Frame(self.body, bg=PANEL_BG)
            f.pack(expand=True)

            _lbl(f, p1["name"], font=F_HEAD).pack(pady=(10, 4))
            _lbl(f, f"Bet: {p1['bet']:,} pts", color=MUTED, font=F_MUTED).pack(pady=(0, 16))

            bet = p1["bet"]

            _btn(f, f"win   +{bet:,} points",
                 lambda: self._apply_outcome(0),
                 color=GREEN, font=F_BTN_SM).pack(fill=tk.X, padx=60, pady=5)
            _btn(f, "draw   +0 points",
                 lambda: self._apply_outcome("draw"),
                 color=YELLOW, fg="#000000", font=F_BTN_SM).pack(fill=tk.X, padx=60, pady=5)
            _btn(f, f"lose   -{bet:,} points",
                 lambda: self._apply_outcome("lose"),
                 color=ACCENT, font=F_BTN_SM).pack(fill=tk.X, padx=60, pady=5)

    def _apply_outcome(self, result):
        p1 = self.players[0]
        p2 = self.players[1]

        if result == "draw" or result is None:
            pass  # bets returned — no change
        elif result == "lose":
            # Duck hunt single-player loss
            apply_points(p1["uid"], -p1["bet"])
        elif result == 0:
            if p2:
                # Piano: P1 wins P2's bet
                apply_points(p1["uid"], p2["bet"])
                apply_points(p2["uid"], -p2["bet"])
            else:
                # Duck hunt single-player win
                apply_points(p1["uid"], p1["bet"])
        elif result == 1 and p2:
            # Piano: P2 wins P1's bet
            apply_points(p2["uid"], p1["bet"])
            apply_points(p1["uid"], -p1["bet"])

        self._show_summary(result)

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN: Summary after outcome applied
    # ══════════════════════════════════════════════════════════════════════════

    def _show_summary(self, result):
        self._clear()
        f = self._center()

        if result is None or result == "draw":
            headline, color = "Draw — bets returned", YELLOW
        elif result == "lose":
            headline, color = f"{self.players[0]['name']} lost", ACCENT
        else:
            headline, color = f"{self.players[result]['name']} wins!", GREEN

        _lbl(f, headline, font=F_TITLE, color=color).pack(pady=(0, 20))

        for p in self.players:
            if p is None:
                continue
            new_pts = refresh_points(p["uid"])
            delta = new_pts - p["points"]
            delta_str = f"+{delta}" if delta > 0 else str(delta)
            delta_color = GREEN if delta > 0 else (ACCENT if delta < 0 else MUTED)

            c = _card(f)
            c.pack(fill=tk.X, pady=6, padx=30)
            row = tk.Frame(c, bg=CARD_BG)
            row.pack(fill=tk.X, pady=10, padx=16)
            _lbl(row, p["name"], font=F_SUBHEAD, bg=CARD_BG).pack(side=tk.LEFT)
            _lbl(row, f"{new_pts:,} pts", font=F_SUBHEAD, color=YELLOW, bg=CARD_BG).pack(
                side=tk.RIGHT
            )
            if delta != 0:
                _lbl(row, f"  ({delta_str})", color=delta_color, bg=CARD_BG,
                     font=F_BODY).pack(side=tk.RIGHT)

        _btn(f, "New Game →", self.show_idle).pack(pady=24)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app = GameManager()
    app.mainloop()
