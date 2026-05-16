#!/usr/bin/env python3
"""
Piano Tiles Rhythm Game  —  2 Player Split Screen
==================================================
Raspberry Pi + AT070TN92V.X (800×480 HDMI display)
Input via Arduino Nano over USB Serial.

Requirements:
    pip install pygame pyserial

Serial protocol (from Arduino):
    "P1_0" .. "P1_3"       Player 1 lane press
    "P1_0_R" .. "P1_3_R"  Player 1 lane release  (hold notes)
    "P2_0" .. "P2_3"       Player 2 lane press
    "P2_0_R" .. "P2_3_R"  Player 2 lane release
    "U" "D" "L" "R"        Macropad navigation

Keyboard fallback (no Arduino):
    P1:  A S K L        P2:  F G H J
    Menu nav: arrow keys, Enter=select, Backspace=back
    Pause: P
"""

import pygame
import sys
import random
import time
import threading
import queue
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto

# ═══════════════════════════════════════════════════════════════════════════════
#  SERIAL
# ═══════════════════════════════════════════════════════════════════════════════
SERIAL_PORT = "/dev/ttyUSB0"   # or /dev/ttyACM0
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
        self.ser = ser
        self.q   = q

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
FPS = 60

# Split screen: each player gets a half
DIVIDER_W    = 6
HALF_W       = (SCREEN_W - DIVIDER_W) // 2   # 397 px each

NUM_LANES    = 4
LANE_W       = HALF_W // NUM_LANES            # ~99 px
TILE_H       = 70
HIT_ZONE_H   = 60
HIT_ZONE_Y   = SCREEN_H - 80

# Hold note trail
TRAIL_W      = 28

# ── Colors ────────────────────────────────────────────────────────────────────
BLACK         = (0,   0,   0)
WHITE         = (255, 255, 255)
DARK_GRAY     = (18,  18,  18)
MID_GRAY      = (40,  40,  40)
DIVIDER_COLOR = (80,  80,  80)

LANE_COLORS = [
    (0,   200, 255),   # cyan
    (0,   255, 160),   # mint
    (255, 200,   0),   # yellow
    (255,  80, 120),   # pink
]
HOLD_TRAIL_COLORS = [
    (0,   140, 200),
    (0,   180, 110),
    (200, 150,   0),
    (200,  50,  90),
]

PERFECT_COLOR = (0,   255, 160)
GOOD_COLOR    = (255, 200,   0)
MISS_COLOR    = (255,  50,  50)
HELD_COLOR    = (180, 255, 200)

P1_ACCENT = (100, 180, 255)
P2_ACCENT = (255, 130,  80)


# ═══════════════════════════════════════════════════════════════════════════════
#  SONGS
# ═══════════════════════════════════════════════════════════════════════════════
# Pattern format: list of (beat_time_seconds, lane, is_hold, hold_duration_sec)
# Beat time is relative to song start.

def _gen_random(duration=60, bpm=120):
    """Generate a random pattern for placeholder songs."""
    beat = 60 / bpm
    events = []
    t = 1.0
    while t < duration:
        lanes = random.sample(range(4), random.choices([1, 2], weights=[70, 30])[0])
        for lane in lanes:
            is_hold = random.random() < 0.2
            hold_dur = random.uniform(0.4, 1.2) if is_hold else 0.0
            events.append((round(t, 3), lane, is_hold, round(hold_dur, 3)))
        t += beat * random.choice([0.5, 1, 1, 1, 1.5, 2])
    return events

@dataclass
class SongDef:
    title:    str
    artist:   str
    bpm:      int
    pattern:  list   # list of (time, lane, is_hold, hold_dur)

SONGS = [
    SongDef("Neon Rush",    "placeholder", 130, _gen_random(60, 130)),
    SongDef("Echo Fields",  "placeholder", 100, _gen_random(60, 100)),
    SongDef("Cyber Waltz",  "placeholder",  90, _gen_random(60,  90)),
    SongDef("Pulse Drive",  "placeholder", 150, _gen_random(60, 150)),
    SongDef("Hollow Moon",  "placeholder", 110, _gen_random(60, 110)),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  TILE CLASSES
# ═══════════════════════════════════════════════════════════════════════════════
TILE_SPEED      = 260    # px / sec
PERFECT_WINDOW  = 32     # px from hit zone center
GOOD_WINDOW     = 60
SCORE_PERFECT   = 100
SCORE_GOOD      = 60
SCORE_HOLD_TICK = 8      # points per frame while holding


class Tile:
    """A standard tap tile."""
    def __init__(self, lane: int, x_offset: int):
        self.lane     = lane
        self.x_offset = x_offset   # pixel x start of player's area
        self.y        = float(-TILE_H)
        self.hit      = False
        self.missed   = False

    @property
    def x(self):
        return self.x_offset + self.lane * LANE_W

    @property
    def rect(self):
        return pygame.Rect(self.x + 3, int(self.y), LANE_W - 6, TILE_H)

    def update(self, dt):
        if not self.hit:
            self.y += TILE_SPEED * dt

    def center_y(self):
        return self.y + TILE_H / 2

    def hit_zone_offset(self):
        return abs(self.center_y() - (HIT_ZONE_Y + HIT_ZONE_H / 2))

    def draw(self, surface):
        if self.hit:
            return
        color = LANE_COLORS[self.lane] if not self.missed else (70, 70, 70)
        r = self.rect
        # Shadow
        sh = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 70))
        surface.blit(sh, (r.x + 3, r.y + 3))
        # Body
        pygame.draw.rect(surface, color, r, border_radius=7)
        # Highlight
        hl = pygame.Surface((r.w - 10, 8), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 55))
        surface.blit(hl, (r.x + 5, r.y + 5))


class HoldTile(Tile):
    """A hold tile: tap head, hold until tail passes hit zone."""
    def __init__(self, lane: int, x_offset: int, hold_duration: float):
        super().__init__(lane, x_offset)
        self.hold_duration = hold_duration          # seconds
        self.hold_px       = hold_duration * TILE_SPEED  # trail length in px
        self.head_hit      = False   # head was tapped
        self.held          = False   # currently being held
        self.released_early= False
        self.completed     = False

    @property
    def tail_y(self):
        """Y position of the bottom of the trail (spawns above head)."""
        return self.y - self.hold_px

    def tail_in_hit_zone(self):
        tail_center = self.tail_y + TILE_H / 2
        return tail_center >= HIT_ZONE_Y

    def draw(self, surface):
        if self.completed:
            return

        # Draw trail first (behind head)
        if not self.hit:
            trail_color = HOLD_TRAIL_COLORS[self.lane]
            tx = self.x + LANE_W // 2 - TRAIL_W // 2
            # Trail goes from top of head up by hold_px
            trail_rect = pygame.Rect(tx, int(self.tail_y), TRAIL_W,
                                     int(self.hold_px + TILE_H))
            pygame.draw.rect(surface, trail_color, trail_rect, border_radius=5)

            # Pulsing glow if being held
            if self.held:
                glow = pygame.Surface((TRAIL_W + 10, trail_rect.h + 10), pygame.SRCALPHA)
                glow.fill((*trail_color, 60))
                surface.blit(glow, (tx - 5, trail_rect.y - 5))

        # Draw head
        super().draw(surface)

        # Tail cap (small rectangle at trail top)
        if not self.hit:
            cap = pygame.Rect(
                self.x + 3, int(self.tail_y), LANE_W - 6, TILE_H // 2
            )
            pygame.draw.rect(surface, LANE_COLORS[self.lane], cap, border_radius=5)


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOATING TEXT
# ═══════════════════════════════════════════════════════════════════════════════
class FloatingText:
    def __init__(self, text, x, y, color, font):
        self.text  = text
        self.x     = x
        self.y     = float(y)
        self.color = color
        self.font  = font
        self.alpha = 255.0

    def update(self, dt):
        self.y    -= 55 * dt
        self.alpha = max(0.0, self.alpha - 420 * dt)

    def draw(self, surface):
        surf = self.font.render(self.text, True, self.color)
        surf.set_alpha(int(self.alpha))
        surface.blit(surf, (self.x - surf.get_width() // 2, int(self.y)))

    @property
    def alive(self):
        return self.alpha > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAYER STATE
# ═══════════════════════════════════════════════════════════════════════════════
class PlayerState:
    def __init__(self, x_offset: int, accent_color):
        self.x_offset    = x_offset
        self.accent      = accent_color
        self.tiles       = []
        self.score       = 0
        self.combo       = 0
        self.max_combo   = 0
        self.perfects    = 0
        self.goods       = 0
        self.misses      = 0
        self.lane_flash  = [0.0] * NUM_LANES
        self.held_lanes  = [False] * NUM_LANES   # which lanes currently held

    def reset(self):
        self.tiles      = []
        self.score      = 0
        self.combo      = 0
        self.max_combo  = 0
        self.perfects   = 0
        self.goods      = 0
        self.misses     = 0
        self.lane_flash = [0.0] * NUM_LANES
        self.held_lanes = [False] * NUM_LANES

    def spawn_tile(self, lane, is_hold, hold_dur):
        if is_hold:
            self.tiles.append(HoldTile(lane, self.x_offset, hold_dur))
        else:
            self.tiles.append(Tile(lane, self.x_offset))

    def press(self, lane, floating_texts, font_med):
        self.lane_flash[lane] = 1.0
        self.held_lanes[lane] = True

        candidates = [
            t for t in self.tiles
            if t.lane == lane
            and not t.hit
            and not t.missed
            and t.y > -TILE_H
            and t.center_y() < HIT_ZONE_Y + HIT_ZONE_H + 20
        ]
        if not candidates:
            return

        tile   = min(candidates, key=lambda t: t.hit_zone_offset())
        offset = tile.hit_zone_offset()
        lx     = self.x_offset + lane * LANE_W + LANE_W // 2

        if isinstance(tile, HoldTile):
            if offset <= GOOD_WINDOW:
                tile.head_hit = True
                tile.held     = True
                self.combo   += 1
                self.perfects += 1
                floating_texts.append(
                    FloatingText("HOLD!", lx, HIT_ZONE_Y - 20, HELD_COLOR, font_med)
                )
            else:
                self.combo  = 0
                self.misses += 1
                floating_texts.append(
                    FloatingText("MISS", lx, HIT_ZONE_Y - 20, MISS_COLOR, font_med)
                )
        else:
            if offset <= PERFECT_WINDOW:
                tile.hit      = True
                self.score   += SCORE_PERFECT * (1 + self.combo // 10)
                self.combo   += 1
                self.perfects += 1
                floating_texts.append(
                    FloatingText("PERFECT", lx, HIT_ZONE_Y - 20, PERFECT_COLOR, font_med)
                )
            elif offset <= GOOD_WINDOW:
                tile.hit     = True
                self.score  += SCORE_GOOD
                self.combo  += 1
                self.goods  += 1
                floating_texts.append(
                    FloatingText("GOOD", lx, HIT_ZONE_Y - 20, GOOD_COLOR, font_med)
                )
            else:
                self.combo  = 0
                self.misses += 1
                floating_texts.append(
                    FloatingText("MISS", lx, HIT_ZONE_Y - 20, MISS_COLOR, font_med)
                )

        self.max_combo = max(self.max_combo, self.combo)

    def release(self, lane):
        self.held_lanes[lane] = False
        for tile in self.tiles:
            if isinstance(tile, HoldTile) and tile.lane == lane and tile.held:
                tile.held = False
                if not tile.tail_in_hit_zone():
                    tile.released_early = True

    def update(self, dt):
        for tile in self.tiles:
            tile.update(dt)

            # Hold note scoring tick
            if isinstance(tile, HoldTile) and tile.held:
                self.score += SCORE_HOLD_TICK

            # Mark tap tiles as missed
            if not isinstance(tile, HoldTile):
                if not tile.hit and not tile.missed:
                    if tile.y > HIT_ZONE_Y + HIT_ZONE_H + TILE_H:
                        tile.missed = True
                        self.misses += 1
                        self.combo   = 0

            # Hold tile: complete when tail exits hit zone
            if isinstance(tile, HoldTile) and tile.head_hit:
                if tile.y > HIT_ZONE_Y + HIT_ZONE_H + TILE_H:
                    if tile.held:
                        tile.completed = True
                    elif not tile.released_early:
                        tile.completed = True
                    else:
                        tile.missed = True
                        self.misses += 1

        # Clean up
        self.tiles = [
            t for t in self.tiles
            if t.y < SCREEN_H + 200
            and not (isinstance(t, HoldTile) and t.completed)
        ]

        for i in range(NUM_LANES):
            self.lane_flash[i] = max(0.0, self.lane_flash[i] - 5.0 * dt)

    def draw_lanes(self, surface):
        for i in range(NUM_LANES):
            lx = self.x_offset + i * LANE_W
            pygame.draw.rect(surface, MID_GRAY, pygame.Rect(lx, 0, LANE_W, SCREEN_H))
            if self.lane_flash[i] > 0:
                fs = pygame.Surface((LANE_W, SCREEN_H), pygame.SRCALPHA)
                fs.fill((*LANE_COLORS[i], int(self.lane_flash[i] * 55)))
                surface.blit(fs, (lx, 0))
            pygame.draw.line(surface, BLACK, (lx, 0), (lx, SCREEN_H), 2)

    def draw_hit_zone(self, surface):
        hz = pygame.Rect(self.x_offset, HIT_ZONE_Y, NUM_LANES * LANE_W, HIT_ZONE_H)
        pygame.draw.rect(surface, (55, 55, 55), hz)
        pygame.draw.rect(surface, WHITE, hz, 2)
        for i in range(NUM_LANES):
            lx  = self.x_offset + i * LANE_W
            ind = pygame.Rect(lx + 8, HIT_ZONE_Y + 8, LANE_W - 16, HIT_ZONE_H - 16)
            col = LANE_COLORS[i] if self.lane_flash[i] > 0.3 else (75, 75, 75)
            pygame.draw.rect(surface, col, ind, border_radius=5)

    def draw_tiles(self, surface):
        for tile in self.tiles:
            tile.draw(surface)


# ═══════════════════════════════════════════════════════════════════════════════
#  GAME STATE ENUM
# ═══════════════════════════════════════════════════════════════════════════════
class Screen(Enum):
    MENU   = auto()
    GAME   = auto()
    PAUSE  = auto()
    RESULT = auto()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN GAME CLASS
# ═══════════════════════════════════════════════════════════════════════════════
class RhythmGame:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Rhythm Game")
        flags = pygame.FULLSCREEN if SERIAL_AVAILABLE else 0
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        self.clock  = pygame.time.Clock()

        self.font_xl   = pygame.font.SysFont("monospace", 58, bold=True)
        self.font_big  = pygame.font.SysFont("monospace", 42, bold=True)
        self.font_med  = pygame.font.SysFont("monospace", 28, bold=True)
        self.font_sm   = pygame.font.SysFont("monospace", 20)
        self.font_tiny = pygame.font.SysFont("monospace", 16)

        # Serial
        self.serial_q: queue.Queue = queue.Queue()
        if SERIAL_AVAILABLE:
            SerialReader(_ser, self.serial_q).start()

        # Players (x_offset: P1 starts at 0, P2 starts at HALF_W + DIVIDER_W)
        self.p1 = PlayerState(0,                      P1_ACCENT)
        self.p2 = PlayerState(HALF_W + DIVIDER_W,     P2_ACCENT)

        self.floating_texts = []

        # Menu state
        self.screen_state  = Screen.MENU
        self.menu_cursor   = 0
        self.selected_song: Optional[SongDef] = None

        # Game state
        self.song_start_time = 0.0
        self.pattern_index   = 0
        self.paused          = False
        self.pause_start     = 0.0
        self.total_paused    = 0.0
        self.song_elapsed    = 0.0

    # ── Input processing ──────────────────────────────────────────────────────
    def _drain_serial(self):
        events = {"p1_press": [], "p1_release": [],
                  "p2_press": [], "p2_release": [],
                  "nav": []}
        while not self.serial_q.empty():
            msg = self.serial_q.get_nowait()
            if msg in ("U", "D", "L", "R"):
                events["nav"].append(msg)
            elif msg.startswith("P1_") and msg.endswith("_R"):
                events["p1_release"].append(int(msg[3]))
            elif msg.startswith("P2_") and msg.endswith("_R"):
                events["p2_release"].append(int(msg[3]))
            elif msg.startswith("P1_"):
                events["p1_press"].append(int(msg[3]))
            elif msg.startswith("P2_"):
                events["p2_press"].append(int(msg[3]))
        return events

    # ── Menu ──────────────────────────────────────────────────────────────────
    def _menu_nav(self, direction):
        if direction == "U":
            self.menu_cursor = (self.menu_cursor - 1) % len(SONGS)
        elif direction == "D":
            self.menu_cursor = (self.menu_cursor + 1) % len(SONGS)
        elif direction == "R":
            self._start_game(SONGS[self.menu_cursor])

    def _start_game(self, song: SongDef):
        self.selected_song  = song
        self.p1.reset()
        self.p2.reset()
        self.floating_texts = []
        self.pattern_index  = 0
        self.total_paused   = 0.0
        self.song_elapsed   = 0.0
        self.song_start_time = time.time()
        self.screen_state   = Screen.GAME

    def _pause(self):
        self.paused      = True
        self.pause_start = time.time()
        self.screen_state = Screen.PAUSE

    def _resume(self):
        self.total_paused += time.time() - self.pause_start
        self.paused        = False
        self.screen_state  = Screen.GAME

    def _back_to_menu(self):
        self.screen_state = Screen.MENU
        self.paused       = False

    # ── Spawn tiles from pattern ───────────────────────────────────────────────
    def _spawn_from_pattern(self):
        song = self.selected_song
        while self.pattern_index < len(song.pattern):
            t, lane, is_hold, hold_dur = song.pattern[self.pattern_index]
            if self.song_elapsed >= t:
                self.p1.spawn_tile(lane, is_hold, hold_dur)
                self.p2.spawn_tile(lane, is_hold, hold_dur)
                self.pattern_index += 1
            else:
                break

        # Song finished — all tiles spawned, check if done
        if self.pattern_index >= len(song.pattern):
            last_t = song.pattern[-1][0] if song.pattern else 0
            if self.song_elapsed > last_t + 3.0:   # 3s grace after last note
                self.screen_state = Screen.RESULT

    # ── Update ────────────────────────────────────────────────────────────────
    def update(self, dt):
        events = self._drain_serial()

        if self.screen_state == Screen.MENU:
            for nav in events["nav"]:
                self._menu_nav(nav)

        elif self.screen_state == Screen.PAUSE:
            for nav in events["nav"]:
                if nav == "R":   self._resume()
                elif nav == "L": self._back_to_menu()

        elif self.screen_state == Screen.GAME:
            # Nav: L = pause, R = nothing in-game
            for nav in events["nav"]:
                if nav == "L":
                    self._pause()
                    return

            self.song_elapsed = time.time() - self.song_start_time - self.total_paused
            self._spawn_from_pattern()

            for lane in events["p1_press"]:
                self.p1.press(lane, self.floating_texts, self.font_med)
            for lane in events["p1_release"]:
                self.p1.release(lane)
            for lane in events["p2_press"]:
                self.p2.press(lane, self.floating_texts, self.font_med)
            for lane in events["p2_release"]:
                self.p2.release(lane)

            self.p1.update(dt)
            self.p2.update(dt)

            for ft in self.floating_texts:
                ft.update(dt)
            self.floating_texts = [ft for ft in self.floating_texts if ft.alive]

        elif self.screen_state == Screen.RESULT:
            for nav in events["nav"]:
                if nav == "L":
                    self._back_to_menu()

    # ══════════════════════════════════════════════════════════════════════════
    #  DRAW SCREENS
    # ══════════════════════════════════════════════════════════════════════════
    def draw(self):
        self.screen.fill(DARK_GRAY)

        if self.screen_state == Screen.MENU:
            self._draw_menu()
        elif self.screen_state in (Screen.GAME, Screen.PAUSE):
            self._draw_game()
            if self.screen_state == Screen.PAUSE:
                self._draw_pause_overlay()
        elif self.screen_state == Screen.RESULT:
            self._draw_result()

        pygame.display.flip()

    # ── Menu screen ───────────────────────────────────────────────────────────
    def _draw_menu(self):
        # Title
        title = self.font_big.render("RHYTHM GAME", True, WHITE)
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 30))

        sub = self.font_sm.render("UP / DOWN  to scroll      RIGHT  to select", True, (130, 130, 130))
        self.screen.blit(sub, (SCREEN_W // 2 - sub.get_width() // 2, 85))

        # Song list
        visible  = 5
        start    = max(0, self.menu_cursor - visible // 2)
        end      = min(len(SONGS), start + visible)
        item_h   = 64
        list_y   = 140

        for idx in range(start, end):
            song   = SONGS[idx]
            sel    = idx == self.menu_cursor
            iy     = list_y + (idx - start) * item_h
            bg_col = (50, 60, 80) if sel else (28, 28, 28)
            bdr    = P1_ACCENT if sel else (50, 50, 50)

            box = pygame.Rect(60, iy, SCREEN_W - 120, item_h - 6)
            pygame.draw.rect(self.screen, bg_col, box, border_radius=10)
            pygame.draw.rect(self.screen, bdr, box, 2, border_radius=10)

            t_col  = WHITE if sel else (180, 180, 180)
            t_surf = self.font_med.render(song.title, True, t_col)
            self.screen.blit(t_surf, (box.x + 18, iy + 8))

            bpm_s = self.font_tiny.render(f"{song.bpm} BPM", True, (120, 120, 120))
            self.screen.blit(bpm_s, (box.x + 18, iy + 36))

            if sel:
                arr = self.font_med.render("▶", True, P1_ACCENT)
                self.screen.blit(arr, (box.right - arr.get_width() - 16, iy + 14))

        # Cursor indicator dots
        dot_x = SCREEN_W - 30
        for i, _ in enumerate(SONGS):
            col = WHITE if i == self.menu_cursor else (60, 60, 60)
            pygame.draw.circle(self.screen, col, (dot_x, list_y + i * 12 + 6), 4)

    # ── Game screen ───────────────────────────────────────────────────────────
    def _draw_game(self):
        # Both player lanes
        self.p1.draw_lanes(self.screen)
        self.p2.draw_lanes(self.screen)

        # Right edge of P1 / left edge of P2
        pygame.draw.line(self.screen, BLACK,
                         (HALF_W, 0), (HALF_W, SCREEN_H), 2)
        pygame.draw.line(self.screen, BLACK,
                         (HALF_W + DIVIDER_W, 0), (HALF_W + DIVIDER_W, SCREEN_H), 2)

        # Divider bar
        div = pygame.Rect(HALF_W, 0, DIVIDER_W, SCREEN_H)
        pygame.draw.rect(self.screen, DIVIDER_COLOR, div)

        # Song title in divider
        song_chars = list(self.selected_song.title)
        for ci, ch in enumerate(song_chars[:20]):
            cs = self.font_tiny.render(ch, True, (160, 160, 160))
            self.screen.blit(cs, (HALF_W + 1, 20 + ci * 20))

        # Hit zones
        self.p1.draw_hit_zone(self.screen)
        self.p2.draw_hit_zone(self.screen)

        # Tiles
        self.p1.draw_tiles(self.screen)
        self.p2.draw_tiles(self.screen)

        # Floating feedback text
        for ft in self.floating_texts:
            ft.draw(self.screen)

        # ── HUD ───────────────────────────────────────────────────────────────
        self._draw_hud(self.p1, "P1", 0)
        self._draw_hud(self.p2, "P2", HALF_W + DIVIDER_W)

        # Pause hint
        hint = self.font_tiny.render("◄ PAUSE", True, (80, 80, 80))
        self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 20))

    def _draw_hud(self, player: PlayerState, label: str, x_off: int):
        # Player label
        lbl = self.font_sm.render(label, True, player.accent)
        self.screen.blit(lbl, (x_off + 6, 6))

        # Score
        sc = self.font_big.render(f"{player.score:,}", True, WHITE)
        self.screen.blit(sc, (x_off + 6, 26))

        # Combo
        if player.combo > 1:
            col  = PERFECT_COLOR if player.combo >= 10 else WHITE
            cmb  = self.font_med.render(f"×{player.combo}", True, col)
            self.screen.blit(cmb, (x_off + HALF_W - cmb.get_width() - 8, 6))

        # Stats
        stats = self.font_tiny.render(
            f"P:{player.perfects} G:{player.goods} M:{player.misses}",
            True, (130, 130, 130)
        )
        self.screen.blit(stats, (x_off + 6, SCREEN_H - 20))

    # ── Pause overlay ─────────────────────────────────────────────────────────
    def _draw_pause_overlay(self):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        pause_txt = self.font_xl.render("PAUSED", True, WHITE)
        self.screen.blit(pause_txt,
                         (SCREEN_W // 2 - pause_txt.get_width() // 2, 160))

        lines = [
            ("► RESUME",    P1_ACCENT),
            ("◄ MAIN MENU", MISS_COLOR),
        ]
        for i, (txt, col) in enumerate(lines):
            s = self.font_med.render(txt, True, col)
            self.screen.blit(s, (SCREEN_W // 2 - s.get_width() // 2, 270 + i * 50))

    # ── Result screen ─────────────────────────────────────────────────────────
    def _draw_result(self):
        title = self.font_big.render("RESULTS", True, WHITE)
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 20))

        song_s = self.font_sm.render(self.selected_song.title, True, (160, 160, 160))
        self.screen.blit(song_s, (SCREEN_W // 2 - song_s.get_width() // 2, 72))

        # Winner banner
        if self.p1.score > self.p2.score:
            w_txt, w_col = "P1 WINS!", P1_ACCENT
        elif self.p2.score > self.p1.score:
            w_txt, w_col = "P2 WINS!", P2_ACCENT
        else:
            w_txt, w_col = "DRAW!", WHITE

        win = self.font_xl.render(w_txt, True, w_col)
        self.screen.blit(win, (SCREEN_W // 2 - win.get_width() // 2, 105))

        # Score cards
        self._draw_result_card(self.p1, "PLAYER 1", 40,  P1_ACCENT)
        self._draw_result_card(self.p2, "PLAYER 2", SCREEN_W // 2 + 10, P2_ACCENT)

        back = self.font_sm.render("◄  BACK TO MENU", True, (150, 150, 150))
        self.screen.blit(back, (SCREEN_W // 2 - back.get_width() // 2, SCREEN_H - 36))

    def _draw_result_card(self, player: PlayerState, label: str, x: int, accent):
        card = pygame.Rect(x, 200, SCREEN_W // 2 - 50, 230)
        pygame.draw.rect(self.screen, (30, 30, 30), card, border_radius=12)
        pygame.draw.rect(self.screen, accent, card, 2, border_radius=12)

        lbl = self.font_med.render(label, True, accent)
        self.screen.blit(lbl, (card.x + 12, card.y + 12))

        rows = [
            ("SCORE",    f"{player.score:,}"),
            ("PERFECT",  str(player.perfects)),
            ("GOOD",     str(player.goods)),
            ("MISS",     str(player.misses)),
            ("MAX COMBO",str(player.max_combo)),
        ]
        for i, (k, v) in enumerate(rows):
            ky = self.font_sm.render(k, True, (140, 140, 140))
            vy = self.font_sm.render(v, True, WHITE)
            ry = card.y + 52 + i * 34
            self.screen.blit(ky, (card.x + 12, ry))
            self.screen.blit(vy, (card.right - vy.get_width() - 12, ry))

    # ══════════════════════════════════════════════════════════════════════════
    #  KEYBOARD FALLBACK (dev/testing)
    # ══════════════════════════════════════════════════════════════════════════
    P1_KEYS = {pygame.K_a: 0, pygame.K_s: 1, pygame.K_k: 2, pygame.K_l: 3}
    P2_KEYS = {pygame.K_f: 0, pygame.K_g: 1, pygame.K_h: 2, pygame.K_j: 3}

    def _handle_keydown(self, key):
        if key == pygame.K_ESCAPE:
            self.quit()

        if self.screen_state == Screen.MENU:
            if key == pygame.K_UP:        self._menu_nav("U")
            elif key == pygame.K_DOWN:    self._menu_nav("D")
            elif key == pygame.K_RETURN:  self._menu_nav("R")

        elif self.screen_state == Screen.GAME:
            if key == pygame.K_p:
                self._pause()
            if key in self.P1_KEYS:
                self.p1.press(self.P1_KEYS[key], self.floating_texts, self.font_med)
            if key in self.P2_KEYS:
                self.p2.press(self.P2_KEYS[key], self.floating_texts, self.font_med)

        elif self.screen_state == Screen.PAUSE:
            if key == pygame.K_RETURN:    self._resume()
            elif key == pygame.K_BACKSPACE: self._back_to_menu()

        elif self.screen_state == Screen.RESULT:
            if key == pygame.K_BACKSPACE: self._back_to_menu()

    def _handle_keyup(self, key):
        if self.screen_state == Screen.GAME:
            if key in self.P1_KEYS:
                self.p1.release(self.P1_KEYS[key])
            if key in self.P2_KEYS:
                self.p2.release(self.P2_KEYS[key])

    # ══════════════════════════════════════════════════════════════════════════
    #  MAIN LOOP
    # ══════════════════════════════════════════════════════════════════════════
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                if event.type == pygame.KEYDOWN:
                    self._handle_keydown(event.key)
                if event.type == pygame.KEYUP:
                    self._handle_keyup(event.key)

            self.update(dt)
            self.draw()

    def quit(self):
        pygame.quit()
        sys.exit()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    game = RhythmGame()
    game.run()