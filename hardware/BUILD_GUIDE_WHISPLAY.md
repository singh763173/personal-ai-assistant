# Hardware Build Guide: Ollama Bee Device v2.2

## Target Form Factor

A compact **lanyard/badge clip** wearable with a forward-facing camera and a color status screen. Uses the PiSugar hardware stack as an integrated sandwich.

## What We Are Using

| Item | Part | Why |
|------|------|-----|
| Computer | Raspberry Pi Zero 2 W | Captures audio + video, runs Wi-Fi, uploads to backend |
| Audio/Display/Input HAT | PiSugar Whisplay HAT | Dual mics, WM8960 audio, 1.69" ST7789 LCD, RGB LED, button |
| Battery HAT | PiSugar 3 1200 mAh | Battery, charging, power management, UPS features |
| Camera | Raspberry Pi Camera Module 3 (wide angle) | High-quality stills for visual recognition |
| Cable | Raspberry Pi Zero camera adapter | 22-pin to 15-pin for Pi Zero CSI port |
| Enclosure | 3D-printed PETG two-piece case | See `case/README.md` |
| Lanyard clip | PCB-mount badge clip or self-adhesive steel plate + magnet | For wearing or desk mounting |

## Physical Stack

```text
Top:  Whisplay HAT
      ├─ 1.69" color LCD
      ├─ dual WM8960 microphones
      ├─ RGB LED
      └─ button

Mid:  Raspberry Pi Zero 2 W
      ├─ Wi-Fi / Bluetooth
      ├─ 15-pin CSI port (camera)
      └─ 40-pin GPIO header

Bot:  PiSugar 3 Battery HAT
      ├─ 1200 mAh LiPo
      ├─ USB-C charging input
      └─ power button
```

## Wiring

There is almost no wiring:
- Whisplay HAT plugs onto the Pi Zero 2 W 40-pin header.
- PiSugar 3 attaches to the bottom of the Pi Zero 2 W via pogo pins / GPIO header.
- Camera connects with a single CSI ribbon cable.

**No loose power wires. No separate charger board.**

## Step-by-Step Assembly

### 1. Prepare the Pi

- Solder a 2×20 **female** GPIO header on the Pi Zero 2 W if you want the HAT to plug on top.
- The PiSugar 3 attaches to the bottom; check whether your PiSugar 3 variant uses pogo pins or requires a male header on the bottom of the Pi.
- Connect the 15-to-22 pin CSI adapter cable between Pi Zero CSI port and Camera Module 3.

### 2. Attach PiSugar 3

- Mount the PiSugar 3 battery HAT to the bottom of the Pi Zero 2 W.
- Ensure the pogo pins / header make contact with Pi 5 V / GND pins.
- Do not power on yet.

### 3. Attach Whisplay HAT

- Carefully align the Whisplay HAT with the Pi GPIO header.
- Press down gently but firmly.
- The HAT screen is glass — handle by the PCB edges, not the screen.

### 4. Mount Camera

- Route the CSI ribbon around the stack.
- Position Camera Module 3 facing outward through a case window.
- Avoid sharp bends in the ribbon.

### 5. Final Assembly

- Slide the sandwich into the case.
- Ensure the Whisplay button, screen, mic port, and camera lens are exposed.
- Add lanyard clip or magnet plate.
- Close the case.

## Software Configuration on the Pi

### 1. Flash Raspberry Pi OS Lite (64-bit)

Use Raspberry Pi Imager. Enable SSH and set Wi-Fi credentials before first boot.

### 2. Install Whisplay HAT Drivers

```bash
sudo apt update
sudo apt install -y git i2c-tools libcamera-dev python3-pip python3-venv ffmpeg

git clone --depth 1 https://github.com/PiSugar/Whisplay.git /tmp/Whisplay
cd /tmp/Whisplay
sudo bash install_driver.sh
```

### 3. Install PiSugar Power Manager

```bash
# PiSugar provides a power-manager package; install from their docs/repo
# Example for PiSugar 3:
curl -sSL https://cdn.pisugar.com/release/Pisugar-power-manager.sh | sudo bash
```

After install:

```bash
sudo systemctl enable --now pisugar-server
```

Battery level is then readable via the `pisugar-server` API on localhost.

### 4. Camera Overlay

Edit `/boot/firmware/config.txt`:

```ini
dtoverlay=imx708
start_x=1
gpu_mem=128
```

Reboot.

### 5. Test Audio

```bash
arecord -l
arecord -D hw:whisplay-soundcard -c2 -r16000 -f S16_LE -d 5 /tmp/test.wav
aplay /tmp/test.wav
```

### 6. Test Display

```bash
cd /tmp/Whisplay/example
pip install -r requirements.txt --break-system-packages
sudo python3 test.py
```

### 7. Test Camera

```bash
libcamera-jpeg -o /tmp/test.jpg --width 1640 --height 1232
```

### 8. Test PiSugar Battery Level

```bash
curl -s http://localhost:8423/api/power | python3 -m json.tool
```

Or use the PiSugar CLI:

```bash
pisugar-power-manager --status
```

### 9. Install Project Firmware

```bash
scp -r ollama-bee-device/firmware pi@bee-device.local:/home/pi/bee-device
ssh pi@bee-device.local
bash /home/pi/bee-device/setup-pi.sh
sudo reboot
```

### 10. Start the Recorder

```bash
sudo systemctl enable --now bee-device
```

## Configuration Summary Table

| Setting | Value |
|---------|-------|
| Audio card | `whisplay-soundcard` (verify with `arecord -l`) |
| Sample rate | 16000 Hz |
| Channels | 2 (stereo mics) |
| Display | 1.69" ST7789 SPI, 240×280 |
| Camera | Raspberry Pi Camera Module 3 |
| Button | Whisplay onboard button |
| RGB LED | Whisplay onboard LED |
| Battery | PiSugar 3 via `pisugar-server` |
| Backend URL | `http://192.168.1.86:8000` |
| Device ID | `bee-pioneer-01` |

## Power-On / Power-Off Procedure

### Power on

1. Short press the PiSugar power button
2. Hold / long press until the LED stays on
3. Pi boots; firmware starts automatically

### Power off

- **Software:** long-press the Whisplay button → firmware calls `sudo shutdown -h now`
- **Hardware:** hold the PiSugar power button for the required duration (usually ~5–10 s)

## Power Budget and Battery Life

| Component | Typical current |
|-----------|---------------|
| Pi Zero 2 W | ~120–250 mA |
| Whisplay HAT | ~80–120 mA |
| Camera Module 3 active | ~150 mA |

**Heavy use:** ~350–450 mA average.

With PiSugar 3 1200 mAh: **2.5–3.5 hours**.

With PiSugar 3 Plus 5000 mAh (if it fits): **10+ hours**.

## Button Mappings

| Gesture | Action |
|---------|--------|
| Single click | Toggle mute / recording |
| Double click | Capture and upload a photo immediately |
| Long press (~2 s) | Safe shutdown |

## Common Pitfalls

1. **PiSugar 3 power-on issues**
   - Test the bare Pi + PiSugar 3 first before adding the Whisplay HAT.
   - Request a replacement if power-on is unreliable.

2. **Whisplay HAT driver not loading**
   - Run PiSugar's `install_driver.sh` and reboot.
   - Check `dmesg | grep -i whisplay` for errors.

3. **Camera not detected**
   - Ensure the 15-to-22 pin adapter is oriented correctly.
   - Verify `dtoverlay=imx708` is in `/boot/firmware/config.txt`.

4. **Audio card name wrong**
   - Run `arecord -l` and update `BEE_AUDIO_CARD` in the service file.

5. **Battery level not showing**
   - Confirm `pisugar-server` is running and reachable on `localhost:8423`.

## Next Steps

1. Print or verify the enclosure fits the 3-layer sandwich and camera.
2. Flash the Pi and confirm audio, display, camera, button, and battery all work.
3. Pair with the backend and test an end-to-end spoken chunk + photo.

Want me to generate the 3D-printable case or update the firmware to read PiSugar battery level next?
