# Prompt: Generate STL Enclosure for Ollama Bee Wearable AI Device

## Output required

A **single, watertight, manifold STL file** ready for 3D printing in PETG. Preferably two STL files: one for the **main body** and one for the **press-fit lid**. All dimensions in **millimetres**.

---

## Device overview

Build a compact, wearable enclosure for a self-hosted AI voice recorder. The device clips to a pocket, belt, or shirt and records audio that is sent to a local backend for transcription and LLM processing.

The enclosure must be a **two-piece shell**: a main body that holds the electronics, and a lid that snaps or screws on top. The lid must expose the screen, button, LED, and microphone.

---

## Hardware stack (bottom to top)

| Layer | Component | Dimensions (mm) | Notes |
|---|---|---|---|
| 1 (bottom) | PiSugar 3 battery HAT | 65 × 30 × 15 | Battery and charging HAT. USB-C charging port on one short edge. |
| 2 | Raspberry Pi Zero 2 W | 65 × 30 × 5 | Sits on top of PiSugar 3 via 40-pin GPIO header. |
| 3 (top) | PiSugar Whisplay HAT | 65 × 30 × 10 | Sits on top of Pi Zero via 40-pin GPIO pass-through. Contains LCD, button, RGB LED, microphone. |
| Front | Raspberry Pi Camera Module 3 Wide | 25 × 24 × 8 | Mounted on the front face, lens facing outward. |

**Total stacked height:** approximately 35–40 mm.
**Recommended internal footprint:** 72 × 38 mm to give 1–2 mm clearance around the stack.

---

## External dimensions

- **Main body:** 72 mm × 38 mm × 42 mm
- **Wall thickness:** 2 mm minimum
- **Lid:** 72 mm × 38 mm × 3 mm
- **Corner radius:** 3 mm external, keep internal edges sharp or slightly rounded for part fit

---

## Part layout inside the body

1. **Bottom layer:** PiSugar 3 battery HAT sits on the floor of the main body.
2. **Middle layer:** Raspberry Pi Zero 2 W mounts on top of PiSugar 3 via the 40-pin female header.
3. **Top layer:** Whisplay HAT mounts on top of the Pi Zero via the 40-pin male header.
4. **Front face:** Camera Module 3 Wide sits in a dedicated pocket, ribbon cable runs internally to the Pi Zero CSI port.
5. **Left short edge:** USB-C charging port of PiSugar 3 must align with a slot in the wall.

---

## Mounting details

### Pi Zero 2 W mounting
- The Pi Zero has **four M2.5 mounting holes** in a rectangle.
- Hole centres: **58 mm × 23 mm** (standard Raspberry Pi Zero hole spacing).
- Hole diameter: **2.7 mm** for self-tapping or 2.5 mm for machine screws.
- Add four **5 mm diameter × 8 mm tall cylindrical standoffs** from the floor of the main body.
- The Pi Zero PCB sits on these standoffs and is secured with M2.5 × 5 mm screws or is press-fit.

### PiSugar 3 retention
- The PiSugar 3 is thicker than the Pi Zero and connects via the GPIO header.
- Add small **internal ribs or lips** on the short walls to hold the PiSugar 3 from sliding sideways.
- Do not fully enclose the PiSugar 3 underneath — leave a small gap for the battery and charging circuitry.

### Whisplay HAT retention
- The Whisplay HAT sits on top of the Pi Zero stack.
- The lid should press gently against the edges of the Whisplay HAT to stop vertical movement.
- Add **corner posts** on the lid that contact the HAT corners without blocking the LCD/button/mic.

### Camera pocket
- A front-facing rectangular pocket: **28 mm × 27 mm × 9 mm deep**.
- Lens window: **6 mm diameter hole** centred on the camera lens position.
- Leave a **3 mm wide slot** below the pocket for the CSI ribbon cable to pass back into the main body.

---

## Openings on each face

### Lid (top face)
- **LCD window:** 28 mm × 16 mm rectangular cut-out, centred on the Whisplay HAT display area.
- **Button hole:** 6 mm diameter hole for the tactile button on the Whisplay HAT.
- **LED light pipe:** 3 mm diameter hole positioned over the RGB LED. Optional: add a small 4 mm tall translucent PETG cylinder as a built-in diffuser.
- **Microphone port:** cluster of **five 1.5 mm diameter holes** on the side of the lid closest to the microphone. The holes should face outward when worn.

### Front face (camera side)
- **Camera lens window:** 6 mm diameter hole.
- **Camera pocket:** as described above.

### Left short edge
- **USB-C charging slot:** 10 mm wide × 4 mm tall rectangular slot, positioned to match the PiSugar 3 USB-C port centreline.
- The slot should allow a USB-C cable plug to enter and fully seat.

### Right short edge
- Leave solid or add a small **ventilation slot** 20 mm × 2 mm for heat dissipation.

### Rear face
- **Integrated belt/pocket clip** (see below). No other openings.

---

## Wearable clip specification

- **Type:** integrated rear clip, printed as one piece with the main body.
- **Position:** centred on the rear face, near the top edge so the device hangs upright.
- **Dimensions:**
  - Total clip length: 30 mm
  - Clip height: 12 mm
  - Clip thickness: 2 mm
  - Gap between clip and body: 3 mm (for belt, pocket hem, or shirt)
- **Shape:** J-shape or hook shape with a small inward bump at the tip to grip fabric.
- **Reinforcement:** add a 4 mm thick triangular fillet where the clip meets the body.
- The clip opening should face downward when the device is worn upright.

---

## Assembly features

### Lid attachment
- **Preferred method:** press-fit.
- Add four **2 mm diameter × 3 mm tall snap pins** on the inside corners of the lid.
- Add matching **2.2 mm diameter × 4 mm deep holes** in the main body corners.
- **Alternative:** include four M2.5 threaded brass insert holes in the body walls and matching clearance holes in the lid.

### Internal cable routing
- Add a **2 mm wide × 4 mm deep channel** from the camera pocket to the Pi Zero CSI port area.
- Keep the channel away from the PiSugar battery contacts.

### Battery access
- Do not permanently trap the battery. If possible, add a **removable bottom panel** or leave enough clearance that the PiSugar 3 can slide in from the bottom before the lid closes.

---

## Print settings

- **Material:** PETG or ABS
- **Layer height:** 0.2 mm
- **Walls:** 3
- **Top/bottom layers:** 4
- **Infill:** 20% gyroid
- **Supports:** yes, for the clip overhang and any internal standoffs
- **Orientation:** print the main body with the open face upward; print the lid with the smooth top face upward

---

## Design priorities

1. The Pi Zero stack must drop into the body and be held securely by standoffs and ribs.
2. The lid must expose the screen, button, LED, and microphone without blocking them.
3. The USB-C slot must align with the PiSugar 3 port.
4. The camera pocket must face forward and hold the module square.
5. The clip must be strong enough for daily wear; use generous fillets.
6. All walls must be 2 mm thick minimum for durability.
7. The final STL must be manifold and printable without supports inside the hollow cavity.

---

## Reference coordinate system

- Origin at the bottom-left-front corner of the main body when the device is worn.
- X-axis: left–right (short edge, USB-C side is left)
- Y-axis: front–back (camera faces +Y)
- Z-axis: bottom–top (battery at Z=0, lid at top)

---

## Deliverables

1. `bee-pioneer-body.stl` — main enclosure body
2. `bee-pioneer-lid.stl` — press-fit lid
3. A short note confirming the dimensions and the STL units are in millimetres.

If only one STL can be generated, combine body and lid in the same file but clearly separate them so they can be split in the slicer.
