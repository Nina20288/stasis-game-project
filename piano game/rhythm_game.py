#!/usr/bin/env python3
"""
Piano Tiles Rhythm Game
For Raspberry Pi + AT070TN92V.X 7" HDMI display (800x480)
Button input from Arduino over USB Serial

Requirements:
    pip install pygame pyserial

Arduino sends "0\n", "1\n", "2\n", or "3\n" when a button is pressed.

Run:
    python3 rhythm_game.py

    If Arduino is not on /dev/ttyUSB0, check with:
        ls /dev/ttyUSB* /dev/ttyACM*
    and update SERIAL_PORT below.

Keyboard fallback (for testing without Arduino):
    A = Lane 0, S = Lane 1, K = Lane 2, L = Lane 3
    ESC = Quit, R = Restart
"""

import pygame
import sys
import random
import time
import threading
import queue

# ── Serial config ─────────────────────────────────────────────────────────────
SERIAL_PORT = "/dev/ttyUSB0"   # change to /dev/ttyACM0 if ttyUSB0 not found
BAUD_RATE   = 9600

# ── Try to open serial port ───────────────────────────────────────────────────
try:
    import serial
    _ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    SERIAL_AVAILABLE = True
    print(f"[INFO] Serial connected on {SERIAL_PORT}")
except Exception as e:
    SERIAL_AVAILABLE = False
    print(f"[INFO] Serial not available ({e}) — keyboard-only mode.")

# ── Display / Layout Constants ────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 800, 480
FPS = 60

NUM_LANES     = 4
LANE_W        = 160
LANE_OFFSET_X = 80
TILE_H        = 80
HIT_ZONE_Y    = SCREEN_H - 90
HIT_ZONE_H    = 70

# ── Colors ────────────────────────────────────────────────────────────────────
BLACK         = (0,   0,   0)
WHITE         = (255, 255, 255)
DARK_GRAY     = (20,  20,  20)
MID_GRAY      = (45,  45,  45)
LANE_COLORS   = [
    (0,   200, 255),
    (0,   255, 160),
    (255, 200,   0),
    (255,  80, 120),
]
PERFECT_COLOR = (0,   255, 160)
GOOD_COLOR    = (255, 200,   0)
MISS_COLOR    = (255,  50,  50)

# ── Keyboard fallback ─────────────────────────────────────────────────────────
KEY_MAP = {
    pygame.K_a: 0,
    pygame.K_s: 1,
    pygame.K_k: 2,
    pygame.K_l: 3,
}

# ── Tile generation ───────────────────────────────────────────────────────────
SPAWN_INTERVAL = 0.55   # seconds between spawns
TILE_SPEED     = 280    # pixels per second

def generate_tile_batch():
    count = random.choices([1, 2], weights=[75, 25])[0]
    return random.sample(range(NUM_LANES), count)

# ── Scoring ───────────────────────────────────────────────────────────────────
PERFECT_WINDOW = 35
GOOD_WINDOW    = 65
SCORE_PERFECT  = 100
SCORE_GOOD     = 60


# ═════════════════════════════════════════════════════════════════════════════
class SerialReader(threading.Thread):
    """
    Background thread: reads lines from Arduino serial, puts lane
    numbers (int 0-3) into a thread-safe queue for the main loop.
    """
    def __init__(self, ser, q):
        super().__init__(daemon=True)
        self.ser = ser
        self.q   = q

    def run(self):
        while True:
            try:
                line = self.ser.readline().decode("utf-8").strip()
                if line in ("0", "1", "2", "3"):
                    self.q.put(int(line))
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════════
class Tile:
    def __init__(self, lane: int):
        self.lane   = lane
        self.y      = float(-TILE_H)
        self.hit    = False
        self.missed = False

    @property
    def x(self):
        return LANE_OFFSET_X + self.lane * LANE_W

    @property
    def rect(self):
        return pygame.Rect(self.x + 4, int(self.y), LANE_W - 8, TILE_H)

    def update(self, dt):
        if not self.hit:
            self.y += TILE_SPEED * dt

    def draw(self, surface):
        if self.hit:
            return
        color = LANE_COLORS[self.lane] if not self.missed else (80, 80, 80)
        r = self.rect

        shadow = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 80))
        surface.blit(shadow, (r.x + 3, r.y + 3))

        pygame.draw.rect(surface, color, r, border_radius=8)

        hl = pygame.Surface((r.w - 12, 10), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 60))
        surface.blit(hl, (r.x + 6, r.y + 6))

    def center_y(self):
        return self.y + TILE_H / 2

    def hit_zone_offset(self):
        hz_center = HIT_ZONE_Y + HIT_ZONE_H / 2
        return abs(self.center_y() - hz_center)


# ═════════════════════════════════════════════════════════════════════════════
class FloatingText:
    def __init__(self, text, x, y, color, font):
        self.text  = text
        self.x     = x
        self.y     = float(y)
        self.color = color
        self.font  = font
        self.alpha = 255.0
        self.age   = 0.0

    def update(self, dt):
        self.age  += dt
        self.y    -= 60 * dt
        self.alpha = max(0.0, 255 - self.age * 500)

    def draw(self, surface):
        surf = self.font.render(self.text, True, self.color)
        surf.set_alpha(int(self.alpha))
        surface.blit(surf, (self.x - surf.get_width() // 2, int(self.y)))

    @property
    def alive(self):
        return self.alpha > 0


# ═════════════════════════════════════════════════════════════════════════════
class RhythmGame:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Rhythm Game")

        flags = pygame.FULLSCREEN if SERIAL_AVAILABLE else 0
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        self.clock  = pygame.time.Clock()

        self.font_big  = pygame.font.SysFont("monospace", 52, bold=True)
        self.font_med  = pygame.font.SysFont("monospace", 32, bold=True)
        self.font_tiny = pygame.font.SysFont("monospace", 18)

        self.serial_queue: queue.Queue = queue.Queue()
        if SERIAL_AVAILABLE:
            SerialReader(_ser, self.serial_queue).start()

        self.reset()

    def reset(self):
        self.tiles          = []
        self.floating_texts = []
        self.score       = 0
        self.combo       = 0
        self.max_combo   = 0
        self.misses      = 0
        self.perfects    = 0
        self.goods       = 0
        self.spawn_timer = 0.0
        self.lane_flash  = [0.0] * NUM_LANES
        self.start_time  = time.time()

    def press_lane(self, lane: int):
        self.lane_flash[lane] = 1.0

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
        lx     = LANE_OFFSET_X + lane * LANE_W + LANE_W // 2

        if offset <= PERFECT_WINDOW:
            tile.hit   = True
            self.score += SCORE_PERFECT * (1 + self.combo // 10)
            self.combo += 1
            self.perfects += 1
            self._float("PERFECT", lx, HIT_ZONE_Y - 20, PERFECT_COLOR)
        elif offset <= GOOD_WINDOW:
            tile.hit   = True
            self.score += SCORE_GOOD
            self.combo += 1
            self.goods += 1
            self._float("GOOD", lx, HIT_ZONE_Y - 20, GOOD_COLOR)
        else:
            self.combo  = 0
            self.misses += 1
            self._float("MISS", lx, HIT_ZONE_Y - 20, MISS_COLOR)

        self.max_combo = max(self.max_combo, self.combo)

    def _float(self, text, x, y, color):
        self.floating_texts.append(FloatingText(text, x, y, color, self.font_med))

    def update(self, dt):
        while not self.serial_queue.empty():
            self.press_lane(self.serial_queue.get_nowait())

        self.spawn_timer += dt
        if self.spawn_timer >= SPAWN_INTERVAL:
            self.spawn_timer -= SPAWN_INTERVAL
            for lane in generate_tile_batch():
                self.tiles.append(Tile(lane))

        for tile in self.tiles:
            tile.update(dt)

        for tile in self.tiles:
            if not tile.hit and not tile.missed:
                if tile.y > HIT_ZONE_Y + HIT_ZONE_H + TILE_H:
                    tile.missed = True
                    self.misses += 1
                    self.combo   = 0

        self.tiles = [t for t in self.tiles if t.y < SCREEN_H + TILE_H * 2]

        for ft in self.floating_texts:
            ft.update(dt)
        self.floating_texts = [ft for ft in self.floating_texts if ft.alive]

        for i in range(NUM_LANES):
            self.lane_flash[i] = max(0.0, self.lane_flash[i] - 5.0 * dt)

    def draw(self):
        self.screen.fill(DARK_GRAY)

        for i in range(NUM_LANES):
            lx = LANE_OFFSET_X + i * LANE_W
            pygame.draw.rect(self.screen, MID_GRAY, pygame.Rect(lx, 0, LANE_W, SCREEN_H))
            if self.lane_flash[i] > 0:
                fs = pygame.Surface((LANE_W, SCREEN_H), pygame.SRCALPHA)
                fs.fill((*LANE_COLORS[i], int(self.lane_flash[i] * 60)))
                self.screen.blit(fs, (lx, 0))
            pygame.draw.line(self.screen, BLACK, (lx, 0), (lx, SCREEN_H), 2)

        pygame.draw.line(
            self.screen, BLACK,
            (LANE_OFFSET_X + NUM_LANES * LANE_W, 0),
            (LANE_OFFSET_X + NUM_LANES * LANE_W, SCREEN_H), 2
        )

        hz = pygame.Rect(LANE_OFFSET_X, HIT_ZONE_Y, NUM_LANES * LANE_W, HIT_ZONE_H)
        pygame.draw.rect(self.screen, (60, 60, 60), hz)
        pygame.draw.rect(self.screen, WHITE, hz, 2)
        for i in range(NUM_LANES):
            lx  = LANE_OFFSET_X + i * LANE_W
            ind = pygame.Rect(lx + 10, HIT_ZONE_Y + 10, LANE_W - 20, HIT_ZONE_H - 20)
            col = LANE_COLORS[i] if self.lane_flash[i] > 0.3 else (80, 80, 80)
            pygame.draw.rect(self.screen, col, ind, border_radius=6)

        for tile in self.tiles:
            tile.draw(self.screen)

        for ft in self.floating_texts:
            ft.draw(self.screen)

        self.screen.blit(self.font_big.render(f"{self.score:,}", True, WHITE), (10, 10))

        if self.combo > 1:
            col  = PERFECT_COLOR if self.combo >= 10 else WHITE
            surf = self.font_med.render(f"x{self.combo} COMBO", True, col)
            self.screen.blit(surf, (SCREEN_W - surf.get_width() - 10, 10))

        elapsed = int(time.time() - self.start_time)
        stats   = f"P:{self.perfects}  G:{self.goods}  M:{self.misses}  {elapsed}s"
        self.screen.blit(
            self.font_tiny.render(stats, True, (160, 160, 160)), (10, SCREEN_H - 28)
        )

        if not SERIAL_AVAILABLE:
            hint = self.font_tiny.render("A  S       K  L", True, (100, 100, 100))
            self.screen.blit(hint, (SCREEN_W - hint.get_width() - 10, SCREEN_H - 28))

        pygame.display.flip()

    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.quit()
                    if event.key == pygame.K_r:
                        self.reset()
                    lane = KEY_MAP.get(event.key)
                    if lane is not None:
                        self.press_lane(lane)

            self.update(dt)
            self.draw()

    def quit(self):
        pygame.quit()
        sys.exit()


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    game = RhythmGame()
    game.run()