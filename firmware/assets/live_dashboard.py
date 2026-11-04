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
FONT_NORMAL = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
WHITE = (237, 242, 255)
MUTED = (138, 146, 177)
CYAN = (110, 242, 254)


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
    with Image.open(gif) as source:
        source.seek(frame_index % source.n_frames)
        image = source.convert("RGB")

    d = ImageDraw.Draw(image)
    now = now or datetime.now()
    big = ImageFont.truetype(FONT_PATH, 46)
    small = ImageFont.truetype(FONT_PATH, 10)
    tiny = ImageFont.truetype(FONT_PATH, 9)

    d.text((16, 36), now.strftime("%H:%M"), fill=WHITE, font=big)
    d.text((18, 92), now.strftime("%a %d %b").upper(), fill=MUTED, font=small)

    battery = max(0, min(100, int(battery_percent)))
    d.text((183, 12), f"{battery}%", fill=WHITE, font=tiny)
    d.rounded_rectangle((216, 13, 231, 23), radius=2, outline=MUTED, width=1)
    d.rounded_rectangle((231, 16, 233, 20), radius=1, fill=MUTED)
    d.rounded_rectangle((218, 15, 218 + 2 + round(battery / 100 * 10), 21),
                        radius=1, fill=CYAN if battery > 20 else (255, 130, 135))

    assert image.size == (WIDTH, HEIGHT)
    return image


if __name__ == "__main__":
    # Test the dynamic display output without hardware.
    live_dashboard_frame(86).save(HERE / "live_dashboard_example.png")
    print("Created live_dashboard_example.png")
