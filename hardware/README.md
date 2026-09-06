# Hardware BOM and Wiring

## Bill of Materials

| Item | Suggested Part | Est. Cost | Purpose |
|------|----------------|-----------|---------|
| Single-board computer | Raspberry Pi Zero 2 W | £15 | Host firmware, Wi-Fi streamer |
| Microphone | Adafruit SPH0645 MEMS I2S Mic Breakout | £8 | Audio capture |
| Audio ADC alternative | ReSpeaker 2-Mics Pi HAT | £10 | Plug-and-play mic array if you prefer HAT over soldering |
| Main button | Tactile 6x6x5mm momentary switch | £1 | Record / mute toggle |
| Status LED | 3mm or 5mm LED (red/green/bicolor) | £1 | Recording / idle / error state |
| Resistor | 220 Ω 1/4W | £0.05 | LED current limit |
| Battery | 3.7V 1200 mAh LiPo (803860 or similar) | £10 | Portable power |
| Charger / booster | Adafruit PowerBoost 1000C | £15 | Charge LiPo + 5V boost to Pi |
| USB-C power-only port | USB-C breakout | £2 | Charging input |
| Case | 3D-printed (see `case/`) | filament | Wearable clip enclosure |
| Misc | pin headers, 28 AWG wire, heat-shrink | £5 | Wiring |

**Approximate total: £55–70**

## Wiring Diagram

### Pi Zero 2 W GPIO

```text
       [Pi Zero 2 W]
    3.3V (Pin 1)  ----->  SPH0645 3V
    GPIO 18 (Pin 12) --->  SPH0645 BCLK
    GPIO 19 (Pin 35) --->  SPH0645 DIN
    GPIO 21 (Pin 40) --->  SPH0645 LRCLK
    GND (Pin 34)   ----->  SPH0645 GND

    GPIO 17 (Pin 11) --->  Button (other side to GND)
    GPIO 27 (Pin 13) --->  220 Ω resistor ---> LED Anode
    GND (Pin 39)     --->  LED Cathode

    PowerBoost 5V  --->  Pi 5V (Pin 2)
    PowerBoost GND --->  Pi GND (Pin 6)
    LiPo +/-       --->  PowerBoost JST input
    USB-C +5V      --->  PowerBoost USB in
    USB-C GND      --->  PowerBoost GND
```

> Note: Pin 35/40 are on the full 40-pin header. On a Pi Zero the header is unpopulated; solder a 2x20 male/female header or direct-solder wires.

## Audio: I2S Microphone Configuration

SPH0645 requires an I2S driver. On Raspberry Pi OS, add to `/boot/firmware/config.txt`:

```ini
dtparam=i2s=on
dtoverlay=adau7002-base
```

The `adau7002` overlay provides a simple I2S mono input driver compatible with the SPH0645.

Then create `/etc/asound.conf`:

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

Test capture:

```bash
arecord -D plughw:0 -c1 -r16000 -f S16_LE -d 5 test.wav
aplay test.wav
```

## Button and LED

- Button between GPIO17 and GND, internal pull-up enabled in firmware.
- LED anode -> 220 Ω resistor -> GPIO27; cathode -> GND.
- Optional: use a bicolor LED or WS2812B (single-wire) for richer status.

## Power Notes

- The Pi Zero 2 W draws ~100 mA idle, ~300 mA under load. A 1200 mAh LiPo gives ~4–6 hours of continuous streaming.
- For "7-day battery life" like Bee you need aggressive duty cycling: sleep between captures, wake on button or VAD (voice activity detection). That requires extra hardware ( microcontroller + PDM mic ) and is not in v1.
- PowerBoost 1000C enables USB-C charging while running.

## Alternative Simpler Path

If you want to skip custom audio hardware, use a **ReSpeaker 2-Mics Pi HAT**. It plugs directly onto the Pi Zero, gives you 2 mics + button + ring LEDs, and works with `arecord` out of the box. The firmware is the same; only the LED/button pin numbers change.
