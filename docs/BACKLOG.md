# Bee Pioneer — Backlog of Enhancements and Improvements

## ✅ Completed (today)

- Onboard Wi-Fi travel setup via triple-click AP (`bee-config` at 192.168.4.1)
- Known-network persistence and roaming across saved SSIDs
- Dynamic dashboard overlay with new fonts, Wi-Fi signal bars, backend status dot, battery icon
- Baked-in "READY" and bottom pill text removed from dashboard GIF; labels now drawn at runtime
- Piper local TTS option integrated (default on backend, edge-tts fallback available)
- NAS backup to Synology over SSH with nightly cron
- Backend `/api/v1/health` enhanced for device status checks
- Device checks backend health and reflects it on the dashboard
- ruff clean + pytest passing across backend and firmware
- Latest code and assets pushed to GitHub and deployed to Pi + LXC backend

## 🎯 Next — High Value / Low Risk

### 1. PiSugar battery integration
- Read real battery % from PiSugar over I2C / API instead of placeholder
- Add charging indicator (bolt icon) when plugged in
- Low-battery warning overlay and auto-shutdown below 10 %

### 2. Listening / processing / speaking animations
- Replace static GIFs with runtime waveform/spectrum visualiser during LISTENING
- Radial spinner for PROCESSING
- Dedicated SPEAKING state with mascot mouth movement or audio bars
- Draw these overlays instead of relying on GIF frames

### 3. Voice activity detection (VAD)
- Stop recording on silence rather than button release only
- Better double-click/triple-click experience; avoid accidental triggers
- Adjustable sensitivity via env var

### 4. Offline fallbacks
- Cache a tiny LLM (`phi4-mini` / `qwen2.5:0.5b` / `gemma2:2b`) on the Pi for basic replies when backend unreachable
- Local intent routing: "what time is it?", "set a timer", "weather?" can be handled on-device

### 5. Vision improvements
- Add red dot / flash overlay while capturing
- Vision prompt optimisation for the Bee use-case
- Allow image-only periodic capture if requested (re-enable `BEE_AUTO_CAMERA_INTERVAL` safely)

### 6. Audio playback quality
- Test and tune Piper voice for naturalness (other voices, speed/length scale)
- Reduce Piper ONNX affinity warnings or move TTS to a dedicated service if latency unacceptable
- Add volume control and headphone/amp detection

### 7. Dashboard web UI polish
- Show battery history / last-seen / conversation list with audio playback
- Dark/light mode toggle
- Mobile-first responsive refinements

## 🔧 Next — Infrastructure / Reliability

### 8. End-to-end monitoring and alerting
- External monitor check for Whisper service health
- Alert if Pi `bee-device` hasn't checked in for > N minutes
- Backup success/failure notifications

### 9. Robust deployments
- Add `deploy-firmware.sh` check for stale `/tmp/live_dashboard.py` and similar stale pyc traps
- Version the device image/config; rollback capability
- CI build that lints, tests, and validates assets exist

### 10. Security hardening
- Rotate device API key periodically or support key derivation
- Audit public_paths; ensure no unintended endpoints are exposed
- Harden setup AP: optional WPA2, timeout after 10 minutes, auto-disable

### 11. AWS zero-bill rules
- Draft and review cost-guard rules once API keys provided
- No resource creation until rules approved

## 🚀 Future / Bigger Bets

### 12. Wearable enclosure and hardware
- 3D-printed case design with button, LED, screen bezel, mic/speaker cavities
- PiSugar battery hat mount and USB-C pass-through
- Magnetic or clip mounting for wearable use

### 13. Always-on / wake-word
- Lightweight on-device wake-word (`openwakeword` / `porcupine` / `snowboy`) so it does not need button press
- Pair with VAD for hands-free use

### 14. Multi-modal agent memory
- Vector memory of past conversations (searchable via `nomic-embed-text`)
- Per-device personalised context
- Long-term todo follow-up and reminders

### 15. Companion mobile app
- Bluetooth or web-based companion for setup without AP mode
- Push notifications for replies / alerts

## 📋 Suggested Priority Order

1. PiSugar battery integration
2. LISTENING/PROCESSING/SPEAKING runtime animations
3. Voice activity detection (VAD)
4. Whisper service monitoring alert
5. Dashboard UI polish
6. Offline tiny-LLM fallback
7. Wake-word
8. Wearable enclosure
9. Security / key rotation
10. AWS zero-bill rules + resources
