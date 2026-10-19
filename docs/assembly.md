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
  Where SPEC §8 is not buildable as written, the model deviates from it and marks the constant `DEV:`. SPEC §8
  has since been revised: the base board is a Ø46 disc on two M2 bosses at r = 21, the pack lies along
  θ = 0°/180°, the antenna sits on a printed shelf along y = +26, both link connectors are side-entry and the FA
  lower plate is a 3-spoke spider. This document follows SPEC and the generated boards for those items (§2.2,
  §6, §7.1, §7.2, §11.2). It still follows the model for the guide pins and stop screws, the FA springs, the
  spindle slots and hub, and the feet (§4.3, §11). The model is being updated to the generated boards, so
  re-check those steps against `docs/mechanical.md` before printing parts.
* Designators are the ones in the schematic sheet modules (`hardware/design/sheets/*.py`) and on the generated
  boards. The BOM, CPL and `ORDER-NOTES.md` that `release.py` writes come from the same netlists (§2), so treat
  those files, not this text, as the order record.

---

## 1. What gets built where

| Item | Made by | Notes |
|---|---|---|
| Main board PCB + PCBA (Ø64, 4-layer, ENIG) | JLCPCB, Standard PCBA, **both sides** | MDBT50Q module via Global Sourcing or consignment (§4.1) |
| Base board PCB + PCBA (Ø46 + USB tab, 2-layer, ENIG) | JLCPCB, Standard PCBA, top side, plus RT1 on the bottom (§3.1) | BQ25180 DSBGA, X-ray required (§3.2) |
| 12-way link harness through the spindle (plus a separate bench harness) | Hand | §6 |
| 2.4 GHz flex antenna + coax | Hand (adhesive + u.FL mate) | §7.1 |
| 1S LiPo pack + JST-PH breakout lead | Hand | Check polarity before plugging in (§7.2) |
| Detent actuator (micro linear stepper), carriage, Ø3×2 detent magnet | Hand | §7.3 |
| OLED panel into the bottom-contact ZIF | Hand, **after SWD programming and the recovery gate (B-8.7)** | §7.4 |
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
| Silkscreen | Any, but **none inside the LED cavity r 27–30** | Silk and bare copper inside the cavity show as specular hotspots ([leds research]). As generated, the stock LED footprints' own silk marks (D101–D148) and R42's reference lie in this band: remove them or accept the hotspots (§13 #22) |
| Board outline | Ø64 disc, centre Ø5; 3× **plated GND** M2 (H1–H3) at r = 6.5, θ 90°/210°/330°; 2× NPTH M2 (H4/H5) at r = 17, θ 60°/120° | SPEC §8. H1–H3 clamp the spindle hub and are the GND end of the ring's ESD bleed path (§10.1). H4/H5 hold the actuator bracket |
| Fiducials | FID1–FID3 on the top, FID4–FID6 on the bottom (1 mm copper, 2 mm mask opening) | Three per assembled side (`layout.py`) |
| Electrical test | Yes (JLC default for multilayer) | |

### 2.2 Base board (`hardware/kicad/base`)

| Option | Setting | Why |
|---|---|---|
| Layers | 2 | SPEC §2 |
| Thickness | 1.6 mm | Stiffness under the centre press switch: 1.6 mm deflects < 0.05 mm under 5 N, while 0.8 mm deflects about 0.26 mm ([mechanical research]) |
| Surface finish | **ENIG** (required) | JLC requires ENIG for 0.20–0.25 mm BGA pads. The BQ25180YBG is a 0.4 mm-pitch DSBGA-8 on 0.23 mm NSMD pads ([power verifier]; [BQ25180 datasheet](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) |
| Copper | 1 oz | Charger traces carry up to 1 A |
| Solder mask | Green is fine (hidden) | Mask opening on the DSBGA must be ≤ 0.05 mm larger than the 0.23 mm pad. The footprint (`base.py`) opens it 0.025 mm per side, giving 0.28 mm openings and a dam of about 0.12 mm at 0.4 mm pitch. If that is below JLC's minimum for the chosen colour, JLC may merge the openings. Accept it, since no traces run between balls **[TVP: check the JLC DFM report]** |
| Board outline | Ø46 disc plus a 13 mm-wide tab to r = 34.6 at θ = 0° for the USB-C; 2× NPTH M2 (H1/H2) at r = 21, θ = 90°/270° | SPEC §2, §8; `layout.py`. The holes sit outside the pack, and the USB-C shell clamped in the cup wall is the third support (§11.2) |
| USB-C shell legs | Plated slots per the HRO TYPE-C-31-M-12 footprint | Shell legs carry the cable side loads |
| Bottom side | **Only RT1**, the 0402 NTC (r 8, θ 200°) | `layout.py` puts it there so it reads the cell through a soft thermal pad (architecture §8.5, R28). The underside faces the LiPo across 1.0 mm (§7.2) |
| Fiducials | FID1–FID3 on the top | `layout.py` |

### 2.3 Panelization of round boards

Both outlines are round. Pick-and-place needs straight edges, so order with **"Panel by JLCPCB" plus edge
rails**, or accept JLC adding process edges. Break-off tabs (mouse bites) leave nubs on the rim:

* Main board: put tabs where the rim is free of parts. File the nubs flush, because the light box (r 27–30) and
  the top cover (r 32.5) sit very close to the r = 32 edge.
* Base board: keep tabs off the USB tab and away from the 2 M2 holes at r = 21 (θ 90°/270°).

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
   (VSYS is the switch's VIN), with QOD through R4 = 100 Ω to VLED and R3 = 100 kΩ as the ON pull-down. The OLED
   boost-input switch U21 (`display.py`) is wired the same way: C37 = 1 nF from CT to VSYS, QOD open. With CT to
   VIN, SLVSDW8B gives at VIN = 3.6 V: tR = 1.6 µs/pF (≈ 1.6 ms) and tON = 3.8 µs/pF (≈ 3.8 ms, the "≈ 4 ms" of
   SPEC §5.1), with RON = 90 mΩ typ / 110 mΩ max at 25 °C (80 mΩ is the 5 V figure). If the slew were
   uncontrolled, the inrush into the 2× 22 µF + 48× 100 nF on VLED would be about 1 A ([power research]).
   Bring-up step B-9.8a measures it. Only the TPS22918 alternate takes CT to GND, so if you substitute it for U2
   or U21, its CT capacitor goes back to GND.
4. **TC2030-IDC-NL footprint** J10 on the top side under the OLED glass (r 12, θ 150°): 6 pads plus 3 NPTH
   locating holes, with no parts inside the cable-head outline.
5. **LED rotations:** D101 (pixel 1, SPEC "LED1") sits at θ = 0° and the numbering runs CCW to D148: 48 LEDs at
   7.5° steps on r = 28.5. Each footprint is rotated, so check in the JLC placement preview that every pin-1 mark
   is rotated consistently (§3.4). Note that D1 on the *base* board is the SMF5.0A TVS.
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
8. **Module u.FL clearance to the rotor: still open.** The mated u.FL plug stands about 2.5 mm proud of the module
   and points down, toward the rotor. The layout follows SPEC §8: U10 is on the bottom at r = 14.5, θ = 215°,
   with its u.FL end toward the centre, and its courtyard reaches in to r ≈ 8.5. That puts the plug above the 608,
   the bearing retainer and the carrier collar, which rotate and reach up to z = 26.0 at r ≤ 12.2 in the model,
   and leaves no margin to the spindle-flange keep-out r ≤ 8.5 (`docs/mechanical.md` §3 item 7 asks for the
   module to start at r ≥ 8.7). In the earlier model the plug overlapped the rotor's swept envelope by
   ≈ 41 mm³ (z 24.4–26.0, r 9.5–12.2; a `clash_geom` run on `main_board`). Before ordering, re-run the clash check
   with the as-placed board (`hardware/mechanical/extract_board_parts.py` brings the board parts into the model)
   and either show clearance or move the module so that its u.FL sits at r ≥ 13 over the bowl (the carrier web is
   at z ≤ 19 there).
9. **Base-board mounting holes: done.** SPEC §8 and the base board now use 2× M2 (H1/H2) at r = 21,
   θ = 90°/270°, outside the pack, with the USB-C shell as the third support. The cup has to match (§11.2).

---

## 3. PCBA at JLCPCB

### 3.1 Service level and sides

* **Main board: Standard PCBA, two sides.** Bottom: MDBT50Q U10, QSPI flash U11 and crystal Y1, TMAG5273 U30
  and its ESD array U32, both DRV8837 (U40, U41), link J1, motor connector J40, piezo BZ1, and their passives.
  Top: LEDs, ZIF J20, LDO U1, both TPS22917 load switches (U2, U21), 13 V boost, LIS2DW12, DRV5032 U42, TC2030
  pads. `ORDER-NOTES.md` lists every bottom-side placement. Plan for two reflow passes.
* **Base board: Standard PCBA.** This is the safer tier for a 0.4 mm DSBGA plus an X-ray request. Check JLC's
  current rules on which tier offers X-ray. Every part is on the top except **RT1** (0402 NTC, r 8, θ 200°),
  which `layout.py` puts on the bottom against the pack (§2.2); `ORDER-NOTES.md` lists it as the only bottom-side
  placement. Either order two-sided assembly for that one part, or remove RT1 from the BOM and CPL before upload
  and hand-solder it (§13 #21).
* Most ICs are JLC Extended parts. Each unique Extended part carries a per-order setup fee, so check the BOM
  quote and consider ordering 5 boards per order.

### 3.2 X-ray and inspection requests

| Part | Board | X-ray | Reason |
|---|---|---|---|
| U1 BQ25180YBGR (DSBGA-8, 0.4 mm) | base | **Required, every board** | Hidden joints. Bridging or opens here mean no charging or no SYS |
| U10 MDBT50Q-U1MV2 (61 bottom pads, 28 of them inner) | main | **Strongly recommended** | Inner pads cannot be inspected optically or reworked with an iron ([mcu verifier]) |
| U31 LIS2DW12 (LGA-12), U40/U41 DRV8837 (WSON-8 + EP) | main | Optional | Electrical tests in `bringup.md` catch most faults |

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
6. The main board is assembled on both sides. The base board has one bottom-side part (RT1).
```

Copy notes 5 and 6 from the generated `hardware/fab/<board>/ORDER-NOTES.md` rather than from this text (§3.5):
it lists the parts flagged `dnp=True` in the sheets and every bottom-side placement.

### 3.4 CPL and orientation spot-checks (in the JLC preview, before paying)

The CPL already carries the per-part rotation and origin corrections (§2). The preview is the check.

* LEDs D101–D148: pin-1 marks follow the ring; the DI/VDD pad column faces the previous LED.
* TMAG5273 U30 (bottom, θ = 270°, Hall element at r = 29.0): long axis radial (SPEC §5.5), so its X axis is
  tangential.
* MDBT50Q U10 (bottom, r 14.5, θ 215°): the u.FL end faces the board centre (SPEC §8), so the coax runs straight
  into the spindle bore.
* AFC01-S30FCA-00 ZIF J20 (top, r 9.5, θ = 270°): pin 1 matches the folded FPC (§7.4). Contacts are on the
  **bottom**.
* BQ25180 U1 (base): ball A1.
* Polarised parts: VCOMH tantalum C32 (C7189, + to the panel pin), B5819W D21 cathode to +13V_OLED, BAV99 D20
  orientation; on the base, SMF5.0A D1 cathode to VBUS.
* Side-entry JST SH link connectors `SM12B-SRSS-TB`, entry toward the board centre: J1 (main, bottom, r 17.5,
  θ 330°) and J3 (base, top, r 15.5, θ 120°). Pin 1 position (§6). Also the motor connector J40 (main, bottom)
  and the battery connector J2 (base, BAT+ silk at pin 1, §7.2).

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
* Test pads (TP1–TP4, TP10–TP13, TP40 and the base TP1–TP4), the TC2030 footprint J10 and the plated spindle
  holes H1–H3 are `in_bom = False`. The fiducials and the NPTH holes (main H4/H5, base H1/H2) are board-only.
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
| WS2812C-2020-V6 (5 mA/ch) | C55109522 | ~47k, single source | WS2812B-2020-V6 C52917434 (~897k) is footprint- and pin-compatible but **12 mA/ch**: 48 LEDs at full white draw 1.73 A instead of 0.72 A, 2.35 A worst case (SPEC §5.4), so the firmware ring cap ≤ 0.75 A is mandatory and the link power contacts are at their limit ([leds verifier]) |
| TMAG5273A2QDBVR | C3715882 | ~5.4k LCSC / 6.3k JLC; other variants nearly 0 | Buy reserve stock. The TMAG5173-Q1 is pin-compatible at VCC ≥ 2.3 V (OK at 3.3 V); order the A2/0x35 variant ([sensing verifier]) |
| BQ25180YBGR | C3682423 | ~4.1k | BQ25188YBGR C43043524 (62 pcs); check its register map before swapping |
| PKMCS0909E4000-R1 piezo | C910763 | 0 to 4k across snapshots | DigiKey/Mouser; hand-solder if JLC is out |
| 560 kΩ 0402 (OLED IREF) | C132339 | 0 at LCSC, ~9k at JLC | Any 560 kΩ 1 % 0402 |
| AFC01-S30FCA-00 ZIF | C262671 | ~37k | FH12-30S-0.5SH(55) C506793 (bottom contact) or HDGC 0.5K-HX-30PWB C2919501 (double-sided contacts, removes the orientation risk) |
| SM04B-SRSS-TB (motor) | C160404 | fluctuates | |
| TS-1187A-B-A-B (press switch) | C318884 | ~2.4k, fluctuates | KSC2-series parts are 3.5 mm tall and do **not** fit the stack ([mechanical verifier]) |
| SC-20S 32.768 kHz | C97603 | ~6.8k | SC-32S C97604 has a different footprint (3.2×1.5) and needs 9–10 pF caps. Not a drop-in |
| TPS22917DBVR (two per main board: U2, U21) | C2681320 | ~28.5k | TPS22918DBVR C131941 is pin-compatible, but its CT goes to GND (§2.4 item 3) |

### 4.3 Parts not bought through JLC

| Item | Spec | Notes |
|---|---|---|
| OLED panel | NHD-1.5-128128G, or the proven pin-identical Orient AOC128128A0-1.50W | 0 stock at DigiKey/LCSC, 8–16 week lead times; Newhaven direct shows low stock. Buy ≥ 3 early. Other "SSD1351 30-pin" panels are unverified ([display verifier](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)) |
| Bearing | 608 (8×22×7), SKF 608-2Z (shields) or 608-2RSL. **No RSH/RS1 contact seals.** Buy 5+ | [608-2Z data](https://www.simplybearings.co.uk/products/608-2z-skf) |
| Bearing oil | ISO VG 2–10 (e.g. Mobil Velocite No.3 = VG 2, No.6 = VG 10) | Base oil type not stated by Mobil |
| Track magnets | 48 + ≥ 10 spare, NdFeB **Ø2.0×2.0 mm N52**, axially magnetised, NiCuNi, one batch | ±0.05 mm and ±5 % Br vary by vendor ([detent research]) |
| Detent magnet | 1 + spares, **Ø3×2 mm N52** axial | Near-equivalent: [K&J D21B-N52](https://www.kjmagnetics.com/d21b-n52-neodymium-disc-magnet) (1/8"×1/16") |
| Linear stepper | VIC-TECH VSM08102 (Ø8, M2×0.4, 0.02 mm/full step, ~10 mm stroke, 20 Ω/phase), or its 10 mm sibling for thrust margin | Listings conflict on stroke and the 10 mm part's thrust is unverified; get the drawing ([vendor page](https://www.micro-steppermotors.com/sale-28526335-vsm08102-8mm-4-pins-fpc-small-linear-stepper-motor-with-slider-m2-lead-screw.html)) |
| Antenna | Molex **146153-0100** (100 mm coax), as SPEC §5.2 and §8 specify | The 50 mm -0050 is too short for the shelf-to-u.FL route (§7.1). -0100 is at DigiKey/Mouser ([Molex](https://www.molex.com/ja-jp/products/part-detail/1461530100)); LCSC C916292 is the -0050, so do not order it |
| Battery | Protected 1S LiPo, 603450 class, **≤ 6.0 mm thick** at the drawing maximum (SPEC §8), JST-PH 2.0 lead, UN38.3 report | The bay envelope is 55 × 34.5 mm (\|x\| ≤ 27.5, \|y\| ≤ 17.25) with the long axis along θ = 0°/180° and the leads at the θ = 180° end. A protected 603450 is about 34.5 × 54–55 mm (diagonal 64–65 mm). The cup inner diameter is 66.8 mm. 6.0 mm leaves the 1.0 mm swelling gap (§7.2) |
| Harness (final) | 12× JST SH pre-crimped double-ended leads, **28 AWG on the power pins 1–4 and 8** (SPEC §2), 28 or 30 AWG on the signals, + 2× SHR-12V-S housings | §6. One end stays loose until it has been threaded through the spindle (Stage C) |
| Harness (bench) | A second 12-way SH lead, housings fitted on both ends | Used only for Stages A–B, so the final harness never has to be de-pinned (§6) |
| Battery breakout | Short JST-PH 2.0 extension (PH plug ↔ PH receptacle housing) with BAT+ cut and both ends, plus GND, brought out as a 3-wire 28–30 AWG tail to a 3-pin header and a shorting jumper | §7.2. Gives a battery disconnect and a PPK2/bench tap once J2 is buried |
| RF test pigtail | 1.13 mm coax, ≈ 150–200 mm, **u.FL receptacle** (sold as "U.FL/IPEX male") on one end, SMA on the other, plus 1–2 clip-on ferrites | B-11.2 d/e (Stage R, §11.5). Check that it mates with the Molex antenna's u.FL plug and that its receptacle end passes the main-board Ø5 hole and the hub channel (3.5 × 1.5 mm in the model) **[TVP]** |
| Motor lead | SHR-04V-S housing; ideally a factory-crimped SH lead on the motor | Avoid hand-crimping SH contacts ([detent verifier]) |
| Fasteners | M2, **A4/316 stainless or brass**, nylon where possible | Test every screw with an N52 magnet. No carbon steel within 10 mm of the track. The 3 hub screws through the plated H1–H3 must be metal (A4 or brass), because they carry the ring's ESD bleed to GND (§12). No metal fastener within 10 mm of the antenna (§13 #19) |
| Guide pins and stop screws (model) | 3× brass Ø3.0 pins, tapped M2 at the top, bonded into the cup ears; 3× M2 A4 or brass pan-head stop screws | Model `guide_pins()`: the springs push the FA plate up against the screw heads (§11.3) |
| FA springs | 3× compression, 302/316 wire 0.35 mm, OD 4.0, free 6.0 mm, 5 active coils (k ≈ 0.53 N/mm) | Installed at about 3.56 mm for 3.9 N total; 3.4 mm gives 4.15 N ([mechanical verifier]). SPEC: ≈ 4 N. **The model's pockets give an installed length of only ≈ 2.65 mm** (ear seat z 10.25 to plate seat z 12.9). At that length this spring gives ≈ 5.3 N, and its solid height (≈ 7 × 0.35 = 2.45 mm) leaves 0.2 mm of travel against the 0.6 mm overload stop. Re-spec the spring to the pockets before buying, for example ≈ 3.5 active coils, free length ≈ 4.3–4.5 mm, k ≈ 0.78 N/mm, ≈ 1.3 N each at 2.65 mm, solid height ≤ 1.9 mm **[TVP]** |
| Bearing wave spring | Non-magnetic (316 or BeCu), ≥ 2.5–3 N axial preload (SPEC §8) | Meant to keep every ball loaded under the ±0.7 N alternating detent pull ([detent verifier]). In the model it sits between the outer race and a snap retainer in the carrier, so it only retains the race; it does not load the balls (see §13 #12) |
| Feet | 3× rubber or micro-suction at r = 28 | High-μ gel feet make it tip instead of slide under a hard flick ([mechanical verifier]) |

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
* **Threading (final harness).** A 12-way SHR housing is about 14 mm wide and cannot pass the **Ø6 bore** or the
  3.5 × 1.5–1.9 mm spindle exit slots (model). Use leads pre-crimped on both ends, for example JST "ASSHSSH28K"
  series double-ended leads **[TVP: confirm the part number and length]**. Insert one end into the base-side
  housing (J3) and leave the other 12 contacts loose. At Stage C, feed the loose contacts into the spindle's
  lower exit slot a few at a time, together with the antenna coax, and fish them out of the upper slot with a
  loop of 0.2 mm nylon line. Insert them into the main-side housing only then (Stage D1). The bore
  cross-section (28 mm²) easily holds 12× 28 AWG (≈ 0.7 mm OD) plus the 1.13 mm coax. **The exit slots do not:**
  in the model the spindle slots and the hub channel are 3.5 × 1.5–1.9 mm (≈ 5.3–6.7 mm²), while 12 × 0.7 mm
  wires plus the coax take ≈ 5.6 mm². SPEC §2 keeps 28 AWG on the five power leads (pins 1–4 and 8), so thinner
  wire can help only on the seven signals: 5× 28 AWG + 7× 30 AWG (≈ 0.5 mm OD) plus the coax take ≈ 4.3 mm²
  (estimate from the same ODs). Widen the slots (≈ 5 × 2.5 mm) before printing (§13 #15).
* **Length.** Measure on the first mechanical mock-up, from base J3 (top side) up through the spindle and out
  of its upper side slot to main J1 (bottom side, r = 17.5, θ = 330°). Allow a **≥ 5 mm service loop**,
  because the FA moves 0.3–0.6 mm on every press while the base is fixed. On the first unit, and on any unit that
  gets the RF S11 test (Stage R), add a **≥ 10 mm lift loop** parked straight inside the spindle bore (nothing
  rotates in the bore). It lets the main board be lifted about 10 mm off the hub to reach J1 and the u.FL
  **[TVP: check on the mock-up]**.
* **Pin 1 orientation.** J1 and J3 are both side-entry `SM12B-SRSS-TB` (LCSC C160411, about 2.95 mm tall) with
  the entry facing the board centre: J1 on the main-board **bottom** at r = 17.5, θ = 330°, and J3 on the
  base-board **top** at r ≈ 15.5, θ = 120°. The pinout is the same at both ends (`nets.py LINK_PINOUT`):
  1, 2 VSYS · 3, 4 GND · 5 VBUS · 6 USB_DM · 7 USB_DP · 8 GND · 9 I2C_SCL · 10 I2C_SDA · 11 CHG_INT_N · 12 BTN_N.
  Mark pin 1 on both housings and check that pin 1 lands on pin 1 at both ends.
* **Current.** JST SH contacts are rated 1 A each, so VSYS on two contacts carries ≤ 2 A and GND has three;
  these five leads are the 28 AWG ones (SPEC §2). A full-white LED ring (0.72 A with the C variant) plus the OLED
  (≤ 0.15 A) fits. With the B variant (2.35 A worst case, SPEC §5.4) the power contacts are at their limit and
  the firmware ring cap is mandatory (§4.2).
* **Test before first use.**

  | Check | Bench harness | Final harness | Pass |
  |---|---|---|---|
  | Each pin to the same pin at the other end | All 12, on the bench | Stage C2, base end in J3, base unpowered, base TPs still reachable: each loose contact for pins 1–2 (VSYS TP), 3/4/8 (GND TP) and 5 (VBUS TP) | < 0.5 Ω |
  | Each pin to its neighbours | All, on the bench | Loose contacts against each other at C2; then at D1 across adjacent cavities of the fitted main-side housing | > 10 MΩ loose; > 100 kΩ once the base board loads the nets |
  | Pins 1–2 (VSYS) to 3/4/8 (GND) | open | D1, at the housing front | > 100 kΩ (the base VSYS-to-GND reading, B-3c) |

  Final-harness signal pins 6, 7 and 9–12 are verified by function in Stage D (USB enumerates, both I2C devices
  answer, CHG_INT_N pulses, BTN_N follows the press).

* **Strain relief:** Kapton at the spindle exits. Nothing in this path rotates.

---

## 7. Hand-assembly items

### 7.1 Antenna and coax (Molex 146153-0100)

SPEC §8 places the 34.9 × 9 × 0.1 mm flex on a printed shelf at z ≈ 5.5–6.0 along the chord y = +26 (θ ≈ 90°),
outer edge ≤ r 33: about 9.5 mm below the ring, about 6 mm above the desk and ≥ 4 mm from the pack side
(y = 17.25). The coax (100 mm on the -0100) rises to the spindle's lower side slot, runs up the bore and leaves
through the upper slot to the module's u.FL (U10, main-board bottom, r = 14.5, θ = 215°, u.FL end toward the
centre). The 50 mm -0050 is too short for this route.

**Geometry: check SPEC's shelf on the mock-up** (also §13 #19). The committed model still has the earlier
floor-pocket layout at x = −23.85 and is being updated:

* SPEC's numbers do not all fit together. Centred on y = +26, the 9 mm-wide strip's outer corners sit at
  r ≈ 35.1, outside the cup's inner wall at r = 33.4 (Ø70, 1.6 mm wall). With the corners at r ≤ 33 the centre
  moves to y ≈ 23.5 and the inner edge to y ≈ 19.0, only ≈ 1.75 mm from the pack side instead of ≥ 4 mm. The
  base-board boss at r = 21, θ = 90° (H1) also stands on the strip, and a metal screw or insert there would break
  the 10 mm metal keep-out (§12). The cup design has to settle all three.
* At z ≈ 5.5–6 the radiator is about 6 mm above the desk (SPEC). A metal desk still detunes it; bring-up
  B-11.2e tests that case.
* **Route:** the antenna side (θ ≈ 90°) lies in the FA lower plate's open sector centred on θ = 120° (spokes at
  60°/180°/300°, SPEC §8), so the coax rises past the plate without a plate hole. Allow bend radii (≥ 5 mm for
  1.13 mm coax) and a press-travel loop: the run between the shelf (stationary) and the spindle slot (FA, moves
  0.6 mm) is the travel loop. Keep any excess as a gentle loop away from the antenna and the rotor gap; do not
  coil it next to the antenna. The u.FL plug has to pass the spindle's lower slot (§6) **[TVP]**.

**Fitting:**

1. Clean the shelf with IPA. Apply the antenna's adhesive once, without bubbles, and do not stretch the
   flex. Keep metal paint, plating and conductive tape away from it.
2. Route the coax with ≥ 5 mm bend radius. Fix it with Kapton every 15–20 mm. It must never cross the rotor
   running gap.
3. **u.FL mating is rated for only about 30 cycles.** Unmate with a u.FL extraction tool, never by pulling the
   cable, and log every cycle. The planned sequence for a unit that gets the full RF test is:

   | When | Antenna plug mates with | Antenna plug cycles | Module receptacle cycles |
   |---|---|---|---|
   | Stage B, B-11.2 a–c | RF test pigtail (coax still free in the base) | 1 | 0 |
   | Stage D2, before the main board is lowered | RF test pigtail again, led out through the main-board Ø5 hole or round the board edge (§11.4) | 2 | 0 |
   | Stage R, after B-11.2 d/e | Module (main board lifted ≈ 10 mm) | 3 | 1 |

   A unit that skips the S11 test (§11.5) mates the module once at D2: 1 cycle each.

### 7.2 Battery

1. **Polarity first.** SPEC §6: J2 pin 1 = BAT+, pin 2 = GND, marked BAT+/GND on the silkscreen next to J2.
   Hobby JST-PH polarity is not standardised. Measure the pack lead with a DMM before every first insertion. The
   BQ25180 BAT pin has an absolute minimum of −0.3 V, so a reversed pack destroys the charger ([power research]).
2. Check the pack voltage (accept 3.5–4.2 V; do not use a pack below 3.0 V), the protection-PCB position and
   whether its length clears the cup wall.
3. **Swell gap.** SPEC §8 limits the pack to ≤ 6.0 mm. In the bay (z 2.5–9.0) it tops out at z 8.5, and the
   base board's underside is at z 9.5, which leaves the **1.0 mm** swelling gap SPEC asks for (the mechanical
   verifier asked for 0.8–1.0 mm). Check it against the maximum thickness on the pack drawing, not the nominal.
   The only part on the underside is RT1, the NTC (r 8, θ 200°): it must touch the pouch through a soft thermal
   pad, never as a hard point (architecture §8.5, R28).
4. Fix the pack with thin double-sided foam tape, not hard adhesive, so it can swell and be replaced. Long axis
   along θ = 0°/180° (SPEC §8: |x| ≤ 27.5, |y| ≤ 17.25), with the leads at the θ = 180° end.
5. Nickel is slightly ferromagnetic ([power research]). The cell's tab end is the lead end at θ = 180°; keep
   any extra nickel strip or steel hardware away from the TMAG side (θ = 270°).
6. **Battery breakout (fit at Stage B on every unit that will get B-9.9b, B-10 or B-9.8f after Stage C).** Once
   the FA lower plate and the rotor are in, J2 cannot be reached. J2 sits on the base-board top at r = 17,
   θ = 212° (SPEC §8, `layout.py`), and the pack leads come up past the board edge from the θ = 180° end. The
   pack can then no longer be unplugged or replaced by a supply. Fit the breakout lead (§4.3) between the pack
   and J2. Bring its 3-wire tail (BAT+ pack side, BAT+ board side, GND) out through a Ø3 cable port printed in
   the cup wall of a **dev cup**, at z ≈ 3–8 (below the base board), at θ ≈ 190–230° near the pack's lead end
   and J2, clear of the θ = 180° guide pin and away from the antenna side (θ ≈ 90°) **[TVP: mock-up]**. Outside
   the cup:
   * **jumper fitted:** normal operation;
   * **jumper open:** battery disconnected, for safe harness plugging (Stage C–D) and for supply tests;
   * **PPK2 ammeter mode:** VIN to the pack side, VOUT to the board side, GND to GND, in series with the real pack;
   * **PPK2 source mode or bench supply:** board side and GND, pack side left open.

   Check that the extra mated PH pair fits in the bay past the pack's lead end (x ≈ −27.5 to −33)
   **[TVP: mock-up]**.
   Leave the breakout in engineering units. On a unit that must ship without it, remove it only when the main
   board, hub and rotor come off anyway (the stop screws sit under the ring, §11.3).

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
4. **Guide and anti-lash** (detent verifier's limits for the 8 mm VSM08102):
   * Preload the carriage **0.4–0.5 N** against its vertical and tangential reference faces, on a PTFE/POM
     sliding pair. Do not go above 0.5 N with the 8 mm motor. If the guide needs more, use the 10 mm sibling
     (thrust unverified, get the drawing).
   * Fit an **anti-lash spring of ≥ 0.3 N along the screw axis, pushing toward PARK**, or a split anti-backlash
     nut instead. The magnetic radial force on the carriage reverses by up to ±0.29 N at intermediate offsets,
     so without this the M2 nut rattles across its lash. Pushing toward PARK makes the spring assist the
     retraction, which the magnet opposes whenever the rotor rests in a well.
   * Budget the worst case in either direction as 0.29 N (magnetic) + the anti-lash spring + μ × preload. With
     a 0.3 N spring and μ ≈ 0.1–0.2 that is ≈ 0.65–0.7 N, against the motor's 0.78 N rated pull-out thrust at
     500 PPS: little margin. Keep the spring near 0.3 N, step at ≤ 300–500 PPS through the loaded 0–4 mm zone
     ([detent verifier]), and treat lost steps in B-9.10d as a reason to move to the 10 mm motor.
   * Couple the slider pin-in-slot (travel axis only). The M2×0.4 lead screw self-locks, so the carriage cannot
     be pushed by hand. Move it only by stepping (bring-up B-9.10).
5. **Park before assembly:** mount the actuator on the main board, plug the motor lead into J40 and step the
   carriage to PARK (r = 21.5) on the bench (Stage A8, B-9.10a–c) before the main board is lowered over the rotor,
   so the detent magnet is not dragged across the track during assembly. J40 sits on the board's bottom side and
   cannot be reached once the board is seated.
6. **Gap:** the nominal gap is 1.0 mm, with 0.8 mm minimum including bearing play and runout; it must never
   touch. Check the sub-assembly heights with calipers. The gap cannot be reached with a feeler once assembled.

### 7.4 OLED panel into the ZIF (last electronic step)

The TC2030 SWD pads are under the OLED glass (SPEC §8). **Fit the panel only after** bring-up B-7 (SWD),
B-8.7 (MCUboot DFU and at least one serial-recovery route proven **with the TC2030 removed**) and B-9.9a (bare
boost verified at 13 V and discharged).

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

Bearing friction sets the spin time. Factory grease gives about 9–14 s spins from 10 rev/s instead of 40–120 s,
and contact seals (RSH/RS1) stop the rotor in under 1 s ([mechanical research and verifier](https://cdn.skfmediahub.skf.com/api/public/0901d1968065e9e7)).

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
5. Reject any bearing with shield rub, grit or a notchy feel. The final selection is by measured spin-down on the
   rotor (bring-up B-13). Keep the runner-up as a spare.
6. Re-oiling will be needed periodically: shields are meant for inner-ring rotation and this design spins the
   outer ring ([mechanical verifier]). Note the date in the build log.

---

## 10. Rotor assembly and balancing

### 10.1 Assembly

The order is fixed: **carrier bond → magnets → static balance on the arbor → bearing in**.

1. Check the ring: OD 70 / ID 54 / 10 mm, OD/ID concentricity ≤ 0.02 mm TIR, faces flat and square ≤ 0.02 mm
   (§8.2 magnet test too).
2. Bond the **PA12-GF carrier** (web z 17–19, r 11–27) concentric to the ring ID. **No aluminium or copper may
   rotate within 13 mm of the detent magnet's path.** An aluminium web would cost about 0.13–1.6 N·mm of eddy
   drag, against about 0.15 N·mm of bearing friction ([mechanical verifier]).
3. Install the magnets (§8) **before** balancing.
4. Weigh the ring + carrier + magnets (expect ≈ 130 g: ring 124 g, magnets 2.3 g, carrier), then
   **static-balance it on the arbor (§10.3), without the bearing.**
5. Only then press the 608 outer race into the carrier's Ø22 seat, pressing **on the outer race only**, never
   through the balls. If you use retaining compound, keep it out of the bearing. Fit the wave spring and the snap
   retainer above the outer race (model `wave_spring()`, `bearing_retainer()`). **ESD bleed (SPEC §8):** the
   touchable ring must reach GND through conductive epoxy → 608 races → spindle → the main board's plated
   H1–H3. The PA12-GF carrier insulates the ring from the outer race, so make the conductive-epoxy link between
   them now and check ring-to-outer-race continuity with a DMM. Its layout is not defined in `docs/mechanical.md`
   yet (§13 #20). Weigh the finished rotor (expect ≈ 135–140 g) **[TVP]** and use that value for I in
   B-12/B-13.

### 10.2 Balance targets

| Item | Value |
|---|---|
| ISO G2.5 at 15 rev/s for ~137 g | U_perm ≈ **3.6 g·mm** (e = 26.5 µm) |
| Target | **≤ 2 g·mm** ([mechanical research]) |
| Ring eccentricity 0.02 mm TIR | ≈ 1.24 g·mm ([mechanical verifier]) |
| One missing magnet | 1.37 g·mm |
| Correction pit Ø2 × 1 mm in 316L at r = 31 (ring bottom face) | ≈ 25 mg ≈ **0.78 g·mm** each. Calibrate by weighing chips: the drill-point cone adds mass |
| M2 brass/316 set screw in a balance hole (if provided) | ≈ 2.2 g·mm |

### 10.3 Static balance (§10.1 step 4, before the bearing goes in)

1. Mount the ring + carrier + magnets on a stepped arbor: a Ø22 h6 seat (it fills the empty bearing seat) with
   Ø6–8 ground journals.
2. Roll it on two level, hardened knife edges (or a prop balancer's roller set). Do not balance on the 608
   itself: its breakaway friction (≈ 0.04–0.1 N·mm) masks imbalances below about 4–10 g·mm.
3. Let it settle 5 times from random start angles. The heavy spot comes to rest at the bottom.
4. Remove mass at the heavy spot with shallow Ø1.5–2 mm pits on the **ring bottom face at r ≈ 31**, which faces
   the base lip and is not visible. Alternatively, add brass or 316 at the light spot. **Never add steel or
   ferrous putty.**
5. Repeat until the rotor stays put at any angle. Knife-edge sensitivity is roughly 0.5–1 g·mm **[TVP]**.

### 10.4 Dynamic trim (after full assembly, Stage E, **before** the B-13 spin-down acceptance) **[TVP]**

Use the firmware balancing assistant: the LIS2DW12 runs in high-performance mode at 400–1600 Hz, and its x/y
signals are demodulated synchronously with the encoder angle ([sensing research]). Use a single-plane trial
weight:

1. Spin to 10–15 rev/s and record the 1×/rev vibration vector V0.
2. Stick a known trial mass at a known angle on the ring bottom face, e.g. 50 mg of non-magnetic putty at r = 31
   (1.55 g·mm). Record V1. The bottom face at r = 31 is above the base lip; reach it from the side through the
   gap between the ring and the cup wall, or with a thin spatula.
3. Correction = −V0 / (V1 − V0) × trial mass. Apply it at the computed angle and verify.

The FA rides on springs and the desk, so the IMU's response to imbalance is unknown until measured.

---

## 11. Mechanical assembly order

Each stage has a gate: do not continue until the referenced bring-up step passes.

**Why this order.** In the model, the FA up-stops are M2 screws in the tops of the guide pins. Their heads sit at
r = 29, directly under the rotor ring (ring r 27–35, bottom face z 15.6; screw heads z 13.3–14.6). They can only
be fitted before the rotor goes on. The floating assembly (FA) is therefore built **in place on the base**, bottom
up, in the order of the model's exploded view: plate and spindle, rotor, hub, main board. From Stage C on, the
antenna coax also ties the FA to the base.

### 11.1 Stage A: electronics on the bench (no mechanics)

| Step | Action | Gate (`bringup.md`) |
|---|---|---|
| A1 | Inspect both boards, check resistances | B-2, B-3 |
| A2 | Base alone on a current-limited 5 V supply, then on a bench battery | B-4 |
| A3 | Main alone from bench VSYS | B-5 |
| A4 | Build and test the **bench harness** (§6). Link the boards. First linked power-up: 5.00 V at a 100–150 mA limit into the base VBUS TP, no battery. Only after that passes, a charger behind a USB meter | B-6 |
| A5 | SWD: recover, UICR, flash the bring-up image | B-7 |
| A6 | First firmware: clocks, DC/DC, SAADC, USB CDC | B-8.1–B-8.6 |
| A7 | Peripheral smoke tests that need no mechanics: QSPI, I2C, IMU, BQ25180, battery and press network, piezo, LED ring, **bare boost at 13 V** | B-9.1–B-9.9a |
| A8 | Mount the actuator on the main board: bracket (2× non-magnetic M2 at r = 17, θ 60°/120°), rail, carriage with its preload and anti-lash spring, detent magnet (§7.3). Plug the motor lead into J40. Run the driver, motor and home-sensor tests on the bench. **End at PARK with all IN low and nSLEEP low** | B-9.10a–c |
| A9 | **MCUboot and recovery gate**, with the TC2030 removed and a battery on J2. Record which recovery route works | B-8.7 |

Keep steel tools away from the main board from A8 on, because the detent magnet is fitted.

### 11.2 Stage B: base sub-assembly

1. **Feet.** The model uses three 70° arc pads at r 25–31 (DEV, to resist tipping). SPEC says point feet at r = 28.
2. **Guide pins (model).** Bond the 3 brass Ø3.0 pins, tapped M2 at the top, into the cup ears at r = 29,
   θ = 60°/180°/300°. Keep them square to the floor (≤ 0.05 mm over their length; check with a square or a dial
   indicator). Keep adhesive out of the tapped hole and off the sliding length. The ear tops (z 11.4) are the
   FA's overload stop.
3. **Base-board supports (SPEC §8).** Two M2 bosses at r = 21, θ = 90°/270°, outside the pack, matching the
   base PCB's H1/H2 (§2.2). The USB-C shell clamped in the cup wall is the third support. Fit M2 heat-set inserts
   in the bosses now. Metal must stay ≥ 10 mm from the antenna in plane (§12), which rules out a metal insert and
   screw at the θ = 90° boss: it stands on the antenna strip (§7.1, §13 #19), so follow the cup design there.
4. **Antenna** onto its shelf along y = +26 (§7.1). Before bonding, mate the RF test pigtail to the antenna plug
   (u.FL cycle 1) and run **B-11.2 a**. Bond the flex and run **B-11.2 b**. Lay the coax up its route and leave
   the pigtail mated for B-11.2 c.
5. **Battery** (§7.2): polarity check, long axis along θ = 0°/180° with the leads at θ = 180°, foam tape. Fit the
   **breakout lead** and bring its tail out through the dev-cup port (§7.2 step 6), jumper open.
6. **Base board** onto the two bosses with non-magnetic M2 screws through H1 and H2 (plastic at H1, next to the
   antenna, unless the cup design moves that support; step 3). Align the USB-C mating face with the wall
   opening: flush to +0.3 mm proud at r = 35.0, opening = receptacle + 0.3 mm ([mechanical research]). Run
   **B-11.2 c**, then unmate the pigtail.
7. Plug the battery (through the breakout) into J2 and fit the jumper. The board comes up in battery mode.
   Check VSYS at the base TP (B-9.5a). With the bench harness, link the main board once more and confirm I2C to
   the BQ25180 (B-9.2).
8. **End Stage B with the base dead:** write SHIP_RST = 0x49 (ship mode, B-9.5c) before unplugging the bench
   harness, or open the breakout jumper. VSYS must be off while the final harness is plugged in at Stages C
   and D.

### 11.3 Stage C: FA lower plate, spindle and rotor, in place on the base

Prerequisites: Stage B done and the base dead; the final harness with its base end in a housing and the other
end loose (§6); the rotor finished, statically balanced, with the bearing, wave spring and retainer fitted
(§10.1); the main board from A8 at PARK.

1. Bond the spindle (Ø8 × 1.0 wall, 316 or Ti; check with an N52 that it is non-magnetic) into the plate's Ø8
   socket (1.0 deep, 0.5 mm floor over the centre boss), square to the plate. Turn its two exit slots to the
   angles in `docs/mechanical.md`: the committed model's `SLOT_A` = 225° predates J3 at θ = 120°, J1 at
   θ = 330° and the antenna at θ ≈ 90° (§13 #15). Fit the 0.5 mm TPU or silicone dot on the centre boss (model
   `DOT_T`). Slide the POM lower spacer onto the spindle with its slot at the same angle as the lower exit slot.
2. Plug the final harness's base housing into J3. Test the harness (§6 table, final-harness column) while the
   base TPs can still be reached.
3. Drop the 3 FA springs over the guide pins into the ear pockets. Check the spring against the model's
   installed length first (§4.3).
4. Hold the plate just above the base. Pass the harness's loose end and the antenna coax (plug first) up
   through the plate's open sector centred on θ = 120°: the plate is a 3-spoke spider with spokes at
   θ = 60°/180°/300° (SPEC §8), and both J3 (θ = 120°) and the antenna side (θ ≈ 90°) open into that sector.
   Lower the plate onto the pins and springs.
5. Fit the 3 non-magnetic M2 **stop screws** into the pin tops through the plate counterbores. Snug them only,
   because the pins are bonded. The springs now hold the plate up against the screw heads.
6. **Plate check.** The plate slides freely, returns under spring force, and stops after ≈ 0.6 mm when its bosses
   land on the ear tops (the overload stop). A press at the centre and over each spoke must give an audible
   switch click before the overload stop. The pre-gap between the dot and the TS-1187A plunger is 0.15 mm
   (SPEC §8); adjust it with the dot thickness. The electrical click check is D6. If the base was left in ship
   mode, keep these presses under 1 s: a 2 s press is a ship-mode wake.
7. Lead the coax to the spindle, clear of the rotor gap. Feed the loose harness contacts and the coax plug into
   the spindle's lower side slot (SPEC z ≈ 14.5–16; model z 14.4–16.3, under the lower spacer's slot) and fish
   them out of the upper exit slot with a loop of 0.2 mm nylon line. Leave the ≥ 5 mm service loop at the base
   end, plus the ≥ 10 mm lift loop inside the bore on the first unit (§6). Check the slot fill first (§13 #15).
8. Slide the rotor down over the spindle until the 608 inner race seats on the lower spacer. The inner race is a
   slip fit on the spindle. If it binds, do not force it through the outer race or the ring.
9. Slide the spindle hub (upper spacer + flange with 3 M2 heat-set inserts at r = 6.5, θ = 90°/210°/330° to
   match the main board's plated H1–H3) onto the spindle top, with its channel lined up with the spindle's
   upper slot, and bring the harness and coax out through the channel. The hub is part of the ring's ESD path
   (spindle → H1–H3 → GND, SPEC §8), so it must connect the spindle to the inserts: a brass hub, or a defined
   conductive link in a printed one (§13 #20).
10. Spin the rotor by hand. There is no detent magnet yet, so any ticking means a ferrous part near the track or
    a magnet standing proud. Rubbing means a stack-up error; check the 0.15 mm drop-stop gap under the carrier
    lip.

### 11.4 Stage D: main board

The main board is tethered as soon as the harness or the coax is connected, and J1, J40 and the module u.FL all
face down once it is seated. Make every connection with the board held just above the hub.

1. Insert the loose harness contacts into the main-side SHR-12V-S housing, pin 1 to pin 1 (§6), and do the D1
   checks in the §6 table.
2. Hold the main board 10–20 mm above the hub, on edge or upside down, with the carriage still at PARK from A8.
   Check that the motor lead is in J40. Plug the harness into J1. Then **either**:
   * **Normal build:** mate the antenna plug to the module's u.FL (1 cycle each); **or**
   * **RF test build (Stage R follows):** fit the RF test pigtail instead. *Centre route* (preferred, because it
     keeps the board's top and rim clear): feed the pigtail's receptacle end down through the main-board Ø5
     hole, into the open top of the bore and out through the hub channel, alongside the harness and the antenna
     coax, and mate it to the antenna plug on the bowl side. This works only if the channel has room for a third
     cable (§13 #15). *Edge route* if it does not: mate on the bowl side, then tape
     the pigtail radially along the board underside at θ ≈ 200° (clear of the TMAG at 270° and the actuator at
     60–120°) and up around the board edge at r = 32. It crosses ≈ 2.4 mm above the ring's top face, which is
     acceptable for a static measurement. Use a pigtail with a non-magnetic (silver-plated copper, not
     copper-clad steel) centre conductor.

   Dress the service loops and Kapton-tape the coax, and the mated pair or pigtail, to the board underside so
   nothing hangs into the rotor's swept volume: r ≤ 12.2 below z 26.0, and the carrier web at z ≤ 19 (see §2.4
   item 8).
3. Lower the board onto the hub flange and fit 3 non-magnetic, **conductive** M2 screws (A4 or brass, not nylon)
   through the plated H1–H3 (r = 6.5, θ 90°/210°/330°) into the hub inserts: they ground the spindle and so the
   ring. The 2 M2 at r = 17 (H4/H5) already hold the actuator bracket (A8). Measure ring to TP4 GND and log the
   value (no pass limit is set yet, §13 #20).
4. **Spin check:** the rotor turns freely in FREE (carriage parked) with no ticking. A ticking rotor in FREE means
   a ferrous part near the track, a magnet standing proud, or a carriage that is not at PARK.
5. **First power-up on the final harness.** Keep the breakout jumper **open**, so the pack cannot feed a harness
   fault, and feed the USB-C receptacle from a 5.00 V bench supply at a 100–150 mA limit through a USB-C plug
   breakout. Check VSYS (4.4–4.6 V) across C6 or C2 on the top side (main TP1 VSYS is on the bottom and is now
   covered, §2.4 item 7) and TP2 +3V3 (3.30 V). Confirm that USB enumerates, I2C finds 0x19
   and 0x6A, and CHG_INT_N pulses on plug and unplug. That proves the harness signal pins. Then fit the jumper
   (if the base was left in ship mode, the USB insertion has already woken it).
6. **Click check:** press at the centre and at the rim at θ = 0°, 120° and 240°. Every press must click and pull
   BTN_N low (B-9.5d). For ~4 N preload and the 1.6 N switch, expect ≈ 4.1–4.3 N at the centre and
   ≈ 2.0–2.3 N at the rim ([mechanical research and verifier]); a re-specced spring (§4.3) changes these.
   Measure with a gram gauge **[TVP]**. Rim presses that do not click mean the rim ledge is too shallow for the
   switch travel.

### 11.5 Stage R: RF acceptance, B-11.2 d/e (only if the test pigtail was fitted at D2)

Required on the first unit of a build, and whenever the antenna, the cup, the pack or the coax route changes. On
later identical units it is optional, and B-11.3 (Stage G) is the per-unit RF gate.

1. The top is still open: no OLED, light box, diffuser or cover (the top cover is not in the antenna's near
   field). Fit a clip-on ferrite on the pigtail outside the device, ≥ 30 mm from the magnet track, and lead the
   cable away vertically.
2. Run B-11.2 d (wooden desk) and e (metal plate, hand on the dial), including the cable-touch test.
3. **Swap to the module.** Power on and confirm the carriage is at PARK: the firmware's park stall is the
   reference and HOME_N low only confirms it, because on some units the DRV5032 can also assert near full click
   (`firmware.md` §5.4). Make the base dead again
   (ship mode or breakout jumper open) and unplug USB. Remove the 3 M2 at r = 6.5. Lift the main board straight
   up ≈ 10 mm on the lift loop (§6), then tilt the module side (θ ≈ 215°) up, keeping the opposite edge from
   dropping onto the ring. Unmate the pigtail with the extraction tool and pull it out (up through the Ø5 hole
   for the centre route). Mate the antenna plug to the module (§7.1 table: plug cycle 3, module cycle 1).
   Re-dress the coax, lower the board, refit the screws and repeat D4–D6.
4. Log the u.FL cycles.

### 11.6 Stage E: mechanics-dependent tests (top still open)

In this order: TMAG field with the rotor (B-9.6c–d); actuator and home sensor on the rotor (B-9.10c–d); detent
calibration (B-12); **dynamic balance trim (§10.4)**; then spin-down acceptance (B-13), which needs the rotor
fully assembled and balanced. Keep the top open so SWD stays reachable. Supply from the real pack (jumper fitted)
or through the breakout (B-1).

### 11.7 Stage F: close the top

1. OLED bracket and panel (§7.4). Test the display (B-9.9b) on a bench supply or the PPK2 through the breakout
   (B-1).
2. Light box (white interior, opaque exterior, r 27–30), sealed to the PCB.
3. Diffuser ring (opal PMMA, r 27–30) and top cover (Ø30 OLED window, cover OD r = 32.5).
4. From here on, firmware updates go over MCUboot (USB CDC or BLE SMP), and SWD needs the top and OLED removed.
   **Write the serial-recovery route that passed B-8.7 into the unit log and on a label under the base**, for
   example "hold the dial through the 20 s reset and keep holding until the USB port re-enumerates" (route a)
   or "from ship mode: hold the dial and plug in USB" (route b). Route c (app command 0x08) needs a running app.

### 11.8 Stage G: final acceptance

1. Radiated and link checks (B-11.3). The S11 measurements (B-11.2) were done in Stages B and R and are not
   repeated here.
2. Sleep and mode currents (B-10), with the PPK2 on the breakout tail.
3. The full pass/fail table (B-14).
4. Check that the breakout jumper is fitted, then leave the unit in ship mode or shutdown (B-9.5c).

## 12. Material and fastener rules (summary)

* **Non-magnetic** within 10 mm of the track (r 27–31) or the TMAG5273: 316/A4 or brass screws, 316/BeCu
  springs, PA12/POM structure. **No carbon steel, 4xx/17-4 stainless or W-Ni-Fe weights** ([detent research]).
* **Non-conductive** (no aluminium or copper) on any rotating part within 13 mm of the detent magnet path
  (eddy drag).
* **No metal paint, plating or conductive tape** near the antenna; plastic only within 10 mm of it in-plane.
* **Conductive** (A4 or brass, never nylon) for the 3 screws through the plated H1–H3: with the hub and the
  spindle they carry the ring's ESD bleed to GND (SPEC §8).
* **Every screw tested with an N52 magnet** before it goes in.

## 13. Open items and [TVP] list (assembly)

| # | Item | Status |
|---|---|---|
| 1 | TPS22917 CT: C7 must go CT–VSYS (SLVSDW8B) (§2.4 item 3) | **Done:** `main_power.py` has C7 = 1 nF from LSW_CT to VSYS, QOD through R4 = 100 Ω to VLED, R3 = 100 kΩ ON pull-down; the OLED switch U21 has C37 = 1 nF CT–VSYS |
| 2 | SPEC's base-board bosses at r = 15 overlapped the battery footprint | **Done:** SPEC §8 and the base board use 2× M2 at r = 21, θ 90°/270° outside the pack (now along θ 0°/180°) plus the USB-C shell. The cup model must match (§2.2, §11.2) |
| 3 | Antenna did not fit on the floor at x = −26 | **Superseded:** SPEC §8 moved it to a printed shelf along y = +26 (z 5.5–6, about 6 mm above the desk). That position has its own fit problem (#19). Desk sensitivity remains (B-11.2e) |
| 4 | Coax length (§7.1) | **Done:** SPEC §5.2 and §8 specify 146153-0100 (100 mm); the -0050 is too short (§4.3) |
| 5 | Battery-to-board swell gap 0.7 mm (§7.2) | **Done:** SPEC §8 limits the pack to ≤ 6.0 mm, which leaves 1.0 mm. RT1 is the only underside part, on a soft thermal pad |
| 6 | FA up-stops | Defined in the model: guide pins bonded in the cup ears, M2 stop screws in counterbores. Their heads sit under the ring, which forces the in-place build order (§11) |
| 7 | JLC LED baking and X-ray image availability (§3) | Open |
| 8 | Harness lead part numbers and lengths, including the lift loop; 28 AWG on pins 1–4 and 8 (§6) | Open |
| 9 | Knife-edge balance sensitivity; IMU dynamic trim response (§10) | TVP |
| 10 | Folded-FPC fit under the glass (§7.4 mock-up) | TVP |
| 11 | Mated module u.FL over the rotor hub: U10 is placed per SPEC (bottom, r 14.5, θ 215°, u.FL toward the centre) with its courtyard reaching r ≈ 8.5, no margin to the flange keep-out r ≤ 8.5; the earlier model showed ≈ 41 mm³ overlap (z 24.4–26.0, r 9.5–12.2) (§2.4 item 8) | **Open: re-run the clash check on the placed board before ordering** |
| 12 | Bearing "wave-spring preload" (SPEC §8): a single 608 cannot be axially preloaded by a spring without a reaction against the stationary side, and in the model the spring only retains the outer race. The rotor weight (≈ 1.35 N) exceeds the ±0.7 N detent pull, so the balls should stay loaded anyway **[TVP]** | Restate in SPEC/model |
| 13 | FA springs: the model's installed length (≈ 2.65 mm) does not match the spring spec (3.56 mm) and leaves only ≈ 0.2 mm to solid (§4.3) | Re-spec before buying |
| 14 | J2 location | **Done:** SPEC §8 and the board put J2 on the base-board top at r = 17, θ = 212°, with BAT+/GND silk. It is still buried after Stage C, hence the breakout (§7.2) |
| 15 | Spindle and hub exit slots (3.5 × 1.5–1.9 mm) are too small for the 12 leads (28 AWG on the five power leads) plus the coax, and leave no room for the RF test pigtail (§6, §11.4). The committed model's slot angle (225°) predates J3 at θ 120° and J1 at θ 330° | Widen and re-angle before printing |
| 16 | Magnet pocket depth: SPEC and the model say 2.05; ≥ 2.20 is needed to set Ø2×2 ±0.05 magnets flush (§8.1) | SPEC change |
| 17 | The model's Ø2 "ship-mode/reset access" hole under the switch is covered by the pack (SPEC: \|x\| ≤ 27.5, \|y\| ≤ 17.25 spans the centre), so it can only act as a vent | Open |
| 18 | u.FL plug through the spindle's lower slot; RF pigtail receptacle through the Ø5 hole and hub channel (§4.3, §7.1, §11.4). The plate's Ø2.2 coax hole is gone: the coax rises through the spider's open sector | TVP on the mock-up |
| 19 | Antenna shelf fit (§7.1): centred on y = +26 the strip's corners reach r ≈ 35.1 (cup wall r 33.4); with the corners at r ≤ 33 its inner edge is ≈ 1.75 mm from the pack, not ≥ 4 mm; the base-board boss at r 21, θ 90° (H1) stands on the strip, inside the 10 mm metal keep-out (§12) | Open (SPEC and cup design) |
| 20 | Ring ESD bleed path (ring → conductive epoxy → 608 races → spindle → H1–H3 → GND, SPEC §8): the PA12-GF carrier insulates the ring from the outer race, a printed hub does not connect the spindle to the screws, and no pass value is set (§10.1, §11.3, §11.4) | Open (define in `docs/mechanical.md`) |
| 21 | Base-board RT1 on the bottom: two-sided base PCBA for one 0402 part, or hand-fit; thermal-pad material and thickness (§3.1, §7.2) | Open (order decision) |
| 22 | LED-cavity silk: the stock LED footprints' silk marks (D101–D148) and R42's reference lie in r 27–30 (§2.1) | Open, before ordering |
| 23 | L20 courtyard reaches r ≈ 19.9, ≈ 7 mm in plane from the r = 27 edge of the track annulus (§2.4 item 2) | Check before ordering |

Source abbreviations used above: "[x research]" and "[x verifier]" refer to the subsystem research and its
independent verification, which SPEC.md was built from. Where the two differ, the verifier's corrected value is
used. Datasheet links are inline where a number depends on them.
