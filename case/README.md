# 3D-Printed Enclosure

## Design Requirements

- Clip onto a belt, pocket, or shirt hem
- Hold Raspberry Pi Zero 2 W, microphone, button, LED, and battery
- Expose USB-C for charging
- Ventilation for microphone and LED visibility
- Two-piece design: main body + lid

## Suggested Dimensions

- Main body: ~80 mm × 45 mm × 20 mm
- Lid: press-fit or 2× M2 screw mounting
- Clip: 25 mm long, 5 mm thick, internal width ~3 mm for fabric
- Microphone port: 3 mm hole facing outward
- LED window: small transparent PETG diffuser or leave hole

## Recommended Print Settings

- Material: PETG or ABS (more durable than PLA for wearable)
- Layer height: 0.2 mm
- Walls: 3
- Infill: 20% gyroid
- Supports: yes for clip overhang

## Files

- `case/bee-pioneer-body.stl` — main enclosure (TODO: generate or model)
- `case/bee-pioneer-lid.stl` — lid (TODO: generate or model)
- `case/bee-pioneer-clip.stl` — belt/pocket clip (optional separate part)

## Build Notes

- Leave internal standoffs for Pi Zero mounting holes.
- Route wires through channels to keep microphone away from battery/PowerBoost switching noise.
- Add a small diffuser over the LED hole, or use a transparent resin drop.
- The microphone should face away from the body to reduce clothing rustle.

## Quick Simplification

If you don't want to design from scratch, you can remix an existing Raspberry Pi Zero case from Printables/Thingiverse and add a microphone hole, button cutout, and clip.
