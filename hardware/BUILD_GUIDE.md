# Hardware Build Guide: Ollama Bee Device v1.1

## Target Form Factor

A compact **lanyard/badge clip** wearable with a forward-facing camera and a small status screen. It can hang on a lanyard, clip to a pocket, or sit on a magnetic desk stand.

## What We Are Using

| Item | Part | Why |
|------|------|-----|
| Computer | Raspberry Pi Zero 2 W (preferred) or Pi Zero W | Captures audio + video, runs Wi-Fi, uploads to backend |
| Microphone | Adafruit SPH0645 MEMS I2S Mic Breakout | Small, low power, good near-field voice pickup |
| Camera | Raspberry Pi Camera Module 3 (wide angle) | High-quality stills for visual recognition |
| Screen | 1.3" I2C SH1106 OLED (128×64) | Status display: mute/recording/error/battery/Wi-Fi |
| Button | 6 × 6 mm tactile momentary switch | Record / mute / shutter toggle |
| LED | 3 mm green/red bicolor LED with common cathode | Quick glance status |
| Resistors | 220 Ω and 330 Ω | LED current limiting |
| Power board | Adafruit PowerBoost 1000C | LiPo charge + 5 V boost to Pi |
| Battery | 3.7 V 1200 mAh LiPo, 603450 or 803860 | ~4–6 hours heavy use |
| Charging | USB-C female breakout board | Recharge without opening case |
| Headers | 2 × 20 male 0.1" header for Pi | Optional; direct-solder for slimmer build |
| Wire | 28 AWG silicone stranded wire | Flexible, easy to route |
| Enclosure | 3D-printed PETG two-piece case | See `case/README.md` |
| Lanyard clip | PCB-mount badge clip or self-adhesive steel plate + magnet | For wearing or desk mounting |

> This is medium-soldering work: wire-to-header, wire-to-module pads, through-hole LED/button. No SMD chip soldering.

## Wiring Diagram

```
+------------------------------------------------------------+
|                     USB-C CHARGE INPUT                     |
|                        (female breakout)                    |
|                          +5V  GND                           |
|                             |  |                            |
|                  +----------+  +----------+                 |
|                  |                         |                |
|            +-----v-----+             +------v------+        |
|            | PowerBoost |             |  Pi Zero 2  |        |
|            |  1000C    |             |      W      |        |
|            |           |             |             |        |
|   LiPo +-->| BAT+  5V  |------------>| 5V  (Pin 2) |        |
|   LiPo - -->| BAT-  GND |------------>| GND (Pin 6) |        |
|            +-----------+             |             |        |
|                                      | 3V3 (Pin 1) |---> SPH0645 3V
|                                      | GPIO18(P12) |---> SPH0645 BCLK
|                                      | GPIO19(P35) |---> SPH0645 DIN
|                                      | GPIO21(P40) |---> SPH0645 LRCLK
|                                      | GND (Pin34) |---> SPH0645 GND
|                                      | GPIO17(P11) |---> BUTTON --> GND
|                                      | GPIO27(P13) |---> 220R --> LED1A
|                                      | GPIO22(P15) |---> 330R --> LED2A
|                                      | GND (Pin39) |---> LED common cathode
|                                      | GPIO2 (Pin3)|---> OLED SDA
|                                      | GPIO3 (Pin5)|---> OLED SCL
|                                      | 3V3 (Pin17) |---> OLED VCC
|                                      | GND (Pin9)  |---> OLED GND
|                                      | 15-pin CSI  |---> Camera ribbon |
+------------------------------------------------------------+
```

### Pi GPIO Pinout Reference

```
3.3V  (1)  (2)  5V
GPIO2 (3)  (4)  5V          ← I2C SDA for OLED
GPIO3 (5)  (6)  GND          ← I2C SCL for OLED
GPIO4 (7)  (8)  GPIO14
GND   (9)  (10) GPIO15
GPIO17(11) (12) GPIO18       ← BCLK to SPH0645
GPIO27(13) (14) GND
GPIO22(15) (16) GPIO23
3.3V  (17) (18) GPIO24
GPIO10(19) (20) GND
GPIO9 (21) (22) GPIO25
GPIO11(23) (24) GPIO8
GND   (25) (26) GPIO7
GPIO0 (27) (28) GPIO1
GPIO5 (29) (30) GND
GPIO6 (31) (32) GPIO12
GPIO13(33) (34) GND
GPIO19(35) (36) GPIO16       ← DIN from SPH0645
GPIO26(37) (38) GPIO20
GND   (39) (40) GPIO21       ← LRCLK to SPH0645
```

### SPH0645 Wiring

| SPH0645 Pin | Connect To |
|-------------|-----------|
| 3V          | Pi 3.3 V (Pin 1) |
| GND         | Pi GND (Pin 34 or 39) |
| BCLK        | Pi GPIO18 (Pin 12) |
| DIN         | Pi GPIO19 (Pin 35) |
| LRCLK       | Pi GPIO21 (Pin 40) |

### Camera Wiring

- Pi Zero CSI cable connects the 15-pin camera port on the Pi to the Camera Module 3.
- No extra power or data wiring needed; the ribbon carries MIPI CSI, 3.3 V, and I2C.
- Route the ribbon carefully — do not fold it more than 90° or crease it.
- The camera should face outward on the front of the case.

### OLED 1.3" SH1106 Wiring

| OLED Pin | Connect To |
|----------|-----------|
| VCC      | Pi 3.3 V (Pin 17) |
| GND      | Pi GND (Pin 9 or 14) |
| SCL      | Pi GPIO3 / I2C SCL (Pin 5) |
| SDA      | Pi GPIO2 / I2C SDA (Pin 3) |

Default I2C address is `0x3C`. Some modules are `0x3D`.

### Bicolor LED Wiring

Use a common-cathode LED so one GND pin controls both colors:

- **Red anode** → 330 Ω resistor → Pi GPIO22 (pin 15)  → charging / error / muted
- **Green anode** → 220 Ω resistor → Pi GPIO27 (pin 13) → recording / ready
- **Common cathode** → Pi GND (pin 39)

### Button Wiring

- One button pin → Pi GPIO17 (pin 11)
- Other button pin → Pi GND
- Firmware enables internal pull-up.

## Step-by-Step Assembly

### 1. Prepare the Pi

- Solder a 2×20 male header **OR** direct-solder wires to the Pi GPIO holes. For the slimmest case, direct-solder wires.
- Connect the Pi Zero CSI ribbon cable to the camera port. Note: Pi Zero uses a smaller 15-pin CSI connector; Camera Module 3 comes with the standard 22-pin cable, so you need a **15-to-22 pin CSI adapter cable** for Pi Zero.

### 2. Solder the SPH0645

- Cut five 60 mm lengths of 28 AWG wire.
- Strip, tin, and solder to the SPH0645 breakout pads.
- Route to Pi GPIO pins.

### 3. Add Button, LED, and OLED

- Solder button to GPIO17 and GND.
- Solder LED with resistors to GPIO27/GPIO22 and GND.
- Solder OLED to 3.3 V, GND, GPIO2 (SDA), GPIO3 (SCL).
- Test I2C detects the OLED: `sudo i2cdetect -y 1` should show `3c`.

### 4. Attach Camera

- Connect the 15-to-22 pin CSI adapter cable.
- Mount Camera Module 3 in the front of the case with the lens exposed.
- Protect the ribbon from sharp bends.

### 5. Power Circuit

- Solder PowerBoost 1000C:
  - `BAT+` / `BAT-` to LiPo red/black
  - `5V` / `GND` to Pi pin 2 (5V) and pin 6 (GND)
  - `USB` pads to USB-C breakout `+` and `-`

### 6. Final Assembly

- Mount Pi in the case bottom.
- Place PowerBoost and LiPo in their pockets.
- Position mic and camera to face the exterior.
- Mount OLED behind a clear window on the case top or lid.
- Press-fit or screw the lid on.

## Software Configuration on the Pi

### 1. Flash Raspberry Pi OS Lite (64-bit)

Use Raspberry Pi Imager. Enable SSH, camera, and I2C; set Wi-Fi credentials before first boot.

### 2. Enable Interfaces

Edit `/boot/firmware/config.txt`:

```ini
# Audio
dtparam=i2s=on
dtoverlay=adau7002-base

# Camera
dtoverlay=imx708
start_x=1
gpu_mem=128

# I2C
dtparam=i2c_arm=on
```

For Camera Module 3, `imx708` is the correct sensor overlay. Also enable legacy camera stack if you prefer `picamera2`:

```bash
sudo raspi-config
# Interface Options > Legacy Camera > No
# Interface Options > Camera > Yes
# Interface Options > I2C > Yes
```

Reboot.

### 3. Configure ALSA

Create `/etc/asound.conf`:

```text
pcm.!default {
    type hw
    card 0
}
ctl.!default {
    type hw
    card 0
}
```

### 4. Test Audio

```bash
arecord -D plughw:0 -c1 -r16000 -f S16_LE -d 5 /tmp/test.wav
aplay /tmp/test.wav
```

### 5. Test Camera

```bash
libcamera-jpeg -o /tmp/test.jpg --width 1640 --height 1232
```

You should get a JPEG. If not, check the cable orientation and `dtoverlay`.

### 6. Test OLED

```bash
python3 -m pip install luma.oled
python3 -c "from luma.core.interface.serial import i2c; from luma.oled.device import sh1106; from luma.core.render import canvas; d=sh1106(i2c(port=1, address=0x3c)); from PIL import ImageDraw; with canvas(d) as draw: draw.text((0,0),'Bee OK',fill='white')"
```

### 7. Install Firmware

Run the setup script:

```bash
scp -r ollama-bee-device/firmware pi@bee-device.local:/home/pi/bee-device
ssh pi@bee-device.local
bash /home/pi/bee-device/setup-pi.sh
sudo reboot
```

### 8. Start the Recorder

```bash
sudo systemctl enable --now bee-device
```

## Power Budget and Battery Life

| Component | Active Current | Notes |
|-----------|---------------|-------|
| Pi Zero 2 W | ~120–300 mA | Wi-Fi active, CPU streaming |
| SPH0645 | ~1 mA | Negligible |
| Camera Module 3 | ~150 mA active | Only on during capture |
| OLED SH1106 | ~20 mA | Always on if lit |
| LED | ~10 mA | Only on when recording |
| PowerBoost idle | ~10 mA | Quiescent current |

**Continuous recording + occasional camera:** ~250–350 mA average → 1200 mAh / 300 mA ≈ **4 hours**.

**Audio-only with screen on:** ~6 hours.

## Configuration Summary Table

| Setting | Value |
|---------|-------|
| Audio interface | `plughw:0` |
| Sample rate | 16000 Hz |
| Bit depth | 16-bit signed little-endian |
| Camera | Raspberry Pi Camera Module 3 (`/dev/video0` via libcamera) |
| Screen | SH1106 I2C OLED at address `0x3C` |
| Button GPIO | GPIO17 |
| Green LED GPIO | GPIO27 |
| Red LED GPIO | GPIO22 |
| Backend URL | `http://192.168.1.86:8000` |
| Device ID | `bee-pioneer-01` |

## Common Pitfalls

1. **Camera not detected**
   - Pi Zero requires a 15-to-22 pin CSI adapter cable.
   - Ensure the ribbon is oriented correctly (blue side faces different directions on each end).
   - Use `dtoverlay=imx708` for Camera Module 3.

2. **OLED not detected**
   - Run `sudo raspi-config` and enable I2C.
   - Try I2C address `0x3D` if `0x3C` fails.

3. **No audio from SPH0645**
   - Use `adau7002-base` overlay.
   - Check BCLK/DIN/LRCLK wiring.

4. **PowerBoost noise in audio**
   - Keep mic and PowerBoost physically separated.
   - Twist mic wires.

## Next Steps

1. Order or verify parts.
2. Print or verify the enclosure fits with camera window and OLED window.
3. Flash the Pi and confirm audio, camera, and OLED all work independently.
4. Pair with the backend and test an end-to-end spoken chunk + photo.

Want me to update the firmware and backend to actually use the camera and OLED now?
