# dial-me-spinner — hardware capture spec (rev A)

This is the **architecture of record** that the generated schematics implement.
Every sheet module in `sheets/` must follow it. It records the decisions that
came out of the subsystem research and its fact-check (see `docs/` for the
reasoning). When a sheet needs to deviate (a part is unavailable, a datasheet
contradicts this spec), keep the deviation as small as possible and note it in
the sheet's group note.

## 1. System summary

A ~70 mm BLE dial spinner with three parts:

* **Stationary hub** (the "floating assembly", FA): it does not rotate. It holds
  the **main board**, the OLED, the LED ring, the diffuser and the top cover, and
  sits on a hollow Ø8 mm spindle. The whole FA moves down ~0.3–0.5 mm when the
  user presses the dial.
* **Rotor**: a balanced 316L stainless flywheel ring (OD 70 / ID 54 / 10 mm) on a
  non-conductive carrier. It spins on one **608** ball bearing around the
  spindle. Its **top face** carries the **magnet track**: 48 alternating-polarity
  N52 Ø2×2 mm discs at R = 29.0 mm.
* **Base**: a stationary plastic cup holding the **base board**, the LiPo and the
  2.4 GHz flex antenna. The FA rests on the press switch in the base.

The magnet track does double duty:
* **Detents**: a stationary N52 Ø3×2 mm magnet sits 1.0 mm above the track
  under the main board. It gives 24 detents of 15°. The magnet is mounted on a
  carriage that a micro actuator slides **radially inward in-plane**: 0 mm offset
  is full click, ≥7.5 mm offset (r ≤ 21.5 mm) is free spin, and positions in
  between give variable strength. The actuator holds position with zero power
  (self-locking lead screw).
* **Encoder**: a TI TMAG5273A2 3D Hall sensor on the main-board underside reads
  the same track: 24 electrical periods per revolution, atan2 interpolation,
  and µA wake-on-rotation.

## 2. Boards and the link between them

| Board | Shape | Layers | Contents |
|---|---|---|---|
| **main** (`hardware/kicad/main`) | Ø64 mm disc, centre hole Ø5 plus 3× M2 on r = 6.5 mm (spindle flange) | 4 (1.6 mm, ENIG) | nRF52840 module, 32 kHz crystal, QSPI flash, 3V3 LDO, OLED ZIF, 13 V boost, 48 RGB LEDs, LED load switch, TMAG5273, LIS2DW12, piezo, 2× DRV8837, DRV5032 home Hall, motor connector, link connector, SWD Tag-Connect |
| **base** (`hardware/kicad/base`) | Ø40 mm disc plus a tab to the USB-C at θ = 0° | 2 (1.6 mm, **ENIG**, needed for the 0.4 mm DSBGA) | USB-C, ESD/TVS, BQ25180 charger + ship-mode button network, battery connector, NTC, centre press switch, link connector |

**Link** = 12-way JST SH (1.0 mm): side-entry `SM12B-SRSS-TB` (C160411) on **both** boards, entry facing the centre (main: bottom side at r = 17.5 mm, clear of the rotor hub; base: r ≈ 15.5 mm, θ = 120°, under the rotor web). Use 28 AWG pre-crimped SH leads for pins 1–4 and 8 (power). A
12-wire harness runs through the spindle bore. Pinout (identical on both
boards):

| Pin | Net | Notes |
|---|---|---|
| 1 | VSYS | power-path output, 3.0–4.5 V |
| 2 | VSYS | |
| 3 | GND | |
| 4 | GND | |
| 5 | VBUS | USB 5 V, used only for nRF USB detection/PHY (few mA) |
| 6 | USB_DM | USB D− (after ESD on base) |
| 7 | USB_DP | USB D+ |
| 8 | GND | |
| 9 | I2C_SCL | system I2C (pull-ups on main board) |
| 10 | I2C_SDA | |
| 11 | CHG_INT_N | BQ25180 /INT, open drain, pull-up on main |
| 12 | BTN_N | dial press, open drain (BSS138 on base), pull-up on main |

## 3. Power architecture

```
USB-C VBUS ──TVS── BQ25180 IN ──(power path)── SYS = VSYS (4.5 V on USB / VBAT on battery)
                         └── BAT ── 1S LiPo (protected pack, ~1000 mAh) + NTC on TS
VSYS ─┬─ RT9080-33 (or TPS7A02-33) LDO ── +3V3  (always on: nRF VDD+VDDH, flash, TMAG, IMU, OLED logic, pull-ups, DRV VCC, DRV5032)
      ├─ TPS22917 load switch (LED_PWR_EN) ── VLED → 48× WS2812C-2020-V6 (+ DNP SN74LV1T34 data level-shifter option)
      ├─ AO3401A disconnect (OLED_VCC_EN) ── OLED_VIN → TPS61040 boost ── +13V_OLED → SSD1351 VCC
      └─ DRV8837 ×2 VM (motor), sleep ≤ 0.24 µA
VBUS ── link ── nRF VBUS pad (USB detect)
```

* nRF52840 in **normal-voltage mode**: VDD (pad 28) **and** VDDH (pad 30) both on
  +3V3, DCCH (pad 31) not connected, REG1 DC/DC enabled (the inductor is inside
  the module). Logic level everywhere on main is **3.3 V**.
* **LDO**: ≥ 200 mA, Iq ≤ 2 µA, dropout ≤ 300 mV at 200 mA, SOT-23-5, LCSC-stocked
  (RT9080-33GJ5 preferred, TPS7A0233PDBVR alternate). Input 10 µF, output
  10 µF + 100 nF.
* **Battery measurement**: always-on divider VSYS → 2.2 MΩ → VSYS_SENSE → 1 MΩ →
  GND, with 100 nF on VSYS_SENSE, into AIN0 (P0.02). That is ~1.3 µA, read with
  the internal 0.6 V reference at gain 1/6.
* **Charger (base)**: BQ25180YBGR. IN 2.2 µF/25 V + SMF5.0A TVS, SYS 10 µF/25 V,
  BAT 4.7 µF. The TS/MR pin takes a 10 kΩ B3435 NTC (NCP15XH103F03RC) to GND
  plus the button-pull FET. The I2C address is 0x6A. Firmware register settings
  are in docs/power.md.
* **Press / ship-wake network (base)**: SW1 (centre tact switch, TS-1187A-B-A-B,
  1.6 N) connects VBAT → 1 kΩ → SW_GATE. 1 MΩ pulls SW_GATE to GND. SW_GATE
  drives both gates of a BSS138DW: Q1 drain → BQ25180 TS/MR (MR wake/reset
  function), Q2 drain → BTN_N (to nRF, SENSE wake). Both sources go to GND.
* **USB-C (base)**: HRO TYPE-C-31-M-12. Each CC pin gets its own 5.1 kΩ to GND.
  The connector's D+/D− pin pairs are tied together (A6/B6, A7/B7). A
  USBLC6-2SC6 is placed at the connector, with its VBUS pin on VBUS. The shell
  goes to GND. USB D+/D− leave on the link.

## 4. nRF52840 pin map (MDBT50Q-U1MV2, KiCad `RF_Module:MDBT50Q-U1MV2`)

Low-frequency-only pins (keep fast signals off them): P0.02, P0.03, P0.09,
P0.10, P0.28–P0.31, P1.01–P1.07, P1.10–P1.15.

| Pin | Net | Use |
|---|---|---|
| P0.00 / P0.01 | XL1 / XL2 | 32.768 kHz crystal SC-20S 9 pF (C97603), 2× 12 pF C0G (C1547) |
| P0.18 | NRESET | pin reset → TC2030 pin 3, 10 kΩ pull-up optional (internal pull-up) |
| SWDIO / SWDCLK | SWDIO / SWDCLK | TC2030 pins 2 / 4 |
| P1.00 | SWO | TC2030 pin 6 (SWO / UART log TX) |
| D+ / D− / VBUS | USB_DP / USB_DM / VBUS | from link; 4.7 µF on VBUS at the module |
| P0.17, P0.19, P0.20, P0.21, P0.22, P0.23 | QSPI_CS, QSPI_SCK, QSPI_IO0..3 | W25Q128JVSIQ (C97521); IO2 = /WP, IO3 = /HOLD; 10 kΩ pull-up on CS |
| P0.13, P0.14, P0.15, P0.16 | OLED_SCK, OLED_MOSI, OLED_CS_N, OLED_DC | SPIM3 |
| P1.01 | OLED_RES_N | 1 MΩ pull-down |
| P1.02 | OLED_VCC_EN | boost input disconnect enable, 100 kΩ pull-down |
| P0.06 | LED_DIN_MCU | I2S SDOUT → 220 Ω → LED_DIN (first LED DI) |
| P1.04 | LED_PWR_EN | TPS22917 ON, 100 kΩ pull-down |
| P0.24, P0.25 | TMAG_SCL, TMAG_SDA | dedicated TWIM0, 4.7 kΩ pull-ups to +3V3 |
| P0.27 | TMAG_INT_N | 47 kΩ pull-up (open-drain INT) |
| P0.08, P1.09 | I2C_SCL, I2C_SDA | system TWIM1 (IMU 0x19, BQ25180 0x6A via link), 4.7 kΩ pull-ups |
| P1.12 | IMU_INT1 | LIS2DW12 INT1 (push-pull) |
| P0.30 | IMU_INT2 | LIS2DW12 INT2 |
| P0.09 | CHG_INT_N | NFC1 used as GPIO; 10 kΩ pull-up to +3V3 |
| P1.10 | BTN_N | 100 kΩ pull-up to +3V3 |
| P0.02 | VSYS_SENSE | AIN0 |
| P0.26, P0.05 | MOT_A_IN1, MOT_A_IN2 | DRV8837 #1 (coil A) |
| P0.07, P0.11 | MOT_B_IN1, MOT_B_IN2 | DRV8837 #2 (coil B) |
| P1.15 | MOT_NSLEEP | shared nSLEEP, 100 kΩ pull-down |
| P1.14 | HOME_N | DRV5032FA output (push-pull, low = magnet present) |
| P0.12, P1.08 | BUZZ_A, BUZZ_B | piezo, complementary PWM, 100 Ω series each |
| P0.03, P0.04, P1.11, P1.13 | TP_SPARE1..4 | test pads |
| P0.10, P0.28, P0.29, P0.31, P1.03, P1.05, P1.06, P1.07 | — | no-connect |

## 5. Main-board sheets

### 5.1 `main_power` — link, LDO, rails
* J1 link connector (pinout §2).
* U LDO VSYS → +3V3 (§3). VSYS bulk 22 µF 0805 plus 10 µF at the LDO.
* VSYS_SENSE divider (§3).
* U TPS22917DBVR (C2681320; KiCad `Power_Management:TPS22917DBV`): VIN = VSYS (10 µF), ON = LED_PWR_EN (100 kΩ
  pull-down), CT = 1 nF/50 V **from CT to VIN** (TPS22917 pin table; ≈ 4 ms rise), QOD → 100 Ω → VOUT, VOUT = VLED (2× 22 µF 0805).
  The TPS22918 is *not* a drop-in: its CT goes to GND.
* TP pads for VSYS, +3V3, GND.

### 5.2 `mcu` — nRF52840 module, crystal, flash, debug
* U MDBT50Q-U1MV2 (C2688382; JLC global sourcing).
  * VDD + VDDH: 10 µF 0603 + 100 nF; VBUS: 4.7 µF.
  * The u.FL connector is on the module, so the antenna is off-board (Molex
    146153-0050, mechanical item).
* Y1 + 2× 12 pF.
* U W25Q128JVSIQ + 100 nF; 10 kΩ CS pull-up.
* J TC2030-IDC-NL footprint (`Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical`):
  1 VTref (+3V3), 2 SWDIO, 3 NRESET, 4 SWDCLK, 5 GND, 6 SWO.
* Test pads for spare GPIOs.

### 5.3 `display` — SSD1351 OLED + 13 V boost
Panel NHD-1.5-128128G (pin-identical: Orient AOC128128A0-1.50W). It is a
30-pin, 0.5 mm FPC into a **bottom-contact** ZIF (AFC01-S30FCA-00, C262671),
4-wire SPI. Pin functions follow the NHD datasheet:
* VCC (13 V) gets 10 µF/25 V + 100 nF; VCOMH gets 4.7 µF/25 V tantalum (C7189);
  VDD and VDDIO get 1 µF each; VCI gets 4.7 µF + 100 nF.
* IREF: 560 kΩ to GND. VSL: 51 Ω (1206) to a BAV99 used as two series diodes
  to GND.
* BS0/BS1 strapped for 4-wire SPI. Unused data pins are tied per the datasheet.
* RES# has a 1 MΩ pull-down.

Boost:
* Input disconnect: AO3401A, source = VSYS, drain = OLED_VIN. Gate: 100 kΩ to
  VSYS, 10 kΩ series from the 2N7002 drain. The 2N7002 gate is OLED_VCC_EN
  with 100 kΩ to GND.
* TPS61040DBVR (C7722): VIN = OLED_VIN (4.7 µF), L = 10 µH SWPA3015S100MT
  (C45403), D = B5819W, COUT 4.7 µF/25 V.
* FB divider: R1 = 499 kΩ (0.5 %), R2 = 52.3 kΩ (0.5 %) → 13.0 V, CFF 33 pF
  across R1. EN tied to OLED_VIN (the input disconnect does the switching).
* The boost inductor and SW node must sit ≥ 10 mm from the TMAG5273 and from
  the magnets (layout note).

### 5.4 `leds` — 48× WS2812C-2020-V6 ring
* D101…D148 WS2812C-2020-V6 (C55109522; footprint
  `LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm`; WS2812B-2020-V6 C52917434 is a
  pin-compatible only: its 12 mA/ch gives a 2.35 A worst case, so the firmware ring cap ≤ 0.75 A becomes mandatory and the link power contacts are at their limit), chained DOUT→DIN (nets LED_D1…LED_D47; the last DOUT is LED_D48). Each LED has its own 100 nF 0402 (C1525) on
  VLED/GND (C101…C148, same index).
* LED_DIN_MCU → 220 Ω (R40; limits DIN clamp injection if P0.06 is ever high while VLED is off) → LED_DIN (D101.DIN),
  with 100 kΩ pull-down (R41) on LED_DIN. D148.DOUT (LED_D48) goes to TP40 with a 100 kΩ pull-down (R42), since V6 DI/DO are swappable.
  Firmware: drive P0.06 low and send an all-zero frame before switching VLED off; never drive P0.06 high while VLED is off.
* Level shifting: none fitted by default (3.3 V drive). A DNP SN74LV1T34 (U43, powered from VLED) with a fitted 0 Ω bypass (R43)
  is provided because the guaranteed VIH margin is only 0.1–0.2 V when VSYS = 4.5 V on USB (fit U43, remove R43 if the bench test fails).

### 5.5 `sensors` — encoder, IMU, piezo
* U TMAG5273A2QDBVR (C3715882), **bottom side**, θ = 270°, long axis radial, placed so that the **Hall
  element** (offset 0.40 mm toward pin 3 and 0.12 mm toward the pin 1–3 edge from the body centre) is at r = 29.0 mm. Pins: 1 SCL, 2 GND, 3 TEST → GND, 4 VCC, 5 INT, 6 SDA. VCC gets
  100 nF + 1 µF. 4.7 kΩ pull-ups on TMAG_SCL/SDA, 47 kΩ on TMAG_INT_N.
  DNP footprint: DRV5012AEDMRR (C2655038) latch as a fallback wake sensor →
  TP_SPARE (optional).
* U LIS2DW12TR (C189624): CS → +3V3 (I2C mode), SA0 → +3V3 (address 0x19,
  **never GND**), RES → GND, VDD 100 nF + 10 µF, VDD_IO 100 nF, INT1 →
  IMU_INT1, INT2 → IMU_INT2, SCL/SDA → I2C_SCL/I2C_SDA.
* System I2C pull-ups 4.7 kΩ ×2 (I2C_SCL/SDA → +3V3). CHG_INT_N 10 kΩ and BTN_N
  100 kΩ pull-ups live here or in `main_power`, but exactly once.
* BZ1 Murata PKMCS0909E4000-R1 (C910763), magnet-free: BUZZ_A → 100 Ω → BZ+,
  BUZZ_B → 100 Ω → BZ−.

### 5.6 `detent` — actuator driver + home sensor
* 2× DRV8837DSGR (C39159): pin 1 VM ← VSYS (0.1 µF each + one 10 µF 0805
  shared), pin 8 VCC ← +3V3 (0.1 µF each), pin 7 nSLEEP ← MOT_NSLEEP (shared),
  IN1/IN2 ← MOT_x_IN1/2, OUT1/OUT2 → coil, pin 4 + EP → GND.
* J motor: JST SH 4-pin SM04B-SRSS-TB (C160404). Pin 1 = A+ (OUT1 of #1), pin
  2 = A− (OUT2 of #1), pin 3 = B+ (OUT1 of #2), pin 4 = B− (OUT2 of #2). A
  2-wire DC gearmotor can use pins 1–2 only.
* U DRV5032FADBZR (C140921) always powered from +3V3 (≤ 2 µA avg), OUT → HOME_N,
  100 nF on VCC. It sits on the **top side** directly above the free-mode park
  position (r = 21.5 mm, θ = 90°).

## 6. Base board (`base` sheet)
* J1 USB-C, R CC ×2, U USBLC6-2SC6, D SMF5.0A (VBUS→GND).
* U BQ25180YBGR + caps (§3), RT1 NTC, I2C to the link.
* J2 battery: JST PH 2-pin SMD S2B-PH-SM4-TB (C295747). Pin 1 = BAT+, pin 2 =
  GND (verify the pack polarity before plugging in!).
* SW1 TS-1187A-B-A-B (C318884) at the board centre, top side.
* Q1 BSS138DW (C154900) network (§3).
* J3 link connector (§2), VSYS 10 µF near J3.
* Test pads: VBUS, VBAT, VSYS, GND.

## 7. Global rules
* Passives: 0402 by default (`Resistor_SMD:R_0402_1005Metric`,
  `Capacitor_SMD:C_0402_1005Metric`); bulk caps 0603/0805 as stated. Use JLC
  basic parts where possible and put an `LCSC` field on every part.
* Every part gets fields `MPN`, `Manufacturer` (when known) and `LCSC`.
* Never place ferromagnetic hardware or power inductors within 10 mm of the
  magnet track (r = 29 ± 2 mm under the board) or the TMAG5273.
* Net names are defined in `nets.py`. Use them exactly. Do not invent new
  inter-sheet nets.

## 8. Mechanical stack-up (shared by the PCB layout and the enclosure model)

z is measured from the desk (0) upward. θ = 0° is the USB-C direction; angles
increase counter-clockwise when the device is viewed from the top. All
dimensions are in mm.

| z range | Part | Radii / notes |
|---|---|---|
| 0.0–1.0 | 3× rubber/micro-suction feet | r = 28 |
| 1.0–2.5 | base cup floor (PA12/PETG) | cup OD Ø70, wall 1.6, wall top z = 14.3 |
| 2.5–9.0 | LiPo bay, protected 603450-class pack **≤ 6.0 thick** (≥ 1 mm swelling gap to the board) | long axis along **θ = 0°/180°** (|x| ≤ 27.5, |y| ≤ 17.25); leads exit at the θ = 180° end |
| 5.5–6.0 | **2.4 GHz flex antenna** (Molex **146153-0100**, 100 mm coax) on a printed shelf along the chord y = +26 (θ ≈ 90°), outer edge ≤ r 33 | ≈ 9.5 mm below the ring, ≈ 6 mm above the desk, ≥ 4 mm from the pack side (y = 17.25); coax rises to the spindle side slot |
| 9.5–11.1 | **base board** (Ø46 disc + USB tab to r = 35 at θ = 0°, 1.6 mm) | 2× M2 bosses at r = 21, θ = 90°/270° (outside the pack); the USB-C shell clamped in the cup wall is the 3rd support |
| 11.1–12.6 | press switch TS-1187A (1.5 tall) at the base-board centre | |
| 12.8–14.3 | FA lower plate (PA12, stationary, part of the floating assembly): a **3-spoke spider** (spokes at θ = 60°/180°/300°, hub r ≤ 6 with the centre boss over the switch, pre-gap 0.15, outer ring r 26–30). The open sectors centred on θ = 0°/120°/240° clear the tall base-board parts | 3 guide pins + springs at r = 29, θ = 60°/180°/300°, preload ≈ 4 N up against stops |
| 12.8–29.1 | hollow spindle Ø8 × 1.0 wall (316 or titanium), bore Ø6 for link harness + antenna coax | clamped to the lower plate and to the main board; side slots at z ≈ 14.5–16 (below the carrier web) and just under the main board let the harness/coax in and out |
| 15.6–25.6 | **rotor**: 316L ring OD 70 / ID 54, on a PA12-GF carrier web (z 17–19, r 11–27) holding the 608 outer race | ring top face z = 25.6 carries the 48-magnet track (Ø2×2, pockets 2.05 deep, R_t = 29.0) |
| 18.0–25.0 | 608 bearing on the spindle; ≥ 2.5–3 N wave-spring axial preload | outer race r = 11 |
| 19–29.1 | "bowl" under the main board, r 12–27: detent actuator (micro linear stepper, chord placement near θ = 90°) | stationary, hangs from the main-board bottom |
| 26.6–28.6 | detent magnet Ø3×2 N52 on carriage, 1.0 mm above the track; slides r = 29.0 (click) → 21.5 (free) along θ = 90° | carriage plate 0.5 mm, rail fixed to the main-board bottom |
| 29.1–30.7 | **main board** Ø64 (r ≤ 32), 4-layer 1.6 mm | centre Ø5 hole + 3× **plated GND** M2 at r = 6.5 (spindle flange; the ring's ESD bleed path runs ring → conductive epoxy → 608 races → spindle → GND), 2× M2 at r = 17 θ = 60°/120° (actuator bracket) |
| 30.7–31.6 | LEDs (48× WS2812C-2020) at r = 28.5 | |
| 31.6–34.2 | LED light box (white interior, opaque exterior) r 27–30 | |
| 33.0–34.7 | OLED glass 33.8 × 34.0 (active-area centre on axis) on a bracket; FPC folded under to the ZIF | |
| 34.2–36.0 | diffuser ring (opal PMMA, r 27–30) + top cover (stationary) with Ø30 OLED window, cover OD r = 32.5 | |

The ring's visible surfaces are the knurled side (z 15.6–25.6) and a top rim
band at r 32.5–35. Overall size is Ø70 × 36 mm.

**Main-board PCB rules that come from the stack**
* No copper pours on **B.Cu or In2.Cu** for r ≥ 26 (this annulus faces the
  magnet track, so pours there add eddy drag). F.Cu/In1.Cu pours are allowed,
  since the track is 3.5–5 mm away. Traces and pads are allowed everywhere.
* Bottom side keep-outs:
  * sector θ = 60°–120°, r 12–32: actuator and detent carriage, no components;
  * the spindle flange area r ≤ 8.5.
* TMAG5273 on the **bottom** side at (r = 29, θ = 270°). Its long axis is
  radial. Nothing ferromagnetic and no inductor may sit within 10 mm of it.
* DRV5032 on the **top** side at (r = 21.5, θ = 90°).
* LEDs on the **top** side, centred on r = 28.5, with LED1 at θ = 0° and
  numbering increasing CCW. Each LED's 100 nF cap goes radially inward (r ≈ 26).
* The OLED ZIF sits on the **top** side under the glass, toward θ = 270° (the
  FPC side). The 13 V boost also sits on the top side under the glass and must
  be ≥ 10 mm from the TMAG5273.
* MDBT50Q module on the **bottom** side, r 8–22, sector θ ≈ 180°–250°. Its u.FL
  end faces the centre so the coax runs straight into the spindle bore.
* The link connector J1 (side-entry JST SH) sits on the **bottom** side at r = 17.5 mm, θ = 330°, entry facing the centre.
  The harness lies flat against the board bottom (above the rotor hub, which tops out at z ≈ 25) into the spindle bore.
* The piezo goes on the **bottom** side (sound vents through the board).
* The TC2030 pads go on the top side under the OLED glass, so they are
  reachable before the OLED is fitted.

**Base-board placement rules (§8)**
* The space above the base board is only 1.7 mm, or 1.2 mm when the dial is pressed, wherever an FA spoke or the hub passes over it. Put every part taller than 1.0 mm in the open sectors (θ = 0° ± 40°, 120° ± 40°, 240° ± 40°, r > 6). That means:
  * USB-C J1 at θ = 0° on the tab;
  * USBLC6 U2 and SMF5.0A near J1;
  * link J3 (**side-entry** SH SM12B, ~3 mm tall, entry facing the centre) at r ≈ 15.5, θ = 120°. A vertical header plus plug would reach the rotor web;
  * battery J2 (PH, top side) at r ≈ 17, θ ≈ 212°. The pack leads come up past the board edge from the pack end at θ = 180°.
* Nothing on the base-board bottom side: the battery sits 0.5 mm below it. The only exception is pads/test points.
* SW1 sits exactly at the centre, under the FA boss.

