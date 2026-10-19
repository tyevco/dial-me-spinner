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
* **Mechanical model:** `hardware/mechanical/dial_spinner.scad`, described in [`docs/mechanical.md`](mechanical.md).
  Where SPEC §8 is not buildable as written, the model deviates from it and marks the constant `DEV:`. The model
  takes the board parts from the generated PCBs (`extract_board_parts.py`), so its clash check tests the boards
  as placed. SPEC §8 has since been revised: the base board is a Ø46 disc on one M2 boss at r = 20, θ = 270°, a
  printed rib and the USB-C shell; the pack lies along θ = 0°/180°; the antenna shelf is centred on y = +23.5;
  both link connectors are side-entry; and the FA lower plate is a 3-spoke spider. This document follows SPEC and
  the generated boards for those items (§2.2, §6, §7.1, §7.2, §11.2), and the model for the parts SPEC does not
  define: guide pins and stop screws, springs, press pad, spindle stack and its M4 clamp, rotor seat and ESD
  strap, feet (§4.3, §10, §11). `docs/mechanical.md` §12 is the reference build order; re-check against it
  before printing or machining parts.
* Designators are the ones in the schematic sheet modules (`hardware/design/sheets/*.py`) and on the generated
  boards. The BOM, CPL and `ORDER-NOTES.md` that `release.py` writes come from the same netlists and boards (§2),
  so treat those files, not this text, as the order record.

---

## 1. What gets built where

| Item | Made by | Notes |
|---|---|---|
| Main board PCB + PCBA (Ø64, 4-layer, ENIG) | JLCPCB, Standard PCBA, **both sides** | MDBT50Q module via Global Sourcing or consignment (§4.1) |
| Base board PCB + PCBA (Ø46 + USB tab, 4-layer, ENIG) | JLCPCB, Standard PCBA, top side only | BQ25180 DSBGA, X-ray required (§3.2) |
| 12-way link harness through the spindle (plus a separate bench harness) | Hand | §6 |
| 2.4 GHz flex antenna + coax | Hand (adhesive + u.FL mate) | §7.1 |
| 1S LiPo pack, re-terminated with SH leads for J2, + battery breakout lead | Hand | Check polarity before plugging in (§7.2) |
| Detent actuator (micro linear stepper), carriage, Ø3×2 detent magnet | Hand | §7.3 |
| OLED panel into the bottom-contact ZIF | Hand, **after SWD programming and the recovery gate (B-8.7)** | §7.4 |
| NFC coil (13.56 MHz flex in the top cover) | Hand: solder its tail to the J11 pads | §11.7 |
| 48-magnet track in the 316L ring | Hand, with a polarity jig | §8 |
| 608 bearing prep, rotor assembly, balancing | Hand | §9, §10 |
| Base cup, FA lower plate, spindle, light box, diffuser, top cover, OLED bracket, feet | Printed or machined parts + hand | §11 |

---

## 2. PCB fabrication at JLCPCB

**Order files.** `python3 hardware/design/release.py` writes everything JLC needs into `hardware/fab/<board>/`:
`gerbers.zip` (Gerbers plus Excellon drill files, plated and non-plated holes separate),
`dial-me-spinner-<board>-BOM-JLCPCB.csv`, `dial-me-spinner-<board>-CPL-JLCPCB.csv` and `ORDER-NOTES.md` (DNP list,
bottom-side placements, board-only parts). For review it adds the schematic PDF, board PDFs per side and per copper
layer, and top and bottom 3D renders. It first runs `kicad-cli` DRC with schematic parity and stops before writing
any fab output if either reports an error (the report is `drc-parity.rpt`; `--force` writes a review-only package).
DNP parts are left out of the BOM and the CPL. The CPL angles and origins carry per-LCSC-part corrections fitted to
JLC's EasyEDA footprints (`hardware/tools/jlc_cpl.py`, cached in `hardware/design/jlc_offsets.json`; top θ + α,
bottom 180° − θ + α), so the JLC preview should already show every part the right way round. Check it anyway
(§3.4).

### 2.1 Main board (`hardware/kicad/main`)

| Option | Setting | Why |
|---|---|---|
| Layers | 4 | SPEC §2 |
| Thickness | 1.6 mm | SPEC §2 and §8 stack-up (z 29.1–30.7) |
| Stack-up | JLC standard (e.g. JLC04161H-7628) | No controlled impedance needed. RF stays inside the module (u.FL on the module), and USB is Full-Speed through a short run |
| Impedance control | No | As above |
| Surface finish | **ENIG** (1 µ" is enough) | Flat pads for the 61-pad bottom-terminated MDBT50Q (0.4 mm pad gaps), the LGA-12 LIS2DW12, the WSON-8 DRV8837, the 0.5 mm ZIF and 48 LEDs with 0.7 mm pads. HASL is not acceptable |
| Outer / inner copper | 1 oz / 0.5 oz (JLC default) | 0.5 oz inner copper doubles the ring IR-drop estimate to about 12 mV per mm of path, which is still negligible ([leds verifier]). In1 is a solid GND plane (`layout.py`). Order 1 oz inner only if VLED ends up routed on In2 as a thin trace |
| Vias | 0.25 mm drill / 0.45 mm pad, 0.5 mm pad on the power and GND net classes (`layout.py`), **tented** | Module inner pads escape inward to tented vias under the module body ([mcu verifier]). If any via touches a pad, order "epoxy filled & capped" instead |
| Solder mask | **White** (matches the white light-box interior in SPEC §8) or black | White raises the cavity-floor reflectance and recovers band-edge brightness. Black gives crisper pixels. Both sides get the same colour. Check JLC's minimum mask dam for the chosen colour against the 0.5 mm-pitch ZIF and LGA pads |
| Silkscreen | Any, but **none inside the LED cavity r 27–30** | Silk and bare copper inside the cavity show as specular hotspots ([leds research]). As generated, the stock LED footprints' own silk marks (D101–D148) lie in this band: remove them or accept the hotspots (§13 #22). R42 has moved to r 24.1, out of the band |
| Board outline | Ø64 disc, centre Ø5; 3× **plated GND** M2 (H1–H3) at r = 6.5, θ 90°/210°/330°; 2× NPTH M2 (H4/H5) at r = 17, θ 60°/120° | SPEC §8. The spindle's M4 spigot passes the Ø5 hole. The brass hub's face on the plated H1–H3 pads is the GND end of the ring's ESD bleed (§10.1, §11.4), and the OLED-bracket screws go through H1–H3 into the hub. H4 holds the stepper saddle; the model leaves H5 unused |
| Fiducials | FID1–FID3 on the top, FID4–FID6 on the bottom (1 mm copper, 2 mm mask opening) | Three per assembled side (`layout.py`) |
| Electrical test | Yes (JLC default for multilayer) | |

### 2.2 Base board (`hardware/kicad/base`)

| Option | Setting | Why |
|---|---|---|
| Layers | 4 (In1 = GND plane, In2 = signals/power) | SPEC §2. Single-sided assembly all the same |
| Thickness | 1.6 mm | Stiffness under the centre press switch: 1.6 mm deflects < 0.05 mm under 5 N, while 0.8 mm deflects about 0.26 mm ([mechanical research]) |
| Stack-up | JLC standard 4-layer (e.g. JLC04161H-7628) | No controlled impedance needed: USB is Full-Speed over a short run |
| Surface finish | **ENIG** (required) | JLC requires ENIG for 0.20–0.25 mm BGA pads. The BQ25180YBG is a 0.4 mm-pitch DSBGA-8 on 0.23 mm NSMD pads ([power verifier]; [BQ25180 datasheet](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) |
| Outer / inner copper | 1 oz / 0.5 oz (JLC default) | Charger traces carry up to 1 A on the outer layers; the BQ25180's GND ball D2 stitches into both pours and the In1 plane (SPEC §8) |
| Solder mask | Green is fine (hidden) | Mask opening on the DSBGA must be ≤ 0.05 mm larger than the 0.23 mm pad. The footprint (`base.py`) opens it 0.025 mm per side, giving 0.28 mm openings and a dam of about 0.12 mm at 0.4 mm pitch. If that is below JLC's minimum for the chosen colour, JLC may merge the openings. Accept it, since no traces run between balls **[TVP: check the JLC DFM report]** |
| Board outline | Ø46 disc plus a 13 mm-wide tab to r = 34.6 at θ = 0° for the USB-C; one NPTH M2 hole (H1, Ø2.2) at r = 20, θ = 270° | SPEC §8; `layout.py`. H1 sits outside the pack. A printed rib under the θ = 90° edge and the USB-C shell, captured in the cup wall, are the other two supports (§11.2) |
| USB-C shell legs | Plated slots per the HRO TYPE-C-31-M-12 footprint | Shell legs carry the cable side loads |
| Bottom side | **No components** (single-sided board) | It faces the LiPo across 1.0 mm (§7.2). The NTC RT1 is on the top at r 8, θ 200° (SPEC §8) |
| Antenna keep-out | No plane or pour on B.Cu, In1 or In2 for y > 15.4 (B.Cu/In2 tracks and vias may come to y ≈ 17.5), and no F.Cu pour for y > 17 | SPEC §8, `layout.py` `ANTENNA_KEEPOUT_*`: keeps base-board copper ≥ 5 mm from the antenna under the θ = 90° edge (§7.1) |
| Fiducials | FID1–FID3 on the top | `layout.py` |
| Electrical test | Yes (JLC default for multilayer) | |

### 2.3 Panelization of round boards

Both outlines are round. Pick-and-place needs straight edges, so order with **"Panel by JLCPCB" plus edge
rails**, or accept JLC adding process edges. Break-off tabs (mouse bites) leave nubs on the rim:

* Main board: put tabs where the rim is free of parts. File the nubs flush, because the light box (r 27–30) and
  the top cover (r 32.5) sit very close to the r = 32 edge.
* Base board: keep tabs off the USB tab, away from the M2 hole at r = 20, θ = 270°, and off the θ = 90° edge
  that rests on the cup's rib.

### 2.4 Pre-order checks (do them in the Gerber viewer, not only in KiCad)

1. **Copper keep-out on the main board:** no pours on **B.Cu or In2.Cu at r ≥ 26**, which faces the magnet
   track (SPEC §8). Traces and pads are allowed. Eddy drag from a plane facing the track falls steeply with
   distance. For the Ø2×2 alternating track, the detent model gives ≈ 27 / 4.6 / 0.8 µN·m per full 1 oz plane at
   2 / 3 / 4 mm and 5 rev/s ([detent research]). Bearing friction is ≈ 150 µN·m.
2. **No ferromagnetic or inductor parts within 10 mm** of the TMAG5273 (U30, bottom, Hall element at r 29,
   θ 270°) or of the track annulus r 27–31 on the bottom (SPEC §5.3, §7). This includes the TPS61040 inductor
   L20, any ferrite bead and shield cans. As placed at the time of writing, L20 (top) is ≈ 21 mm from U30, but
   its courtyard reaches r ≈ 19.9, which is ≈ 7 mm in plane (and ≈ 5 mm higher) from the annulus edge at
   r = 27. Confirm that this meets the rule or move L20 (§13 #23).
3. **TPS22917 CT capacitor: done.** The TPS22917 pin table reads "CT: Switch slew rate control. Connect
   capacitor from this pin to VIN" ([TPS22917 SLVSDW8B](https://www.ti.com/lit/ds/symlink/tps22917.pdf), Pin
   Functions; confirmed by the power verifier). `main_power.py` now ties **C7 (1 nF/50 V) from LSW_CT to VSYS**
   (VSYS is the switch's VIN), with QOD through **R4 = 68 Ω** (RC0402FR-0768RL, C163455) to VLED and R3 = 100 kΩ
   as the ON pull-down. The OLED boost-input switch U21 (`display.py`) has C37 = 1 nF from CT to VSYS and its
   **QOD tied directly to VOUT = OLED_VIN**, so OLED_VIN is held at ≈ 0 V when off and the TPS61040 (EN = VIN)
   stays off in sleep (SPEC §5.3; hardware/sim, SLP-1, LSW-1). With CT to VIN, SLVSDW8B gives at VIN = 3.6 V:
   tR = 1.6 µs/pF (≈ 1.6 ms) and tON = 3.8 µs/pF (≈ 3.8 ms, the "≈ 4 ms" turn-on of SPEC §5.1), with RON = 90 mΩ
   typ / 110 mΩ max at 25 °C (80 mΩ is the 5 V figure). If the slew were uncontrolled, the inrush into the
   2× 22 µF + 48× 100 nF on VLED would be about 1 A ([power research]). The QOD discharge takes VLED to 10 % in
   ≈ 24 ms nominal, 26.6 ms worst case, inside firmware's 30 ms wait (SPEC §5.1; hardware/sim, LSW-2). Bring-up
   step B-9.8a measures both. Only the TPS22918 alternate takes CT to GND, so if you substitute it for U2 or U21,
   its CT capacitor goes back to GND.
4. **TC2030-IDC-NL footprint** J10 on the top side under the OLED glass (r 12, θ 150°): 6 pads plus 3 NPTH
   locating holes, with no parts inside the cable-head outline.
5. **LED rotations:** D101 (SPEC "LED1", pixel 0 in `leds.py`) sits at θ = 0° and the numbering runs CCW to
   D148: 48 LEDs at 7.5° steps on r = 28.5. Each footprint is rotated, so check in the JLC placement preview that
   every pin-1 mark is rotated consistently (§3.4). Note that D1 on the *base* board is the SMF5.0A TVS.
6. **WS2812-2020 footprint pin numbering: checked.** `leds.py` uses the stock
   `LED_WS2812B-2020_PLCC4_2.0x2.0mm` footprint, verified against the pin table (1 DO, 2 GND, 3 DI, 4 VDD). Do
   not renumber it from the V6 typical-application drawing, which the leds research found to number the pins
   differently.
7. **Test points** TP1 VSYS, TP2 +3V3, TP3 VLED and TP4 GND (main), plus TP1–TP4 VBUS, VBAT, VSYS and GND (base)
   must be exposed copper (no mask). Place them so they can be probed with the boards linked by the harness on the
   bench (B-6). On the main board, TP2–TP4 are on the top and are reachable only before the OLED and cover go on.
   **Main TP1 (VSYS) is on the bottom**, so it is covered once the board is seated (Stage D).
   **Base-board TPs and J2 are unreachable once Stage C has fitted the FA lower plate and the rotor**, which is
   why §7.2 adds a battery breakout.
8. **Module u.FL clearance to the rotor: done.** The mated u.FL plug stands about 2.5 mm proud of the module and
   points down, toward the rotor. The earlier placement (r 14.5, u.FL toward the centre) put the module's inner
   end 1.5 mm into the brass hub (`docs/mechanical.md` §3B item B1). SPEC §8 and the board now centre U10 at
   r 17.3, θ 215° on the bottom, inner end at r ≥ 8.8, with its **u.FL end facing outward** (u.FL at r ≈ 23,
   over the bowl), and the model's clash check passes on the current boards. The coax runs back under the board
   beside the module to the spindle's θ = 270° slot and threads between U12 and the module's inner corner:
   0.13 mm to U12 and 0.44 mm above the rotating cap ring (r 9–13), so it is tacked up with Kapton at
   assembly (§7.1, §11.4 D2).
9. **Base-board mounting: done.** SPEC §8 and the base board now use one M2 hole (H1) at r = 20, θ = 270°,
   outside the pack, plus the cup's rib under the θ = 90° edge and the USB-C shell. The θ = 90° boss is gone: it
   stood on the antenna strip.
10. **Other placement checks from the model: done** (`docs/mechanical.md` §3; re-run `extract_board_parts.py`
    and `check_clashes.sh` after any placement change). The three earlier failures are fixed in SPEC §8 and on
    the boards: J1 moved out to r = 19.5 so its mated plug's back clears the rotating hub (B2); the battery
    connector J2 is now the 2.95 mm side-entry SM04B-SRSS-TB instead of the ≈ 5.5 mm PH part (B3); R42 sits at
    r 24.1, clear of the top-cover skirt (B5). The clash check now reports only the intended contacts (hard
    stop, SW1 press, bonded detent rails, felt shoe, drop-stop). The rules still hold for any later change:
    keep the main-board top within r ≤ 4.6 free for the M4 nut (A7), keep bottom parts over the rotating hub
    (r 9.5–12.5) at z ≥ 26.3, and keep bottom parts in the actuator corridor θ 30–160°, r 8.5–27 ≤ 1.3 mm tall
    unless `calcs_output.txt` §11 shows clearance (A11) (SPEC §8).

---

## 3. PCBA at JLCPCB

### 3.1 Service level and sides

* **Main board: Standard PCBA, two sides.** Bottom: MDBT50Q U10 with its VBUS resistor R12, C12 and the
  second-stage USB ESD array U12, QSPI flash U11 and crystal Y1, TMAG5273 U30 and its ESD array U32, both DRV8837
  (U40, U41), link J1, motor connector J40, piezo BZ1, the NFC tuning caps C16/C17, and their passives. Top:
  LEDs, ZIF J20, LDO U1, both TPS22917 load switches (U2, U21), 13 V boost, LIS2DW12, DRV5032 U42, TC2030 pads,
  NFC coil pads J11 (no part). `ORDER-NOTES.md` lists every bottom-side placement. Plan for two reflow passes.
* **Base board: Standard PCBA, top side only.** This is the safer tier for a 0.4 mm DSBGA plus an X-ray request.
  Check JLC's current rules on which tier offers X-ray. The board is single-sided (SPEC §8), so `ORDER-NOTES.md`
  should list no bottom-side placements for it.
* Most ICs are JLC Extended parts. Each unique Extended part carries a per-order setup fee, so check the BOM
  quote and consider ordering 5 boards per order.

### 3.2 X-ray and inspection requests

| Part | Board | X-ray | Reason |
|---|---|---|---|
| U1 BQ25180YBGR (DSBGA-8, 0.4 mm) | base | **Required, every board** | Hidden joints. Bridging or opens here mean no charging or no SYS |
| U10 MDBT50Q-U1MV2 (61 bottom pads, 28 of them inner) | main | **Strongly recommended** | Inner pads cannot be inspected optically or reworked with an iron ([mcu verifier]) |
| U31 LIS2DW12 (LGA-12), U40/U41 DRV8837 (WSON-8 + EP) | main | Optional | Electrical tests in `bringup.md` catch most faults |
| D101–D148 VDD/GND pads | main | AOI; X-ray optional | A VLED-to-GND bridge is stopped only by the BQ25180 BATOCP and the pack PCM: U2 has no current limit (hardware/sim, NF-3) |
| J20 ZIF pins 1–2 | main | No; visual at 10–20× (B-2) | GND sits next to the 13 V VCC at 0.5 mm pitch; a bridge shorts the boost output (hardware/sim, OLED-V3) |

Ask JLC to send the X-ray images. If they are not available, rely on the electrical checks in `bringup.md`: B-4
(BQ25180 power-up), B-9.4 (BQ25180 I2C) and B-7 (module SWD).

### 3.3 Order notes (copy into the JLC order remark)

```
1. Base board U1 BQ25180YBGR (DSBGA-8, 0.4 mm pitch): please X-ray every board and send the images.
2. Main board U10 MDBT50Q-U1MV2 (bottom-terminated module, 61 pads, bottom side; supplied through
   Global Sourcing / consignment): please X-ray and send the images.
3. Main board D101-D148 WS2812C-2020-V6 are MSL 5a (24 h floor life). Please bake per J-STD-033 /
   Worldsemi (70-75 C >= 24 h for reels) before placement, and complete both reflow passes of this
   two-sided board within the floor life.
4. D101-D148 are rotated in 7.5 deg steps around a ring. Please check each placement against the
   pin-1 mark in the preview.
5. DNP (footprint only, do not place): main board R11, U43, C43.
6. The main board is assembled on both sides. The base board is assembled on the top side only.
```

Copy notes 5 and 6 from the `hardware/fab/<board>/ORDER-NOTES.md` that `release.py` writes rather than from this text (§3.5):
it lists the parts flagged `dnp=True` in the sheets and every bottom-side placement.

### 3.4 CPL and orientation spot-checks (in the JLC preview, before paying)

The CPL already carries the per-part rotation and origin corrections (§2). The preview is the check.

* LEDs D101–D148: pin-1 marks follow the ring; the DI/VDD pad column faces the previous LED.
* TMAG5273 U30 (bottom, θ = 270°, Hall element at r = 29.0): long axis radial (SPEC §5.5), so its X axis is
  tangential.
* MDBT50Q U10 (bottom, centred at r 17.3, θ 215°): the u.FL end faces **outward** (u.FL at r ≈ 23, SPEC §8).
* USBLC6-2SC6 U12 (bottom, at the module's D+/D− pads): pin 1 per the silk. Turned 180°, its GND pin lands on
  VBUS_NRF and the internal clamp shorts it (bring-up B-2, B-3a).
* TPD4E05U06 U32 (bottom, beside U30): pin 1 per the silk. Turned 180°, the TMAG lines land on its NC pins and
  are unprotected, and no electrical test shows it (bring-up B-2).
* TPS22917 U2 and U21 (top): pin 1 per the silk.
* AFC01-S30FCA-00 ZIF J20 (top, r 9.5, θ = 270°): pin 1 matches the folded FPC (§7.4). Contacts are on the
  **bottom**.
* BQ25180 U1 (base, r 19.5, θ 255°): ball A1.
* Polarised parts: VCOMH tantalum C32 (C7189, + to the panel pin), B5819W D21 cathode to +13V_OLED, BAV99 D20
  orientation; on the base, SMF5.0A D1 cathode to VBUS.
* Side-entry JST SH link connectors `SM12B-SRSS-TB`, entry toward the board centre: J1 (main, bottom, r 19.5,
  θ 330°) and J3 (base, top, r 15.5, θ 120°). Pin 1 position (§6). Also the motor connector J40 (main, bottom)
  and the battery connector J2 (side-entry SH `SM04B-SRSS-TB`, base, r 17, θ 222°, mouth radially outward,
  BAT+ silk at pins 1–2 and GND at pins 3–4, §7.2).

### 3.5 DNP

`release.py` takes the DNP list from the parts flagged `dnp=True` in `hardware/design/sheets/*.py`, writes it
into `ORDER-NOTES.md` and leaves those parts out of the BOM and the CPL. At the time of writing that is (main
board only):

* **R11**, 10 kΩ NRESET pull-up (`mcu` sheet). The nRF's internal pull-up is used.
* **U43** SN74LV1T34DBVR and its 100 nF **C43** (`leds` sheet): the optional VLED-referenced LED data level
  shifter. The 0 Ω R43 (LED_DIN_R → LED_DIN) is fitted instead. To use the shifter, remove R43 and fit U43 and
  C43 (SPEC §5.4).
* The **DRV5012AEDMRR** fallback wake latch of SPEC §5.5 is not on the `sensors` sheet, so the board has no
  footprint for it.
* Test pads (TP1–TP4, TP10–TP13, TP40 and the base TP1–TP4), the TC2030 footprint J10, the NFC coil pads J11
  and the plated spindle holes H1–H3 are `in_bom = False`. The fiducials and the NPTH holes (main H4/H5, base H1) are board-only.
  None of these needs a part.

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
| WS2812C-2020-V6 (5 mA/ch) | C55109522 | ~47k, single source | Only **V6** parts: the LED data margins are for the V6 input threshold; with any other part fit U43/C43 and remove R43 (SPEC §5.4; hardware/sim, LED-DATA-2). WS2812B-2020-V6 C52917434 (~897k) is footprint- and pin-compatible but **12 mA/ch**: 48 LEDs at full white draw 1.73 A instead of 0.72 A, 2.35 A worst case (SPEC §5.4), so it may be fitted only with firmware's instantaneous current cap (≈ 1.0 A at full battery), and the link power contacts are then at their limit ([leds verifier]; hardware/sim, PI-3) |
| TMAG5273A2QDBVR | C3715882 | ~5.4k LCSC / 6.3k JLC; other variants nearly 0 | Buy reserve stock. The TMAG5173-Q1 is pin-compatible at VCC ≥ 2.3 V (OK at 3.3 V); order the A2/0x35 variant ([sensing verifier]) |
| BQ25180YBGR | C3682423 | ~4.1k | BQ25188YBGR C43043524 (62 pcs); check its register map before swapping |
| PKMCS0909E4000-R1 piezo | C910763 | 0 to 4k across snapshots | DigiKey/Mouser; hand-solder if JLC is out |
| 560 kΩ 0402 (OLED IREF) | C132339 | 0 at LCSC, ~9k at JLC | Any 560 kΩ 1 % 0402 |
| AFC01-S30FCA-00 ZIF | C262671 | ~37k | FH12-30S-0.5SH(55) C506793 (bottom contact) or HDGC 0.5K-HX-30PWB C2919501 (double-sided contacts, removes the orientation risk) |
| SM04B-SRSS-TB (motor J40, base battery J2) | C160404 | fluctuates | Two per board set |
| TS-1187A-B-A-B (press switch) | C318884 | ~2.4k, fluctuates | KSC2-series parts are 3.5 mm tall and do **not** fit the stack ([mechanical verifier]) |
| SC-20S 32.768 kHz | C97603 | ~6.8k | SC-32S C97604 has a different footprint (3.2×1.5) and needs 9–10 pF caps. Not a drop-in |
| TPS22917DBVR (two per main board: U2, U21) | C2681320 | ~28.5k | TPS22918DBVR C131941 is pin-compatible, but its CT goes to GND (§2.4 item 3) |

**Parts changed by the SPICE suite** (all in the sheets, so the generated BOM carries them; check the quote shows
them): R12 4.7 Ω FRC0402F4R70TS (C2909356), VBUS → VBUS_NRF at the module (USB-1); U12, a second USBLC6-2SC6
(C7519) at the module's D+/D− (USB-2); R4 68 Ω RC0402FR-0768RL (C163455), the U2 QOD resistor (LSW-2); main C2,
C6, C41 and base C4 now 10 µF/25 V CL10A106MA8NRNC (C96446), like base C2 (MD-5); base C1 2.2 µF/25 V 0805 X7R
CC0805KKX7R8BB225 (C277470) on the charger input (USB-3); base R4 100 kΩ (C25741), the Q1 gate pull-down
(charger_ts-2). The mechanical model replaced the base battery connector: J2 is the SM04B-SRSS-TB (C160404); the
PH S2B-PH-SM4-TB (C295747) is gone.

### 4.3 Parts not bought through JLC

| Item | Spec | Notes |
|---|---|---|
| OLED panel | NHD-1.5-128128G, or the proven pin-identical Orient AOC128128A0-1.50W | 0 stock at DigiKey/LCSC, 8–16 week lead times; Newhaven direct shows low stock. Buy ≥ 3 early. Other "SSD1351 30-pin" panels are unverified ([display verifier](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)) |
| Bearing | 608 (8×22×7), SKF 608-2Z (shields) or 608-2RSL. **No RSH/RS1 contact seals.** Buy 5+ | [608-2Z data](https://www.simplybearings.co.uk/products/608-2z-skf) |
| Bearing oil | ISO VG 2–10 (e.g. Mobil Velocite No.3 = VG 2, No.6 = VG 10) | Base oil type not stated by Mobil |
| Track magnets | 48 + ≥ 10 spare, NdFeB **Ø2.0×2.0 mm N52**, axially magnetised, NiCuNi, one batch | ±0.05 mm and ±5 % Br vary by vendor ([detent research]) |
| Detent magnet | 1 + spares, **Ø3×2 mm N52** axial | Near-equivalent: [K&J D21B-N52](https://www.kjmagnetics.com/d21b-n52-neodymium-disc-magnet) (1/8"×1/16") |
| Linear stepper | VIC-TECH VSM08102 (Ø8, M2×0.4, ~10 mm stroke, 20 Ω/phase), slider with the spring-preloaded anti-backlash nut | Thrust margin is only ≈ 0.9–1.4× at rest (`docs/mechanical.md` §7), and the SPICE motor model gives at most 0.93 N from any battery VSYS against a 0.8–1.15 N worst-case load (architecture risk R4; hardware/sim, MD-4; still open, §13 #26). The 10 mm sibling does not fit the bowl (`docs/mechanical.md` §7). Fallback: N20 or Ø6 planetary gearmotor with a lead screw. Get the drawing and thrust curve ([vendor page](https://www.micro-steppermotors.com/sale-28526335-vsm08102-8mm-4-pins-fpc-small-linear-stepper-motor-with-slider-m2-lead-screw.html)) |
| Antenna | Molex **146153-0100** (100 mm coax), as SPEC §5.2 and §8 specify | The 50 mm -0050 is too short for the shelf-to-u.FL route (§7.1). -0100 is at DigiKey/Mouser ([Molex](https://www.molex.com/ja-jp/products/part-detail/1461530100)); LCSC C916292 is the -0050, so do not order it |
| Battery | Protected 1S LiPo, **≤ 6.0 mm thick** at the drawing maximum (SPEC §8), ≤ 34.5 × 55 mm including the PCM, UN38.3 report. Re-terminate the leads for J2: 28 AWG pre-crimped SH leads (SSH-003T-P0.2), two per rail, into an SHR-04V-S (pins 1–2 BAT+, 3–4 GND; SPEC §6) | The bay envelope is 55 × 34.5 mm (\|x\| ≤ 27.5, \|y\| ≤ 17.25) with the long axis along θ = 0°/180° and the leads at the θ = 180° end. The mechanical BOM picks a 503450/523450-class pack, ≤ 5.6 mm, ≤ 53 mm long preferred, with the leads leaving the PCM end ≥ 4 mm off the centreline to clear the θ = 180° guide column (`docs/mechanical.md` §13). 6.0 mm leaves the 1.0 mm swelling gap (§7.2) |
| Harness (final) | 12 single JST SH wires pre-crimped on both ends (SSH-003T-P0.2 contacts, no housings), **28 AWG on the power pins 1–4 and 8** (SPEC §2), 32 AWG on the seven signals, + 2× SHR-12V-S housings. Length ≈ 60–70 mm per wire (`docs/mechanical.md` §12; its BOM row lists ~100 mm leads), ≥ 10 mm more on a unit with the lift loop (§6) | §6. Both ends stay loose until the wires have been threaded through the spindle (Stage C) |
| Harness (bench) | A second 12-way SH lead, housings fitted on both ends | Used only for Stages A–B, so the final harness never has to be de-pinned (§6) |
| Battery breakout | The pack lead above built with a break in BAT+: pack-side BAT+, board-side BAT+ and GND brought out as a 3-wire 28 AWG tail to a 3-pin header and a shorting jumper; the J2 end stays the 4-way SHR-04V-S | §7.2. Gives a battery disconnect and a PPK2/bench tap once J2 is buried. The break is spliced into the lead, so no extra mated connector has to fit in the bay |
| RF test pigtail | 1.13 mm coax, ≈ 150–200 mm, **u.FL receptacle** (sold as "U.FL/IPEX male") on one end, SMA on the other, plus 1–2 clip-on ferrites | B-11.2 d/e (Stage R, §11.5). Check that it mates with the Molex antenna's u.FL plug **[TVP]**. It leaves round the board edge (§11.4): the main-board Ø5 hole now carries the spindle's M4 spigot |
| Motor lead | SHR-04V-S housing; ideally a factory-crimped SH lead on the motor | Avoid hand-crimping SH contacts ([detent verifier]) |
| NFC coil | 13.56 MHz flex coil, ≈ 1.4–1.5 µH, in the top cover, with a tail long enough to reach the J11 pads (main top, r 21.5, θ 222°) | C16/C17 (180 pF C0G) are sized for that inductance: measure the coil and retune them on the prototype (SPEC §5.2; bring-up B-9.11) **[TVP]** |
| Fasteners | M2, **brass** (or A4/316 stainless), nylon where the antenna needs it | Test every screw with an N52 magnet. No carbon steel within 10 mm of the track. The OLED-bracket screws through the plated H1–H3 into the brass hub are brass (M2 × 6 countersunk); the hub face clamped on the H1–H3 pads is the GND end of the ring's ESD bleed (§12). The θ 60° stop screw, above the antenna, is nylon (§7.1) |
| Guide pins and stop screws (model) | 3× knurled brass Ø3.0 pins (11.0 mm at θ 180°/300°, 7.0 mm at θ 60°), M2 tapped at the top, pressed with Loctite 638 and locked by Ø1.0 cross pins; 3× M2 × 3 brass pan-head stop screws. At θ 60°, above the antenna: PEEK pin, PEEK cross pin and a nylon screw | `docs/mechanical.md` §8: the springs push the FA plate up against the screw heads (§11.3). The θ 180° guide sits at r = 30 so its column clears the pack end |
| FA springs | 3× compression, 302 SS, wire 0.32 mm, OD 3.95, 3 active + 2 closed/ground, free length 4.72 mm, k ≈ 0.63 N/mm | Installed at 2.60 mm (column/ear seat z 10.5 to plate seat z 13.1): 1.33 N each, 4.0 N total (SPEC: ≈ 4 N). Solid height 1.60 mm leaves 0.50 mm of margin at the 0.50 mm hard stop. A spare set with free length 5.03 mm gives 4.6 N at the same installed length. Measure the rate **[TVP]** |
| Bearing seat | 22 mm-bore single-turn wave washer (working height ≤ 0.5 mm, 30–50 N, stainless) + 0.5 mm 316 cap ring (OD 24.4 / ID 19.9) | A compliant drop seat for the outer race; the cap ring is bonded on the collar top (§10.1). It does not preload the balls (see §13 #12) |
| Turned and small mechanical parts | 316L spindle with M4×0.5 spigot, brass hub, brass lower spacer, M4×0.5 brass nut, Ø3 × 1 silicone press pad, PB ESD strap and silver conductive epoxy, 0.7 mm cover glass, FR4 link plate | Full list with drawings: `docs/mechanical.md` §13 |
| Feet | 3× micro-suction arc pads, 70° each, r 25–31 (model) | SPEC says point feet at r = 28, which tip under a rim press. High-μ gel feet make it tip instead of slide under a hard flick ([mechanical verifier]) |

---

## 5. Moisture sensitivity and baking

| Part | MSL | Handling |
|---|---|---|
| WS2812C-2020-V6 / WS2812B-2020-V6 | **5a** (24 h floor life) ([datasheet](https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf)) | Worldsemi bake: **70–75 °C ≥ 24 h for reels, 120 °C × 4 h for loose LEDs**. The 24 h window runs from the bake to the end of all heating, including repairs. JLC's per-order baking is **not confirmed** ([leds verifier]), hence order note 3 |
| MDBT50Q module, LIS2DW12, others | Per reel label | Keep reels and modules sealed until use |
| BQ25180 DSBGA | Per reel label | |

**Hand rework of an LED on an assembled main board.** The board has certainly exceeded the 24 h floor life, so:

1. Strip the board to the **bare PCBA** first: remove the OLED panel, the harness, the actuator bracket with the
   motor, the carriage and the **N52 detent magnet**, and every printed part (rails, brackets, light box). N52 is
   rated to only about 60–80 °C (§8.5), and a thin Ø3×2 disc starts losing flux irreversibly at the low end of
   that range. Printed PETG/PA12 parts creep at 70–75 °C. Then bake the bare PCBA at **70–75 °C for ≥ 24 h**.
   Check the storage ratings of the piezo and ZIF first; both are rated to +85 °C **[TVP]**.
2. Rework within 24 h. Use preheat and low airflow, keep the hot-air nozzle off neighbouring LEDs' silicone
   lenses, and follow the Worldsemi reflow profile.
3. Use a freshly baked replacement LED (120 °C × 4 h loose).

---

## 6. Link harness (12-way JST SH, through the spindle)

The pinout is identical on both boards and the harness is straight-through, 1→1 (SPEC §2, `nets.py LINK_PINOUT`).

* **Two harnesses.** Build a **bench harness** (housings on both ends, any length ≥ 80 mm) for Stages A–B, and
  keep the **final harness** for the spindle. The final harness is never fitted with both housings before it
  has been threaded, so no SH contact ever has to be extracted from a housing. Extracting and re-inserting SH
  contacts is error-prone, and the detent verifier warns against reworking SH crimps.
* **Threading (final harness).** A 12-way SHR housing is about 14 × 3 mm and cannot pass the **Ø6 bore** or the
  spindle's 5.0 mm-wide side slots (model: the lower window at θ = 120°, z 14.45–16.35, and the upper slot at
  θ = 270°, z 25.8–28.25, with the brass hub's 5.0 mm C-gap above it). Use 12 single wires pre-crimped on both ends
  (SSH-003T-P0.2 contacts): 28 AWG on pins 1–4 and 8 (SPEC §2), 32 AWG on the seven signals (`docs/mechanical.md`
  §13) **[TVP: confirm the lead part numbers]**. At Stage C, while the FA lower stack is still on the bench, push
  the contact ends in through the θ = 120° window and about 10 mm up the bore with a pull string, then the antenna
  coax, plug first, and keep all top ends inside the bore. Insert the base-end contacts into one housing, which
  then plugs into J3 (Stage C3–C4). Fish the top ends out of the θ = 270° slot after the rotor is on, and insert
  them into the main-side housing only then (Stage D1). The bore cross-section (28 mm²) easily holds the wires plus
  the 1.13 mm coax. The 5.0 × 1.9 mm lower window (9.5 mm²) is the tight point: even 12× 28 AWG (≈ 0.7 mm OD) plus
  the coax take ≈ 5.6 mm² there, and with the real 28/32 AWG mix the model's fill is 51 % in the lower window,
  40 % in the upper slot and 17 % in the bore (`docs/mechanical.md` §14).
* **Length.** The modelled path from base J3 (top side) up through the spindle and out of its upper slot to main
  J1 (bottom side, r = 19.5, θ = 330°) is ≈ 43 mm on the current boards (`hardware/mechanical/calcs_output.txt`
  §12, which cuts the wires to 58 mm with 15 mm of slack), and `docs/mechanical.md` §12 cuts them to
  ≈ 60–70 mm, which leaves slack for plugging J3 before the plate goes in. Re-measure on the first mechanical
  mock-up. Allow a **≥ 5 mm service
  loop**, because the FA moves up to 0.5 mm on every press while the base is fixed. On the first unit, and on any
  unit that gets the RF S11 test (Stage R), add a **≥ 10 mm lift loop** (wires that much longer) parked straight
  inside the spindle bore (nothing rotates in the bore). It lets the main board be lifted about 10 mm off the hub
  to reach J1 and the u.FL **[TVP: check on the mock-up]**.
* **Pin 1 orientation.** J1 and J3 are both side-entry `SM12B-SRSS-TB` (LCSC C160411, about 2.95 mm tall) with
  the entry facing the board centre: J1 on the main-board **bottom** at r = 19.5, θ = 330°, and J3 on the
  base-board **top** at r ≈ 15.5, θ = 120°. The pinout is the same at both ends (`nets.py LINK_PINOUT`):
  1, 2 VSYS · 3, 4 GND · 5 VBUS · 6 USB_DM · 7 USB_DP · 8 GND · 9 I2C_SCL · 10 I2C_SDA · 11 CHG_INT_N · 12 BTN_N.
  Mark pin 1 on both housings and check that pin 1 lands on pin 1 at both ends.
* **Current.** JST SH contacts are rated 1 A each, so VSYS on two contacts carries ≤ 2 A and GND has three;
  these five leads are the 28 AWG ones (SPEC §2). A full-white LED ring (0.72 A with the C variant) plus the OLED
  (≤ 0.15 A) fits. With the B variant (2.35 A worst case, SPEC §5.4) the power contacts are at their limit and
  firmware's instantaneous current cap is mandatory (§4.2).
* **Test before first use.**

  | Check | Bench harness | Final harness | Pass |
  |---|---|---|---|
  | Each pin to the same pin at the other end | All 12, on the bench | Stage C4, base end in J3, base unpowered, base TPs still reachable: each loose contact for pins 1–2 (VSYS TP), 3/4/8 (GND TP) and 5 (VBUS TP) | < 0.5 Ω |
  | Each pin to its neighbours | All, on the bench | Loose contacts against each other at C4; then at D1 across adjacent cavities of the fitted main-side housing | > 10 MΩ loose; > 100 kΩ once the base board loads the nets |
  | Pins 1–2 (VSYS) to 3/4/8 (GND) | open | D1, at the housing front | > 100 kΩ (the base VSYS-to-GND reading, B-3c) |

  Final-harness signal pins 6, 7 and 9–12 are verified by function in Stage D (USB enumerates, both I2C devices
  answer, CHG_INT_N pulses, BTN_N follows the press).

* **Strain relief:** Kapton at the spindle exits. Nothing in this path rotates.

---

## 7. Hand-assembly items

### 7.1 Antenna and coax (Molex 146153-0100)

SPEC §8 places the 34.9 × 9 × 0.1 mm flex on a printed shelf at z ≈ 5.5–6.0, centred on the chord y = +23.5
(θ ≈ 90°; strip y 19.0–28.0, corners at r ≤ 33): about 9.5 mm below the ring, about 6 mm above the desk and
1.75 mm in plan from the pack side (y = 17.25). The coax (100 mm on the -0100) rises to the spindle's lower side
slot, runs up the bore and leaves through the upper slot to the module's u.FL (U10, main-board bottom, centred at
r 17.3, θ = 215°, u.FL end facing outward at r ≈ 23). The 50 mm -0050 is too short for this route.

**Geometry** (SPEC §8, `docs/mechanical.md` §9):

* The earlier chord y = +26 put the strip's corners at r ≈ 35.1, outside the cup's inner wall at r = 33.4, so
  SPEC moved it to y = +23.5. The pack is then only 1.75 mm away in plan instead of ≥ 4 mm, and SPEC replaced the
  θ = 90° base-board boss, which stood on the strip, with a printed rib at y 17.75–18.75 (§11.2). The base board
  keeps its copper ≥ 5 mm from the antenna: no plane or pour on B.Cu, In1 or In2 for y > 15.4 (B.Cu/In2 tracks
  and vias may come to y ≈ 17.5) and no F.Cu pour for y > 17 (§2.2, `layout.py`).
* The θ = 60° guide ear sits 0.75 mm above the antenna's +x end, so its pin, cross pin and stop screw are plastic
  (§4.3). The steel spring stays unless S11 says otherwise **[TVP]**.
* At z ≈ 5.5–6 the radiator is about 6 mm above the desk (SPEC). A metal desk still detunes it; bring-up
  B-11.2e tests that case.
* **Route (model):** the coax leaves the antenna's −x end (verify on the Molex drawing), rises at
  (x, y) ≈ (−14.6, 19.9), outside the base board (r 23) and inside the FA ring (r 26), crosses over J3 at
  z ≈ 15, enters the spindle through the θ = 120° window together with the harness, runs up the bore, leaves
  through the θ = 270° slot and the hub's C-gap, and runs back flat against the board bottom beside the module to
  the outward-facing u.FL. On the way it threads between U12 and the module's inner corner, 0.13 mm from U12 and
  0.44 mm above the rotating cap ring (r 9–13), so it **must be tacked up to the board with Kapton** there
  (SPEC §8; §11.4 D2). That is ≈ 79 mm on the current boards (`hardware/mechanical/calcs_output.txt` §12). Stow
  the remaining ≈ 21 mm as one gentle loop against the cup wall at θ ≈ 100–150°, away from the antenna body, and
  leave ≥ 3 mm of slack where the coax crosses the press gap **[TVP: check S11 with the final routing]**. The
  turns into and out of the Ø6 bore are tighter than the usual 5 × OD bend radius **[TVP]**.
* **Plug passage:** the u.FL plug (≈ Ø2.0 × 1.3 plus the crimp sleeve) has to pass the 5.0 × 1.9 mm lower window
  and the 5.0 × 2.45 mm upper slot. Trial-fit a real plug in a spare spindle before the batch is machined
  **[TVP]**.

**Fitting:**

1. Clean the shelf with IPA. Apply the antenna's adhesive once, without bubbles, and do not stretch the
   flex. Keep metal paint, plating and conductive tape away from it.
2. Route the coax with ≥ 5 mm bend radius where there is room. Fix it with Kapton every 15–20 mm. It must never
   cross the rotor running gap.
3. **u.FL mating is rated for only about 30 cycles.** Unmate with a u.FL extraction tool, never by pulling the
   cable, and log every cycle. The planned sequence for a unit that gets the full RF test is:

   | When | Antenna plug mates with | Antenna plug cycles | Module receptacle cycles |
   |---|---|---|---|
   | Stage B, B-11.2 a–c | RF test pigtail (coax still free in the base) | 1 | 0 |
   | Stage D2, before the main board is lowered | RF test pigtail again, led out round the board edge (§11.4) | 2 | 0 |
   | Stage R, after B-11.2 d/e | Module (main board lifted ≈ 10 mm) | 3 | 1 |

   A unit that skips the S11 test (§11.5) mates the module once at D2: 1 cycle each.

### 7.2 Battery

1. **Polarity first.** SPEC §6: J2 (side-entry SH `SM04B-SRSS-TB`) pins 1–2 = BAT+, pins 3–4 = GND, two
   1 A contacts per rail, marked BAT+/GND on the silkscreen next to J2. The pack is re-terminated with 28 AWG
   pre-crimped SH leads, two per rail (§4.3), and hobby pack lead colours are not standardised. Measure the lead
   at its SHR-04V-S housing with a DMM before every first insertion. The BQ25180 BAT pin has an absolute minimum
   of −0.3 V, so a reversed pack destroys the charger ([power research]).
2. Check the pack voltage (accept 3.5–4.2 V; do not use a pack below 3.0 V), the protection-PCB position and
   whether its length clears the cup wall.
3. **Swell gap.** SPEC §8 limits the pack to ≤ 6.0 mm. In the bay (z 2.5–9.0) it tops out at z 8.5, and the
   base board's underside is at z 9.5, which leaves the **1.0 mm** swelling gap SPEC asks for (the mechanical
   verifier asked for 0.8–1.0 mm). Check it against the maximum thickness on the pack drawing, not the nominal.
   The base board is single-sided, so nothing sits on its underside over the pack. The NTC RT1 is on the top
   (r 8, θ 200°) and reads board and pack-air temperature, not the cell skin (SPEC §8).
4. Fix the pack with thin double-sided foam tape, not hard adhesive, so it can swell and be replaced. Long axis
   along θ = 0°/180° (SPEC §8: |x| ≤ 27.5, |y| ≤ 17.25), against the cup's θ = 0° end stop, with the leads at the
   θ = 180° end (model: leaving at y ≈ −7.5, clear of the θ = 180° guide column).
5. Nickel is slightly ferromagnetic ([power research]). The cell's tab end is the lead end at θ = 180°; keep
   any extra nickel strip or steel hardware away from the TMAG side (θ = 270°).
6. **Battery breakout (fit at Stage B on every unit that will get B-9.9b, B-10 or B-9.8f after Stage C).** Once
   the FA lower plate and the rotor are in, J2 cannot be reached. J2 sits on the base-board top at r = 17,
   θ = 222°, mouth radially outward (SPEC §8, `layout.py`), and the pack leads run from the pack end beside the
   pack at z ≈ 10, under the spider, and come up over the board edge at θ ≈ 222° (SPEC §8). The pack can then no
   longer be unplugged or replaced by a supply. Use the breakout lead (§4.3) as the pack's J2 lead. Bring its
   3-wire tail (BAT+ pack side, BAT+ board side, GND) out through a Ø3 cable port printed in the cup wall of a
   **dev cup**, at z ≈ 3–8 (below the base board), at θ ≈ 190–230° near
   the pack's lead end and J2, clear of the θ = 180° guide column and away from the antenna side (θ ≈ 90°)
   **[TVP: mock-up]**. Outside the cup:
   * **jumper fitted:** normal operation;
   * **jumper open:** battery disconnected, for safe harness plugging (Stage C–D) and for supply tests;
   * **PPK2 ammeter mode:** VIN to the pack side, VOUT to the board side, GND to GND, in series with the real pack;
   * **PPK2 source mode or bench supply:** board side and GND, pack side left open.

   Check that the splice and the tail fit beside the pack's lead end (x ≈ −27.5 to −33) and keep clear of the
   spider (the model has the leads 1.4 mm under the pressed plate) **[TVP: mock-up]**.
   Leave the breakout in engineering units. On a unit that must ship without it, swap it for a plain lead only
   when the main board, hub and rotor come off anyway (the stop screws sit under the ring, §11.3).

### 7.3 Detent actuator, carriage and detent magnet

The actuator hangs from the main-board underside in the bowl (r 12–27, z 19–29.1), chord placement near θ = 90°
(model: chord at y = 15.5, sweeping θ ≈ 35–160°, stepper saddle on the θ = 60° hole H4). The carriage slides the
magnet radially from r = 29.0 (click) to r = 21.5 (free) along θ = 90°, 1.0 mm above the track (SPEC §1, §8).

1. **Motor coil check:** about 20 Ω per coil pair for the VSM08102 (measure your part), and the cross pairs
   open. Terminate the lead in an SHR-04V-S housing: pin 1 A+, 2 A−, 3 B+, 4 B− (SPEC §5.6).
2. **Detent magnet:** bond the Ø3×2 N52 into the non-magnetic carriage pocket (PA12/POM) with its axis normal
   to the track face. With an alternating track, either polarity gives 24 detents, and the polarity only shifts
   the rest phase by 7.5°, which calibration absorbs. Record which face is down. The DRV5032 home sensor is
   omnipolar.
3. **Clearances:** the detent research asks for the stepper can ≥ 10 mm from the track and from the parked magnet,
   the steel lead-screw tip ≥ 5 mm from the detent magnet and nothing ferrous within 4 mm of any magnet face
   ([detent research]). The model's layout cannot meet this: the can comes within 3.1 mm of the nearest track
   magnet and the lead screw within 4.6 mm (`docs/mechanical.md` §3 A12). Bench-test the free-mode cogging before
   the PCB is frozen **[TVP]**.
4. **Guide and lash** (`docs/mechanical.md` §7, which supersedes the earlier spring-preload scheme):
   * Bond the two rails to the board bottom and shim them with Kapton so the 0.48 mm carriage plate has
     **≤ 0.02 mm** vertical play (feeler), with PTFE tape on both faces. There is no spring preload.
   * Bond the 0.8 mm FR4 link plate with the inclined slot under the carriage web. A small phosphor-bronze leaf on
     the slider presses its Ø1.5 brass pin against one slot flank at about 0.5 N, so the reversing ±0.29 N
     magnetic radial force cannot rattle the pin across the slot.
   * Use the VIC-TECH slider with the spring-preloaded anti-backlash nut and check the total lash at the carriage
     (≤ 0.03 mm with a dial indicator and ±0.5 N reversal). A separate anti-lash spring toward PARK does not fit
     as a near-constant force here and would drop the thrust margin below 1×.
   * The thrust margin of the 8 mm motor is only ≈ 0.9–1.4× at rest on a rating given at 500 PPS, and the SPICE
     motor model gives at most 0.93 N from any battery VSYS against the verified 0.8–1.15 N worst-case load
     (architecture risk R4; hardware/sim, MD-4; §13 #26). Keep the friction low (PTFE tape, lubricated slot) and
     the carriage preload low (the load must stay ≤ 0.5 N), move the carriage only with the rotor at rest or below
     1 rev/s, and step the loaded 0–4 mm zone at ≤ 300 PPS. Gate: slider thrust ≥ 0.85 N at 3.0 V / 300 PPS against the
     real carriage. If it fails, fall back to an N20 or Ø6 planetary gearmotor; the 10 mm stepper does not fit the
     bowl.
   * The M2×0.4 lead screw self-locks, so the carriage cannot be pushed by hand. Move it only by stepping
     (bring-up B-9.10).
   * Fit the damping shoe (felt or UHMW-PE pad on the carriage flexure, not PTFE) so that it lands on the ring top
     face outside the magnets only at offsets ≤ 1.5 mm.
5. **Park before assembly:** mount the actuator on the main board, plug the motor lead into J40 and step the
   carriage to PARK (r = 21.5) on the bench (Stage A8, B-9.10a–c) before the main board is lowered over the rotor,
   so the detent magnet is not dragged across the track during assembly. J40 sits on the board's bottom side and
   cannot be reached once the board is seated.
6. **Gap:** the nominal gap is 1.0 mm (RSS ±0.13 mm, worst case ±0.25 mm in `docs/mechanical.md` §5); it must
   never touch. Check it with feeler gauges at the click position once the board is clamped (Stage D) and correct
   a whole-rotor height error with 0.05 mm **brass** shims between the hub top and the board (§11.4).

### 7.4 OLED panel into the ZIF (last electronic step)

The TC2030 SWD pads are under the OLED glass (SPEC §8). **Fit the panel only after** bring-up B-7 (SWD),
B-8.7 (MCUboot DFU and at least one serial-recovery route proven **with the TC2030 removed**) and B-9.9a (bare
boost verified at 12.7–13.3 V and discharged).

1. **Mock up first.** Cut a 1:1 paper or Kapton copy of the FPC, fold it 180° behind the glass and check the
   insertion depth, contact side and pin 1. The free tail after the fold is only about 5 mm before the COF IC
   ([display verifier]).
2. **Discharge +13V_OLED.** Before inserting the FPC, touch a 1 kΩ resistor across the boost output cap. The
   rail decays only through the 551 kΩ FB divider: about 12 µF effective gives τ ≈ 6–7 s.
3. **Inspect J20 pins 1–2** at 10–20× before inserting: pin 1 (GND) sits next to pin 2 (the 13 V VCC) at
   0.5 mm pitch, and a bridge or solder ball there shorts the boost output. Firmware can only react afterwards:
   it records OLED_VCC_EN in retained RAM and keeps the OLED off after a brown-out or BAT_OCP reset
   (hardware/sim, OLED-V3).
4. With power off, open the ZIF lid. The AFC01-S30FCA-00 is **bottom-contact**: after the fold, the FPC
   contacts face the PCB. Insert squarely up to the stiffener and close the lid.
5. **Bend rules:** radius ≥ 0.5 mm, ≥ 1 mm preferred. Bend only between the glass edge and the COF driver IC,
   never across the IC or the 4 mm stiffener, and do not press on the IC area.
6. **Mounting:** support the glass on its back perimeter only, outside the 28.86 mm viewing area, with thin foam
   tape on the bracket rim (0.3–0.5 mm per the display research; the model leaves room for 0.2 mm). The
   **active-area centre (1.47 mm off the glass centre, away from the FPC edge) goes on the dial axis**, not the
   glass centre. Keep ≥ 0.3 mm of air gap to the window, which is the 0.7 mm cover glass bonded in the top cover
   (the model leaves 0.6 mm). The window and top cover carry press loads; the glass must not
   ([display research](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)).
7. **Light separation:** the opaque light-box inner wall must seal to the PCB (≤ 0.1 mm or thin black foam) and
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
| Pocket | Ø2.05–2.10 mm × **2.20 mm deep** (recommended; SPEC §8 and the model say 2.05). Pick the diameter after measuring the magnet lot |
| Flushness | Faces flush ±0.03 mm to the top face; face runout ≤ 0.05 mm TIR. A 0.1 mm recess costs about 10 % detent torque |
| Why not 2.05 deep | With Ø2×2 ±0.05 mm magnets pushed to the bottom of a 2.05 mm pocket, every face ends 0–0.10 mm **below** the ring face, which breaks the ±0.03 mm target, and a flat clamp plate cannot pull a recessed magnet up. The sensing verifier's rule is a pocket ≥ 0.15 mm deeper than the longest magnet with the face set flush against a datum while the adhesive cures, or face-machining after bonding. If the ring has already been made at 2.05, see §8.5 step 4b |
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
* Add a flat **clamp plate** (aluminium or glass; non-ferrous, flat to ≤ 0.01 mm) with a thin PTFE release film.
  It rests on the ring's top face, so it sets each magnet face flush only if the magnet starts **proud** and is
  pushed down until the plate bottoms on the ring (§8.5). Use a film ≤ 0.02 mm thick, or account for it: the
  faces end up recessed by the film thickness.
* Use a **magnet dispenser:** a brass or plastic tube (ID ≈ 2.1 mm) holding a stack of magnets. A stack is
  self-aligned, so mark the stack's exposed face polarity once with a pole identifier. Push the bottom magnet
  into the pocket and shear the stack sideways.
* Tools: brass, titanium or plastic tweezers and a plastic push pin. **No steel tools near the ring.**

### 8.5 Procedure

1. Degrease the pockets (IPA) and dry them. Keep the ring away from steel chips: magnets collect swarf.
2. Fit Mask A. Put an **epoxy bed** in each even pocket, enough that a magnet set on it stands about 0.1–0.2 mm
   proud of the ring face (≈ 0.3–0.4 mm of epoxy in a 2.20 mm pocket). Insert **24 magnets N-up** onto the beds;
   do not push them to the bottom. Same-polarity neighbours 7.6 mm apart only repel weakly, so they stay put.
3. **Before the epoxy gels**, check every placed magnet with a pole identifier or Hall probe: all must read N.
4. Lift off the mask, lay the release film and the flat non-magnetic clamp plate on the ring and press it down until the plate
   **bottoms on the ring's top face**. That pushes every magnet down to flush and squeezes the excess epoxy out.
   Clamp and cure fully, then wipe or scrape the squeeze-out with a plastic tool.
   * **4b. Ring already made with 2.05 mm pockets:** sort the magnet lot by length and use only magnets
     ≥ 2.03 mm (a pocket of exactly 2.05 then gives ≤ 0.02 mm recess). Or bond them proud as above in pockets
     deepened to 2.20 with a flat-bottom Ø2 end mill. Last resort: bond proud and lap the track flush on a flat
     plate with wet 600–1000 grit, keeping the ring below ≈ 50 °C. Lapping removes the magnets' NiCuNi coating,
     so seal the track afterwards (step 7). NdFeB swarf is flammable, so keep it wet and collect it.
5. Fit Mask B and insert **24 magnets S-up** on epoxy beds the same way. These sit between opposite-polarity
   neighbours and are pulled sideways and up, so hold each one until the plate goes on. Check the polarity of
   all 48 in sequence: it must read N, S, N, S … all the way round. Lift off the mask, press with the plate until
   it bottoms on the ring face, clamp and cure.
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

Bearing friction sets the spin time. For this rotor the SKF model gives about 28 s from 10 rev/s on factory
grease against 95–131 s on oil (`docs/mechanical.md` §4), and contact seals (RSH/RS1) stop the rotor in about
1 s ([mechanical research and verifier](https://cdn.skfmediahub.skf.com/api/public/0901d1968065e9e7)).

1. Buy at least 5 bearings of the chosen type (608-2Z or 608-2RSL, CN clearance, ABEC-5/P5 or better).
2. **Degrease.** **Never pour IPA, naphtha or any other flammable solvent straight into an ultrasonic tank.**
   Cavitation heats and aerosolises the solvent, and the tank's transducer driver and heater are ignition
   sources; cleaner makers prohibit it. Use one of these instead:
   * **Indirect bath:** put the bearing and the solvent (IPA or naphtha) in a closed glass jar or beaker, stand
     it in the water-filled tank with the **heater off**, and run 3 × 5 min with fresh solvent each time,
     spinning the bearing by hand between runs. Work in a ventilated area away from flames and sparks, and keep
     the solvent volume small (≈ 20–30 ml).
   * Or a **non-flammable** water-based degreaser directly in the tank, followed by a thorough rinse in
     demineralised water, an IPA rinse outside the tank to displace the water, and full drying, because the
     bearing steel rusts.

   Remove the shields if they are designed to be removable. SKF 2Z shields are not, so flush with them in place
   and repeat until the bearing runs free and silent.
3. Dry with clean, dry air, but **do not spin the bearing up with an air jet**.
4. Oil with **1–2 drops of ISO VG 2–10** synthetic instrument oil. Do not over-oil: excess oil adds viscous drag.
5. Spin-test each bearing on a Ø8 arbor: more than 30 s from a finger flick, with no shield rub, grit or notchy
   feel (`docs/mechanical.md` §4). Fit the best one (§10.1) and keep the runner-up as a spare. B-13 then measures
   the spin-down on the rotor. Swapping the bearing later means warming the bonded cap ring to about 120 °C to
   lift it off.
6. Re-oiling will be needed periodically: shields are meant for inner-ring rotation and this design spins the
   outer ring ([mechanical verifier]). Note the date in the build log.

---

## 10. Rotor assembly and balancing

### 10.1 Assembly

The order is fixed: **magnets → bearing into the carrier → ring bonded on the arbor → static balance → wave washer,
cap ring and ESD strap** (`docs/mechanical.md` §5, §12).

1. Check the ring: OD 70 / ID 54 / 10 mm, OD/ID concentricity ≤ 0.02 mm TIR, faces flat and square ≤ 0.02 mm
   (§8.2 magnet test too).
2. Install the magnets (§8) **before** balancing.
3. Bore the printed **PA12-GF carrier** (web z 17–19, r 11–27) to Ø22 H7 and turn its register in the same
   chucking (bore-to-register ≤ 0.02 mm TIR). **No aluminium or copper may rotate within 13 mm of the detent
   magnet's path.** An aluminium web would cost about 0.13–1.6 N·mm of eddy drag, against about 0.15 N·mm of
   bearing friction ([mechanical verifier]). Slide the prepared 608 (§9) into the collar against its lower lip
   (slip fit), pushing **on the outer race only**, never through the balls.
4. **Bond the ring on an arbor.** Slide the carrier, with the 608 seated, onto a ground Ø8 arbor in a lathe or
   V-blocks, spread epoxy on the register, and rotate and tap the ring until a dial indicator on the OD reads
   ≤ 0.02 mm TIR. Set the ring top 0.60 ± 0.03 mm above the 608 outer-race top face with a flat that carries a
   0.60 mm annular spigot resting on the race. Cure undisturbed.
5. **Static-balance** the rotor (§10.3).
6. Fit the wave washer and bond the 0.5 mm 316 cap ring on the collar top. **ESD bleed (SPEC §8):** bond the
   0.1 × 3 mm phosphor-bronze strap with silver conductive epoxy from the ring ID along the web and up the collar
   to under the cap ring, so the touchable ring connects through the cap ring and wave washer to the outer race
   (`docs/mechanical.md` §4). Check ring-to-outer-race continuity with a DMM. Weigh the finished rotor (≈ 134 g
   in `calcs.py`) **[TVP]** and use the measured value for I in B-12/B-13.

### 10.2 Balance targets (`docs/mechanical.md` §5, `calcs.py`)

| Item | Value |
|---|---|
| ISO G2.5 at 15 rev/s for the 134 g rotor | U_per ≈ **3.5 g·mm** |
| Target | **≤ 2 g·mm** ([mechanical research]) |
| Ring OD/ID eccentricity 0.02 mm TIR | ≈ 1.17 g·mm |
| Ring-to-bearing eccentricity | ≈ 1.25 g·mm bonded on the arbor (TIR ≤ 0.02); ≈ 4.4 g·mm bonded freehand |
| RSS before correction, bonded on the arbor | ≈ 1.7 g·mm |
| One missing magnet | 1.37 g·mm |
| Corrections on the ring bottom face at r = 31 | Ø2 × 1 dimple −0.93 g·mm; empty M2 balance hole −1.49; brass grub screw +1.35; non-magnetic W-alloy grub screw +2.70. Calibrate a dimple by weighing chips: the drill-point cone adds mass |

### 10.3 Static balance (§10.1 step 5)

1. Mount the rotor, 608 seated, on a ground Ø8 arbor.
2. Balance on two level, hardened knife edges or a magnetic balancer. The 608's breakaway friction
   (≈ 0.04–0.1 N·mm) masks imbalances below about 4–10 g·mm if the rotor turns on its own bearing, so follow
   `docs/mechanical.md` §5 for the bearing (a second, freshly degreased 608, or spinning the arbor) **[TVP]**.
3. Let it settle from random start angles. The heavy spot comes to rest at the bottom.
4. Correct on the **ring bottom face at r = 31**, which faces the base lip and is not visible: dimples at the heavy
   spot, or grub screws in the four M2 balance holes (θ 45°/135°/225°/315°). **Never add steel, W-Ni-Fe or
   ferrous putty** (§12).
5. Repeat until there is no preferred rest angle in 20 random releases. Knife-edge sensitivity is roughly
   0.5–1 g·mm **[TVP]**.

### 10.4 Dynamic trim (after full assembly, Stage E, **before** the B-13 spin-down acceptance) **[TVP]**

Use the firmware balancing assistant: the LIS2DW12 runs in high-performance mode at 400–1600 Hz, and its x/y
signals are demodulated synchronously with the encoder angle ([sensing research]). Use a single-plane trial
weight:

1. Spin to 10–15 rev/s and record the 1×/rev vibration vector V0.
2. Stick a known trial mass at a known angle on the ring bottom face, e.g. 50 mg of non-magnetic putty at r = 31
   (1.55 g·mm). Record V1. The bottom face at r = 31 is above the base lip; reach it from the side through the
   gap between the ring and the cup wall, or with a thin spatula.
3. Correction = −V0 / (V1 − V0) × trial mass. Apply it at the computed angle and verify.

The FA rides on springs and the desk, so the IMU's response to imbalance is unknown until measured. Acceptance
(`docs/mechanical.md` §5): at 15 rev/s the 1×/rev component must not exceed the value measured with a 2 g·mm test
mass taped at r = 31.

---

## 11. Mechanical assembly order

Each stage has a gate: do not continue until the referenced bring-up step passes.

**Why this order.** In the model, the FA up-stops are M2 screws in the tops of the guide pins. Their heads sit at
r = 29–30, directly under the rotor ring (ring r 27–35, bottom face z 15.6; screw heads z 13.5–14.8). They can only
be fitted before the rotor goes on. The floating assembly (FA) is therefore built **in place on the base**, bottom
up, in the order of the model's exploded view (`docs/mechanical.md` §12): spindle stack and plate, rotor, hub, main
board, all clamped by one M4 nut on the board top. From Stage C on, the harness and the antenna coax also tie the
FA to the base.

### 11.1 Stage A: electronics on the bench (no mechanics)

| Step | Action | Gate (`bringup.md`) |
|---|---|---|
| A1 | Inspect both boards, check resistances | B-2, B-3 |
| A2 | Base alone on a current-limited 5 V supply, then on a bench battery | B-4 |
| A3 | Main alone from bench VSYS | B-5 |
| A4 | Build and test the **bench harness** (§6). Link the boards. First linked power-up: 5.00 V at a 100–150 mA limit into the base VBUS TP, no battery. Only after that passes, a charger behind a USB meter | B-6 |
| A5 | SWD: recover, UICR, flash the bring-up image | B-7 |
| A6 | First firmware: clocks, DC/DC, SAADC, USB CDC | B-8.1–B-8.6 |
| A7 | Peripheral smoke tests that need no mechanics: QSPI, I2C, IMU, BQ25180, battery and press network, piezo, LED ring, **bare boost screen (12.7–13.3 V)** | B-9.1–B-9.9a |
| A8 | Mount the actuator on the main board (§7.3): bond and shim the rails, fit the carriage with its FR4 link plate, zero-lash leaf and detent magnet, and screw the stepper saddle to the θ = 60° hole H4 with a brass M2 (H5 at θ = 120° stays unused). Plug the motor lead into J40. Run the driver, motor and home-sensor tests on the bench. **End at PARK with all IN low and nSLEEP low**, after the ≥ 3 ms brake (SPEC §5.6) | B-9.10a–c |
| A9 | **MCUboot and recovery gate**, with the TC2030 removed and a battery on J2. Record which recovery route works | B-8.7 |

Keep steel tools away from the main board from A8 on, because the detent magnet is fitted.

### 11.2 Stage B: base sub-assembly

1. **Feet.** The model uses three 70° arc pads at r 25–31 (DEV, to resist tipping). SPEC says point feet at r = 28.
2. **Guide pins (model).** Press the 3 knurled brass Ø3.0 pins (M2 tapped at the top) into the cup with Loctite
   638: columns from the floor at θ = 300° (r = 29) and θ = 180° (r = 30, clear of the pack end), and the ear at
   θ = 60° (r = 29), which sits above the antenna and takes a PEEK pin and PEEK cross pin (§7.1). Keep them
   perpendicular within 0.1 mm at the top (check with a printed square). Push the Ø1.0 cross pins in from outside
   the cup and seal the holes with epoxy. Keep adhesive out of the tapped holes and off the sliding length. The
   column and ear tops (z 11.5) are the FA's hard stop.
3. **Base-board supports (SPEC §8).** One M2 boss at r = 20, θ = 270°, under the base board's hole H1; a printed
   rib under the θ = 90° edge (y 17.75–18.75, between the pack and the antenna shelf, no screw); and the USB-C
   shell, captured in a slot in the cup wall. Heat-set the M2 × 3 brass insert into the boss now.
4. **Antenna** onto its shelf, centred at (0, 23.5) with the cable end toward −x (§7.1). Before bonding, mate the
   RF test pigtail to the antenna plug (u.FL cycle 1) and run **B-11.2 a**. Bond the flex and run **B-11.2 b**.
   Lead the coax to its riser point (−14.6, 19.9), tape it, and leave the pigtail mated for B-11.2 c.
5. **Battery** (§7.2): polarity check, foam tape, pack against the θ = 0° end stop, leads routed beside the pack
   toward θ ≈ 222°, where they come up over the base-board edge to J2 (SPEC §8). Fit the **breakout lead** and
   bring its tail out through the dev-cup port (§7.2 step 6), jumper open.
6. **Base board.** Lower it with the tab about 1.5 mm short of the wall, slide it outward into the USB slot so the
   USB-C mating face ends flush to +0.3 mm proud at r = 35.0 (opening = receptacle + 0.3 mm,
   [mechanical research]), then fit the brass M2 screw through H1 at θ = 270°. Run **B-11.2 c**, then unmate the
   pigtail.
7. Plug the battery (through the breakout) into J2 and fit the jumper. The board comes up in battery mode.
   Check VSYS at the base TP (B-9.5a). With the bench harness, link the main board once more and confirm I2C to
   the BQ25180 (B-9.2).
8. **End Stage B with the base dead:** write SHIP_RST = 0x49 (ship mode, B-9.5c) before unplugging the bench
   harness, or open the breakout jumper. VSYS must be off while the final harness is plugged in at Stages C
   and D.

### 11.3 Stage C: FA lower stack, suspension and rotor, in place on the base

Prerequisites: Stage B done and the base dead; the final harness wires with both ends loose (§6); the rotor
finished and statically balanced, with the wave washer, cap ring and ESD strap fitted (§10.1); the main board from
A8 at PARK.

1. **Press pad.** Measure the switch travel t_u on the base board (reject a switch above 0.32 mm). Bond the Ø3 × 1.0
   silicone pad into the pocket in the spindle's solid bottom, with 0.025/0.05 mm Kapton discs under it to set the
   per-unit pre-gap g0 = 0.38 − t_u (`docs/mechanical.md` §8).
2. **FA lower stack (on the bench).** Check the turned 316L spindle with an N52 (it must not cling). Push it up
   through the plate's D-recess: the bottom flange and the D-flats at θ = 90° set its angle, so the lower window
   faces θ = 120° and the upper slot θ = 270°. Slide on the brass lower spacer (D-bore, wire window at θ = 120°).
3. **Thread the harness and the coax** into the bore through the θ = 120° window now (§6), and keep their top ends
   inside the bore. Insert the base-end contacts into one SHR-12V-S housing.
4. Plug that housing into J3. Test the harness (§6 table, final-harness column) while the base TPs can still be
   reached.
5. Drop the 3 FA springs into the column and ear pockets. Check them against the spec first (§4.3). Lower the
   plate over the pins, with the wires and the coax passing through the plate's open sector at θ = 120° (spokes
   at θ = 60°/180°/300°, SPEC §8). The USB-C receptacle sits in the notch in the plate's outer ring at θ = 0°.
6. Fit the 3 M2 **stop screws** (brass at θ 180°/300°, nylon at θ 60°) into the pin tops through the plate
   counterbores, with no washers and a brass-compatible threadlocker. The springs now hold the plate up against the
   screw heads.
7. **Plate check.** The plate slides freely and returns under spring force. The centre free play equals the
   per-unit pre-gap. A press at the centre gives an audible click (about 4–5 N), and the hard stop comes at
   0.50 mm when the plate's under-bosses land on the column and ear tops. A press over each spoke must also click
   before the stop. The electrical click check is D6. If the base was left in ship mode, keep these presses under
   1 s: a 2 s press is a ship-mode wake.
8. Lower the rotor over the spindle until the 608 inner race seats on the brass lower spacer. The wires and coax
   inside the bore do not obstruct it. If the race binds, do not force it through the outer race or the ring.
   Then fish the wire ends and the coax plug out of the θ = 270° upper slot. Leave the ≥ 5 mm service loop at the
   base end, plus the ≥ 10 mm lift loop inside the bore on the first unit (§6).
9. Spin the rotor by hand. There is no detent magnet over it yet, so any ticking means a ferrous part near the track
   or a magnet standing proud. Rubbing means a stack-up error; check the 0.15 mm drop-stop gap under the carrier
   lip.

### 11.4 Stage D: main board

The main board is tethered as soon as the harness or the coax is connected, and J1, J40 and the module u.FL all
face down once it is seated. Make every connection with the board held just above the hub.

1. Slide the brass hub down the spindle with its C-gap at θ = 270° over the wires and the coax (the D-flat at
   θ = 90° sets its angle). Its top face will be the GND contact for the plated H1–H3 on the board bottom. Insert
   the loose harness contacts into the main-side SHR-12V-S housing, pin 1 to pin 1 (§6), and do the D1 checks in
   the §6 table.
2. Hold the main board 10–20 mm above the hub, on edge or upside down, with the carriage still at PARK from A8.
   Check that the motor lead is in J40. Plug the harness into J1. Then **either**:
   * **Normal build:** mate the antenna plug to the module's u.FL (1 cycle each), which faces outward at r ≈ 23
     (§2.4 item 8); **or**
   * **RF test build (Stage R follows):** fit the RF test pigtail instead. Mate it to the antenna plug on the bowl
     side, then tape the pigtail radially along the board underside at θ ≈ 200° (clear of the TMAG at 270° and the
     actuator at 35–160°) and up around the board edge at r = 32. It crosses ≈ 2.4 mm above the ring's top face,
     which is acceptable for a static measurement. Use a pigtail with a non-magnetic (silver-plated copper, not
     copper-clad steel) centre conductor. The earlier centre route down the Ø5 hole is gone: the hole now carries
     the spindle's M4 spigot.

   Dress the service loops and Kapton-tape the coax, and the mated pair or pigtail, to the board underside so
   nothing hangs into the rotor's swept volume: r ≤ 12.2 below z 26.0, and the carrier web at z ≤ 19 (see §2.4
   item 8). **Tack the coax up with Kapton where it passes between U12 and the module's inner corner:** it clears
   U12 by 0.13 mm and the rotating cap ring (r 9–13) by only 0.44 mm (SPEC §8, §7.1).
3. Lower the board onto the hub over the M4 spigot, with H1–H3 over the hub's tapped holes. Fit the M4 × 0.5
   brass nut with Loctite 222 and tighten it to 0.10 N·m with a pin spanner. That one nut clamps board → hub →
   608 inner race → lower spacer → plate → spindle flange (`docs/mechanical.md` §4). Check the magnet-to-track gap
   at the click position with feeler gauges (1.0 ± 0.1 mm) and correct it with 0.05 mm **brass** shims between hub
   and board, never Kapton, because the hub face is the GND contact (§7.3). Measure ring to TP4 GND with the rotor
   turning slowly and log it (pass < 10 MΩ, `docs/mechanical.md` §4) **[TVP]**.
4. **Spin check:** the rotor turns freely in FREE (carriage parked) with no ticking. A ticking rotor in FREE means
   a ferrous part near the track, a magnet standing proud, or a carriage that is not at PARK.
5. **First power-up on the final harness.** Keep the breakout jumper **open**, so the pack cannot feed a harness
   fault, and feed the USB-C receptacle from a 5.00 V bench supply at a 100–150 mA limit through a USB-C plug
   breakout. Check VSYS (4.4–4.6 V) across C6 or C2 on the top side (main TP1 VSYS is on the bottom and is now
   covered, §2.4 item 7) and TP2 +3V3 (3.30 V). Confirm that USB enumerates, I2C finds 0x19 and 0x6A, and
   CHG_INT_N pulses on plug and unplug. That proves the harness signal pins. Then fit the jumper (if the base was
   left in ship mode, the USB insertion has already woken it).
6. **Click check:** press at the centre and at the rim at θ = 0°, 120° and 240°. Every press must click and pull
   BTN_N low (B-9.5d). For the 4.0 N preload and the 1.6 N switch, `docs/mechanical.md` §8 expects ≈ 4.6 N at the
   centre and ≈ 1.9–2.4 N at the ring rim; the spare 4.6 N spring set raises these. Measure with a gram gauge
   **[TVP]**. Rim presses that do not click mean the rim ledge is too shallow for the switch travel.

### 11.5 Stage R: RF acceptance, B-11.2 d/e (only if the test pigtail was fitted at D2)

Required on the first unit of a build, and whenever the antenna, the cup, the pack or the coax route changes. On
later identical units it is optional, and B-11.3 (Stage G) is the per-unit RF gate.

1. The top is still open: no OLED, light box, diffuser or cover (the top cover is not in the antenna's near
   field). Fit a clip-on ferrite on the pigtail outside the device, ≥ 30 mm from the magnet track, and lead the
   cable away vertically.
2. Run B-11.2 d (wooden desk) and e (metal plate, hand on the dial), including the cable-touch test.
3. **Swap to the module.** Power on and confirm the carriage is at PARK: the firmware's park stall is the
   reference and HOME_N low only confirms it, because on some units the DRV5032 can also assert near full click
   (`firmware.md` §5.4). Make the base dead again (ship mode or breakout jumper open) and unplug USB. Remove the
   M4 nut. Lift the main board straight up ≈ 10 mm off the spigot on the lift loop (§6), then tilt the module side
   (θ ≈ 215°) up, keeping the opposite edge from dropping onto the ring. Unmate the pigtail with the extraction
   tool and pull it out. Mate the antenna plug to the module (§7.1 table: plug cycle 3, module cycle 1). Re-dress
   the coax, lower the board, refit the nut (0.10 N·m, fresh Loctite 222) and repeat D3–D6.
4. Log the u.FL cycles.

### 11.6 Stage E: mechanics-dependent tests (top still open)

In this order: TMAG field with the rotor (B-9.6c–d); actuator and home sensor on the rotor (B-9.10c–d); detent
calibration (B-12); **dynamic balance trim (§10.4)**; then spin-down acceptance (B-13), which needs the rotor
fully assembled and balanced. Keep the top open so SWD stays reachable. Supply from the real pack (jumper fitted)
or through the breakout (B-1).

### 11.7 Stage F: close the top

1. Light box (white interior, opaque exterior, r 27–30), bonded and sealed to the PCB with its 24 septa between
   the LEDs.
2. OLED bracket, fixed with 3 brass M2 × 6 countersunk screws through H1–H3 into the hub, then the panel (§7.4).
   Test the display (B-9.9b) on a bench supply or the PPK2 through the breakout (B-1).
3. Diffuser ring (opal PMMA, r 27–30) glued into the top cover, and the 0.7 mm cover glass bonded into its Ø33
   recess. **NFC coil:** with the cover held just above the light box, solder the coil's flex tail to the J11
   pads (main top, r 21.5, θ 222°; flat pads, because a header does not fit under the display glass, SPEC §5.2)
   **[TVP: tail route past the OLED bracket on the mock-up]**. Snap the cover (Ø30 OLED window, cover OD
   r = 32.5) onto the light box, then run B-9.11.
4. From here on, firmware updates go over MCUboot (USB CDC or BLE SMP), and SWD needs the top and OLED removed.
   **Write the serial-recovery route that passed B-8.7 into the unit log and on a label under the base**, for
   example "hold the dial through the 20 s reset and keep holding until the USB port re-enumerates" (route a)
   or "from ship mode: hold the dial and plug in USB" (route b). Route c (app command 0x08) needs a running app.

### 11.8 Stage G: final acceptance

1. Radiated and link checks (B-11.3), and the NFC read check (B-9.11) if it was not run in Stage F. The S11
   measurements (B-11.2) were done in Stages B and R and are not repeated here.
2. Sleep and mode currents (B-10), with the PPK2 on the breakout tail.
3. The full pass/fail table (B-14).
4. Ring to GND < 10 MΩ with the rotor turning slowly (`docs/mechanical.md` §4) **[TVP]**.
5. Check that the breakout jumper is fitted, then leave the unit in ship mode or shutdown (B-9.5c).

## 12. Material and fastener rules (summary)

* **Non-magnetic** within 10 mm of the track (r 27–31) or the TMAG5273: 316/A4 or brass screws, 302/316/BeCu
  springs, PA12/POM structure. **No carbon steel, 4xx/17-4 stainless or W-Ni-Fe weights** ([detent research]).
* **Non-conductive** (no aluminium or copper) on any rotating part within 13 mm of the detent magnet path
  (eddy drag). The one exception is the 3 mm-wide radial phosphor-bronze ESD strap, a strip rather than a loop,
  whose eddy drag is negligible (`docs/mechanical.md` §5).
* **No metal paint, plating or conductive tape** near the antenna; plastic only within 10 mm of it in-plane.
* **Conductive** all along the ring's ESD bleed to GND (SPEC §8): phosphor-bronze strap in silver epoxy, cap ring,
  608, spindle, brass hub, hub face on the plated H1–H3. Shim between hub and board only with brass, never Kapton,
  and use brass screws through H1–H3.
* **Every screw tested with an N52 magnet** before it goes in.

## 13. Open items and [TVP] list (assembly)

| # | Item | Status |
|---|---|---|
| 1 | TPS22917 CT: C7 must go CT–VSYS (SLVSDW8B) (§2.4 item 3) | **Done:** `main_power.py` has C7 = 1 nF from LSW_CT to VSYS, QOD through R4 = 68 Ω to VLED (VLED to 10 % in ≤ 26.6 ms, SPICE), R3 = 100 kΩ ON pull-down; the OLED switch U21 has C37 = 1 nF CT–VSYS and its QOD tied to OLED_VIN |
| 2 | SPEC's base-board bosses at r = 15 overlapped the battery footprint | **Done:** SPEC §8 and the base board use one M2 hole at r = 20, θ 270° outside the pack (now along θ 0°/180°), a printed rib under the θ 90° edge and the USB-C shell (§2.2, §11.2) |
| 3 | Antenna did not fit on the floor at x = −26 | **Done:** SPEC §8 moved it to a printed shelf centred on y = +23.5 (z 5.5–6, about 6 mm above the desk, corners at r ≤ 33). Desk sensitivity remains (B-11.2e) |
| 4 | Coax length (§7.1) | **Done:** SPEC §5.2 and §8 specify 146153-0100 (100 mm); the -0050 is too short (§4.3) |
| 5 | Battery-to-board swell gap 0.7 mm (§7.2) | **Done:** SPEC §8 limits the pack to ≤ 6.0 mm, which leaves 1.0 mm, and the base board is single-sided |
| 6 | FA up-stops | Defined in the model: knurled brass guide pins pressed with Loctite 638 and locked by Ø1 cross pins (PEEK at θ 60°), M2 × 3 stop screws in counterbores. Their heads sit under the ring, which forces the in-place build order (§11). Pull-out capacity ≈ 270–390 N per pin against a very uncertain drop load: pull-test the first printed cup (`docs/mechanical.md` §8) **[TVP]** |
| 7 | JLC LED baking and X-ray image availability (§3) | Open |
| 8 | Harness lead part numbers and lengths, including the lift loop; 28 AWG on pins 1–4 and 8 (§6) | Open |
| 9 | Knife-edge balance sensitivity; IMU dynamic trim response (§10) | TVP |
| 10 | Folded-FPC fit under the glass (§7.4 mock-up) | TVP |
| 11 | Module and mated u.FL over the hub: the earlier placement (r 14.5, u.FL toward the centre) put the module's inner end ≈ 1.5 mm into the brass hub and the plug 0.2 mm into the rotating cap ring (§2.4 item 8, `docs/mechanical.md` §3B B1) | **Done:** U10 centred at r 17.3, θ 215°, inner end r ≥ 8.8, u.FL facing outward (SPEC §8); the clash check passes. The coax passes 0.13 mm from U12 and 0.44 mm above the cap ring, so it is Kapton-tacked at D2 (§11.4) |
| 12 | Bearing "wave-spring preload" (SPEC §8): a single 608 cannot be axially preloaded by a spring without a reaction against the stationary side. In the model the wave washer and cap ring only form a compliant drop seat. The rotor weight (≈ 1.3 N) exceeds the ±0.7 N detent pull, so the balls should stay loaded anyway **[TVP]** | Restate in SPEC |
| 13 | FA springs did not match the model's installed length | **Done:** re-specced to the pockets: wire 0.32, free length 4.72, 2.60 mm installed, 1.33 N each, 0.50 mm to solid at the hard stop (§4.3). Measure the rate **[TVP]** |
| 14 | J2 location and height | **Done:** SPEC §8 and the board put J2 on the base-board top at r = 17, θ = 222°, mouth radially outward, with BAT+/GND silk, and J2 is now the 2.95 mm side-entry SM04B-SRSS-TB (pins 1–2 BAT+, 3–4 GND) instead of the ≈ 5.5 mm PH part (#24). It is still buried after Stage C, hence the breakout (§7.2) |
| 15 | Spindle and hub exit slots were too small for the harness and the coax | **Done in the model:** 5.0 mm-wide lower window at θ 120° (z 14.45–16.35) and upper slot at θ 270° (z 25.8–28.25), with a 5.0 mm C-gap in the hub (§6) |
| 16 | Magnet pocket depth: SPEC and the model say 2.05; ≥ 2.20 is needed to set Ø2×2 ±0.05 magnets flush (§8.1) | SPEC change |
| 17 | The earlier model's Ø2 "ship-mode/reset access" hole under the switch was covered by the pack | **Closed:** the current model has no such hole; the spindle's solid bottom carries the press pad |
| 18 | u.FL plug through the 5.0 × 1.9 mm lower window and the 5.0 × 2.45 mm upper slot (§7.1). The RF test pigtail now leaves round the board edge only, because the Ø5 hole carries the M4 spigot (§4.3, §11.4) | TVP on a spare spindle |
| 19 | Antenna 1.75 mm in plan from the pack instead of ≥ 4 mm, and the θ 60° guide ear 0.75 mm above it (§7.1). A ≤ 30 mm-wide pack would restore 4.0 mm (`docs/mechanical.md` §3 A1) | Measure S11 (B-11.2) |
| 20 | Ring ESD bleed path (ring → PB strap in silver epoxy → cap ring → wave washer → 608 → spindle → brass hub → H1–H3 → GND, SPEC §8, `docs/mechanical.md` §4) (§10.1, §11.4) | **TVP:** ring to GND < 10 MΩ with the rotor turning slowly |
| 21 | Base-board RT1 placement | **Done:** RT1 is on the top side (SPEC §8); it reads board and pack-air temperature, not the cell skin |
| 22 | LED-cavity silk: the stock LED footprints' silk marks (D101–D148) lie in r 27–30 (§2.1); R42 has moved to r 24.1 | Open, before ordering |
| 23 | L20 courtyard reaches r ≈ 19.9, ≈ 7 mm in plane from the r = 27 edge of the track annulus (§2.4 item 2) | Check before ordering |
| 24 | Other model clash items (§2.4 item 10): J1's mated plug only 0.15 mm above the rotating hub (B2), the PH battery connector J2 (≈ 5.5 mm tall) and its plug into the pressed rotor web and the FA ring (B3), R42 under the top-cover skirt (B5) | **Done:** J1 at r 19.5, J2 = SM04B-SRSS-TB, R42 at r 24.1; the clash check shows only the intended contacts. The M4-nut keep-out (r ≤ 4.6, A7) and the actuator-corridor height rule (A11) stay in force for later changes |
| 25 | Stepper can and lead screw 3.1–4.6 mm from the track, against SPEC's 10 mm rule; free-mode cogging unknown (§7.3, `docs/mechanical.md` §3 A12) | Bench test before PCB freeze **[TVP]** |
| 26 | Actuator thrust: the SPICE motor model gives the VSM08102 at most 0.93 N from any battery VSYS against a 0.8–1.15 N worst-case load (architecture risk R4; hardware/sim, MD-4) (§4.3, §7.3) | **Open:** cut the carriage preload and anti-lash spring so the load stays ≤ 0.5 N, or change the actuator; the 10 mm sibling does not fit the bowl in the model |
| 27 | NFC coil: inductance, C16/C17 tuning (180 pF for ≈ 1.4–1.5 µH) and the tail route from the cover to J11 (§4.3, §11.7) | TVP on the prototype (bring-up B-9.11) |

Source abbreviations used above: "[x research]" and "[x verifier]" refer to the subsystem research and its
independent verification, which SPEC.md was built from. Where the two differ, the verifier's corrected value is
used. Datasheet links are inline where a number depends on them.
