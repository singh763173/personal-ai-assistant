# Bee Wearable / Backend — End-to-End Review

Date: 2026-11-04
Repo: `https://github.com/singh763173/personal-ai-assistant`
Scope: backend (`/backend`), firmware (`/firmware`), runtime services, deployment scripts.

---

## Executive Summary

The project works end-to-end: the Pi records audio, the LXC backend runs Q&A/vision, and the AIServer01 Whisper service has cut response time from ~13 s to ~3 s. The main risks now are **maintainability, edge-case robustness, and a few live bugs** rather than missing features.

Top priorities to address:

1. Fix the dashboard JavaScript syntax error (`await ()`)
2. Stop re-opening the dashboard GIF on every frame (Pi CPU waste)
3. Add DB migrations and periodic pruning
4. Secure the LAN Whisper service with a shared secret
5. Replace inline prints with structured logging
6. Add health/telemetry endpoint for the Pi
7. Split the monolithic `backend/main.py`

---

## 1. Security

| Issue | Severity | Notes |
|---|---|---|
| Dashboard login not set by installer | Medium | `install-backend.sh` sets `BEE_ADMIN_TOKEN` but the code needs `BEE_ADMIN_USERNAME` + `BEE_ADMIN_PASSWORD_HASH`. New installs will have no admin unless env is manually populated. |
| Whisper service has no auth | Medium | `bee-whisper` on `192.168.1.86:8001` accepts any LAN client. Add an `Authorization` header check. |
| Session cookie `secure=True` breaks local HTTP | Low | Cookie is only sent over HTTPS. Fine behind Cloudflare, but local testing on `http://192.168.1.56:8000` silently fails. Make it conditional on `request.url.scheme`. |
| No brute-force protection on `/api/v1/login` | Low | Add exponential backoff / CAPTCHA after repeated failures. |
| Rate limit is in-memory | Low | Per-process dict is fine for a single backend, but not obvious. Document. |
| `static/` files bypass admin gate only partially | Low | `if path.startswith("/static/"): pass` still falls through to the session check, which is correct, but the empty branch is confusing. |
| API keys hashed only with SHA-256 | Low | Better than plaintext, but still fast. Consider bcrypt or at least rate-limit key validation. |
| Device IDs not sanitized beyond length | Low | Could allow path traversal in filenames. Use a safe slug. |

**Recommendations**

- Add `WHISPER_API_KEY` env var to both backend and whisper service; reject requests without it.
- Update `install-backend.sh` to prompt for admin username/password and write `BEE_ADMIN_USERNAME` / `BEE_ADMIN_PASSWORD_HASH`.
- Conditional secure cookie.

---

## 2. Reliability & Error Handling

| Issue | Severity | Notes |
|---|---|---|
| `transcribe()` remote fallback can fail if `whisper_model=None` | High | If `WHISPER_URL` is set but the remote service is down, the fallback calls `whisper_model.transcribe(...)` where `whisper_model` is `None`. The code currently raises `AttributeError` and the request crashes. |
| DB sessions opened with `next(get_db())` not always closed | Medium | `upload_audio`, `ask_endpoint`, `upload_image` call `db.close()` inconsistently. Some use `try/finally`, some don't. |
| No retry/backoff for external calls | Medium | Ollama Cloud, edge-tts, Whisper service, PiSugar all fail on first transient error. |
| State machine has race conditions | Medium | `_on_single_click`, `_on_double_click`, `_enter_*` access `self.state` without a consistent lock, and they spawn threads that also change state. Double-click during listening can leave a dangling recorder process. |
| Camera init can crash on import | Low | `Picamera2` import failure is caught, but on a Pi Zero 2 W it is heavy. Camera start sleeps 1 s unconditionally. |
| `_return_home_then_dashboard` hardcodes 2.5 s sleep | Low | Should derive from GIF duration or wait for `_stop_event`. |
| `arecord` device/card can be busy | Low | No recovery if another process holds the ALSA device. |

**Recommendations**

- Fix the Whisper fallback to load the local model lazily or return an explicit error.
- Use FastAPI `Depends(get_db)` consistently and ensure every `next(get_db())` has a matching `db.close()`.
- Add a small retry helper for Ollama/Whisper/TTS.
- Use `self.lock` around all state reads/writes in `recorder.py` and kill/recorder cleanup.

---

## 3. Performance

| Status | Notes |
|---|---|
| Whisper moved to AIServer01 — done | Response time dropped from ~13 s to ~3 s. |
| TTS still network-bound | `edge-tts` calls Microsoft servers. On a slow internet day this dominates latency. Consider local `piper-tts` for offline use. |
| Dashboard GIF overlay is inefficient | `live_dashboard_frame()` re-opens the GIF file and re-creates fonts on every frame. On Pi Zero 2 W this burns CPU and SD card I/O. |
| Image uploads are full-resolution JPEGs | Camera Module 3 at 1640×1232 produces large files. Resize/compress before upload to reduce Pi→Cloudflare→Backend time. |
| No audio compression | 16 kHz mono WAV is fine, but could stream Opus for even smaller uploads. |
| Backend still loads Whisper model even when remote | `WHISPER_LOCAL` check skips instantiation, good. But `faster-whisper` remains a heavy import. |

**Recommendations**

- Cache decoded GIF frames and fonts in `live_dashboard.py`.
- Downscale camera image to ~640×480 before upload.
- Benchmark local `piper-tts` vs `edge-tts` for reply latency.

---

## 4. Code Quality & Maintainability

| Issue | Severity | Notes |
|---|---|---|
| `backend/main.py` is 751 lines and monolithic | High | Auth, DB, models, LLM prompts, endpoints, TTS, security middleware all in one file. |
| `dashboard.html` has a JS syntax error | High | Line 95: `const token = await ();` — the dashboard will fail to load actions. The `api()` function also references `token` but never uses it. |
| Duplicated upload logic | Medium | `upload_audio`, `ask_endpoint`, and `upload_image` repeat temp-dir handling, file validation, DB writes, and TTS generation. |
| Magic numbers everywhere | Medium | `240, 280`, `1640, 1232`, `15.0`, `8.0`, `2.5`, `0.35`, `4096`, etc. Should be module-level constants. |
| `ask_ollama` and `ask_llm` have hardcoded prompts | Medium | Prompts are embedded in code. Move to templates or config files. |
| Type hints incomplete | Low | Mix of `Path`, `str`, optional fields; some functions untyped. |
| `__pycache__` tracked? | Low | `.gitignore` exists; confirm it ignores `__pycache__`, `*.pyc`, `venv/`, `audio_replies/`, `bee.db`. |

**Recommendations**

- Split `main.py` into `auth.py`, `models.py`, `llm.py`, `tts.py`, `uploads.py`, `admin.py`.
- Fix the dashboard JS bug immediately.
- Extract constants to a `config.py` or `settings.py`.
- Move prompts to `backend/prompts/`.

---

## 5. Deployment & Operations

| Issue | Severity | Notes |
|---|---|---|
| Deployment is manual `tar` + `scp` + `pct push` | Medium | Error-prone and not reproducible. Consider a GitHub Actions workflow or at least a `deploy.sh`. |
| `install-backend.sh` `Requires=ollama.service` | Medium | Backend fails to start if Ollama is remote or not installed. Use `After=` only. |
| No backup for `bee.db` / `audio_replies` | High | SQLite + MP3 files are on the LXC. No cron backup or off-host sync. |
| No log rotation | Low | `journald` handles it, but `audio_replies/` will grow unbounded. |
| No health/alerting for Whisper service | Medium | If `bee-whisper` dies, backend falls back to local Whisper on a 2-core LXC and becomes very slow silently. |
| `.env` contains secrets in systemd `EnvironmentFile` | Low | Acceptable for homelab, but secrets are visible in `/proc`. Consider `LoadCredential=` or a secrets file with strict perms. |

**Recommendations**

- Add a nightly backup of `bee.db` and `audio_replies/` to the NAS or S3.
- Add a `deploy.sh` that pushes code and restarts services.
- Change `Requires=` to `After=` in `install-backend.sh`.
- Add a Telegram alert if `bee-whisper` health fails.

---

## 6. UI / UX

| Issue | Severity | Notes |
|---|---|---|
| Dashboard JS broken | High | As above, `api()` function is invalid. |
| Conversations table shows summary/to-do columns | Low | For `/api/v1/ask` conversations, `summary` is empty and `reply` is the useful field. Add a "Reply" column and an audio player. |
| No live refresh | Low | Dashboard loads once. Add polling or SSE for new conversations. |
| Login page has no error display | Low | Failed login returns 401 HTML; the static form shows nothing. |
| No mobile-specific layout tweaks | Low | Works on mobile but tables overflow. |

**Recommendations**

- Fix dashboard JS and add a reply/audio column.
- Auto-refresh conversations every 10 s.
- Show login error from query param.

---

## 7. Hardware / Firmware

| Issue | Severity | Notes |
|---|---|---|
| Dashboard overlay re-opens GIF per frame | High | Wastes CPU and causes visible stutter. |
| Button debounce is basic | Medium | 350 ms double-click window works, but rapid presses can misclassify. Add a press/release timestamp lock. |
| Double-click recording does not stop on button release | Medium | User explicitly asked for "stop on button release or 10 s max". Current code waits for silence or 8 s max. |
| No speaking-state GIF | Low | `_enter_speaking` stops the GIF player entirely, so the screen freezes on the last processing/dashboard frame during audio playback. |
| PiSugar API assumptions | Medium | `BEE_PISUGAR_API=http://localhost:8423` is used. If PiSugar server is not running, dashboard shows 0% battery silently. |
| Camera module 3 overlay `imx708` | Low | Correct for Camera Module 3; verify on actual hardware. |
| `install.sh` hardcodes Python 3.13 site-packages path | Medium | `VENV_SITE="$PROJECT_DIR/venv/lib/python3.13/site-packages"` will break on Pi OS versions with Python 3.11/3.12. Detect dynamically. |
| Whisplay runtime copied into venv site-packages | Low | Fragile. Better to install as a package or keep it in project dir. |
| No hardware health telemetry | Low | Device never reports battery, temperature, or connectivity to the backend. |

**Recommendations**

- Cache dashboard frames and fonts.
- Make double-click recording stop on button release.
- Add a `speaking.gif` or at least keep `processing.gif` running during audio playback.
- Detect venv site-packages path with `python -c "import site; print(site.getsitepackages()[0])"`.
- Add a small heartbeat endpoint where the Pi reports battery % and WiFi signal.

---

## 8. Testing & Monitoring

| Issue | Severity | Notes |
|---|---|---|
| No automated tests | High | No unit, integration, or end-to-end tests. |
| No linting/formatting | Medium | No `ruff`, `black`, `mypy`, or `pre-commit`. |
| No runtime metrics | Medium | No Prometheus/OpenTelemetry, no request latency histograms. |
| No alerting on failures | Medium | Only manual checks and occasional opsbot messages. |

**Recommendations**

- Add pytest tests for auth, rate limit, and upload flow.
- Add `ruff` + `black` config and a GitHub Actions lint job.
- Expose a `/metrics` endpoint with basic counters (requests, latency).

---

## 9. Documentation

| Issue | Severity | Notes |
|---|---|---|
| `backend/README.md` is outdated | Medium | Still focuses on `/upload`, does not document `/api/v1/ask`, `/api/v1/upload-image`, login, `WHISPER_URL`, or the Whisper service. |
| No architecture diagram | Low | Hard to reason about data flow Pi → Cloudflare → LXC → Whisper service → Ollama. |
| No troubleshooting guide | Low | New user won't know how to check `journalctl`, PiSugar, or camera. |

**Recommendations**

- Rewrite README with current endpoints, env vars, and a simple architecture diagram.
- Add `TROUBLESHOOTING.md`.

---

## 10. Data / Database

| Issue | Severity | Notes |
|---|---|---|
| No migrations | High | `alembic` is in `requirements.txt` but unused. Schema changes require manual `ALTER TABLE`. |
| `audio_replies/` not tied to DB rows | Medium | Deleting a conversation does not delete its MP3. Storage grows forever. |
| No data retention policy | Medium | Conversations accumulate indefinitely. Add a retention job. |
| `todos` stored as JSON string | Low | Works, but a separate table or JSON column would be cleaner. |
| `image_path` stored as absolute temp path | Low | `/tmp/bee-uploads/...` is ephemeral. If you want to keep images, store them elsewhere. |

**Recommendations**

- Initialize Alembic and create the initial migration.
- Add a cleanup job that prunes old `audio_replies/` and temp uploads.
- Store images in a persistent directory if they should be reviewable in the dashboard.

---

## Immediate Action List (Do First)

1. **Fix `dashboard.html` JavaScript** — remove `const token = await ();` and clean up `api()`.
2. **Cache `live_dashboard.py` frames and fonts** to stop re-opening the GIF every frame.
3. **Fix Whisper fallback** so the backend does not crash when the LAN service is unreachable.
4. **Close all DB sessions safely** with `try/finally`.
5. **Add `WHISPER_API_KEY`** to the LAN Whisper service.
6. **Update `install-backend.sh`** to set admin username/password and use `After=` not `Requires=` for Ollama.
7. **Detect Python site-packages path** dynamically in `firmware/install.sh`.
8. **Rewrite `backend/README.md`** to match the current system.

---

## Nice-to-Have Improvements

- Local `piper-tts` to remove Microsoft network dependency.
- Downscale camera images before upload.
- Add a `speaking.gif` for the audio playback state.
- Auto-refresh dashboard conversations.
- `/metrics` endpoint and Grafana/Prometheus scrape.
- Nightly backup of `bee.db` + audio replies.
- Split `backend/main.py` into modules.
