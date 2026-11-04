#!/usr/bin/env python3
"""
Ollama Bee Device firmware v2.3 (PiSugar Whisplay HAT + PiSugar 3 battery)

Button mappings (Whisplay single button on GPIO):
- Single click: toggle mute / recording
- Double click: capture and upload a photo immediately
- Long press (~2 s): safe shutdown
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
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception as e:
    print(f"PIL import failed: {e}")
    HAS_PIL = False

try:
    import whisplay
    HAS_WHISPLAY = True
except Exception as e:
    print(f"Whisplay runtime not found: {e}")
    HAS_WHISPLAY = False

# Config from env
BACKEND_URL = os.getenv("BEE_BACKEND_URL", "http://192.168.1.86:8000")
DEVICE_ID = os.getenv("BEE_DEVICE_ID", "bee-pioneer-01")
API_KEY = os.getenv("BEE_API_KEY", "")
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


def rgb565_bytes(img: Image.Image) -> bytes:
    """Convert a PIL RGB image to RGB565 big-endian bytes for the Whisplay LCD."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    pixels = list(img.getdata())
    out = bytearray(len(pixels) * 2)
    for i, (r, g, b) in enumerate(pixels):
        # RGB565: RRRRRGGG GGGBBBBB
        val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[2 * i] = (val >> 8) & 0xFF
        out[2 * i + 1] = val & 0xFF
    return bytes(out)


class BeeDeviceWhisplay:
    def __init__(self):
        self.muted = True
        self.last_upload_ok = True
        self.last_camera_ok = True
        self.battery_level = None
        self.lock = threading.Lock()
        self.session = requests.Session()

        self.board = None
        self.camera = None

        # Button gesture state
        self._last_press_time = 0.0
        self._press_start = 0.0
        self._release_callbacks = []
        self._long_press_triggered = False
        self._double_click_window = 0.4
        self._click_count = 0
        self._last_click_time = 0.0

        self._init_whisplay()
        self._init_camera()

        self._recorder_proc = None
        self._recorder_path = None
        self._recorder_lock = threading.Lock()

    def _init_whisplay(self):
        if not HAS_WHISPLAY:
            print("Running without Whisplay HAT hardware.")
            return
        try:
            self.board = whisplay.WhisplayBoard()
            self.board.on_button_press(self._on_button_press)
            self.board.on_button_release(self._on_button_release)
            self.board.set_backlight(100)
            self.board.set_rgb(0, 0, 255)
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

    def _on_button_press(self):
        self._press_start = time.monotonic()
        self._long_press_triggered = False

    def _on_button_release(self):
        now = time.monotonic()
        press_duration = now - self._press_start
        if press_duration >= LONG_PRESS_SECONDS:
            if not self._long_press_triggered:
                self._long_press_triggered = True
                self._on_long_press()
            return

        # Click detection
        self._click_count += 1
        if self._click_count == 1:
            # Wait for possible second click
            threading.Thread(target=self._handle_click_gesture, args=(now,), daemon=True).start()

    def _handle_click_gesture(self, first_click_time):
        time.sleep(self._double_click_window)
        with self.lock:
            count = self._click_count
            self._click_count = 0
        if count >= 2:
            self._on_double_click()
        elif count == 1:
            self._on_single_click()

    def _check_long_press(self):
        while True:
            if self.board and not self._long_press_triggered and self._press_start > 0:
                if time.monotonic() - self._press_start >= LONG_PRESS_SECONDS:
                    self._long_press_triggered = True
                    self._on_long_press()
            time.sleep(0.1)

    def _on_single_click(self):
        with self.lock:
            self.muted = not self.muted
            now_muted = self.muted
        state = "muted" if now_muted else "recording"
        print(f"[{datetime.now(timezone.utc).isoformat()}] Single click: {state}")
        self._update_display()
        if now_muted:
            # Stopped: upload immediately
            threading.Thread(target=self._upload_last_recording, daemon=True).start()
        else:
            # Started: begin continuous recording
            self._start_recording()

    def _on_double_click(self):
        print(f"[{datetime.now(timezone.utc).isoformat()}] Double click: capture photo + ask")
        self._draw_status("Look at camera...", COLOR_ORANGE)
        # Capture photo and immediately take a 5-second question recording
        img_path = self._capture_image()
        if not img_path:
            return
        # Record 5s question
        q_wav = self._start_recording()
        time.sleep(5)
        self._draw_status("Processing...", COLOR_ORANGE)
        self._upload_ask_with_image(img_path, self._stop_recording())
        self._cleanup(q_wav)
        self._cleanup(img_path)

    def _on_long_press(self):
        print(f"[{datetime.now(timezone.utc).isoformat()}] Long press: shutting down")
        self._draw_status("Shutting\ndown...", COLOR_RED)
        self._set_rgb(COLOR_RED)
        self._shutdown()

    def _shutdown(self):
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
        os.system("sudo shutdown -h now")
        time.sleep(10)

    def _set_rgb(self, color):
        if self.board:
            try:
                self.board.set_rgb(*color)
            except Exception as e:
                print(f"LED set failed: {e}")

    def _get_battery(self):
        try:
            r = self.session.get(f"{PISUGAR_API}/api/power", timeout=5)
            r.raise_for_status()
            data = r.json()
            return data.get("battery_percentage") or data.get("battery") or data.get("level")
        except Exception as e:
            print(f"Battery read failed: {e}")
            return None

    def _draw_status(self, text, color=COLOR_WHITE):
        if not self.board or not HAS_PIL:
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

            self.board.draw_image(0, 0, 240, 280, rgb565_bytes(img))
        except Exception as e:
            print(f"LCD draw failed: {e}")

    def _update_display(self):
        if self.muted:
            self._draw_status("Muted\n[click to record]", COLOR_RED)
            self._set_rgb(COLOR_RED)
        else:
            self._draw_status("Recording...\n[click to mute]", COLOR_GREEN)
            self._set_rgb(COLOR_GREEN)

    def _start_recording(self) -> Path:
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
            str(wav_path),
        ]
        print(f"[REC] Started recording -> {wav_path}")
        with self._recorder_lock:
            self._recorder_path = wav_path
            self._recorder_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return wav_path

    def _stop_recording(self) -> Path:
        with self._recorder_lock:
            proc = self._recorder_proc
            wav_path = self._recorder_path
            self._recorder_proc = None
            self._recorder_path = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
        print(f"[REC] Stopped recording -> {wav_path}")
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

    def _upload_ask(self, url_path: str, wav_path: Path) -> bool:
        url = f"{BACKEND_URL}{url_path}"
        try:
            with open(wav_path, "rb") as f:
                files = {"audio": (wav_path.name, f, "audio/wav")}
                data = {"device_id": DEVICE_ID}
                if API_KEY:
                    headers = {"Authorization": API_KEY}
                else:
                    headers = {}
                resp = self.session.post(url, files=files, data=data, headers=headers, timeout=120)
                resp.raise_for_status()
                result = resp.json()
                reply = result.get("reply", "")
                audio_url = result.get("audio_url")
                print(f"[LLM] reply: {reply}")
                self.last_upload_ok = True
                if reply:
                    self._show_reply(reply)
                    self._play_reply_audio(audio_url)
                return True
        except Exception as e:
            print(f"Upload/ask failed: {e}")
            self.last_upload_ok = False
            return False

    def _upload_ask_with_image(self, img_path: Path, wav_path: Path):
        url = f"{BACKEND_URL}/api/v1/ask"
        try:
            with open(wav_path, "rb") as f_wav, open(img_path, "rb") as f_img:
                files = {
                    "audio": (wav_path.name, f_wav, "audio/wav"),
                    "image": (img_path.name, f_img, "image/jpeg"),
                }
                data = {"device_id": DEVICE_ID}
                headers = {"Authorization": API_KEY} if API_KEY else {}
                resp = self.session.post(url, files=files, data=data, headers=headers, timeout=180)
                resp.raise_for_status()
                result = resp.json()
                reply = result.get("reply", "")
                audio_url = result.get("audio_url")
                print(f"[LLM+vision] reply: {reply}")
                self.last_upload_ok = True
                if reply:
                    self._show_reply(reply)
                    self._play_reply_audio(audio_url)
                return True
        except Exception as e:
            print(f"Vision ask failed: {e}")
            self.last_upload_ok = False
            return False
        finally:
            self._update_display()

    def _upload_last_recording(self):
        wav_path = self._stop_recording()
        if wav_path and wav_path.exists():
            self._upload_ask("/api/v1/ask", wav_path)
            self._cleanup(wav_path)
        else:
            print("[REC] No recording to upload")
        self._update_display()

    def _capture_and_upload(self):
        img_path = self._capture_image()
        if img_path:
            self.last_camera_ok = self._upload_file("/api/v1/upload-image", "image", img_path)
            self._cleanup(img_path)

    def _upload_file(self, url_path: str, field: str, file_path: Path) -> bool:
        url = f"{BACKEND_URL}{url_path}"
        try:
            with open(file_path, "rb") as f:
                files = {field: (file_path.name, f, "image/jpeg" if field == "image" else "audio/wav")}
                data = {"device_id": DEVICE_ID}
                headers = {"Authorization": API_KEY} if API_KEY else {}
                resp = self.session.post(url, files=files, data=data, headers=headers, timeout=180)
                resp.raise_for_status()
                result = resp.json()
                reply = result.get("reply", "")
                audio_url = result.get("audio_url")
                print(f"[UPLOAD {field}] reply: {reply}")
                self.last_upload_ok = True
                if reply:
                    self._show_reply(reply)
                    self._play_reply_audio(audio_url)
                return True
        except Exception as e:
            print(f"Upload {field} failed: {e}")
            self.last_upload_ok = False
            return False

    def _show_reply(self, text: str):
        if not self.board or not HAS_PIL:
            return
        try:
            self.current_reply = text
            img = Image.new("RGB", (240, 280), COLOR_BLACK)
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
                small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except Exception:
                font = ImageFont.load_default()
                small = font
            draw.text((10, 10), "Bee reply", font=font, fill=COLOR_GREEN)
            # Wrap text roughly
            lines = []
            words = text.split()
            line = ""
            for word in words:
                if len(line) + len(word) + 1 < 28:
                    line += " " + word if line else word
                else:
                    lines.append(line)
                    line = word
            if line:
                lines.append(line)
            y = 50
            for line in lines[:12]:
                draw.text((10, y), line, font=font, fill=COLOR_WHITE)
                y += 22
            draw.text((10, 260), "[click to talk again]", font=small, fill=COLOR_YELLOW)
            self.board.draw_image(0, 0, 240, 280, rgb565_bytes(img))
        except Exception as e:
            print(f"Reply display failed: {e}")

    def _play_reply_audio(self, audio_url: str):
        if not audio_url:
            return
        try:
            url = f"{BACKEND_URL}{audio_url}"
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            mp3_path = Path(tempfile.gettempdir()) / "bee-device" / "reply.mp3"
            mp3_path.parent.mkdir(exist_ok=True)
            with open(mp3_path, "wb") as f:
                f.write(r.content)
            # mpg123 handles mp3 and outputs via ALSA default card
            player = ["mpg123", "-q", str(mp3_path)]
            subprocess.run(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print(f"[AUDIO] Played reply")
        except Exception as e:
            print(f"Audio play failed: {e}")

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
                time.sleep(0.5)
                # Periodic camera photo while muted
                if self.muted and ENABLE_CAMERA and (time.time() - last_camera_time) > CAMERA_INTERVAL:
                    self._capture_and_upload()
                    last_camera_time = time.time()
                    self._update_display()
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            self._set_rgb(COLOR_BLACK)
            if self.board:
                try:
                    self.board.cleanup()
                except Exception:
                    pass
            if self.camera:
                try:
                    self.camera.stop()
                except Exception:
                    pass


if __name__ == "__main__":
    BeeDeviceWhisplay().run()
