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
  the **main board**, the OLED, the LED ring, the diffuser and the top cover
  (which carries the NFC tag coil), and sits on a hollow Ø8 mm spindle. The whole FA moves down ~0.3–0.5 mm when the
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
  carriage that a micro actuator slides **radially inward in-plane** along the
  θ = 90° radius: 0 mm offset is full click, ≥7.5 mm offset (r ≤ 21.5 mm) is
  free spin, and positions in between give variable strength. The actuator
  itself lies on a chord (y = 15.5 mm) and drives the carriage through an
  inclined-slot link, so it sweeps θ ≈ 35–160° (§8 bottom-side rules). It holds
  position with zero power (self-locking lead screw).
* **Encoder**: a TI TMAG5273A2 3D Hall sensor on the main-board underside reads
  the same track: 24 electrical periods per revolution, atan2 interpolation,
  and µA wake-on-rotation.

## 2. Boards and the link between them

| Board | Shape | Layers | Contents |
|---|---|---|---|
| **main** (`hardware/kicad/main`) | Ø64 mm disc, centre hole Ø5 plus 3× plated GND M2 on r = 6.5 mm (spindle flange) and 2× NPTH M2 on r = 17 mm (actuator bracket) | 4 (1.6 mm, ENIG; In1 = GND plane, In2 = signals/power); parts on both sides | nRF52840 module, VBUS series R + second-stage USB ESD, 32 kHz crystal, QSPI flash, 3V3 LDO, OLED ZIF, OLED load switch + 13 V boost, 48 RGB LEDs, LED load switch, TMAG5273 + its ESD array, LIS2DW12, piezo, 2× DRV8837, DRV5032 home Hall, motor connector, link connector, SWD Tag-Connect, NFC tuning caps + coil pads |
| **base** (`hardware/kicad/base`) | Ø46 mm disc plus a tab to the USB-C at θ = 0° (r ≤ 35) | 4 (1.6 mm, **ENIG**, needed for the 0.4 mm DSBGA; In1 = GND plane, In2 = signals/power); parts on the top only | USB-C, ESD/TVS, BQ25180 charger + ship-mode button network, battery connector, NTC, centre press switch, link connector |

**Link** = 12-way JST SH (1.0 mm): side-entry `SM12B-SRSS-TB` (C160411) on **both** boards, entry facing the centre (main J1: bottom side at r = 19.5 mm, θ = 330°, so the mated plug's back stays clear of the rotor hub; base J3: top side at r ≈ 15.5 mm, θ = 120°, under the rotor web). Use 28 AWG pre-crimped SH leads for pins 1–4 and 8 (power). The
12-wire harness runs through the spindle bore, in and out through its side slots. Pinout (identical on both
boards):

| Pin | Net | Notes |
|---|---|---|
| 1 | VSYS | power-path output, 3.0–4.5 V |
| 2 | VSYS | |
| 3 | GND | |
| 4 | GND | |
| 5 | VBUS | USB 5 V, used only for nRF USB detection/PHY (few mA); on main it reaches the nRF through R12 4.7 Ω (VBUS_NRF) |
| 6 | USB_DM | USB D− (ESD at the base USB-C, U2, and again at the module, U12) |
| 7 | USB_DP | USB D+ |
| 8 | GND | |
| 9 | I2C_SCL | system I2C (pull-ups on main board) |
| 10 | I2C_SDA | |
| 11 | CHG_INT_N | BQ25180 /INT, open drain, pull-up on main |
| 12 | BTN_N | dial press, open drain (BSS138 on base), pull-up on main |

## 3. Power architecture

```
USB-C VBUS ──TVS── BQ25180 IN ──(power path)── SYS = VSYS (4.4 V on USB with SYS_REG set by firmware / VBAT on battery)
                         └── BAT ── 1S LiPo (protected pack, ~1000 mAh) + NTC on TS
VSYS ─┬─ RT9080-33 (or TPS7A02-33) LDO ── +3V3  (always on: nRF VDD+VDDH, flash, TMAG, IMU, OLED logic, pull-ups, DRV VCC, DRV5032)
      ├─ TPS22917 U2 (ON = LED_PWR_EN) ── VLED → 48× WS2812C-2020-V6 (+ DNP SN74LV1T34 data level-shifter option)
      ├─ TPS22917 U21 (ON = OLED_VCC_EN, R25 100 kΩ pull-down, CT 1 nF to VIN, QOD tied to OLED_VIN)
      │      ── OLED_VIN → TPS61040 boost ── +13V_OLED → SSD1351 VCC
      └─ DRV8837 ×2 VM (motor), sleep ≤ 0.24 µA
VBUS ── link ── R12 4.7 Ω ── VBUS_NRF → nRF VBUS pad (USB detect) + U12 USBLC6 rail
```

* nRF52840 in **normal-voltage mode**: VDD (pad 28) **and** VDDH (pad 30) both on
  +3V3, DCCH (pad 31) not connected, REG1 DC/DC enabled (the inductor is inside
  the module). Logic level everywhere on main is **3.3 V**.
* **LDO**: ≥ 200 mA, Iq ≤ 2 µA typ / 4 µA max, dropout ≤ 300 mV at 200 mA, SOT-23-5, LCSC-stocked
  (RT9080-33GJ5 preferred, TPS7A0233PDBVR alternate). Input 10 µF, output
  10 µF + 100 nF. The RT9080's ground current at the ~20 µA sleep load is not
  specified: it is a bring-up measurement, and the TPS7A0233 is the alternate
  (hardware/sim, LDO-1, LDO-6).
* **Battery measurement**: always-on divider VSYS → 2.2 MΩ → VSYS_SENSE → 1 MΩ →
  GND, with 100 nF on VSYS_SENSE, into AIN0 (P0.02). That is ~1.3 µA, read with
  the internal 0.6 V reference at gain 1/6. Keep the VSYS_SENSE node away from
  other copper and clean: 4.5 nA of leakage on it uses up the whole ±10 mV
  (25 °C) calibrated-accuracy budget (hardware/sim, VSENSE-4, the ageing and
  leakage finding; test_pin_leakage_sensitivity). The calibrated reading can
  still be up to about 73 mV high (+73/−79 mV on an aged unit at −10 / 60 °C,
  at the 3.5393 V SHIP reading). The over-read is a gain error that grows
  with VSYS, to about 2.1 % of the reading (88 mV at 4.2 V), so firmware
  compares every VBAT/VSYS threshold that protects a datasheet limit, as a
  true-cell value, against VBAT_est = 0.979 × calibrated reading (VSYS_est
  likewise; rule R1'), which covers a 2.1 % over-read at every threshold;
  SHIP is entered below VBAT_est 3.465 V, a reading of 3.5393 V
  (docs/firmware.md §12.4; hardware/sim, VSENSE-1/4/5).
* **Charger (base)**: BQ25180YBGR. IN 2.2 µF/25 V 0805 X7R + SMF5.0A TVS (an 0603
  X5R loses too much to DC bias to keep ≥ 1 µF effective; hardware/sim, USB-3),
  SYS 10 µF/25 V, BAT 4.7 µF. The TS/MR pin takes a 10 kΩ B3435 NTC
  (NCP15XH103F03RC) to GND plus the button-pull FET. The I2C address is 0x6A.
  Firmware register settings: docs/firmware.md §13.1. On USB, SYS regulates to
  the SYS_REG setting: firmware sets 4.4 V (rule in §5.4; the POR default is
  4.5 V). The total VSYS capacitance is already close to the BQ25180's 100 µF
  maximum: do not add VSYS bulk (hardware/sim, NF-2). Firmware MUST write
  TS_CONTROL (0x0B) = 0x90 at init (TS_HOT 50 °C, TS_COLD 3 °C): with the
  default 0x00 the worst-case COLD trip is about −2 °C, so the JEITA limits do
  not hold with the NTC tolerances (hardware/sim, charger_ts-1). It MUST
  treat STAT0.TS_OPEN_STAT = 1 as a fault (CHG_DIS = 1, "temperature sensor
  fault"), because an open NTC can disable TS monitoring rather than read cold
  (hardware/sim, charger_ts-v1). It SHOULD treat a TS COLD state while the nRF
  die reads above about 10 °C as the same fault: a resistive, partly open RT1
  (about 46–90 kΩ) leaves TS_OPEN_STAT at 0. While VBUS is present it MUST set
  CHG_DIS = 1 when the nRF die temperature reads below 0 °C and clear it above
  about 3 °C:
  below about −11 °C the TS bias drives TS/MR above VTS_ENZ, where the
  BQ25180 does not guarantee cold-charge protection (hardware/sim, charger_ts-3).
* **Press / ship-wake network (base)**: SW1 (centre tact switch, TS-1187A-B-A-B,
  1.6 N) connects VBAT → 1 kΩ (R3) → SW_GATE. R4 = 100 kΩ pulls SW_GATE to GND,
  so the Q1 gates discharge within 38.5 µs worst case on release, inside the
  64 µs deglitch the simulation assumes (SLUSE99C specifies no TS deglitch);
  it costs ~42 µA from VBAT only while the button is held
  (hardware/sim, charger_ts-2). SW_GATE
  drives both gates of the BSS138DW Q1: Q1A drain → BQ25180 TS/MR (MR wake/reset
  function), Q1B drain → BTN_N (to nRF, SENSE wake). Both sources go to GND.
  A press pulls TS/MR low, so firmware MUST ignore TS_STAT, TS_FAULT and TS
  interrupts while BTN_N is low and for 5 ms after (hardware/sim, charger_ts-v2).
* **USB-C (base)**: HRO TYPE-C-31-M-12. Each CC pin gets its own 5.1 kΩ to GND.
  The connector's D+/D− pin pairs are tied together (A6/B6, A7/B7). A
  USBLC6-2SC6 (U2) is placed at the connector, with its VBUS pin on VBUS; a
  second one (U12) sits at the module on the main board (§5.2). The shell
  goes to GND. USB D+/D− leave on the link. Supported VBUS is 4.5–5.25 V: at
  ~5.5 V the BQ25180 VIN_OVP may stop charging (the unit then runs from the
  battery). The protector stand-offs (USBLC6 5.25 V, SMF5.0A 5.0 V) are below
  the 5.5 V vSafe5V maximum, which costs leakage only (accepted; hardware/sim,
  USB-4, NF-4).

## 4. nRF52840 pin map (MDBT50Q-U1MV2, KiCad `RF_Module:MDBT50Q-U1MV2`)

Low-frequency-only pins (keep fast signals off them): P0.02, P0.03, P0.09,
P0.10, P0.28–P0.31, P1.01–P1.07, P1.10–P1.15.

| Pin | Net | Use |
|---|---|---|
| P0.00 / P0.01 | XL1 / XL2 | 32.768 kHz crystal SC-20S 9 pF (C97603), 2× 12 pF C0G (C1547) |
| P0.18 | NRESET | pin reset → TC2030 pin 3; internal pull-up, 10 kΩ pull-up R11 is DNP |
| SWDIO / SWDCLK | SWDIO / SWDCLK | TC2030 pins 2 / 4 |
| P1.00 | SWO | TC2030 pin 6 (SWO / UART log TX) |
| D+ / D− / VBUS | USB_DP / USB_DM / VBUS_NRF | from link; VBUS → R12 4.7 Ω → VBUS_NRF with 4.7 µF (C12) at the module; U12 USBLC6-2SC6 at the module pins |
| P0.17, P0.19, P0.20, P0.21, P0.22, P0.23 | QSPI_CS, QSPI_SCK, QSPI_IO0..3 | W25Q128JVSIQ (C97521); IO2 = /WP, IO3 = /HOLD; 10 kΩ pull-up on CS |
| P0.13, P0.14, P0.15, P0.16 | OLED_SCK, OLED_MOSI, OLED_CS_N, OLED_DC | SPIM3 at 16 MHz (anomaly 198 and 195 workarounds); SPIM2 at 8 MHz is the same-pin fallback |
| P1.01 | OLED_RES_N | 1 MΩ pull-down |
| P1.02 | OLED_VCC_EN | ON of U21 (TPS22917, OLED boost input switch), 100 kΩ pull-down (R25) |
| P0.06 | LED_DIN_MCU | I2S0 SDOUT, **H0H1 drive** (§5.4) → R40 220 Ω (at the pin) → LED_DIN_R → R43 0 Ω → LED_DIN (D101 DI) |
| P1.04 | LED_PWR_EN | ON of U2 (TPS22917), 100 kΩ pull-down (R3) |
| P0.24, P0.25 | TMAG_SCL, TMAG_SDA | dedicated TWIM0, 4.7 kΩ pull-ups to +3V3; ESD array U32 at the TMAG5273 |
| P0.27 | TMAG_INT_N | 47 kΩ pull-up (open-drain INT); ESD array U32 |
| P0.08, P1.09 | I2C_SCL, I2C_SDA | system TWIM1 (IMU 0x19, BQ25180 0x6A via link), 4.7 kΩ pull-ups |
| P1.12 | IMU_INT1 | LIS2DW12 INT1 (push-pull) |
| P0.30 | IMU_INT2 | LIS2DW12 INT2 |
| P0.09 / P0.10 | NFC1 / NFC2 | NFCT tag antenna (UICR NFCPINS stays in NFC mode); 180 pF C0G tuning cap to GND on each (C16/C17); coil tail pads J11 on the main-board top |
| P1.03 | CHG_INT_N | BQ25180 /INT (open drain, 128 µs pulses); 10 kΩ pull-up to +3V3 |
| P1.10 | BTN_N | 100 kΩ pull-up to +3V3 |
| P0.02 | VSYS_SENSE | AIN0 |
| P0.26, P0.05 | MOT_A_IN1, MOT_A_IN2 | DRV8837 #1 (coil A) |
| P0.07, P0.11 | MOT_B_IN1, MOT_B_IN2 | DRV8837 #2 (coil B) |
| P1.15 | MOT_NSLEEP | shared nSLEEP, 100 kΩ pull-down |
| P1.14 | HOME_N | DRV5032FA output (push-pull, low = magnet present) |
| P0.12, P1.08 | BUZZ_A, BUZZ_B | piezo, complementary PWM, 470 Ω series each (R57/R58), R59 1 MΩ across BZ1 |
| P0.03, P0.04, P1.11, P1.13 | TP_SPARE1..4 | test pads |
| P0.28, P0.29, P0.31, P1.05, P1.06, P1.07 | — | no-connect |

## 5. Main-board sheets

### 5.1 `main_power` — link, LDO, rails
* J1 link connector (pinout §2): side-entry SM12B-SRSS-TB on the bottom at r = 19.5 mm, θ = 330° (§8).
* U1 RT9080-33GJ5 (C841192) VSYS → +3V3 (§3). VSYS bulk C1 22 µF 0805 plus C2 10 µF at the LDO. The 10 µF 0603 VSYS caps
  (main C2, C6, C41; base C2, C4) are 25 V parts (CL10A106MA8NRNC, C96446): a 10 V 0603 keeps only ~28 % of its value at
  5 V, and VSYS has to absorb the stepper's coast energy on USB (hardware/sim, MD-5).
* VSYS_SENSE divider R1 2.2 MΩ (C11490) / R2 1 MΩ / C5 100 nF (§3).
* U2 TPS22917DBVR (C2681320; KiCad `Power_Management:TPS22917DBV`): VIN = VSYS (C6 10 µF/25 V), ON = LED_PWR_EN (R3
  100 kΩ pull-down), CT = C7 1 nF/50 V **from CT to VIN** (TPS22917 pin table; tON ≈ 3.8–4.0 ms, from the
  3.8–4.0 µs/pF of datasheet Table 7.6), QOD → R4 68 Ω (RC0402FR-0768RL, C163455) → VOUT, VOUT = VLED (C8, C9:
  2× 22 µF 0805). The TPS22918 is *not* a drop-in: its CT goes to GND.
  * VLED discharge: QOD + R4 take VLED to 10 % in ≈ 24 ms nominal and 26.6 ms worst case (3.465 V start, C8/C9 +20 %,
    DC bias; 25.7 ms from 4.2 V), inside the firmware's 30 ms allowance; with R4 = 100 Ω it was 30.6 ms (hardware/sim,
    LSW-2, test_u2_qod_discharge_tolerance_extremes). Bring-up measures VLED tFALL: the datasheet tFALL row implies an
    internal QOD of ≈ 170 Ω rather than the 150 Ω typical (hardware/sim, NEW-4).
  * The TPS22917 has no current limit; an eFuse on VLED is optional and not fitted.
  * Firmware rules (details in docs/firmware.md §6.4 and §15):
    * Firmware MUST wait ≥ 30 ms after LED_PWR_EN goes low before switching VLED on again or treating it as off,
      because the QOD discharge takes up to 26.6 ms (hardware/sim, LSW-2).
    * On a BAT_OCP_FAULT or brown-out with LED_PWR_EN set, firmware MUST keep the LEDs off for the session and log a
      VLED fault; if a brown-out, POF or BATOCP follows LED_PWR_EN within ~50 ms twice, it latches VLED off and shows a
      service fault. U2 has no current limit, so a ring fault only shows up as a BATOCP or brown-out
      (hardware/sim, NEW-5, NF-3).
    * Firmware MUST ignore POFWARN for 10 ms after it raises LED_PWR_EN or OLED_VCC_EN, and a POFWARN in that window
      does not count toward the VLED latch above: the enables can dip +3V3 to 2.87–3.02 V for up to 5.8 ms (dead
      battery on USB at the 80 mA ILIM minimum; the NEW-1 supplement branch), below the 3.045 V upper bound of the
      2.9 V POF threshold but above VBOR and the W25Q128's 2.7 V, and the handler would otherwise shed the load it has
      just enabled (docs/firmware.md §12.4; hardware/sim, NEW-1, PI-4).
* H1–H3: plated GND M2 holes at r = 6.5 mm (θ 90°/210°/330°) for the spindle flange. They give the touchable 316L
  ring its ESD bleed path (ring → conductive epoxy → 608 races → spindle → GND).
* Test pads TP1–TP4 for VSYS, +3V3, VLED, GND.

### 5.2 `mcu` — nRF52840 module, crystal, flash, debug
* U10 MDBT50Q-U1MV2 (C2688382). JLC has no stock: use JLC Global Sourcing or consign it.
  * VDD + VDDH: 10 µF 0603 + 100 nF.
  * VBUS (pad 32): R12 4.7 Ω (FRC0402F4R70TS, C2909356) in series from the link VBUS (nRF52840 PS §7.3 config 1),
    net VBUS_NRF, with C12 4.7 µF on the module side. R12·C12 (≈ 20 µs) filters the legacy-cable hot-plug ring, so
    the pin sees the settled VBUS: 4.49–5.49 V for 4.5–5.5 V sources, worst 5.488 V vs the 5.8 V abs max
    (6.5–8.4 V without R12). The DC check at VBUS 4.5 V with a 1.1 A charger load gives 4.378 V at the pin vs the
    4.35 V minimum (28 mV margin, resting on the typical 2.4 mA IUSB), so bring-up confirms enumeration from a 4.5 V
    supply through a 1 m cable (hardware/sim, USB-1). R12 also limits a C12 short to ≈ 1.2 A, which opens the 0402
    (hardware/sim, V-5).
  * U12 USBLC6-2SC6 (C7519) at the module's D+/D− pads, rail on VBUS_NRF, as close as the module courtyard allows:
    without it an IEC 8 kV hit on D+/D− drives 2.6–3.7 A into the nRF pads through the ~145 nH link. Accepted
    residual risk (rev A): with both arrays at datasheet-max clamps the pad current is 1.27 A at a 100 mm harness vs
    the 1.33 A HBM 2 kV class (5 % margin, at an assumed 3 Ω on-chip clamp; typical clamps 0.64–0.84 A), and 1.62 A
    with a 50 mm harness at +8 kV (hardware/sim, USB-2).
  * The u.FL connector is on the module, so the antenna is off-board (Molex
    146153-0100, 100 mm coax; mechanical item).
* Y1 + 2× 12 pF.
* U11 W25Q128JVSIQ + 100 nF; 10 kΩ CS pull-up.
* J10 TC2030-IDC-NL footprint (`Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical`):
  1 VTref (+3V3), 2 SWDIO, 3 NRESET, 4 SWDCLK, 5 GND, 6 SWO. R11 (10 kΩ NRESET pull-up) is DNP.
* NFC tag antenna on the NFCT (P0.09 = NFC1, P0.10 = NFC2; UICR NFCPINS stays in NFC mode): C16/C17 180 pF C0G
  (C78636) from NFC1/NFC2 to GND, sized for a coil of ~1.4–1.5 µH and retuned on the prototype for the coil's real L:
  the coil of §8 is estimated at ≈ 1.75 µH, which wants ≈ 150–160 pF per side, so expect to retune once it is measured.
  The 13.56 MHz flex coil lives in the top cover; its tail solders to the flat pads J11 (NFC_COIL, no part fitted) on
  the top side at r = 21.5 mm, θ = 222° (a 2.95 mm header does not fit under the display glass). Route NFC1/NFC2 as a
  pair, away from the TMAG5273 and the LED data line. Firmware emulates an NFC-A Type 2 / Type 4 tag (nRF Connect SDK
  nfc_t2t / nfc_t4t) with NDEF content and NFCID1 changeable at run time; field detect can wake the MCU from System
  OFF (≈ 100 nA in sleep; hardware/sim, SLP-V1). The nRF52840 cannot read tags: the phone app reads a tag and sends
  the content over BLE. Encrypted badges and payment cards cannot be emulated.
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
* Input switch: TPS22917 U21 (TPS22917DBVR, C2681320): VIN = VSYS (C41 10 µF/25 V), ON = OLED_VCC_EN (R25 100 kΩ
  pull-down, so U21 stays off through an MCU reset), CT = C37 1 nF/50 V from CT to VIN (tON ≈ 4 ms), **QOD tied to
  VOUT = OLED_VIN**. With OLED_VCC_EN low the boost input is disconnected and OLED_VIN is held at ≈ 0 V, so the
  TPS61040 (EN = VIN) is guaranteed off in sleep and through an MCU reset: OLED_VIN < 0.4 V within 1.6 ms of reset,
  0.05–5.4 mV in sleep over −10…60 °C. With QOD open, D21's reverse leakage from the panel's VCI→VCC ESD path floated
  OLED_VIN up and the boost hiccupped in sleep (hardware/sim, SLP-1, LSW-1). U21 has always-on reverse-current
  blocking (IIN,RCB ≤ 1 µA). +13V_OLED still floats when off (D21 blocks).
  * Inrush is set by the TPS61040 soft start, not by C37 (the boost starts at its ~1.5 V UVLO while U21 is still
    ramping): ≈ 0.3 A for ~2 ms, 0.4 A peak; U21 ramp energy ≤ 0.65 mJ (hardware/sim, LSW-4, OLED-BST-3).
  * Accepted sleep cost (rev A): with the boost off, D21 (B5819W) leaks continuously from the panel-ESD-held
    +13V_OLED (~2.7 V) through U21's QOD: 5.4 µA at 25 °C, ~30 µA at 60 °C, 1.0 µA at −10 °C (docs/architecture.md
    §8.2 carries the budget). Rev-B options, not done: a low-IR rectifier for D21, or the TPS61040 EN on its own GPIO
    with a ≤ 400 kΩ pull-down and U21 QOD open (hardware/sim, sleep budget).
  * FB − OLED_VIN with the OLED off is 0.26–0.29 V (generic vs very strong panel-ESD clamp) against the TPS61040's
    0.3 V abs max, so bring-up measures FB with the OLED off (hardware/sim, LSW-1).
* U20 TPS61040DBVR (C7722): VIN = OLED_VIN (C38 4.7 µF/25 V), L20 = 10 µH SWPA3015S100MT (C45403; Isat 0.72 A
  rated, 0.92 A typical, vs a 0.49 A peak need), D21 = B5819W (C8598), COUT C39 4.7 µF/25 V.
* FB divider: R26 = 499 kΩ (0.5 %) to +13V_OLED, R27 = 52.3 kΩ (**0.1 %**, RT0402BRD0752K3L, C852832) to GND →
  1.233 V × (1 + 499/52.3) = 13.0 V; CFF C40 33 pF C0G across R26 (tune 22–100 pF). EN tied to OLED_VIN (U21 does
  the switching). Accepted risk: the TPS61040 FB bias current (1 µA max) through R26 can move VCC by ±0.5 V; a
  lower-value divider would add ~21 µA of sleep current, so the parts stay and every board is screened for VCC
  12.7–13.3 V (bring-up B-9.9a, repeated as a production test) (hardware/sim, OLED-BST-1).
* The boost inductor and SW node must sit ≥ 10 mm from the TMAG5273 and from
  the magnets (layout note).
* Firmware rules (details in docs/firmware.md §7.2, §7.4 and §13.3):
  * Firmware MUST never set OLED_VCC_EN while the BQ25180 input limit is 100 mA (TMR_ILIM = 0xC9) unless the
    battery can supplement SYS (no BUVLO_STAT and VBAT_est ≥ 3.21 V from a battery-only reading in this power-up; at
    −10 °C the boost surge needs about a 3.204 V cell to keep the BAT pin above BUVLO). Otherwise it raises
    OLED_VCC_EN only after ILIM = 500 mA, and until then shows the charging cue on the LEDs (≤ 20 mA). A dead battery
    cannot supplement SYS and the 100 mA input cannot carry the boost inrush, so without this rule the unit
    reboot-loops exactly in the "battery empty, plug in" case (hardware/sim, NEW-1, OLED-V1).
  * Firmware MUST NOT toggle OLED_VCC_EN during an actuator move when VBAT_est < 3.6 V; it enables the OLED before the
    park move. The OLED turn-on surge on top of a stroke eats the BQ25180 BAT-pin margin to BUVLO at a low cell
    (hardware/sim, NEW-2).
  * After OLED_VCC_EN goes high, firmware waits 200 ms (Orient sequence) before AFh. A wait shortened after measuring
    VCC settling MUST never be below 10 ms: VCC can take ~6.3 ms to reach 12.5 V (VSYS 3.0 V, weak TPS61040, L20
    −20 %, C37 +10 %; 4.9 ms with typical parts), so the old 5 ms floor was too short (hardware/sim, OLED-V2,
    test_startup_time_vs_firmware_floor).
  * Firmware records OLED_VCC_EN in retained RAM; if the next reset is a brown-out or BAT_OCP_FAULT with it recorded
    high, it MUST leave the OLED off for the session and show an error on the LEDs, so a 13 V rail fault (J20 puts
    VCC, pin 2, next to GND, pin 1, at 0.5 mm pitch) cannot reboot-loop the unit (hardware/sim, OLED-V3).
  * Below VBAT_est 3.75 V, and whenever the LED current exceeds its 150 mA sustained cap, firmware MUST hold
    C7 ≤ 08h and ≤ 30 % white area: at low VSYS the boost has almost no headroom over the full-white current
    (hardware/sim, OLED-BST-2).

### 5.4 `leds` — 48× WS2812C-2020-V6 ring
* D101…D148 WS2812C-2020-V6 (C55109522; footprint
  `LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm`), chained DOUT→DIN (nets LED_D1…LED_D47; the last DOUT is LED_D48). Each LED has its own 100 nF 0402 (C1525) on
  VLED/GND (C101…C148, same index).
  BOM rule: D101–D148 must be V6 parts (the data-line margins below are for the V6 input threshold), or fit U43/C43 and
  remove R43 (hardware/sim, LED-DATA-2). WS2812B-2020-V6 (C52917434) is pin-compatible only: at 12 mA/ch the full-white
  ring draws 1.73 A (48 × 3 × 12 mA) and the coincident hardware worst case is ≈ 2.35 A (docs/architecture.md §8.4),
  above the 1 A rating of each of the link's two VSYS contacts when uncapped, so it may be fitted only together with
  the firmware's instantaneous current cap (1.0 A from VBAT_est ≥ 3.92 V, the PI-2 rows in amperes below that)
  (hardware/sim, PI-3).
* LED_DIN_MCU → R40 220 Ω (next to U10 pad 22 = P0.06; limits DIN clamp injection if P0.06 is ever high while VLED is
  off) → LED_DIN_R, with a 100 kΩ pull-down (R41) on LED_DIN_R → R43 0 Ω (fitted) → LED_DIN (D101.DIN).
  D148.DOUT (LED_D48) goes to TP40 with a 100 kΩ pull-down (R42), since V6 DI/DO are swappable.
* Level shifting: none fitted by default (3.3 V drive through R43). DC high-level margin at D101 DI against the V6 VIH:
  +427 mV realistic, and +41 mV on the nRF datasheet bound (VOH = VDD − 0.4 V) at VSYS 4.59 V (SYS_REG 4.5 V + 2 %);
  on the same bound ≈ +116 mV with SYS_REG 4.4 V (VSYS ≤ 4.488 V). The tightest pulse width is T1H (15 ns margin)
  (hardware/sim, LED-DATA-2, LDO-2; architecture risk R27).
  A DNP SN74LV1T34 (U43, powered from VLED, with C43) is provided: remove R43 and fit U43/C43 if the bench test shows
  bit errors.
* Firmware rules (details in docs/firmware.md §6.3–§6.4 and §13.1):
  * P0.06 (I2S0 SDOUT) MUST use `nordic,drive-mode = NRF_DRIVE_H0H1` in its default pinctrl state: standard drive does
    not guarantee the WS2812C T1H/T0L/T1L windows (hardware/sim, LED-DATA-V1).
  * Firmware MUST request the HFXO and wait for it before every LED frame, and release it afterwards: on the HFINT
    (±8 %) the I2S bit timing breaks T1H/T0L (hardware/sim, LED-DATA-V2).
  * BQ25180 SYS_REG_CTRL MUST be 001 (4.4 V), set in the init table (register 0x0A); 010 (4.5 V) is the only other
    allowed value, never higher or pass-through while the LEDs may run, and a firmware assert checks it. VLED = VSYS
    sets the LED's VIH, so a higher SYS eats the data margin above (hardware/sim, LED-DATA-V3, LDO-2).
  * After LED_PWR_EN goes high, firmware MUST wait ≥ 10 ms with P0.06 low before the first frame, so VLED is ≥ 2.67 V
    before DIN goes high (DI abs max VDD + 0.7 V with +3V3 up to 3.366 V; U2 tON ≈ 4 ms; VLED ≥ 2.97 V at 10 ms worst
    case) (hardware/sim, LED-DATA-V4).
  * Switch-off order: all-zero frame, P0.06 low, then LED_PWR_EN low, then the ≥ 30 ms wait of §5.1. Firmware MUST
    never drive P0.06 high while VLED is off: QOD holds VLED at 0 V and DIN would back-power the ring through its ESD
    diode. This is a hard rule unless U43 (Ioff) + C43 are fitted and R43 is removed (hardware/sim, LSW-3).
  * When the loaded VSYS falls below ~3.3 V, firmware MUST send an all-zero frame and drop LED_PWR_EN: VLED = VSYS
    is then below the WS2812C's 3.3 V VDD minimum (hardware/sim, LED-DATA-3).
  * The LED/OLED/motor current limiter is a hardware-protection function: it MUST be active from the first frame after
    reset, and MCUboot and the USB-recovery image MUST keep LED_PWR_EN, OLED_VCC_EN and MOT_NSLEEP low
    (hardware/sim, PI-1).
  * On top of the average cap, firmware MUST apply an instantaneous budget (lit channels × 5 mA), because aligned
    2 kHz PWM draws 0.72 A peaks. The allowed peak, looked up with VBAT_est (§3), rises from 0.19 A at 3.48 V and
    0.26 A at 3.53 V to the full ring at ≥ 3.90 V, less ~0.23 A while the actuator moves; the table assumes the
    OLED-BST-2 dimming (§5.3). On USB VBAT cannot be measured: while VBAT_est (the last battery-only estimate) is
    ≥ 3.48 V, firmware uses the 3.48 V row until CHG_STAT reports CV/done or keeps the instantaneous on-USB sum (lit
    channels × I_ch + OLED boost input + actuator, not an average) ≤ 0.40 A; below 3.48 V, or with VBAT_est unknown,
    only the charging cue (hardware/sim, PI-2, NF-1).
  * When the pack cannot supplement SYS on USB (pack absent, which counts until a battery-only reading in this
    power-up gives a VBAT_est, or STAT1 BUVLO_STAT = 1), firmware MUST
    run the "no supplement" profile: at ILIM 100 mA, LEDs at most the ≤ 20 mA charging cue, OLED off, no flash erase,
    BLE TX 0 dBm, total ≤ 70 mA; at ILIM 500 mA, no actuator moves, LEDs ≤ 100 mA peak-limited, OLED C7 ≤ 08h, total
    ≤ 400 mA. The POF handler sheds the OLED as well as the LEDs and motor (after the 10 ms POF blanking of §5.1).
    Otherwise both USB budgets exceed the
    ILIM minimum (80 / 450 mA) and SYS has no operating point (hardware/sim, PI-4). BUVLO_STAT also covers precharge:
    CHG_STAT has no precharge code (it reports precharge as CC, 01), and with VLOWV = BUVLO = 3.0 V
    (docs/firmware.md §13.1) BUVLO_STAT stays 1 through precharge, because it clears only at 3.11–3.19 V rising,
    above VLOWV's 3.1 V maximum (SLUSE99C §7.5).

### 5.5 `sensors` — encoder, IMU, piezo
* U30 TMAG5273A2QDBVR (C3715882), **bottom side**, θ = 270°, long axis radial, placed so that the **Hall
  element** (offset 0.40 mm toward pin 3 and 0.12 mm toward the pin 1–3 edge from the body centre) is at r = 29.0 mm. Pins: 1 SCL, 2 GND, 3 TEST → GND, 4 VCC, 5 INT, 6 SDA. VCC gets
  100 nF + 1 µF. 4.7 kΩ pull-ups on TMAG_SCL/SDA, 47 kΩ on TMAG_INT_N.
  U32 TPD4E05U06DQAR (C138714) next to the TMAG5273 clamps TMAG_SCL, TMAG_SDA and TMAG_INT_N: the touchable 316L
  ring passes 2.4 mm below. The ring is bonded to GND through the conductive epoxy, the 608 races and the spindle
  (plated H1–H3, §5.1). That is a static bleed path (the final test accepts < 10 MΩ, docs/mechanical.md §12), not a
  low-impedance return for a discharge, so U32 stays.
  The optional DRV5012AEDMRR (C2655038) fallback wake-sensor footprint was not captured on rev A (the only DNP
  parts are R11, C43 and U43).
* U31 LIS2DW12TR (C189624): CS → +3V3 (I2C mode), SA0 → +3V3 (address 0x19,
  **never GND**), RES → GND, VDD 100 nF + 10 µF, VDD_IO 100 nF, INT1 →
  IMU_INT1, INT2 → IMU_INT2, SCL/SDA → I2C_SCL/I2C_SDA.
* System I2C pull-ups R53/R54 4.7 kΩ (I2C_SCL/SDA → +3V3), R55 10 kΩ on CHG_INT_N
  and R56 100 kΩ on BTN_N all live on this sheet (the only ones on either board).
* BZ1 Murata PKMCS0909E4000-R1 (C910763), magnet-free: BUZZ_A → R57 470 Ω → BZ+,
  BUZZ_B → R58 470 Ω → BZ−, and R59 1 MΩ across BZ1 bleeds shock charge while the
  drive pins are disconnected in sleep (hardware/sim, PB-1).

### 5.6 `detent` — actuator driver + home sensor
* U40/U41 2× DRV8837DSGR (C39159): pin 1 VM ← VSYS (C70/C72 0.1 µF each + one
  shared 10 µF 0805 bulk C74, rated ≥ 25 V for DC bias per DRV8837 §8.1), pin 8 VCC ← +3V3
  (C71/C73 0.1 µF each), pin 7 nSLEEP ← MOT_NSLEEP (shared, R70 100 kΩ pull-down),
  IN1/IN2 ← MOT_x_IN1/2, OUT1/OUT2 → coil, pin 4 + EP → GND.
  * The firmware-drive coast peak on VSYS is 5.31 / 5.36 V (θ 0° / 45°) at the worst corner with C74 (140–190 mV
    below the BQ25180 SYS 5.5 V abs max) and 5.42 / 5.48 V without it. No electrical limit catches a missing C74 any
    more, so test_vm_capacitors_per_spec checks it structurally (0.1 µF per VM pin + one ≥ 10 µF 0805 bulk)
    (hardware/sim, MD-5).
  * Firmware MUST brake before sleep on every actuator stop path, including FAULT and abort: IN1 = IN2 = 1 on
    U40/U41 for ≥ 3 ms, then IN = 00 and nSLEEP low. It keeps sine microstepping and never uses full-current full
    steps on USB. Coasting from a full-current hold dumps the coil energy through the DRV8837 body diodes into VSYS,
    and on USB after charge termination (BATFET off) only the VSYS ceramics absorb it, so VSYS can pass the BQ25180
    5.5 V abs max (hardware/sim, MD-1).
* J40 motor: JST SH 4-pin SM04B-SRSS-TB (C160404). Pin 1 = A+ (OUT1 of #1), pin
  2 = A− (OUT2 of #1), pin 3 = B+ (OUT1 of #2), pin 4 = B− (OUT2 of #2). A
  2-wire DC gearmotor can use pins 1–2 only.
* U42 DRV5032FADBZR (C140921) always powered from +3V3 (≤ 2 µA avg), OUT → HOME_N,
  100 nF on VCC. It sits on the **top side** directly above the free-mode park
  position (r = 21.5 mm, θ = 90°). On some units it may also assert near full
  click (field margin), so firmware takes the park stall as the reference and
  uses HOME_N only to confirm it (docs/firmware.md §5.4).

## 6. Base board (`base` sheet)
* J1 USB-C TYPE-C-31-M-12 (C165948), R1/R2 5.1 kΩ on CC1/CC2, U2 USBLC6-2SC6, D1 SMF5.0A (VBUS→GND).
* U1 BQ25180YBGR (C3682423) + caps (§3): C1 2.2 µF/25 V 0805 X7R (CC0805KKX7R8BB225, C277470) on IN, C2 10 µF/25 V
  on SYS, C3 4.7 µF on BAT; RT1 NTC; I2C to the link.
* J2 battery: JST SH 4-pin side-entry SM04B-SRSS-TB (C160404, same part as the motor
  connector). Pins 1–2 = BAT+, pins 3–4 = GND (two 1 A contacts per rail). The pack is
  re-terminated with pre-crimped 28 AWG SH leads (verify the pack polarity before plugging in!).
* SW1 TS-1187A-B-A-B (C318884) at the board centre, top side.
* Q1 BSS138DW (C154900) network with R3 1 kΩ and R4 100 kΩ (§3).
* J3 link connector (§2), C4 10 µF/25 V on VSYS near J3.
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
| 2.5–8.5 | LiPo bay: protected pack **≤ 6.0 thick** at the drawing maximum incl. PCM, so its top stays at z ≤ 8.5, ≥ 1 mm below the base board (z 9.5) as the swelling gap. The BOM pick is a 503450/523450-class pack, ≤ 5.6 mm (docs/mechanical.md §13) | long axis along **θ = 0°/180°** (−27.5 ≤ x ≤ 27.5, −17.25 ≤ y ≤ 17.25); leads exit at the θ = 180° end |
| 5.5–6.0 | **2.4 GHz flex antenna** (Molex **146153-0100**, 100 mm coax) on a printed shelf, centred on the chord y = +23.5 (θ ≈ 90°; strip y 19.0–28.0, corners at r ≤ 33) | ≈ 9.5 mm below the ring, ≈ 6 mm above the desk, ≥ 1.75 mm from the pack side (y = 17.25); coax rises to the spindle side slot. Base-board planes and pours keep ≥ 5 mm away: no plane or pour on B.Cu, In1 or In2 for y > 15.4, no F.Cu pour for y > 17; B.Cu/In2 tracks and vias may come to y ≈ 17.5 (≈ 3.8 mm) |
| 9.5–11.1 | **base board** (Ø46 disc + USB tab to r = 35 at θ = 0°, 4-layer 1.6 mm) | supports: **one M2 boss at r = 20, θ = 270°** (outside the pack, 1.9 mm of FR4 to the edge), a printed **rib** under the θ = 90° edge (y 17.75–18.75, between the pack and the antenna shelf; no boss fits there) and the USB-C shell clamped in the cup wall |
| 11.1–12.6 | press switch TS-1187A (1.5 tall) at the base-board centre | |
| 12.8–14.3 | FA lower plate (PA12, stationary, part of the floating assembly): a **3-spoke spider** (spokes at θ = 60°/180°/300°, ±18°, hub r ≤ 6 with the centre boss over the switch, pre-gap 0.15, outer ring r 26–30 with a **through-notch at θ = 0° for the USB-C** (x ≥ 26.5, −5.6 ≤ y ≤ 5.6; the receptacle top is at z 14.36)). The open sectors centred on θ = 0°/120°/240° clear the tall base-board parts | 3 guide pins + springs at r = 29, θ = 60°/180°/300°, preload ≈ 4 N up against stops |
| 12.8–29.1 | hollow spindle Ø8 × 1.0 wall (316 or titanium), bore Ø6 for link harness + antenna coax | clamped to the lower plate and to the main board; side slots at z ≈ 14.5–16 (below the carrier web) and just under the main board let the harness/coax in and out |
| 15.6–25.6 | **rotor**: 316L ring OD 70 / ID 54, on a PA12-GF carrier web (z 17–19, r 11–27) holding the 608 outer race | ring top face z = 25.6 carries the 48-magnet track (Ø2×2, pockets 2.05 deep, R_t = 29.0) |
| 18.0–25.0 | 608 bearing on the spindle; ≥ 2.5–3 N wave-spring axial preload | outer race r = 11 |
| 19–29.1 | "bowl" under the main board, r 12–27: detent actuator (micro linear stepper on the chord y = 15.5 near θ = 90°, driving the carriage through an inclined-slot link; it sweeps θ ≈ 35–160°) | stationary, hangs from the main-board bottom; bottom-side rules below |
| 26.6–28.6 | detent magnet Ø3×2 N52 on carriage, 1.0 mm above the track; the carriage slides radially r = 29.0 (click) → 21.5 (free) along the θ = 90° radius | carriage plate 0.5 mm, rail fixed to the main-board bottom |
| 29.1–30.7 | **main board** Ø64 (r ≤ 32), 4-layer 1.6 mm | centre Ø5 hole + 3× **plated GND** M2 at r = 6.5 (spindle flange; the ring's ESD bleed path runs ring → conductive epoxy → 608 races → spindle → GND), 2× NPTH M2 at r = 17 θ = 60°/120° (actuator bracket) |
| 30.7–31.6 | LEDs (48× WS2812C-2020) at r = 28.5 | |
| 31.6–34.2 | LED light box (white interior, opaque exterior) r 27–30 | |
| 31.8–32.8 | OLED bracket: rim under the glass edge + 3 spokes to the hub screws (M2 brass through H1–H3) | **0.5 mm rim relief** over J11 and the NFC tail: the rim underside is raised from z 31.8 to 32.3 across the pads (±2.0 mm, r 20.1–24.7 along θ = 222°), leaving 0.5 mm of rim under the glass |
| 33.0–34.7 | OLED glass 33.8 × 34.0 (active-area centre on axis) on the bracket rim; FPC folded under to the ZIF | centred with a corner jig at assembly (the cover no longer locates it) |
| 34.2–36.0 | diffuser ring (opal PMMA, r 27–30) + top cover (stationary) with Ø30 OLED window, cover OD r = 32.5 | the cover ceiling is at z 35.0 inside r 26.35 and carries the NFC coil (next row) |
| 34.80–34.95 | **NFC coil**: annular 2-layer flex, ID 31 / OD 52.5 × 0.15, copper turns in r 24.9–26.15, bonded (0.05 PSA) under the top-cover ceiling, 0.10 above the OLED glass | ≈ 1.75 µH estimate for 4 turns over the In1 GND plane (Wheeler, TVP); C16/C17 stay 180 pF C0G and are retuned once L is measured (the estimate wants ≈ 150–160 pF per side). Tail: a 2.0 mm tongue at **θ = 222°** that folds down at r 24.7 beside the glass and laps onto J11 (r 21.5, θ 222°) under the bracket-rim relief (docs/mechanical.md §9) |

The ring's visible surfaces are the knurled side (z 15.6–25.6) and a top rim
band at r 32.5–35. Overall size is Ø70 × 36 mm.

**Main-board PCB rules that come from the stack**
* No copper pours on **B.Cu or In2.Cu** for r ≥ 26 (this annulus faces the
  magnet track, so pours there add eddy drag). F.Cu/In1.Cu pours are allowed,
  since the track is 3.5–5 mm away. Traces and pads are allowed there.
* Bottom side keep-outs:
  * sector θ = 60°–120°, r 12–32: detent carriage, rails and the middle of the actuator's sweep, no components;
  * the wider actuator corridor θ 30°–160°, r 8.5–27 (rule below): parts at most 1.3 mm tall. The carriage moves
    along the θ = 90° radius, but the chord-mounted actuator sweeps θ ≈ 35–160°; where the two areas overlap, the
    no-component keep-out applies;
  * the spindle flange area r ≤ 8.5.
* Copper keep-outs (no tracks or vias; rule areas from layout.py `clamp_keepouts`):
  * B.Cu at r < 8.8: the brass hub flange (r ≤ 8.5) is clamped against the board bottom by the M4 nut (~120 N), so
    only the GND spindle pads H1–H3 and the GND pour sit there (the hub is GND). In2 tracks may still pass under it;
  * F.Cu at r < 4.6: under the M4 nut (OD 7);
  * all layers within 0.35 mm of the Ø5 centre hole (r < 2.85): Freerouting does not see the inner board edge.
* TMAG5273 on the **bottom** side at (r = 29, θ = 270°). Its long axis is
  radial. Nothing ferromagnetic and no inductor may sit within 10 mm of it.
* DRV5032 on the **top** side at (r = 21.5, θ = 90°).
* LEDs on the **top** side, centred on r = 28.5, with D101 at θ = 0° and
  numbering increasing CCW. Each LED's 100 nF cap goes radially inward (r ≈ 26).
* The OLED ZIF J20 sits on the **top** side under the glass at r = 9.5, θ = 270° (the
  FPC side). The 13 V boost also sits on the top side under the glass and must
  be ≥ 10 mm from the TMAG5273.
* MDBT50Q module on the **bottom** side, centred at r = 17.3, θ = 215°, long axis radial, inner end at r ≥ 8.8 (brass
  hub) and its **u.FL end facing outward** (u.FL at r ≈ 23). A mated u.FL hangs to z ≈ 25.8, so it must not sit over the
  rotating bearing hub (r 9.5–12.5, top z 26.0). The coax runs back under the board beside the module (z ≈ 26 beyond
  r 12.5, ≥ 27 inside it) to the spindle's top slot at θ 270°. It threads between U12 and the module's inner
  corner (0.84 mm to U12, 0.44 mm above the rotating cap ring at r 9–13), so it is tacked up with Kapton tape at
  assembly.
* R40 sits within 3 mm of U10 pad 22 (P0.06), and U12 as close to the module's D+/D− pads as the module courtyard
  allows (layout.py pin anchors): U12 is on the bottom at r 14.6, θ 254°, its D− pad 3.1 mm (pad centre to pad
  centre) from the module's D− pad.
* The link connector J1 (side-entry JST SH) sits on the **bottom** side at r = 19.5 mm, θ = 330°, entry facing the centre,
  so the mated plug's back stays outside the rotating hub. The harness lies flat against the board bottom into the
  spindle's top slot.
* Rotating hub zone: bottom-side parts over r 9.5–12.5 must keep their bottom at z ≥ 26.3 (hang ≤ 2.8 mm).
* Actuator corridor: bottom-side parts in θ 30°–160°, r 8.5–27 must be ≤ 1.3 mm tall (chip passives and test pads;
  J40 is the only component there, and every bottom part was checked against the actuator in
  hardware/mechanical/calcs_output.txt §11); inside θ 60°–120°, r 12–27 the no-component keep-out above applies.
* Top side: keep r ≤ 4.6 free for the spindle's M4 nut (OD 7); other top parts stay inside the LED-cap ring
  (r ≤ 25.3) — beyond it are the light box (r 27–30) and the top-cover skirt.
* The piezo BZ1 goes on the **bottom** side at r = 22, θ = 22° (sound vents through the board).
* The TC2030 pads (J10) go on the top side at r = 20.8, θ = 238.5°, beside the module's SWDIO/SWDCLK/NRESET/SWO
  pins (SWDIO 3.3 mm, SWDCLK 3.9 mm of track). They are still under the OLED glass (at its edge, near the bracket
  rim), so they are reachable only before the OLED bracket and glass are fitted. J10's three NPTH alignment holes clear
  the module (on the bottom) and the J20/J11 courtyards.
* The spare-GPIO test pads TP10–TP13 (TP_SPARE1..4: P0.03, P0.04, P1.11, P1.13) sit on the top side near the
  module's west pad row (r 12–20, θ 193–205°), also under the OLED glass, so like J10 they are reachable before the
  display is fitted.
* The NFC coil pads J11 sit on the top side at r = 21.5, θ = 222°, under the OLED-bracket rim relief; NFC1/NFC2 run
  as a pair, away from the TMAG5273 and the LED data line.
* Assembly order at the display: solder the NFC coil tail to J11 **before** the OLED bracket goes on (the joint ends
  up under the bracket rim), then fit the bracket, then place the glass on the rim with a corner jig, then the cover
  with the coil (docs/mechanical.md §12 step 14).
* Assembly: parts on both sides (the module, TMAG5273, piezo, J1 and J40 among the bottom parts); three fiducials per
  side (FID1–FID6). The board title "dial-me-spinner main rA" is on the bottom silkscreen (r 11, θ 90°): the top silk
  inside the LED-cap ring is full of reference designators.

**Base-board placement rules (§8)**
* The space above the base board is only 1.7 mm, or 1.2 mm when the dial is pressed, wherever an FA spoke or the hub passes over it. Put every part taller than 1.0 mm in the open sectors (θ = 0° ± 40°, 120° ± 40°, 240° ± 40°, r > 6). That means:
  * USB-C J1 at θ = 0° on the tab;
  * USBLC6 U2 and SMF5.0A near J1;
  * link J3 (**side-entry** SH SM12B, ~3 mm tall, entry facing the centre) at r ≈ 15.5, θ = 120°. A vertical header plus plug would reach the rotor web;
  * battery J2 (**side-entry JST SH 4-pin SM04B-SRSS-TB**, 2.95 mm tall, pins 1–2 BAT+, 3–4 GND, top side) at r = 17, θ = 222°, mouth radially outward (body θ ≈ 206–238°, clear of the θ 180° spoke). A PH header (≈ 5 mm + plug) would hit the rotor web when pressed and its plug would reach the spider ring. The pack leads (re-terminated with 28 AWG pre-crimped SH leads, two per rail) run from the pack end at θ 180° beside the pack at z ≈ 10, under the spider, and come up over the board edge at θ ≈ 222°.
* Nothing on the base-board bottom side: the battery sits 1 mm below it. The only exception is pads/test points. RT1 (NTC) is on the top side at r 8, θ 200°, so it reads board/pack-air temperature. Single-sided assembly, three fiducials on the top (FID1–FID3).
* BQ25180 at r = 19.5, θ = 255°: off the pack (|y| > 17.25) in the open θ 240° sector, with stitching vias around its GND ball D2 into both pours and the In1 GND plane (it dissipates up to ≈ 0.6 W while charging). Q1 (BSS138DW, SOT-363 up to 1.1 mm) at r 9, θ ≈ 218°, outside the θ 180° spoke sector.
* Antenna clearance (4 layers: In1 = GND plane, In2 = signals/power): no plane or pour on B.Cu, In1 or In2 for device y > 15.4; B.Cu/In2 tracks and vias may come to y ≈ 17.5; no F.Cu pour for y > 17 (layout.py ANTENNA_KEEPOUT_*).
* SW1 sits exactly at the centre, under the FA boss.

