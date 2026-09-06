# Hardware Compatibility and BOM Check — PiSugar 3 Stack

## Final Bill of Materials

| # | Part | Specific Suggestion | Est. Cost | UK Supplier | Notes |
|---|------|---------------------|-----------|-------------|-------|
| 1 | Raspberry Pi Zero 2 W | Raspberry Pi Zero 2 W | £14.40 | The Pi Hut / Pimoroni | You already own one ✅ |
| 2 | PiSugar Whisplay HAT | PiSugar `Whisplay HAT` | ~£36 | PiSugar.com / Amazon UK / resellers | Audio + 1.69" LCD + button + RGB LED |
| 3 | PiSugar 3 Battery HAT | PiSugar 3 1200 mAh | ~£40 | PiSugar.com / Amazon UK / resellers | Power + battery + charging |
| 4 | Raspberry Pi Camera Module 3 | Raspberry Pi SC1224 (wide-angle 120°) | ~£24 | The Pi Hut / Pimoroni | Standard version also includes Pi Zero cable |
| 5 | CSI adapter cable | Raspberry Pi Zero Camera Adapter | £1.70 | The Pi Hut | 22-pin to 15-pin, 15 cm |
| 6 | Enclosure | 3D-printed PETG | ~£3 | Your 3D printer | Design in `case/README.md` |
| 7 | Lanyard clip | PCB badge clip or self-adhesive steel plate + magnet | ~£3 | Amazon / hardware store | For wearing or desk mounting |
| **Total new parts** | | | **~£108** | | |

### Where to buy in the UK

| Part | Supplier | Price | Link / Search |
|------|----------|-------|---------------|
| Pi Zero 2 W | The Pi Hut | £14.40 | thepihut.com/products/raspberry-pi-zero-2-w |
| Camera Module 3 | The Pi Hut | £24 | thepihut.com/products/raspberry-pi-camera-module-3 |
| Pi Zero camera cable | The Pi Hut | £1.70 | thepihut.com/products/raspberry-pi-zero-camera-adapter |
| Whisplay HAT | PiSugar direct | ~£36 | pisugar.com/products/whisplay-hat-for-pi-zero-2w-audio-display |
| PiSugar 3 1200 mAh | PiSugar direct | ~£40 | pisugar.com/products/pisugar-3-raspberry-pi-zero-battery |

PiSugar products may also appear on Amazon UK under "PiSugar 3" or "Whisplay HAT". Check delivery times and import duties if ordering from the US store.

## Physical Stack

```text
Top:  Whisplay HAT        (audio, display, button, RGB LED)
Mid:  Raspberry Pi Zero 2 W  (compute, Wi-Fi, CSI camera)
Bot:  PiSugar 3 Battery HAT  (battery, charging, power management)
```

This is a single integrated sandwich. No loose wires except the camera ribbon.

## Compatibility Matrix

| Layer | Component | Interface | Driver / Library | Status | Notes |
|-------|-----------|-----------|------------------|--------|-------|
| SBC | Raspberry Pi Zero 2 W | 40-pin GPIO + CSI + USB | Raspberry Pi OS Lite 64-bit | ✅ Compatible | You already own it |
| Audio/Display/Button | PiSugar Whisplay HAT | GPIO (I2C + SPI + I2S) | PiSugar `Whisplay` driver | ✅ Compatible | Official driver supports Pi Zero 2 W |
| Battery / Power | PiSugar 3 1200 mAh | 5 V via pogo pins / GPIO | PiSugar power-manager | ⚠️ Compatible with risk | Reported PMIC/power-on issues with Pi Zero 2 W + other HATs (GitHub issue #192). PiSugar offers replacements. Test early. |
| Camera | Raspberry Pi Camera Module 3 | CSI | `libcamera` + `picamera2` | ✅ Compatible | Needs 15-to-22 pin CSI adapter for Pi Zero |
| Case | Custom PETG enclosure | N/A | N/A | ✅ Design pending | Must fit 3-layer stack + camera |

## Pin Usage Check

The Whisplay HAT occupies the full 40-pin header. The PiSugar 3 connects to the same header via pogo pins (no actual pin usage, just power delivery). No free GPIO remains for extra sensors.

The camera uses the dedicated CSI port — no GPIO conflict.

## Software Stack Compatibility

| Layer | Technology | Version / Source | Status |
|-------|-----------|------------------|--------|
| OS | Raspberry Pi OS Lite (64-bit) | Bookworm | ✅ Officially supported by PiSugar driver |
| Audio driver | PiSugar unified Whisplay sound card driver | GitHub `PiSugar/Whisplay` | ✅ Installs via `install_driver.sh` |
| Battery monitor | PiSugar power-manager / `pisugar-server` | PiSugar | ✅ Required to read battery level via I2C |
| Audio capture | `arecord` / ALSA | System package | ✅ Works with WM8960 |
| Camera driver | `libcamera` + `picamera2` | Raspberry Pi foundation | ✅ Standard on Pi OS |
| Display | `whisplay.py` runtime | PiSugar driver | ✅ Provides LCD, LED, button classes |
| Backend | FastAPI + faster-whisper + Ollama | Project code | ✅ Tested syntactically |
| Speech-to-text | faster-whisper | `tiny`/`base`/`small` | ✅ Runs on CPU |
| LLM inference | Ollama | Local endpoint | ✅ Your local Ollama confirmed running |

## Power Budget

| Component | Typical current |
|-----------|---------------|
| Pi Zero 2 W idle + Wi-Fi | ~120 mA |
| Pi Zero 2 W active | ~250 mA |
| Whisplay HAT (LCD + codec + LED) | ~80–120 mA |
| Camera Module 3 active | ~150 mA |

**Continuous recording + occasional camera + screen on:** ~350–450 mA average.

With PiSugar 3 1200 mAh: **2.5–3.5 hours** of heavy use.

If PiSugar 3 Plus (5000 mAh) fits physically: **10+ hours**.

## Power-On Procedure

PiSugar 3 typically requires:
1. Short press the power button
2. Then hold/long press until the LED stays on

Our firmware long-press gesture (shutdown) must not conflict with this hardware power-on sequence. We will map software functions only after the device has booted.

## PiSugar 3 Risk Note

GitHub issue #192 reports PiSugar 3 + Pi Zero 2 W + another HAT causing:
- Power-on button not responding reliably
- Burned PMIC traces in some units

Mitigation:
- Order from a retailer with easy returns / warranty
- Test the bare PiSugar 3 + Pi Zero 2 W first
- Then add the Whisplay HAT
- If you see power-on issues, request a replacement immediately

PiSugar's official response was to offer free replacements, implying a manufacturing/quality issue rather than a design incompatibility.

## Confidence Level

| Area | Confidence | Reason |
|------|------------|--------|
| Electrical compatibility | **Medium-High** | PiSugar docs confirm Whisplay HAT works with Pi Zero 2 W; camera uses CSI; PiSugar 3 power delivery is standard but has reported edge-case failures |
| Driver availability | **High** | Official installers exist |
| Firmware correctness | **Medium-High** | Syntactically valid, uses documented APIs, not yet run on real hardware |
| Physical fit | **Medium** | 3-layer stack is taller; case design is pending |
| Battery life | **Medium** | Based on datasheets; real-world ±25% |

## Known Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| PiSugar 3 PMIC/power-on issues | Buy from a supplier with easy returns; test bare stack first |
| Whisplay driver button API differs from assumptions | Run PiSugar `example/test.py` first; adjust callback names if needed |
| Camera ribbon blocked by stacked HATs | Use long (300 mm) flexible cable or route around the side |
| LCD orientation/colors wrong | Adjust ST7789 init in driver or firmware |
| Audio card name not `whisplay-soundcard` | Run `arecord -l` after install and set `BEE_AUDIO_CARD` |
| Taller stack needs larger case | Design case around 3-board sandwich + camera |

## Recommended Build Order

1. Assemble bare stack: Pi Zero 2 W + PiSugar 3 + Whisplay HAT.
2. Flash OS, install Whisplay driver, and test HAT screen/LED/button/audio.
3. Verify PiSugar 3 power-on/off works reliably.
4. Add camera and test `libcamera-jpeg`.
5. Install project firmware and test backend upload.
6. Design and print case.

## Checklist Before Ordering

- [ ] Confirm Pi Zero 2 W available (you have one)
- [ ] Order Whisplay HAT + PiSugar 3 from PiSugar or Amazon UK
- [ ] Order Camera Module 3 from The Pi Hut / Pimoroni
- [ ] Order Pi Zero camera adapter cable from The Pi Hut / Pimoroni
- [ ] Verify 3D printer has PETG filament
- [ ] Confirm backend host reachable on same Wi-Fi

## Next Steps

1. Update firmware to read PiSugar battery level via `pisugar-server` and show it on the LCD.
2. Model the 3D-printable case for the 3-layer stack.
3. Update backend to accept camera images and run visual recognition via Ollama.

Want me to do one of those now?
