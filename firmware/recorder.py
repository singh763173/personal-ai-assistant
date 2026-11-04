#!/usr/bin/env python3
"""
Ollama Bee Device firmware v3.0 — animated Whisplay UI

States:
  DASHBOARD -> LISTENING -> PROCESSING -> SPEAKING -> RETURN_HOME -> DASHBOARD
  DASHBOARD -> CAMERA_VOICE -> PROCESSING -> SPEAKING -> RETURN_HOME -> DASHBOARD
"""
import os
import time
import subprocess
import threading
import json
import tempfile
import wave
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

# Load live dashboard helper
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
sys_path_inserted = False
try:
    import sys
    sys.path.insert(0, str(ASSETS_DIR))
    sys_path_inserted = True
    from live_dashboard import live_dashboard_frame
    HAS_LIVE_DASHBOARD = True
except Exception as e:
    print(f"live_dashboard import failed: {e}")
    HAS_LIVE_DASHBOARD = False
finally:
    if sys_path_inserted:
        sys.path.pop(0)

# Config from env
BACKEND_URL = os.getenv("BEE_BACKEND_URL", "http://192.168.1.86:8000")
DEVICE_ID = os.getenv("BEE_DEVICE_ID", "bee-pioneer-01")
API_KEY = os.getenv("BEE_API_KEY", "")
SAMPLE_RATE = int(os.getenv("BEE_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("BEE_AUDIO_CHANNELS", "2"))
AUDIO_CARD = os.getenv("BEE_AUDIO_CARD", "whisplaysound")
ENABLE_CAMERA = os.getenv("BEE_ENABLE_CAMERA", "true").lower() in ("1", "true", "yes")
LONG_PRESS_SECONDS = float(os.getenv("BEE_LONG_PRESS_SECONDS", "2.0"))
PISUGAR_API = os.getenv("BEE_PISUGAR_API", "http://localhost:8423")

SILENCE_TIMEOUT_SECONDS = float(os.getenv("BEE_SILENCE_TIMEOUT", "3.0"))
MAX_RECORD_SECONDS = float(os.getenv("BEE_MAX_RECORD_SECONDS", "15.0"))

# GIF assets
GIF_DASHBOARD = ASSETS_DIR / "dashboard_background.gif"
GIF_LISTENING = ASSETS_DIR / "listening.gif"
GIF_CAMERA_VOICE = ASSETS_DIR / "camera_voice.gif"
GIF_PROCESSING = ASSETS_DIR / "processing.gif"
GIF_RETURN_HOME = ASSETS_DIR / "return_home.gif"


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

    def _play_loop(self, gif_path: Path, loop: bool = True, overlay_func=None):
        try:
            with Image.open(gif_path) as gif:
                frames = []
                durations = []
                for i in range(gif.n_frames):
                    gif.seek(i)
                    frames.append(gif.convert("RGB").copy())
                    # Duration in seconds; default 100ms
                    durations.append(max(gif.info.get("duration", 100), 20) / 1000.0)

                while not self._stop_event.is_set():
                    for idx, frame in enumerate(frames):
                        if self._stop_event.is_set():
                            return
                        img = overlay_func(frame, idx) if overlay_func else frame
                        self.draw_func(img)
                        self._frame_index = idx
                        # Wait duration, but allow early stop
                        if self._stop_event.wait(durations[idx]):
                            return
                    if not loop:
                        # For one-shot GIFs, stay on the final frame
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
        "DASHBOARD", "LISTENING", "CAMERA_VOICE", "PROCESSING",
        "SPEAKING", "RETURN_HOME", "SHUTDOWN",
    }

    def __init__(self):
        self.state = "DASHBOARD"
        self.lock = threading.Lock()
        self.session = requests.Session()

        self.board = None
        self.camera = None
        self.gif = GifPlayer(self._draw_image)

        # Button gesture state
        self._press_start = 0.0
        self._long_press_triggered = False
        self._double_click_window = 0.35
        self._click_count = 0
        self._click_lock = threading.Lock()

        self._recorder_proc = None
        self._recorder_path = None
        self._recorder_lock = threading.Lock()
        self._recording_stop_event = threading.Event()

        self._init_whisplay()
        self._init_camera()

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

    def _draw_image(self, img: Image.Image):
        if self.board and HAS_PIL:
            try:
                self.board.draw_image(0, 0, 240, 280, rgb565_bytes(img))
            except Exception as e:
                print(f"LCD draw failed: {e}")

    def _get_battery(self):
        try:
            r = self.session.get(f"{PISUGAR_API}/api/power", timeout=3)
            r.raise_for_status()
            data = r.json()
            return data.get("battery_percentage") or data.get("battery") or data.get("level")
        except Exception:
            return None

    def _dashboard_overlay(self, frame: Image.Image, frame_index: int) -> Image.Image:
        if not HAS_LIVE_DASHBOARD:
            return frame
        try:
            # live_dashboard_frame re-opens the GIF; pass the same file and frame index
            battery = self._get_battery() or 0
            return live_dashboard_frame(
                battery_percent=battery,
                frame_index=frame_index,
                animation_file=GIF_DASHBOARD,
            )
        except Exception as e:
            print(f"Dashboard overlay failed: {e}")
            return frame

    def _set_state(self, new_state: str):
        with self.lock:
            if new_state not in self.STATES:
                raise ValueError(f"Unknown state {new_state}")
            self.state = new_state
        print(f"[{datetime.now(timezone.utc).isoformat()}] State -> {new_state}")

    def _enter_dashboard(self):
        self._set_state("DASHBOARD")
        self.gif.play(GIF_DASHBOARD, loop=True, overlay_func=self._dashboard_overlay)
        self._set_rgb(0, 0, 255)

    def _enter_listening(self):
        self._set_state("LISTENING")
        self.gif.play(GIF_LISTENING, loop=True)
        self._set_rgb(0, 255, 0)
        self._start_recording()
        # Start a thread to stop recording on silence timeout or max duration
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
        self.gif.stop()
        # Keep last dashboard/processing frame briefly, then play audio
        threading.Thread(target=self._speak_reply, args=(reply_text, audio_url), daemon=True).start()

    def _enter_return_home(self):
        self._set_state("RETURN_HOME")
        self.gif.play(GIF_RETURN_HOME, loop=False)
        # Wait for one-shot GIF to finish roughly, then go dashboard
        threading.Thread(target=self._return_home_then_dashboard, daemon=True).start()

    def _set_rgb(self, color):
        if self.board:
            try:
                if isinstance(color, tuple):
                    self.board.set_rgb(*color)
                else:
                    self.board.set_rgb(color)
            except Exception as e:
                print(f"LED set failed: {e}")

    # ---- Recording ----

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

    def _wav_duration_seconds(self, wav_path: Path) -> float:
        try:
            with wave.open(str(wav_path), "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                return frames / float(rate) if rate else 0.0
        except Exception:
            return 0.0

    def _wait_for_silence(self, wav_path: Path, timeout: float, silence_seconds: float):
        """Monitor the recording file; stop when it stops growing for silence_seconds."""
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
        # Wait for speech to finish
        self._wait_for_silence(wav_path, MAX_RECORD_SECONDS, SILENCE_TIMEOUT_SECONDS)
        wav_path = self._stop_recording()
        self._enter_processing()
        self._upload_ask("/api/v1/ask", wav_path)
        self._cleanup(wav_path)

    def _capture_then_listen(self):
        img_path = self._capture_image()
        if not img_path:
            self._enter_dashboard()
            return
        # Continue showing camera_voice while recording the question
        wav_path = self._start_recording()
        self._wait_for_silence(wav_path, 8.0, SILENCE_TIMEOUT_SECONDS)
        wav_path = self._stop_recording()
        self._enter_processing()
        self._upload_ask_with_image(img_path, wav_path)
        self._cleanup(wav_path)
        self._cleanup(img_path)

    def _capture_image(self) -> Path:
        if not self.camera:
            return None
        tmp_dir = Path(tempfile.gettempdir()) / "bee-device"
        tmp_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        img_path = tmp_dir / f"{DEVICE_ID}-{stamp}.jpg"
        try:
            self.camera.capture_file(str(img_path))
            print(f"Captured -> {img_path}")
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
        if not audio_url or not reply_text:
            self._enter_return_home()
            return
        try:
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
        except Exception as e:
            print(f"Audio play failed: {e}")
        finally:
            self._enter_return_home()

    def _return_home_then_dashboard(self):
        # Wait for the one-shot GIF to finish (approx 2s); then back to dashboard
        time.sleep(2.5)
        self._enter_dashboard()

    def _cleanup(self, path: Path):
        try:
            path.unlink()
        except Exception:
            pass

    # ---- Button handling ----

    def _on_button_press(self):
        self._press_start = time.monotonic()
        self._long_press_triggered = False

    def _on_button_release(self):
        now = time.monotonic()
        duration = now - self._press_start
        if duration >= LONG_PRESS_SECONDS:
            if not self._long_press_triggered:
                self._long_press_triggered = True
                self._on_long_press()
            return

        with self._click_lock:
            self._click_count += 1
            count = self._click_count
            if count == 1:
                threading.Thread(target=self._handle_click_gesture, daemon=True).start()

    def _handle_click_gesture(self):
        time.sleep(self._double_click_window)
        with self._click_lock:
            count = self._click_count
            self._click_count = 0

        if count >= 2:
            self._on_double_click()
        elif count == 1:
            self._on_single_click()

    def _on_single_click(self):
        # Only act from dashboard
        with self.lock:
            if self.state != "DASHBOARD":
                return
        self._enter_listening()

    def _on_double_click(self):
        with self.lock:
            if self.state not in {"DASHBOARD", "LISTENING"}:
                return
        # If we were already listening, stop that and do camera+voice
        if self.state == "LISTENING":
            self._recording_stop_event.set()
            self._stop_recording()
        self._enter_camera_voice()

    def _on_long_press(self):
        self._set_state("SHUTDOWN")
        self.gif.stop()
        self._set_rgb(255, 0, 0)
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
        os.system("sudo shutdown -h now")
        time.sleep(10)

    def run(self):
        print(f"Bee device {DEVICE_ID} starting. Backend: {BACKEND_URL}")
        print("Single click = voice, Double click = photo+voice, Long press = shutdown")
        self._enter_dashboard()
        try:
            while True:
                # Keep the dashboard clock/battery updating; the GIF loop handles frames,
                # but the overlay refreshes itself when called per frame.
                time.sleep(1)
                if self.state == "DASHBOARD":
                    # Force an immediate frame refresh so clock updates within a second
                    pass
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            self.gif.stop()
            self._set_rgb(0, 0, 0)
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
