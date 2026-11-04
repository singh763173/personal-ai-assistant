"""Overlay real clock/date/battery data on an animated Whisplay dashboard.

The GIF contains only the background and animated mascot. Draw the changing
data at runtime because a static GIF cannot display a live clock or battery.

The result is a Pillow RGB image (240x280) suitable for handing to a Whisplay
display driver. This script does not assume a particular PiSugar battery model.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 240, 280
HERE = Path(__file__).resolve().parent
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
WHITE = (237, 242, 255)
MUTED = (138, 146, 177)
CYAN = (110, 242, 254)


class _DashboardCache:
    """Avoid reloading the GIF and fonts on every frame."""

    def __init__(self):
        self.gif_path: Path | None = None
        self.frames: list[Image.Image] | None = None
        self.durations: list[float] | None = None
        self.font_big: ImageFont.FreeTypeFont | None = None
        self.font_small: ImageFont.FreeTypeFont | None = None
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
        try:
            self.font_big = ImageFont.truetype(FONT_PATH, 46)
            self.font_small = ImageFont.truetype(FONT_PATH, 10)
            self.font_tiny = ImageFont.truetype(FONT_PATH, 9)
        except OSError:
            # Fallback to default bitmap font if DejaVu is missing
            self.font_big = ImageFont.load_default()
            self.font_small = self.font_big
            self.font_tiny = self.font_big


_cache = _DashboardCache()


def live_dashboard_frame(
    battery_percent: int,
    frame_index: int = 0,
    now: datetime | None = None,
    animation_file: str | Path | None = None,
) -> Image.Image:
    """Return one clock/battery-updated dashboard frame as a 240x280 RGB image.

    Call about eight times a second to animate. Supply the latest battery
    percentage from your own PiSugar model / configured battery service.
    """
    gif = Path(animation_file) if animation_file else HERE / "dashboard_background.gif"
    _cache.load(gif)

    image = _cache.frames[frame_index % len(_cache.frames)].copy()
    d = ImageDraw.Draw(image)
    now = now or datetime.now()

    d.text((16, 36), now.strftime("%H:%M"), fill=WHITE, font=_cache.font_big)
    d.text((18, 92), now.strftime("%a %d %b").upper(), fill=MUTED, font=_cache.font_small)

    battery = max(0, min(100, int(battery_percent)))
    d.text((183, 12), f"{battery}%", fill=WHITE, font=_cache.font_tiny)
    d.rounded_rectangle((216, 13, 231, 23), radius=2, outline=MUTED, width=1)
    d.rounded_rectangle((231, 16, 233, 20), radius=1, fill=MUTED)
    d.rounded_rectangle(
        (218, 15, 218 + 2 + round(battery / 100 * 10), 21), radius=1, fill=CYAN if battery > 20 else (255, 130, 135)
    )

    assert image.size == (WIDTH, HEIGHT)
    return image


if __name__ == "__main__":
    # Test the dynamic display output without hardware.
    live_dashboard_frame(86).save(HERE / "live_dashboard_example.png")
    print("Created live_dashboard_example.png")
