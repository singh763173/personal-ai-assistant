"""Overlay real clock/date/battery/WiFi/backend data on an animated Whisplay dashboard.

The GIF provides the background + mascot.  Everything else (clock, labels,
battery icon, Wi-Fi bars, backend status) is drawn at runtime so it stays sharp
and can react to live state.

Returns a 240x280 Pillow RGB image for the Whisplay driver.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 240, 280
HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"

# Palette
WHITE = (237, 242, 255)
MUTED = (170, 178, 200)
CYAN = (110, 242, 254)
GREEN = (100, 230, 150)
YELLOW = (250, 210, 90)
RED = (255, 110, 110)
BACKGROUND_BAR = (50, 55, 75)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled TTF font or fall back to the system default."""
    candidates = [
        FONT_DIR / name,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


class _DashboardCache:
    """Avoid reloading GIF frames and fonts on every draw call."""

    def __init__(self):
        self.gif_path: Path | None = None
        self.frames: list[Image.Image] | None = None
        self.durations: list[float] | None = None
        self.font_clock: ImageFont.FreeTypeFont | None = None
        self.font_label: ImageFont.FreeTypeFont | None = None
        self.font_tiny: ImageFont.FreeTypeFont | None = None

    def load(self, gif: Path) -> None:
        if self.gif_path == gif and self.frames is not None:
            return
        self.gif_path = gif
        with Image.open(gif) as source:
            self.frames = []
            self.durations = []
            for i in range(source.n_frames):
                source.seek(i)
                self.frames.append(source.convert("RGB").copy())
                self.durations.append(max(source.info.get("duration", 100), 20) / 1000.0)
        self.font_clock = _font("JetBrainsMono-Bold.ttf", 44)
        self.font_label = _font("NotoSans-Bold.ttf", 11)
        self.font_tiny = _font("NotoSans-Regular.ttf", 9)


_cache = _DashboardCache()


def _text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    shadow: tuple[int, int, int] = (20, 22, 35),
    anchor: str | None = None,
) -> None:
    """Draw text with a 1px soft shadow for readability over busy GIFs."""
    x, y = xy
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + dx, y + dy), text, font=font, fill=shadow, anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _battery_color(level: int) -> tuple[int, int, int]:
    if level > 50:
        return GREEN
    if level > 20:
        return YELLOW
    return RED


def _draw_wifi_bars(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    rssi: int | None,
    connected: bool,
) -> None:
    """Draw 4 ascending signal bars in the top status bar."""
    if not connected or rssi is None:
        # Disconnected: small crossed-out icon
        draw.line((x, y + 10, x + 14, y), fill=RED, width=2)
        draw.arc((x - 2, y - 4, x + 16, y + 10), start=180, end=360, fill=MUTED, width=2)
        return

    # Map RSSI to 0-4 bars
    if rssi >= -50:
        bars = 4
    elif rssi >= -60:
        bars = 3
    elif rssi >= -70:
        bars = 2
    elif rssi >= -80:
        bars = 1
    else:
        bars = 1

    colour = GREEN if rssi >= -65 else (YELLOW if rssi >= -80 else RED)
    widths = [2, 2, 2, 2]
    heights = [4, 6, 8, 10]
    gap = 2
    for i in range(4):
        bx = x + i * (widths[i] + gap)
        by = y + heights[-1] - heights[i]
        fill = colour if i < bars else BACKGROUND_BAR
        draw.rectangle((bx, by, bx + widths[i], y + heights[-1]), fill=fill, outline=None)


def _draw_backend_dot(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    online: bool,
) -> None:
    """Small status dot + ring."""
    colour = CYAN if online else RED
    draw.ellipse((x, y, x + 8, y + 8), fill=colour)
    draw.ellipse((x - 2, y - 2, x + 10, y + 10), outline=BACKGROUND_BAR, width=1)


def live_dashboard_frame(
    battery_percent: int,
    frame_index: int = 0,
    now: datetime | None = None,
    animation_file: str | Path | None = None,
    wifi_connected: bool = True,
    wifi_rssi: int | None = None,
    backend_online: bool = True,
    status_text: str | None = None,
) -> Image.Image:
    """Return one clock/battery/WiFi/backend-updated dashboard frame.

    Args:
        battery_percent: 0-100 battery level.
        frame_index: Which GIF frame to composite over.
        animation_file: Path to the dashboard GIF (default bundled asset).
        wifi_connected: Whether the device has an association.
        wifi_rssi: dBm signal strength, e.g. -45 for excellent.
        backend_online: Whether the backend was reachable recently.
        status_text: Optional short message shown at the bottom.
    """
    gif = Path(animation_file) if animation_file else HERE / "dashboard_background.gif"
    _cache.load(gif)

    image = _cache.frames[frame_index % len(_cache.frames)].copy()
    d = ImageDraw.Draw(image)
    now = now or datetime.now()

    # ---- Top status bar ----
    # Backend online dot (left)
    _draw_backend_dot(d, 10, 11, backend_online)

    # Wi-Fi bars (centre)
    _draw_wifi_bars(d, WIDTH // 2 - 12, 12, wifi_rssi, wifi_connected)

    # Battery icon + percentage (right)
    battery = max(0, min(100, int(battery_percent)))
    batt_colour = _battery_color(battery)
    d.text((172, 11), f"{battery}%", font=_cache.font_tiny, fill=WHITE)
    # Battery body
    d.rounded_rectangle((202, 11, 226, 21), radius=3, outline=MUTED, width=1)
    # Battery nib
    d.rounded_rectangle((226, 14, 230, 18), radius=1, fill=MUTED)
    # Fill
    fill_width = round(battery / 100 * 20)
    if fill_width > 0:
        d.rounded_rectangle((208, 13, 208 + fill_width, 19), radius=2, fill=batt_colour)

    # ---- Clock and date ----
    # Positioned high so it does not cover the mascot's face
    _text_with_shadow(d, (16, 34), now.strftime("%H:%M"), _cache.font_clock, WHITE)
    _text_with_shadow(d, (18, 90), now.strftime("%a %d %b").upper(), _cache.font_label, MUTED)

    # ---- Optional status line at the bottom ----
    # Drawn above the dashboard's own bottom pill area (which starts ~210 px)
    if status_text:
        _text_with_shadow(d, (WIDTH // 2, 232), status_text, _cache.font_tiny, MUTED, anchor="mm")

    assert image.size == (WIDTH, HEIGHT)
    return image


if __name__ == "__main__":
    # Test render
    live_dashboard_frame(
        battery_percent=72,
        wifi_connected=True,
        wifi_rssi=-52,
        backend_online=True,
    ).save(HERE / "live_dashboard_example.png")
    print("Created live_dashboard_example.png")


def current_wifi_rssi() -> int | None:
    """Try to read wlan0 signal level in dBm."""
    try:
        result = subprocess.run(
            ["iw", "dev", "wlan0", "station", "dump"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "signal:" in line:
                # line like: 	signal:   -45 dBm
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "signal:" and i + 1 < len(parts):
                        try:
                            return int(parts[i + 1])
                        except ValueError:
                            continue
    except Exception:
        pass
    return None


def current_wifi_ssid() -> str | None:
    """Return the current SSID or None."""
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ssid = result.stdout.strip()
        return ssid if ssid else None
    except Exception:
        return None
