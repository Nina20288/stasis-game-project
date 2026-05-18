#!/usr/bin/env python3
"""
chart_editor.py  v2  —  Visual Chart Editor for the Rhythm Game
================================================================
Run:
    python3 chart_editor.py                     # startup screen
    python3 chart_editor.py song.mp3            # open with audio
    python3 chart_editor.py song.mp3 --load existing_chart.py

Requirements:
    pip install pygame --break-system-packages

Controls (in editor):
    MOUSE
      Click              Place tap note (click again to remove)
      Click + drag down  Place hold note — drag further = longer hold
      Right-click        Delete note

    PLAYBACK
      Space              Play / Pause
      R                  Rewind to start

    NAVIGATION
      Scroll wheel       Scroll timeline
      Home / End         Jump to start / end

    SNAP  (keys 1-4)
      1  4th notes   2  8th notes   3  16th notes   4  32nd notes

    EDIT
      Ctrl+Z   Undo        Ctrl+Y   Redo
      Delete   Clear all (with confirmation)

    BPM
      [ / ]    BPM -1 / +1     { / }   BPM -5 / +5

    EXPORT
      Ctrl+S   Export to <title>_chart.py
"""

import pygame
import sys, os, math, time, argparse, re, copy
from dataclasses import dataclass
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
SCREEN_W, SCREEN_H = 1060, 720
FPS         = 60
TIMELINE_X  = 210
TIMELINE_W  = 560
LANE_W      = TIMELINE_W // 4
PANEL_X     = TIMELINE_X + TIMELINE_W + 14
PANEL_W     = SCREEN_W - PANEL_X - 10
PLAYHEAD_Y  = SCREEN_H - 110
PX_PER_SEC  = 200
NOTE_H      = 16
DRAG_THRESHOLD = 6   # pixels before a click becomes a drag

# ══════════════════════════════════════════════════════════════════════════════
#  COLORS
# ══════════════════════════════════════════════════════════════════════════════
BG           = (10,  10,  16)
PANEL_BG     = (16,  16,  26)
LANE_EVEN    = (20,  20,  30)
LANE_ODD     = (24,  24,  36)
GRID_LINE    = (38,  38,  58)
MEASURE_LINE = (75,  75, 110)
BEAT_LINE    = (48,  48,  72)
HALF_LINE    = (36,  36,  54)
PLAYHEAD_C   = (255, 220,  50)
WHITE        = (255, 255, 255)
OFF_WHITE    = (220, 220, 235)
GRAY         = (160, 160, 180)
MID_GRAY     = (100, 100, 120)
DARK_GRAY    = (55,  55,  75)
ACCENT       = (100, 180, 255)
GREEN        = (80,  220, 140)
RED          = (255,  70,  70)

LANE_COLORS  = [(0,200,255), (0,255,160), (255,200,0), (255,80,120)]
HOLD_COLORS  = [(0,120,180), (0,160,100), (180,140,0), (180,50,90)]
SNAP_COLORS  = {"4th":(255,80,80), "8th":(80,160,255), "16th":(80,255,160), "32nd":(200,200,200)}


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Note:
    time:     float
    lane:     int
    hold_dur: float = 0.0

    @property
    def is_hold(self): return self.hold_dur > 0.02

    def end_time(self): return self.time + self.hold_dur


# ══════════════════════════════════════════════════════════════════════════════
#  FONT HELPER  — consistent readable fonts throughout
# ══════════════════════════════════════════════════════════════════════════════
class Fonts:
    def __init__(self):
        # All bold for consistency — no thin/light variants
        self.xl  = pygame.font.SysFont("monospace", 26, bold=True)
        self.lg  = pygame.font.SysFont("monospace", 20, bold=True)
        self.md  = pygame.font.SysFont("monospace", 15, bold=True)
        self.sm  = pygame.font.SysFont("monospace", 13, bold=True)
        self.xs  = pygame.font.SysFont("monospace", 11, bold=True)

    def render(self, font, text, color):
        return font.render(text, True, color)


# ══════════════════════════════════════════════════════════════════════════════
#  TEXT INPUT WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class TextInput:
    def __init__(self, value="", max_len=40):
        self.value   = value
        self.max_len = max_len
        self.active  = False
        self.cursor  = len(value)

    def handle_key(self, event):
        if not self.active:
            return
        if event.key == pygame.K_BACKSPACE:
            if self.cursor > 0:
                self.value  = self.value[:self.cursor-1] + self.value[self.cursor:]
                self.cursor -= 1
        elif event.key == pygame.K_DELETE:
            self.value = self.value[:self.cursor] + self.value[self.cursor+1:]
        elif event.key == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif event.key == pygame.K_RIGHT:
            self.cursor = min(len(self.value), self.cursor + 1)
        elif event.key == pygame.K_HOME:
            self.cursor = 0
        elif event.key == pygame.K_END:
            self.cursor = len(self.value)
        elif event.unicode and len(self.value) < self.max_len:
            self.value  = self.value[:self.cursor] + event.unicode + self.value[self.cursor:]
            self.cursor += 1

    def draw(self, surface, font, rect, label="", label_color=GRAY):
        # Background
        border_col = ACCENT if self.active else DARK_GRAY
        pygame.draw.rect(surface, (25, 25, 38), rect, border_radius=5)
        pygame.draw.rect(surface, border_col, rect, 1, border_radius=5)

        # Label
        if label:
            ls = font.render(label, True, label_color)
            surface.blit(ls, (rect.x, rect.y - ls.get_height() - 3))

        # Text + cursor
        disp = self.value
        ts   = font.render(disp, True, WHITE)
        tx   = rect.x + 6
        ty   = rect.y + (rect.h - ts.get_height()) // 2
        surface.blit(ts, (tx, ty))

        if self.active and int(time.time() * 2) % 2 == 0:
            cx  = tx + font.size(disp[:self.cursor])[0]
            pygame.draw.line(surface, WHITE, (cx, ty+2), (cx, ty+ts.get_height()-2), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP SCREEN
# ══════════════════════════════════════════════════════════════════════════════
class StartupScreen:
    """
    New Chart mode   : Title, Artist, BPM, MP3 path, Save chart as (filename)
    Edit Existing    : Song dropdown (from charts/*.json), Artist, BPM, MP3 path,
                       Load chart file (.json/.py)
    """

    # Try to read song list from chart JSON files in charts/
    @staticmethod
    def _read_songs_from_charts():
        """Return list of dicts {title, artist, bpm, filename} from charts/*.json."""
        songs = []
        try:
            from loader import discover_charts
            import json
            charts = discover_charts()
            entries = []
            for cid, path in sorted(charts.items(), key=lambda item: item[1].name):
                try:
                    raw = json.loads(path.read_text(encoding='utf-8'))
                    title = raw.get('title', 'Untitled')
                    artist = raw.get('artist', 'Unknown')
                    bpm = int(raw.get('bpm', 120))
                    entries.append({
                        "title": title,
                        "artist": artist,
                        "bpm": bpm,
                        "filename": path.name,
                        "audio_file": raw.get('audio_file', ''),
                    })
                except Exception:
                    continue
            counts = {}
            for entry in entries:
                counts[entry["title"]] = counts.get(entry["title"], 0) + 1
            for entry in entries:
                entry["display"] = (
                    f"{entry['title']} ({entry['filename']})"
                    if counts[entry['title']] > 1 else entry['title']
                )
                songs.append(entry)
        except Exception as e:
            print(f"[STARTUP] Could not read charts: {e}")
        return songs

    def __init__(self, screen, fonts: Fonts, initial_mp3=None):
        self.screen = screen
        self.F      = fonts
        self.done   = False
        self.result = None

        self.mode = "new"   # "new" or "edit"

        # ── NEW CHART fields ──────────────────────────────────────────────────
        self.new_title   = TextInput(
            os.path.splitext(os.path.basename(initial_mp3))[0].replace("_"," ")
            if initial_mp3 else "", 40
        )
        self.new_artist  = TextInput("Unknown", 40)
        self.new_bpm     = TextInput("120", 6)
        self.new_mp3     = TextInput(initial_mp3 or "", 80)
        self.new_saveas  = TextInput("my_song_chart.py", 60)
        self.new_inputs  = [self.new_title, self.new_artist, self.new_bpm,
                            self.new_mp3,   self.new_saveas]

        # ── EDIT EXISTING fields ──────────────────────────────────────────────
        self.songs          = self._read_songs_from_charts()
        self.dropdown_open  = False
        self.dropdown_hover = -1
        self.song_idx       = 0          # selected index in self.songs

        selected_title = self.songs[self.song_idx]["title"] if self.songs else "Untitled"
        self.edit_title  = TextInput(selected_title, 40)
        self.edit_artist = TextInput("Unknown", 40)
        self.edit_bpm    = TextInput("120", 6)
        self.edit_mp3    = TextInput(initial_mp3 or "", 80)
        self.edit_load   = TextInput("", 80)
        self.edit_inputs = [self.edit_title, self.edit_artist, self.edit_bpm,
                            self.edit_mp3,    self.edit_load]

        # Active input tracking (separate per mode)
        self.new_active  = 0
        self.edit_active = 0
        self._activate_new(0)

        self.error_msg = ""

    # ── Activation helpers ────────────────────────────────────────────────────
    def _activate_new(self, idx):
        for i, inp in enumerate(self.new_inputs):
            inp.active = (i == idx)
        self.new_active = idx

    def _activate_edit(self, idx):
        for i, inp in enumerate(self.edit_inputs):
            inp.active = (i == idx)
        self.edit_active = idx

    def _tab(self):
        if self.mode == "new":
            self._activate_new((self.new_active + 1) % len(self.new_inputs))
        else:
            self._activate_edit((self.edit_active + 1) % len(self.edit_inputs))

    def _current_inputs(self):
        return self.new_inputs if self.mode == "new" else self.edit_inputs

    def _active_input(self):
        return (self.new_inputs[self.new_active] if self.mode == "new"
                else self.edit_inputs[self.edit_active])

    # ── Song dropdown helpers ─────────────────────────────────────────────────
    def _dropdown_rect(self):
        cx = SCREEN_W // 2
        return pygame.Rect(cx - 220, 210, 440, 34)

    def _dropdown_list_rect(self):
        r   = self._dropdown_rect()
        cnt = min(len(self.songs), 6)
        return pygame.Rect(r.x, r.bottom + 2, r.w, cnt * 34)

    def _select_song(self, idx):
        if 0 <= idx < len(self.songs):
            self.song_idx = idx
            s = self.songs[idx]
            self.edit_title.value  = s["title"]
            self.edit_artist.value = s["artist"]
            self.edit_bpm.value    = str(s["bpm"])
            self.edit_mp3.value    = os.path.basename(s.get("audio_file", ""))
            self.edit_load.value   = os.path.join("charts", s["filename"])
        self.dropdown_open = False

    def _set_mode(self, mode):
        self.mode      = mode
        self.error_msg = ""
        self.dropdown_open = False
        if mode == "new":
            self._activate_new(0)
        else:
            self._activate_edit(0)
            if self.songs:
                self._select_song(self.song_idx)

    # ── Event handling ────────────────────────────────────────────────────────
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            elif event.type == pygame.KEYDOWN:
                k = event.key
                if k == pygame.K_ESCAPE:
                    if self.dropdown_open:
                        self.dropdown_open = False
                    else:
                        pygame.quit(); sys.exit()
                elif k == pygame.K_TAB:
                    self._tab()
                elif k == pygame.K_RETURN:
                    if self.dropdown_open:
                        self._select_song(
                            self.song_idx if self.dropdown_hover < 0 else self.dropdown_hover
                        )
                    else:
                        self._submit()
                elif k in (pygame.K_UP, pygame.K_DOWN) and self.mode == "edit":
                    if self.songs:
                        delta = -1 if k == pygame.K_UP else 1
                        self._select_song((self.song_idx + delta) % len(self.songs))
                else:
                    self._active_input().handle_key(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                self._on_click(mx, my)

            elif event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                if self.dropdown_open:
                    dlr = self._dropdown_list_rect()
                    if dlr.collidepoint(mx, my):
                        self.dropdown_hover = (my - dlr.y) // 34
                    else:
                        self.dropdown_hover = -1

    def _on_click(self, mx, my):
        # Mode buttons
        cx = SCREEN_W // 2
        nb = pygame.Rect(cx - 210, 110, 190, 42)
        eb = pygame.Rect(cx + 20,  110, 190, 42)
        if nb.collidepoint(mx, my): self._set_mode("new");  return
        if eb.collidepoint(mx, my): self._set_mode("edit"); return

        # Submit button
        sb = pygame.Rect(cx - 120, SCREEN_H - 80, 240, 46)
        if sb.collidepoint(mx, my): self._submit(); return

        if self.mode == "new":
            for i, r in enumerate(self._new_field_rects()):
                if r.collidepoint(mx, my):
                    self._activate_new(i); return

        elif self.mode == "edit":
            # Dropdown toggle
            dr = self._dropdown_rect()
            if dr.collidepoint(mx, my):
                self.dropdown_open = not self.dropdown_open
                return

            # Dropdown item click
            if self.dropdown_open:
                dlr = self._dropdown_list_rect()
                if dlr.collidepoint(mx, my):
                    idx = (my - dlr.y) // 34
                    self._select_song(idx); return
                else:
                    self.dropdown_open = False

            # Edit text fields (artist, bpm, mp3, load)
            for i, r in enumerate(self._edit_field_rects()):
                if r.collidepoint(mx, my):
                    self._activate_edit(i); return

    # ── Field rects ───────────────────────────────────────────────────────────
    def _new_field_rects(self):
        cx = SCREEN_W // 2
        return [
            pygame.Rect(cx-220, 210, 440, 34),   # title
            pygame.Rect(cx-220, 285, 440, 34),   # artist
            pygame.Rect(cx-220, 360, 200, 34),   # bpm
            pygame.Rect(cx-220, 435, 440, 34),   # mp3
            pygame.Rect(cx-220, 510, 440, 34),   # save as
        ]

    def _edit_field_rects(self):
        # dropdown occupies row 0 (210), then:
        cx = SCREEN_W // 2
        return [
            pygame.Rect(cx-220, 285, 440, 34),   # title
            pygame.Rect(cx-220, 360, 440, 34),   # artist
            pygame.Rect(cx-220, 435, 200, 34),   # bpm
            pygame.Rect(cx-220, 510, 440, 34),   # mp3
            pygame.Rect(cx-220, 585, 440, 34),   # load chart
        ]

    # ── Submit ────────────────────────────────────────────────────────────────
    def _resolve_mp3(self, raw):
        """Return an absolute path to the MP3, checking charts/ if bare filename."""
        if not raw:
            return None
        if os.path.exists(raw):
            return raw
        charts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", raw)
        if os.path.exists(charts_path):
            return charts_path
        return None

    def _submit(self):
        self.error_msg = ""

        if self.mode == "new":
            title   = self.new_title.value.strip()  or "Untitled"
            artist  = self.new_artist.value.strip()  or "Unknown"
            mp3_raw = self.new_mp3.value.strip()
            saveas  = self.new_saveas.value.strip()  or "my_song_chart.py"
            try:
                bpm = float(self.new_bpm.value.strip())
                assert 20 <= bpm <= 400
            except:
                self.error_msg = "BPM must be a number between 20 and 400."; return
            mp3 = self._resolve_mp3(mp3_raw)
            if mp3_raw and not mp3:
                self.error_msg = f"MP3 not found: {mp3_raw}"; return
            self.result = dict(mp3=mp3, bpm=bpm, title=title, artist=artist,
                               notes=[], saveas=saveas)

        else:  # edit
            title   = self.edit_title.value.strip() or "Untitled"
            artist  = self.edit_artist.value.strip()  or "Unknown"
            mp3_raw = self.edit_mp3.value.strip()
            load    = self.edit_load.value.strip()     or None
            try:
                bpm = float(self.edit_bpm.value.strip())
                assert 20 <= bpm <= 400
            except:
                self.error_msg = "BPM must be a number between 20 and 400."; return
            mp3 = self._resolve_mp3(mp3_raw)
            if mp3_raw and not mp3:
                self.error_msg = f"MP3 not found: {mp3_raw}"; return
            notes = []
            source = load if load and load.lower().endswith(".json") else None
            if load:
                if not os.path.exists(load):
                    self.error_msg = f"Chart file not found: {load}"; return
                notes = self._load_chart(load)
                if notes is None:
                    self.error_msg = "Could not parse chart file."; return
            self.result = dict(mp3=mp3, bpm=bpm, title=title, artist=artist,
                               notes=notes, saveas=None, source=source)

        self.done = True

    def _load_chart(self, path):
        try:
            if path.lower().endswith('.json'):
                import json
                raw = json.loads(open(path, encoding='utf-8').read())
                notes = []
                for n in raw.get('notes', []):
                    t = float(n.get('time_ms', 0)) / 1000.0
                    lane = int(n.get('lane', 0))
                    if n.get('type') == 'hold' or n.get('duration_ms'):
                        dur = float(n.get('duration_ms', 0)) / 1000.0
                    else:
                        dur = 0.0
                    notes.append(Note(t, lane, dur))
                return notes

            with open(path) as f:
                src = f.read()
            m = re.search(r'pattern\s*=\s*\[([^\]]+)\]', src, re.DOTALL)
            if not m: return None
            notes = []
            for tup in re.finditer(
                r'\(([\d.]+)\s*,\s*(\d)\s*,\s*(True|False)\s*,\s*([\d.]+)\)', m.group(1)
            ):
                t, lane, is_hold, hold_dur = tup.groups()
                notes.append(Note(float(t), int(lane),
                                  float(hold_dur) if is_hold=="True" else 0.0))
            return notes
        except Exception as e:
            print(f"[LOAD] {e}"); return None

    # ── Draw ──────────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(BG)
        F  = self.F
        cx = SCREEN_W // 2

        # Header
        ht = F.xl.render("CHART EDITOR", True, WHITE)
        self.screen.blit(ht, (cx - ht.get_width()//2, 38))
        sub = F.md.render("Create or edit a rhythm game chart", True, MID_GRAY)
        self.screen.blit(sub, (cx - sub.get_width()//2, 70))

        # Mode buttons
        for label, mode, bx in [("+ NEW CHART","new",cx-210),
                                 ("✎ EDIT EXISTING","edit",cx+20)]:
            br  = pygame.Rect(bx, 110, 190, 42)
            sel = self.mode == mode
            pygame.draw.rect(self.screen, (30,50,80) if sel else (20,20,32), br, border_radius=8)
            pygame.draw.rect(self.screen, ACCENT if sel else DARK_GRAY, br, 2, border_radius=8)
            ls = F.md.render(label, True, WHITE if sel else GRAY)
            self.screen.blit(ls, (br.centerx-ls.get_width()//2, br.centery-ls.get_height()//2))

        if self.mode == "new":
            self._draw_new_fields(F, cx)
        else:
            self._draw_edit_fields(F, cx)

        # Error
        if self.error_msg:
            em = F.sm.render(self.error_msg, True, RED)
            self.screen.blit(em, (cx - em.get_width()//2, SCREEN_H - 108))

        # Submit
        sb = pygame.Rect(cx-120, SCREEN_H-80, 240, 46)
        pygame.draw.rect(self.screen, (28,72,46), sb, border_radius=10)
        pygame.draw.rect(self.screen, GREEN, sb, 2, border_radius=10)
        sl = F.lg.render("OPEN EDITOR  ↵", True, GREEN)
        self.screen.blit(sl, (sb.centerx-sl.get_width()//2, sb.centery-sl.get_height()//2))

        # Footer
        ft = F.xs.render("Tab = next field    ↑↓ = pick song    Enter = open    Esc = quit",
                          True, DARK_GRAY)
        self.screen.blit(ft, (cx - ft.get_width()//2, SCREEN_H - 22))

        pygame.display.flip()

    def _draw_new_fields(self, F, cx):
        rects  = self._new_field_rects()
        labels = ["Song Title", "Artist", "BPM", "MP3 File Path", "Save Chart As (.py)"]
        inps   = self.new_inputs
        for inp, rect, label in zip(inps, rects, labels):
            inp.draw(self.screen, F.sm, rect, label=label)

    def _draw_edit_fields(self, F, cx):
        # ── Song dropdown ──────────────────────────────────────────────────
        dr    = self._dropdown_rect()
        label = F.sm.render("Song (from charts/*.json)", True, GRAY)
        self.screen.blit(label, (dr.x, dr.y - label.get_height() - 3))

        pygame.draw.rect(self.screen, (25,25,38), dr, border_radius=5)
        pygame.draw.rect(self.screen, ACCENT if self.dropdown_open else DARK_GRAY,
                         dr, 1, border_radius=5)

        if self.songs:
            song_txt = self.songs[self.song_idx].get("display", self.songs[self.song_idx]["title"])
            st = F.sm.render(song_txt, True, WHITE)
            self.screen.blit(st, (dr.x+8, dr.y+(dr.h-st.get_height())//2))
        else:
            nt = F.sm.render("(no songs found in charts/*.json)", True, MID_GRAY)
            self.screen.blit(nt, (dr.x+8, dr.y+(dr.h-nt.get_height())//2))

        # Arrow
        arr = F.sm.render("▼" if not self.dropdown_open else "▲", True, GRAY)
        self.screen.blit(arr, (dr.right-arr.get_width()-8, dr.y+(dr.h-arr.get_height())//2))

        # Dropdown list (drawn last so it overlaps fields below)
        if self.dropdown_open and self.songs:
            dlr = self._dropdown_list_rect()
            pygame.draw.rect(self.screen, (28,28,44), dlr, border_radius=5)
            pygame.draw.rect(self.screen, ACCENT, dlr, 1, border_radius=5)
            for i, song in enumerate(self.songs[:6]):
                item_r = pygame.Rect(dlr.x, dlr.y + i*34, dlr.w, 34)
                sel    = i == self.song_idx
                hover  = i == self.dropdown_hover
                if sel:
                    pygame.draw.rect(self.screen, (40,60,100), item_r)
                elif hover:
                    pygame.draw.rect(self.screen, (32,32,52), item_r)
                st = F.sm.render(song.get("display", song["title"]), True, WHITE if sel else OFF_WHITE)
                bt = F.xs.render(f"{song['bpm']} BPM  {song['artist']}", True, MID_GRAY)
                self.screen.blit(st, (item_r.x+10, item_r.y+4))
                self.screen.blit(bt, (item_r.x+10, item_r.y+20))
            return   # don't draw fields underneath while open

        # ── Edit text fields ───────────────────────────────────────────────
        rects  = self._edit_field_rects()
        labels = ["Song Title", "Artist", "BPM", "MP3 File Path", "Load Chart File (.json/.py)"]
        for inp, rect, label in zip(self.edit_inputs, rects, labels):
            inp.draw(self.screen, F.sm, rect, label=label)

    def run(self):
        clock = pygame.time.Clock()
        while not self.done:
            clock.tick(60)
            self.handle_events()
            self.draw()
        return self.result


# ══════════════════════════════════════════════════════════════════════════════
#  CHART EDITOR
# ══════════════════════════════════════════════════════════════════════════════
class ChartEditor:
    def __init__(self, mp3_path, bpm, title, artist, initial_notes=None, source_path=None):
        self.F = Fonts()
        pygame.display.set_caption(f"Chart Editor — {title}")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock  = pygame.time.Clock()

        self.mp3_path = mp3_path
        self.bpm      = bpm
        self.title    = title
        self.artist   = artist
        self.duration = 120.0

        # BPM input widget (panel, always visible)
        self.bpm_input        = TextInput(str(round(bpm)), 6)
        self.bpm_input.active = False

        # Audio
        self.audio_loaded = False
        if mp3_path and os.path.exists(mp3_path):
            try:
                pygame.mixer.music.load(mp3_path)
                self.audio_loaded = True
                size = os.path.getsize(mp3_path)
                self.duration = max(60.0, size / (128*1024/8))
            except Exception as e:
                print(f"[AUDIO] {e}")

        # Playback
        self.playing      = False
        self.play_start_t = 0.0
        self.play_offset  = 0.0
        self.song_pos     = 0.0

        self.source_path  = source_path

        # Scroll
        self.scroll_sec = 0.0

        # Snap
        self.snap_modes = ["4th","8th","16th","32nd"]
        self.snap_idx   = 1
        self.snap_divs  = {"4th":1,"8th":2,"16th":4,"32nd":8}

        # Notes + history
        self.notes: list[Note]       = initial_notes or []
        self.undo_stack: list[list]  = []
        self.redo_stack: list[list]  = []

        # Drag state — cleaner state machine
        # States: "idle", "dragging"
        self.drag_state   = "idle"
        self.drag_lane    = -1
        self.drag_start_t = 0.0
        self.drag_start_y = 0
        self.drag_cur_t   = 0.0   # current snapped end time while dragging
        self.drag_moved   = False  # has mouse moved beyond threshold?

        # UI
        self.status_msg    = "Ready.  Click = tap note,  drag down = hold note."
        self.status_timer  = 0.0
        self.confirm_clear = False
        self.back_requested = False

    # ── Helpers ───────────────────────────────────────────────────────────────
    def sec_to_y(self, t):
        return int(PLAYHEAD_Y - (t - self.scroll_sec) * PX_PER_SEC)

    def y_to_sec(self, y):
        return self.scroll_sec + (PLAYHEAD_Y - y) / PX_PER_SEC

    def x_to_lane(self, x):
        return max(0, min(3, (x - TIMELINE_X) // LANE_W))

    def in_timeline(self, x, y):
        return TIMELINE_X <= x < TIMELINE_X + TIMELINE_W

    def snap_time(self, t):
        beat = 60.0 / self.bpm
        div  = self.snap_divs[self.snap_modes[self.snap_idx]]
        grid = beat / div
        return round(max(0.0, t) / grid) * grid

    def _apply_bpm_input(self):
        try:
            v = float(self.bpm_input.value)
            if 20 <= v <= 400:
                self.bpm = v
                self.set_status(f"BPM set to {round(v,1)}")
        except:
            self.bpm_input.value = str(round(self.bpm))

    # ── Playback ──────────────────────────────────────────────────────────────
    def play(self):
        if self.audio_loaded:
            pygame.mixer.music.play(start=max(0, self.song_pos))
        self.play_start_t = time.time()
        self.play_offset  = self.song_pos
        self.playing      = True

    def pause(self):
        if self.audio_loaded: pygame.mixer.music.pause()
        self.playing = False

    def rewind(self):
        was = self.playing
        if was: self.pause()
        self.song_pos   = 0.0
        self.scroll_sec = 0.0
        if was: self.play()

    def toggle_play(self):
        self.pause() if self.playing else self.play()

    # ── Note helpers ──────────────────────────────────────────────────────────
    def _save_undo(self):
        self.undo_stack.append(copy.deepcopy(self.notes))
        self.redo_stack.clear()
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    def note_at(self, t, lane):
        tol = max(0.04, (60.0/self.bpm) / (self.snap_divs[self.snap_modes[self.snap_idx]] * 2))
        for n in self.notes:
            if n.lane != lane: continue
            if abs(n.time - t) <= tol: return n
            if n.is_hold and n.time - tol <= t <= n.end_time() + tol: return n
        return None

    def place_tap(self, t, lane):
        self._save_undo()
        ex = self.note_at(t, lane)
        if ex:
            self.notes.remove(ex)
        else:
            self.notes.append(Note(time=t, lane=lane))
        self.notes.sort(key=lambda n: n.time)

    def place_hold(self, start_t, lane, hold_dur):
        if hold_dur < 0.02:
            self.place_tap(start_t, lane)
            return
        self._save_undo()
        ex = self.note_at(start_t, lane)
        if ex: self.notes.remove(ex)
        self.notes.append(Note(time=start_t, lane=lane, hold_dur=hold_dur))
        self.notes.sort(key=lambda n: n.time)

    def delete_at(self, t, lane):
        n = self.note_at(t, lane)
        if n:
            self._save_undo()
            self.notes.remove(n)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.notes))
            self.notes = self.undo_stack.pop()
            self.set_status("Undo.")

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.notes))
            self.notes = self.redo_stack.pop()
            self.set_status("Redo.")

    def set_status(self, msg):
        self.status_msg   = msg
        self.status_timer = 3.0

    # ── Export ────────────────────────────────────────────────────────────────
    def export(self):
        if not self.notes:
            self.set_status("Nothing to export!")
            return
        var      = "_".join(re.sub(r"[^a-zA-Z0-9 ]","",self.title).strip().upper().split())
        filename = var.lower() + "_chart.py"
        mp3name  = os.path.basename(self.mp3_path) if self.mp3_path else "song.mp3"
        pat      = "\n".join(
            f"        ({round(n.time,3)}, {n.lane}, {n.is_hold}, {round(n.hold_dur,3)}),"
            for n in sorted(self.notes, key=lambda n: n.time)
        )
        out = f'''# chart_editor.py export — paste into charts.py and add {var} to SONGS
{var} = SongDef(
    title      = "{self.title}",
    artist     = "{self.artist}",
    bpm        = {round(self.bpm)},
    audio_file = _audio("{mp3name}"),
    pattern    = [
{pat}
    ],
)
'''
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path,"w") as f: f.write(out)
        self.set_status(f"Saved → {filename}  ({len(self.notes)} notes)")
        print(f"[EXPORT] {path}")

    def _save_json_chart(self, path):
        import json
        data = {
            "title": self.title,
            "artist": self.artist,
            "bpm": round(self.bpm),
            "audio_file": os.path.basename(self.mp3_path) if self.mp3_path else "",
            "notes": [],
        }
        for n in sorted(self.notes, key=lambda n: n.time):
            note = {
                "time_ms": int(round(n.time * 1000)),
                "lane": n.lane,
                "type": "hold" if n.is_hold else "tap",
                "duration_ms": int(round(n.hold_dur * 1000)) if n.is_hold else 0,
            }
            data["notes"].append(note)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.set_status(f"Saved → {path}  ({len(self.notes)} notes)")
        print(f"[SAVE] {path}")

    def save_chart(self):
        if self.source_path:
            self._save_json_chart(self.source_path)
        else:
            self.export()

    # ── Update ────────────────────────────────────────────────────────────────
    def update(self, dt):
        if self.playing:
            self.song_pos = self.play_offset + (time.time() - self.play_start_t)
            if self.song_pos >= self.duration:
                self.pause(); self.song_pos = self.duration
            self.scroll_sec = max(0.0, self.song_pos)
        if self.status_timer > 0:
            self.status_timer -= dt

    # ── Draw ──────────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(BG)
        self._draw_lanes()
        self._draw_grid()
        self._draw_notes()
        self._draw_drag_preview()
        self._draw_hover()
        self._draw_playhead()
        self._draw_panel()
        if self.confirm_clear:
            self._draw_confirm()
        pygame.display.flip()

    def _draw_lanes(self):
        for i in range(4):
            lx  = TIMELINE_X + i * LANE_W
            col = LANE_EVEN if i % 2 == 0 else LANE_ODD
            pygame.draw.rect(self.screen, col, (lx, 0, LANE_W, SCREEN_H))

    def _draw_grid(self):
        beat     = 60.0 / self.bpm
        div      = self.snap_divs[self.snap_modes[self.snap_idx]]
        grid_inc = beat / div
        top_sec  = self.y_to_sec(0)
        t        = math.floor(self.scroll_sec / grid_inc) * grid_inc

        while t <= top_sec + grid_inc:
            y = self.sec_to_y(t)
            if -2 <= y <= SCREEN_H + 2:
                bn = t / beat
                if abs(bn % 4) < 0.005:
                    col, w = MEASURE_LINE, 2
                elif abs(bn % 1) < 0.005:
                    col, w = BEAT_LINE, 1
                elif abs(bn % 0.5) < 0.005:
                    col, w = HALF_LINE, 1
                else:
                    col, w = GRID_LINE, 1
                pygame.draw.line(self.screen, col,
                                 (TIMELINE_X, y), (TIMELINE_X+TIMELINE_W, y), w)
                # Measure label
                if abs(bn % 4) < 0.005:
                    mn  = int(round(bn/4)) + 1
                    lbl = self.F.xs.render(f"M{mn}", True, MEASURE_LINE)
                    self.screen.blit(lbl, (TIMELINE_X - lbl.get_width() - 5, y - 8))
                # Time
                m2  = int(t//60); s2 = t%60
                tl  = self.F.xs.render(f"{m2}:{s2:05.2f}", True, DARK_GRAY)
                self.screen.blit(tl, (TIMELINE_X - tl.get_width() - 5, y + 3))
            t += grid_inc

        # Lane separators
        for i in range(5):
            lx = TIMELINE_X + i * LANE_W
            pygame.draw.line(self.screen, DARK_GRAY, (lx,0), (lx,SCREEN_H), 1)

    def _draw_notes(self):
        for n in self.notes:
            self._draw_single_note(n, alpha=255)

    def _draw_single_note(self, n: Note, alpha=255, override_lane=None):
        lane = override_lane if override_lane is not None else n.lane
        y    = self.sec_to_y(n.time)
        x    = TIMELINE_X + lane * LANE_W

        if n.is_hold:
            hold_px = int(n.hold_dur * PX_PER_SEC)
            tail_y  = y - hold_px   # tail is above (earlier time = smaller y? No: EARLIER = LOWER y)
            # In our coords: larger t → smaller y (higher on screen)
            # hold_dur adds to time, so tail is at n.time + hold_dur → lower y value (higher)
            # tail_y = sec_to_y(n.time + n.hold_dur) = y - hold_px  ✓ tail is above head
            tc = list(HOLD_COLORS[lane]) + [alpha]
            tr = pygame.Rect(x + LANE_W//2 - 12, tail_y, 24, hold_px)
            if tr.height > 0:
                s = pygame.Surface((tr.w, tr.h), pygame.SRCALPHA)
                s.fill((*HOLD_COLORS[lane], alpha))
                self.screen.blit(s, (tr.x, tr.y))
            # Tail cap
            cap = pygame.Rect(x+4, tail_y, LANE_W-8, NOTE_H//2)
            cs  = pygame.Surface((cap.w, cap.h), pygame.SRCALPHA)
            cs.fill((*LANE_COLORS[lane], alpha))
            self.screen.blit(cs, (cap.x, cap.y))

        # Head
        hr = pygame.Rect(x+4, y-NOTE_H//2, LANE_W-8, NOTE_H)
        hs = pygame.Surface((hr.w, hr.h), pygame.SRCALPHA)
        hs.fill((*LANE_COLORS[lane], alpha))
        self.screen.blit(hs, (hr.x, hr.y))
        # Highlight bar
        hl = pygame.Surface((hr.w-8, 3), pygame.SRCALPHA)
        hl.fill((255,255,255, min(alpha, 80)))
        self.screen.blit(hl, (hr.x+4, hr.y+4))

    def _draw_drag_preview(self):
        if self.drag_state != "dragging":
            return
        # Preview note
        hold_dur = max(0.0, self.drag_cur_t - self.drag_start_t) if self.drag_moved else 0.0
        preview  = Note(time=self.drag_start_t, lane=self.drag_lane, hold_dur=hold_dur)
        self._draw_single_note(preview, alpha=160)

    def _draw_hover(self):
        mx, my = pygame.mouse.get_pos()
        if not self.in_timeline(mx, my) or self.drag_state == "dragging":
            return
        lane = self.x_to_lane(mx)
        t    = self.snap_time(self.y_to_sec(my))
        y    = self.sec_to_y(t)
        x    = TIMELINE_X + lane * LANE_W
        s    = pygame.Surface((LANE_W-8, NOTE_H), pygame.SRCALPHA)
        s.fill((*LANE_COLORS[lane], 60))
        self.screen.blit(s, (x+4, y-NOTE_H//2))

    def _draw_playhead(self):
        pygame.draw.line(self.screen, PLAYHEAD_C,
                         (TIMELINE_X, PLAYHEAD_Y), (TIMELINE_X+TIMELINE_W, PLAYHEAD_Y), 2)
        pygame.draw.polygon(self.screen, PLAYHEAD_C, [
            (TIMELINE_X-2, PLAYHEAD_Y-7),
            (TIMELINE_X-2, PLAYHEAD_Y+7),
            (TIMELINE_X-14, PLAYHEAD_Y),
        ])
        m = int(self.song_pos//60); s = self.song_pos%60
        tl = self.F.sm.render(f"▶ {m}:{s:05.2f}", True, PLAYHEAD_C)
        self.screen.blit(tl, (TIMELINE_X+4, PLAYHEAD_Y+6))

    # ── Panel ─────────────────────────────────────────────────────────────────
    def _draw_panel(self):
        pygame.draw.rect(self.screen, PANEL_BG,
                         pygame.Rect(PANEL_X-6, 0, PANEL_W+6, SCREEN_H))
        pygame.draw.line(self.screen, DARK_GRAY, (PANEL_X-6,0), (PANEL_X-6,SCREEN_H), 1)

        F  = self.F
        px = PANEL_X
        y  = 14

        def row(text, color=OFF_WHITE, font=None, dy=4):
            nonlocal y
            f    = font or F.md
            surf = f.render(text, True, color)
            self.screen.blit(surf, (px, y))
            y   += surf.get_height() + dy

        def divider(label):
            nonlocal y
            y += 4
            ls = F.xs.render(f"── {label} ──", True, MID_GRAY)
            self.screen.blit(ls, (px, y))
            y += ls.get_height() + 5

        # Header
        row(f"CHART EDITOR", WHITE, F.lg, dy=2)
        row(f"{self.title}", LANE_COLORS[0], F.md, dy=1)
        row(f"{self.artist}", GRAY, F.sm, dy=8)

        # BPM (editable)
        divider("BPM")
        bpm_rect = pygame.Rect(px, y, 100, 28)
        self.bpm_input.draw(self.screen, F.sm, bpm_rect, label_color=GRAY)
        hint = F.xs.render("[ ] ±1   { } ±5", True, MID_GRAY)
        self.screen.blit(hint, (px, y + 32))
        y += 56

        # Playback
        divider("PLAYBACK")
        state = "▶  PLAYING" if self.playing else "▐▐  PAUSED"
        row(state, PLAYHEAD_C if self.playing else GRAY)
        m = int(self.song_pos//60); s = self.song_pos%60
        dm = int(self.duration//60); ds = self.duration%60
        row(f"{m}:{s:05.2f} / {dm}:{ds:05.2f}", MID_GRAY, F.sm)

        # Snap
        divider("SNAP")
        for i, mode in enumerate(self.snap_modes):
            col = SNAP_COLORS[mode] if i == self.snap_idx else MID_GRAY
            row(f"[{i+1}] {mode} notes", col, F.sm, dy=3)

        # Back button
        back_btn = self._back_button_rect()
        pygame.draw.rect(self.screen, (30,40,50), back_btn, border_radius=8)
        pygame.draw.rect(self.screen, (80,120,180), back_btn, 2, border_radius=8)
        bt = F.sm.render("← BACK", True, WHITE)
        self.screen.blit(bt, (back_btn.x + 10, back_btn.y + (back_btn.h - bt.get_height())//2))

        # Chart info
        divider("CHART")
        holds = sum(1 for n in self.notes if n.is_hold)
        row(f"Notes:  {len(self.notes)}", OFF_WHITE, F.sm, dy=2)
        row(f"Taps:   {len(self.notes)-holds}", OFF_WHITE, F.sm, dy=2)
        row(f"Holds:  {holds}", OFF_WHITE, F.sm, dy=2)
        row(f"Undo:   {len(self.undo_stack)}  Redo: {len(self.redo_stack)}", MID_GRAY, F.sm)

        # Controls
        divider("CONTROLS")
        controls = [
            ("Space",   "Play/Pause"),
            ("R",       "Rewind"),
            ("E",       "Rewind 5s"),
            ("Scroll",  "Scroll"),
            ("Click",   "Tap note"),
            ("Drag↓",   "Hold note"),
            ("R-click", "Delete"),
            ("Ctrl+Z",  "Undo"),
            ("Ctrl+Y",  "Redo"),
            ("Ctrl+S",  "Export"),
            ("[ ]",     "BPM ±1"),
            ("{ }",     "BPM ±5"),
            ("Del",     "Clear all"),
        ]
        for key, desc in controls:
            ks = F.xs.render(f"{key:<9}", True, LANE_COLORS[2])
            ds = F.xs.render(desc, True, GRAY)
            self.screen.blit(ks, (px, y))
            self.screen.blit(ds, (px + ks.get_width() + 4, y))
            y += ks.get_height() + 3

        # Status bar
        if self.status_timer > 0:
            a  = min(255, int(self.status_timer * 200))
            ss = F.sm.render(self.status_msg, True, GREEN)
            ss.set_alpha(a)
            self.screen.blit(ss, (px, SCREEN_H - 46))

        exp = F.xs.render("Ctrl+S = export chart", True, DARK_GRAY)
        self.screen.blit(exp, (px, SCREEN_H - 22))

        # Lane color legend at bottom of timeline
        for i in range(4):
            lx  = TIMELINE_X + i*LANE_W
            lbl = F.xs.render(f"L{i+1}", True, LANE_COLORS[i])
            self.screen.blit(lbl, (lx + LANE_W//2 - lbl.get_width()//2, SCREEN_H-18))

    def _back_button_rect(self):
        return pygame.Rect(PANEL_X + PANEL_W - 112, 102, 104, 30)

    def _draw_confirm(self):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0,0,0,180))
        self.screen.blit(ov,(0,0))
        cx,cy = SCREEN_W//2, SCREEN_H//2
        box   = pygame.Rect(cx-200, cy-55, 400, 110)
        pygame.draw.rect(self.screen, (28,28,40), box, border_radius=12)
        pygame.draw.rect(self.screen, RED, box, 2, border_radius=12)
        t1 = self.F.lg.render("Clear all notes?", True, WHITE)
        t2 = self.F.sm.render("Enter = confirm      Esc = cancel", True, GRAY)
        self.screen.blit(t1,(cx-t1.get_width()//2, cy-38))
        self.screen.blit(t2,(cx-t2.get_width()//2, cy+10))

    # ── Events ────────────────────────────────────────────────────────────────
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()

            elif event.type == pygame.KEYDOWN:
                # BPM input takes priority if active
                if self.bpm_input.active:
                    if event.key == pygame.K_RETURN:
                        self._apply_bpm_input()
                        self.bpm_input.active = False
                    elif event.key == pygame.K_ESCAPE:
                        self.bpm_input.value  = str(round(self.bpm))
                        self.bpm_input.active = False
                    else:
                        self.bpm_input.handle_key(event)
                else:
                    self._on_key(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                # Click BPM box?
                bpm_rect = pygame.Rect(PANEL_X, 0, 100, 28)  # rough; recalc below
                # Just check x range of panel for BPM activation
                if event.button == 1:
                    # Check if clicking the BPM input (approximate rect)
                    br = pygame.Rect(PANEL_X, self._bpm_rect_y(), 100, 28)
                    if br.collidepoint(mx, my):
                        self.bpm_input.active  = True
                        self.bpm_input.cursor  = len(self.bpm_input.value)
                    elif self._back_button_rect().collidepoint(mx, my):
                        self.back_requested = True
                    else:
                        self.bpm_input.active = False
                        if self.in_timeline(mx, my):
                            self._on_lmb_down(mx, my)
                elif event.button == 3:
                    self.bpm_input.active = False
                    if self.in_timeline(mx, my):
                        t    = self.snap_time(self.y_to_sec(my))
                        lane = self.x_to_lane(mx)
                        self.delete_at(t, lane)
                elif event.button == 4:
                    self.scroll_sec = max(0.0, self.scroll_sec - (60/self.bpm)*0.5)
                elif event.button == 5:
                    self.scroll_sec += (60/self.bpm)*0.5

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self._on_lmb_up(*event.pos)

            elif event.type == pygame.MOUSEMOTION:
                self._on_mouse_move(*event.pos)

    def _bpm_rect_y(self):
        # Approximate y of BPM input in the panel — keep in sync with _draw_panel
        # Title(lg) + artist(md) + dy + divider + some spacing
        return 14 + 26 + 4 + 19 + 4 + 4 + 13 + 5 + 5   # ~94

    def _on_key(self, event):
        mods = pygame.key.get_mods()
        k    = event.key

        if self.confirm_clear:
            if k == pygame.K_RETURN:
                self._save_undo(); self.notes = []
                self.set_status("Cleared all notes.")
            self.confirm_clear = False
            return

        if k == pygame.K_SPACE:          self.toggle_play()
        elif k == pygame.K_r:            self.rewind()
        elif k == pygame.K_e:
            was = self.playing
            if was: self.pause()
            self.song_pos   = max(0.0, self.song_pos - 5.0)
            self.scroll_sec = max(0.0, self.song_pos)
            if was: self.play()
        elif k == pygame.K_HOME:         self.scroll_sec=0.0; self.song_pos=0.0
        elif k == pygame.K_END:          self.scroll_sec=max(0,self.duration-PLAYHEAD_Y/PX_PER_SEC)
        elif k in (pygame.K_1,pygame.K_2,pygame.K_3,pygame.K_4):
            self.snap_idx = k - pygame.K_1
        elif k == pygame.K_z and mods & pygame.KMOD_CTRL:  self.undo()
        elif k == pygame.K_y and mods & pygame.KMOD_CTRL:  self.redo()
        elif k == pygame.K_s and mods & pygame.KMOD_CTRL:  self.save_chart()
        elif k == pygame.K_DELETE:       self.confirm_clear = True
        elif k == pygame.K_ESCAPE:
            self.confirm_clear = False
        elif k == pygame.K_BACKSPACE:
            self.back_requested = True
        # BPM nudge
        elif k == pygame.K_LEFTBRACKET:
            self.bpm = max(20, self.bpm - (5 if mods & pygame.KMOD_SHIFT else 1))
            self.bpm_input.value = str(round(self.bpm)); self.set_status(f"BPM → {round(self.bpm)}")
        elif k == pygame.K_RIGHTBRACKET:
            self.bpm = min(400, self.bpm + (5 if mods & pygame.KMOD_SHIFT else 1))
            self.bpm_input.value = str(round(self.bpm)); self.set_status(f"BPM → {round(self.bpm)}")

    def _on_lmb_down(self, mx, my):
        t    = self.snap_time(self.y_to_sec(my))
        lane = self.x_to_lane(mx)
        self.drag_state   = "dragging"
        self.drag_lane    = lane
        self.drag_start_t = t
        self.drag_start_y = my
        self.drag_cur_t   = t
        self.drag_moved   = False

    def _on_lmb_up(self, mx, my):
        if self.drag_state != "dragging":
            return
        t_end    = self.snap_time(self.y_to_sec(my))
        hold_dur = max(0.0, t_end - self.drag_start_t) if self.drag_moved else 0.0
        self.place_hold(self.drag_start_t, self.drag_lane, hold_dur)
        self.drag_state = "idle"
        self.drag_moved = False

    def _on_mouse_move(self, mx, my):
        if self.drag_state != "dragging":
            return
        dy = my - self.drag_start_y
        if abs(dy) > DRAG_THRESHOLD:
            self.drag_moved = True
        self.drag_cur_t = self.snap_time(self.y_to_sec(my))

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        while True:
            if self.back_requested:
                if self.source_path:
                    self.save_chart()
                pygame.mixer.music.stop()
                return "back"
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()

    def quit(self):
        pygame.quit(); sys.exit()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Rhythm Game Chart Editor")
    parser.add_argument("mp3", nargs="?", default=None, help="MP3 file (optional)")
    parser.add_argument("--load", default=None, help="Load existing chart .py to edit")
    args = parser.parse_args()

    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    fonts  = Fonts()

    # Startup / editor loop
    while True:
        startup = StartupScreen(screen, fonts, initial_mp3=args.mp3)
        if args.load:
            startup.edit_load.value = args.load
            startup.mode = "edit"
            args.load = None
        params = startup.run()

        if not params:
            break

        editor = ChartEditor(
            mp3_path      = params["mp3"],
            bpm           = params["bpm"],
            title         = params["title"],
            artist        = params["artist"],
            initial_notes = params["notes"],
            source_path   = params.get("source"),
        )
        result = editor.run()
        if result == "back":
            continue
        break


if __name__ == "__main__":
    main()