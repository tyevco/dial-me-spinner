# dial-me-spinner rev A: fabrication and assembly

This document covers ordering the two PCBs from JLCPCB, the parts JLC cannot place, and the hand assembly of the
mechanics: magnets, bearing, rotor balancing, harness, antenna, battery, actuator and OLED. Electrical testing is
in [`bringup.md`](bringup.md). The two documents interleave: several assembly steps below are gated on a bring-up
step passing first.

* **Architecture of record:** `hardware/design/SPEC.md`. If this document disagrees with it, SPEC wins.
* **Coordinates** (SPEC §8): z is measured up from the desk in mm. θ = 0° points at the USB-C port, and angles
  increase counter-clockwise when viewed from the top.
* **[TVP]** means *to verify on prototype*: the number comes from a model, a datasheet typical or an unverified
  vendor claim, not from a measurement on this design.
* Board designators (U1, C7 and so on) are not final while the schematic sheets are in progress, so parts are
  referred to by function or MPN.

---

## 1. What gets built where

| Item | Made by | Notes |
|---|---|---|
| Main board PCB + PCBA (Ø64, 4-layer) | JLCPCB, Standard PCBA, **both sides** | MDBT50Q module via Global Sourcing or consignment (§4.1) |
| Base board PCB + PCBA (Ø40 + USB tab, 2-layer) | JLCPCB, Standard PCBA, top side | BQ25180 DSBGA, X-ray required (§3.2) |
| 12-way link harness through the spindle | Hand | §6 |
| 2.4 GHz flex antenna + coax | Hand (adhesive + u.FL mate) | §7.1 |
| 1S LiPo pack | Hand | Check polarity before plugging in (§7.2) |
| Detent actuator (micro linear stepper), carriage, Ø3×2 detent magnet | Hand | §7.3 |
| OLED panel into the bottom-contact ZIF | Hand, **after SWD programming** | §7.4 |
| 48-magnet track in the 316L ring | Hand, with a polarity jig | §8 |
| 608 bearing prep, rotor assembly, balancing | Hand | §9, §10 |
| Base cup, FA lower plate, spindle, light box, diffuser, top cover, OLED bracket, feet | Printed or machined parts + hand | §11 |

---

## 2. PCB fabrication at JLCPCB

### 2.1 Main board (`hardware/kicad/main`)

| Option | Setting | Why |
|---|---|---|
| Layers | 4 | SPEC §2 |
| Thickness | 1.6 mm | SPEC §2 and §8 stack-up (z 29.1–30.7) |
| Stack-up | JLC standard (e.g. JLC04161H-7628) | No controlled impedance needed. RF stays inside the module (u.FL on the module), and USB is Full-Speed through a short run |
| Impedance control | No | As above |
| Surface finish | **ENIG** (1 µ" is enough) | Flat pads for the 61-pad bottom-terminated MDBT50Q (0.4 mm pad gaps), the LGA-12 LIS2DW12, the WSON-8 DRV8837, the 0.5 mm ZIF and 48 LEDs with 0.7 mm pads. HASL is not acceptable |
| Outer / inner copper | 1 oz / 0.5 oz (JLC default) | 0.5 oz inner copper doubles the ring IR-drop estimate to about 12 mV per mm of path, which is still negligible ([leds verifier]). Order 1 oz inner only if VLED is routed on In1 as a thin trace |
| Vias | JLC standard 0.2 mm drill / 0.45 mm pad, **tented** | Module inner pads escape inward to tented vias under the module body ([mcu verifier]). If any via touches a pad, order "epoxy filled & capped" instead |
| Solder mask | **White** (matches the white light-box interior in SPEC §8) or black | White raises the cavity-floor reflectance and recovers band-edge brightness. Black gives crisper pixels. Both sides get the same colour. Check JLC's minimum mask dam for the chosen colour against the 0.5 mm-pitch ZIF and LGA pads |
| Silkscreen | Any, but **none inside the LED cavity r 27–30** | Silk and bare copper inside the cavity show as specular hotspots ([leds research]) |
| Board outline | Ø64 disc, centre Ø5, 3× M2 at r = 6.5, 2× M2 at r = 17 (θ 60°/120°) | SPEC §8 |
| Electrical test | Yes (JLC default for multilayer) | |

### 2.2 Base board (`hardware/kicad/base`)

| Option | Setting | Why |
|---|---|---|
| Layers | 2 | SPEC §2 |
| Thickness | 1.6 mm | Stiffness under the centre press switch: 1.6 mm deflects < 0.05 mm under 5 N, while 0.8 mm deflects about 0.26 mm ([mechanical research]) |
| Surface finish | **ENIG** (required) | JLC requires ENIG for 0.20–0.25 mm BGA pads. The BQ25180YBG is a 0.4 mm-pitch DSBGA-8 on 0.23 mm NSMD pads ([power verifier]; [BQ25180 datasheet](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) |
| Copper | 1 oz | Charger traces carry up to 1 A |
| Solder mask | Green is fine (hidden) | Mask opening on the DSBGA must be ≤ 0.05 mm larger than the 0.23 mm pad. At 0.4 mm pitch that leaves a dam of about 0.07 mm, which is probably below JLC's minimum, so JLC may merge the openings. Accept it, since no traces run between balls **[TVP: check the JLC DFM report]** |
| Board outline | Ø40 disc + tab to r = 35 at θ = 0° for the USB-C; 3× M2 at r = 15 | SPEC §6, §8. See the boss conflict in §11.2 |
| USB-C shell legs | Plated slots per the HRO TYPE-C-31-M-12 footprint | Shell legs carry the cable side loads |
| Bottom side | **No components** | It faces the LiPo across a gap of about 0.7 mm (§7.2) |

### 2.3 Panelization of round boards

Both outlines are round. Pick-and-place needs straight edges, so order with **"Panel by JLCPCB" plus edge
rails**, or accept JLC adding process edges. Break-off tabs (mouse bites) leave nubs on the rim:

* Main board: put tabs where the rim is free of parts. File the nubs flush, because the light box (r 27–30) and
  the top cover (r 32.5) sit very close to the r = 32 edge.
* Base board: keep tabs off the USB tab and away from the 3 M2 bosses.

### 2.4 Pre-order checks (do them in the Gerber viewer, not only in KiCad)

1. **Copper keep-out on the main board:** no pours on **B.Cu or In2.Cu at r ≥ 26**, which faces the magnet
   track (SPEC §8). Traces and pads are allowed. Eddy drag from a plane facing the track falls steeply with
   distance. For the Ø2×2 alternating track, the detent model gives ≈ 27 / 4.6 / 0.8 µN·m per full 1 oz plane at
   2 / 3 / 4 mm and 5 rev/s ([detent research]). Bearing friction is ≈ 150 µN·m.
2. **No ferromagnetic or inductor parts within 10 mm** of the TMAG5273 (bottom, r 29, θ 270°) or of the track
   annulus r 27–31 on the bottom (SPEC §7). This includes the TPS61040 inductor, any ferrite bead and shield cans.
3. **TPS22917 CT capacitor:** **[TVP, check before fab]** The power research (verified) says the TPS22917's CT
   capacitor goes **from CT to VIN, not to GND**. The TPS22918 uses CT to GND. The current `main_power` sheet ties
   C7 (1 nF) from LSW_CT to GND. Read the [TPS22917 datasheet](https://www.ti.com/lit/ds/symlink/tps22917.pdf)
   application section and fix the sheet if needed. If the slew is uncontrolled, the inrush into the
   2× 22 µF + 48× 100 nF on VLED is about 1 A ([power research]). Bring-up step B-9.8a measures it.
4. **TC2030-IDC-NL footprint** on the top side under the OLED glass: 6 pads plus 3 NPTH locating holes, with no
   parts inside the cable-head outline.
5. **LED rotations:** D1 sits at θ = 0° and the numbering runs CCW, 48 LEDs at 7.5° steps on r = 28.5. Each
   footprint is rotated, so check in the JLC placement preview that every pin-1 mark is rotated consistently
   (§3.4).
6. **WS2812-2020 footprint pin numbering:** build it from the mechanical drawing and pin table (1 DO, 2 GND,
   3 DI, 4 VDD). The V6 typical-application drawing numbers the pins differently ([leds research]).
7. **Test points** TP1 VSYS, TP2 +3V3, TP3 VLED and TP4 GND (main), plus VBUS, VBAT, VSYS and GND (base) must be
   exposed copper (no mask). Place them so they can be probed with the boards linked by the harness on the bench
   (B-6). Main-board TPs on the top side are only reachable before the OLED and cover go on.

---

## 3. PCBA at JLCPCB

### 3.1 Service level and sides

* **Main board: Standard PCBA, two sides.** Bottom: MDBT50Q, TMAG5273, J1 link connector, piezo. Top: LEDs, ZIF,
  boost, DRV5032, TC2030 pads. Plan for two reflow passes.
* **Base board: Standard PCBA, top side only.** This is the safer tier for a 0.4 mm DSBGA plus an X-ray request.
  Check JLC's current rules on which tier offers X-ray.
* Most ICs are JLC Extended parts. Each unique Extended part carries a per-order setup fee, so check the BOM
  quote and consider ordering 5 boards per order.

### 3.2 X-ray and inspection requests

| Part | Board | X-ray | Reason |
|---|---|---|---|
| BQ25180YBGR (DSBGA-8, 0.4 mm) | base | **Required, every board** | Hidden joints. Bridging or opens here mean no charging or no SYS |
| MDBT50Q-U1MV2 (61 bottom pads, 28 of them inner) | main | **Strongly recommended** | Inner pads cannot be inspected optically or reworked with an iron ([mcu verifier]) |
| LIS2DW12 (LGA-12), DRV8837 (WSON-8 + EP) | main | Optional | Electrical tests in `bringup.md` catch most faults |

Ask JLC to send the X-ray images. If they are not available, rely on the electrical checks in `bringup.md`: B-4
(BQ25180 power-up), B-9.4 (BQ25180 I2C) and B-7 (module SWD).

### 3.3 Order notes (copy into the JLC order remark; replace `<ref>` with final designators)

```
1. Base board <ref> BQ25180YBGR (DSBGA-8, 0.4 mm pitch): please X-ray every board and send the images.
2. Main board <ref> MDBT50Q-U1MV2 (bottom-terminated module, 61 pads): please X-ray and send the images.
3. Main board D1-D48 WS2812C-2020-V6 are MSL 5a (24 h floor life). Please bake per J-STD-033 /
   Worldsemi (70-75 C >= 24 h for reels) before placement, and complete both reflow passes of this
   two-sided board within the floor life.
4. D1-D48 are rotated in 7.5 deg steps around a ring. Please check each placement against the
   silkscreen pin-1 mark in the preview.
5. DNP (footprint only): <ref> DRV5012AEDMRR.
```

### 3.4 CPL and orientation spot-checks (in the JLC preview, before paying)

* LEDs D1–D48: pin-1 marks follow the ring; the DI/VDD pad column faces the previous LED.
* TMAG5273 (bottom, θ = 270°, r = 29): long axis radial (SPEC §5.5), so its X axis is tangential.
* MDBT50Q (bottom): the u.FL end faces the board centre (SPEC §8), so the coax runs straight into the spindle bore.
* AFC01-S30FCA-00 ZIF (top, toward θ = 270°): pin 1 matches the folded FPC (§7.4). Contacts are on the
  **bottom**.
* Polarised passives: VCOMH tantalum (C7189, + to the panel pin), B5819W cathode to +13V_OLED, BAV99 orientation.
* Vertical JST SH link connectors on both boards: pin 1 position (§6).

### 3.5 DNP

* DRV5012AEDMRR fallback wake latch (SPEC §5.5): footprint only.
* Test pads are `in_bom = False` and need no part.

---

## 4. Sourcing

### 4.1 MDBT50Q-U1MV2 (Global Sourcing or consignment)

JLC/LCSC C2688382 showed **0 stock on 2026-10-18** ([mcu research](https://jlcpcb.com/partdetail/C2688382)).
There are two routes:

1. **JLC Global Sourcing / pre-order:** order the module into your JLC parts library before placing the PCBA
   order. Allow for its lead time.
2. **Consignment:** buy from TME (about 146–172 pcs at about US$6.8–9.4,
   [TME](https://www.tme.eu/en/details/mdbt50q-u1mv2/iot-wifi-bluetooth-modules/raytac/)) or DigiKey/Mouser,
   and ship to JLC per their consignment procedure. Send 1–2 spares for attrition. Ship the modules in their
   sealed moisture-barrier bag; check the module's MSL in the
   [Raytac spec](https://cdn.sparkfun.com/assets/4/7/4/3/8/_nRF52840__MDBT50Q-1MV2___MDBT50Q-P1MV2_Ver.K_spec.pdf)
   **[TVP]**.

Do **not** substitute the -1MV2 (chip antenna) or -P1MV2 (PCB antenna). They share the footprint, but their
antenna would sit on the main-board bottom inside the metal ring, and the design relies on the off-board flex
antenna. Hand-placing the module is possible only with a stencil plus hot plate or hot air, because of the 28
inner pads. Verify it with X-ray or at least with B-7.

Record the nRF52840 silicon revision of the received modules (B-7.2). Rev 3 (build code F) has hardware
APPROTECT enabled by default, which changes the programming procedure.

### 4.2 Thin-stock or volatile JLC parts (snapshot 2026-10-18; re-check at order time)

| Part | LCSC | Stock seen | Fallback / note |
|---|---|---|---|
| WS2812C-2020-V6 (5 mA/ch) | C55109522 | ~47k, single source | WS2812B-2020-V6 C52917434 (~897k) is footprint-identical but **12 mA/ch**: 48 LEDs at full white draw 1.73 A instead of 0.72 A, so the firmware current cap is mandatory ([leds verifier]) |
| TMAG5273A2QDBVR | C3715882 | ~5.4k LCSC / 6.3k JLC; other variants nearly 0 | Buy reserve stock. The TMAG5173-Q1 is pin-compatible at VCC ≥ 2.3 V (OK at 3.3 V); order the A2/0x35 variant ([sensing verifier]) |
| BQ25180YBGR | C3682423 | ~4.1k | BQ25188YBGR C43043524 (62 pcs); check its register map before swapping |
| PKMCS0909E4000-R1 piezo | C910763 | 0 to 4k across snapshots | DigiKey/Mouser; hand-solder if JLC is out |
| 560 kΩ 0402 (OLED IREF) | C132339 | 0 at LCSC, ~9k at JLC | Any 560 kΩ 1 % 0402 |
| AFC01-S30FCA-00 ZIF | C262671 | ~37k | FH12-30S-0.5SH(55) C506793 (bottom contact) or HDGC 0.5K-HX-30PWB C2919501 (double-sided contacts, removes the orientation risk) |
| SM04B-SRSS-TB (motor) | C160404 | fluctuates | |
| TS-1187A-B-A-B (press switch) | C318884 | ~2.4k, fluctuates | KSC2-series parts are 3.5 mm tall and do **not** fit the stack ([mechanical verifier]) |
| SC-20S 32.768 kHz | C97603 | ~6.8k | SC-32S C97604 has a different footprint (3.2×1.5) and needs 9–10 pF caps. Not a drop-in |
| TPS22917DBVR | C2681320 | ~28.5k | TPS22918DBVR C131941 is pin-compatible, but see the CT note in §2.4 |

### 4.3 Parts not bought through JLC

| Item | Spec | Notes |
|---|---|---|
| OLED panel | NHD-1.5-128128G, or the proven pin-identical Orient AOC128128A0-1.50W | 0 stock at DigiKey/LCSC, 8–16 week lead times; Newhaven direct shows low stock. Buy ≥ 3 early. Other "SSD1351 30-pin" panels are unverified ([display verifier](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)) |
| Bearing | 608 (8×22×7), SKF 608-2Z (shields) or 608-2RSL. **No RSH/RS1 contact seals.** Buy 5+ | [608-2Z data](https://www.simplybearings.co.uk/products/608-2z-skf) |
| Bearing oil | ISO VG 2–10 (e.g. Mobil Velocite No.3 = VG 2, No.6 = VG 10) | Base oil type not stated by Mobil |
| Track magnets | 48 + ≥ 10 spare, NdFeB **Ø2.0×2.0 mm N52**, axially magnetised, NiCuNi, one batch | ±0.05 mm and ±5 % Br vary by vendor ([detent research]) |
| Detent magnet | 1 + spares, **Ø3×2 mm N52** axial | Near-equivalent: [K&J D21B-N52](https://www.kjmagnetics.com/d21b-n52-neodymium-disc-magnet) (1/8"×1/16") |
| Linear stepper | VIC-TECH VSM08102 (Ø8, M2×0.4, 0.02 mm/full step, ~10 mm stroke, 20 Ω/phase), or its 10 mm sibling for thrust margin | Listings conflict on stroke and the 10 mm part's thrust is unverified; get the drawing ([vendor page](https://www.micro-steppermotors.com/sale-28526335-vsm08102-8mm-4-pins-fpc-small-linear-stepper-motor-with-slider-m2-lead-screw.html)) |
| Antenna | Molex 146153, **order -0100 (100 mm coax)**; -0050 is in SPEC | The route is ≈ 55–70 mm (§7.1), so the 50 mm coax is likely too short. LCSC C916292 (-0050) had 118 pcs; -0100 is at DigiKey/Mouser ([Molex](https://www.molex.com/ja-jp/products/part-detail/1461530100)) |
| Battery | Protected 1S LiPo, 603450 class, ≤ 6.3 mm thick (SPEC), JST-PH 2.0 lead, UN38.3 report | A protected 603450 is about 34.5 × 54–55 mm (diagonal 64–65 mm). The cup inner diameter is 66.8 mm. Thinner (≤ 5.5–6.0 mm) is better for swelling margin (§7.2) |
| Harness | 12× JST SH pre-crimped leads (28–30 AWG) + 2× SHR-12V-S housings | §6 |
| Motor lead | SHR-04V-S housing; ideally a factory-crimped SH lead on the motor | Avoid hand-crimping SH contacts ([detent verifier]) |
| Fasteners | M2, **A4/316 stainless or brass**, nylon where possible | Test every screw with an N52 magnet. No carbon steel within 10 mm of the track |
| FA springs | 3× compression, 302/316 wire 0.35 mm, OD 4.0, free 6.0 mm, 5 active coils (k ≈ 0.53 N/mm) | Installed at about 3.56 mm for 3.9 N total; 3.4 mm gives 4.15 N ([mechanical verifier]). SPEC: ≈ 4 N |
| Bearing wave spring | Non-magnetic (316 or BeCu), ≥ 2.5–3 N axial preload (SPEC §8) | Keeps every ball loaded under the ±0.7 N alternating detent pull ([detent verifier]) |
| Feet | 3× rubber or micro-suction at r = 28 | High-μ gel feet make it tip instead of slide under a hard flick ([mechanical verifier]) |

---

## 5. Moisture sensitivity and baking

| Part | MSL | Handling |
|---|---|---|
| WS2812C-2020-V6 / WS2812B-2020-V6 | **5a** (24 h floor life) ([datasheet](https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf)) | Worldsemi bake: **70–75 °C ≥ 24 h for reels, 120 °C × 4 h for loose LEDs**. The 24 h window runs from the bake to the end of all heating, including repairs. JLC's per-order baking is **not confirmed** ([leds verifier]), hence order note 3 |
| MDBT50Q module, LIS2DW12, others | Per reel label | Keep reels and modules sealed until use |
| BQ25180 DSBGA | Per reel label | |

**Hand rework of an LED on an assembled main board.** The board has certainly exceeded the 24 h floor life, so:

1. Bake the whole board at **70–75 °C for ≥ 24 h** (no battery, no OLED panel, no motor). Check the storage
   ratings of the piezo and ZIF first; both are rated to +85 °C **[TVP]**.
2. Rework within 24 h. Use preheat and low airflow, keep the hot-air nozzle off neighbouring LEDs' silicone
   lenses, and follow the Worldsemi reflow profile.
3. Use a freshly baked replacement LED (120 °C × 4 h loose).

---

## 6. Link harness (12-way JST SH, through the spindle)

The pinout is identical on both boards and the harness is straight-through, 1→1 (SPEC §2, `nets.py LINK_PINOUT`).

* **Threading.** A 12-way SHR housing is about 14 mm wide and cannot pass the **Ø6 bore**. Use leads
  pre-crimped on both ends, for example JST "ASSHSSH28K" series double-ended leads **[TVP: confirm the part
  number and length]**. Pass the loose contacts through the bore a few at a time together with the antenna
  coax, then insert them into the housings. The bore cross-section (28 mm²) easily holds 12× 28 AWG
  (≈ 0.7 mm OD) plus the 1.13 mm coax.
* **Length.** Measure on the first mechanical mock-up, from base J3 (top side) up through the spindle and out
  of its upper side slot to main J1 (bottom side, next to the centre hole). Allow a **≥ 5 mm service loop**,
  because the FA moves 0.3–0.5 mm on every press while the base is fixed.
* **Pin 1 orientation.** Both J1 and J3 are vertical connectors facing each other. Mark pin 1 on both housings
  and check that pin 1 lands on pin 1 at both ends (VSYS on pins 1–2, GND on 3, 4 and 8).
* **Current.** JST SH contacts are rated 1 A each, so VSYS on two contacts carries ≤ 2 A and GND has three.
  A full-white LED ring (0.72 A with the C variant) plus the OLED (≤ 0.15 A) fits.
* **Test before first use:**

  | Check | Pass |
  |---|---|
  | Each pin to the same pin at the other end | < 0.5 Ω |
  | Each pin to its neighbours | > 10 MΩ (open) |
  | Pins 1–2 (VSYS) to 3/4/8 (GND) | open |

* **Strain relief:** Kapton at the spindle exits. Nothing in this path rotates.

---

## 7. Hand-assembly items

### 7.1 Antenna and coax (Molex 146153)

SPEC §8 places the 34.9 × 9 × 0.1 mm flex on the base-cup floor (z 1.0–2.0) along the chord x = −26 (θ ≈ 180°),
≥ 13 mm below the rotor and ≥ 4.5 mm from the battery side. The coax runs up through the spindle bore to the
module's u.FL.

**Geometry checks before printing the base cup** (also listed in §13):

* Centred on x = −26 and 9 mm wide, the strip's outer corners sit at r ≈ 35.1 mm. The cup's inner wall is at
  r = 33.4 (Ø70, 1.6 mm wall), so **the flex does not lie flat there**. Corners at r ≤ 33.0 need the centre at
  x ≈ −23.5 (inner edge x ≈ −19). That leaves only about 2 mm to a 34.5 mm-wide battery (|x| ≤ 17.25), less
  than the SPEC's 4.5 mm. Resolve this in CAD: move it, curve it slightly up the wall, or narrow the battery.
* z 1.0–2.0 lies inside the floor thickness (1.0–2.5), so the antenna needs a recess. If the recess opens
  downward, the antenna sits about 1 mm above the desk (the feet are 1.0 mm tall), and a metal desk will detune
  it badly. Test that case explicitly (bring-up B-11).
* **Route length.** From the floor at x ≈ −24, up past the battery edge to z ≈ 11–12, across the base board
  (r 20 → 4), up the bore (z ≈ 13 → 29), then out to the u.FL at r ≈ 8–10: about 55 mm plus bend radii
  (≥ 5 mm for 1.13 mm coax) plus a press-travel service loop. That is **≈ 60–70 mm**, so order **146153-0100**.
  Keep any excess as a gentle loop away from the antenna and the rotor gap; do not coil it next to the antenna.

**Fitting:**

1. Clean the floor recess with IPA. Apply the antenna's adhesive once, without bubbles, and do not stretch the
   flex. Keep metal paint, plating and conductive tape away from it.
2. Route the coax with ≥ 5 mm bend radius. Fix it with Kapton every 15–20 mm. It must never cross the rotor
   running gap.
3. **u.FL mating is rated for only about 30 cycles.** Mate it once at final assembly. RF tests (B-11) use the
   same connector, so plan them. Unmate with a u.FL extraction tool, never by pulling the cable.

### 7.2 Battery

1. **Polarity first.** SPEC §6: J2 pin 1 = BAT+, pin 2 = GND. Hobby JST-PH polarity is not standardised. Measure
   the pack lead with a DMM before every first insertion. The BQ25180 BAT pin has an absolute minimum of −0.3 V,
   so a reversed pack destroys the charger ([power research]).
2. Check the pack voltage (accept 3.5–4.2 V; do not use a pack below 3.0 V), the protection-PCB position and
   whether its length clears the cup wall.
3. **Swell gap.** The bay is z 2.5–9.0, a ≤ 6.3 mm pack tops out at z 8.8, and the base board's underside is at
   z 9.5. That leaves **0.7 mm**, below the 0.8–1.0 mm the mechanical verifier asked for to allow for swelling.
   Prefer a ≤ 5.5–6.0 mm pack and keep the base board's underside bare.
4. Fix the pack with thin double-sided foam tape, not hard adhesive, so it can swell and be replaced. Long axis
   along θ = 90°/270° (SPEC §8).
5. Keep the cell's nickel tab end away from the TMAG side (θ = 270°) if possible: nickel is slightly
   ferromagnetic ([power research]).

### 7.3 Detent actuator, carriage and detent magnet

The actuator hangs from the main-board underside in the bowl (r 12–27, z 19–29.1), chord placement near θ = 90°.
The carriage slides the magnet radially from r = 29.0 (click) to r = 21.5 (free) along θ = 90°, 1.0 mm above the
track (SPEC §1, §8).

1. **Motor coil check:** about 20 Ω per coil pair for the VSM08102 (measure your part), and the cross pairs
   open. Terminate the lead in an SHR-04V-S housing: pin 1 A+, 2 A−, 3 B+, 4 B− (SPEC §5.6).
2. **Detent magnet:** bond the Ø3×2 N52 into the non-magnetic carriage pocket (PA12/POM) with its axis normal
   to the track face. With an alternating track, either polarity gives 24 detents, and the polarity only shifts
   the rest phase by 7.5°, which calibration absorbs. Record which face is down. The DRV5032 home sensor is
   omnipolar.
3. **Clearances:** stepper can ≥ 10 mm from the track and from the parked magnet; steel lead-screw tip ≥ 5 mm
   from the detent magnet; nothing ferrous within 4 mm of any magnet face ([detent research]).
4. **Guide:** preload the carriage about 0.4–1 N against its reference faces on a PTFE/POM pair. Couple the
   slider pin-in-slot (travel axis only). Total actuator load must stay within the 8 mm motor's 0.78 N rated
   thrust ([detent verifier]). The M2×0.4 lead screw self-locks, so the carriage cannot be pushed by hand. Move
   it only by stepping (bring-up B-9.10).
5. **Park before assembly:** step the carriage to PARK (r = 21.5) before the main board is lowered over the
   rotor, so the detent magnet is not dragged across the track during assembly.
6. **Gap:** the nominal gap is 1.0 mm, with 0.8 mm minimum including bearing play and runout; it must never
   touch. Check the sub-assembly heights with calipers. The gap cannot be reached with a feeler once assembled.

### 7.4 OLED panel into the ZIF (last electronic step)

The TC2030 SWD pads are under the OLED glass (SPEC §8). **Fit the panel only after** bring-up B-7 (SWD),
B-8 (MCUboot + USB serial recovery proven) and B-9.9a (bare boost verified at 13 V and discharged).

1. **Mock up first.** Cut a 1:1 paper or Kapton copy of the FPC, fold it 180° behind the glass and check the
   insertion depth, contact side and pin 1. The free tail after the fold is only about 5 mm before the COF IC
   ([display verifier]).
2. **Discharge +13V_OLED.** Before inserting the FPC, touch a 1 kΩ resistor across the boost output cap. The
   rail decays only through the 551 kΩ FB divider: about 12 µF effective gives τ ≈ 6–7 s.
3. With power off, open the ZIF lid. The AFC01-S30FCA-00 is **bottom-contact**: after the fold, the FPC
   contacts face the PCB. Insert squarely up to the stiffener and close the lid.
4. **Bend rules:** radius ≥ 0.5 mm, ≥ 1 mm preferred. Bend only between the glass edge and the COF driver IC,
   never across the IC or the 4 mm stiffener, and do not press on the IC area.
5. **Mounting:** support the glass on its back perimeter only, outside the 28.86 mm viewing area, with 0.3–0.5 mm
   foam tape on the bracket. The **active-area centre (1.47 mm off the glass centre, away from the FPC edge) goes
   on the dial axis**, not the glass centre. Keep ≥ 0.3 mm air gap to the window. The window and top cover carry
   press loads; the glass must not ([display research](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)).
6. **Light separation:** the opaque light-box inner wall must seal to the PCB (≤ 0.1 mm or thin black foam) and
   to the cover. The diffuser ring and the OLED window are separate parts, otherwise LED light pipes into the
   window.

---

## 8. Magnet track installation (48 × Ø2×2 N52, polarity jig)

### 8.1 Target geometry (SPEC §1, §8; tolerances from the detent research)

| Parameter | Value |
|---|---|
| Count / pattern | 48, **alternating** N/S, giving 24 detents of 15° and 24 encoder periods per revolution |
| Pitch circle | R = 29.0 mm on the ring **top** face (z = 25.6) |
| Angular pitch / chord | 7.5° / 3.79 mm, leaving about 1.79 mm between magnet edges |
| Pocket | Ø2.05–2.10 mm × 2.05 mm deep (SPEC depth). Pick the diameter after measuring the magnet lot |
| Flushness | Faces flush ±0.03 mm to the top face; face runout ≤ 0.05 mm TIR. A 0.1 mm recess costs about 10 % detent torque |
| Bond | Structural epoxy. Each magnet sees about ±0.7 N per detent pass in click mode |
| Mass | 0.047 g each. **One missing magnet is a 1.37 g·mm imbalance**, about 40 % of the balance budget (§10) |

### 8.2 Incoming checks

* Measure 10 magnets per lot with a micrometer (Ø and length). Weigh 20 together and expect ≈ 0.94 g.
* Check field spread with an analog Hall probe at a fixed distance and reject outliers beyond ±5 %. Optionally
  sort the magnets into matched diametric pairs.
* **Ring magnetism check:** an N52 magnet must not cling to the 316L ring anywhere, especially on the knurled OD.
  Austenitic stainless can become slightly magnetic from machining or knurling. If you feel attraction, anneal
  the ring or reject it ([mechanical verifier]).

### 8.3 Polarity convention

* Mark a witness line on the ring at **pocket 0**.
* **Even pockets (0, 2, …, 46): N face up** (toward the main board). **Odd pockets: S face up.**
* Rev A has no index magnet. The witness mark is only for build records: balance log and suspect-pole notes.

### 8.4 Jig

Print (PETG/PA12) two **masks** that register on the ring's ID (Ø54) and top face, with a tab that aligns to the
witness mark:

* **Mask A** opens only the 24 even pockets; **Mask B** opens only the 24 odd pockets.
* Add a flat **clamp plate** (aluminium or glass; non-ferrous) with a PTFE release film, pressing all faces flush
  while the epoxy cures.
* Use a **magnet dispenser:** a brass or plastic tube (ID ≈ 2.1 mm) holding a stack of magnets. A stack is
  self-aligned, so mark the stack's exposed face polarity once with a pole identifier. Push the bottom magnet
  into the pocket and shear the stack sideways.
* Tools: brass, titanium or plastic tweezers and a plastic push pin. **No steel tools near the ring.**

### 8.5 Procedure

1. Degrease the pockets (IPA) and dry them. Keep the ring away from steel chips: magnets collect swarf.
2. Fit Mask A. Put a small amount of epoxy in each even pocket and insert **24 magnets N-up**. Same-polarity
   neighbours 7.6 mm apart only repel weakly, so they stay put.
3. **Before the epoxy gels**, check every placed magnet with a pole identifier or Hall probe: all must read N.
4. Clamp the faces flush with the plate and release film, then cure fully.
5. Fit Mask B and insert **24 magnets S-up**. These sit between opposite-polarity neighbours and are pulled
   sideways and up, so push each one fully down and hold it. Check the polarity of all 48 in sequence: it must
   read N, S, N, S … all the way round. Clamp and cure.
6. **A wrong magnet after cure is destructive to fix.** It has to be drilled or milled out, because heating
   the epoxy also demagnetises N52 (max operating about 60–80 °C). So check before every cure.
7. Measure flushness and runout (dial indicator, non-magnetic tip if possible). Optionally seal the track with a
   thin epoxy skim against NiCuNi corrosion, without changing flushness.
8. The firmware cross-checks later: 24 uniform electrical periods per revolution and per-pole amplitude within
   ±15 % (bring-up B-9.6c). A reversed magnet shows as a phase jump and a missing or shifted detent.

**Safety.** Swallowed NdFeB magnets (two or more) can cause intestinal perforation. Count them in and out, and
keep them away from children and pets. N52 discs chip if allowed to snap together, so wear eye protection.

---

## 9. Bearing preparation (608)

Bearing friction sets the spin time. Factory grease gives about 9–14 s spins from 10 rev/s instead of 40–120 s,
and contact seals (RSH/RS1) stop the rotor in under 1 s ([mechanical research and verifier](https://cdn.skfmediahub.skf.com/api/public/0901d1968065e9e7)).

1. Buy at least 5 bearings of the chosen type (608-2Z or 608-2RSL, CN clearance, ABEC-5/P5 or better).
2. **Degrease:** ultrasonic bath in IPA or naphtha, 3 × 5 min with fresh solvent, spinning by hand between baths.
   Remove the shields if they are designed to be removable. SKF 2Z shields are not, so flush with them in place
   and repeat until the bearing runs free and silent.
3. Dry with clean, dry air, but **do not spin the bearing up with an air jet**.
4. Oil with **1–2 drops of ISO VG 2–10** synthetic instrument oil. Do not over-oil: excess oil adds viscous drag.
5. Reject any bearing with shield rub, grit or a notchy feel. The final selection is by measured spin-down on the
   rotor (bring-up B-13). Keep the runner-up as a spare.
6. Re-oiling will be needed periodically: shields are meant for inner-ring rotation and this design spins the
   outer ring ([mechanical verifier]). Note the date in the build log.

---

## 10. Rotor assembly and balancing

### 10.1 Assembly

1. Check the ring: OD 70 / ID 54 / 10 mm, OD/ID concentricity ≤ 0.02 mm TIR, faces flat and square ≤ 0.02 mm
   (§8.2 magnet test too).
2. Bond the **PA12-GF carrier** (web z 17–19, r 11–27) concentric to the ring ID. **No aluminium or copper may
   rotate within 13 mm of the detent magnet's path.** An aluminium web would cost about 0.13–1.6 N·mm of eddy
   drag, against about 0.15 N·mm of bearing friction ([mechanical verifier]).
3. Install the magnets (§8) **before** final balancing.
4. Weigh the rotor (expect ≈ 135–140 g: ring 124 g, magnets 2.3 g, carrier, bearing outer race) **[TVP]**.
5. Press the 608 outer race into the carrier's Ø22 seat, pressing **on the outer race only**, never through the
   balls. If you use retaining compound, keep it out of the bearing.

### 10.2 Balance targets

| Item | Value |
|---|---|
| ISO G2.5 at 15 rev/s for ~137 g | U_perm ≈ **3.6 g·mm** (e = 26.5 µm) |
| Target | **≤ 2 g·mm** ([mechanical research]) |
| Ring eccentricity 0.02 mm TIR | ≈ 1.24 g·mm ([mechanical verifier]) |
| One missing magnet | 1.37 g·mm |
| Correction pit Ø2 × 1 mm in 316L at r = 31 (ring bottom face) | ≈ 25 mg ≈ **0.78 g·mm** each. Calibrate by weighing chips: the drill-point cone adds mass |
| M2 brass/316 set screw in a balance hole (if provided) | ≈ 2.2 g·mm |

### 10.3 Static balance (before the bearing goes in)

1. Mount the ring + carrier + magnets on a stepped arbor: a Ø22 h6 seat with Ø6–8 ground journals.
2. Roll it on two level, hardened knife edges (or a prop balancer's roller set). Do not balance on the 608
   itself: its breakaway friction (≈ 0.04–0.1 N·mm) masks imbalances below about 4–10 g·mm.
3. Let it settle 5 times from random start angles. The heavy spot comes to rest at the bottom.
4. Remove mass at the heavy spot with shallow Ø1.5–2 mm pits on the **ring bottom face at r ≈ 31**, which faces
   the base lip and is not visible. Alternatively, add brass or 316 at the light spot. **Never add steel or
   ferrous putty.**
5. Repeat until the rotor stays put at any angle. Knife-edge sensitivity is roughly 0.5–1 g·mm **[TVP]**.

### 10.4 Dynamic trim (after full assembly) **[TVP]**

Use the firmware balancing assistant: the LIS2DW12 runs in high-performance mode at 400–1600 Hz, and its x/y
signals are demodulated synchronously with the encoder angle ([sensing research]). Use a single-plane trial
weight:

1. Spin to 10–15 rev/s and record the 1×/rev vibration vector V0.
2. Stick a known trial mass at a known angle on the ring bottom face, e.g. 50 mg of non-magnetic putty at r = 31
   (1.55 g·mm). Record V1.
3. Correction = −V0 / (V1 − V0) × trial mass. Apply it at the computed angle and verify.

The FA rides on springs and the desk, so the IMU's response to imbalance is unknown until measured.

---

## 11. Mechanical assembly order

Each stage has a gate: do not continue until the referenced bring-up step passes.

### 11.1 Stage A: electronics on the bench (no mechanics)

| Step | Action | Gate (`bringup.md`) |
|---|---|---|
| A1 | Inspect both boards, check resistances | B-2, B-3 |
| A2 | Base alone on USB, then on a bench battery | B-4 |
| A3 | Main alone from bench VSYS | B-5 |
| A4 | Build and test the harness (§6). Link the boards; USB without battery | B-6 |
| A5 | SWD: recover, UICR, flash the bring-up image | B-7 |
| A6 | First firmware, USB CDC, **MCUboot + serial recovery verified** | B-8 |
| A7 | Peripheral smoke tests that need no mechanics: QSPI, I2C, IMU, BQ25180, piezo, LED ring, **bare boost at 13 V** | B-9.1–9.9a |

### 11.2 Stage B: base sub-assembly

1. Feet (3× at r = 28).
2. **Boss conflict check.** SPEC places the base-board M2 bosses at r = 15, θ = 60°/180°/300°, at
   (7.5, 13.0), (−15, 0) and (7.5, −13.0) mm. All three fall **inside the battery footprint**
   (|x| ≤ 17.25, |y| ≤ 27) of the 34.5 mm-wide pack in the bay directly below. Resolve this in CAD first: the
   bosses must clear the pack, or the pack must change.
3. Antenna into its recess and coax routed (§7.1).
4. Battery, after the polarity check (§7.2).
5. Base board onto the bosses with non-magnetic M2 screws. Align the USB-C mating face with the wall opening:
   flush to +0.3 mm proud at r = 35.0, opening = receptacle + 0.3 mm ([mechanical research]).
6. Plug the battery into J2. The board comes up in battery mode. Check VSYS at the base TP (B-9.5a).

### 11.3 Stage C: floating assembly (FA)

1. Clamp the spindle (Ø8 × 1.0 wall, 316 or Ti) into the PA12 lower plate. Fit the 3 guide pins and springs at
   r = 29, θ = 60°/180°/300°.
2. Fit the wave spring, then slide the rotor (with the prepared 608) onto the spindle.
3. **Thread the harness and coax** up through the spindle bore (§6, §7.1) before the main board closes the top.
4. Main board with the actuator, carriage and detent magnet **already at PARK** (§7.3), lowered onto the spindle
   flange. 3× M2 at r = 6.5 and 2× M2 actuator bracket screws at r = 17 (θ 60°/120°), all **non-magnetic**.
5. Plug the harness into J1 on the main board. Mate the antenna u.FL to the module (once).
6. Spin the rotor by hand: no rubbing, no ticking in FREE (detent parked). A ticking rotor in FREE means a ferrous
   part near the track, a magnet standing proud or rubbing.

### 11.4 Stage D: FA into the base

1. Connect the harness to base J3 **before** lowering the FA. Leave the service loop.
2. Lower the FA. The guide pins locate it and the springs preload it about 4 N upward against the stops
   (SPEC §8). **Open item:** SPEC §8 does not define the up-stops or how they are fitted after the FA is in.
   If the FA flange is wider than the stop, the stop must be a separate ring fastened after insertion
   ([mechanical verifier]).
3. Set and verify the press **pre-gap of 0.15 mm** (SPEC §8) between the centre boss and the TS-1187A plunger.
   Use a shim or sanding allowance on the boss.
4. **Click check:** press at the centre and at the rim at θ = 0°, 120° and 240°. Every press must click and
   pull BTN_N low (B-9.5d). Expected force is ≈ 4.1–4.3 N at the centre and ≈ 2.0–2.3 N at the rim for ~4 N
   preload and the 1.6 N switch ([mechanical research and verifier]). Measure with a gram gauge **[TVP]**. Rim
   presses that do not click mean the rim ledge is too shallow for the switch travel.

### 11.5 Stage E: mechanics-dependent tests (top still open)

TMAG field with the rotor (B-9.6), actuator and home sensor (B-9.10), detent calibration (B-12), spin-down
acceptance (B-13), dynamic balance trim (§10.4). Keep the top open so SWD stays reachable.

### 11.6 Stage F: close the top

1. OLED bracket and panel (§7.4). Test the display (B-9.9b).
2. Light box (white interior, opaque exterior, r 27–30), sealed to the PCB.
3. Diffuser ring (opal PMMA, r 27–30) and top cover (Ø30 OLED window, cover OD r = 32.5).
4. From here on, firmware updates go over MCUboot (USB CDC or BLE SMP). SWD needs the top and OLED removed.

### 11.7 Stage G: final acceptance

RF S11 in the real enclosure (B-11; the top cover is not in the antenna's near field), sleep currents per mode
(B-10), the full pass/fail table (B-14). Then ship mode or shutdown (B-9.5).

---

## 12. Material and fastener rules (summary)

* **Non-magnetic** within 10 mm of the track (r 27–31) or the TMAG5273: 316/A4 or brass screws, 316/BeCu
  springs, PA12/POM structure. **No carbon steel, 4xx/17-4 stainless or W-Ni-Fe weights** ([detent research]).
* **Non-conductive** (no aluminium or copper) on any rotating part within 13 mm of the detent magnet path
  (eddy drag).
* **No metal paint, plating or conductive tape** near the antenna; plastic only within 10 mm of it in-plane.
* **Every screw tested with an N52 magnet** before it goes in.

## 13. Open items and [TVP] list (assembly)

| # | Item |
|---|---|
| 1 | TPS22917 CT reference node (VIN vs GND) versus the current sheet (§2.4) |
| 2 | Base-board bosses at r = 15 overlap the battery footprint (§11.2) |
| 3 | Antenna does not lie flat at x = −26; the recess direction decides desk sensitivity (§7.1) |
| 4 | Coax length: order 146153-0100 (§7.1) |
| 5 | Battery-to-board swell gap 0.7 mm (§7.2) |
| 6 | FA up-stop design and insertion (§11.4) |
| 7 | JLC LED baking and X-ray image availability (§3) |
| 8 | Harness lead part numbers and lengths (§6) |
| 9 | Knife-edge balance sensitivity; IMU dynamic trim response (§10) |
| 10 | Folded-FPC fit under the glass (§7.4 mock-up) |

Source abbreviations used above: "[x research]" and "[x verifier]" refer to the subsystem research and its
independent verification, which SPEC.md was built from. Where the two differ, the verifier's corrected value is
used. Datasheet links are inline where a number depends on them.
