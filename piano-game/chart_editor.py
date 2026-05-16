#!/usr/bin/env python3
"""
chart_editor.py  —  Visual Chart Editor for the Rhythm Game
============================================================
Run this on your Raspberry Pi (or laptop with pygame) to create charts.

Usage:
    python3 chart_editor.py MySong.mp3
    python3 chart_editor.py MySong.mp3 --bpm 128 --title "My Song" --artist "Artist"
    python3 chart_editor.py MySong.mp3 --load existing_chart.py  (load a pattern to edit)

Requirements:
    pip install pygame --break-system-packages

Controls:
    MOUSE
      Click          Place / remove a tap note
      Click + drag   Place a hold note (drag downward = longer hold)
      Right-click    Delete note under cursor

    PLAYBACK
      Space          Play / Pause
      R              Rewind to start

    NAVIGATION
      Scroll wheel   Scroll timeline up/down
      Home / End     Jump to start / end

    SNAP
      1              Snap to 4th notes  (1 beat)
      2              Snap to 8th notes  (1/2 beat)
      3              Snap to 16th notes (1/4 beat)
      4              Snap to 32nd notes (1/8 beat)  — free mode

    EDIT
      Ctrl+Z         Undo last action
      Delete         Clear all notes (with confirmation)

    EXPORT
      Ctrl+S         Export chart to  <songname>_chart.py
                     (ready to paste into charts.py)

Layout:
    Left panel  — 4 lane timeline (notes placed here)
    Right panel — controls, info, snap selector
"""

import pygame
import sys, os, math, time, argparse, re
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
SCREEN_W, SCREEN_H = 1000, 700
FPS = 60

TIMELINE_X  = 200          # x start of lane area
TIMELINE_W  = 560          # total width of 4 lanes
LANE_W      = TIMELINE_W // 4   # 140px per lane
PANEL_X     = TIMELINE_X + TIMELINE_W + 10  # right panel x
PANEL_W     = SCREEN_W - PANEL_X - 10

PLAYHEAD_Y  = SCREEN_H - 120   # fixed y position of playhead on screen
PX_PER_SEC  = 200              # pixels per second on timeline (zoom level)

# Colors
BG          = (12,  12,  18)
PANEL_BG    = (20,  20,  30)
LANE_BG     = (22,  22,  32)
LANE_ALT    = (26,  26,  38)
GRID_COL    = (40,  40,  60)
MEASURE_COL = (70,  70, 100)
BEAT_COL    = (45,  45,  68)
HALF_COL    = (35,  35,  52)
PLAYHEAD    = (255, 220,  50)
WHITE       = (255, 255, 255)
GRAY        = (140, 140, 160)
DARK_GRAY   = (60,  60,  80)

LANE_COLORS = [
    (0,   200, 255),   # cyan
    (0,   255, 160),   # mint
    (255, 200,   0),   # yellow
    (255,  80, 120),   # pink
]

HOLD_COLORS = [
    (0,   120, 180),
    (0,   160, 100),
    (180, 140,   0),
    (180,  50,  90),
]
SNAP_COLORS = {
    "4th":  (255, 80,  80),
    "8th":  (80,  160, 255),
    "16th": (80,  255, 160),
    "32nd": (200, 200, 200),
}

NOTE_H = 16   # pixel height of a tap note rect


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Note:
    time:     float          # beat time in seconds
    lane:     int            # 0-3
    hold_dur: float = 0.0    # 0 = tap, >0 = hold duration in seconds

    @property
    def is_hold(self):
        return self.hold_dur > 0.01

    def end_time(self):
        return self.time + self.hold_dur


# ═══════════════════════════════════════════════════════════════════════════════
#  EDITOR
# ═══════════════════════════════════════════════════════════════════════════════
class ChartEditor:
    def __init__(self, mp3_path: str, bpm: float, title: str, artist: str):
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption(f"Chart Editor — {title}")
        self.clock = pygame.time.Clock()

        # Fonts
        self.font_lg  = pygame.font.SysFont("monospace", 22, bold=True)
        self.font_md  = pygame.font.SysFont("monospace", 16, bold=True)
        self.font_sm  = pygame.font.SysFont("monospace", 13)
        self.font_xs  = pygame.font.SysFont("monospace", 11)

        # Song info
        self.mp3_path = mp3_path
        self.bpm      = bpm
        self.title    = title
        self.artist   = artist
        self.duration = 0.0

        # Load audio
        self.audio_loaded = False
        if mp3_path and os.path.exists(mp3_path):
            try:
                pygame.mixer.music.load(mp3_path)
                self.audio_loaded = True
                # Estimate duration via file size / bitrate (rough)
                size = os.path.getsize(mp3_path)
                self.duration = max(60.0, size / (128 * 1024 / 8))
            except Exception as e:
                print(f"[AUDIO] Could not load: {e}")
        else:
            self.duration = 120.0
            print("[AUDIO] No MP3 — editor will work without audio.")

        # Playback state
        self.playing      = False
        self.play_start_t = 0.0   # wall time when play started
        self.play_offset  = 0.0   # song position when play started (seconds)
        self.song_pos     = 0.0   # current song position (seconds)

        # Timeline scroll: scroll_sec = song time at the BOTTOM of the screen
        self.scroll_sec   = 0.0

        # Snap
        self.snap_modes   = ["4th", "8th", "16th", "32nd"]
        self.snap_idx     = 1    # default 8th notes
        self.snap_divs    = {"4th": 1, "8th": 2, "16th": 4, "32nd": 8}

        # Notes
        self.notes: list[Note] = []
        self.undo_stack: list[list[Note]] = []

        # Drag state
        self.drag_note:   Optional[Note] = None
        self.drag_lane:   int  = -1
        self.drag_start_t: float = 0.0
        self.drag_start_y: int  = 0

        # UI state
        self.hovered_lane  = -1
        self.hovered_time  = 0.0
        self.status_msg    = "Ready.  Click to place notes."
        self.status_timer  = 0.0
        self.confirm_clear = False

    # ── Coordinate helpers ────────────────────────────────────────────────────
    def sec_to_y(self, t: float) -> int:
        """Convert song time (sec) to screen Y. Later time = higher on screen."""
        return int(PLAYHEAD_Y - (t - self.scroll_sec) * PX_PER_SEC)

    def y_to_sec(self, y: int) -> float:
        return self.scroll_sec + (PLAYHEAD_Y - y) / PX_PER_SEC

    def x_to_lane(self, x: int) -> int:
        lane = (x - TIMELINE_X) // LANE_W
        return max(0, min(3, lane))

    def in_timeline(self, x: int, y: int) -> bool:
        return TIMELINE_X <= x < TIMELINE_X + TIMELINE_W and 0 <= y < SCREEN_H

    def snap_time(self, t: float) -> float:
        """Snap t to nearest grid line based on current snap mode."""
        beat   = 60.0 / self.bpm
        div    = self.snap_divs[self.snap_modes[self.snap_idx]]
        grid   = beat / div
        return round(t / grid) * grid

    # ── Playback ──────────────────────────────────────────────────────────────
    def play(self):
        if self.audio_loaded:
            pygame.mixer.music.play(start=self.song_pos)
        self.play_start_t = time.time()
        self.play_offset  = self.song_pos
        self.playing      = True

    def pause(self):
        if self.audio_loaded:
            pygame.mixer.music.pause()
        self.playing  = False
        # song_pos already updated in update()

    def rewind(self):
        was_playing = self.playing
        if self.playing:
            self.pause()
        self.song_pos  = 0.0
        self.scroll_sec = 0.0
        if was_playing:
            self.play()

    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    # ── Note editing ──────────────────────────────────────────────────────────
    def _save_undo(self):
        import copy
        self.undo_stack.append(copy.deepcopy(self.notes))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def note_at(self, t: float, lane: int) -> Optional[Note]:
        """Find a note close to time t in this lane."""
        beat  = 60.0 / self.bpm
        tol   = beat / (self.snap_divs[self.snap_modes[self.snap_idx]] * 2)
        tol   = max(tol, 0.02)
        for n in self.notes:
            if n.lane == lane and abs(n.time - t) <= tol:
                return n
            if n.is_hold and n.lane == lane and n.time - tol <= t <= n.end_time() + tol:
                return n
        return None

    def place_note(self, t: float, lane: int):
        self._save_undo()
        existing = self.note_at(t, lane)
        if existing:
            self.notes.remove(existing)
        else:
            self.notes.append(Note(time=t, lane=lane))
            self.notes.sort(key=lambda n: n.time)

    def delete_note_at(self, t: float, lane: int):
        n = self.note_at(t, lane)
        if n:
            self._save_undo()
            self.notes.remove(n)

    def undo(self):
        if self.undo_stack:
            self.notes = self.undo_stack.pop()
            self.set_status("Undo.")

    def set_status(self, msg: str):
        self.status_msg   = msg
        self.status_timer = 3.0

    # ── Export ────────────────────────────────────────────────────────────────
    def export(self):
        if not self.notes:
            self.set_status("Nothing to export!")
            return

        varname  = re.sub(r"[^a-zA-Z0-9 ]", "", self.title).strip()
        varname  = "_".join(varname.upper().split())
        filename = varname.lower() + "_chart.py"
        mp3name  = os.path.basename(self.mp3_path) if self.mp3_path else "song.mp3"

        pat_lines = "\n".join(
            f"        ({round(n.time,3)}, {n.lane}, {n.is_hold}, {round(n.hold_dur,3)}),"
            for n in sorted(self.notes, key=lambda n: n.time)
        )

        out = f'''# Auto-exported by chart_editor.py
# Paste this SongDef into charts.py and add {varname} to the SONGS list.

{varname} = SongDef(
    title      = "{self.title}",
    artist     = "{self.artist}",
    bpm        = {round(self.bpm)},
    audio_file = _audio("{mp3name}"),
    pattern    = [
{pat_lines}
    ],
)
'''
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path, "w") as f:
            f.write(out)
        self.set_status(f"Exported → {filename}  ({len(self.notes)} notes)")
        print(f"[EXPORT] {path}")

    # ── Update ────────────────────────────────────────────────────────────────
    def update(self, dt: float):
        if self.playing:
            self.song_pos = self.play_offset + (time.time() - self.play_start_t)
            if self.song_pos >= self.duration:
                self.pause()
                self.song_pos = self.duration
            # Auto-scroll: keep playhead visible
            screen_top_sec = self.scroll_sec + (PLAYHEAD_Y / PX_PER_SEC)
            if self.song_pos > screen_top_sec - 1.0:
                self.scroll_sec = self.song_pos - PLAYHEAD_Y / PX_PER_SEC + 1.0
            self.scroll_sec = max(0.0, self.scroll_sec)

        if self.status_timer > 0:
            self.status_timer -= dt

    # ── Draw ──────────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(BG)
        self._draw_timeline()
        self._draw_notes()
        self._draw_playhead()
        self._draw_drag_preview()
        self._draw_hover()
        self._draw_panel()
        if self.confirm_clear:
            self._draw_confirm()
        pygame.display.flip()

    def _draw_timeline(self):
        # Lane backgrounds
        for i in range(NUM_LANES := 4):
            lx  = TIMELINE_X + i * LANE_W
            col = LANE_BG if i % 2 == 0 else LANE_ALT
            pygame.draw.rect(self.screen, col, (lx, 0, LANE_W, SCREEN_H))
            # Lane separator
            pygame.draw.line(self.screen, GRID_COL, (lx, 0), (lx, SCREEN_H), 1)

        # Right edge
        pygame.draw.line(self.screen, GRID_COL,
                         (TIMELINE_X + TIMELINE_W, 0),
                         (TIMELINE_X + TIMELINE_W, SCREEN_H), 1)

        # Horizontal grid lines (measures, beats, subdivisions)
        beat     = 60.0 / self.bpm
        div      = self.snap_divs[self.snap_modes[self.snap_idx]]
        grid_inc = beat / div

        # Range of grid lines visible on screen
        screen_top_sec = self.y_to_sec(0)
        t = math.floor(self.scroll_sec / grid_inc) * grid_inc

        while t <= screen_top_sec + grid_inc:
            y = self.sec_to_y(t)
            if 0 <= y <= SCREEN_H:
                beat_num  = t / beat
                is_measure = abs(beat_num % 4) < 0.01
                is_beat    = abs(beat_num % 1) < 0.01
                is_half    = abs(beat_num % 0.5) < 0.01

                if is_measure:
                    col, w = MEASURE_COL, 2
                elif is_beat:
                    col, w = BEAT_COL, 1
                elif is_half:
                    col, w = HALF_COL, 1
                else:
                    col, w = GRID_COL, 1

                pygame.draw.line(self.screen, col,
                                 (TIMELINE_X, y),
                                 (TIMELINE_X + TIMELINE_W, y), w)

                # Measure label on left
                if is_measure:
                    measure_num = int(round(t / beat / 4)) + 1
                    lbl = self.font_xs.render(f"m{measure_num}", True, MEASURE_COL)
                    self.screen.blit(lbl, (TIMELINE_X - lbl.get_width() - 4, y - 7))

                # Time label
                mins = int(t // 60)
                secs = t % 60
                tl = self.font_xs.render(f"{mins}:{secs:05.2f}", True, DARK_GRAY)
                self.screen.blit(tl, (TIMELINE_X - tl.get_width() - 4, y + 2))

            t += grid_inc

        # Lane labels at bottom
        labels = ["LANE 1", "LANE 2", "LANE 3", "LANE 4"]
        for i in range(4):
            lx  = TIMELINE_X + i * LANE_W
            col = LANE_COLORS[i]
            lbl = self.font_xs.render(labels[i], True, col)
            self.screen.blit(lbl, (lx + LANE_W//2 - lbl.get_width()//2, SCREEN_H - 20))

    def _draw_notes(self):
        for note in self.notes:
            y = self.sec_to_y(note.time)
            x = TIMELINE_X + note.lane * LANE_W

            if note.is_hold:
                hold_px = int(note.hold_dur * PX_PER_SEC)
                tail_y  = y - hold_px   # tail is earlier (higher on screen = later time, lower y = earlier)
                # Trail
                tc = HOLD_COLORS[note.lane]
                trail_rect = pygame.Rect(x + LANE_W//2 - 12, tail_y, 24, hold_px + NOTE_H)
                pygame.draw.rect(self.screen, tc, trail_rect, border_radius=4)
                # Tail cap
                pygame.draw.rect(self.screen, LANE_COLORS[note.lane],
                                 pygame.Rect(x+4, tail_y, LANE_W-8, NOTE_H//2), border_radius=3)

            # Head
            col = LANE_COLORS[note.lane]
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(x+4, y - NOTE_H//2, LANE_W-8, NOTE_H),
                             border_radius=5)
            # Highlight
            pygame.draw.rect(self.screen, (255,255,255),
                             pygame.Rect(x+8, y - NOTE_H//2 + 2, LANE_W-16, 3),
                             border_radius=2)

    def _draw_playhead(self):
        # Glow
        glow = pygame.Surface((TIMELINE_W, 3), pygame.SRCALPHA)
        glow.fill((*PLAYHEAD, 60))
        self.screen.blit(glow, (TIMELINE_X, PLAYHEAD_Y - 1))
        # Line
        pygame.draw.line(self.screen, PLAYHEAD,
                         (TIMELINE_X, PLAYHEAD_Y),
                         (TIMELINE_X + TIMELINE_W, PLAYHEAD_Y), 2)
        # Triangle marker
        tx = TIMELINE_X - 2
        pygame.draw.polygon(self.screen, PLAYHEAD, [
            (tx, PLAYHEAD_Y - 7),
            (tx, PLAYHEAD_Y + 7),
            (tx - 12, PLAYHEAD_Y),
        ])
        # Time label
        mins  = int(self.song_pos // 60)
        secs  = self.song_pos % 60
        tl    = self.font_md.render(f"▶ {mins}:{secs:05.2f}", True, PLAYHEAD)
        self.screen.blit(tl, (TIMELINE_X + 4, PLAYHEAD_Y + 6))

    def _draw_drag_preview(self):
        if self.drag_note is None:
            return
        note = self.drag_note
        y    = self.sec_to_y(note.time)
        x    = TIMELINE_X + note.lane * LANE_W
        if note.is_hold:
            hold_px = int(note.hold_dur * PX_PER_SEC)
            tail_y  = y - hold_px
            s = pygame.Surface((24, hold_px + NOTE_H), pygame.SRCALPHA)
            s.fill((*HOLD_COLORS[note.lane], 160))
            self.screen.blit(s, (x + LANE_W//2 - 12, tail_y))
        s = pygame.Surface((LANE_W-8, NOTE_H), pygame.SRCALPHA)
        s.fill((*LANE_COLORS[note.lane], 200))
        self.screen.blit(s, (x+4, y - NOTE_H//2))

    def _draw_hover(self):
        if not self.in_timeline(*pygame.mouse.get_pos()):
            return
        mx, my = pygame.mouse.get_pos()
        lane   = self.x_to_lane(mx)
        t      = self.snap_time(self.y_to_sec(my))
        y      = self.sec_to_y(t)
        x      = TIMELINE_X + lane * LANE_W
        col    = LANE_COLORS[lane]
        s = pygame.Surface((LANE_W-8, NOTE_H), pygame.SRCALPHA)
        s.fill((*col, 80))
        self.screen.blit(s, (x+4, y - NOTE_H//2))

    def _draw_panel(self):
        pygame.draw.rect(self.screen, PANEL_BG,
                         pygame.Rect(PANEL_X-4, 0, PANEL_W+4, SCREEN_H))
        pygame.draw.line(self.screen, GRID_COL, (PANEL_X-4, 0), (PANEL_X-4, SCREEN_H), 1)

        y = 14
        def txt(s, col=WHITE, font=None, indent=0):
            nonlocal y
            f = font or self.font_md
            surf = f.render(s, True, col)
            self.screen.blit(surf, (PANEL_X + indent, y))
            y += surf.get_height() + 4

        txt("CHART EDITOR", WHITE, self.font_lg)
        y += 4
        txt(f"♪ {self.title}", LANE_COLORS[0])
        txt(f"  {self.artist}", GRAY, self.font_sm)
        txt(f"  {round(self.bpm)} BPM", GRAY, self.font_sm)
        y += 8

        # Playback
        txt("── PLAYBACK ──", DARK_GRAY, self.font_sm)
        state = "▐▐  PAUSED" if not self.playing else "▶  PLAYING"
        col   = PLAYHEAD if self.playing else GRAY
        txt(state, col)
        mins = int(self.song_pos // 60)
        secs = self.song_pos % 60
        dur_m = int(self.duration // 60)
        dur_s = self.duration % 60
        txt(f"  {mins}:{secs:05.2f} / {dur_m}:{dur_s:05.2f}", GRAY, self.font_sm)
        y += 6

        # Snap
        txt("── SNAP MODE ──", DARK_GRAY, self.font_sm)
        for i, mode in enumerate(self.snap_modes):
            col = SNAP_COLORS[mode] if i == self.snap_idx else DARK_GRAY
            key = str(i+1)
            txt(f"  [{key}] {mode} notes", col, self.font_sm)
        y += 6

        # Stats
        txt("── CHART INFO ──", DARK_GRAY, self.font_sm)
        txt(f"  Notes: {len(self.notes)}", WHITE, self.font_sm)
        holds = sum(1 for n in self.notes if n.is_hold)
        taps  = len(self.notes) - holds
        txt(f"  Taps:  {taps}   Holds: {holds}", GRAY, self.font_sm)
        txt(f"  Undo:  {len(self.undo_stack)} steps", GRAY, self.font_sm)
        y += 6

        # Controls reference
        txt("── CONTROLS ──", DARK_GRAY, self.font_sm)
        controls = [
            ("Space",   "Play / Pause"),
            ("R",       "Rewind"),
            ("Scroll",  "Scroll timeline"),
            ("Click",   "Place note"),
            ("Drag↓",   "Hold note"),
            ("R-click", "Delete note"),
            ("Ctrl+Z",  "Undo"),
            ("Ctrl+S",  "Export"),
            ("Del",     "Clear all"),
        ]
        for key, desc in controls:
            ks  = self.font_sm.render(f"  {key:<9}", True, LANE_COLORS[2])
            ds  = self.font_sm.render(desc, True, GRAY)
            self.screen.blit(ks, (PANEL_X, y))
            self.screen.blit(ds, (PANEL_X + ks.get_width(), y))
            y  += ks.get_height() + 3
        y += 6

        # Status
        if self.status_timer > 0:
            alpha = min(255, int(self.status_timer * 200))
            s = self.font_md.render(self.status_msg, True, PERFECT_COLOR := (0,255,160))
            s.set_alpha(alpha)
            self.screen.blit(s, (PANEL_X, SCREEN_H - 50))

        # Export button hint
        exp = self.font_sm.render("Ctrl+S  to export", True, DARK_GRAY)
        self.screen.blit(exp, (PANEL_X, SCREEN_H - 28))

    def _draw_confirm(self):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0,0,0,180))
        self.screen.blit(ov, (0,0))
        cx, cy = SCREEN_W//2, SCREEN_H//2
        box = pygame.Rect(cx-200, cy-60, 400, 120)
        pygame.draw.rect(self.screen, (30,30,40), box, border_radius=12)
        pygame.draw.rect(self.screen, (255,80,80), box, 2, border_radius=12)
        t1 = self.font_lg.render("Clear all notes?", True, WHITE)
        t2 = self.font_md.render("Enter = confirm    Esc = cancel", True, GRAY)
        self.screen.blit(t1, (cx - t1.get_width()//2, cy-44))
        self.screen.blit(t2, (cx - t2.get_width()//2, cy+10))

    # ── Events ────────────────────────────────────────────────────────────────
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()

            elif event.type == pygame.KEYDOWN:
                self._on_key(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self._on_lmb_down(event.pos)
                elif event.button == 3:
                    self._on_rmb(event.pos)
                elif event.button == 4:   # scroll up
                    self.scroll_sec = max(0.0, self.scroll_sec - (60/self.bpm)*0.5)
                elif event.button == 5:   # scroll down
                    self.scroll_sec += (60/self.bpm)*0.5

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self._on_lmb_up(event.pos)

            elif event.type == pygame.MOUSEMOTION:
                self._on_mouse_move(event.pos)

    def _on_key(self, event):
        mods = pygame.key.get_mods()
        k    = event.key

        if self.confirm_clear:
            if k == pygame.K_RETURN:
                self._save_undo()
                self.notes = []
                self.set_status("Cleared all notes.")
            self.confirm_clear = False
            return

        if k == pygame.K_SPACE:
            self.toggle_play()
        elif k == pygame.K_r:
            self.rewind()
        elif k == pygame.K_HOME:
            self.scroll_sec = 0.0; self.song_pos = 0.0
        elif k == pygame.K_END:
            self.scroll_sec = max(0, self.duration - PLAYHEAD_Y/PX_PER_SEC)
        elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
            self.snap_idx = k - pygame.K_1
        elif k == pygame.K_z and mods & pygame.KMOD_CTRL:
            self.undo()
        elif k == pygame.K_s and mods & pygame.KMOD_CTRL:
            self.export()
        elif k == pygame.K_DELETE:
            self.confirm_clear = True
        elif k == pygame.K_ESCAPE:
            self.confirm_clear = False

    def _on_lmb_down(self, pos):
        mx, my = pos
        if not self.in_timeline(mx, my):
            return
        t    = self.snap_time(self.y_to_sec(my))
        lane = self.x_to_lane(mx)
        self.drag_lane    = lane
        self.drag_start_t = t
        self.drag_start_y = my
        # Start a provisional note for drag preview
        self.drag_note = Note(time=t, lane=lane, hold_dur=0.0)

    def _on_lmb_up(self, pos):
        if self.drag_note is None:
            return
        mx, my = pos
        t      = self.snap_time(self.y_to_sec(my))
        lane   = self.drag_lane
        start  = self.drag_start_t

        # If dragged upward (earlier time on screen = lower y), it's a hold
        hold_dur = max(0.0, start - t)   # earlier start, drag to later time (lower y)
        # Actually: dragging DOWN on screen = later in time (lower y = later)
        # start_t is where we clicked, drag DOWN means my > drag_start_y
        if my > self.drag_start_y:
            t_end    = self.snap_time(self.y_to_sec(my))
            hold_dur = max(0.0, t_end - start)
            self._save_undo()
            existing = self.note_at(start, lane)
            if existing:
                self.notes.remove(existing)
            self.notes.append(Note(time=start, lane=lane, hold_dur=hold_dur))
        else:
            # Regular tap (or very small drag = tap)
            self.place_note(start, lane)

        self.notes.sort(key=lambda n: n.time)
        self.drag_note = None

    def _on_rmb(self, pos):
        mx, my = pos
        if not self.in_timeline(mx, my):
            return
        t    = self.snap_time(self.y_to_sec(my))
        lane = self.x_to_lane(mx)
        self.delete_note_at(t, lane)

    def _on_mouse_move(self, pos):
        mx, my = pos
        if self.drag_note is not None:
            # Update drag preview
            t_end    = self.snap_time(self.y_to_sec(my))
            hold_dur = max(0.0, t_end - self.drag_start_t)
            self.drag_note = Note(
                time     = self.drag_start_t,
                lane     = self.drag_lane,
                hold_dur = hold_dur if my > self.drag_start_y else 0.0
            )

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        print("Chart Editor started.")
        print("  Space=Play/Pause  R=Rewind  Ctrl+S=Export  Ctrl+Z=Undo")
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()

    def quit(self):
        pygame.quit()
        sys.exit()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Rhythm Game Chart Editor")
    parser.add_argument("mp3",              nargs="?", default=None,
                        help="Path to MP3 file (optional)")
    parser.add_argument("--bpm",    type=float, default=120.0, help="Song BPM")
    parser.add_argument("--title",  default=None,              help="Song title")
    parser.add_argument("--artist", default="Unknown",         help="Artist name")
    args = parser.parse_args()

    mp3    = os.path.abspath(args.mp3) if args.mp3 else None
    title  = args.title or (
        os.path.splitext(os.path.basename(args.mp3))[0].replace("_"," ")
        if args.mp3 else "Untitled"
    )

    editor = ChartEditor(
        mp3_path = mp3,
        bpm      = args.bpm,
        title    = title,
        artist   = args.artist,
    )
    editor.run()


if __name__ == "__main__":
    main()