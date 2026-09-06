#!/usr/bin/env python3
"""
Ollama Bee Device firmware v2.2 (PiSugar Whisplay HAT + PiSugar 3 battery)

Button mappings:
- Single click: toggle mute / recording
- Double click: capture and upload a photo immediately
- Long press (~2 s): safe shutdown

Reads battery level from PiSugar power-manager server and displays it on the LCD.
"""
import os
import time
import subprocess
import threading
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import requests

# Optional hardware libraries
try:
    from picamera2 import Picamera2
    HAS_CAMERA = True
except Exception as e:
    print(f"Camera import failed: {e}")
    HAS_CAMERA = False

try:
    import whisplay
    from PIL import Image, ImageDraw, ImageFont
    HAS_WHISPLAY = True
except Exception as e:
    print(f"Whisplay runtime not found: {e}")
    HAS_WHISPLAY = False

# Config from env
BACKEND_URL = os.getenv("BEE_BACKEND_URL", "http://192.168.1.86:8000")
DEVICE_ID = os.getenv("BEE_DEVICE_ID", "bee-pioneer-01")
CHUNK_SECONDS = int(os.getenv("BEE_CHUNK_SECONDS", "30"))
SAMPLE_RATE = int(os.getenv("BEE_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("BEE_AUDIO_CHANNELS", "2"))
AUDIO_CARD = os.getenv("BEE_AUDIO_CARD", "whisplaysound")
ENABLE_CAMERA = os.getenv("BEE_ENABLE_CAMERA", "true").lower() in ("1", "true", "yes")
CAMERA_INTERVAL = int(os.getenv("BEE_CAMERA_INTERVAL", "300"))
LONG_PRESS_SECONDS = float(os.getenv("BEE_LONG_PRESS_SECONDS", "2.0"))
PISUGAR_API = os.getenv("BEE_PISUGAR_API", "http://localhost:8423")

# Display colors (RGB tuples)
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (255, 0, 0)
COLOR_BLUE = (0, 120, 255)
COLOR_YELLOW = (255, 200, 0)
COLOR_ORANGE = (255, 100, 0)


class BeeDeviceWhisplay:
    def __init__(self):
        self.muted = True
        self.last_upload_ok = True
        self.last_camera_ok = True
        self.battery_level = None
        self.lock = threading.Lock()
        self.session = requests.Session()

        self.board = None
        self.button = None
        self.lcd = None
        self.led = None
        self.camera = None

        self._init_whisplay()
        self._init_camera()

    def _init_whisplay(self):
        if not HAS_WHISPLAY:
            print("Running without Whisplay HAT hardware.")
            return
        try:
            self.board = whisplay.Board()
            self.button = whisplay.Button(self.board)
            self.lcd = whisplay.LCD(self.board, width=240, height=280)
            self.led = whisplay.LED(self.board)

            self.button.on_click = self._on_single_click
            self.button.on_double_click = self._on_double_click
            self.button.on_long_press = self._on_long_press

            self._set_led(COLOR_BLUE)
            self._draw_status("Bee\nReady")
            print("Whisplay HAT initialized.")
        except Exception as e:
            print(f"Whisplay init failed: {e}")
            self.board = None

    def _init_camera(self):
        if not HAS_CAMERA or not ENABLE_CAMERA:
            return
        try:
            self.camera = Picamera2()
            cfg = self.camera.create_still_configuration(main={"size": (1640, 1232)})
            self.camera.configure(cfg)
            self.camera.start()
            time.sleep(1)
            print("Camera initialized.")
        except Exception as e:
            print(f"Camera init failed: {e}")
            self.camera = None

    def _on_single_click(self):
        with self.lock:
            self.muted = not self.muted
        state = "muted" if self.muted else "recording"
        print(f"[{datetime.now(timezone.utc).isoformat()}] Single click: {state}")
        self._update_display()

    def _on_double_click(self):
        print(f"[{datetime.now(timezone.utc).isoformat()}] Double click: capture photo")
        self._draw_status("Capturing...", COLOR_ORANGE)
        self._capture_and_upload()
        self._update_display()

    def _on_long_press(self):
        print(f"[{datetime.now(timezone.utc).isoformat()}] Long press: shutting down")
        self._draw_status("Shutting\ndown...", COLOR_RED)
        self._set_led(COLOR_RED)
        self._shutdown()

    def _shutdown(self):
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
        os.system("sudo shutdown -h now")
        time.sleep(10)

    def _set_led(self, color):
        if self.led:
            try:
                self.led.set_color(*color)
            except Exception as e:
                print(f"LED set failed: {e}")

    def _get_battery(self):
        try:
            r = self.session.get(f"{PISUGAR_API}/api/power", timeout=5)
            r.raise_for_status()
            data = r.json()
            # PiSugar server returns different fields depending on version
            return data.get("battery_percentage") or data.get("battery") or data.get("level")
        except Exception as e:
            print(f"Battery read failed: {e}")
            return None

    def _draw_status(self, text, color=COLOR_WHITE):
        if not self.lcd:
            return
        try:
            img = Image.new("RGB", (240, 280), COLOR_BLACK)
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except Exception:
                font = ImageFont.load_default()
                small = font

            self.battery_level = self._get_battery()

            draw.text((10, 10), f"Bee {DEVICE_ID}", font=font, fill=color)
            draw.multiline_text((10, 60), text, font=font, fill=color)

            status_line = (
                f"Net:{'OK' if self.last_upload_ok else 'ERR'}  "
                f"Cam:{'OK' if self.last_camera_ok else 'ERR'}"
            )
            if self.battery_level is not None:
                status_line += f"  Bat:{self.battery_level}%"
            draw.text((10, 250), status_line, font=small, fill=COLOR_YELLOW)

            self.lcd.show(img)
        except Exception as e:
            print(f"LCD draw failed: {e}")

    def _update_display(self):
        if self.muted:
            self._draw_status("Muted\n[click to record]", COLOR_RED)
            self._set_led(COLOR_RED)
        else:
            self._draw_status("Recording...\n[click to mute]", COLOR_GREEN)
            self._set_led(COLOR_GREEN)

    def _record_chunk(self, duration_seconds: int) -> Path:
        tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
        tmp_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        wav_path = tmp_dir / f"{DEVICE_ID}-{stamp}.wav"

        cmd = [
            "arecord",
            "-D", f"hw:{AUDIO_CARD}",
            "-c", str(AUDIO_CHANNELS),
            "-r", str(SAMPLE_RATE),
            "-f", "S16_LE",
            "-d", str(duration_seconds),
            str(wav_path),
        ]
        print(f"Recording {duration_seconds}s -> {wav_path}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return wav_path

    def _capture_image(self) -> Path:
        if not self.camera:
            return None
        tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
        tmp_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        img_path = tmp_dir / f"{DEVICE_ID}-{stamp}.jpg"
        try:
            self.camera.capture_file(str(img_path))
            print(f"Captured image -> {img_path}")
            return img_path
        except Exception as e:
            print(f"Camera capture failed: {e}")
            return None

    def _upload_file(self, url_path: str, field_name: str, file_path: Path) -> bool:
        url = f"{BACKEND_URL}{url_path}"
        try:
            with open(file_path, "rb") as f:
                files = {field_name: (file_path.name, f, "audio/wav" if file_path.suffix == ".wav" else "image/jpeg")}
                data = {"device_id": DEVICE_ID}
                resp = self.session.post(url, files=files, data=data, timeout=60)
                resp.raise_for_status()
                print(f"Upload OK: {resp.status_code}")
                return True
        except Exception as e:
            print(f"Upload failed: {e}")
            return False

    def _capture_and_upload(self):
        img_path = self._capture_image()
        if img_path:
            self.last_camera_ok = self._upload_file("/upload-image", "image", img_path)
            self._cleanup(img_path)

    def _cleanup(self, path: Path):
        try:
            path.unlink()
        except Exception:
            pass

    def run(self):
        print(f"Bee Whisplay device {DEVICE_ID} starting. Backend: {BACKEND_URL}")
        print("Single click = toggle mute, Double click = photo, Long press = shutdown")
        self._update_display()

        last_camera_time = 0

        try:
            while True:
                if self.muted:
                    time.sleep(0.5)
                    if ENABLE_CAMERA and (time.time() - last_camera_time) > CAMERA_INTERVAL:
                        self._capture_and_upload()
                        last_camera_time = time.time()
                        self._update_display()
                    continue

                self._update_display()
                wav_path = self._record_chunk(CHUNK_SECONDS)
                self.last_upload_ok = self._upload_file("/upload", "audio", wav_path)
                self._cleanup(wav_path)

                if ENABLE_CAMERA and (time.time() - last_camera_time) > CAMERA_INTERVAL:
                    self._capture_and_upload()
                    last_camera_time = time.time()

                self._update_display()
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            self._set_led(COLOR_BLACK)
            if self.camera:
                try:
                    self.camera.stop()
                except Exception:
                    pass


if __name__ == "__main__":
    BeeDeviceWhisplay().run()
