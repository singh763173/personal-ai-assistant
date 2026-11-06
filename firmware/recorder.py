#!/usr/bin/env python3
"""
Ollama Bee Device firmware v3.1 — animated Whisplay UI

States:
  DASHBOARD -> LISTENING -> PROCESSING -> SPEAKING -> RETURN_HOME -> DASHBOARD
  DASHBOARD -> CAMERA_VOICE -> PROCESSING -> SPEAKING -> RETURN_HOME -> DASHBOARD
"""

import contextlib
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
import socket

# Wi-Fi management
try:
    from wifi_manager import create_manager

    HAS_WIFI_MANAGER = True
except Exception as e:
    print(f"wifi_manager import failed: {e}")
    HAS_WIFI_MANAGER = False

# Optional hardware libraries
try:
    from picamera2 import Picamera2

    HAS_CAMERA = True
except Exception as e:
    print(f"Camera import failed: {e}")
    HAS_CAMERA = False

try:
    from PIL import Image

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

# Load live dashboard helper
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
sys.path.insert(0, str(ASSETS_DIR))
try:
    from live_dashboard import current_wifi_rssi, current_wifi_ssid, live_dashboard_frame

    HAS_LIVE_DASHBOARD = True
except Exception as e:
    print(f"live_dashboard import failed: {e}")
    HAS_LIVE_DASHBOARD = False
finally:
    sys.path.pop(0)

# Config from env
BACKEND_URL = os.getenv("BEE_BACKEND_URL", "http://192.168.1.86:8000").rstrip("/")
DEVICE_ID = os.getenv("BEE_DEVICE_ID", "bee-pioneer-01")
API_KEY = os.getenv("BEE_API_KEY", "")
SAMPLE_RATE = int(os.getenv("BEE_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("BEE_AUDIO_CHANNELS", "2"))
AUDIO_CARD = os.getenv("BEE_AUDIO_CARD", "whisplaysound")
ENABLE_CAMERA = os.getenv("BEE_ENABLE_CAMERA", "true").lower() in ("1", "true", "yes")
LONG_PRESS_SECONDS = float(os.getenv("BEE_LONG_PRESS_SECONDS", "2.0"))
PISUGAR_HOST = os.getenv("BEE_PISUGAR_HOST", "127.0.0.1")
PISUGAR_PORT = int(os.getenv("BEE_PISUGAR_PORT", "8423"))

SILENCE_TIMEOUT_SECONDS = float(os.getenv("BEE_SILENCE_TIMEOUT", "3.0"))
MAX_RECORD_SECONDS = float(os.getenv("BEE_MAX_RECORD_SECONDS", "15.0"))
CAMERA_MAX_SECONDS = float(os.getenv("BEE_CAMERA_MAX_SECONDS", "10.0"))

# GIF assets
GIF_DASHBOARD = ASSETS_DIR / "dashboard_background_clean.gif"
GIF_LISTENING = ASSETS_DIR / "listening.gif"
GIF_CAMERA_VOICE = ASSETS_DIR / "camera_voice.gif"
GIF_PROCESSING = ASSETS_DIR / "processing.gif"
GIF_RETURN_HOME = ASSETS_DIR / "return_home.gif"

# Constants
LCD_WIDTH, LCD_HEIGHT = 240, 280
IMAGE_UPLOAD_WIDTH = 640


def rgb565_bytes(img: Image.Image) -> bytes:
    """Convert a PIL RGB image to RGB565 big-endian bytes for the Whisplay LCD."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    pixels = list(img.getdata())
    out = bytearray(len(pixels) * 2)
    for i, (r, g, b) in enumerate(pixels):
        val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[2 * i] = (val >> 8) & 0xFF
        out[2 * i + 1] = val & 0xFF
    return bytes(out)


class GifPlayer:
    """Decode and play a GIF on the Whisplay LCD in a background thread."""

    def __init__(self, draw_func):
        self.draw_func = draw_func
        self._stop_event = threading.Event()
        self._thread = None
        self._current_file = None
        self._frame_index = 0
        self._cache = {}

    def _load_gif(self, gif_path: Path):
        if gif_path in self._cache:
            return self._cache[gif_path]
        frames = []
        durations = []
        with Image.open(gif_path) as gif:
            for i in range(gif.n_frames):
                gif.seek(i)
                frames.append(gif.convert("RGB").copy())
                durations.append(max(gif.info.get("duration", 100), 20) / 1000.0)
        self._cache[gif_path] = (frames, durations)
        return frames, durations

    def _play_loop(self, gif_path: Path, loop: bool = True, overlay_func=None):
        try:
            frames, durations = self._load_gif(gif_path)
            while not self._stop_event.is_set():
                for idx, frame in enumerate(frames):
                    if self._stop_event.is_set():
                        return
                    img = overlay_func(frame, idx) if overlay_func else frame
                    self.draw_func(img)
                    self._frame_index = idx
                    if self._stop_event.wait(durations[idx]):
                        return
                if not loop:
                    final = overlay_func(frames[-1], len(frames) - 1) if overlay_func else frames[-1]
                    self.draw_func(final)
                    return
        except Exception as e:
            print(f"GIF playback error: {e}")

    def play(self, gif_path: Path, loop: bool = True, overlay_func=None):
        self.stop()
        self._stop_event.clear()
        self._current_file = gif_path
        self._thread = threading.Thread(
            target=self._play_loop,
            args=(gif_path, loop, overlay_func),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    @property
    def frame_index(self) -> int:
        return self._frame_index


class BeeDeviceWhisplay:
    STATES = {
        "DASHBOARD",
        "LISTENING",
        "CAMERA_VOICE",
        "PROCESSING",
        "SPEAKING",
        "RETURN_HOME",
        "WIFI_SETUP",
        "SHUTDOWN",
    }

    def __init__(self):
        self._state = "DASHBOARD"
        self._state_lock = threading.Lock()
        self.session = requests.Session()

        self.board = None
        self.camera = None
        self.gif = GifPlayer(self._draw_image)

        # Button gesture state
        self._press_start = 0.0
        self._long_press_triggered = False
        self._double_click_window = 0.7
        self._click_count = 0
        self._click_lock = threading.Lock()
        self._click_event = threading.Event()

        # Button debounce: ignore transitions within this window (seconds)
        self._button_debounce = 0.08
        self._last_press_time = 0.0
        self._last_release_time = 0.0
        self._button_state_lock = threading.Lock()

        self._recorder_proc = None
        self._recorder_path = None
        self._recorder_lock = threading.Lock()
        self._recording_stop_event = threading.Event()

        # Watchdog to recover from backlight being pulled low by adjacent button GPIO short
        self._display_watchdog_stop = threading.Event()
        self._display_watchdog_thread = threading.Thread(target=self._display_watchdog, daemon=True)

        self._init_whisplay()
        self._init_camera()

        # Wi-Fi manager singleton (created once, reused for triple-click setup mode)
        self.wifi_manager = create_manager() if HAS_WIFI_MANAGER else None

        # Network watchdog: log backend reachability and try to recover Wi-Fi if lost
        self._network_watchdog_stop = threading.Event()
        self._network_watchdog_thread = threading.Thread(target=self._network_watchdog, daemon=True)
        self._network_watchdog_thread.start()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: str):
        if new_state not in self.STATES:
            raise ValueError(f"Unknown state {new_state}")
        with self._state_lock:
            self._state = new_state
        print(f"[{datetime.now(UTC).isoformat()}] State -> {new_state}")

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
            print("Whisplay HAT initialized.")
        except Exception as e:
            print(f"Whisplay init failed: {e}")
            self.board = None

    def _init_camera(self):
        """Create camera object but do not keep it running to save power."""
        if not HAS_CAMERA or not ENABLE_CAMERA:
            return
        try:
            self.camera = Picamera2()
            cfg = self.camera.create_still_configuration(main={"size": (1640, 1232)})
            self.camera.configure(cfg)
            print("Camera ready (sleeping).")
        except Exception as e:
            print(f"Camera init failed: {e}")
            self.camera = None

    def _capture_image(self) -> Path | None:
        """Start camera, capture one still, and stop it again."""
        if not self.camera:
            return None
        try:
            tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
            tmp_dir.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            img_path = tmp_dir / f"{DEVICE_ID}-{stamp}.jpg"
            self.camera.start()
            time.sleep(0.8)  # let auto-exposure settle
            self.camera.capture_file(str(img_path))
            self.camera.stop()
            return img_path
        except Exception as e:
            print(f"Camera capture failed: {e}")
            return None


    def _display_watchdog(self):
        """Reassert backlight very frequently to recover from GPIO coupling/noise."""
        while not self._display_watchdog_stop.is_set():
            try:
                if self.board and HAS_WHISPLAY:
                    self.board.set_backlight(100)
            except Exception as e:
                print(f"Display watchdog failed: {e}")
            self._display_watchdog_stop.wait(0.1)

    def _draw_image(self, img: Image.Image):
        if self.board and HAS_PIL:
            try:
                self.board.draw_image(0, 0, LCD_WIDTH, LCD_HEIGHT, rgb565_bytes(img))
            except Exception as e:
                print(f"LCD draw failed: {e}")

    def _pisugar_cmd(self, cmd: str, timeout: float = 1.0) -> str:
        """Send a raw command to the PiSugar TCP server and return the first line of response."""
        try:
            with socket.create_connection((PISUGAR_HOST, PISUGAR_PORT), timeout=timeout) as sock:
                sock.sendall(f"{cmd}\n".encode())
                sock.shutdown(socket.SHUT_WR)
                response = b""
                while True:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    response += chunk
                    if b"\n" in response:
                        break
                return response.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            print(f"PiSugar cmd '{cmd}' failed: {e}")
            return ""

    def _get_battery(self):
        now = time.time()
        # Cache for 5 seconds so we don't hammer I2C on every animation frame
        if now - getattr(self, "_battery_cache_time", 0) < 5.0:
            return getattr(self, "_battery_cache_value", None)
        try:
            line = self._pisugar_cmd("get battery")
            if line.startswith("battery:"):
                value = float(line.split(":", 1)[1].strip())
                self._battery_cache_value = value
                self._battery_cache_time = now
                return value
        except Exception as e:
            print(f"Battery read failed: {e}")
        return None

    def _pisugar_plugged(self) -> bool:
        try:
            line = self._pisugar_cmd("get battery_power_plugged")
            if line.startswith("battery_power_plugged:"):
                return line.split(":", 1)[1].strip().lower() == "true"
        except Exception:
            pass
        return False

    def _pisugar_charging(self) -> bool:
        try:
            line = self._pisugar_cmd("get battery_charging")
            if line.startswith("battery_charging:"):
                return line.split(":", 1)[1].strip().lower() == "true"
        except Exception:
            pass
        return False

    def _check_backend_online(self, timeout: float = 5.0) -> bool:
        """Return True if the configured backend /health endpoint responds."""
        try:
            r = requests.get(f"{BACKEND_URL}/api/v1/health", timeout=timeout)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception as e:
            print(f"Backend online check failed: {e}")
            return False

    def _dashboard_overlay(self, frame: Image.Image, frame_index: int) -> Image.Image:
        # Reassert backlight every frame; the adjacent button pin can momentarily
        # pull the backlight line low/off, so keep driving it high (on).
        if self.board and HAS_WHISPLAY:
            try:
                self.board.set_backlight(100)
            except Exception:
                pass
        if not HAS_LIVE_DASHBOARD:
            return frame
        try:
            battery = self._get_battery() or 0
            ssid = current_wifi_ssid()
            rssi = current_wifi_rssi() if ssid else None
            status_text = None
            if not self._pisugar_charging() and self._pisugar_plugged():
                status_text = "plugged in"
            return live_dashboard_frame(
                battery_percent=battery,
                frame_index=frame_index,
                animation_file=GIF_DASHBOARD,
                wifi_connected=ssid is not None,
                wifi_rssi=rssi,
                backend_online=self._check_backend_online(),
                status_text=status_text,
                charging=self._pisugar_charging(),
            )
        except Exception as e:
            print(f"Dashboard overlay failed: {e}")
            return frame

    # ---- State transitions ----

    def _enter_dashboard(self):
        self._set_state("DASHBOARD")
        self.gif.play(GIF_DASHBOARD, loop=True, overlay_func=self._dashboard_overlay)
        self._set_rgb(0, 0, 255)

    def _enter_listening(self):
        self._set_state("LISTENING")
        self.gif.play(GIF_LISTENING, loop=True)
        self._set_rgb(0, 255, 0)
        self._start_recording()
        threading.Thread(target=self._listen_then_process, daemon=True).start()

    def _enter_camera_voice(self):
        self._set_state("CAMERA_VOICE")
        self.gif.play(GIF_CAMERA_VOICE, loop=True)
        self._set_rgb(255, 200, 0)
        threading.Thread(target=self._capture_then_listen, daemon=True).start()

    def _enter_processing(self):
        self._set_state("PROCESSING")
        self.gif.play(GIF_PROCESSING, loop=True)
        self._set_rgb(0, 120, 255)

    def _enter_speaking(self, reply_text: str, audio_url: str):
        self._set_state("SPEAKING")
        self.gif.play(GIF_PROCESSING, loop=True)
        threading.Thread(target=self._speak_reply, args=(reply_text, audio_url), daemon=True).start()

    def _enter_return_home(self):
        self._set_state("RETURN_HOME")
        self.gif.play(GIF_RETURN_HOME, loop=False)
        threading.Thread(target=self._return_home_then_dashboard, daemon=True).start()

    def _set_rgb(self, *color):
        if self.board:
            try:
                if len(color) == 1 and isinstance(color[0], tuple):
                    self.board.set_rgb(*color[0])
                elif len(color) == 3:
                    self.board.set_rgb(*color)
                else:
                    self.board.set_rgb(*color)
                # Ensure backlight stays on after LED update; shared power/GPIO noise can dim it.
                self.board.set_backlight(100)
            except Exception as e:
                print(f"LED set failed: {e}")

    # ---- Recording ----

    def _start_recording(self) -> Path:
        tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
        tmp_dir.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        wav_path = tmp_dir / f"{DEVICE_ID}-{stamp}.wav"

        cmd = [
            "arecord",
            "-D",
            f"hw:{AUDIO_CARD}",
            "-c",
            str(AUDIO_CHANNELS),
            "-r",
            str(SAMPLE_RATE),
            "-f",
            "S16_LE",
            str(wav_path),
        ]
        print(f"[REC] Start -> {wav_path}")
        with self._recorder_lock:
            self._recorder_path = wav_path
            self._recorder_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._recording_stop_event.clear()
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
        print(f"[REC] Stop -> {wav_path}")
        return wav_path

    def _wait_for_silence(self, wav_path: Path, timeout: float, silence_seconds: float):
        start = time.monotonic()
        last_size = 0
        silent_since = None
        while time.monotonic() - start < timeout:
            time.sleep(0.2)
            if self._recording_stop_event.is_set():
                return True
            size = wav_path.stat().st_size if wav_path.exists() else 0
            if size > last_size:
                last_size = size
                silent_since = None
            else:
                if silent_since is None:
                    silent_since = time.monotonic()
                elif time.monotonic() - silent_since >= silence_seconds:
                    print("[REC] Silence detected")
                    return True
        print("[REC] Max duration reached")
        return True

    def _listen_then_process(self):
        wav_path = self._recorder_path
        if not wav_path:
            return
        try:
            self._wait_for_silence(wav_path, MAX_RECORD_SECONDS, SILENCE_TIMEOUT_SECONDS)
        finally:
            wav_path = self._stop_recording()
        self._enter_processing()
        self._upload_ask("/api/v1/ask", wav_path)
        self._cleanup(wav_path)

    def _capture_then_listen(self):
        img_path = self._capture_image()
        if not img_path:
            self._enter_dashboard()
            return
        try:
            wav_path = self._start_recording()
            # Wait for button release or max duration
            release_event = threading.Event()

            def wait_release():
                # The button release callback will set _recording_stop_event when detected
                while self.state == "CAMERA_VOICE" and not self._recording_stop_event.is_set():
                    time.sleep(0.05)
                release_event.set()

            threading.Thread(target=wait_release, daemon=True).start()
            release_event.wait(timeout=CAMERA_MAX_SECONDS)
            wav_path = self._stop_recording()
            self._enter_processing()
            self._upload_ask_with_image(img_path, wav_path)
        finally:
            self._cleanup(img_path)
            if self._recorder_path:
                self._stop_recording()

    def _capture_image(self) -> Path:
        if not self.camera:
            return None
        tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
        tmp_dir.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        raw_path = tmp_dir / f"{DEVICE_ID}-{stamp}-raw.jpg"
        img_path = tmp_dir / f"{DEVICE_ID}-{stamp}.jpg"
        try:
            self.camera.capture_file(str(raw_path))
            # Downscale for faster upload
            with Image.open(raw_path) as img:
                img.thumbnail((IMAGE_UPLOAD_WIDTH, IMAGE_UPLOAD_WIDTH), Image.Resampling.LANCZOS)
                img.save(img_path, "JPEG", quality=85)
            raw_path.unlink(missing_ok=True)
            print(f"Captured -> {img_path} ({img_path.stat().st_size} bytes)")
            return img_path
        except Exception as e:
            print(f"Camera capture failed: {e}")
            return None

    # ---- Backend uploads ----

    def _upload_ask(self, url_path: str, wav_path: Path):
        url = f"{BACKEND_URL}{url_path}"
        try:
            with open(wav_path, "rb") as f:
                files = {"audio": (wav_path.name, f, "audio/wav")}
                data = {"device_id": DEVICE_ID}
                headers = {"Authorization": API_KEY} if API_KEY else {}
                resp = self.session.post(url, files=files, data=data, headers=headers, timeout=120)
                resp.raise_for_status()
                result = resp.json()
                reply = result.get("reply", "")
                audio_url = result.get("audio_url")
                self._enter_speaking(reply, audio_url)
                return True
        except Exception as e:
            print(f"Upload/ask failed: {e}")
            self._enter_return_home()
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
                self._enter_speaking(reply, audio_url)
                return True
        except Exception as e:
            print(f"Vision ask failed: {e}")
            self._enter_return_home()
            return False

    def _speak_reply(self, reply_text: str, audio_url: str):
        if not reply_text:
            self._enter_return_home()
            return
        try:
            if audio_url:
                url = f"{BACKEND_URL}{audio_url}"
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                mp3_path = Path(tempfile.gettempdir()) / "bee-device" / "reply.mp3"
                mp3_path.parent.mkdir(exist_ok=True)
                with open(mp3_path, "wb") as f:
                    f.write(r.content)
                player = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)]
                subprocess.run(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                print("[AUDIO] Played reply")
            else:
                print("[AUDIO] No audio URL; reply text only")
        except Exception as e:
            print(f"Audio play failed: {e}")
        finally:
            self._enter_return_home()

    def _return_home_then_dashboard(self):
        # Wait for the one-shot GIF to finish roughly, then back to dashboard
        time.sleep(2.5)
        self._enter_dashboard()

    def _cleanup(self, path: Path):
        with contextlib.suppress(Exception):
            path.unlink()

    # ---- Button handling ----

    def _on_button_press(self):
        now = time.monotonic()
        with self._button_state_lock:
            if now - self._last_press_time < self._button_debounce:
                return
            self._last_press_time = now
        self._press_start = now
        self._long_press_triggered = False
        # Reassert backlight immediately; some button transitions can couple onto the backlight line.
        try:
            if self.board and HAS_WHISPLAY:
                self.board.set_backlight(100)
        except Exception as e:
            print(f"Backlight reassert on press failed: {e}")

    def _on_button_release(self):
        now = time.monotonic()
        with self._button_state_lock:
            if now - self._last_release_time < self._button_debounce:
                return
            self._last_release_time = now

        # Reassert backlight after release as well.
        try:
            if self.board and HAS_WHISPLAY:
                self.board.set_backlight(100)
        except Exception as e:
            print(f"Backlight reassert on release failed: {e}")

        duration = now - self._press_start
        if duration >= LONG_PRESS_SECONDS:
            if not self._long_press_triggered:
                self._long_press_triggered = True
                self._on_long_press()
            return

        # Require a minimum press time to count as an intentional click.
        # Bounce/noise can produce sub-50 ms press/release pairs.
        if duration < 0.05:
            return

        # If in camera voice mode, signal recording to stop on release
        if self.state == "CAMERA_VOICE":
            self._recording_stop_event.set()

        with self._click_lock:
            self._click_count += 1
            count = self._click_count
            self._click_event.set()
            if count == 1:
                threading.Thread(target=self._handle_click_gesture, daemon=True).start()

    def _handle_click_gesture(self):
        """Detect single/double/triple clicks with a sliding window.

        Each new click extends the decision window from the most recent release,
        so slower triple-clicks still register.
        """
        while True:
            # Wait the full window; if no new click arrives, decide now.
            self._click_lock.acquire()
            start_count = self._click_count
            self._click_lock.release()

            if self._click_event.wait(timeout=self._double_click_window):
                self._click_event.clear()
                # A new press/release happened within the window; loop again to extend it.
                continue

            # No new click within window: decide gesture.
            with self._click_lock:
                count = self._click_count
                self._click_count = 0

            if count >= 3:
                self._on_triple_click()
            elif count >= 2:
                self._on_double_click()
            elif count == 1:
                self._on_single_click()
            return

    def _on_single_click(self):
        if self.state != "DASHBOARD":
            return
        self._enter_listening()

    def _on_triple_click(self):
        if not HAS_WIFI_MANAGER or not self.wifi_manager:
            print("WiFi manager not available")
            return
        if self.state == "WIFI_SETUP":
            print("Already in WiFi setup mode")
            return
        print("Triple click: entering WiFi setup mode")
        self._set_state("WIFI_SETUP")
        self.gif.stop()
        # Show a clear visual: white screen with setup label
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (240, 280), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
                small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except Exception:
                font = small = ImageFont.load_default()
            draw.text((120, 100), "Wi-Fi Setup", fill=(0, 0, 0), font=font, anchor="mm")
            draw.text((120, 140), "AP: bee-config", fill=(0, 0, 0), font=small, anchor="mm")
            draw.text((120, 165), "http://192.168.4.1:8080", fill=(0, 0, 255), font=small, anchor="mm")
            self._draw_image(img)
            self._set_rgb(255, 0, 255)
        except Exception as e:
            print(f"Setup screen failed: {e}")
            self._set_rgb(0, 0, 255)
        try:
            self.wifi_manager.enter_setup_mode()
        except Exception as e:
            print(f"Failed to start setup mode: {e}")

    def _on_double_click(self):
        if self.state not in {"DASHBOARD", "LISTENING"}:
            return
        if self.state == "LISTENING":
            self._recording_stop_event.set()
            self._stop_recording()
        self._enter_camera_voice()

    def _on_long_press(self):
        self._set_state("SHUTDOWN")
        self.gif.stop()
        self._set_rgb(255, 0, 0)
        if self.camera:
            with contextlib.suppress(Exception):
                self.camera.stop()
        os.system("sudo shutdown -h now")
        time.sleep(10)

    def _network_watchdog(self):
        """Log backend reachability and try to restart Wi-Fi if unreachable."""
        fail_count = 0
        while not self._network_watchdog_stop.is_set():
            self._network_watchdog_stop.wait(60)
            if self._network_watchdog_stop.is_set():
                return
            reachable = self._check_backend_online()
            if reachable:
                if fail_count:
                    print("[NET] Backend reachable again")
                fail_count = 0
            else:
                fail_count += 1
                print(f"[NET] Backend unreachable ({fail_count}/3)")
                if fail_count >= 3:
                    print("[NET] Attempting Wi-Fi recovery")
                    try:
                        subprocess.run(["sudo", "nmcli", "connection", "up", "netplan-wlan0-IoT-Network"], timeout=30, check=False)
                    except Exception as e:
                        print(f"[NET] Wi-Fi recovery failed: {e}")
                    fail_count = 0

    def run(self):
        print(f"Bee device {DEVICE_ID} starting. Backend: {BACKEND_URL}")
        print("Single click = voice, Double click = photo+voice, Triple click = WiFi setup, Long press = shutdown")
        self._enter_dashboard()
        self._display_watchdog_thread.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            self._display_watchdog_stop.set()
            self._network_watchdog_stop.set()
            self.gif.stop()
            self._set_rgb(0, 0, 0)
            if self.board:
                with contextlib.suppress(Exception):
                    self.board.cleanup()
            if self.camera:
                with contextlib.suppress(Exception):
                    self.camera.stop()


if __name__ == "__main__":
    BeeDeviceWhisplay().run()
