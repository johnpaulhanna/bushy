"""
Bush sprite extraction and rendering for the click tracker.
Loads bush_spritesheet.png (with true transparency), extracts 6 bush stages,
scales them up, and handles dynamic flower overlay and color transitions.
"""

import tkinter as tk
import os
import sys
import random


def resource_path(relative):
    """Resolve asset path for both dev and PyInstaller frozen mode."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


SPRITESHEET_PATH = resource_path("bush_spritesheet.png")

# Bounding boxes for each sprite in the spritesheet: (x1, y1, x2, y2) inclusive
SPRITE_BOUNDS = [
    (4, 70, 12, 77),      # 1. Seedling
    (16, 64, 29, 77),     # 2. Sprout
    (33, 62, 45, 77),     # 3. Young
    (50, 59, 67, 78),     # 4. Growing
    (72, 55, 93, 78),     # 5. Mature
    (97, 52, 123, 79),    # 6. Full Bush
]

# Bush size thresholds (key presses)
BUSH_THRESHOLDS = [0, 1_000, 10_000, 100_000, 1_000_000, 10_000_000]

# Flower stage thresholds (mouse clicks)
FLOWER_THRESHOLDS = [0, 200, 500, 1_000, 3_000, 8_000, 20_000, 50_000, 100_000, 300_000, 700_000, 1_000_000]

# Flower colors per stage (index 0 = no flowers)
FLOWER_COLORS = [
    None,          # 0: no flowers
    "#a0c060",     # 1: buds (yellow-green)
    "#f0f0e0",     # 2: white flowers
    "#f0a0b0",     # 3: pink flowers
    "#c03040",     # 4: dark red
    "#e02020",     # 5: crimson
    "#d020a0",     # 6: magenta
    "#9030d0",     # 7: purple
    "#3060e0",     # 8: blue
    "#20a0a0",     # 9: teal
    "#60e0e0",     # 10: cyan-white
    "#f0c020",     # 11: golden
]

GROUND_FLOWER_COLORS = ["#f06080", "#f0a040", "#e0e060", "#a0d0f0", "#f0f0f0"]


def get_bush_stage(key_presses):
    stage = 0
    for i, threshold in enumerate(BUSH_THRESHOLDS):
        if key_presses >= threshold:
            stage = i
    return stage


def get_flower_stage(mouse_clicks):
    stage = 0
    for i, threshold in enumerate(FLOWER_THRESHOLDS):
        if mouse_clicks >= threshold:
            stage = i
    return stage


def lerp_color(c1, c2, t):
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_green_foliage(r, g, b):
    """Check if a pixel is green foliage (candidate for flower placement)."""
    return g > 80 and g > r * 1.3 and g > b * 1.2 and r < 200


class SpriteManager:
    """Loads the spritesheet and extracts individual bush sprites."""

    def __init__(self, root, scale=4):
        self._root = root
        self._scale = scale
        self._sheet = tk.PhotoImage(file=SPRITESHEET_PATH)
        self._sprites = []       # List of tk.PhotoImage (scaled) for each stage
        self._raw_sprites = []   # Unscaled sprites (for pixel manipulation)
        self._raw_sizes = []     # (w, h) of each raw sprite
        self._flower_maps = []   # List of [(x,y), ...] foliage pixel coords (in raw coords)
        self._extract_sprites()

    def _extract_sprites(self):
        """Extract each bush sprite using transparency."""
        sheet = self._sheet
        for idx, (x1, y1, x2, y2) in enumerate(SPRITE_BOUNDS):
            w = x2 - x1 + 1
            h = y2 - y1 + 1
            sprite = tk.PhotoImage(width=w, height=h)
            flower_positions = []

            for sy in range(h):
                for sx in range(w):
                    px = x1 + sx
                    py = y1 + sy
                    if not sheet.transparency_get(px, py):
                        r, g, b = sheet.get(px, py)
                        color = f"#{r:02x}{g:02x}{b:02x}"
                        sprite.put(color, to=(sx, sy))
                        if _is_green_foliage(r, g, b):
                            flower_positions.append((sx, sy))

            self._raw_sprites.append(sprite)
            self._raw_sizes.append((w, h))

            # Scale up using zoom
            scaled = sprite.zoom(self._scale)
            self._sprites.append(scaled)

            # Select flower positions — spaced apart so multi-pixel flowers don't overlap
            rng = random.Random(42 + idx)
            rng.shuffle(flower_positions)
            selected = []
            for pos in flower_positions:
                # Ensure minimum 4px distance from other flowers
                too_close = False
                for sx, sy in selected:
                    if abs(pos[0] - sx) < 4 and abs(pos[1] - sy) < 4:
                        too_close = True
                        break
                if not too_close:
                    selected.append(pos)
                if len(selected) >= max(3, len(flower_positions) // 10):
                    break
            self._flower_maps.append(selected)

    def get_sprite(self, stage_index):
        return self._sprites[stage_index]

    def get_flower_positions(self, stage_index):
        return self._flower_maps[stage_index]

    def get_sprite_size(self, stage_index):
        s = self._sprites[stage_index]
        return s.width(), s.height()

    def _draw_flower(self, img, cx, cy, color, flower_stage, w, h):
        """Draw a flower shape centered at (cx, cy) in raw pixel coords."""
        # Clamp helper
        def put_if_valid(c, x, y):
            if 0 <= x < w and 0 <= y < h:
                img.put(c, to=(x, y))

        if flower_stage <= 2:
            # Early stages: small '+' cross (3px)
            put_if_valid(color, cx, cy)
            put_if_valid(color, cx - 1, cy)
            put_if_valid(color, cx + 1, cy)
            put_if_valid(color, cx, cy - 1)
            put_if_valid(color, cx, cy + 1)
        elif flower_stage <= 5:
            # Mid stages: '+' cross with contrasting center
            center = "#ffffa0" if flower_stage < 5 else "#ffe040"
            put_if_valid(color, cx - 1, cy)
            put_if_valid(color, cx + 1, cy)
            put_if_valid(color, cx, cy - 1)
            put_if_valid(color, cx, cy + 1)
            put_if_valid(center, cx, cy)
        elif flower_stage <= 8:
            # High stages: diamond/star with bright center
            center = "#fffff0"
            put_if_valid(color, cx - 1, cy)
            put_if_valid(color, cx + 1, cy)
            put_if_valid(color, cx, cy - 1)
            put_if_valid(color, cx, cy + 1)
            put_if_valid(color, cx - 1, cy - 1)
            put_if_valid(color, cx + 1, cy - 1)
            put_if_valid(color, cx - 1, cy + 1)
            put_if_valid(color, cx + 1, cy + 1)
            put_if_valid(center, cx, cy)
        else:
            # Max stages: full bloom — 3x3 petals with bright center + outer accents
            center = "#ffffff"
            # Inner petals
            put_if_valid(color, cx - 1, cy)
            put_if_valid(color, cx + 1, cy)
            put_if_valid(color, cx, cy - 1)
            put_if_valid(color, cx, cy + 1)
            # Diagonal petals
            put_if_valid(color, cx - 1, cy - 1)
            put_if_valid(color, cx + 1, cy - 1)
            put_if_valid(color, cx - 1, cy + 1)
            put_if_valid(color, cx + 1, cy + 1)
            # Outer tips
            put_if_valid(color, cx - 2, cy)
            put_if_valid(color, cx + 2, cy)
            put_if_valid(color, cx, cy - 2)
            put_if_valid(color, cx, cy + 2)
            put_if_valid(center, cx, cy)

    def create_flowered_sprite(self, stage_index, flower_stage):
        """Create a scaled sprite with flowers overlaid."""
        raw = self._raw_sprites[stage_index]
        rw, rh = self._raw_sizes[stage_index]
        result = raw.copy()

        if flower_stage > 0 and flower_stage < len(FLOWER_COLORS):
            color = FLOWER_COLORS[flower_stage]
            if color:
                positions = self._flower_maps[stage_index]
                for x, y in positions:
                    self._draw_flower(result, x, y, color, flower_stage, rw, rh)

        return result.zoom(self._scale)

    def create_animated_frame(self, old_bush, old_flower, new_bush, new_flower, t):
        """Create an interpolated frame between two states."""
        if old_bush != new_bush:
            if t < 0.5:
                return self.create_flowered_sprite(old_bush, old_flower)
            else:
                return self.create_flowered_sprite(new_bush, new_flower)
        else:
            if old_flower == 0:
                old_color = "#4a9c2a"
            else:
                old_color = FLOWER_COLORS[old_flower]
            new_color = FLOWER_COLORS[new_flower] if new_flower > 0 else "#4a9c2a"

            blended = lerp_color(old_color, new_color, t)

            raw = self._raw_sprites[new_bush]
            rw, rh = self._raw_sizes[new_bush]
            result = raw.copy()

            target_stage = max(new_flower, old_flower)
            positions = self._flower_maps[new_bush]
            for x, y in positions:
                self._draw_flower(result, x, y, blended, target_stage, rw, rh)

            return result.zoom(self._scale)
