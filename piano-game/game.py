#!/usr/bin/env python3
"""
Piano Tiles Rhythm Game  —  2 Player Split Screen
==================================================
Raspberry Pi + AT070TN92V.X (800×480 HDMI display)
Input via Arduino Nano over USB Serial.

Requirements:
    pip install pygame pyserial --break-system-packages

Put your MP3 files in the same folder as this script.
Audio file paths are set in the SONGS list below.

Serial protocol (from Arduino):
    "P1_0".."P1_3"        Player 1 lane press
    "P1_0_R".."P1_3_R"   Player 1 lane release (hold notes)
    "P2_0".."P2_3"        Player 2 lane press
    "P2_0_R".."P2_3_R"   Player 2 lane release
    "U" "D" "L" "R"       Macropad navigation

Keyboard fallback (no Arduino):
    P1: A S K L     P2: F G H J
    Menu: arrow keys, Enter=select
    Pause: P    Back: Backspace
"""

import pygame
import sys, os, time, threading, queue, random
from typing import Optional
from enum import Enum, auto
from charts import SONGS, SongDef

# ═══════════════════════════════════════════════════════════════════════════════
#  SERIAL
# ═══════════════════════════════════════════════════════════════════════════════
SERIAL_PORT = "/dev/ttyACM0"   # Arduino Nano usually ttyACM0; try ttyUSB0 if not found
BAUD_RATE   = 9600

try:
    import serial as _serial_mod
    _ser = _serial_mod.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    SERIAL_AVAILABLE = True
    print(f"[INFO] Serial connected on {SERIAL_PORT}")
except Exception as e:
    SERIAL_AVAILABLE = False
    print(f"[INFO] Serial not available ({e}) — keyboard mode.")


class SerialReader(threading.Thread):
    def __init__(self, ser, q):
        super().__init__(daemon=True)
        self.ser, self.q = ser, q

    def run(self):
        while True:
            try:
                line = self.ser.readline().decode("utf-8").strip()
                if line:
                    self.q.put(line)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPLAY CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
SCREEN_W, SCREEN_H = 800, 480
FPS          = 60
DIVIDER_W    = 6
HALF_W       = (SCREEN_W - DIVIDER_W) // 2
NUM_LANES    = 4
LANE_W       = HALF_W // NUM_LANES
TILE_H       = 70
HIT_ZONE_H   = 60
HIT_ZONE_Y   = SCREEN_H - 80
TRAIL_W      = 28
TILE_SPEED   = 260   # px/sec

# ── Colors ─────────────────────────────────────────────────────────────────────
BLACK         = (0,   0,   0)
WHITE         = (255, 255, 255)
DARK_GRAY     = (18,  18,  18)
MID_GRAY      = (40,  40,  40)
DIVIDER_COLOR = (80,  80,  80)
LANE_COLORS   = [(0,200,255),(0,255,160),(255,200,0),(255,80,120)]
HOLD_COLORS   = [(0,140,200),(0,180,110),(200,150,0),(200,50,90)]
PERFECT_COLOR = (0,   255, 160)
GOOD_COLOR    = (255, 200,   0)
MISS_COLOR    = (255,  50,  50)
HELD_COLOR    = (180, 255, 200)
P1_ACCENT     = (100, 180, 255)
P2_ACCENT     = (255, 130,  80)

# ── Hit windows ────────────────────────────────────────────────────────────────
PERFECT_WINDOW = 32
GOOD_WINDOW    = 60
SCORE_PERFECT  = 100
SCORE_GOOD     = 60
SCORE_HOLD_TICK= 8


# Songs are loaded from charts.py — see that file to add new songs.
# Keeping a dummy reference so the block below finds its end marker cleanly.
BAD_ROMANCE_PATTERN = [
    (1.091, 1, False, 0.0),
    (1.091, 3, False, 0.0),
    (1.3, 0, False, 0.0),
    (1.3, 1, False, 0.0),
    (1.533, 2, False, 0.0),
    (1.533, 3, False, 0.0),
    (1.881, 0, False, 0.0),
    (1.881, 1, False, 0.0),
    (1.997, 2, False, 0.0),
    (1.997, 0, False, 0.0),
    (2.345, 2, False, 0.0),
    (2.345, 1, False, 0.0),
    (2.554, 3, False, 0.0),
    (2.554, 2, False, 0.0),
    (2.833, 0, False, 0.0),
    (2.833, 1, False, 0.0),
    (3.088, 3, False, 0.0),
    (3.088, 2, False, 0.0),
    (3.204, 0, False, 0.0),
    (3.204, 3, False, 0.0),
    (3.46, 0, False, 0.0),
    (3.46, 2, False, 0.0),
    (3.646, 1, False, 0.0),
    (3.646, 3, False, 0.0),
    (4.226, 0, False, 0.0),
    (4.226, 2, False, 0.0),
    (4.458, 3, False, 0.0),
    (4.458, 1, False, 0.0),
    (4.598, 2, False, 0.0),
    (4.598, 3, False, 0.0),
    (4.83, 1, False, 0.0),
    (4.83, 0, False, 0.0),
    (5.317, 1, False, 0.0),
    (5.317, 2, False, 0.0),
    (5.851, 0, False, 0.0),
    (5.851, 1, False, 0.0),
    (6.107, 3, False, 0.0),
    (6.107, 0, False, 0.0),
    (6.316, 3, False, 0.0),
    (6.316, 1, False, 0.0),
    (6.618, 0, False, 0.0),
    (6.618, 2, False, 0.0),
    (7.129, 1, False, 0.0),
    (7.129, 3, False, 0.0),
    (7.291, 1, False, 0.0),
    (7.291, 2, False, 0.0),
    (7.477, 1, False, 0.0),
    (7.477, 0, False, 0.0),
    (7.616, 2, False, 0.0),
    (7.616, 3, False, 0.0),
    (7.848, 0, False, 0.0),
    (7.848, 2, False, 0.0),
    (8.313, 3, False, 0.0),
    (8.313, 1, False, 0.0),
    (8.499, 0, False, 0.0),
    (8.499, 3, False, 0.0),
    (8.94, 2, False, 0.0),
    (8.94, 0, False, 0.0),
    (9.218, 3, False, 0.0),
    (9.218, 1, False, 0.0),
    (9.334, 0, False, 0.0),
    (9.334, 3, False, 0.0),
    (9.59, 0, False, 0.0),
    (9.59, 1, False, 0.0),
    (9.868, 0, False, 0.0),
    (9.868, 2, False, 0.0),
    (10.101, 3, False, 0.0),
    (10.101, 1, False, 0.0),
    (10.356, 2, False, 0.0),
    (10.356, 0, False, 0.0),
    (10.588, 3, False, 0.0),
    (10.588, 1, False, 0.0),
    (11.146, 0, False, 0.0),
    (11.146, 3, False, 0.0),
    (11.262, 0, False, 0.0),
    (11.262, 2, False, 0.0),
    (11.447, 0, False, 0.0),
    (11.447, 3, False, 0.0),
    (11.726, 0, False, 0.0),
    (11.726, 2, False, 0.0),
    (11.865, 3, False, 0.0),
    (11.865, 0, False, 0.0),
    (12.376, 1, False, 0.0),
    (12.376, 2, False, 0.0),
    (12.539, 0, False, 0.0),
    (12.539, 3, False, 0.0),
    (12.841, 0, False, 0.0),
    (12.841, 2, False, 0.0),
    (13.119, 0, False, 0.0),
    (13.119, 3, False, 0.0),
    (13.351, 2, False, 0.0),
    (13.351, 0, False, 0.0),
    (13.886, 1, False, 0.0),
    (13.886, 2, False, 0.0),
    (14.396, 3, False, 0.0),
    (14.396, 0, False, 0.0),
    (14.675, 3, False, 0.0),
    (14.675, 2, False, 0.0),
    (14.884, 3, False, 0.0),
    (14.884, 1, False, 0.0),
    (15.139, 3, False, 0.0),
    (15.139, 2, False, 0.0),
    (15.673, 1, False, 0.0),
    (15.673, 0, False, 0.0),
    (15.999, 3, False, 0.0),
    (15.999, 1, False, 0.0),
    (16.184, 2, False, 0.0),
    (16.184, 3, False, 0.0),
    (16.3, 1, False, 0.0),
    (16.3, 2, False, 0.0),
    (16.417, 1, False, 0.0),
    (16.417, 3, False, 0.0),
    (16.625, 1, False, 0.0),
    (16.625, 2, False, 0.0),
    (16.904, 3, False, 0.0),
    (16.904, 1, False, 0.0),
    (17.16, 3, False, 0.0),
    (17.16, 2, False, 0.0),
    (17.299, 1, False, 0.0),
    (17.299, 0, False, 0.0),
    (17.926, 2, False, 0.0),
    (17.926, 1, False, 0.0),
    (18.042, 2, False, 0.0),
    (18.042, 0, False, 0.0),
    (18.646, 2, True,  0.58),
    (18.901, 3, False, 0.0),
    (18.901, 1, False, 0.0),
    (19.691, 2, False, 0.0),
    (19.691, 0, False, 0.0),
    (19.946, 3, False, 0.0),
    (19.946, 1, False, 0.0),
    (20.317, 2, False, 0.0),
    (20.317, 0, False, 0.0),
    (20.434, 1, False, 0.0),
    (20.434, 3, False, 0.0),
    (20.689, 1, False, 0.0),
    (20.689, 2, False, 0.0),
    (20.944, 3, False, 0.0),
    (20.944, 0, False, 0.0),
    (21.432, 2, False, 0.0),
    (21.943, 0, False, 0.0),
    (22.454, 3, False, 0.0),
    (22.454, 2, False, 0.0),
    (22.663, 1, False, 0.0),
    (22.663, 0, False, 0.0),
    (22.941, 3, False, 0.0),
    (22.941, 1, False, 0.0),
    (23.452, 2, False, 0.0),
    (23.661, 0, False, 0.0),
    (23.94,  2, False, 0.0),
    (24.195, 3, False, 0.0),
    (24.474, 2, False, 0.0),
    (24.474, 0, False, 0.0),
    (24.961, 2, False, 0.0),
    (24.961, 1, False, 0.0),
    (25.472, 2, False, 0.0),
    (25.612, 3, False, 0.0),
    (25.612, 1, False, 0.0),
    (25.983, 2, False, 0.0),
    (25.983, 0, False, 0.0),
    (26.494, 1, False, 0.0),
    (26.494, 2, False, 0.0),
    (26.749, 0, False, 0.0),
    (26.749, 3, False, 0.0),
    (26.982, 2, False, 0.0),
    (26.982, 1, False, 0.0),
    (27.26,  2, False, 0.0),
    (27.26,  3, False, 0.0),
    (27.492, 0, False, 0.0),
    (27.492, 2, False, 0.0),
    (27.655, 0, False, 0.0),
    (27.655, 3, False, 0.0),
    (28.003, 0, False, 0.0),
    (28.003, 1, False, 0.0),
    (28.514, 3, False, 0.0),
    (28.514, 0, False, 0.0),
    (28.677, 2, False, 0.0),
    (28.677, 3, False, 0.0),
    (29.002, 2, False, 0.0),
    (29.002, 0, False, 0.0),
    (29.513, 2, False, 0.0),
    (29.513, 3, False, 0.0),
]  # end dummy list — actual songs come from charts.py


# ═══════════════════════════════════════════════════════════════════════════════
#  TILE CLASSES
# ═══════════════════════════════════════════════════════════════════════════════
class Tile:
    def __init__(self, lane, x_offset):
        self.lane, self.x_offset = lane, x_offset
        self.y, self.hit, self.missed = float(-TILE_H), False, False

    @property
    def x(self): return self.x_offset + self.lane * LANE_W

    @property
    def rect(self): return pygame.Rect(self.x + 3, int(self.y), LANE_W - 6, TILE_H)

    def update(self, dt):
        if not self.hit: self.y += TILE_SPEED * dt

    def center_y(self): return self.y + TILE_H / 2

    def hit_zone_offset(self):
        return abs(self.center_y() - (HIT_ZONE_Y + HIT_ZONE_H / 2))

    def draw(self, surface):
        if self.hit: return
        color = LANE_COLORS[self.lane] if not self.missed else (70,70,70)
        r = self.rect
        sh = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        sh.fill((0,0,0,70))
        surface.blit(sh, (r.x+3, r.y+3))
        pygame.draw.rect(surface, color, r, border_radius=7)
        hl = pygame.Surface((r.w-10, 8), pygame.SRCALPHA)
        hl.fill((255,255,255,55))
        surface.blit(hl, (r.x+5, r.y+5))


class HoldTile(Tile):
    def __init__(self, lane, x_offset, hold_duration):
        super().__init__(lane, x_offset)
        self.hold_duration  = hold_duration
        self.hold_px        = hold_duration * TILE_SPEED
        self.head_hit       = False
        self.held           = False
        self.released_early = False
        self.completed      = False

    @property
    def tail_y(self): return self.y - self.hold_px

    def tail_in_hit_zone(self):
        return (self.tail_y + TILE_H / 2) >= HIT_ZONE_Y

    def draw(self, surface):
        if self.completed: return
        if not self.hit:
            tc = HOLD_COLORS[self.lane]
            tx = self.x + LANE_W // 2 - TRAIL_W // 2
            tr = pygame.Rect(tx, int(self.tail_y), TRAIL_W, int(self.hold_px + TILE_H))
            pygame.draw.rect(surface, tc, tr, border_radius=5)
            if self.held:
                glow = pygame.Surface((TRAIL_W+10, tr.h+10), pygame.SRCALPHA)
                glow.fill((*tc, 60))
                surface.blit(glow, (tx-5, tr.y-5))
        super().draw(surface)
        if not self.hit:
            cap = pygame.Rect(self.x+3, int(self.tail_y), LANE_W-6, TILE_H//2)
            pygame.draw.rect(surface, LANE_COLORS[self.lane], cap, border_radius=5)


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOATING TEXT
# ═══════════════════════════════════════════════════════════════════════════════
class FloatingText:
    def __init__(self, text, x, y, color, font):
        self.text, self.x, self.y = text, x, float(y)
        self.color, self.font     = color, font
        self.alpha = 255.0

    def update(self, dt):
        self.y    -= 55 * dt
        self.alpha = max(0.0, self.alpha - 420 * dt)

    def draw(self, surface):
        s = self.font.render(self.text, True, self.color)
        s.set_alpha(int(self.alpha))
        surface.blit(s, (self.x - s.get_width()//2, int(self.y)))

    @property
    def alive(self): return self.alpha > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAYER STATE
# ═══════════════════════════════════════════════════════════════════════════════
class PlayerState:
    def __init__(self, x_offset, accent):
        self.x_offset, self.accent = x_offset, accent
        self.tiles = []
        self.score = self.combo = self.max_combo = 0
        self.perfects = self.goods = self.misses = 0
        self.lane_flash  = [0.0] * NUM_LANES
        self.held_lanes  = [False] * NUM_LANES

    def reset(self):
        self.tiles = []
        self.score = self.combo = self.max_combo = 0
        self.perfects = self.goods = self.misses = 0
        self.lane_flash  = [0.0] * NUM_LANES
        self.held_lanes  = [False] * NUM_LANES

    def spawn(self, lane, is_hold, hold_dur):
        self.tiles.append(
            HoldTile(lane, self.x_offset, hold_dur) if is_hold
            else Tile(lane, self.x_offset)
        )

    def press(self, lane, fts, font):
        self.lane_flash[lane] = 1.0
        self.held_lanes[lane] = True
        lx = self.x_offset + lane * LANE_W + LANE_W // 2

        cands = [t for t in self.tiles
                 if t.lane == lane and not t.hit and not t.missed
                 and t.y > -TILE_H and t.center_y() < HIT_ZONE_Y + HIT_ZONE_H + 20]
        if not cands: return

        tile   = min(cands, key=lambda t: t.hit_zone_offset())
        offset = tile.hit_zone_offset()

        if isinstance(tile, HoldTile):
            if offset <= GOOD_WINDOW:
                tile.head_hit = True; tile.held = True
                self.combo += 1; self.perfects += 1
                fts.append(FloatingText("HOLD!", lx, HIT_ZONE_Y-20, HELD_COLOR, font))
            else:
                self.combo = 0; self.misses += 1
                fts.append(FloatingText("MISS", lx, HIT_ZONE_Y-20, MISS_COLOR, font))
        else:
            if offset <= PERFECT_WINDOW:
                tile.hit = True
                self.score += SCORE_PERFECT * (1 + self.combo // 10)
                self.combo += 1; self.perfects += 1
                fts.append(FloatingText("PERFECT", lx, HIT_ZONE_Y-20, PERFECT_COLOR, font))
            elif offset <= GOOD_WINDOW:
                tile.hit = True
                self.score += SCORE_GOOD
                self.combo += 1; self.goods += 1
                fts.append(FloatingText("GOOD", lx, HIT_ZONE_Y-20, GOOD_COLOR, font))
            else:
                self.combo = 0; self.misses += 1
                fts.append(FloatingText("MISS", lx, HIT_ZONE_Y-20, MISS_COLOR, font))

        self.max_combo = max(self.max_combo, self.combo)

    def release(self, lane):
        self.held_lanes[lane] = False
        for t in self.tiles:
            if isinstance(t, HoldTile) and t.lane == lane and t.held:
                t.held = False
                if not t.tail_in_hit_zone():
                    t.released_early = True

    def update(self, dt):
        for t in self.tiles:
            t.update(dt)
            if isinstance(t, HoldTile) and t.held:
                self.score += SCORE_HOLD_TICK
            if not isinstance(t, HoldTile):
                if not t.hit and not t.missed and t.y > HIT_ZONE_Y + HIT_ZONE_H + TILE_H:
                    t.missed = True; self.misses += 1; self.combo = 0
            if isinstance(t, HoldTile) and t.head_hit:
                if t.y > HIT_ZONE_Y + HIT_ZONE_H + TILE_H:
                    if t.held or not t.released_early:
                        t.completed = True
                    else:
                        t.missed = True; self.misses += 1

        self.tiles = [t for t in self.tiles
                      if t.y < SCREEN_H + 200
                      and not (isinstance(t, HoldTile) and t.completed)]
        for i in range(NUM_LANES):
            self.lane_flash[i] = max(0.0, self.lane_flash[i] - 5.0*dt)

    def draw_lanes(self, surf):
        for i in range(NUM_LANES):
            lx = self.x_offset + i * LANE_W
            pygame.draw.rect(surf, MID_GRAY, (lx, 0, LANE_W, SCREEN_H))
            if self.lane_flash[i] > 0:
                fs = pygame.Surface((LANE_W, SCREEN_H), pygame.SRCALPHA)
                fs.fill((*LANE_COLORS[i], int(self.lane_flash[i]*55)))
                surf.blit(fs, (lx, 0))
            pygame.draw.line(surf, BLACK, (lx,0), (lx,SCREEN_H), 2)

    def draw_hit_zone(self, surf):
        hz = pygame.Rect(self.x_offset, HIT_ZONE_Y, NUM_LANES*LANE_W, HIT_ZONE_H)
        pygame.draw.rect(surf, (55,55,55), hz)
        pygame.draw.rect(surf, WHITE, hz, 2)
        for i in range(NUM_LANES):
            lx  = self.x_offset + i*LANE_W
            ind = pygame.Rect(lx+8, HIT_ZONE_Y+8, LANE_W-16, HIT_ZONE_H-16)
            col = LANE_COLORS[i] if self.lane_flash[i] > 0.3 else (75,75,75)
            pygame.draw.rect(surf, col, ind, border_radius=5)

    def draw_tiles(self, surf):
        for t in self.tiles: t.draw(surf)


# ═══════════════════════════════════════════════════════════════════════════════
#  SCREEN ENUM
# ═══════════════════════════════════════════════════════════════════════════════
class Screen(Enum):
    MENU   = auto()
    GAME   = auto()
    PAUSE  = auto()
    RESULT = auto()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN GAME
# ═══════════════════════════════════════════════════════════════════════════════
class RhythmGame:
    def __init__(self):
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.display.set_caption("Rhythm Game")
        flags = pygame.FULLSCREEN if SERIAL_AVAILABLE else 0
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        self.clock  = pygame.time.Clock()

        self.font_xl   = pygame.font.SysFont("monospace", 58, bold=True)
        self.font_big  = pygame.font.SysFont("monospace", 42, bold=True)
        self.font_med  = pygame.font.SysFont("monospace", 28, bold=True)
        self.font_sm   = pygame.font.SysFont("monospace", 20)
        self.font_tiny = pygame.font.SysFont("monospace", 16)

        self.serial_q: queue.Queue = queue.Queue()
        if SERIAL_AVAILABLE:
            SerialReader(_ser, self.serial_q).start()

        self.p1 = PlayerState(0,                  P1_ACCENT)
        self.p2 = PlayerState(HALF_W + DIVIDER_W, P2_ACCENT)
        self.fts: list[FloatingText] = []

        self.screen_state: Screen    = Screen.MENU
        self.menu_cursor             = 0
        self.selected_song: Optional[SongDef] = None
        self.pattern_index           = 0
        self.song_start_time         = 0.0
        self.total_paused            = 0.0
        self.song_elapsed            = 0.0
        self.pause_start             = 0.0
        self._music_loaded           = False
        self._loaded_audio_path      = None
        if SONGS:
            self._load_audio(SONGS[self.menu_cursor])

    # ── Audio ──────────────────────────────────────────────────────────────────
    def _load_audio(self, song: SongDef):
        if song.audio_file and os.path.exists(song.audio_file):
            if self._loaded_audio_path != song.audio_file:
                try:
                    pygame.mixer.music.load(song.audio_file)
                    self._music_loaded = True
                    self._loaded_audio_path = song.audio_file
                    print(f"[AUDIO] Loaded: {song.audio_file}")
                except Exception as e:
                    self._music_loaded = False
                    self._loaded_audio_path = None
                    print(f"[AUDIO] Failed to load {song.audio_file}: {e}")
        else:
            self._music_loaded = False
            self._loaded_audio_path = None
            print(f"[AUDIO] No audio file for '{song.title}' — playing silently.")

    def _load_and_play(self, song: SongDef):
        pygame.mixer.music.stop()
        self._loaded_audio_path = None  # force fresh load before every game start
        self._load_audio(song)

    def _start_music(self):
        if self._music_loaded:
            pygame.mixer.music.play()

    def _stop_music(self):
        pygame.mixer.music.stop()

    def _pause_music(self):
        if self._music_loaded:
            pygame.mixer.music.pause()

    def _unpause_music(self):
        if self._music_loaded:
            pygame.mixer.music.unpause()

    # ── Game flow ──────────────────────────────────────────────────────────────
    def _start_game(self, song: SongDef):
        self.selected_song  = song
        self.p1.reset(); self.p2.reset()
        self.fts            = []
        self.pattern_index  = 0
        self.total_paused   = 0.0
        self.song_elapsed   = 0.0
        self._load_and_play(song)
        self._start_music()
        self.song_start_time = time.time()
        self.screen_state   = Screen.GAME

    def _pause(self):
        self.pause_start = time.time()
        self._pause_music()
        self.screen_state = Screen.PAUSE

    def _resume(self):
        self.total_paused += time.time() - self.pause_start
        self._unpause_music()
        self.screen_state = Screen.GAME

    def _back_to_menu(self):
        self._stop_music()
        self.screen_state = Screen.MENU

    # ── Serial drain ───────────────────────────────────────────────────────────
    def _drain_serial(self):
        ev = {"p1_press":[],"p1_release":[],"p2_press":[],"p2_release":[],"nav":[]}
        while not self.serial_q.empty():
            msg = self.serial_q.get_nowait()
            if msg in ("U","D","L","R"):
                ev["nav"].append(msg)
            elif msg.startswith("P1_") and "_R" in msg:
                ev["p1_release"].append(int(msg[3]))
            elif msg.startswith("P2_") and "_R" in msg:
                ev["p2_release"].append(int(msg[3]))
            elif msg.startswith("P1_"):
                ev["p1_press"].append(int(msg[3]))
            elif msg.startswith("P2_"):
                ev["p2_press"].append(int(msg[3]))
        return ev

    # ── Tile spawning ──────────────────────────────────────────────────────────
    def _spawn(self):
        song = self.selected_song
        while self.pattern_index < len(song.pattern):
            t, lane, is_hold, hold_dur = song.pattern[self.pattern_index]
            if self.song_elapsed >= t - (HIT_ZONE_Y + HIT_ZONE_H // 2 + TILE_H // 2) / TILE_SPEED:
                self.p1.spawn(lane, is_hold, hold_dur)
                self.p2.spawn(lane, is_hold, hold_dur)
                self.pattern_index += 1
            else:
                break
        if self.pattern_index >= len(song.pattern):
            last_t = song.pattern[-1][0] if song.pattern else 0
            if self.song_elapsed > last_t + 3.0:
                self.screen_state = Screen.RESULT

    # ── Update ─────────────────────────────────────────────────────────────────
    def update(self, dt):
        ev = self._drain_serial()

        if self.screen_state == Screen.MENU:
            for n in ev["nav"]:
                if n == "U":
                    self.menu_cursor = (self.menu_cursor-1) % len(SONGS)
                    self._load_audio(SONGS[self.menu_cursor])
                elif n == "D":
                    self.menu_cursor = (self.menu_cursor+1) % len(SONGS)
                    self._load_audio(SONGS[self.menu_cursor])
                elif n == "R":
                    self._start_game(SONGS[self.menu_cursor])
            for l in ev["p1_press"]:
                if l == 3:
                    self._start_game(SONGS[self.menu_cursor])

        elif self.screen_state == Screen.PAUSE:
            for n in ev["nav"]:
                if n == "R": self._resume()
                elif n == "L": self._back_to_menu()
            for l in ev["p1_press"]:
                if l == 0:
                    self._back_to_menu()

        elif self.screen_state == Screen.GAME:
            for n in ev["nav"]:
                if n == "L": self._pause(); return
            self.song_elapsed = time.time() - self.song_start_time - self.total_paused
            self._spawn()
            for l in ev["p1_press"]:    self.p1.press(l, self.fts, self.font_med)
            for l in ev["p1_release"]:  self.p1.release(l)
            for l in ev["p2_press"]:    self.p2.press(l, self.fts, self.font_med)
            for l in ev["p2_release"]:  self.p2.release(l)
            self.p1.update(dt); self.p2.update(dt)
            for ft in self.fts: ft.update(dt)
            self.fts = [ft for ft in self.fts if ft.alive]

        elif self.screen_state == Screen.RESULT:
            for n in ev["nav"]:
                if n == "L": self._back_to_menu()
            for l in ev["p1_press"]:
                if l == 0:
                    self._back_to_menu()

    # ── Draw ───────────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(DARK_GRAY)
        if self.screen_state == Screen.MENU:
            self._draw_menu()
        elif self.screen_state in (Screen.GAME, Screen.PAUSE):
            self._draw_game()
            if self.screen_state == Screen.PAUSE:
                self._draw_pause()
        elif self.screen_state == Screen.RESULT:
            self._draw_result()
        pygame.display.flip()

    def _draw_menu(self):
        title = self.font_big.render("RHYTHM GAME", True, WHITE)
        self.screen.blit(title, (SCREEN_W//2 - title.get_width()//2, 28))

        sub = self.font_sm.render("UP / DOWN  to scroll      RIGHT  to select", True, (210,210,210))
        self.screen.blit(sub, (SCREEN_W//2 - sub.get_width()//2, 82))

        item_h, list_y = 64, 138
        visible = 5
        start = max(0, self.menu_cursor - visible//2)
        end   = min(len(SONGS), start + visible)

        for idx in range(start, end):
            song = SONGS[idx]
            sel  = idx == self.menu_cursor
            iy   = list_y + (idx - start) * item_h
            box  = pygame.Rect(60, iy, SCREEN_W-120, item_h-6)
            pygame.draw.rect(self.screen, (50,60,80) if sel else (28,28,28), box, border_radius=10)
            pygame.draw.rect(self.screen, P1_ACCENT if sel else (50,50,50), box, 2, border_radius=10)

            # Song title
            tc   = WHITE if sel else (180,180,180)
            ts   = self.font_med.render(song.title, True, tc)
            self.screen.blit(ts, (box.x+18, iy+8))

            # BPM + audio / ready indicator
            has_audio = song.audio_file and os.path.exists(song.audio_file)
            if sel:
                if has_audio:
                    status = "READY" if self._music_loaded else "AUDIO UNAVAILABLE"
                else:
                    status = "(no audio)"
                meta = f"{song.bpm} BPM  {status}"
            else:
                meta = f"{song.bpm} BPM  {'♪' if has_audio else '(no audio)'}"
            ms   = self.font_tiny.render(meta, True, (120,120,120))
            self.screen.blit(ms, (box.x+18, iy+36))

            if sel:
                arr = self.font_med.render("▶", True, P1_ACCENT)
                self.screen.blit(arr, (box.right - arr.get_width()-16, iy+14))

        # Scroll dots
        for i in range(len(SONGS)):
            col = WHITE if i == self.menu_cursor else (60,60,60)
            pygame.draw.circle(self.screen, col, (SCREEN_W-22, list_y + i*12 + 6), 4)

    def _draw_game(self):
        self.p1.draw_lanes(self.screen)
        self.p2.draw_lanes(self.screen)
        pygame.draw.line(self.screen, BLACK, (HALF_W,0), (HALF_W,SCREEN_H), 2)
        pygame.draw.line(self.screen, BLACK, (HALF_W+DIVIDER_W,0), (HALF_W+DIVIDER_W,SCREEN_H), 2)
        pygame.draw.rect(self.screen, DIVIDER_COLOR, (HALF_W,0,DIVIDER_W,SCREEN_H))

        # Song title in divider (vertical)
        for ci, ch in enumerate(self.selected_song.title[:20]):
            cs = self.font_tiny.render(ch, True, (160,160,160))
            self.screen.blit(cs, (HALF_W+1, 18+ci*20))

        self.p1.draw_hit_zone(self.screen)
        self.p2.draw_hit_zone(self.screen)
        self.p1.draw_tiles(self.screen)
        self.p2.draw_tiles(self.screen)
        for ft in self.fts: ft.draw(self.screen)

        self._draw_hud(self.p1, "P1", 0)
        self._draw_hud(self.p2, "P2", HALF_W+DIVIDER_W)

        hint = self.font_tiny.render("◄ PAUSE", True, (80,80,80))
        self.screen.blit(hint, (SCREEN_W//2 - hint.get_width()//2, SCREEN_H-20))

    def _draw_hud(self, p: PlayerState, label: str, x_off: int):
        lbl = self.font_sm.render(label, True, p.accent)
        self.screen.blit(lbl, (x_off+6, 6))
        sc  = self.font_big.render(f"{p.score:,}", True, WHITE)
        self.screen.blit(sc,  (x_off+6, 26))
        if p.combo > 1:
            col = PERFECT_COLOR if p.combo >= 10 else WHITE
            cmb = self.font_med.render(f"×{p.combo}", True, col)
            self.screen.blit(cmb, (x_off + HALF_W - cmb.get_width()-8, 6))
        stats = self.font_tiny.render(f"P:{p.perfects} G:{p.goods} M:{p.misses}", True, (130,130,130))
        self.screen.blit(stats, (x_off+6, SCREEN_H-20))

    def _draw_pause(self):
        ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        ov.fill((0,0,0,160))
        self.screen.blit(ov, (0,0))
        pt = self.font_xl.render("PAUSED", True, WHITE)
        self.screen.blit(pt, (SCREEN_W//2 - pt.get_width()//2, 160))
        for i, (txt,col) in enumerate([("► RESUME", P1_ACCENT),("◄ MAIN MENU", MISS_COLOR)]):
            s = self.font_med.render(txt, True, col)
            self.screen.blit(s, (SCREEN_W//2 - s.get_width()//2, 270+i*50))

    def _draw_result(self):
        title = self.font_big.render("RESULTS", True, WHITE)
        self.screen.blit(title, (SCREEN_W//2 - title.get_width()//2, 18))
        sn = self.font_sm.render(self.selected_song.title, True, (160,160,160))
        self.screen.blit(sn, (SCREEN_W//2 - sn.get_width()//2, 68))
        if self.p1.score > self.p2.score:   w,c = "P1 WINS!", P1_ACCENT
        elif self.p2.score > self.p1.score: w,c = "P2 WINS!", P2_ACCENT
        else:                               w,c = "DRAW!", WHITE
        ws = self.font_xl.render(w, True, c)
        self.screen.blit(ws, (SCREEN_W//2 - ws.get_width()//2, 100))
        self._draw_result_card(self.p1, "PLAYER 1", 40,              P1_ACCENT)
        self._draw_result_card(self.p2, "PLAYER 2", SCREEN_W//2+10,  P2_ACCENT)
        bk = self.font_sm.render("◄  BACK TO MENU", True, (150,150,150))
        self.screen.blit(bk, (SCREEN_W//2 - bk.get_width()//2, SCREEN_H-34))

    def _draw_result_card(self, p: PlayerState, label, x, accent):
        card = pygame.Rect(x, 196, SCREEN_W//2-50, 230)
        pygame.draw.rect(self.screen, (30,30,30), card, border_radius=12)
        pygame.draw.rect(self.screen, accent, card, 2, border_radius=12)
        lbl = self.font_med.render(label, True, accent)
        self.screen.blit(lbl, (card.x+12, card.y+12))
        for i,(k,v) in enumerate([("SCORE",f"{p.score:,}"),("PERFECT",str(p.perfects)),
                                   ("GOOD",str(p.goods)),("MISS",str(p.misses)),
                                   ("MAX COMBO",str(p.max_combo))]):
            ry = card.y+52+i*34
            self.screen.blit(self.font_sm.render(k, True, (140,140,140)), (card.x+12, ry))
            vs = self.font_sm.render(v, True, WHITE)
            self.screen.blit(vs, (card.right - vs.get_width()-12, ry))

    # ── Keyboard fallback ──────────────────────────────────────────────────────
    P1_KEYS = {
        pygame.K_LEFT:  0, 
        pygame.K_UP:    1, 
        pygame.K_DOWN:  2, 
        pygame.K_RIGHT: 3
    }
    P2_KEYS = {pygame.K_f:0, pygame.K_g:1, pygame.K_h:2, pygame.K_j:3,
               pygame.K_1:0, pygame.K_2:1, pygame.K_3:2, pygame.K_4:3}

    def _keydown(self, key):
        if key == pygame.K_ESCAPE: self.quit()
        
        if self.screen_state == Screen.MENU:
            if key == pygame.K_UP:      
                self.menu_cursor = (self.menu_cursor-1)%len(SONGS)
                self._load_audio(SONGS[self.menu_cursor])
            elif key == pygame.K_DOWN:  
                self.menu_cursor = (self.menu_cursor+1)%len(SONGS)
                self._load_audio(SONGS[self.menu_cursor])
            # Added K_RIGHT here so your 4th button can select a song!
            elif key in (pygame.K_RETURN, pygame.K_RIGHT): 
                self._start_game(SONGS[self.menu_cursor])
                
        elif self.screen_state == Screen.GAME:
            if key == pygame.K_p: self._pause()
            if key in self.P1_KEYS: self.p1.press(self.P1_KEYS[key], self.fts, self.font_med)
            if key in self.P2_KEYS: self.p2.press(self.P2_KEYS[key], self.fts, self.font_med)
            
        elif self.screen_state == Screen.PAUSE:
            # Allows you to use UP (or Return) to resume, DOWN (or Backspace) to quit
            if key in (pygame.K_RETURN, pygame.K_UP):    self._resume()
            elif key in (pygame.K_BACKSPACE, pygame.K_DOWN): self._back_to_menu()
            
        elif self.screen_state == Screen.RESULT:
            # Pressing any arrow key on the result screen takes you back to menu
            if key in (pygame.K_BACKSPACE, pygame.K_LEFT, pygame.K_UP, pygame.K_DOWN, pygame.K_RIGHT): 
                self._back_to_menu()

    def _keyup(self, key):
        if self.screen_state == Screen.GAME:
            if key in self.P1_KEYS: self.p1.release(self.P1_KEYS[key])
            if key in self.P2_KEYS: self.p2.release(self.P2_KEYS[key])

    # ── Main loop ──────────────────────────────────────────────────────────────
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:       self.quit()
                if event.type == pygame.KEYDOWN:    self._keydown(event.key)
                if event.type == pygame.KEYUP:      self._keyup(event.key)
            self.update(dt)
            self.draw()

    def quit(self):
        self._stop_music()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    RhythmGame().run()