import tkinter as tk
import ctypes
import ctypes.wintypes as wt
import threading
import json
import os
import sys
import time
import random
import logging
import logging.handlers
import winreg

from bush_sprites import (
    SpriteManager, FLOWER_COLORS,
    get_bush_stage, get_flower_stage, lerp_color, resource_path,
)

# ---------------------------------------------------------------------------
# Paths — assets via resource_path(), user data in %APPDATA%
# ---------------------------------------------------------------------------
APP_NAME = "ClickTracker"
__version__ = "1.0.0"

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
os.makedirs(DATA_DIR, exist_ok=True)

DATA_FILE = os.path.join(DATA_DIR, "tracker_data.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "clicktracker.log")

# Migrate old data file sitting next to the script/exe
_old_data = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "tracker_data.json")
if os.path.exists(_old_data) and not os.path.exists(DATA_FILE):
    try:
        import shutil
        shutil.move(_old_data, DATA_FILE)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.DEBUG)
_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# DPI awareness — call before any tkinter usage
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _get_dpi_scale():
    """Return a scale multiplier based on primary monitor DPI."""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(2, round(4 * dpi / 96))
    except Exception:
        return 4


# ---------------------------------------------------------------------------
# Constants for Windows hooks
# ---------------------------------------------------------------------------
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

HOOKPROC = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
user32.CallNextHookEx.restype = ctypes.c_long
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wt.BOOL

# Single-instance mutex
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.GetLastError.restype = wt.DWORD

SAVE_INTERVAL = 30
BG_COLOR = "#010101"
ANIM_FRAMES = 15
ANIM_MS = 50

# Stats panel colors
STATS_BG = "#1a3a10"
STATS_INNER = "#243d18"
TEXT_COLOR = "#e8f0d8"
TEXT_DIM = "#8aaa6a"
FONT_FAMILY = "Iosevka Charon Mono"

VINE_DARK = "#0e2a06"
VINE_MED = "#1a4a0a"
VINE_LIGHT = "#2d6b1e"
LEAF_GREEN = "#4a9c2a"
LEAF_LIGHT = "#6db33f"

# Startup registry key
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "ClickTracker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_fonts():
    FR_PRIVATE = 0x10
    fonts_dir = resource_path("fonts")
    for name in ["IosevkaCharonMono-Regular.ttf", "IosevkaCharonMono-Bold.ttf"]:
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            gdi32.AddFontResourceExW(path, FR_PRIVATE, 0)
        else:
            logger.warning("Font not found: %s", path)


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            mc = data.get("mouse_clicks", 0)
            kp = data.get("key_presses", 0)
            if isinstance(mc, int) and mc >= 0 and isinstance(kp, int) and kp >= 0:
                return {"mouse_clicks": mc, "key_presses": kp}
            logger.warning("Invalid values in tracker_data.json, resetting")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Corrupt tracker_data.json: %s — backing up", e)
            try:
                import shutil
                shutil.copy2(DATA_FILE, DATA_FILE + ".bak")
            except Exception:
                pass
    return {"mouse_clicks": 0, "key_presses": 0}


def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    except IOError as e:
        logger.error("Failed to save data: %s", e)


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
    except Exception as e:
        logger.error("Failed to save settings: %s", e)


def format_count(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def is_startup_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, STARTUP_REG_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup_enabled(enabled):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            exe_path = sys.executable
            script = os.path.abspath(sys.argv[0])
            if getattr(sys, 'frozen', False):
                cmd = f'"{exe_path}"'
            else:
                cmd = f'"{exe_path}" "{script}"'
            winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_REG_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logger.error("Failed to update startup registry: %s", e)


def _draw_vine_border(canvas, w, h, ps, flower_color=None):
    """Draw a pixel art vine/leaf border on the canvas."""
    rng = random.Random(123)

    canvas.create_rectangle(0, 0, w, h, fill=STATS_BG, outline="")

    border_w = ps * 3
    canvas.create_rectangle(border_w, border_w, w - border_w, h - border_w,
                            fill=STATS_INNER, outline="")

    for x in range(0, w, ps):
        canvas.create_rectangle(x, 0, x + ps, ps, fill=VINE_DARK, outline="")
        canvas.create_rectangle(x, ps, x + ps, ps * 2, fill=VINE_MED, outline="")
        if rng.random() < 0.25:
            canvas.create_rectangle(x, ps * 2, x + ps, ps * 3, fill=LEAF_GREEN, outline="")
        if rng.random() < 0.12 and flower_color:
            canvas.create_rectangle(x, ps, x + ps, ps * 2, fill=flower_color, outline="")

    for x in range(0, w, ps):
        canvas.create_rectangle(x, h - ps, x + ps, h, fill=VINE_DARK, outline="")
        canvas.create_rectangle(x, h - ps * 2, x + ps, h - ps, fill=VINE_MED, outline="")
        if rng.random() < 0.25:
            canvas.create_rectangle(x, h - ps * 3, x + ps, h - ps * 2, fill=LEAF_GREEN, outline="")
        if rng.random() < 0.12 and flower_color:
            canvas.create_rectangle(x, h - ps * 2, x + ps, h - ps, fill=flower_color, outline="")

    for y in range(0, h, ps):
        canvas.create_rectangle(0, y, ps, y + ps, fill=VINE_DARK, outline="")
        canvas.create_rectangle(ps, y, ps * 2, y + ps, fill=VINE_MED, outline="")
        if rng.random() < 0.25:
            canvas.create_rectangle(ps * 2, y, ps * 3, y + ps, fill=LEAF_GREEN, outline="")
        if rng.random() < 0.12 and flower_color:
            canvas.create_rectangle(ps, y, ps * 2, y + ps, fill=flower_color, outline="")

    for y in range(0, h, ps):
        canvas.create_rectangle(w - ps, y, w, y + ps, fill=VINE_DARK, outline="")
        canvas.create_rectangle(w - ps * 2, y, w - ps, y + ps, fill=VINE_MED, outline="")
        if rng.random() < 0.25:
            canvas.create_rectangle(w - ps * 3, y, w - ps * 2, y + ps, fill=LEAF_GREEN, outline="")
        if rng.random() < 0.12 and flower_color:
            canvas.create_rectangle(w - ps * 2, y, w - ps, y + ps, fill=flower_color, outline="")

    for cx, cy in [(0, 0), (w - ps * 3, 0), (0, h - ps * 3), (w - ps * 3, h - ps * 3)]:
        canvas.create_rectangle(cx, cy, cx + ps * 3, cy + ps * 3, fill=LEAF_GREEN, outline="")
        canvas.create_rectangle(cx + ps, cy + ps, cx + ps * 2, cy + ps * 2,
                                fill=LEAF_LIGHT, outline="")
        if flower_color:
            canvas.create_rectangle(cx + ps, cy, cx + ps * 2, cy + ps,
                                    fill=flower_color, outline="")


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------
def _acquire_mutex():
    """Return mutex handle if we're the first instance, None otherwise."""
    mutex = kernel32.CreateMutexW(None, False, "Global\\ClickTrackerMutex_v1")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return mutex


# ---------------------------------------------------------------------------
# System tray
# ---------------------------------------------------------------------------
def _create_tray_icon(tracker):
    """Run pystray in its own thread."""
    try:
        import pystray
        from PIL import Image

        img_path = resource_path("bush_spritesheet.png")
        img = Image.open(img_path)
        # Crop the full bush sprite for the icon
        icon_img = img.crop((97, 52, 124, 80)).resize((64, 64), Image.NEAREST)

        def toggle_visible(icon, item):
            tracker.root.after(0, tracker._toggle_visibility)

        def toggle_startup(icon, item):
            tracker.root.after(0, tracker._toggle_startup)

        def reset_counts(icon, item):
            tracker.root.after(0, tracker._reset)

        def show_about(icon, item):
            tracker.root.after(0, tracker._show_about)

        def quit_app(icon, item):
            tracker.root.after(0, tracker._quit)

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", toggle_visible, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                toggle_startup,
                checked=lambda item: is_startup_enabled(),
            ),
            pystray.MenuItem("Reset Counts", reset_counts),
            pystray.MenuItem(f"About (v{__version__})", show_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        )

        icon = pystray.Icon(APP_NAME, icon_img, "Click Tracker", menu)
        tracker._tray_icon = icon
        icon.run()
    except Exception as e:
        logger.error("Failed to create tray icon: %s", e)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class ClickTracker:
    def __init__(self):
        _load_fonts()
        self.data = load_data()
        self.settings = load_settings()
        self.mouse_clicks = self.data["mouse_clicks"]
        self.key_presses = self.data["key_presses"]
        self.expanded = False
        self.running = True
        self._drag_x = 0
        self._drag_y = 0
        self._pending_update = False
        self._animating = False
        self._current_sprite_ref = None
        self._tray_icon = None
        self._visible = True
        self._tooltip_win = None
        self._hover_bright = False
        self._dpi_scale = _get_dpi_scale()
        self._ps = max(2, round(3 * self._dpi_scale / 4))  # border pixel size scales with DPI

        self._visual_bush_stage = get_bush_stage(self.key_presses)
        self._visual_flower_stage = get_flower_stage(self.mouse_clicks)

        self._mouse_hook_proc = HOOKPROC(self._mouse_callback)
        self._kb_hook_proc = HOOKPROC(self._kb_callback)

        self._build_ui()
        self._start_hooks()
        self._schedule_save()

        # Start tray icon in background thread
        tray_thread = threading.Thread(target=_create_tray_icon, args=(self,), daemon=True)
        tray_thread.start()

        # First-run: ask about startup
        if "first_run_done" not in self.settings:
            self.root.after(1000, self._first_run_prompt)

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("Click Tracker")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", BG_COLOR)
        self.root.configure(bg=BG_COLOR)

        # Restore saved position or default to top-right
        saved_x = self.settings.get("window_x")
        saved_y = self.settings.get("window_y")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        if saved_x is not None and saved_y is not None:
            # Validate saved position is on-screen
            if 0 <= saved_x < screen_w and 0 <= saved_y < screen_h:
                self.root.geometry(f"+{saved_x}+{saved_y}")
            else:
                self.root.geometry(f"+{screen_w - 320}+10")
        else:
            self.root.geometry(f"+{screen_w - 320}+10")

        self.sprites = SpriteManager(self.root, scale=self._dpi_scale)

        self.bush_label = tk.Label(self.root, bg=BG_COLOR, cursor="hand2", borderwidth=0)
        self.bush_label.pack()

        self._stats_panel_w = 140
        self._stats_panel_h = 36
        self._stats_text_ids = {}
        self.stats_win = None

        self.bush_label.bind("<ButtonPress-1>", self._on_drag_start)
        self.bush_label.bind("<B1-Motion>", self._on_drag)
        self.bush_label.bind("<ButtonRelease-1>", self._on_click)
        self.bush_label.bind("<Enter>", self._on_hover_enter)
        self.bush_label.bind("<Leave>", self._on_hover_leave)
        self.root.bind("<Button-3>", self._on_right_click)

        self.menu = tk.Menu(self.root, tearoff=0, bg="#243d18", fg=TEXT_COLOR,
                            activebackground="#2d6b1e", activeforeground="#ffffff",
                            font=(FONT_FAMILY, 9))
        self.menu.add_command(label="Reset Counts", command=self._reset)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self._quit)

        self.root.bind("<<InputEvent>>", self._on_input_event)

        self._render_bush(self._visual_bush_stage, self._visual_flower_stage)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self._force_topmost()

    # --- Tooltip ---
    def _on_hover_enter(self, event):
        self._hover_bright = True
        # Show tooltip after short delay
        self._tooltip_after = self.root.after(400, self._show_tooltip)

    def _on_hover_leave(self, event):
        self._hover_bright = False
        if hasattr(self, '_tooltip_after'):
            self.root.after_cancel(self._tooltip_after)
        self._hide_tooltip()

    def _show_tooltip(self):
        if self._tooltip_win:
            return
        mc = format_count(self.mouse_clicks)
        kp = format_count(self.key_presses)

        self._tooltip_win = tw = tk.Toplevel(self.root)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.configure(bg="#1a3a10")

        lbl = tk.Label(tw, text=f"Clicks: {mc}  |  Keys: {kp}",
                       bg="#1a3a10", fg=TEXT_COLOR,
                       font=(FONT_FAMILY, 8), padx=6, pady=2)
        lbl.pack()

        x = self.root.winfo_x() + self.root.winfo_width() // 2
        y = self.root.winfo_y() - 24
        tw.geometry(f"+{x}+{y}")

    def _hide_tooltip(self):
        if self._tooltip_win:
            self._tooltip_win.destroy()
            self._tooltip_win = None

    # --- Stats panel ---
    def _draw_stats_panel(self):
        c = self.stats_canvas
        w = self._stats_panel_w
        h = self._stats_panel_h
        c.delete("all")

        fs = get_flower_stage(self.mouse_clicks)
        flower_color = FLOWER_COLORS[fs] if fs > 0 and fs < len(FLOWER_COLORS) else None

        _draw_vine_border(c, w, h, self._ps, flower_color)

        font_size = max(7, round(8 * self._dpi_scale / 4))
        self._stats_text_ids["stats"] = c.create_text(
            w // 2, h // 2,
            text="", anchor="center",
            font=(FONT_FAMILY, font_size), fill=TEXT_COLOR,
        )

    def _render_bush(self, bush_stage, flower_stage):
        sprite = self.sprites.create_flowered_sprite(bush_stage, flower_stage)
        self._current_sprite_ref = sprite
        self.bush_label.config(image=sprite)

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self._drag_moved = False

    def _on_drag(self, event):
        dx = abs(event.x - self._drag_x)
        dy = abs(event.y - self._drag_y)
        if dx > 3 or dy > 3:
            self._drag_moved = True
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        new_x = old_x + event.x - self._drag_x
        new_y = old_y + event.y - self._drag_y
        self.root.geometry(f"+{new_x}+{new_y}")
        if self.stats_win and self.stats_win.winfo_exists():
            sx = self.stats_win.winfo_x() + (new_x - old_x)
            sy = self.stats_win.winfo_y() + (new_y - old_y)
            self.stats_win.geometry(f"+{sx}+{sy}")
        # Save position (debounced in _schedule_save)
        self.settings["window_x"] = new_x
        self.settings["window_y"] = new_y

    def _on_click(self, event):
        if hasattr(self, '_drag_moved') and self._drag_moved:
            return
        self.expanded = not self.expanded
        if self.expanded:
            self._show_stats_popup()
        else:
            self._hide_stats_popup()

    def _show_stats_popup(self):
        if self.stats_win and self.stats_win.winfo_exists():
            self.stats_win.destroy()

        mc = format_count(self.mouse_clicks)
        kp = format_count(self.key_presses)
        stats_text = f"{mc} | {kp}"

        import tkinter.font as tkfont
        font_size = max(7, round(8 * self._dpi_scale / 4))
        font = tkfont.Font(family=FONT_FAMILY, size=font_size)
        text_w = font.measure(stats_text)
        border_pad = self._ps * 8
        pw = text_w + border_pad
        ph = max(30, round(36 * self._dpi_scale / 4))

        bx = self.root.winfo_x()
        by = self.root.winfo_y()
        bw = self.root.winfo_width()
        bh = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        bush_cx = bx + bw // 2
        bush_cy = by + bh // 2

        if bush_cx > sw // 2:
            px = bx - pw - 4
        else:
            px = bx + bw + 4

        if bush_cy > sh // 2:
            py = by - ph - 4
        else:
            py = by + bh + 4

        px = max(0, min(px, sw - pw))
        py = max(0, min(py, sh - ph))

        self._stats_panel_w = pw
        self._stats_panel_h = ph

        self.stats_win = tk.Toplevel(self.root)
        self.stats_win.overrideredirect(True)
        self.stats_win.attributes("-topmost", True)
        self.stats_win.geometry(f"{pw}x{ph}+{px}+{py}")
        self.stats_win.configure(bg=STATS_BG)

        self.stats_canvas = tk.Canvas(
            self.stats_win, width=pw, height=ph,
            bg=STATS_BG, highlightthickness=0,
        )
        self.stats_canvas.pack()

        self._draw_stats_panel()
        self._update_stats_text()

        self.stats_canvas.bind("<ButtonPress-1>", self._on_stats_drag_start)
        self.stats_canvas.bind("<B1-Motion>", self._on_stats_drag)

    def _hide_stats_popup(self):
        if self.stats_win and self.stats_win.winfo_exists():
            self.stats_win.destroy()
            self.stats_win = None

    def _on_stats_drag_start(self, event):
        self._stats_drag_x = event.x
        self._stats_drag_y = event.y

    def _on_stats_drag(self, event):
        if self.stats_win:
            x = self.stats_win.winfo_x() + event.x - self._stats_drag_x
            y = self.stats_win.winfo_y() + event.y - self._stats_drag_y
            self.stats_win.geometry(f"+{x}+{y}")

    def _on_right_click(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def _on_input_event(self, event=None):
        self._pending_update = False
        new_bush = get_bush_stage(self.key_presses)
        new_flower = get_flower_stage(self.mouse_clicks)

        if new_bush != self._visual_bush_stage or new_flower != self._visual_flower_stage:
            old_bush = self._visual_bush_stage
            old_flower = self._visual_flower_stage
            self._visual_bush_stage = new_bush
            self._visual_flower_stage = new_flower

            if not self._animating:
                self._animate(old_bush, old_flower, new_bush, new_flower, 0)
            else:
                self._render_bush(new_bush, new_flower)

        if self.expanded:
            self._update_stats_text()

    def _animate(self, old_bush, old_flower, new_bush, new_flower, frame):
        self._animating = True
        if frame > ANIM_FRAMES:
            self._animating = False
            self._render_bush(new_bush, new_flower)
            return

        t = frame / ANIM_FRAMES
        sprite = self.sprites.create_animated_frame(
            old_bush, old_flower, new_bush, new_flower, t
        )
        self._current_sprite_ref = sprite
        self.bush_label.config(image=sprite)

        self.root.after(ANIM_MS, self._animate,
                        old_bush, old_flower, new_bush, new_flower, frame + 1)

    def _update_stats_text(self):
        if not hasattr(self, 'stats_canvas') or not self.stats_win:
            return
        mc = format_count(self.mouse_clicks)
        kp = format_count(self.key_presses)
        c = self.stats_canvas
        if "stats" in self._stats_text_ids:
            c.itemconfig(self._stats_text_ids["stats"], text=f"{mc} | {kp}")

    # --- Hooks ---
    def _mouse_callback(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            self.mouse_clicks += 1
            if not self._pending_update:
                self._pending_update = True
                try:
                    self.root.event_generate("<<InputEvent>>", when="tail")
                except Exception:
                    pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _kb_callback(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self.key_presses += 1
            if not self._pending_update:
                self._pending_update = True
                try:
                    self.root.event_generate("<<InputEvent>>", when="tail")
                except Exception:
                    pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _hook_thread(self, hook_type, proc):
        hook = user32.SetWindowsHookExW(hook_type, proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            logger.error("Failed to install hook type %d", hook_type)
            return
        logger.info("Hook type %d installed", hook_type)
        msg = wt.MSG()
        while self.running:
            result = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            if result:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)
        user32.UnhookWindowsHookEx(hook)
        logger.info("Hook type %d removed", hook_type)

    def _start_hooks(self):
        t1 = threading.Thread(target=self._hook_thread, args=(WH_MOUSE_LL, self._mouse_hook_proc), daemon=True)
        t2 = threading.Thread(target=self._hook_thread, args=(WH_KEYBOARD_LL, self._kb_hook_proc), daemon=True)
        t1.start()
        t2.start()

    def _force_topmost(self):
        if not self.running:
            return
        try:
            hwnd = int(self.root.wm_frame(), 16)
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
            if self.stats_win and self.stats_win.winfo_exists():
                shwnd = int(self.stats_win.wm_frame(), 16)
                user32.SetWindowPos(
                    shwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
        except Exception as e:
            logger.debug("force_topmost error: %s", e)
        self.root.after(2000, self._force_topmost)

    # --- Persistence ---
    def _schedule_save(self):
        if not self.running:
            return
        self._save()
        save_settings(self.settings)
        self.root.after(SAVE_INTERVAL * 1000, self._schedule_save)

    def _save(self):
        save_data({"mouse_clicks": self.mouse_clicks, "key_presses": self.key_presses})

    # --- Tray / visibility ---
    def _toggle_visibility(self):
        if self._visible:
            self.root.withdraw()
            self._hide_stats_popup()
            self._hide_tooltip()
            self._visible = False
        else:
            self.root.deiconify()
            self._visible = True

    def _toggle_startup(self):
        enabled = is_startup_enabled()
        set_startup_enabled(not enabled)

    def _show_about(self):
        about = tk.Toplevel(self.root)
        about.title("About Click Tracker")
        about.attributes("-topmost", True)
        about.configure(bg=STATS_BG)
        about.resizable(False, False)

        tk.Label(about, text=f"Click Tracker v{__version__}",
                 bg=STATS_BG, fg=TEXT_COLOR,
                 font=(FONT_FAMILY, 12, "bold")).pack(padx=20, pady=(15, 5))
        tk.Label(about, text="Track your clicks and keystrokes\nwith a growing pixel art bush!",
                 bg=STATS_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 9), justify="center").pack(padx=20, pady=5)
        tk.Label(about, text=f"All-time: {format_count(self.mouse_clicks)} clicks | {format_count(self.key_presses)} keys",
                 bg=STATS_BG, fg=TEXT_COLOR,
                 font=(FONT_FAMILY, 9)).pack(padx=20, pady=(5, 15))

        about.update_idletasks()
        w = about.winfo_width()
        h = about.winfo_height()
        sw = about.winfo_screenwidth()
        sh = about.winfo_screenheight()
        about.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _first_run_prompt(self):
        self.settings["first_run_done"] = True
        save_settings(self.settings)

        dialog = tk.Toplevel(self.root)
        dialog.title("Click Tracker")
        dialog.attributes("-topmost", True)
        dialog.configure(bg=STATS_BG)
        dialog.resizable(False, False)

        tk.Label(dialog, text="Start Click Tracker\nautomatically with Windows?",
                 bg=STATS_BG, fg=TEXT_COLOR,
                 font=(FONT_FAMILY, 10), justify="center").pack(padx=20, pady=(15, 10))

        btn_frame = tk.Frame(dialog, bg=STATS_BG)
        btn_frame.pack(padx=20, pady=(0, 15))

        def yes():
            set_startup_enabled(True)
            dialog.destroy()

        def no():
            dialog.destroy()

        tk.Button(btn_frame, text="Yes", command=yes,
                  bg="#2d6b1e", fg=TEXT_COLOR, font=(FONT_FAMILY, 9),
                  width=8, relief="flat", cursor="hand2").pack(side="left", padx=5)
        tk.Button(btn_frame, text="No", command=no,
                  bg="#243d18", fg=TEXT_DIM, font=(FONT_FAMILY, 9),
                  width=8, relief="flat", cursor="hand2").pack(side="left", padx=5)

        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    # --- Lifecycle ---
    def _reset(self):
        self.mouse_clicks = 0
        self.key_presses = 0
        self._visual_bush_stage = 0
        self._visual_flower_stage = 0
        self._save()
        self._render_bush(0, 0)
        if self.expanded:
            self._show_stats_popup()

    def _quit(self):
        self.running = False
        self._save()
        save_settings(self.settings)
        self._hide_stats_popup()
        self._hide_tooltip()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Single-instance guard
    mutex = _acquire_mutex()
    if mutex is None:
        logger.info("Another instance is already running, exiting")
        sys.exit(0)

    try:
        app = ClickTracker()
        app.run()
    except Exception:
        logger.exception("Fatal error")
        try:
            import tkinter.messagebox as mb
            mb.showerror("Click Tracker", "An unexpected error occurred.\nCheck the log at:\n" + LOG_FILE)
        except Exception:
            pass
        sys.exit(1)
