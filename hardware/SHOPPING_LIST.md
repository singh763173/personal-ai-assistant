# Shopping List — Ollama Bee Device v2.2

## Where to buy everything

You will need to order from **two suppliers**: PiSugar/Amazon UK for the HAT and battery, and The Pi Hut/Pimoroni/Amazon UK for the Pi, camera, and cable.

### Option A: Cheapest and fastest UK shipping — mostly Amazon UK

| # | Part | Suggested product | Price | Link | Notes |
|---|------|-------------------|-------|------|-------|
| 1 | Raspberry Pi Zero 2 W | Raspberry Pi Zero 2 W | ~£15 | https://www.amazon.co.uk/Raspberry-Pi-Zero-2-W/dp/B09KLVX4RT | You already own one; only buy if you want a spare |
| 2 | PiSugar Whisplay HAT | Whisplay HAT for Raspberry Pi Zero W/2W | ~£36 | https://www.amazon.co.uk/Whisplay-HAT-Raspberry-Zero-Expansion/dp/B0FPG8S6K6 | Audio + display + button + RGB LED |
| 3 | PiSugar 3 1200 mAh | PiSugar 3 Portable 1200 mAh UPS Lithium Battery | ~£35–£40 | https://www.amazon.co.uk/Portable-Pwnagotchi-Raspberry-Accessories-handhold/dp/B09QS12N1W | Battery + charging + power management |
| 4 | Raspberry Pi Camera Module 3 Wide | Raspberry Pi Camera Module 3 Wide | ~£40 | https://www.amazon.co.uk/Raspberry-Pi-Camera-Module-Wide/dp/B0BRY757NX | 120° wide-angle, best for wearable |
| 5 | Pi Zero camera adapter | 2PCS 30CM Camera Cable 15-pin to 22-pin | ~£5 | https://www.amazon.co.uk/pi-zero-camera-adapter/s?k=pi+zero+camera+adapter | Search results — pick a 15-pin to 22-pin cable |
| 6 | Magnetic badge clip | OFFCUP Magnetic Badge Holders 10 pack | ~£8 | Search Amazon UK for "OFFCUP Magnetic Badge Holders" | For attaching device to clothing |
| 7 | Lanyard clip | Generic metal lanyard clip / badge clip | ~£3 | Search Amazon UK or eBay for "metal lanyard clip with ring" | Alternative to magnet |

### Option B: Best balance — The Pi Hut for Pi/camera/cable + PiSugar direct for HAT/battery

| # | Part | Suggested product | Price | Link | Notes |
|---|------|-------------------|-------|------|-------|
| 1 | Raspberry Pi Zero 2 W | Raspberry Pi Zero 2 W | £14.40 | https://thepihut.com/products/raspberry-pi-zero-2-w | You already own one |
| 2 | PiSugar Whisplay HAT | Whisplay HAT | $35.99 (~£29 + shipping/import) | https://www.pisugar.com/products/whisplay-hat-for-pi-zero-2w-audio-display | Order direct from PiSugar |
| 3 | PiSugar 3 1200 mAh | PiSugar 3 1200mAh Raspberry Pi Zero Battery | ~£40 + shipping | https://www.pisugar.com/products/pisugar-3-raspberry-pi-zero-battery | Order direct from PiSugar |
| 4 | Raspberry Pi Camera Module 3 Wide | Raspberry Pi Camera Module 3 | From £24 | https://thepihut.com/products/raspberry-pi-camera-module-3 | Select **Wide** variant on the page |
| 5 | Pi Zero camera adapter | Raspberry Pi Zero Camera Adapter | £1.70 | https://thepihut.com/products/raspberry-pi-zero-camera-adapter | Official Raspberry Pi adapter cable |
| 6 | Magnetic badge clip | Search Amazon/eBay for "magnetic name badge holders neodymium" | ~£5–£10 | https://www.amazon.co.uk/s?k=magnetic+name+badge+holder | Buy a small pack |
| 7 | Lanyard clip | Search Amazon/eBay for "metal lanyard clip" | ~£3 | https://www.amazon.co.uk/s?k=metal+lanyard+clip | Optional alternative |

## Recommended purchase combination

**Best UK option:**

- The Pi Hut: Pi Zero 2 W (if spare needed) + Camera Module 3 Wide + Pi Zero Camera Adapter
- Amazon UK: Whisplay HAT + PiSugar 3 + magnetic badge clips

This gives you fast UK delivery on the Raspberry Pi official parts and reasonable Prime/next-day delivery on the PiSugar/Amazon items.

## What you do NOT need to buy

- MicroSD card: you likely have one; any 32 GB+ Class 10 card works.
- USB-C cable: included with PiSugar 3 for charging.
- Extra wires: the HAT stack eliminates nearly all wiring.
- Case: you will 3D print it.

## Total estimated cost

| Supplier | Items | Subtotal |
|----------|-------|----------|
| The Pi Hut | Camera Module 3 Wide + adapter | ~£26 |
| Amazon UK / PiSugar | Whisplay HAT + PiSugar 3 + clips | ~£80 |
| **Total** | | **~£106** |

Add ~£3 for PETG filament if you don't have any.

## Order checklist

- [ ] Whisplay HAT
- [ ] PiSugar 3 1200 mAh battery HAT
- [ ] Raspberry Pi Camera Module 3 (Wide recommended)
- [ ] Pi Zero camera adapter cable (15-pin to 22-pin)
- [ ] Magnetic badge clips or lanyard clip
- [ ] MicroSD card (if needed)

## Important note on PiSugar 3

There are reported power-on/PMIC issues with PiSugar 3 + Pi Zero 2 W + stacked HATs (PiSugar GitHub issue #192). Order from a source with easy returns (Amazon UK Prime is ideal) and test the bare PiSugar 3 + Pi Zero 2 W before adding the Whisplay HAT. If it has power-on problems, return it for a replacement.
