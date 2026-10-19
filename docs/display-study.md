# Display study: larger round touch display (rev B options)

This document combines three research sweeps (panels, MCU and display interface, mechanical and NFC). Each sweep was independently checked, and every correction from those checks is applied here. Prepared 2026-10-19. No repository files were changed. Rev A continues with the SSD1351 OLED. This study covers the next revision.

Two labels are used throughout:
- **(unverified)**: not confirmed from a primary source.
- **(estimate)**: my own calculation or model, not a measurement.

Everything carrying either label needs a bench check before the rev B layout is frozen.

## 1. Short answer

- **The largest round touch display that fits inside the LED ring** is a **1.75 in 466×466 AMOLED with built-in (on-cell) capacitive touch**. The panel is Huaxin H0175Y003AMT003, with a CO5300 driver chip.
  - Its pixels span Ø43.76 mm, against today's Ø30 window. That is **2.3× the visible area**.
  - Between the last pixel and the glass edge there is 2.0–2.6 mm of black ink. With a clear light guide, the LED glow can start right at the glass edge.
  - No larger round touch AMOLED was found. The next sizes up are LCDs, which cover the LED ring and block NFC.
- **Recommendation: configuration A.** Keep the nRF52840 and drive the 1.75 in panel over SPIM3 at 32 MHz.
  - Small UI elements update at 30–60 fps.
  - Full-screen redraws run at about 9 fps in full colour, 18–22 fps in 256 colours or grey, and about 37 fps in 8 colours.
  - The LED ring carries the fast spin motion.
  - Battery life stays about where it is today (estimate), and the parts cost is about the same.
- **Configuration B** (nRF52840 replaced by an nRF54LM20A with a quad display link) is the right upgrade if smooth full-colour, full-screen animation at 30+ fps is a must. However, no nRF54LM20A module with an external-antenna connector is shipping yet. Prototype it on a development kit in parallel.
- **Configuration C** (keep the nRF52840 and add an RP2350 graphics co-processor) gives 30–60 fps now. The cost is a second firmware image and roughly a third to a half less battery life at the desk (estimate).
- **NFC** in all three configurations: a 4-turn coil printed on the display's support plate around the panel, with a thin ferrite sheet under it.

## 2. Your notes, answered

- **NFC.** Rev B keeps the nRF52840's built-in NFC tag, so the phone reads the dial.
  - What the dial hands the phone (a URL, a contact card, a Wi-Fi login, an app launch) can be changed from the phone app over Bluetooth or from the dial's own touch menu.
  - Having the dial *read* a card or tag needs a separate reader chip on the same coil, for example the ST25R3916B, which can also act as a tag. That is the "more work" option. I suggest deferring it, optionally with board space reserved now (open question 5).
- **Plastic, not aluminium.** Agreed. Plastic also suits the new parts: a metal ring around the glass would act as a shorted turn for the NFC coil and would disturb the touch sensor at its edge.
- **Clicking the whole ring like a Nest.** Rev A already works this way.
  - The spinning steel ring rides on the floating assembly. Pressing down on the ring's top rim, the glass or the LED ring moves the whole top 0.45 mm down onto the one centre switch.
  - The press force is about 4.6 N at the centre and about 1.9–2.4 N at the ring's top rim (mechanical.md §8).
  - With touch, the firmware can also tell a press with a finger on the glass from a press on the ring, where the glass sees no touch. So one switch gives two kinds of click, and taps and swipes on the glass are a third kind of input.
- **Is the screen limited, and what about the bezel?** Yes, today's screen is small: a 1.5 in square OLED seen through a Ø30 window. All three configurations replace it with the 1.75 in round touch AMOLED described above, and its glass becomes the top surface. Seen from the centre outward:
  1. pixels out to r 21.9 mm;
  2. about 2.0–2.6 mm of black ink on the stock glass;
  3. the LED glow ring (r 24.6–30 mm with a light guide);
  4. a narrow black band out to r 32.5;
  5. the ring's rim.

## 3. What all three configurations share

### 3.1 Display and touch parts

The panel is the Huaxin H0175Y003AMT003 family: 1.75 in, 466×466, 273 ppi, 700 cd/m², with the CO5300 driver and on-cell touch. It has a 31-pin FPC (flexible printed cable). A power chip on that FPC (BV6802W) makes the AMOLED supply rails, so the 13 V boost goes away.

| SKU | Touch IC | Cover glass | Black ink width (glass edge to pixels) | Price, qty 1 | Notes |
|---|---|---|---|---|---|
| Viewe ALL-UEOL018VG-RA31-A001A (datasheet name ALL-UEOL018WV-RA31-A001A) | CST9217. No datasheet found (unverified). Drivers exist from Espressif and ESPHome. | Ø48.16 × 1.1 (edge at r 24.08) | 2.0 mm to the touch area, about 2.2 mm to the pixels | US$14.99 (list price 16.99) | Same touch IC as the Waveshare reference board. Its drawing says the touch I2C runs at 1.8 V. Confirm the order code with Viewe. |
| TailorPixels TOH175XRT-02CG | CST820B | Ø48.96 × 1.1 (edge at r 24.48) | 2.4 mm to the touch area, 2.6 mm to the pixels | US$9–17 | Its drawing says the touch I2C runs at 2.8 V. It has a grounded steel stiffener on the FPC, which is slightly worse for NFC. |
| DisplayAMOLED ESHX0175Y003AMT002/003 | CST9217 | Ø48.96 | as above | US$8.7, minimum order 1000, 4–6 weeks | Volume source only. |
| Waveshare ESP32-S3-Touch-AMOLED-1.75 (development board) | CST9217 | Ø48.96 | as above | US$29.99–39.99 | Reference schematic and working start-up code. It ties VBAT, VCI, IOVCC and VCI_EN to 3.3 V and mates the panel tail with a Hirose FH26-31S-0.3SHW ZIF connector. |

Key numbers, from the vendor drawings and confirmed by the checks:

| Item | Value |
|---|---|
| Pixel area | Ø43.76 |
| Touch area | Ø44.16 |
| Bare panel | 45.93 × 46.35 × 0.8 |
| Module total thickness | 2.07 (Waveshare drawing: 2.05) |
| Glass surface compressive stress | ≥ 450 MPa |
| Ball-drop rating | a 64 g ball from 30 cm (0.19 J) passes |
| Operating temperature | −20 to +70 °C |
| Current, Viewe and TailorPixels | 75 mA typical on a full red screen at 60 Hz (supply rail not stated); 400 µA standby |
| Current, Huaxin | 30 mA typical, 60 µA standby (no conditions stated) |

The drawings settle several facts that affect the design:

- **No reverse scan.** The CO5300's scan-direction register (MADCTL) has only mirror bits, with no row/column exchange, and the drawing says reverse scan is not supported. So the direction in which the FPC leaves the panel decides which way is "up". Rotating the image in software on the nRF52840 is too expensive, so choose the FPC exit so that the panel's native "up" is the device's "up" (open question 3).
- **The folded tail.**
  - The 31-way tail folds 180° flat behind the panel. Folded, it is about 31 × 17 mm.
  - It carries a 1.2 mm-tall component area holding the BV6802W and its inductor. On the TailorPixels part it also has a grounded steel stiffener.
  - The separate 6-way touch tail plugs into it.
  - Its contact end has staggered pads at 0.3 mm pitch, and Waveshare mates it with a Hirose FH26-31S-0.3SHW ZIF. Both points come from the drawing and Waveshare's choice of mating connector; confirm them on a sample.
  - The drawing names the connector OK-F302-31115, which has no datasheet.
- **Glass finish.** The stock glass is listed as 无一体黑 (no "integrated black" finish). The ink border and a black screen may therefore not look like one seamless black. If the seamless look matters, ask the vendor for integrated-black glass.
- **Panel supplies.**

  | Supply | What it feeds | Range |
  |---|---|---|
  | VBAT | BV6802W power chip | 3.7–4.5 V in the pin tables; 3.3–5.5 V in both vendors' application circuits; Waveshare runs it at 3.3 V |
  | VCI | driver chip | 2.4–3.3 V (2.7–3.6 V in the application circuits) |
  | IOVCC | logic I/O | 1.65–3.3 V |
  | Touch supply | touch IC | 2.8–3.3 V |

  The BV6802W datasheet was not found (unverified).
- **Touch I2C voltage.** The drawings say 1.8 V (Huaxin and Viewe) or 2.8 V (TailorPixels), but Waveshare drives the touch I2C from 3.3 V GPIO. Confirm with the vendor, and lay out an optional level shifter.
- **Partial updates.** The CO5300 frame memory holds a whole frame (480×480×24 bit, compressed 3:1), so only changed areas need to be sent. Update windows must start on an even column and row and have an even width and height.

### 3.2 Top stack, bezel and LED ring

Heights (z) are in mm from the desk, as in SPEC §8.

| z (mm) | Part | Notes |
|---|---|---|
| 30.7 | Main-board top | Panel connector (see §3.4), M4 nut (30.7–32.2), TC2030 pads, DRV5032, NFC tuning parts. |
| 33.26–33.5 | Ferrite sheet, TDK IFL05K 0.2 mm (0.24 mm with adhesive) | Disc r ≤ 26.6, with a cutout for the panel tail and a notch over the TMAG5273 (§3.3). |
| 33.5–33.9 | Display support plate: 0.4 mm FR4, white solder mask, r ≤ 26.6 | Carries the NFC coil on its rim. It gives the panel continuous flat support everywhere except over the tail. |
| 33.93–36.0 | 1.75 in panel module, glass on top | The glass is now the top surface. The Ø30 window and the Ø33 cover glass go away. |
| 31.6–34.2 | Light box, r 27–30 | Unchanged. |
| 33.9–36.2 | Clear PC light-guide ring with a diffusing top, from r 24.6 (r 24.2 with the Viewe glass) to r 30 | Replaces the opal diffuser. It stands 0.2 mm proud of the glass, so a face-down drop lands on plastic, not on the glass edge. |
| 34.2–36.2 | Top ring, black PA12, r 30–32.5 | Replaces the top cover and its window. |

The device height becomes 36.2 mm, 0.2 mm more than today, because of the proud edge. Keeping 36.0 means dropping the whole stack 0.2 mm, which would leave only about 0.1 mm between the tail's component area and the M4 nut.

Seen from above, from the centre outward:
1. pixels out to r 21.9;
2. 2.0–2.6 mm of black ink out to the glass edge;
3. LED glow from r 24.6 (24.2 with the Viewe glass) to r 30;
4. black out to r 32.5;
5. the spinning ring's rim.

Further points:

- **LEDs.** Unchanged: 48 × WS2812C-2020 at r 28.5, light box r 27–30.
- **Light-guide evenness.** Whether the glow is even over r 24.6–27 is untested. The fallback is the plain opal diffuser at r 27–30 with the inner part black. That makes the black band r 21.9–27, i.e. 5.1 mm.
- **Later, for a seamless Nest-like top.** One custom Ø62 × 1.0 mm strengthened glass covers the whole top. It carries the touch sensor and a printed mask: black, plus a translucent band for the LEDs. This needs custom glass and touch tuning from the vendor (cost and minimum order unverified). Do it after the stock-glass build works.
- **Support plate.** Radius r ≤ 26.6, not 26.8, to leave 0.4 mm to the light-box wall. It needs its own locating feature.
- **Pressing on the glass.**
  - A centre press (4.64 N) now goes through the glass into the panel. The panel therefore needs continuous flat support with no point contacts. Over the tail, support it through the tail's stiffener and a foam pad.
  - Peak glass stress for a 20 N centre press on the stock glass, held only at its rim, is 23 MPa (estimate, assuming a 5 mm load radius). The glass's surface compression is ≥ 450 MPa.
- **Mass and click force.** The floating assembly gains about 4–7 g (estimate). The centre click force drops from 4.64 N to about 4.57–4.60 N, less than 2 %.

### 3.3 NFC coil

- **Where.** A 4-turn coil is printed on the rim of the support plate, around the panel, at about r 24.6–26.3, under the glass's black ink. The copper stays ≥ 0.3 mm from the plate edge.
  - This follows Apple patent US11205832B2: a coil along the periphery under the display, with ferrite between it and the circuit board.
  - The two coil ends reach the main board's J11 pads (current SPEC §4) through two spring contacts.
- **Why a ferrite sheet.** The main board's ground plane, 3.5 mm below the coil, is the main thing shielding it.
  - Without ferrite, the coil is about 1.41 µH and couples to a phone 28–39 % as well as it would in free space.
  - A 0.2 mm TDK IFL05K sheet under the coil (µ′ 50, µ″ 1.3 at 13.56 MHz) raises that to 81–93 % in an infinite-sheet model. That figure is an upper bound.
  - The real disc extends only 0.3 mm beyond the coil and has a tail cutout and notches. Expect somewhere between 40 and 90 % (estimate).
  - Avoid the lossy ferrite grades (IFL10M, IFL16).
- **Ferrite notches.**
  1. **Over the TMAG5273** (r 29, θ 270°, about 5 mm below the sheet). SPEC's 10 mm rule means no ferrite within about ±17° of θ 270° at r 24–27 (estimate; check in CAD).
  2. **Optional, over the detent-magnet path** (θ ≈ 75–105°).
     - The detent magnet puts 6.6–7.5 mT in-plane on the sheet there. That is enough to partly saturate it and shift the tuning by up to about 1.5 % between click and free-spin modes (estimate).
     - The sheet may also bias the DRV5032 home sensor, whose margin is already thin (risk R35).
     - Build plates with and without this notch and compare.
  3. **Magnet track distance.** The ferrite edge is also about 7.7 mm from the magnet track, where SPEC asks for 10 mm. The track's field there is only 0.12–0.14 mT. Check for cogging with the 50-rest test.
- **Tuning.**
  - Each NFC pin needs Ctune = 2/((2π·13.56 MHz)²·L) − Cp − Cint (nRF52840 PS), with Cint ≈ 4 pF. That is about 95–110 pF C0G per pin with the ferrite and about 190 pF without. Rev A's 180 pF capacitors (C16/C17) match the no-ferrite case.
  - Fit one capacitor per pin, plus a not-fitted (DNP) trim-capacitor footprint and a DNP damping-resistor footprint. Keep the two pins matched.
  - Tune on the finished unit with Nordic's network-analyser method. Tune slightly high, because a phone at contact pulls the frequency down.
- **Metal in the display is the biggest unknown.**
  - The drawings show no metal back plate, only Poron foam. Copper or graphite back films are common, though, and are not always drawn.

  | Display back layer | Effect on the coil (estimate) |
  |---|---|
  | ≥ 10 Ω/sq | no loss |
  | 3 Ω/sq | coil Q drops to about 34–38 |
  | ≤ 1 Ω/sq, or a copper foil | coupling falls to 19–58 % |

  - The folded tail also sits inside the coil, with its ground copper, the power chip's inductor and the TailorPixels steel stiffener. The model gave a loss of 2–9 percentage points, but it assumed less copper area than the real tail has, so the real loss is probably larger (unverified).
  - Ask the vendor for the back-layer stack, and measure a sample coil with the real panel on top.
- **Read range.** The nRF52840 needs only 1.2 V peak across the coil to detect a phone's field. Under an assumed phone field, detection holds to about 4 cm. The real read range depends on the phone; expect contact to 2–4 cm (unverified). Measure with an iPhone and an Android phone.
- **Firmware and hardware checks.**
  - Remove `nfct-pins-as-gpios` from every image, including MCUboot.
  - A board already flashed with that setting needs ERASEUICR (or a full erase) over SWD, because a firmware update cannot set the UICR NFCPINS register back.
  - Check that the +3V3 rail tolerates the reverse current a strong field can push into the supply (PS §6.14.11; unverified for the RT9080).

### 3.4 Connecting the panel

With the tail folded as the vendor intends, its contact end sits about 2.5–3 mm above the main-board top. There are two ways to bridge that gap. Decide with a sample panel in hand.

1. **Stock tail.**
   - The support plate (or a small riser) carries a 31-pin 0.3 mm ZIF (FH26-31S-0.3SHW or equivalent) where the contact end lands.
   - A board-to-board connector pair of about 2.5 mm mated height carries the signals down to the main board (part to be selected).
   - The plate and the ferrite need a cutout of about 32 × 18 mm for the tail's components, which puts the tail's metal inside the NFC coil.
2. **Longer tail** (a custom FPC length from the vendor; minimum order unverified).
   - The tail loops down through a slot at the panel edge and plugs into a ZIF on the main-board top.
   - The plate and ferrite stay full discs. That gives the panel better support and puts the tail's metal behind the ferrite.
   - The touch tail may also need to be longer.

Either way, three constraints apply:
- The panel power chip's inductor on the tail must stay ≥ 10 mm from the TMAG5273 (SPEC §7/§8). That rules out an FPC exit near θ 270°.
- The tail's 1.2 mm component area must clear the M4 nut. The margin is about 0.3 mm.
- The SPI lines at 32 MHz must stay short and low in capacitance. The CO5300 needs clock edges of ≤ 3.5 ns (20–80 %). An nRF52840 high-drive pin manages about 2.5–3.0 ns at 15 pF and about 3.2–3.75 ns at 25 pF. Check on a scope.

### 3.5 Panel power wiring

- **VBAT (the panel's power chip)** comes from VSYS through the existing TPS22917 load switch U21 (net OLED_VCC_EN, renamed DISP_VBAT_EN).
  - Do not feed it from the +3V3 LDO: a full-white screen could draw 100–200 mA (estimate).
  - The pin table does not guarantee the panel below VSYS ≈ 3.3–3.7 V. Bench-test brightness and brown-out at 3.0–3.4 V.
  - If the panel fails that test, add a small buck-boost converter that makes about 3.8 V (part to be selected). Its inductor must also be ≥ 10 mm from the TMAG.
- **VCI, IOVCC and the touch supply** come from +3V3. That adds about 5–10 mA (estimate); the LDO is sized for ≥ 200 mA. Logic runs at 3.3 V, the top of the CO5300's 1.65–3.3 V I/O range, as on the Waveshare board.
- **VCI_EN** goes to a GPIO. The vendor circuits tie it to VCI, but firmware control lets the power chip be shut off cleanly.
- **Sleep sequence.** Display off, sleep in, VCI_EN low, VBAT switch off, then CO5300 deep standby (2 µA on VDDI + 1 µA on VCI).
  - The image is lost. Waking takes a reset of ≥ 3 ms, re-initialisation, a 120 ms sleep-out wait and a redraw. That is about 180–230 ms to the first image (estimate), similar to today's 200–400 ms.
  - The touch IC goes into its sleep mode. CST816-class chips draw under 1 µA there; the CST9217 and CST820B figures are unverified.
- **Brightness** is set with the brightness command (DCS 51h). It sends no pixel data, so fades cost nothing on the SPI link.
- **Low-power display modes.** Idle mode (39h, reduced colours) and partial-display mode (30h/31h) can cut power for a dim clock face (savings unverified).

### 3.6 Touch

- **Bus.** On-cell capacitive touch on I2C, plus INT and RST lines.
  - If the vendor confirms 3.3 V I/O, it shares TWIM1 with the LIS2DW12 (address 0x19) and the BQ25180 (0x6A). Third-party drivers give the CST9217 address as 0x5A and the CST820 family as 0x15 (unverified), so there is no clash.
  - Otherwise, put the touch IC on its own 1.8 V segment behind a 2-channel level shifter (PCA9306 class).
- **Firmware.**
  - A Zephyr input driver: port the CST9217 driver. The CST820B may work with Zephyr's Hynitron driver (unverified).
  - Tap, swipe and long-press gestures, with edge and palm rejection.
  - Ignore touch while the NFC field is present (FIELDDETECTED).
  - Combine the touch state with BTN_N to tell a glass press from a ring press.
- **Risks.**
  - The WS2812 data line (800 kHz) runs 6.4 mm outside the touch area. Interference has not been tested.
  - Static discharges now land on the glass and the touch IC. Add an optional ESD protection array on the touch lines at the connector.

## 4. The three configurations

### 4.1 Side by side

| | **A: nRF52840 + 1.75 in AMOLED (recommended)** | **B: nRF54LM20A + 1.75 in AMOLED, quad link** | **C: nRF52840 + RP2350 graphics co-processor + 1.75 in AMOLED** |
|---|---|---|---|
| Display and touch | Viewe ALL-UEOL018VG-RA31-A001A (CST9217) or TailorPixels TOH175XRT-02CG (CST820B) | same | same |
| Visible area and bezel | Ø43.76 of pixels (2.3× today's area); 2.0–2.6 mm of black ink, then LED glow from r 24.2–24.6 (fallback: 5.1 mm black) | same | same |
| LED ring | LEDs unchanged; clear light guide r 24.6–30 | same | same |
| NFC | 4-turn coil on the support plate, r 24.6–26.3, IFL05K ferrite; nRF52840 NFC on P0.09/P0.10 | same coil; nRF54LM20A NFC (different pins) | same as A |
| MCU or module | Raytac MDBT50Q-U1MV2 (unchanged) | Raytac AN54LM-U20A (u.FL), Ezurio BL54LM20A/B (MHF4) or Fanstel BM20E/M; none shipping yet | MDBT50Q-U1MV2 + RP2350A (or RP2354A with 2 MB flash in the package; availability unverified) |
| Display link | SPIM3, 1 data line, 32 MHz, CO5300 framing of 0x02 + 24-bit address | sQSPI (software peripheral on the RISC-V core), 4 data lines, 32–64 MHz, CO5300 quad write (0x32) | RP2350 PIO quad SPI at ≤ 50 MHz (CO5300 write cycle ≥ 20 ns); the nRF52840 sends commands to the RP2350 on SPIM2 at 8 MHz |
| Full-screen frame, full colour (RGB565) | 108.6 ms (9.2 fps); 88 ms when clipped to the circle (11.4 fps); tears | 27.1 ms at 32 MHz (37 fps, tear-free with TE); 13.6 ms at 64 MHz; the real rate depends on rendering speed on the 128 MHz M33 (unverified) | 17.4 ms at 50 MHz (57 fps on the wire) from a full 424 KB frame buffer; 30–60 fps (unverified) |
| Full-screen frame, 256 colours or grey (8-bit) | 54.3 ms (18.4 fps); 44 ms clipped (22.7 fps) | not needed | not needed |
| Full-screen frame, 8 colours (RGB111) | 27.1 ms (36.8 fps); tear-free at 30 fps with TE | not needed | not needed |
| Small widgets (e.g. a 160×64 readout, a 60×200 pointer) | 5.1–6.0 ms each: 30–60 fps | < 2 ms | drawn locally on the RP2350 |
| Desk battery, typical day | about 26–37 days (today 28–29) | about 26–36 days | about 14–23 days |
| Game battery | about 8.0–9.2 h (today 8.6 h) | about 7.8–9.0 h | about 6.4–8.1 h |
| Parts cost per unit vs rev A | about −$20 to +$19 (roughly neutral) | A plus the module price difference (not published) | A plus about $3–6 |
| Sourcing risk | medium: panel only direct from Chinese vendors, one maker | high: modules not shipping, certification only "intended" | medium: as A; RP2350 widely stocked |
| Firmware risk | medium: CO5300 SPI driver backport, low-colour patch, tight RAM | high: port to nRF54L (DPPI/GRTC, LEDs over TDM or SPI, sQSPI with an MSPI CO5300 backport) | high: second firmware image, command protocol, update path |
| When | rev B | a later revision, or rev B if modules ship before the layout freeze | only if full-screen full-colour motion is needed now |

Notes on the table:
- TE is the panel's tearing-effect signal, which marks the start of each panel refresh so writes can be timed against it.
- All frame times are time on the wire. Real throughput should be ≥ 97 % of that for 8–32 KB transfers (estimate, unverified).
- Battery figures are estimates; see §5.

### 4.2 Configuration A: keep the nRF52840 (recommended)

**How the UI gets its speed.**
- Draw static screens once in full colour (RGB565). Update only what changes (readouts, pointer, labels) as small windows at 30–60 fps.
- For full-screen motion, switch the panel's colour mode (COLMOD): 8-bit grey or RGB332 at 18–22 fps, or 8-colour RGB111 at about 37 fps.
  - RGB111 is tear-free at 30 fps when writes are timed to TE.
  - The CO5300 datasheet documents these modes with the 1-wire framing, but they have not been bench-tested. The Zephyr driver supports only RGB565 and RGB888, so it needs a patch.
- Let the 48-LED ring carry the fast spin motion. The screen shows the result, the pointer and the counts.
- Use the brightness command for fades.
- Pre-rendered wheel frames can stream from the QSPI flash. About 36 frames in RGB565, or 72 in 8-bit, fit in the 15 MB littlefs area.
- The nRF52840's QSPI peripheral cannot drive the panel. It splits every write into flash-sized pages, and the CO5300 carries its command in the address, so every page after the first arrives as the wrong command (verified).

**Resources.**
- **SPI clock.** SPIM3 moves from 16 to 32 MHz (decision D6).
  - The SPIM2 fallback at 8 MHz is useless at 466×466 (2.3 fps). So SPIM3 errata 174, 193, 195 and 198 must all be handled.
  - At 32 MHz, the clock's harmonics land in the Bluetooth band only at 2432 and 2464 MHz. At 16 MHz they land every 16 MHz.
- **RAM.**

  | Use | Size |
  |---|---|
  | LVGL draw buffers, in RAM blocks 0–7 (anomaly 198) | 2 × 32 KB |
  | LVGL heap | 48 → 64 KB |
  | NFC and touch | about 4 KB |
  | **Total** | **about 232 KB of 256 KB** |

  - The draw buffers stay out of the large 192 KB RAM block because, per firmware.md, the anomaly-198 workaround stalls the CPU on any access to the buffer's block.
  - That leaves roughly 8–25 KB free (estimate), which is tight.
  - Ways to free RAM: 8-bit render buffers, keeping the heap at 48 KB, or dropping one USB CDC serial port.
  - Check a real map file from a development-kit build before committing.
- **Display driver.**
  - Zephyr's `chipone,co5300` driver on a plain SPI bus exists only in Zephyr main (4.5.0-rc2). It is not in the 4.3.0 or 4.4.0 releases, and NCS's copy supports MIPI-DSI only, so copy it into the project.
  - Patch its hard-coded +6 column offset (check what this panel needs).
  - Add the even-coordinate rounding and the low-colour modes.
- **Pins.** The rev A NFC change leaves P0.28, P0.29, P0.31 and P1.05–P1.07 free.

  | Signal | Pin |
  |---|---|
  | SPIM3 SCK / MOSI / CS | P0.13 / P0.14 / P0.15 |
  | Optional read line (the panel's SIO1/DCX; DC is not used by the 0x02 framing) | P0.16 |
  | Panel reset | P1.01 |
  | VBAT switch | P1.02 |
  | TOUCH_INT | P0.28 |
  | TOUCH_RST | P0.29 |
  | TE | P0.31 |
  | VCI_EN | P1.05 |
  | Spare | P1.06, P1.07 |

### 4.3 Configuration B: nRF54LM20A

- **The chip** (Nordic product page):
  - 128 MHz M33, plus a 128 MHz RISC-V core that runs the sQSPI software peripheral;
  - 512 KB RAM, 2 MB non-volatile memory;
  - high-speed USB and NFC;
  - transmit power +8 dBm (CSP package) or +7 dBm (QFN);
  - currents: 5.0 mA transmitting at 0 dBm, 3.3 mA receiving, 0.7–4.3 µA asleep.
- **Display.**
  - sQSPI quad runs from 32 MHz (27 ms per RGB565 frame) up to 64 MHz. Nordic's porting guide covers 64 MHz, which needs extra-high pin drive.
  - With 512 KB of RAM, two draw buffers of a tenth of the screen each (2 × 43 KB) fit with margin.
  - The CO5300 needs the same driver backport, for its MSPI bus path.
  - Nordic documents the sQSPI quad command modes as "implemented but not tested".
- **What it costs.**
  - There is no hardware QSPI. The W25Q128 moves to an SPIM at 32 MHz on a single data line, or the assets move into the 2 MB internal memory.
  - The product page lists TDM but no I2S. The WS2812 LED driver moves to TDM or to an SPI-based driver (unverified).
  - The encoder's PPI chain moves to DPPI/GRTC.
  - New board files, pin map and footprint.
- **Modules.** None can be bought yet.
  - Raytac AN54LM-U20A: u.FL, 9.9 × 13.6 × 2.05 mm, 66 GPIO, certification "intended", no stock. Raytac also lists the AN54LMQ-U20A.
  - Ezurio BL54LM20A 453-00585 and BL54LM20B 453-00672: MHF4, early preview, zero stock.
  - Fanstel BM20E and BM20M: sources disagree on which one has the external-antenna connector; Mouser expects them around November 2026.
  - The nRF54H20 is restricted to selected customers and its Ezurio module is end-of-life.
- **Prototype now** on an nRF54LM20 DK (about $39–58) or a Seeed XIAO nRF54LM20A (about $16). Use DK v0.5.4 or later: the early v0.3.4 (Eng-A) DKs lock up in sQSPI tests.
- **Chips that do not help.** The nRF5340 still has a 1-wire 32 MHz link and transmits at only +3 dBm. The nRF54L15 has sQSPI but no USB and no more RAM.

### 4.4 Configuration C: RP2350 graphics co-processor

- **How it splits the work.**
  - The nRF52840 keeps Bluetooth, NFC, USB, the sensors, the LEDs and the detent.
  - An RP2350A renders the UI and drives the panel over PIO quad SPI. Its 520 KB of RAM holds a full 466×466 RGB565 frame.
  - The nRF sends screen state and assets over the spare SPIM2 plus an interrupt line.
  - Precedent: the Waveshare RP2350-Touch-AMOLED-1.43 drives a 466×466 CO5300 panel over QSPI, with FT6146 touch ($23.99–28.99).
- **What it adds to the board.**
  - The RP2350A plus 2–16 MB of QSPI flash. Alternatively an RP2354A with 2 MB of flash in the package: about +$0.20 at launch, availability and datasheet unverified.
  - A 12 MHz crystal and an inductor for its core regulator (unverified here). The inductor must be ≥ 10 mm from the TMAG.
  - A load switch to power-gate it, and SWD pads.
  - Board area under the panel, which the tail also wants.
- **Power.** About +15–30 mA whenever the screen is on (unverified), which causes the battery hit. Power-gated, it draws almost nothing when the screen is off.
- **Firmware.** A second firmware image (Pico SDK, or Zephyr on the RP2350), a command protocol, and an update path through the nRF (how is unverified).
- **Other co-processor or single-chip options were rejected:**
  - ESP32-S3: more power.
  - Ambiq Apollo4/510: no NFC, 1.8 V logic, BGA package, own radio certification.
  - SiFli SF32LB52: no NFC. A Zephyr port exists, but its LCD driver has no QSPI yet.
  - Renesas DA1469x: integrated antenna only, no NFC.

### 4.5 Panels considered and set aside

| Panel | Why not |
|---|---|
| 1.43 in 466×466 AMOLED (TailorPixels TOH143XRT-01CG2, CST820, $7.80–13.20) | Pixels Ø36.35, only 1.6× today's area. It leaves an 8.8 mm black band to the LEDs unless they move inward. A good low-cost fallback. |
| 1.5 in 466×466 AMOLED (Viewe ALL-UEOL015WV-RB24-A021A, Ø38.3 active area, touch) | Seen only in Viewe's catalogue table (unverified). |
| 1.39 in 454×454 AMOLED (DisplayModule DM-OLED14R-678N, SH8601A + TMA525B, $59.90) | Small and about 4× the price. It does have the best documentation and true 4-wire SPI. |
| 1.85 in 360×360 IPS LCD (Waveshare SKU 35079 with CST816S; Viewe UE018HV-RB39-A002 with CST816T) | Its Ø55 touch glass overlaps the LED diffuser. The backlight draws 60 mA whenever it is on, and blacks glow. The Waveshare module is wired for QSPI only. |
| 1.8 in 360×360 IPS LCD (DisplayModule DMKDI0180F5NA, no touch, $19) | Needs a custom touch lens; has an LCD backlight. |
| 1.28 in 240×240 IPS LCD, GC9A01 + CST816S (Waveshare, $18.99) | Barely bigger than today (+8 % in diameter). Lowest risk and 35 fps. |
| 2.1 in 480×480 LCD, ST7701S (Adafruit 5792 and others) | Its active area alone reaches the LED ring. It needs an RGB parallel bus, which the nRF52840 lacks, and a 12.8 V backlight supply. |
| Round memory-in-pixel LCDs | No touch version found, and not the AMOLED look. |

## 5. Battery-life impact

Rev A figures come from architecture.md §8, with 900 mAh usable. The new figures are estimates (unverified), built on these assumptions:

| Component | Assumption |
|---|---|
| Panel at the desk | 8–18 mA (dim, dark UI, about 15 % of pixels lit) |
| Panel in the game | 25–40 mA (about 30 % lit) |
| Panel, fidget counter | 5–10 mA |
| Panel, full white at full brightness | about 100–200 mA. No vendor gives current against screen content, so measure with a PPK2 power profiler. |
| Touch | about 1.5 mA while scanning, under 1 µA asleep (CST816 figures; CST9217 and CST820B unverified) |
| Display when asleep | CO5300 deep standby 3 µA + touch sleep + NFC field sensing 0.1 µA ≈ 4 µA, replacing the OLED's 12 µA |
| MCU, configuration A | +0.9 mA at the desk and +2.5 mA in the game, for 32 MHz SPI and rendering |
| MCU, configuration B | +1.5 mA at the desk and +5 mA in the game |
| Co-processor, configuration C | RP2350 +15–30 mA whenever the screen is on |

| Mode | Rev A today | A | B | C |
|---|---|---|---|---|
| Sleep | 32 µA | ≈ 24 µA | ≈ 24 µA | ≈ 24 µA |
| Desk idle (connected, screen off) | 57 µA | ≈ 49 µA | ≈ 49 µA | ≈ 49 µA |
| Desk active | 29.4 mA | 23–33 mA | 23–33 mA | 37–62 mA |
| Game | 104 mA → 8.6 h | 98–113 mA → 8.0–9.2 h | 100–115 mA → 7.8–9.0 h | 111–141 mA → 6.4–8.1 h |
| Fidget, dim counter | 12 mA → 75 h | 9.5–16 mA → 57–95 h | same as A | 25–46 mA → 20–37 h |
| Desk, typical day (1 h turning, 7 h idle, 16 h asleep, 20 detent strokes) | 31.5 mAh → 28–29 days | 25–35 mAh → 26–37 days | 25–35 mAh → 26–36 days | 39–64 mAh → 14–23 days |

Peak current: the AMOLED at full white (estimate 100–200 mA) replaces the OLED's 146 mA. With brightness capped below a battery voltage of 3.6 V, the capped worst-case combined peak stays at about 0.7 A (architecture §8.4).

## 6. Cost

Per prototype unit in a 5-unit build, compared with rev A. Rev A prices come from architecture §12. Added parts are estimates unless a quote is cited.

| Change | Rev A part and price | Rev B (configuration A) | Change in cost |
|---|---|---|---|
| Panel | SSD1351 NHD-1.5-128128G, $15.3–28 | 1.75 in AMOLED with touch: $9–17 (TailorPixels) or $14.99 (Viewe) | −$19 to +$2 |
| 13 V boost circuit | $1.3–1.8 | removed (U21 reused) | −$1.3 to −$1.8 |
| Ø33 cover glass | $2–5 | removed | −$2 to −$5 |
| Opal diffuser | $2 | clear PC light guide with a textured top, $3–8 (estimate) | +$1 to +$6 |
| Support plate with NFC coil | printed OLED bracket | 0.4 mm 2-layer PCB, $2–6 (estimate) | +$2 to +$6 |
| Ferrite | none | IFL05K, die-cut, $1–3 (estimate) | +$1 to +$3 |
| Panel connector and riser or board-to-board pair | ZIF AFC01-S30FCA-00 | 31-pin 0.3 mm ZIF + board-to-board pair, $1.5–4 (estimate) | +$1 to +$3.5 |
| NFC tuning parts, spring contacts, foam, optional level shifter and ESD parts | none | $1–2 (estimate) | +$1 to +$2 |
| **Total** | | | **about −$20 to +$19** |

One-off cost of the bench work, roughly $150–200 (estimate):
- 3 Viewe and 3 TailorPixels panels ($75–100);
- a Waveshare ESP32-S3-Touch-AMOLED-1.75 ($30–40);
- an FH26 breakout board and an NFC coil test board ($20–40);
- an IFL05K ferrite sample.

Configuration B adds an nRF54LM20 DK ($39–58) or a XIAO nRF54LM20A (about $16). Configuration C adds a Waveshare RP2350-Touch-AMOLED-1.43 ($23.99–28.99).

## 7. Design changes for rev B

### 7.1 Configuration A

**SPEC.md**
- §1: replace the OLED with the 1.75 in round AMOLED with touch; replace the windowed top cover with the top ring and light guide; add the NFC coil on the support plate.
- §2: update the main-board contents (no 13 V boost; add the panel connector, touch and NFC tuning). Add the support plate, and the riser if one is used, as a part or board.
- §3: power diagram: U21 feeds the panel's VBAT (DISP_VBAT); remove the TPS61040 circuit; +3V3 also feeds VCI, IOVCC and touch.
- §4: pin map: SPIM3 at 32 MHz; P0.16 as an optional SIO1 read line; TOUCH_INT on P0.28, TOUCH_RST on P0.29, DISP_TE on P0.31, DISP_VCI_EN on P1.05. NFC is already on P0.09/P0.10, and CHG_INT_N is already on P1.03.
- §5.3: rewrite the display-sheet section.
- §5.5: touch on TWIM1, or on its own level-shifted segment; pull-up values for the longer bus.
- §7: add the ferrite sheet (with its notch at the TMAG) and the panel power chip's inductor on the tail to the 10 mm rule.
- §8:
  - replace the z 33.0–36.0 rows with the stack in §3.2;
  - update the top-side rules: TC2030 and DRV5032 under the plate, the tail's component area against the M4 nut, support plate r ≤ 26.6;
  - overall height becomes 36.2.

**Schematic sheets** (hardware/design/sheets)
- `display.py`:
  - Remove J20 (the 30-pin ZIF), U20 (TPS61040), L20, D21, R26/R27/C40, and the 13 V, VCOMH, VSL and IREF parts.
  - Keep U21 as the VBAT switch.
  - Add:
    - the 31-pin 0.3 mm connector, or the board-to-board connector to the plate;
    - VCI, IOVCC and VBAT decoupling per the vendor application circuit;
    - VCI_EN, TE and reset;
    - touch I2C, INT and RST, with an optional PCA9306-class level shifter (not fitted, with a 0 Ω bypass);
    - an optional ESD array.
- `mcu.py`: the new pin assignments.
- `sensors.py`: touch on TWIM1 and the address list.
- `nets.py`: DISP_VBAT, DISP_VCI_EN, DISP_TE, TP_INT_N, TP_RST_N (plus TP_SDA/TP_SCL if the touch bus is separate).
- NFC: change C16/C17 from 180 pF to the with-ferrite value (about 100 pF). Add a DNP trim capacitor and a DNP damping resistor on each pin.
- `layout.py`: placement rules for the new connector and the coil contacts; check the tail inductor's distance from the TMAG.
- New small PCB: the support plate with the coil (and possibly the ZIF and the board-to-board connector). Add it to `build.py`.

**Mechanical** (`dial_spinner.scad`, `stl/`, `mechanical.md`)
- Remove: the OLED glass and bracket (`oled_bracket.stl`), the Ø33 cover glass (BOM #23), the opal diffuser (BOM #31), and the window in `top_cover.stl`.
- Add:
  - the support plate (a PCB);
  - the ferrite sheet with its cutout and notches;
  - the light-guide ring: clear PC, textured top, stepped to sit on the light box;
  - the top ring, r 30–32.5;
  - foam pads under the panel and the tail.
- Update in `mechanical.md`:
  - §2: the stack;
  - §8: mass and click force (floating assembly +4–7 g);
  - §10: drop (the glass is now the top surface; the vendor's 0.19 J ball drop is the pass mark; the plastic edge stands proud);
  - §12: assembly order;
  - §13: BOM #22 (the panel);
  - §15: tests (light-guide evenness, NFC, touch);
  - the clash check.

**Firmware** (`firmware.md`)
- §1.2: NFC enabled; SPIM3 at 32 MHz to the CO5300; the touch IC added to TWIM1.
- §1.3: new pins and their sleep settings.
- §1.4: RAM map (2 × 32 KB buffers in RAM blocks 0–7, 64 KB heap, NFC and touch). The assets in QSPI flash get larger.
- §3: devicetree:
  - a project-local copy of the `chipone,co5300-spi` driver and its node;
  - the touch input node and NFC;
  - remove `nfct-pins-as-gpios`.
- §7, rewrite:
  - CO5300 start-up from the vendor or Waveshare sequence, power sequencing and deep standby;
  - colour-mode switching, even-coordinate rounding and TE pacing;
  - brightness via 51h;
  - the burn-in policy (kept);
  - the circular 466×466 UI.
- §8.2: combine touch with the press switch (glass press vs ring press); gestures.
- New NFC module:
  - NDEF content from nrfxlib's Type 2 or Type 4 tag library;
  - content set over a GATT characteristic or from the menu;
  - wake when a field is detected;
  - touch ignored while the field is present.
- §12: power states (panel deep standby, touch sleep).
- §16: production tests (touch, NFC resonance, panel current).
- §18: open items.

**architecture.md**
- §6.3: rewrite the display decision.
- §7: power tree.
- §8: power budget (the table in §5 here).
- §8.4: peak currents.
- §10 risks:
  - retire R31–R33 (all about the boost);
  - update R7 (panel sourcing), R19 (SPIM3 now at 32 MHz with no slower fallback) and R22 (AMOLED burn-in);
  - close R30 (resolved by the rev A NFC change);
  - add the new risks from §8 here.
- §11: D6 becomes SPIM3 at 32 MHz.
- §12: BOM.

**`assembly.md` and `bringup.md`**: folding and plugging the panel tail, fitting the ferrite and plate, tuning the coil on the finished unit, and erasing UICR.

### 7.2 Configuration B (in addition to A)

- **Hardware.**
  - New module footprint and a rewrite of `mcu.py`.
  - Pin map built around the sQSPI pins and the module's GPIO.
  - The W25Q128 moves to an SPIM, or is removed if the 2 MB internal memory holds the assets and the MCUboot layout fits.
  - LED data over TDM or SPI; NFC on the nRF54LM20A's pins.
- **Firmware.**
  - New board definition (HWMv2).
  - Port the encoder chain and detent PWM to DPPI/GRTC.
  - sQSPI with the MSPI CO5300 driver backport.
  - High-speed USB device stack, MCUboot partitions.
  - NFC library on the nRF54L (support for the LM20A unverified).
- **RF.** Check the module's u.FL position against the hub and the coax route (the SPEC §8 rules behind R25).
- **Documents.** SPEC §2/§4/§5.2, firmware.md §1–3 and §11, architecture §6.6.

### 7.3 Configuration C (in addition to A)

- **New sheet `gfx.py`:** the RP2350A or RP2354A, flash, crystal, core-regulator inductor, load switch, SWD pads, and the link to the nRF (SPIM2, an interrupt, and reset/boot pins).
- **Pin map:** SPIM2 pins for the link, the RP2350 enable and the interrupt.
- **Firmware:** a second project, the command protocol, power gating and the update path. The display code moves to the RP2350.
- **Documents and layout:** SPEC §2/§3/§4/§5, the power budget, and the layout rule keeping the inductor ≥ 10 mm from the TMAG.

## 8. Main risks and how to retire them

| Risk | Applies to | Action |
|---|---|---|
| The panel is not guaranteed with VBAT below 3.7 V (pin table 3.7–4.5 V; application circuits 3.3–5.5 V; BV6802W datasheet missing) | all | Bench sweep from 3.0 to 4.5 V; add a buck-boost footprint if it fails |
| Hidden metal behind the panel or in the folded tail shields the NFC coil | all | Ask the vendor for the back-layer stack; measure a test coil with the real panel |
| Real NFC coupling with a finite, cut and notched ferrite sheet | all | Network-analyser L/Q and phone tests on the first plates, with and without the θ 90° notch |
| Touch I2C at 1.8 V rather than 3.3 V | all | Vendor confirmation; optional level shifter on the board |
| No CST9217 datasheet | all (Viewe part) | Port the Espressif/ESPHome driver; keep the TailorPixels CST820B part as a second source |
| One panel maker, no Western distributor, and the SKUs differ in glass and touch IC | all | Lock one SKU, buy spares (≥ 3 per unit, as for R7), check drawing revisions |
| The CO5300 SPI driver exists only in Zephyr main; the low-colour modes are not in the driver | A, B | Project-local copy; bench-test 1-wire 0x02 framing at 32 MHz and RGB332/RGB111 on an nRF52840-DK |
| SPIM3 at 32 MHz with no slower fallback; clock edges at the FPC | A | Scope it; keep the route short and low in capacitance |
| Only about 8–25 KB of RAM left on the nRF52840 | A | Map file from a DK build with LVGL at 466×466, BLE, USB and NFC |
| Panel tail fold against the plate, the nut and the TMAG distance | all | Have a sample panel in hand before CAD; choose option 1 or 2 from §3.4 |
| Uneven glow from the light guide over r 24.6–27 | all | Printed or laser-cut mock-up with LEDs; fallback 5.1 mm black band |
| Glass presses and drops loading the panel | all | Continuous support with foam over the tail; 10 cm drop tests (mechanical §10) |
| Ferrite near the magnets: cogging, bias on the DRV5032, detuning | all | 50-rest cogging test, HOME margin test, resonance check at both detent positions |
| WS2812 data and the NFC field disturbing touch | all | Bench test; firmware ignores touch while an NFC field is present |
| AMOLED burn-in; −20 to +70 °C rating | all | Keep the rev A burn-in policy |
| nRF54LM20A modules not shipping; sQSPI immature | B | Prototype on DK v0.5.4 or later; adopt once a u.FL module can be ordered |
| Co-processor power and a second firmware image | C | Measure RP2350 current on a development board before choosing C |

## 9. Recommendation

1. **Adopt configuration A for rev B:**
   - Keep the nRF52840 unchanged.
   - Use the 1.75 in 466×466 AMOLED with on-cell touch. Make the Viewe ALL-UEOL018VG-RA31-A001A the primary part, for its smaller glass and the CST9217 that the Waveshare board already proves. Make the TailorPixels TOH175XRT-02CG the second source.
   - The glass becomes the top surface. The LEDs stay as they are, under a clear light guide.
   - Fit a 4-turn NFC coil on the support plate over an IFL05K ferrite sheet.
   - Run SPIM3 at 32 MHz, and build the UI on partial updates, with low-colour modes for full-screen motion.
2. **Before the rev B layout, run a short bench phase** (about 2–3 weeks, roughly $150–200 in parts):
   - **Panel on an nRF52840-DK** through an FH26 breakout:
     - start-up sequence; 1-wire 0x02 framing at 32 MHz; RGB565, RGB332 and RGB111; TE; partial windows;
     - current against screen content and brightness, with a PPK2;
     - a VBAT sweep from 3.0 to 4.5 V;
     - the touch I2C voltage.
   - **NFC test board.** The plate PCB with the coil and the IFL05K sheet, over a copy of the main-board ground, with the panel on top. Measure L, Q and resonance on the NanoVNA, then try reads with 2–3 phones.
   - **Mechanical.** Fold the tail of a real panel; build a light-guide mock-up; press the glass on the support stack.
   - **RAM.** Build a firmware skeleton with LVGL at 466×466, BLE, USB and NFC, and read the map file.
3. **Run configuration B as a parallel track** on an nRF54LM20 DK (CO5300 over sQSPI). Switch to it in a later revision, once a u.FL module can be ordered, if smooth full-colour animation turns out to matter.
4. **Choose configuration C only** if full-screen, full-colour animation at 30+ fps is a must for rev B and nRF54LM20A modules are still unavailable. That means accepting a third to a half less desk battery life.
5. **Keep NFC as a tag** (the phone reads the dial). Card reading (an ST25R3916B-class chip) waits for a later revision, unless you want board space reserved now.

## 10. Open questions for you

1. **Animation.** Is this acceptable: small elements move smoothly and the LED ring does the fast spinning, but full-screen redraws run at about 9 fps in full colour (about 18–22 fps in 256 colours or grey, about 37 fps in 8 colours)? Or must the screen itself show smooth full-colour, full-screen animation (B later, or C now with the battery hit)?
2. **Bezel look.** Are you happy with about 2–2.6 mm of black and then the LED glow ring? Or should we plan the seamless one-piece glass top (custom glass and touch tuning) for a later revision?
3. **Which way is up.** The panel cannot rotate its image in hardware. Should "up" on the screen be the side opposite the USB-C port, with USB-C at the back?
4. **Wake by touch.** Should tapping the glass wake the dial from sleep? That keeps the touch chip scanning, at a current that is unknown but may be tens of µA. Otherwise the dial wakes on a press, a turn or being picked up, as today.
5. **Reading NFC cards.** Defer it completely, or reserve board space for a reader chip in rev B?
6. **Brightness.** Is an indoor desk brightness cap of about half the panel's 700 cd/m² acceptable for battery life and burn-in, with a "bright" mode on request?
7. **Glass finish.** Should we pay for integrated-black glass, so the border and a black screen look identical, if the vendor offers it in small quantities?
8. **Budget.** Is about $150–200 for sample panels, a reference board and test boards for the bench phase OK?

## 11. Sources and files

Primary sources the sweeps used (checked):
- Huaxin ESHX0175Y003AMT003 specification: https://www.displayamoled.com/photo/displayamoled/document/88489/ESHX0175Y003AMT003-SPEC.pdf
- TailorPixels TOH175XRT-02CG: https://tailorpixels.com/product/1-75-inch-amoled-round-on-cell-touch-466x466-mipi-qspi/
- Viewe 1.75 in round AMOLED with touch: https://viewedisplay.com/product/1-75-inch-466x466-round-amoled-display-with-touch-screen/
- Waveshare ESP32-S3-Touch-AMOLED-1.75 schematic: https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.75/ESP32-S3-Touch-AMOLED-1.75.pdf
- CO5300 datasheet V0.01: https://files.waveshare.com/wiki/common/Co5300_Datasheet.pdf
- Zephyr `chipone,co5300-spi` binding: https://docs.zephyrproject.org/latest/build/dts/api/bindings/display/chipone,co5300-spi.html
- Zephyr CO5300 driver source: https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/drivers/display/display_co5300.c
- nRF52840 Product Specification v1.11: SPIM, QSPI and NFCT §6.14. nRF52840 errata 174, 193, 195 and 198. The anomaly-198 workaround in nrfx `nrfx_spim.c`.
- Nordic DevZone 96283 (QSPI page splitting) and 127479 (nRF54LM20 sQSPI lock-ups)
- nRF54LM20A product page: https://www.nordicsemi.com/Products/nRF54LM20A
- sQSPI changelog: https://nrfconnectdocs.nordicsemi.com/ncs/latest/nrfxlib/softperipheral/doc/sQSPI/CHANGELOG.html
- TDK IFL ferrite sheet datasheets: https://cdn.components.ru/media/PDF/2459147.pdf and https://cdn.components.ru/media/PDF/2436599.pdf
- Apple patents US11205832B2 and US12712267B2: https://patents.google.com/patent/US11205832B2/en and https://patents.google.com/patent/US12712267B2/en
- Waveshare RP2350-Touch-AMOLED-1.43: https://www.waveshare.com/RP2350-Touch-AMOLED-1.43.htm
- RP2354 announcement (secondary source): https://www.eenewseurope.com/en/raspberry-pi-adds-2mb-stacked-flash-to-rp2354-microcontroller
- ST25R3916B: https://www.st.com/en/nfc/st25r3916b.html

The working files behind this study (datasheet extracts, drawing crops, the NFC coupling model and the frame-time and battery calculations) stayed in the research workspace; the numbers that matter are all reproduced above with their sources.
