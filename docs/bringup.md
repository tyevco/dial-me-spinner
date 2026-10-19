# dial-me-spinner rev A: bring-up and acceptance tests

This document takes the boards from bare PCBA to an accepted unit. Steps are numbered **B-x** so
[`assembly.md`](assembly.md) can gate mechanical work on them. Do them in order; each step assumes the previous
ones passed. Record every measured number in a per-unit log (the checklist in B-14 is the summary).

* **Architecture of record:** `hardware/design/SPEC.md`. Pin map and net names: `hardware/design/nets.py`.
  BQ25180 firmware register values: [`firmware.md`](firmware.md) §13.1 (SPEC §3 points there); B-9.4 repeats
  them, including the two SPICE-driven values SPEC adds (SYS_REG 4.4 V, §5.4; TS_CONTROL, §3).
* "(hardware/sim, *ID*)" cites a finding of the SPICE suite ([`simulation.md`](simulation.md)); the numbers
  next to it are simulated, not measured.
* **[TVP]** means *to verify on prototype*: the value comes from a model, a datasheet typical or an unverified
  claim. Tighten those limits after the first good unit.
* "[x research]" and "[x verifier]" refer to the subsystem research files. Where the two differ, the verifier's
  corrected value is used.

---

## B-0. Equipment

| Item | Use | Notes |
|---|---|---|
| DMM with diode test, µA range, 10 MΩ input | Resistance and rail checks | A 10 MΩ meter reads VSYS_SENSE about 6 % low (687 kΩ source) |
| Bench supply, 0–6 V, ≥ 1.5 A, current limit settable to ~5 mA | Stand-in for battery and VSYS | Most bench supplies **cannot sink current** (see B-1) |
| Inline USB-C power meter + 5 V ≥ 1 A charger | USB tests | |
| Oscilloscope, ≥ 100 MHz, 2–4 channels, plus a current probe or a 0.1 Ω shunt | Rise times, I2C/SPI/LED timing, boost SW node, inrush and pack current | |
| SWD probe: SEGGER J-Link (EDU Mini fits the 10-pin 1.27 mm header) **or** an nRF52840 DK's "Debug out" header | Programming | |
| Tag-Connect **TC2030-CTX-NL** cable (+ optional TC2030-CLIP) | SWD to the TC2030-IDC-NL footprint (no legs) | [TC2030-CTX](https://www.tag-connect.com/wp-content/uploads/bsk-pdf-manager/TC2030-CTX_1.pdf) |
| Nordic **PPK2** | Sleep and mode currents | Source mode 0.8–5 V. After Stage C it connects through the battery breakout tail (assembly §7.2), because J2 is buried |
| Battery breakout lead with jumper, SH 4-pin (SHR-04V-S) at J2 (assembly §4.3, §7.2) | Battery disconnect and PPK2/bench tap on an assembled unit | One per unit that gets B-9.9b, B-9.8f or B-10 after Stage C |
| USB-C plug breakout | Feeding the USB-C receptacle from the current-limited bench supply once the base TPs are buried (Stage D) | |
| 1 m USB cable with VBUS broken out to the bench supply (D+, D−, GND to the host) | Enumeration at VBUS 4.50 V (B-8.6) | |
| VNA reaching 2.5 GHz: **NanoVNA V2 / V2 Plus4 or LiteVNA** + SMA SOL kit + **RF test pigtail** (1.13 mm coax, u.FL receptacle to SMA, 150–200 mm, assembly §4.3) + 1–2 clip-on ferrites + u.FL extraction tool | Antenna S11 | The original NanoVNA-H/H4 does not usefully reach 2.4 GHz |
| Thermocouple or IR thermometer | Charger and LED thermal checks | |
| Gram force gauge, or small masses + thread | Detent torque, click force | |
| Magnet pole identifier or analog Hall probe | Magnet polarity | |
| Protected 1S LiPo (spare), LiPo-safe bag | Charging tests | |
| nRF52840 DK (also serves as RF reference) and a phone with nRF Connect | RSSI comparison | |

---

## B-1. Ground rules

1. **Power each board alone before linking them.** Link only after both pass (B-4, B-5).
2. **Supplies and current limits for each step:**

   | Step | Supply → where | Setting | Current limit | Expected draw |
   |---|---|---|---|---|
   | B-4a base, USB only | 5 V → base VBUS TP (or USB-C via meter) | 5.00 V | 100 mA | < 5 mA |
   | B-4b base, battery only | bench → base J2 / VBAT TP | 3.70 V | 20 mA | < 0.1 mA (µA level) |
   | B-5 main alone | bench → main TP1 VSYS / TP4 GND | 3.70 V | 50 mA | < 10 mA unprogrammed **[TVP]** |
   | B-6 linked, no battery (first power-up) | 5 V bench → base VBUS TP | 5.00 V | **100–150 mA** | < 20 mA |
   | B-6, after it passes | USB charger via meter | 5 V | source-limited | < 20 mA |
   | B-9.8 LEDs | bench → base J2 (no USB) | **start at 3.7 V**; 4.2 V; 3.4 V only by lowering while running | 300 mA (1 A only for B-9.8e) | see B-9.8 |
   | B-9.9a bare boost (Stage A) | bench → J2 | 3.7 V | 500 mA (the boost soft start draws ≈ 0.4 A peak, B-9.9a) | see B-9.9 |
   | B-9.9b OLED panel (Stage F) | bench → **breakout tail**, board side (jumper open) | 3.7 V | 500 mA | see B-9.9 |
   | B-9.10 actuator | bench → J2 (Stage A8); real pack or breakout (Stage E) | 3.7 V | 600 mA | ≤ 0.45 A peak |
   | First power-up on the final harness (assembly D5) | 5 V bench → USB-C plug breakout, breakout jumper open | 5.00 V | 100–150 mA | < 20 mA |

   **Cold start on a bench "battery":** the BQ25180 powers SYS from BAT alone only above VBATPOR = 3.08 / 3.21 /
   3.46 V (min/typ/max, [BQ25180 SLUSE99C](https://www.ti.com/lit/ds/symlink/bq25180.pdf)). A start at 3.4 V can
   leave SYS off on some units and look like a fault. Always power up at **3.7 V**, then lower the voltage while
   the unit runs. Once running, SYS stays up down to BUVLO (3.0 V).

   **J2 and the base TPs are unreachable after assembly Stage C.** Every later step that names J2 uses the
   battery breakout tail instead (assembly §7.2): jumper open plus supply on the board side, or the PPK2 in
   ammeter mode in series with the real pack.

3. **A bench "battery" plus USB at the same time.** The BQ25180 will try to charge the bench supply, which cannot
   sink current, so its voltage creeps up. Either use a real cell, or put a dummy load across the bench supply
   that draws more than the charge current: the power-on default is 10 mA, and 82 Ω at 3.7 V draws 45 mA. Do not
   rely on a dummy load once firmware sets 400 mA.
4. **Never put more than 4.6 V on VSYS** and never 5 V. The LED absolute maximum is 5.3 V, and at VSYS 4.59 V
   the guaranteed LED data high-level margin is already down to +41 mV (SPEC §5.4; hardware/sim, LED-DATA-2).
5. **LiPo:** check pack polarity before every first connection (J2 pins 1–2 = BAT+, pins 3–4 = GND). Do the
   first charge in a LiPo bag, attended.
6. **OLED:** never insert or remove the panel FPC with power applied or with +13V_OLED charged (B-9.9a).
7. Keep magnets, steel tools and the rotor apart, and keep the u.FL mating count low (about 30 cycles rated).

---

## B-2. Visual and X-ray inspection

Inspect under 10–20× magnification, with the JLC X-ray images ([assembly §3.2](assembly.md#32-x-ray-and-inspection-requests)).

| Board | Check | Pass |
|---|---|---|
| base | BQ25180 X-ray: 8 balls, no bridges, no opens, voids < 25 % of ball area | Clean image |
| main | MDBT50Q X-ray: 61 pads, no bridges on the 0.4 mm-gap inner pads | Clean image |
| main | 48 LEDs: all present, pin-1 marks consistent around the ring, no tombstoning, lenses clean | All OK |
| main | VCOMH tantalum C32 polarity (+ to the panel pin), B5819W D21 cathode to +13V_OLED, BAV99 D20 orientation, pin 1 of both TPS22917 load switches (U2 for VLED, U21 for OLED_VIN) | Per schematic |
| main | USBLC6-2SC6 U12 (bottom, at the module's D+/D− pads): pin-1 mark matches the silk. Turned 180°, its GND pin lands on VBUS_NRF and its internal clamp conducts from VBUS_NRF to GND; B-3a then reads VBUS_NRF low, and on USB R12 burns open | OK |
| main | ZIF: bottom-contact part, lid present and working, no solder wicking into contacts. **J20 pins 1–2** (GND next to the 13 V VCC at 0.5 mm pitch): no bridge or solder ball; a bridge shorts the boost output (hardware/sim, OLED-V3) | OK |
| main | TMAG5273 U30 (bottom, θ 270°): pin 1 orientation, long axis radial | OK |
| main | TPD4E05U06 ESD array U32 (bottom, beside U30): pin-1 mark matches the silk. Turned 180°, it puts TMAG_SCL/SDA/INT_N on its NC pins (6, 7, 9): the lines are then unprotected and no electrical test shows it | OK |
| main | DRV8837 ×2 exposed pad wetted (side view), LIS2DW12 pin-1 dot, W25Q128 pin 1, crystal | OK |
| main | DNP parts absent (R11, U43, C43); R43 (0 Ω, LED_DIN_R → LED_DIN) fitted (assembly §3.5) | OK |
| main | Nothing ferrous added near the track: no shield cans, no stray screws or washers (B-9.6) | OK |
| both | Side-entry JST SH link connectors `SM12B-SRSS-TB` (main J1 on the bottom, r 19.5, θ 330°; base J3 on the top, r ≈ 15.5, θ 120°): seated flat, entry facing the board centre, pin 1 as expected (assembly §6) | OK |
| base | USB-C shell legs soldered through; SMF5.0A D1 cathode band toward VBUS (assembly §3.4); switch SW1 centred and square; battery connector J2 (side-entry SH `SM04B-SRSS-TB`, r 17, θ 222°, mouth radially outward) seated flat, BAT+/GND silk legible | OK |
| both | Flux residue, solder balls, especially around the 0.5 mm ZIF, the DSBGA and the VSYS_SENSE node (R1/R2/C5): 4.5 nA of leakage there uses up the whole ±10 mV calibrated budget (SPEC §3; hardware/sim, VSENSE-2) | Clean |

---

## B-3. Unpowered resistance checks

Use the DMM ohms range with the red lead on the node and black on GND. Wait for the capacitors to charge; the
reading climbs. Then run diode test with the **red lead on GND** and black on the rail: expect 0.3–0.8 V
(ESD and body diodes). 0.0x V is a short; "OL" on a rail full of ICs suggests a missing ground. Record the values
from the first good board and compare later boards against them (±20 %).

### B-3a Main board, power nets

| Node (probe at) | Expected | Fail if | Notes |
|---|---|---|---|
| VSYS (TP1, bottom side) | > 100 kΩ, settling into MΩ | < 1 kΩ | 2.2 M + 1 M divider, LDO, VIN of both load switches (U2, U21), DRV VM |
| +3V3 (TP2) | > 10 kΩ after charging (record) | < 1 kΩ | Supply pins of nRF, flash, TMAG, IMU, OLED logic, DRV VCC, DRV5032 |
| VLED (TP3) | > 10 kΩ | < 1 kΩ | 48 LEDs, 48× 100 nF, 2× 22 µF |
| +13V_OLED (boost output cap C39) | **520–580 kΩ** (499 k + 52.3 k FB divider), panel not fitted | outside range | Confirms the divider |
| OLED_VIN (boost input cap C38) | **≈ 0.55–0.9 MΩ**: about the +13V_OLED reading plus a diode drop (record) | < 10 kΩ | Behind the load switch U21 (TPS22917, off), but OLED_VIN reaches GND through L20 → D21 (forward-biased from OLED_VIN toward +13V_OLED) → the 499 k + 52.3 k divider. The exact value depends on the meter's test current and the B5819W drop. U21's QOD pin is tied to OLED_VIN, but its ≈ 150 Ω discharge acts only while U21 has VIN ([TPS22917 SLVSDW8B](https://www.ti.com/lit/ds/symlink/tps22917.pdf) §9.3.3.1), so it does not show unpowered; B-5 and B-9.9a check it powered. U21's always-on reverse-current blocking (reverse leakage ≤ 1 µA) leaves no diode path back into VSYS |
| VBUS (J1 pin 5) | > 100 kΩ | < 10 kΩ | Only R12 hangs on this net on the main board |
| VBUS_NRF (C12, module side of R12) | > 100 kΩ | < 10 kΩ | nRF VBUS pad 32, C12 4.7 µF and the U12 USBLC6 rail (pin 5). Low here: U12 turned (B-2) or C12 shorted. A C12 short with VBUS applied burns the 0402 R12 open at ≈ 1.2 A (hardware/sim, V-5) |
| VBUS ↔ VBUS_NRF | ≈ 4.7 Ω (R12; zero the leads first) | open, or > 10 Ω | R12 FRC0402F4R70TS in series to the nRF VBUS pin (SPEC §5.2) |
| VSYS↔+3V3, VSYS↔VLED, VSYS↔OLED_VIN | > 10 kΩ | < 100 Ω | A short here means a damaged LDO (U1) or load switch (U2 for VLED, U21 for OLED_VIN) |

### B-3b Main board, pull resistors (catches missing or swapped resistors)

| Net | To | Expected |
|---|---|---|
| I2C_SCL, I2C_SDA, TMAG_SCL, TMAG_SDA | +3V3 | ≈ 4.7 kΩ |
| TMAG_INT_N | +3V3 | ≈ 47 kΩ |
| CHG_INT_N | +3V3 | ≈ 10 kΩ |
| BTN_N | +3V3 | ≈ 100 kΩ |
| QSPI_CS | +3V3 | ≈ 10 kΩ |
| OLED_RES_N | GND | ≈ 1 MΩ |
| OLED_VCC_EN (R25) | GND | ≈ 88–100 kΩ (U21's 750 kΩ smart ON pull-down in parallel, as on LED_PWR_EN) |
| LED_PWR_EN (R3) | GND | ≈ 88–100 kΩ (TPS22917 750 kΩ smart pull-down in parallel) |
| **MOT_NSLEEP** (R70) | GND | **≈ 33 kΩ**: 100 k external in parallel with each DRV8837's internal pull-down (RPD = 100 kΩ typ, [DRV8837](https://www.ti.com/lit/ds/symlink/drv8837.pdf); `detent.py`) |
| LED_DIN_R and LED_DIN (R41; the fitted 0 Ω R43 joins them) | GND | ≈ 100 kΩ at both; may read lower through D101's DIN ESD diode into VLED. LED_DIN_R ↔ LED_DIN ≈ 0 Ω |
| LED_D48 at TP40 (R42, chain end) | GND | ≈ 100 kΩ |
| VSYS_SENSE | GND | ≈ 0.7–1.0 MΩ (1 M in parallel with 2.2 M plus the VSYS-to-GND path) |
| ZIF pin 22 (IREF) | GND | ≈ 560 kΩ |
| BZ_P (BZ1 pad 1) | BZ_N (pad 2) | ≈ 1 MΩ (R59 bleed); may read lower through R57/R58 (470 Ω each) and the unpowered nRF pins |

Pass: each net within ±10 % of the value in this table, not of the bare resistor value. Where the table gives a
range (LED_PWR_EN, OLED_VCC_EN, VSYS_SENSE) or says "may read lower" (LED_DIN, BZ1), pass inside the range, or
within ±20 % of the first good board's reading.

### B-3c Base board

| Node | Expected | Notes |
|---|---|---|
| VBUS (base TP1) → GND | > 100 kΩ | TVS D1, USBLC6 U2, BQ IN |
| CC1, CC2 (at connector) → GND | **5.1 kΩ each** | Separate Rd per pin, R1/R2 (SPEC §3) |
| VBAT (J2 pins 1–2 / TP2) → GND | > 100 kΩ | |
| VSYS (TP3) → GND | > 100 kΩ | |
| TS/MR → GND | **≈ 10 kΩ at 25 °C** (≈ 11.2 kΩ at 22 °C) | RT1 NCP15XH103F03RC NTC, B25/50 = 3380 K (the "B3435" in SPEC §3 and on the sheet is its B25/85 value). This is the only hardware screen for an open RT1, which can switch the charger's TS monitoring off rather than read cold (B-4a) |
| SW_GATE → GND | ≈ 100 kΩ (R4); while pressing SW1, SW_GATE → VBAT ≈ 1 kΩ | Press network |
| USB_DP ↔ USB_DM | > 1 MΩ | |
| USB-C shell → GND | ≈ 0 Ω | SPEC §3 |
| VBUS↔VSYS↔VBAT | not shorted (> 10 kΩ) | |

---

## B-4. Base board alone

### B-4a USB only, no battery

Apply 5.00 V, 100 mA limit.

| Measure | Expected | Notes |
|---|---|---|
| Input current | < 5 mA | BQ input quiescent + TVS leakage |
| VBUS (TP1) | 4.75–5.25 V | |
| VSYS (TP3) | **4.4–4.6 V** (SYS_REG default 4.5 V) | [BQ25180 datasheet](https://www.ti.com/lit/ds/symlink/bq25180.pdf) |
| TS/MR | ≈ 0.38 V at 25 °C (38 µA bias × 10 kΩ) | Default thresholds ([BQ25180 SLUSE99C](https://www.ti.com/lit/ds/symlink/bq25180.pdf), §7.5): **> 1.0 V** (cold entry 0.96–1.06 V) means cold (≈ 0 °C); **< 0.185 V** (0.173–0.198 V) means warm (≈ 45 °C); **< 0.115 V** (0.105–0.125 V) means hot (≈ 60 °C). An **open NTC** does not read cold: the pin floats to VTS_CLAMP (2.2–3.3 V), above VTS_ENZ (1.8–2.8 V), and TS monitoring may switch off, so the charger can charge with no temperature limit. Firmware MUST treat STAT0.TS_OPEN_STAT = 1 as a fault (CHG_DIS = 1) (SPEC §3; hardware/sim, charger_ts-v1) |
| VBAT (TP2) | Undefined, may sawtooth | With no battery the charger cycles its detection. Do not judge it |

### B-4b Battery only (bench 3.70 V into J2, 20 mA limit, USB unplugged)

| Measure | Expected |
|---|---|
| VSYS (TP3) | ≈ VBAT (within 50 mV; BATFET 55 mΩ) |
| Current | Below the bench meter's resolution (BQ IQ ≈ 3–4 µA; measured properly in B-10) |

If VSYS stays at 0 V, the BQ25180 is in ship mode. Plug USB or hold the press switch for about 2 s. Start this
test at 3.70 V, never at 3.4 V: battery-only power-up needs VBAT above VBATPOR (3.08–3.46 V, B-1).

---

## B-5. Main board alone (bench → TP1 VSYS, 3.70 V, 50 mA limit)

The base and battery are disconnected and the module is unprogrammed (or erased).

| Measure | Expected | Notes |
|---|---|---|
| Supply current | < 10 mA (record) **[TVP]** | An erased nRF52840 sits in a reset/lockup loop. The TMAG5273 powers up in standby (≈ 0.45 mA). A module with vendor demo firmware may draw more |
| +3V3 (TP2) | **3.30 V** (accept 3.20–3.40 V) | RT9080-33 ([DS9080](https://www.richtek.com/assets/product_file/RT9080/DS9080-07.pdf)) |
| VLED (TP3) | < 50 mV | LED_PWR_EN pulled down; U2's QOD (through R4 68 Ω) holds VLED at 0 V |
| OLED_VIN, +13V_OLED | < 50 mV | OLED_VCC_EN held low by R25, so U21 is off and its QOD holds OLED_VIN at ≈ 0 V; panel not fitted |
| VSYS_SENSE | 1.156 V (VSYS / 3.2); a 10 MΩ DMM reads about 1.09 V | |
| QSPI_CS, BTN_N, CHG_INT_N, TMAG_INT_N | ≈ 3.3 V | Pull-ups |

**LDO dropout sweep:** step VSYS from 4.6 V down to 3.0 V in 0.1 V steps and log +3V3. It should hold 3.30 V
until VSYS is roughly 3.3 V plus dropout, then follow VSYS down. Note where it drops out. The W25Q128JV needs
≥ 2.7 V, so firmware must block flash writes and DFU before that point ([mcu verifier]).

---

## B-6. Both boards linked, USB power, no battery

Connect the tested **bench harness** (assembly §6). For the **first** linked power-up, do not use a charger: a
harness mis-pin (VSYS or VBUS onto GND) would get amps from it. Feed **5.00 V at a 100–150 mA limit into the base
VBUS TP** (GND to the base GND TP). Switch to a 5 V charger behind the USB meter only after every row below
passes.

| Measure | Expected |
|---|---|
| Supply / USB input current | < 20 mA. Hitting the 100–150 mA limit means a short: switch off and check the harness |
| Base VSYS TP / main TP1 VSYS | 4.4–4.6 V; difference < 20 mV at this load |
| Main TP2 +3V3 | 3.30 V |
| Main J1 pin 5 (VBUS) | ≈ 5 V |
| Main VBUS_NRF (C12) | Within ≈ 20 mV of J1 pin 5 (R12 drops ≈ 11 mV at the nRF's 2.4 mA VBUS current, `mcu` sheet) |

Known limitation: the press network is referenced to VBAT (SPEC §3), so **the dial press may not work on USB
power without a battery**. Test it in B-9.5d. Serial recovery is therefore always tested with a battery fitted
(B-8.7).

---

## B-7. SWD programming and UICR configuration

### B-7.1 Hook-up

* TC2030 pads (J10, r 12, θ 150°) are on the main-board **top under the OLED glass**, so they are only reachable
  before the panel is fitted (SPEC §8). Pinout: 1 VTref (+3V3), 2 SWDIO, 3 NRESET (P0.18), 4 SWDCLK, 5 GND, 6 SWO (P1.00).
* The TC2030-CTX-NL plugs into a J-Link EDU Mini directly, or into the nRF52840 DK's 10-pin "Debug out" header.
  The DK only switches to an external target when it sees target voltage on VTref and the GND-detect pin
  (header pin 9) is grounded. Check that the cable does this, and confirm in the DK user guide **[TVP]**.
* Power the target from USB (B-6) or bench VSYS. VTref must read 3.3 V. Hold the NL plug square (or use the
  clip), and start at an SWD clock of 1–4 MHz.

### B-7.2 Identify the silicon

```
nrfjprog --memrd 0x10000100 --n 8      # FICR INFO.PART, INFO.VARIANT
```

| Word | Expected |
|---|---|
| INFO.PART | 0x00052840 |
| INFO.VARIANT (ASCII) | e.g. "AAD0"/"AAD1" = Rev 2, "AAF0" = Rev 3 **[TVP: confirm the mapping in Nordic's revision guide]** |

If the read fails with an access-port-protection error, the part is locked. Run `nrfjprog --recover` (or
`nrfutil device recover`), which does a full erase. Rev 3 (build code F) enables hardware APPROTECT by default
([mcu verifier]). `nrfjprog` is archived but still works with J-Link; `west flash` and `nrfutil device` are the
current tools.

### B-7.3 UICR settings (normal-voltage mode)

Set the reset pin through devicetree in the board files, `&uicr { gpio-as-nreset; };`. Zephyr's SoC start-up
writes it on first boot and resets once. NFCPINS stays at its erased value (NFC mode): P0.09/P0.10 are the NFC1/NFC2
tag-antenna pins (SPEC §4), so do **not** set `nfct-pins-as-gpios` or `CONFIG_NFCT_PINS_AS_GPIOS`. Check the
readback after a **power cycle**:

```
nrfjprog --memrd 0x10001200 --n 16     # PSELRESET[0], PSELRESET[1], APPROTECT, NFCPINS
nrfjprog --memrd 0x10001304 --n 4      # REGOUT0
```

| Address | Register | Expected | Why |
|---|---|---|---|
| 0x10001200 / 0x10001204 | PSELRESET[0] / [1] | Both PIN = 18, CONNECT = 0 (e.g. 0x00000012 or 0x7FFFFFD2), and both identical | P0.18 is the NRESET pin on TC2030 pin 3 (SPEC §4) |
| 0x10001208 | APPROTECT | Rev 2: 0xFFFFFFFF (debug open). Rev 3: 0x0000005A (HwDisabled), and firmware also writes APPROTECT.DISABLE at boot (NCS default unless `CONFIG_NRF_APPROTECT_LOCK`) **[TVP]** | Keep SWD usable during development |
| 0x1000120C | NFCPINS | **0xFFFFFFFF** (PROTECT = 1, NFC mode) | P0.09/P0.10 = NFC1/NFC2 with C16/C17 to GND and the coil on J11 (SPEC §4, §5.2). 0xFFFFFFFE would turn them into GPIOs and disable the tag. CHG_INT_N is on P1.03 |
| 0x10001304 | REGOUT0 | **Leave 0xFFFFFFFF** | VDD and VDDH are both on +3V3 (SPEC §3), so REG0 is bypassed and REGOUT0 has no effect. Do **not** apply the high-voltage-mode value (0xFFFFFFFC) from the power research |

Pass when NRESET resets the chip (pull TC2030 pin 3 low → RESETREAS shows RESETPIN) and SWD still attaches after a
full power cycle.

---

## B-8. First firmware

### B-8.1 Bring-up image

Build a Zephyr/NCS image for the board with: a shell over **RTT** (no extra pins needed), plus
`CONFIG_I2C_SHELL`, `CONFIG_GPIO_SHELL`, `CONFIG_FLASH_SHELL`, `CONFIG_SENSOR_SHELL`, `CONFIG_PWM_SHELL` and
`CONFIG_ADC_SHELL`; LFCLK from the crystal (`CONFIG_CLOCK_CONTROL_NRF_K32SRC_XTAL`); and REG1 DC/DC enabled
(`&reg1 { regulator-initial-mode = <NRF5X_REG_MODE_DCDC>; }`, inductor inside the module). Flash it with
`west flash` or `nrfjprog --program merged.hex --chiperase --verify --reset`.

### B-8.2 Blinky

There is no discrete LED. Toggle **TP_SPARE1 (P0.03, pad TP10 on the main-board bottom)** at 1 Hz and watch it on the scope or DMM, and print
"hello" over RTT. P0.03 is a low-frequency pin, which is fine at 1 Hz.

### B-8.3 Clocks

| Check | Expected |
|---|---|
| `NRF_CLOCK->LFCLKSTAT` (0x40000418) after start-up | 0x00010001 (running, source = Xtal) |
| RTC drift against the host over 1 h | ≤ 0.1 s (≤ about 28 ppm: crystal ±20 ppm + load error) **[TVP]** |
| HFXO (inside the module) on request | HFCLKSTAT shows Xtal running |

The 32.768 kHz crystal is the SC-20S 9 pF with 2× 12 pF ([mcu research]). Probing the crystal pins loads them,
so judge it by LFCLKSTAT and drift.

### B-8.4 DC/DC

Run a busy loop with REG1 in LDO mode, then in DC/DC mode. Supply current must drop noticeably in DC/DC mode.
Record both. That confirms the module's internal REG1 inductor works.

### B-8.5 VSYS measurement (SAADC)

AIN0 = P0.02, gain 1/6, internal 0.6 V reference (3.6 V full scale), TACQ **40 µs** (the source is 687 kΩ),
12 bits, 8× oversampling. **VSYS = code × 2.8125 mV** (code × 3.6 V / 4096 × 3.2).

| Check | Pass |
|---|---|
| vs DMM at TP1 (3.0 / 3.7 / 4.5 V bench), uncalibrated | within ±5.5 % (SAADC gain error EG1/6 ±3 %, divider ±1.4 %, offset) (hardware/sim, VSENSE-3) |
| After a one-point calibration at 3.80 V | within ±20 mV over 3.3–4.5 V **[TVP]** |

Take the calibration reference from the DMM at TP1 (VSYS at the divider), not from the bench setpoint, or keep
the board current below 5 mA while calibrating: the BATFET, link and path resistance otherwise store a permanent
gain error (hardware/sim, VSENSE-5). The calibrated reading holds ±10 mV only at 25 ± 10 °C on a fresh board; it
can drift ±46 mV over −10…60 °C and with ageing, which is why firmware's low-battery SHIP threshold is 3.53 V
(hardware/sim, VSENSE-1, VSENSE-4).

On USB this reads SYS (4.4 V once firmware has set SYS_REG, 4.5 V at power-on), not the battery. Use the BQ25180
CHG_STAT field while charging.

### B-8.6 USB

| Check | Pass |
|---|---|
| USBREGSTATUS.VBUSDETECT with USB plugged | 1 (VBUS ≥ 4.3 V guaranteed) |
| CDC-ACM sample enumerates (`lsusb`, Device Manager) | Enumerates first time, no resets in `dmesg` |
| 1 MB loopback | 0 errors |
| Same, with VBUS from the bench at **4.50 V** through the 1 m broken-out cable (B-0), battery fitted and charging | Enumerates; VBUSDETECT stays 1. R12 leaves only ≈ 28 mV above the 4.35 V VBUS minimum at this corner (SPEC §5.2; hardware/sim, USB-1) |

D+/D− pass through the base ESD (U2), about 70 mm of harness, the second USBLC6 (U12) and the module. Full Speed
tolerates that, but watch for retries.

### B-8.7 MCUboot and recovery (a gate of its own: assembly A9, after B-9.1 QSPI and B-9.5 battery)

MCUboot uses signed images, with the secondary slot on the QSPI flash ([mcu verifier]). **Do every check below
with the TC2030 cable removed** and a battery (bench pack or real cell) on J2. That is the only state a closed unit
can be recovered from: after Stage F the TC2030 pads, and with them NRESET, are under the glass.

1. Image upload over USB CDC with mcumgr, test swap, confirm. Also upload an image and reset *without* confirming:
   MCUboot must revert.
2. The same over BLE SMP (nRF Connect Device Manager).
3. **Serial recovery.** Try every route below and record which work. Recovery is entered when the bootloader
   answers `mcumgr --conntype serial --connstring dev=<CDC port> image list`.

| Route | Procedure | Why it works (or may not) |
|---|---|---|
| **(a) Long-press hardware reset** | With the app's BQ25180 init set written (TMR_ILIM 0x08 = 0xCD: MR_LPRESS = 20 s, MR_RESET_VIN = 0; SHIP_RST 0x09 = 0x09: PB_LPRESS_ACTION = 01 = hardware reset), hold the dial press. At **18–22 s** the BQ25180 switches SYS off and restarts it about 1 s later (AUTOWAKE = 1 s). **Keep holding through the restart** so MCUboot sees BTN_N low, then release 1–3 s after the recovery port appears. Do **not** keep holding for long: after the hardware reset the BQ25180 is back at its power-on defaults, where a 9–11 s press means **ship mode** | Plugging USB does not reset the nRF when a battery is fitted, because the power path keeps SYS up, so this long press is the only reset that needs no SWD. SLUSE99C: MR_RESET_VIN = 0 is "Reset sent when long press duration is met", with no VIN condition, but EN_PUSH is described as "Enable Push Button and Reset Function on Battery Only". **Test it on battery alone (then plug USB to reach the port) and with USB present**, and record both |
| **(b) From ship mode or shutdown** | Enter ship (0x09 = 0x49) or shutdown (0x09 = 0x29). Hold the press, plug in USB, keep holding ≈ 2 s after the recovery port appears, release. Also try it from ship mode with the press alone: hold ≥ 2 s (ship wake), keep holding, then plug USB | USB insertion exits ship or shutdown at once. SYS and +3V3 come up with BTN_N already held low by the VBAT-referenced press network, so MCUboot starts in recovery |
| (a′) App never ran since power-on | Hold the press: at 9–11 s the BQ25180 defaults (MR_LPRESS 10 s, PB_LPRESS_ACTION = ship) put it in ship mode. Keep holding and continue with (b) | Covers a unit whose app crashes before writing the BQ registers |
| **(c) App request** | Firmware command 0x08 ("reboot to serial recovery", [`firmware.md`](firmware.md) §11.2), or the shell, writes the retained boot-mode word and reboots | Needs a running app and a BLE or USB connection |

4. **Rails stay off outside the app.** While MCUboot runs and while the unit sits in serial recovery, VLED and
   OLED_VIN read < 50 mV and MOT_NSLEEP is low. MCUboot and the USB-recovery image MUST keep LED_PWR_EN,
   OLED_VCC_EN and MOT_NSLEEP low, because the LED/OLED/motor current limit lives only in the app
   (SPEC §5.4; hardware/sim, PI-1).

**Pass (needed before the OLED is fitted):** USB and BLE DFU with revert work, route (c) works, the rails stay off
(step 4), and at least one of
(a) or (b) works with no SWD attached. Write the working routes into the unit log and into assembly §11.7 step 4.
If neither (a) nor (b) works, do not close the unit. Fix it first. Options: a detect delay before MCUboot samples
BTN_N (`CONFIG_BOOT_SERIAL_DETECT_DELAY`), a short recovery window at every boot (`CONFIG_BOOT_SERIAL_WAIT_FOR_DFU`)
**[TVP: check the option names in the NCS version used]**, or, for rev B, an NRESET pad that can be reached from
outside.

---

## B-9. Peripheral smoke tests

### B-9.1 QSPI flash (W25Q128JVSIQ)

Pins: CS P0.17, SCK P0.19, IO0–IO3 P0.20–P0.23 (SPEC §4). Zephyr `nordic,qspi-nor`, start at 8 MHz with
single-line opcodes (`readoc = "fastread"`, `writeoc = "pp"`).

| Check | Pass |
|---|---|
| JEDEC ID (9Fh) | **EF 40 18** (Winbond W25Q128JV datasheet; not in the research set) **[TVP]** |
| Erase one 4 kB sector, write a pattern, read back | 0 errors |
| Switch to quad (`read4io`, `pp4o`) at up to 32 MHz, 1 MB write/read CRC | 0 errors |
| Deep power-down (B9h) and release (ABh) | Device answers after release. The current check is in B-10 |

### B-9.2 I2C scans

```
i2c scan i2c@40003000   # TWIM0, TMAG only (P0.24 SCL / P0.25 SDA)
i2c scan i2c@40004000   # TWIM1, system bus (P0.08 SCL / P1.09 SDA)
```

| Bus | Expected addresses | Notes |
|---|---|---|
| TWIM0 | **0x35** only | TMAG5273A2. Nothing else may be on this bus |
| TWIM1 | **0x19**, **0x6A** | LIS2DW12 (SA0 high) and BQ25180 (via the link; only when the base is linked and powered) |

* **0x18 instead of 0x19** means the LIS2DW12 SA0 is grounded. That is wrong and costs about 60–170 µA through
  its internal pull-up ([sensing verifier]).
* **Bus clocks.** The bring-up image MUST configure the TWIMs like the application: nRF52840 errata 219 cuts
  SCL low to 1.25 µs at 400 kHz, below the 1.3 µs Fast-mode tLOW, so TWIM0 writes FREQUENCY = 0x06200000 after
  init, and TWIM1 runs at 250 kHz (FREQUENCY = 0x04000000) or 100 kHz. Keep the default S0D1 drive on all TWIM
  pins: H0D1 or stiffer pull-ups need series resistors first (hardware/sim, test_piezo_bus NF-1, PB-2, NF-3).
* Then scope the buses (TWIM1 includes two harness wires):

  | Check | Where | Pass |
  |---|---|---|
  | SCL low time tLOW | U30 pin 1 (TMAG_SCL), U31 pin 1 (I2C_SCL) | ≥ 1.3 µs (UM10204 Fast mode). SPICE: 1.306–1.312 µs at U30 with the workaround, ≈ 1.97 µs at U31 at 250 kHz |
  | SCL rise time (30–70 %) | Base J3 pin 9, the far end of the harness | ≤ 250 ns (Fast mode allows 300 ns). If longer, run TWIM1 at 100 kHz; do not stiffen the pull-ups (hardware/sim, PB-2) |
  | SDA-to-SCL setup tSU;DAT | U31 pins 4/1 (0.8/0.2 × VDD_IO points) and base J3 pins 10/9 (0.7/0.3 × VDD) | ≥ 100 ns. If short, run TWIM1 at 100 kHz (hardware/sim, test_piezo_bus NF-2) |
  | Ringing on SCL/SDA | Base J3 | Record; no extra crossings of VIL/VIH (hardware/sim, NF-3) |

### B-9.3 LIS2DW12

| Check | Pass |
|---|---|
| WHO_AM_I (0x0F) | **0x44** (ST datasheet) **[TVP]** |
| `sensor get` at rest | \|a\| = 0.9–1.1 g; one axis ≈ ±1 g depending on mounting side |
| Wake-up: LP mode 1, 12.5 Hz, ±2 g, threshold 2–4 LSB (62–125 mg) on INT1 | A tap on the bench pulses IMU_INT1 (P1.12) |
| INT2 (P0.30) | Toggles when routed in firmware |

Reference: [AN5038](https://www.st.com/resource/en/application_note/an5038-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf).

### B-9.4 BQ25180 registers (USB only, no battery)

1. Read 0x00–0x0C. At power-on, expect VBAT_CTRL (0x03) = 0x46 (4.20 V), ICHG_CTRL at its low default (10 mA)
   and STAT0 showing input power good. Check the bit positions against the
   [register map](https://www.ti.com/lit/ds/symlink/bq25180.pdf) **[TVP]**.
2. **First write IC_CTRL = 0x97.** The 160 s register watchdog starts at the first I2C transaction, and when it
   expires every register reverts ([power verifier]).
3. Write the set below and read every register back. It must match exactly.

| Reg | Name | Value | Meaning ([power verifier]) |
|---|---|---|---|
| 0x07 | IC_CTRL | **0x97** | Watchdog off, TS_EN, VLOWV 3.0 V, VRCH 100 mV, 2×TMR, 6 h safety timer |
| 0x03 | VBAT_CTRL | 0x46 | 4.20 V |
| 0x04 | ICHG_CTRL | **0x43** | 400 mA (40 + (code − 31) × 10 mA) |
| 0x05 | CHARGECTRL0 | 0x20 | IPRECHG 2× term, ITERM 10 %, VINDPM 4.2 V, TREG 100 °C |
| 0x06 | CHARGECTRL1 | 0x92 | BATOCP 1.5 A, BUVLO 3.0 V, charge-status INT on, ILIM INT masked |
| 0x08 | TMR_ILIM | **0xCD** | Long press 20 s, MR_RESET_VIN 0 (reset on long press regardless of VIN), autowake 1 s, ILIM code 500 mA (≈ 475 mA typ) |
| 0x09 | SHIP_RST | 0x09 | Long press = hardware reset, WAKE1 300 ms, WAKE2 2 s, push-button enabled |
| 0x0A | SYS_REG | **0x20** | SYS_REG_CTRL = 001: SYS 4.4 V on USB. It MUST be 4.4 V (or 0x40 = 4.5 V), never higher and never pass-through while the LEDs may run, for the LED data margin (SPEC §5.4; hardware/sim, LED-DATA-V3, LDO-2) |
| 0x0B | TS_CONTROL | **0x90** | TS_HOT 50 °C, TS_COLD 3 °C (WARM 45 °C, COOL 10 °C unchanged), so the JEITA limits hold with the NTC and threshold tolerances (SPEC §3; hardware/sim, charger_ts-1) |

Rev A has no CC-line sensing (CC goes only to 5.1 kΩ), so stay at 400 mA / 0xCD. Do not use the 500 mA / 700 mA
ILIM pair that the verifier allows only for a detected 1.5 A or 3 A source.

| Check | Pass |
|---|---|
| CHG_INT_N (P1.03) on the scope while plugging and unplugging USB | **≈ 128 µs active-low pulses** ([power research]). A line stuck low, or no pulses, points to the 10 kΩ pull-up R55, link pin 11 or the BQ25180 |

A VIN_OVP flag within about 30 ms of plug-in is the hot-plug overshoot of a legacy cable, not a charger fault
(hardware/sim, V-3).

**Before firmware writes SHIP_RST:** with the power-on default, a 10 s press enters ship mode and SYS goes off.
Wake with a 2 s press or USB.

### B-9.5 Battery, charging, ship mode, press network

**B-9.5a First battery connection.** Check polarity first (assembly §7.2). Use a pack at 3.5–4.0 V. Connect with
USB unplugged.

| Check | Pass |
|---|---|
| VSYS (base TP) | VBAT ± 50 mV |
| Main +3V3 | 3.30 V |
| Pack current at insertion (current probe or shunt at the breakout jumper), on several boards | Peak below the BQ25180's power-on BATOCP of 1 A, and VSYS comes up without a restart. SPICE puts the +3V3-rail inrush at ≈ 0.95 A for a typical LDO current limit, 5 % below it; record the peak (hardware/sim, LDO-4) |

**B-9.5b Charging.** Use a real protected cell at 3.5–3.9 V, a 5 V ≥ 1 A USB source, and keep the system idle
(LEDs and OLED off).

| Check | Pass |
|---|---|
| Battery current in constant-current phase (DMM in series with the pack, e.g. across the open breakout jumper) | **380–420 mA** (ICHG 400 mA, ILIM ≈ 475 mA) |
| STAT0 CHG_STAT sequence | CC → CV → done |
| VBAT at "done" (measured at base TP2) | **4.18–4.22 V** (VBATREG 4.20 V ±0.5 %) |
| Termination current | ≈ 40 mA (ITERM 10 %) |
| Board temperature beside the BQ25180 after 15 min, 25 °C ambient | < 60 °C **[TVP]**. Dissipation (5.0 − 3.7) V × 0.4 A ≈ 0.52 W gives a ≈ +27–35 °C junction rise ([power research]); TREG 100 °C throttles beyond that |
| Charge current with LEDs on | Drops (DPPM). This is expected, not a fault |
| SYS stability on USB: LED ring stepped 0 → full white (≈ 0.7 A) for ≤ 1 s, real pack fitted | VSYS settles without sustained ringing; record the dip. Do not add VSYS bulk to tame it: the SYS capacitance is already close to the BQ25180's 100 µF maximum (SPEC §3; hardware/sim, NF-2) |
| JEITA: warm RT1 gently above 45 °C (hand warmth or a hair dryer, not hot air) | Status shows the warm condition and charging adapts |

The supported VBUS range is 4.5–5.25 V. At about 5.5 V the BQ25180 input overvoltage protection (5.5 V minimum)
may stop charging and the unit runs from the battery; that is not a fault (SPEC §3; hardware/sim, NF-4).

**B-9.5c Ship mode, shutdown, hardware reset.**

| Action | Expected |
|---|---|
| Write 0x09 = **0x49** (ship) | SYS off within ms. Wake by holding the press ≈ 2 s, or by plugging USB |
| Write 0x09 = **0x29** (shutdown) | SYS off. Wake **only** by USB |
| Hold the press 20 s (after the init writes) | Hardware reset at 18–22 s: SYS off, back on ≈ 1 s later. Test on battery alone **and** with USB present, and record both (EN_PUSH is described as "on battery only"; B-8.7 route a depends on this) |
| Hold the press > 11 s with the BQ25180 at power-on defaults (no init writes since POR) | Ship mode (default MR_LPRESS 10 s, PB_LPRESS_ACTION = ship) |
| Pack current at the ship-mode wake (SYS starts empty), current probe at the breakout | No BATOCP trip, SYS comes up first time; record the peak (hardware/sim, LDO-4, NF-2) |
| Plug USB with the bench "battery" at 3.0–3.1 V (lowered while running, dummy load per B-1), +3V3 on the scope at 20 MHz bandwidth | +3V3 peak < 3.5 V (SSD1351 VCI maximum). SPICE gives 3.42–3.45 V while the LDO leaves dropout; repeat warm (hardware/sim, LDO-5) |

The currents for these modes are measured in B-10.

**B-9.5d Press network** (battery connected; SPEC §3).

| Node | At rest | Pressed |
|---|---|---|
| SW_GATE (base) | ≈ 0 V | ≈ VBAT |
| BTN_N (main, P1.10) | 3.3 V | **< 0.4 V** |
| TS/MR (base) | NTC bias level | < 90 mV (pulled down by Q1; charging pauses during a press, as the datasheet specifies) |
| BTN_N release time | | < 1 ms |
| TS/MR release (R4 100 kΩ discharges the Q1 gates) | | Back at the NTC level within ≈ 40 µs (SPICE worst case 38.5 µs, hardware/sim, charger_ts-2) |

Also confirm a press wakes the nRF from System OFF through SENSE on P1.10.

**Press while charging** (USB, real pack in CC). Press for about 1 s, then read STAT0, STAT1 and FLAG0 and watch
CHG_INT_N. Record whether the BQ25180 reports a TS fault or hot zone, or pulses /INT, and confirm charging
resumes after release. A press pulls TS/MR below every TS threshold, so firmware MUST ignore TS_STAT, TS_FAULT and
TS interrupts while BTN_N is low and for 5 ms after (SPEC §3; hardware/sim, charger_ts-v2).

Known hazard ([power verifier]): a very hot NTC (≈ 68 °C on USB, ≈ 84 °C on battery) reads as a press on TS/MR.
That can cause reset loops in a hot car. It is outside the cell's rating; log it, do not chase it.

### B-9.6 TMAG5273A2 (encoder)

**B-9.6a Identity** ([datasheet](https://www.ti.com/lit/ds/symlink/tmag5273.pdf)):

| Register | Expected |
|---|---|
| ACK at 0x35 on TWIM0 | Yes |
| MANUFACTURER_ID 0x0E / 0x0F | 0x49 / 0x54 ("TI") **[TVP]** |
| DEVICE_ID 0x0D bits [1:0] | 2 (×2 range variant, ±133/266 mT) **[TVP]** |

**B-9.6b Bench readout (no rotor).** Write DEVICE_CONFIG_2 (0x01) = 0x02 (continuous), SENSOR_CONFIG_1 (0x02) =
0x70 (X, Y, Z) and SENSOR_CONFIG_2 (0x03) = 0x00 (±133 mT). Read 6 bytes from 0x12. **B[mT] = code × 133 / 32768.**

| Check | Pass |
|---|---|
| \|B\| with no magnets near | < 0.2 mT (Earth's field plus offset) |
| A test magnet brought near | Large, consistent change, mostly on Z |

The part powers up in standby (≈ 0.45 mA). Firmware must put it to sleep or Wake-up&Sleep mode (checked in B-10).

**B-9.6c With the rotor installed** (assembly Stage E, after the main board is seated in Stage D). Turn the ring
slowly by hand through one full revolution while logging X (tangential) and Z.

Expected element-to-magnet gap: the board underside is at z = 29.1 and the track face at z = 25.6. The Hall
element is 0.73 mm below the package top, and the SOT-23-6 body height varies 0.9–1.45 mm, so the gap is
**≈ 2.8–3.3 mm**. The detent model for the Ø2×2 alternating track gives Bt/Bz amplitudes of 15/18 mT at 3 mm,
40/51 mT at 2 mm and 6/7 mT at 4 mm ([detent research]).

| Check | Pass |
|---|---|
| X and Z waveforms | Sinusoids in quadrature, **exactly 24 periods per revolution** |
| Bz peak | 12–25 mT |
| Per-pole amplitude | Within ±15 % of the mean |
| ≥ 40 mT | Gap ≈ 2 mm: look for rubbing |
| ≤ 7 mT | Gap ≥ 4 mm: stack-up error |
| A missing or doubled period, or a phase jump | Reversed or missing magnet. Note its position from the witness mark (assembly §8) |
| Reading change when the carriage moves PARK ↔ CLICK at a fixed rotor angle | < 0.1 mT (the detent magnet is about 58 mm away; ≈ 0.02 mT stray) **[TVP]** |

**B-9.6d Tracking and wake modes** ([sensing verifier]).

* Tracking: XZX, 4× averaging, about 3.1 kSPS. The oscillator is untrimmed (up to about +10 %), so measure the
  INT period on P0.27 with the scope (10 µs pulses). Current ≈ 2.3 mA TMAG + ≈ 0.3 mA pull-ups.
* Wake-on-rotation (W&S, 10 ms): arm at rest, then turn the ring slightly. INT must latch low within a few
  degrees **[TVP]**.
* After a threshold INT the TMAG sits in standby (0.45 mA) until re-armed. Confirm firmware re-arms it every
  time.

### B-9.7 Piezo (PKMCS0909E4000-R1)

Drive BUZZ_A (P0.12) and BUZZ_B (P1.08) as complementary PWM at **4.0 kHz** (resonance) from one PWM instance.
Each pin reaches BZ1 through 470 Ω (R57, R58); R59 (1 MΩ) across BZ1 bleeds shock-generated charge while the
pins are disconnected in sleep (`sensors.py`).

| Check | Pass |
|---|---|
| Each pin on the scope (nRF side of R57/R58) | 0–3.3 V, opposite phase |
| Tone | Clear |
| Level at 10 cm (phone SPL app, indicative only) | ≈ 72–79 dB(A). Murata specifies ≥ 65 dB(A) at ±1.5 V0-p ([leds research/verifier](https://www.lcsc.com/product-detail/C910763.html)) |
| Tick: 1–2 cycles | Audible click |

### B-9.8 LED ring (48× WS2812C-2020-V6)

**B-9.8a VLED switch.** Bench into J2 at 3.7 V, 300 mA limit. With LED_PWR_EN (P1.04) low, VLED < 50 mV. Then
assert LED_PWR_EN and scope VLED and VSYS together.

| Check | Pass |
|---|---|
| VLED rise time (10–90 %) | **≈ 1.5–2.5 ms** (C7 = 1 nF from CT to VIN: tR = 1.6 µs/pF at 3.6 V) |
| Turn-on time, LED_PWR_EN high to VLED at 90 % | ≈ 3.8 ms (tON = 3.8 µs/pF at 3.6 V); record it |
| Inrush | ≤ ~100 mA |
| VSYS dip during enable | ≤ 100 mV |
| VLED steady | VSYS − I × RON (RON = 90 mΩ typ, 110 mΩ max at 3.6 V and 25 °C; 80 mΩ is the 5 V figure) |
| VLED fall to 10 % after LED_PWR_EN low (record tFALL) | **≤ 30 ms**, expected ≈ 20–27 ms: QOD (150 Ω typical) plus R4 (68 Ω) into ≈ 49 µF nominal (SLVSDW8B §9.3.3). SPICE: ≈ 24 ms nominal, 26.6 ms worst case (3.48 V start, C8/C9 +20 %, DC bias), 25.7 ms from 4.2 V (SPEC §5.1; hardware/sim, LSW-2, `test_u2_qod_discharge_tolerance_extremes`). The datasheet tFALL row implies an internal QOD nearer 170 Ω, so a reading of 27–30 ms passes but log it (hardware/sim, NEW-4). Above 30 ms fails: firmware waits ≥ 30 ms ([`firmware.md`](firmware.md) §6.4, test 12) |

Timing and RON are from [TPS22917 SLVSDW8B](https://www.ti.com/lit/ds/symlink/tps22917.pdf) §7.5–7.6. The
`main_power` sheet has C7 (1 nF/50 V) from CT to **VSYS**, the switch's VIN (assembly §2.4 item 3, done). If VLED
rises in tens of µs and VSYS dips hard, C7 is missing, open or the wrong value; check it before running any LED
test. (The TPS22918 takes CT to GND, which is why SPEC §5.1 rules it out as a drop-in.)

**B-9.8b Data timing.** Use Zephyr `worldsemi,ws2812-i2s` on i2s0 with `clock-source = "PCLK32M_HFXO"`,
`chain-length = <48>`, GRB, `lrck-period = <10>` (3.2 MHz), `nibble-zero = <0x8>`, `nibble-one = <0xC>` and
`reset-delay = <300>` ([leds verifier](https://docs.zephyrproject.org/latest/build/dts/api/bindings/led_strip/worldsemi,ws2812-i2s.html)).
The driver default nibble 0xE violates T1L, so it must be overridden. P0.06 MUST use
`nordic,drive-mode = <NRF_DRIVE_H0H1>` in its default pinctrl state, because standard drive does not guarantee the
WS2812C T1H/T0L/T1L windows (hardware/sim, LED-DATA-V1), and the image MUST request the HFXO and wait for it
before every frame: on the HFINT (±8 %) the I2S timing breaks T1H/T0L (hardware/sim, LED-DATA-V2). Scope LED_DIN at
D101's DIN, after **R40** (220 Ω at the nRF pin, LED_DIN_MCU → LED_DIN_R) and the 0 Ω R43 (LED_DIN_R → LED_DIN).
R40 is deliberately larger than
a typical 33 Ω damping resistor: it limits the current into the DIN clamp diode if P0.06 is ever high while VLED
is off (SPEC §5.4). With the DIN input capacitance it also slows the edges a little, so check the edges as well
as the timing. If the level-shifter option is fitted (U43 instead of R43, B-9.8f), D101 sees U43's VLED-level
output; the same table applies:

| Parameter | Expected | V6 spec ([datasheet](https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf)) |
|---|---|---|
| Bit period | 1.25 µs | |
| T0H | 312.5 ns | 220–380 ns |
| T1H | 625 ns | 580 ns–1 µs |
| T0L | 937.5 ns | 580 ns–1 µs |
| T1L | 625 ns | 580 ns–1 µs |
| Reset gap | ≥ 280 µs | |
| Ringing | < 0.5 V | |

**Sequencing** (SPEC §5.1, §5.4): enable VLED and wait **≥ 10 ms with P0.06 low** before the first frame, so VLED
is ≥ 2.5 V before DIN goes high (tON ≈ 3.8 ms; hardware/sim, LED-DATA-V4). To turn off: send an all-zero frame,
drive P0.06 low, release LED_PWR_EN, then wait ≥ 30 ms before re-enabling VLED or treating it as off (LSW-2).
Firmware, the bring-up image included, MUST never drive P0.06 high while VLED is off: QOD holds VLED at 0 V, the
DIN input limit is VDD + 0.7 V, and DIN would back-power the ring through its ESD diode (hardware/sim, LSW-3). Only
the DNP U43 (Ioff) option, fitted with R43 removed, lifts this rule.

**B-9.8c Walk test.** Light one LED at a time at 10 % red, starting from **D101 (SPEC LED1, firmware index 0)
at θ = 0° (the USB-C side)** and stepping **CCW seen from the top** through D148. Repeat in green and blue. Each step must light
exactly one LED in the right place. A dead LED blanks everything after it.

**B-9.8d End of chain.** Send 49 pixel words. The 49th word must appear on **TP40** (LED_D48, D148's DOUT, pulled
down by R42) on the scope, which proves every LED passes data.

**B-9.8e Current** (VSYS 3.7 V):

| Pattern | Expected |
|---|---|
| VLED on, all pixels 0 | Record. Standby is ≤ 1 µA/LED by datasheet; the "operating" current per IC is unknown, possibly ≈ 0.2 mA each **[TVP]** |
| One LED, one channel at 255 | ≈ 5 mA above baseline |
| Whole ring white at 10 % | ≈ 72 mA (48 × 3 × 5 mA × 0.1) |
| Whole ring white at 25 % | ≈ 180 mA |
| **Once only**, full white ≤ 2 s at a 1 A limit | ≈ 0.72 A; VLED droop ≤ 100 mV; no reset |
| PWM phase alignment: ring at 10 % white right after LED_PWR_EN, VLED current on the scope (current probe on the VLED side, or a shunt in the bench lead) | Record the peak and whether the 48 LEDs' PWM phases stay aligned or drift apart. Aligned, the sum current pulses to the full-on value of the lit channels (≈ 0.72 A for the whole ring) at the LED PWM rate, not the 72 mA average (hardware/sim, PI-2) |

Firmware cap: **300 mA burst / 150 mA sustained** ([leds research]), and on top of it an instantaneous budget of
lit channels × 5 mA, scaled with VBAT (0.19 A at 3.48 V up to the full ring at ≥ 3.90 V, less ≈ 0.23 A while the
actuator moves), because aligned PWM draws the full peak (SPEC §5.4; hardware/sim, PI-2). The limiter MUST be
active from the first frame after reset (PI-1). If the WS2812**B**-2020-V6 (12 mA/ch) was fitted instead, full
white is 1.73 A: never test it; it needs the instantaneous cap (≈ 1.0 A at full battery) from first boot
(hardware/sim, PI-3).

**B-9.8f Logic margin.** Run the walk test for 10 min with VSYS at 4.6 V (bench), then at 3.4 V. Reach 3.4 V by
starting at 3.7 V and lowering the supply while the unit runs: a cold start at 3.4 V on BAT may stay off
(VBATPOR, B-1). Run it with the H0H1 drive and HFXO of B-9.8b. There must be no glitches. At VSYS 4.59 V (SYS_REG
4.5 V + 2 %) the DC high-level margin at D101 DI is +41 mV on the nRF datasheet bound (VOH = VDD − 0.4 V) and
+427 mV with realistic drive; with firmware's SYS_REG 4.4 V it is ≈ +116 mV. The tightest pulse width is T1H, 15 ns
of margin (SPEC §5.4; hardware/sim, LED-DATA-2). The 4.6 V run is above every SYS_REG value firmware may use, so it
is the stress case, and the margin has to be measured, not assumed. If the run at 4.6 V glitches and B-9.8b
timing is clean, fit the level-shifter option: remove R43, fit U43 (SN74LV1T34DBVR, powered from VLED) and C43
(100 nF), both DNP by default (SPEC §5.4, `leds.py`), then repeat B-9.8b and this test.

**B-9.8g Low battery.** At VSYS 3.4–3.5 V with white at 25 %, record the colour shift. Firmware derates below
3.50 V, and when the loaded VSYS falls below about 3.3 V (WS2812C VDD minimum) it MUST send an all-zero frame and
drop LED_PWR_EN (SPEC §5.4; hardware/sim, LED-DATA-3).

**B-9.8h Thermal.** Run 10 min at the 150 mA sustained cap. Board temperature rise near the ring ≤ 15 °C
**[TVP]**.

### B-9.9 OLED (SSD1351, NHD-1.5-128128G)

**B-9.9a Bare boost: panel NOT fitted.** Bench at 3.7 V into J2, 500 mA limit. Run the OLED tests with a
battery or bench "battery" on J2, never on USB alone: firmware MUST never set OLED_VCC_EN while the BQ25180 input
limit is 100 mA (TMR_ILIM = 0xC9) unless the battery can supplement SYS (no BUVLO_STAT, VBAT ≥ about 3.15 V),
because the 100 mA input cannot carry the boost inrush and a dead-battery unit then reboot-loops (SPEC §5.3;
hardware/sim, NEW-1, OLED-V1).

| Check | Pass |
|---|---|
| OLED_VCC_EN (P1.02) low | OLED_VIN < 50 mV (U21's QOD holds it), +13V_OLED ≈ 0 V |
| OLED_VCC_EN high: OLED_VIN | ≈ VSYS once U21 is on |
| OLED_VCC_EN high: OLED_VIN, VSYS and the U21 input current on the scope | OLED_VIN rise ≈ 1.5–2.5 ms (U21 has C37 = 1 nF from CT to VIN, like U2 in B-9.8a); VSYS dip ≤ 100 mV (SPICE ≈ 25 mV). Inrush through U21 ≈ 0.3 A for about 2 ms, **0.4 A peak**, set by the TPS61040 soft start, not by C37: the boost starts at its ≈ 1.5 V UVLO while U21 is still ramping (SPEC §5.3; hardware/sim, LSW-4, OLED-BST-3). Record the peak **[TVP]** |
| U21 temperature right after the first enable (finger or IR) | No noticeable rise: SPICE gives ≤ 0.65 mJ per turn-on (hardware/sim, LSW-4) |
| OLED_VCC_EN high: +13V_OLED | **12.7–13.3 V** (1.233 V × (1 + 499/52.3) = 13.00 V). This is a pass/fail screen on **every board**, repeated as a production test (SPEC §5.3; hardware/sim, OLED-BST-1) |
| Input current, no load | < 2 mA (TPS61040 IQ 28 µA + 24 µA divider + switching) |
| SW node on the scope | Clean PFM bursts; tune CFF C40 22–100 pF (SPEC 33 pF) if it is erratic or audible |

**Abort above 13.5 V** (panel limit; Orient abs max 16 V) or below 12.5 V. The datasheet worst case with the
R26/R27 divider (0.5 % / 0.1 %) is about 12.6–13.4 V before the FB bias-current term ([display verifier](https://www.ti.com/lit/ds/symlink/tps61040.pdf)).
The TPS61040 FB bias current (1 µA maximum) through R26 can move VCC by a further ±0.5 V. A lower-value divider
would cost about 21 µA of sleep current, so rev A keeps the parts and accepts the risk, which is why the
12.7–13.3 V window above screens every board (hardware/sim, OLED-BST-1).

Turn the boost off and **discharge +13V_OLED with 1 kΩ** before fitting the panel. It only decays through
551 kΩ (τ ≈ 6–7 s).

**B-9.9b Panel** (after B-7 and B-8.7, fitted per assembly §7.4, Stage F). Bench supply at 3.7 V with a 500 mA
limit on the breakout tail's board side, jumper open (J2 is buried by then, B-1).

With VCC_EN low, +13V_OLED floats at about VCI − Vf (≈ 2.5–3 V) through the panel's internal ESD path. That is
expected ([display verifier]). D21 then leaks backwards into OLED_VIN, where U21's QOD sinks it: ≈ 5.4 µA at
25 °C, ≈ 30 µA at 60 °C, an accepted sleep cost for rev A (SPEC §5.3). Measure, with VCC_EN low:

| Node | Pass |
|---|---|
| +13V_OLED | ≈ 2.5–3 V (record) |
| OLED_VIN | < 50 mV (SPICE: 0.05–5.4 mV over −10…60 °C), so the TPS61040 (EN tied to VIN) stays off |
| FB (OLED_BST_FB: U20 pin 3, the R26/R27/C40 node) minus OLED_VIN | **< 0.30 V** (TPS61040 FB abs max VIN + 0.3 V); record it. SPICE gives 0.26 V for a generic panel ESD clamp and up to 0.29 V for a very strong one, so the margin is thin (SPEC §5.3; hardware/sim, LSW-1). A unit at or above 0.30 V is logged for rev B and not shipped |

Bring-up sequence ([NHD datasheet](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf),
[SSD1351](https://cdn-shop.adafruit.com/datasheets/SSD1351-Revision+1.3.pdf)):

1. RES# low ≥ 2 µs (use 10 µs), then high.
2. Vendor init, including `A0 74` (65k RGB565), `B4 A0 B5 55` and `C7 08–0A`.
3. Clear GDDRAM.
4. VCC_EN high.
5. Wait **≥ 200 ms** (vendor). Firmware may shorten this after VCC settling has been measured, but MUST never
   wait less than 10 ms, which covers U21's tON and the boost soft start (SPEC §5.3; hardware/sim, OLED-V2).
6. `AF`.

SPI settings: SPIM3 (SPEC §4), mode 0, **16 MHz** in operation ([`firmware.md`](firmware.md) §7.1). For first
light, start at 8 MHz, then go to 16 MHz. **Never above 20 MHz** (SSD1351 t_cycle ≥ 50 ns), so SPIM3's next
step, 32 MHz, is out. Both SPIM3 errata workarounds are part of the design:

* Anomaly 198 ([errata 198](http://docs.nordicsemi.com/r/bundle/errata_nrf52840_rev3/page/err/nrf52840/rev3/latest/anomaly_840_198.html)):
  SPIM3 TX buffers must sit in a dedicated RAM AHB slave that the CPU does not access during the transfer, with
  `CONFIG_NRF52_ANOMALY_198_WORKAROUND`. Any dedicated 8 KB slave works. **This project uses slaves 0 and 1,
  0x20000000–0x20003FFF**, with sram0 moved up to 0x20004000 ([`firmware.md`](firmware.md) §7.1). Check in
  `zephyr.map` that the SPIM3/LVGL buffers land there and nothing else does.
* Anomaly 195: after disabling SPIM3, write 1 to 0x4002F004, otherwise the peripheral keeps drawing about 900 µA.
  nrfx does this on uninit; B-10 confirms it.

Fallback: SPIM2 at 8 MHz on the same pins (no errata, about 30 fps). It is a devicetree-only change and gives up
SPIM2 as the LED-driver fallback ([`firmware.md`](firmware.md) §7.1).

| Test | Pass |
|---|---|
| Colour bars; solid R/G/B at `C7` = 0x08 | Uniform |
| Single-pixel grid every 8 px | No missing rows or columns. Missing lines usually mean the FPC is not fully in the ZIF |
| Orientation | Upright, centred on the active area (the 1.47 mm offset is mechanical) |
| SCK at the ZIF on the scope | t_R/t_F ≤ 15 ns, t_CLKL/H ≥ 20 ns. If not, use H0H1 drive ([display verifier]) |
| Current (battery side, VSYS 3.7 V): black with VCC on | ≈ 5 mA |
| Typical dark UI | ≈ 14–26 mA |
| Full white **only at `C7` = 0x08, briefly** | Well under the ≈ 146 mA maximum-contrast figure ([display research]) |
| Below rested VBAT 3.75 V, and while the LED current exceeds its 150 mA sustained cap | Firmware MUST hold `C7` ≤ 08h and ≤ 30 % white area: at low VSYS the boost has almost no headroom over the full-white current, about 33–40 mA at 3.0 V (SPEC §5.3; hardware/sim, OLED-BST-2) |
| Sleep: `AE`, `AB 00`, VCC_EN low, RES# held high | OLED + boost ≈ 17.6 µA typ at 25 °C, including ≈ 5.4 µA of D21 leakage; 46 µA maximum at 25 °C, 72 µA at 60 °C (architecture §8.2; measured in B-10) |
| Wake: `AB 01`, VCC on, ≥ 200 ms, `AF`, full redraw | Image back in about 0.2–0.4 s |
| Listen at near-black | No audible PFM whine (about 15 kHz at 1.5 mA). If present, see the CFF note above |

### B-9.10 Detent driver (2× DRV8837), home sensor, actuator

Run B-9.10a–c on the bench at assembly Stage A8, with the actuator, carriage and detent magnet mounted on the main
board and the motor lead in J40, and finish at PARK with all IN low and nSLEEP low. J40 and the carriage cannot be
reached once the board is seated. Repeat B-9.10c and run B-9.10d on the rotor in Stage E.

**B-9.10a Drivers, motor disconnected.** Pins: driver A IN1/IN2 = P0.26/P0.05, driver B = P0.07/P0.11, shared
nSLEEP = P1.15 (SPEC §4).

| nSLEEP, IN1, IN2 | OUT1 / OUT2 |
|---|---|
| 0, x, x | Hi-Z (sleep, ≤ 0.24 µA for both drivers) |
| 1, 1, 0 | VSYS / 0 |
| 1, 0, 1 | 0 / VSYS |
| 1, 1, 1 | 0 / 0 (brake) |
| 1, 0, 0 | Hi-Z (coast) |

Both drivers must show all five states ([DRV8837](https://www.ti.com/lit/ds/symlink/drv8837.pdf)).

**B-9.10b Motor.** Check coil pairs ≈ 20 Ω (VSM08102; measure yours): A on J40 pins 1–2, B on 3–4. Also log each
phase's inductance (LCR meter): the coast energy that VSYS must absorb when a move ends scales with it
(hardware/sim, MD-5). Set a 600 mA limit.

| Check | Expected |
|---|---|
| Full steps at 100 PPS, ≤ 50 % amplitude | Smooth motion, 0.02 mm per full step |
| Full stroke | 375 full steps = 7.5 mm |
| Phase current at 100 % | ≈ 185 mA (3.7 V) to 225 mA (4.5 V) |
| Supply peak | ≤ 0.45 A |
| After every move, and on every stop path including FAULT and abort | Brake (IN1 = IN2 = 1 on U40 and U41 for ≥ 3 ms), then all IN low and nSLEEP low, so hold power is zero (the lead screw self-locks) ([detent research]). Firmware MUST brake before sleep: coasting both coils dumps their energy into VSYS, and on USB after charge termination nothing but the VSYS capacitors absorbs it. Never run full-current full steps on USB power (SPEC §5.6; hardware/sim, MD-1) |

**B-9.10c Home sensor.** HOME_N (P1.14) comes from a DRV5032FA (U42, top side, r 21.5, θ 90°): push-pull,
low = magnet present, always powered, sampling at 13–37 Hz. Wait ≥ 75 ms before reading after a move. Log HOME_N
against step count over park → click → park at 50 PPS. Firmware learns the same two edges at 80 PPS in its
factory test 19 ([`firmware.md`](firmware.md) §5.4).

| Position | Expected |
|---|---|
| Within ≈ 4–5 mm of PARK | HOME_N low ([detent research]; firmware.md §5.4 simulates the assert edge 3.8–4.6 mm and the release edge 4.1–5.0 mm from the stop). **Required** |
| At the CLICK end (x = 0) | HOME_N high. **Required** (firmware test 19): a unit that reads HOME at click is rejected or reworked (firmware.md §18 item 2) |

**Why a unit can read HOME at click.** SPEC puts the DRV5032 on the **top** side, so the die sits only
≈ 2.4–2.8 mm above the magnet (firmware.md §5.4 stack-up), against the research's 3.0–3.5 mm. Moving toward
click, HOME releases 4.1–5.0 mm from the stop, the field passes through zero about 5–6 mm out and then comes back
with the opposite sign: |Bz| at full click is 1.0–1.4 mT for a 2.4–2.8 mm die (0.47 mT at 3.5 mm). The DRV5032FA
is omnipolar with BOP 1.5 / 3 / 4.8 mT (min/typ/max,
[DRV5032 SLVSDC7H](https://www.ti.com/lit/ds/symlink/drv5032.pdf)), so the margin to BOP min is only 0.1–0.5 mT, and a unit with a low die or a strong magnet may assert HOME at click. Firmware does
not rely on HOME for position: the **mechanical stall at the park stop is the only position reference**, HOME only
confirms it after the stall, and HOME is ignored at x < 2 mm in normal moves (firmware.md §5.4). Test 19 screens
out units that assert at click, because firmware then takes "HOME asserted" to mean the park zone. Log the click
reading on every unit for rev B (sensor further from the magnet, or a DRV5032 variant with more margin).

**B-9.10d Homing and stroke.** Use the firmware homing procedure (firmware.md §5.4, phases H0–H5).

1. From an unknown position, approach PARK at run current until HOME asserts. That edge lies ≈ 190–230 steps
   before the stop, so it does **not** mark the stop. Run in, then finish at **80 PPS and 50 % current** into the
   park stop with 20 steps of overdrive. Park is force-free, so stalling there is safe. HOME must read asserted
   after the stall; back off 4 steps.
2. Define s = 0 at the park stop (after the back-off the carriage sits at s = 4, x_park). Step out to CLICK
   (s = 375) and back. On the way back, HOME must assert inside the edge window around the learned assert step
   (firmware.md §5.4 rule 2; 32 steps wide at 80 PPS, 60 at 446 PPS). Otherwise re-home; after
   3 failures go to FAULT and stay in FREE ([detent research]).
3. Speed profile: ≤ 300–500 PPS through the magnetically loaded 0–4 mm zone, ≤ 800–1000 PPS beyond. Expect
   ≈ 0.6–0.9 s per full stroke ([detent verifier]).

**Robustness:** 50 round trips with the rotor resting in a detent well. HOME must read asserted after every park
stall, and every HOME edge must fall inside its window (no E_DET_STEPS; firmware test 19 runs 20 cycles).

### B-9.11 NFC tag (Stage F, coil soldered to J11 and the top cover on)

The NFCT drives the cover coil through J11 (main top, r 21.5, θ 222°), tuned by C16/C17 = 180 pF C0G to GND,
which suits a coil of about 1.4–1.5 µH (SPEC §5.2). NFCPINS must read NFC mode (B-7.3).

1. Before soldering the coil, measure its inductance. If it is outside 1.4–1.5 µH, recompute C16/C17 with the
   `mcu` sheet formula Ctune = 2 / ((2π × 13.56 MHz)² × L) − Cp − Cint (Cint ≈ 4 pF) **[TVP]**.
2. Run an NFC-A Type 2 tag image (NCS `nfc_t2t`, e.g. a text-record sample) **[TVP: sample name in the NCS
   version used]**. A phone must read the NDEF record through the top cover; record the best phone position and
   the largest reliable distance.
3. If firmware arms it, a phone's field must wake the unit from System OFF.

---

## B-10. Sleep and mode currents (PPK2)

### Setup

1. J2 is buried in an assembled unit, so connect the PPK2 to the **battery breakout tail** (assembly §7.2):
   * **Source mode** (preferred for targets): jumper open, PPK2 output to the board-side BAT+ wire, GND to GND.
     Power up at **3.7 V**, then repeat the key modes at 4.2 V and at 3.4 V, reaching 3.4 V by lowering the
     voltage while the unit runs (a cold start below VBATPOR = 3.08–3.46 V may stay off, B-1).
   * **Ammeter mode**, in series with the real pack: VIN to the pack-side wire, VOUT to the board-side wire,
     GND to GND, jumper open.

   On the bench (Stage A/B), the PPK2 can go straight onto J2 (pins 1–2 +, pins 3–4 GND, through an SHR-04V-S
   lead) with the pack removed.
2. **Unplug USB.** Remove the TC2030 cable: the probe back-powers the chip through VTref and SWDIO. Disable RTT
   and UART logging.
3. Enter the mode, wait 10 s, then average over a ≥ 10 s window. TMAG wake samples, the BQ25180 TS bias pulses
   (every 200 ms), DRV5032 sampling (about 20 Hz) and BLE events are all periodic.
4. Measure at 20–25 °C. With the panel fitted, D21's reverse leakage rises steeply with temperature (≈ 5.4 µA at
   25 °C, ≈ 30 µA at 60 °C; SPEC §5.3), so a warm unit reads high.

In both modes the pack's own protection circuit (PCM) is outside the measurement. Real battery drain is the
reading plus about 3–6 µA. Readings below about 1 µA are at the instrument floor.

### Targets per mode

The targets are derived from datasheet typicals at 25 °C ([TVP]); the panel-fitted rows include ≈ 5.4 µA of D21
leakage through U21's QOD, which SPEC §5.3 accepts for rev A (hardware/sim, SLEEP BUDGET). For comparison, the
SPICE sleep total (System ON idle with rotation and motion wake, pack PCM included) is 37.4 µA at VBAT 3.7 V and
25 °C (architecture §8.2). Tighten the targets after the first good unit.

| Mode | How to enter | Expected typ | Pass |
|---|---|---|---|
| **Shutdown** | BQ 0x09 = 0x29 | 0.015 µA (BQ) | ≤ 1 µA (floor) |
| **Ship** | BQ 0x09 = 0x49 | 3.2 µA (BQ only) | ≤ 4.5 µA ([BQ25180](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) |
| **System OFF, press wake only**, panel fitted | nRF System OFF; TMAG sleep; IMU power-down; flash deep power-down; OLED `AE` + `AB 00` + VCC off | ≈ 27–30 µA | ≤ 35 µA |
| Same, panel not fitted | | ≈ 11–13 µA | ≤ 16 µA |
| **System OFF + rotation and motion wake** | Above, plus TMAG W&S at 100 ms and IMU low-power at 12.5 Hz | ≈ 32–35 µA | ≤ 40 µA |
| **System ON idle, armed** (no BLE) | Zephyr idle, TMAG W&S at 10 ms, IMU wake | ≈ 50–56 µA | ≤ 65 µA |
| + BLE connected idle (15 ms interval, latency 30) | | + ≈ 7 µA | ≤ 75 µA |
| + BLE advertising at 1 s | | + ≈ 11 µA | ≤ 80 µA |
| Active controller: dark UI, LEDs off, tracking, BLE | | ≈ 20–30 mA | record |
| Game spin, LEDs at the 150 mA sustained cap | | ≈ 170–200 mA | record |

### Contribution budget (for debugging a high reading)

| Contributor | State | Typ µA | Source |
|---|---|---|---|
| BQ25180 | Battery mode, push-button enabled | 4 (5 max) | [BQ25180](https://www.ti.com/lit/ds/symlink/bq25180.pdf) |
| BQ25180 TS bias into the NTC | 38 µA (ITS_BIAS) pulsed about 4 ms per 200 ms | ≈ 0.8 (may already be in IQ) **[TVP]** | [BQ25180](https://www.ti.com/lit/ds/symlink/bq25180.pdf) §7.5; pulse timing [power research] |
| RT9080 LDO | Always on | ≈ 2 (4 max) at no load; the ground current at the real ≈ 20 µA sleep load is not specified (see below) | [DS9080](https://www.richtek.com/assets/product_file/RT9080/DS9080-07.pdf); hardware/sim, LDO-1, LDO-6 |
| VSYS divider 2.2 M + 1 M | Always on | 1.16 at 3.7 V | SPEC §3 |
| nRF52840 | System OFF / System ON idle (Zephyr, RTC); NFCT field sense, if armed, ≈ 0.1 more | 0.4 / ≈ 3 | [nRF52840 PS](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/_tmp/nrf52840/autodita/current/parameters.i_sleep.html), [mcu verifier]; SPEC §5.2 |
| DRV5032FA | Always on (SPEC §5.6) | 1.6 (3.5 max) | [DRV5032](https://www.ti.com/lit/ds/symlink/drv5032.pdf) |
| DRV8837 ×2 | Sleep | 0.07 (0.24 max) | [DRV8837](https://www.ti.com/lit/ds/symlink/drv8837.pdf) |
| W25Q128JV | Deep power-down / standby | ≈ 1 / tens of µA | [mcu research and verifier] |
| TMAG5273 | Sleep / W&S 100 ms / W&S 10 ms / **standby** | 0.005 / ≈ 3 / ≈ 17–20 / **450** | [TMAG5273](https://www.ti.com/lit/ds/symlink/tmag5273.pdf), modelled **[TVP]** |
| LIS2DW12 | Power-down / LP1 at 12.5 Hz | 0.05 / ≈ 1 (at 1.8 V; more at 3.3 V) | [sensing verifier] |
| OLED panel asleep (VCI/VDDIO always on) | ICI 4 + RES# 1 MΩ 3.3 + VCI→VCC ESD path into 551 kΩ ≈ 5 | ≈ 12 | [display verifier] |
| D21 (B5819W) reverse leakage from the ESD-held +13V_OLED (≈ 2.7 V) through U21's QOD, panel fitted | Always, while VCC is off | 5.4 at 25 °C (1.0 at −10 °C, ≈ 30 at 60 °C). OLED row total 17.6, maximum 46 at 25 °C | SPEC §5.3; architecture §8.2; hardware/sim, SLEEP BUDGET |
| TPS22917 ×2 (U2 VLED, U21 OLED_VIN); TPS61040 (U21 off, QOD holds OLED_VIN at ≈ 0 V) | Off | 0.01 each / ~0 | [power research]; hardware/sim, SLP-1 |

**RT9080 ground current at the sleep load.** DS9080 specifies IQ only at no load (2 µA typ, 4 µA max) and from
1 mA up, so the LDO's share of the sleep floor is a bring-up measurement. On a spare RT9080-33 on a breakout, PPK2
on VIN at 3.7 V, load VOUT with 0, ≈ 20 µA (165 kΩ) and ≈ 50 µA (66 kΩ) at 25 °C and warm: ground current = IIN −
ILOAD. If it is well above 2–4 µA, fit the TPS7A0233PDBVR alternate (SPEC §3; 25 nA IQ; check its EN/NC pins
against the footprint first) (hardware/sim, LDO-6, SLP-3).

### Excess current: likely causes

| Excess over target | Likely cause | Check or fix |
|---|---|---|
| ≈ +0.45 mA | TMAG left in standby, e.g. after a threshold wake that was never re-armed | Read DEVICE_CONFIG_2 and re-arm W&S |
| ≈ +0.9 mA | SPIM3 not fully off (anomaly 195) | Write 1 to 0x4002F004 after disable |
| ≈ +15 µA | A wake pin on a GPIOTE IN channel instead of PORT/SENSE (17.37 vs 2.36 µA) | Use `sense-edge-mask` |
| ≈ +70 µA | TMAG_INT_N latched low through its 47 kΩ pull-up | Read CONV_STATUS to clear it |
| +10–50 µA | QSPI flash not in deep power-down | Send B9h; enable the driver's power management; the sleep pinctrl must bias SCK and IO0–IO3 low (pull-down) (hardware/sim, SLP-4) |
| +60–170 µA | LIS2DW12 SA0 grounded (address 0x18) | Assembly/schematic fault |
| ≈ +33 µA on main, + ≈ 37–42 µA on base | BTN_N held low: switch pre-gap is 0. Main: R56 100 kΩ from +3V3; base: VBAT through R3 1 kΩ + R4 100 kΩ | Mechanical, assembly §11.3 steps 1 and 7 |
| Tens of µA, bursty; OLED_VIN ≈ 0.5–1.2 V in sleep | U21's QOD (pin 5) not connected to OLED_VIN (open joint): D21's leakage floats OLED_VIN and the boost hiccups (hardware/sim, SLP-1) | Reflow U21 pin 5 |
| Reading rises steeply when the unit is warm | D21 reverse leakage (≈ 30 µA at 60 °C) | Not a fault; measure at 20–25 °C |
| ≈ +5 mA | OLED VCC left on (black screen) | `AE` + VCC_EN low |
| mA level | VLED left on, logging backend active, CPU not sleeping | Check LED_PWR_EN, disable UART/RTT |
| Constant ≈ 1.6–3.5 µA | DRV5032 (always on by design) | Not a fault |

---

## B-11. RF: antenna S11 in the real enclosure, and link checks

The SPEC places a Molex 146153-0100 flex antenna (100 mm coax) on a printed shelf in the base cup at
z ≈ 5.5–6, along a chord near θ ≈ 90° (SPEC §8, assembly §7.1), connected by coax to the module's u.FL. There is
**no matching network** anywhere in the design, so tuning means placement or antenna choice.

### B-11.1 VNA setup

1. NanoVNA V2 / V2 Plus4 or LiteVNA. Sweep **2.0–3.0 GHz**, ≥ 401 points, with averaging or a low IF bandwidth.
2. SOL calibration at the SMA reference plane.
3. Add the **RF test pigtail** (1.13 mm coax, u.FL receptacle to SMA, assembly §4.3) and apply port extension:
   with the pigtail's u.FL end open, adjust the electrical delay until the trace collapses to a point on the
   right edge of the Smith chart across the sweep. Port extension removes delay, not loss. With the end open,
   |S11| reads −2 × the pigtail's one-way loss. Note that value and enter it as port-extension loss if the
   firmware supports it; otherwise every |S11| reading is that much better than the truth.
4. Every mate counts against the u.FL's ~30-cycle rating. Follow the sequence in assembly §7.1, use the
   extraction tool and log each cycle.
5. **Common-mode check.** The flex is coax-fed with no balun, so current on the outside of the pigtail's shield
   changes the result. For c–e, fit a clip-on ferrite on the pigtail outside the device, ≥ 30 mm from the magnet
   track, and lead the cable away at right angles to the device. Then grip and move the pigtail outside the
   device: if the minimum moves by more than ≈ 10 MHz or |S11| at the band edges by more than ≈ 1 dB, shield
   current is significant. Add a second ferrite further out or reroute, and record the spread **[TVP]**. Most
   clip-on ferrites lose effect well below 2.4 GHz, so the touch test, not the ferrite, is the real check.

### B-11.2 Measurements

Record the frequency of minimum |S11| and |S11| at 2400, 2440 and 2480 MHz for each:

| # | When (assembly) | Configuration | Purpose |
|---|---|---|---|
| a | Stage B4 | Antenna alone, pigtail mated, taped to foam ≥ 30 mm from anything | Baseline ([Molex 146153](https://www.molex.com/ja-jp/products/part-detail/1461530100)) |
| b | Stage B4 | Bonded on its shelf, cup only | Plastic loading |
| c | Stage B6 | Base complete: battery, base board (harness optional) | Nearby conductors |
| d | **Stage R** | **Full device**: pigtail fitted at D2 in place of the module mate, main board seated with all screws, rotor and base complete, top (OLED, light box, diffuser, cover) not yet fitted, on a wooden desk. Pigtail taped along the board underside at θ ≈ 200° and out round the board edge (assembly §11.4 D2; the Ø5 hole carries the spindle's M4 spigot), ferrite outside | **Acceptance** |
| e | Stage R | As d, on a metal plate (laptop lid or steel desk), and with a hand gripping the dial | Sensitivity. The antenna lies ≈ 6 mm above the desk (SPEC §8, assembly §7.1) |

The module's u.FL is on the main board's bottom side inside the bowl (SPEC §8), so d and e cannot be done by
taking the top off. The antenna has to be connected to the pigtail before the main board is seated, and swapped
to the module afterwards by lifting the board (assembly §11.4 D2, §11.5).

**Pass (d):** |S11| ≤ −10 dB from 2400 to 2483.5 MHz, after the pigtail-loss correction. **Marginal:** ≤ −6 dB
at the worst band edge, accepted only if B-11.3 passes **[TVP]** ([mcu research]). Case e is informative; record
how far it moves.

**Which units:** d/e are required on the first unit of a build and after any change to the antenna, cup, pack or
coax route. On later identical units they are optional (each costs two extra u.FL cycles and a board lift), and
B-11.3 is the per-unit RF gate.

**Tuning levers:**

* Move or rotate the flex on its shelf.
* Increase spacing to the battery, harness and coax.
* Change the shelf thickness or material under the antenna. Molex tunes these flexes for mounting on plastic of a
  stated thickness; check the 146153 data sheet.
* Dress the coax away from the radiator. If touching or moving the coax changes S11 a lot, common-mode current is
  flowing on its shield. Reroute it; do not use ferrite near the magnets.
* Alternative antenna: Molex 204281-0100 (C3283990) ([mcu research]).

A minimum below the band is typical of plastic loading, and the flex cannot be trimmed.

### B-11.3 Radiated and link checks

| Check | Method | Pass |
|---|---|---|
| RSSI vs a reference | nRF Connect for Mobile at 1 m and 5 m line of sight, fixed orientation, TX +4 dBm (then +8 dBm). Repeat with an nRF52840 DK at the same spot | DK minus device ≤ 10 dB at 1 m **[TVP]** |
| Link robustness | BLE HID to a PC at 5 m for 10 min, with LEDs and OLED animating | No disconnects, no visible dial stutter |
| Desense | At the distance where RSSI ≈ −85 dBm, compare disconnects and packet loss with display, LEDs and actuator idle vs running. Use the NCS `radio_test` sample for an RX error rate if available | No obvious degradation. Suspects: SPI harmonics (16 MHz × 150 = 2.4 GHz), LED I2S, boost switching |
| Desk material | Repeat link robustness on a metal desk | Record (expected worse) |

---

## B-12. Detent calibration

Prerequisites: B-9.6c (encoder on the rotor) and B-9.10d (homing).

**B-12.1 Encoder self-calibration (FREE, carriage at park).**

1. Spin at ≥ 3 rev/s for ≥ 3 s.
2. Fit an ellipse: X/Z offsets, gain ratio and skew ([sensing research]).
3. Confirm 24 electrical periods per revolution and per-pole amplitude within ±15 %.
4. Spin clockwise (seen from the top) to fix the sign convention.

**B-12.2 Detent phase (CLICK, offset 0).**

1. Step 375 from park.
2. Let the ring settle in a detent and record the rest angle.
3. Click through all 24 detents by hand, three times.

Pass: all rest angles within **±0.5° mechanical** of a 15.00° grid **[TVP]**. The predicted rest error from
friction is about ±0.24° ([detent research]). Store the mean rest phase: one value, since every well sits at the
same electrical phase.

**B-12.3 Strength LUT.** At each offset below, measure peak detent torque two ways:

* **Hanging mass / gram gauge:** wrap a thread round the knurled OD (r = 35 mm). Find the mass at which the ring
  slips past a detent. **T = m·g·0.035 m.**
* **Ring-down frequency:** nudge the ring within a well, release it and read f_n from the encoder.
  **T1 = I·(2π·f_n)² / 24**, with I ≈ 1.25 × 10⁻⁴ kg·m² (ring 1.215e-4 + magnets + carrier). Weigh the rotor
  and recompute **[TVP]**.

| Offset (mm) | Full steps from click | Simulated T (mN·m) | Slip mass at r = 35 (g) | f_n (Hz, I = 1.25e-4) |
|---|---|---|---|---|
| 0 | 0 | 16.4 | 47.8 | 8.9 |
| 0.5 | 25 | 15.4 | 44.9 | 8.7 |
| 1.0 | 50 | 12.8 | 37.3 | 7.9 |
| 1.5 | 75 | 9.4 | 27.4 | 6.8 |
| 2.0 | 100 | 6.2 | 18.1 | 5.5 |
| 2.5 | 125 | 3.7 | 10.8 | 4.2 |
| 3.0 | 150 | 2.0 | 5.8 | 3.1 |
| 4.0 | 200 | 0.55 | 1.6 | 1.6 |
| 5.0 | 250 | 0.14 | 0.4 | 0.8 |
| ≥ 7.5 (FREE) | 375 | ≤ 0.003 | — | — |

The simulated column is the detent research's magpylib model, verified to within about 1 %, but run at
R_t = 30 mm on the flywheel underside. SPEC uses R = 29.0 mm on the top face, so expect about ±10–20 %. Gap
sensitivity is about −10 % torque per +0.1 mm, and magnet grade spread about ±10 % ([detent research/verifier]).

Pass:

* Torque falls monotonically with offset.
* T(0) within ±25 % of 16.4 mN·m.
* The default user setting gives 10–12 mN·m (≈ 1.2–1.4 mm offset).

Store the measured LUT and map strength 0–100 % onto it.

**B-12.4 FREE residual.** At park:

* Turning the ring slowly by hand must show no ticking.
* Coast down from 5 rev/s 50 times and histogram the rest angle modulo 15°. It must be uniform, with no preferred
  bin (χ² test). The model gives ≤ 3 µN·m residual cogging ([detent research]).

**B-12.5 Ringing (informative).** At full click, release the ring from about 7° inside a well and count cycles
until it is below 0.5°. With about 0.15 N·mm of bearing friction, expect roughly 80 cycles (≈ 9 s at 8.9 Hz). The
detent is under-damped and SPEC has no friction shoe, so firmware must decide the landing detent at the first
velocity reversal ([detent verifier]). Record the count.

**B-12.6 HID mapping.** In CLICK mode, check that one physical click gives exactly one menu step in Windows
Wheel / Surface Dial settings. The firmware default reports 100 units (10.0°) per detent ([mcu research]), but
that assumes Windows' default RotationResolutionInDegrees is 10°, which the mcu verifier rated unverifiable;
`docs/architecture.md` says 150 units **[TVP]**. Test both 100 and 150 units per detent (it is a setting) in
Windows Wheel settings and in one app menu, record which gives exactly one step per click, and make that the
default ([`firmware.md`](firmware.md) Dial mapping notes the same open point).

---

## B-13. Spin-down acceptance (FREE mode)

**Conditions:**

* Detent parked (HOME asserted).
* Device on a level wooden desk at 20–25 °C.
* Bearing prepared per assembly §9 and run in (10 spins first).
* Rotor fully assembled and balanced: static balance (assembly §10.3) and the dynamic trim (assembly
  §10.4) already done.

**Procedure:**

1. **Hold the base cup only** with one hand, or tape the base to the desk, with no fingers on the top cover or
   the FA. Flick the ring above 10 rev/s with the other hand, then let go of the base. A 10 rev/s flick is
   ≈ 7.8 N average over ≈ 30 ms, against a slide threshold of 1.4–2.3 N and a tip threshold of ≈ 3.3 N
   ([mechanical verifier]), so an unheld unit slides or tips. Gripping the top instead presses the FA, which can
   cause false clicks and adds drag. **Discard any run in which the base moved.** Firmware logs ω(t) from the
   TMAG at ≥ 100 Hz (decimated).
2. Record the time from crossing **10.0 rev/s** down to **0.1 rev/s**.
3. Do 5 runs clockwise and 5 counter-clockwise. Report the median.
4. Fit **α = −a − b·ω** to each run. The Coulomb torque is T_c = I·a and the viscous coefficient is c = I·b.

**Pass:**

| Criterion | Value |
|---|---|
| Median spin time from 10 rev/s | **≥ 45 s minimum, ≥ 60 s target** ([mechanical verifier]: 40–120 s expected for an oiled 608) |
| Equivalent Coulomb torque | ≤ 0.175 N·mm for 45 s, ≤ 0.13 N·mm for 60 s (with I = 1.25e-4 kg·m²) |
| Viscous coefficient c | ≤ 1 × 10⁻⁶ N·m·s ([mechanical research]: 2e-7 gives 83 s, 1e-6 gives 71 s, 7e-6 from solid planes near the magnets gives 36 s) |
| CW vs CCW | Within 10 % |

**Diagnostics:**

| Result | Likely cause |
|---|---|
| < 15 s | Factory grease still in the bearing, or contact seals |
| 15–45 s with large Coulomb term a | Shield rub, too much oil, the rotor rubbing somewhere (listen), carriage not parked, a ferrous part near the track |
| 15–45 s with large viscous term b | Eddy drag: copper pour facing the track, aluminium or copper rotating near the detent magnet, battery foil too close |
| Fine at first, worse after days | Oil migrating or evaporating. Re-oil and repeat after one week **[TVP]** |

Informative: also run a click-mode spin from 5 rev/s at the default strength, and record its time and detent
count.

---

## B-14. Pass/fail checklist (one per unit)

| # | Step | Measurement | Pass criterion | Result |
|---|---|---|---|---|
| 1 | B-2 | BQ25180 X-ray | No bridges or opens | |
| 2 | B-2 | MDBT50Q X-ray | No bridges or opens | |
| 3 | B-2 | Visual: 48 LED orientation, polarised parts and IC pin 1 (incl. U12, U21, U32), ZIF type and J20 pins 1–2 free of bridges, DNP parts absent and R43 fitted, side-entry link and battery connectors | All correct | |
| 4 | B-3a | VSYS, +3V3, VLED to GND | > 1 kΩ (no short) | |
| 5 | B-3a | +13V_OLED to GND | 520–580 kΩ | |
| 5a | B-3a | VBUS ↔ VBUS_NRF; VBUS_NRF to GND | ≈ 4.7 Ω (R12); > 100 kΩ | |
| 6 | B-3b | Pull resistors, per net | Within ±10 % of the B-3b per-net value (e.g. MOT_NSLEEP ≈ 33 kΩ, LED_PWR_EN and OLED_VCC_EN 88–100 kΩ, VSYS_SENSE 0.7–1.0 MΩ), not of the bare resistor | |
| 7 | B-3c | CC1, CC2 to GND | 5.1 kΩ each | |
| 8 | B-3c | TS/MR to GND | 8–13 kΩ at 20–30 °C | |
| 9 | B-4a | Base VSYS on USB | 4.4–4.6 V; input < 5 mA | |
| 10 | B-4b | Base VSYS on bench battery | VBAT ± 50 mV | |
| 11 | B-5 | Main +3V3 | 3.20–3.40 V; supply < 10 mA unprogrammed | |
| 12 | B-5 | VLED, OLED_VIN off | < 50 mV | |
| 13 | B-6 | Linked, first power-up at 5.00 V / 100–150 mA into base VBUS TP: main VSYS, +3V3 | 4.4–4.6 V, 3.30 V; < 20 mA | |
| 14 | B-7.2 | FICR PART / VARIANT recorded | 0x52840; revision noted | |
| 15 | B-7.3 | NFCPINS, PSELRESET, REGOUT0 | 0xFFFFFFFF (NFC mode); PIN 18 ×2; 0xFFFFFFFF | |
| 16 | B-7.3 | SWD after a power cycle | Attaches | |
| 17 | B-8.3 | LFCLKSTAT | 0x00010001 | |
| 18 | B-8.5 | VSYS ADC vs DMM | ±5.5 % raw; ±20 mV calibrated (reference from the DMM at TP1) | |
| 19 | B-8.6 | USB CDC enumeration and loopback; enumeration at VBUS 4.50 V through 1 m | 0 errors; enumerates | |
| 20 | B-8.7 | MCUboot: USB DFU, BLE DFU, revert; serial recovery **with the TC2030 removed**, routes a/b/c; rails off in MCUboot and recovery | DFU and revert pass; route c and at least one of a/b pass; working routes recorded; VLED, OLED_VIN < 50 mV, MOT_NSLEEP low. **Before the OLED is fitted** | |
| 21 | B-9.1 | QSPI JEDEC ID, quad R/W 1 MB | EF 40 18; 0 errors | |
| 22 | B-9.2 | I2C scans | TWIM0: 0x35. TWIM1: 0x19, 0x6A | |
| 22a | B-9.2 | SCL tLOW at U30/U31 pin 1; SCL rise at base J3 pin 9; SDA setup | ≥ 1.3 µs; ≤ 250 ns; ≥ 100 ns | |
| 23 | B-9.3 | LIS2DW12 WHO_AM_I, \|a\|, INT1 | 0x44; 0.9–1.1 g; pulse on tap | |
| 24 | B-9.4 | BQ25180 register readback | Matches the table (SYS_REG 0x20, TS_CONTROL 0x90) | |
| 25 | B-9.4 | CHG_INT_N pulses on USB plug/unplug | ≈ 128 µs low pulses | |
| 26 | B-9.5b | Charge current in CC | 380–420 mA | |
| 27 | B-9.5b | VBAT at termination | 4.18–4.22 V | |
| 28 | B-9.5b | Charger area temperature | < 60 °C at 25 °C ambient **[TVP]** | |
| 29 | B-9.5c | Ship wake (2 s press, USB) and shutdown wake (USB only) | Both work | |
| 30 | B-9.5d | BTN_N on press (centre + 3 rim points) | < 0.4 V every time | |
| 30a | B-9.5a/c | Pack current at insertion and at ship-mode wake | No BATOCP trip (< 1 A); peak recorded | |
| 31 | B-9.6a | TMAG IDs | 0x5449; variant 2 | |
| 32 | B-9.6c | Track signal | 24 periods; Bz 12–25 mT; per-pole ±15 % | |
| 33 | B-9.6d | W&S wake on a small rotation | INT latches; re-arm verified | |
| 34 | B-9.7 | Piezo at 4 kHz | Clear tone, ≈ 72–79 dB(A) at 10 cm | |
| 35 | B-9.8a | VLED rise time; tON; VSYS dip; fall to 10 % (C7 1 nF CT to VSYS; QOD + R4 68 Ω) | ≈ 1.5–2.5 ms; ≈ 3.8 ms recorded; ≤ 100 mV; ≤ 30 ms (≈ 20–27 ms expected), tFALL recorded | |
| 36 | B-9.8b | LED bit timing | Within the V6 windows | |
| 37 | B-9.8c/d | Walk test, D101 at θ = 0° CCW to D148; 49th word at TP40 | All 48 correct | |
| 38 | B-9.8e | Ring white at 10 % | ≈ 72 mA above baseline (±25 %) | |
| 39 | B-9.8f | Logic margin at 4.6 V and 3.4 V | No glitches in 10 min (else fit U43/C43, remove R43, retest); record which is fitted | |
| 40 | B-9.9a | Bare boost output (every board; also a production test) | 12.7–13.3 V | |
| 40a | B-9.9a | U21 inrush at the first OLED enable; VSYS dip | ≈ 0.4 A peak recorded; ≤ 100 mV | |
| 41 | B-9.9b | OLED full test pattern, no missing lines | Pass | |
| 41a | B-9.9b | FB − OLED_VIN with VCC_EN low, panel fitted | < 0.30 V, recorded | |
| 42 | B-9.9b | SCK edges at the ZIF | t_R/t_F ≤ 15 ns | |
| 43 | B-9.10a | DRV8837 truth table, both drivers | All five states | |
| 44 | B-9.10c | HOME_N near park and at click | Low within ≈ 4–5 mm of PARK; high at click (x = 0), else reject or rework (firmware test 19) | |
| 45 | B-9.10d | 50 round trips | HOME asserted after every park stall; every edge inside its window (no E_DET_STEPS) | |
| 45a | B-9.11 | NFC tag read by a phone through the top cover | Reads; distance recorded | |
| 46 | B-10 | Ship current (PPK2 on the breakout tail) | ≤ 4.5 µA | |
| 47 | B-10 | System OFF, press wake only, panel fitted, at 20–25 °C | ≤ 35 µA | |
| 48 | B-10 | System ON idle, armed, at 20–25 °C | ≤ 65 µA | |
| 49 | B-11.2d | S11, full device on a wooden desk (Stage R; first unit and after changes, optional on later identical units) | ≤ −10 dB over 2400–2483.5 MHz after pigtail-loss correction; u.FL cycles logged | |
| 50 | B-11.3 | HID link at 5 m, 10 min, LEDs and OLED animating | No drops | |
| 51 | B-12.2 | 24 detent rest angles | Within ±0.5° of the 15° grid | |
| 52 | B-12.3 | T(0 mm) | 16.4 mN·m ±25 % (slip mass ≈ 36–60 g at r = 35) | |
| 53 | B-12.4 | FREE rest-angle histogram | Uniform (no preferred angle) | |
| 54 | B-13 | Spin-down from 10 rev/s, median of 10 runs | **≥ 45 s (target ≥ 60 s)** | |
| 55 | B-13 | Viscous coefficient c | ≤ 1e-6 N·m·s | |
| 56 | assembly §10 | Residual imbalance | ≤ 2 g·mm target, ≤ 3.6 g·mm max | |
| 57 | final | Unit left in ship or shutdown mode for storage | Done | |

## Open [TVP] items for the first prototype

1. VLED and OLED_VIN soft-start and inrush with 1 nF from CT to VSYS on both TPS22917 (C7 on U2, C37 on U21;
   B-9.8a, B-9.9a), the VLED fall time with R4 = 68 Ω (SPICE ≤ 26.6 ms; the datasheet tFALL row hints at a
   ≈ 170 Ω internal QOD), and the ≈ 0.4 A boost soft-start peak through U21. The sheet changes are done
   (`main_power.py`, `display.py`; assembly §2.4 item 3); only the measured values are open.
2. HOME_N at the click end with the top-side DRV5032: |Bz| 1.0–1.4 mT against BOP min 1.5 mT (B-9.10c, firmware
   test 19).
3. Antenna S11 and link margin with the antenna on its base-cup shelf (≈ 6 mm above the desk), on wood and on
   metal (B-11), and how much the test pigtail's shield current moves the result.
4. Which serial-recovery routes work on a closed unit, in particular whether the 20 s long-press reset fires with
   USB present (B-8.7; EN_PUSH wording in SLUSE99C).
5. Windows Radial Controller units per detent, 100 vs 150 (B-12.6).
6. TMAG W&S currents and wake angle; LIS2DW12 current at 3.3 V (B-10).
7. Detent torque at R = 29 mm versus the R_t = 30 mm simulation; ringing count without a damping shoe (B-12).
8. Absolute spin time, and whether the oil holds up (B-13).
9. Register-level ID values (W25Q128 JEDEC, LIS2DW12 WHO_AM_I, TMAG IDs, BQ25180 power-on values), which were
   not confirmed against primary sources in the research set.
10. LED data margin with H0H1 drive at VSYS 4.6 V, and whether the DNP U43 level shifter has to be fitted
    (B-9.8f); LED PWM phase alignment and the sum-current peak (B-9.8e).
11. FB − OLED_VIN with the OLED off and the real panel's ESD clamp: SPICE 0.26–0.29 V against the 0.3 V abs max
    (B-9.9b), and the +13V_OLED spread against the 12.7–13.3 V screen (B-9.9a).
12. RT9080 ground current at the ≈ 20 µA sleep load (B-10), the pack current at battery insertion and ship-mode
    wake against BATOCP (B-9.5a/c), and the +3V3 overshoot on USB plug-in at low VBAT (B-9.5c).
13. I2C tLOW, SCL rise time at J3 and SDA setup with the errata 219 settings (B-9.2), and USB enumeration at
    VBUS 4.5 V through R12 (B-8.6).
14. NFC coil inductance, C16/C17 tuning and read distance through the top cover (B-9.11).
