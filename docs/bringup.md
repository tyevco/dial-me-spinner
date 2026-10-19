# dial-me-spinner rev A: bring-up and acceptance tests

This document takes the boards from bare PCBA to an accepted unit. Steps are numbered **B-x** so
[`assembly.md`](assembly.md) can gate mechanical work on them. Do them in order; each step assumes the previous
ones passed. Record every measured number in a per-unit log (the checklist in B-14 is the summary).

* **Architecture of record:** `hardware/design/SPEC.md`. Pin map and net names: `hardware/design/nets.py`.
  BQ25180 firmware register values: `docs/power.md` if present, otherwise the verified values in B-9.4.
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
| Oscilloscope, ≥ 100 MHz, 2–4 channels | Rise times, SPI/LED timing, boost SW node | |
| SWD probe: SEGGER J-Link (EDU Mini fits the 10-pin 1.27 mm header) **or** an nRF52840 DK's "Debug out" header | Programming | |
| Tag-Connect **TC2030-CTX-NL** cable (+ optional TC2030-CLIP) | SWD to the TC2030-IDC-NL footprint (no legs) | [TC2030-CTX](https://www.tag-connect.com/wp-content/uploads/bsk-pdf-manager/TC2030-CTX_1.pdf) |
| Nordic **PPK2** | Sleep and mode currents | Source mode 0.8–5 V |
| VNA reaching 2.5 GHz: **NanoVNA V2 / V2 Plus4 or LiteVNA** + SMA SOL kit + SMA-to-u.FL-receptacle adapter + u.FL extraction tool | Antenna S11 | The original NanoVNA-H/H4 does not usefully reach 2.4 GHz |
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
   | B-6 linked, USB, no battery | USB charger via meter | 5 V | source-limited | < 20 mA |
   | B-9.8 LEDs | bench → base J2 (no USB) | 3.7 V (also 3.4 / 4.2) | 300 mA (1 A only for B-9.8e) | see B-9.8 |
   | B-9.9 OLED | bench → J2 | 3.7 V | 200 mA | see B-9.9 |
   | B-9.10 actuator | bench → J2 | 3.7 V | 600 mA | ≤ 0.45 A peak |

3. **A bench "battery" plus USB at the same time.** The BQ25180 will try to charge the bench supply, which cannot
   sink current, so its voltage creeps up. Either use a real cell, or put a dummy load across the bench supply
   that draws more than the charge current: the power-on default is 10 mA, and 82 Ω at 3.7 V draws 45 mA. Do not
   rely on a dummy load once firmware sets 400 mA.
4. **Never put more than 4.6 V on VSYS** and never 5 V. The LED absolute maximum is 5.3 V, and above about 4.8 V
   the LED data threshold exceeds the nRF's guaranteed high level ([leds verifier]).
5. **LiPo:** check pack polarity before every first connection (J2 pin 1 = BAT+). Do the first charge in a
   LiPo bag, attended.
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
| main | VCOMH tantalum polarity, B5819W cathode to +13V, BAV99 orientation, AO3401A/2N7002 | Per schematic |
| main | ZIF: bottom-contact part, lid present and working, no solder wicking into contacts | OK |
| main | TMAG5273 (bottom, θ 270°): pin 1 orientation, long axis radial | OK |
| main | DRV8837 ×2 exposed pad wetted (side view), LIS2DW12 pin-1 dot, W25Q128 pin 1, crystal | OK |
| main | Nothing ferrous added near the track: no shield cans, no stray screws or washers (B-9.6) | OK |
| both | Vertical JST SH link connectors seated flat, pin 1 as expected (assembly §6) | OK |
| base | USB-C shell legs soldered through; switch SW1 centred and square | OK |
| both | Flux residue, solder balls, especially around the 0.5 mm ZIF and the DSBGA | Clean |

---

## B-3. Unpowered resistance checks

Use the DMM ohms range with the red lead on the node and black on GND. Wait for the capacitors to charge; the
reading climbs. Then run diode test with the **red lead on GND** and black on the rail: expect 0.3–0.8 V
(ESD and body diodes). 0.0x V is a short; "OL" on a rail full of ICs suggests a missing ground. Record the values
from the first good board and compare later boards against them (±20 %).

### B-3a Main board, power nets

| Node (probe at) | Expected | Fail if | Notes |
|---|---|---|---|
| VSYS (TP1) | > 100 kΩ, settling into MΩ | < 1 kΩ | 2.2 M + 1 M divider, LDO, load switch, DRV VM, P-FET source |
| +3V3 (TP2) | > 10 kΩ after charging (record) | < 1 kΩ | Supply pins of nRF, flash, TMAG, IMU, OLED logic, DRV VCC, DRV5032 |
| VLED (TP3) | > 10 kΩ | < 1 kΩ | 48 LEDs, 48× 100 nF, 2× 22 µF |
| +13V_OLED (boost output cap) | **520–580 kΩ** (499 k + 52.3 k FB divider), panel not fitted | outside range | Confirms the divider |
| OLED_VIN (boost input cap) | > 1 MΩ | < 10 kΩ | Behind the AO3401A |
| VBUS (J1 pin 5 / nRF VBUS cap) | > 100 kΩ | < 10 kΩ | |
| VSYS↔+3V3, VSYS↔VLED, VSYS↔OLED_VIN | > 10 kΩ | < 100 Ω | A short here means a damaged LDO, load switch or P-FET |

### B-3b Main board, pull resistors (catches missing or swapped resistors)

| Net | To | Expected |
|---|---|---|
| I2C_SCL, I2C_SDA, TMAG_SCL, TMAG_SDA | +3V3 | ≈ 4.7 kΩ |
| TMAG_INT_N | +3V3 | ≈ 47 kΩ |
| CHG_INT_N | +3V3 | ≈ 10 kΩ |
| BTN_N | +3V3 | ≈ 100 kΩ |
| QSPI_CS | +3V3 | ≈ 10 kΩ |
| OLED_RES_N | GND | ≈ 1 MΩ |
| OLED_VCC_EN, LED_PWR_EN, MOT_NSLEEP, LED_DIN, D48 DOUT test pad | GND | ≈ 100 kΩ (MOT_NSLEEP may read lower because of the DRV8837 internal pull-downs) |
| VSYS_SENSE | GND | ≈ 0.7–1.0 MΩ |
| ZIF pin 22 (IREF) | GND | ≈ 560 kΩ |

### B-3c Base board

| Node | Expected | Notes |
|---|---|---|
| VBUS TP → GND | > 100 kΩ | TVS, USBLC6, BQ IN |
| CC1, CC2 (at connector) → GND | **5.1 kΩ each** | Separate Rd per pin (SPEC §3) |
| VBAT (J2 pin 1 / TP) → GND | > 100 kΩ | |
| VSYS TP → GND | > 100 kΩ | |
| TS/MR → GND | **≈ 10 kΩ at 25 °C** (≈ 11.2 kΩ at 22 °C) | NCP15XH103 NTC, B 3380 |
| SW_GATE → GND | ≈ 1 MΩ; while pressing SW1, SW_GATE → VBAT ≈ 1 kΩ | Press network |
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
| VBUS TP | 4.75–5.25 V | |
| VSYS TP | **4.4–4.6 V** (SYS_REG default 4.5 V) | [BQ25180 datasheet](https://www.ti.com/lit/ds/symlink/bq25180.pdf) |
| TS/MR | ≈ 0.38 V at 25 °C (38 µA bias × 10 kΩ) | > 1.1 V means NTC open or cold fault; < 0.19 V means hot (≈ 45 °C) ([power research]) |
| VBAT TP | Undefined, may sawtooth | With no battery the charger cycles its detection. Do not judge it |

### B-4b Battery only (bench 3.70 V into J2, 20 mA limit, USB unplugged)

| Measure | Expected |
|---|---|
| VSYS TP | ≈ VBAT (within 50 mV; BATFET 55 mΩ) |
| Current | Below the bench meter's resolution (BQ IQ ≈ 3–4 µA; measured properly in B-10) |

If VSYS stays at 0 V, the BQ25180 is in ship mode. Plug USB or hold the press switch for about 2 s.

---

## B-5. Main board alone (bench → TP1 VSYS, 3.70 V, 50 mA limit)

The base and battery are disconnected and the module is unprogrammed (or erased).

| Measure | Expected | Notes |
|---|---|---|
| Supply current | < 10 mA (record) **[TVP]** | An erased nRF52840 sits in a reset/lockup loop. The TMAG5273 powers up in standby (≈ 0.45 mA). A module with vendor demo firmware may draw more |
| +3V3 (TP2) | **3.30 V** (accept 3.20–3.40 V) | RT9080-33 ([DS9080](https://www.richtek.com/assets/product_file/RT9080/DS9080-07.pdf)) |
| VLED (TP3) | < 50 mV | LED_PWR_EN pulled down |
| OLED_VIN, +13V_OLED | < 50 mV | OLED_VCC_EN pulled down; panel not fitted |
| VSYS_SENSE | 1.156 V (VSYS / 3.2); a 10 MΩ DMM reads about 1.09 V | |
| QSPI_CS, BTN_N, CHG_INT_N, TMAG_INT_N | ≈ 3.3 V | Pull-ups |

**LDO dropout sweep:** step VSYS from 4.6 V down to 3.0 V in 0.1 V steps and log +3V3. It should hold 3.30 V
until VSYS is roughly 3.3 V plus dropout, then follow VSYS down. Note where it drops out. The W25Q128JV needs
≥ 2.7 V, so firmware must block flash writes and DFU before that point ([mcu verifier]).

---

## B-6. Both boards linked, USB power, no battery

Connect the tested harness (assembly §6), then plug USB through the meter.

| Measure | Expected |
|---|---|
| USB input current | < 20 mA |
| Base VSYS TP / main TP1 VSYS | 4.4–4.6 V; difference < 20 mV at this load |
| Main TP2 +3V3 | 3.30 V |
| Main J1 pin 5 (VBUS) | ≈ 5 V |

Known limitation: the press network is referenced to VBAT (SPEC §3), so **the dial press may not work on USB
power without a battery**. Test it in B-9.5d.

---

## B-7. SWD programming and UICR configuration

### B-7.1 Hook-up

* TC2030 pads are on the main-board **top under the OLED glass**, so they are only reachable before the panel is
  fitted (SPEC §8). Pinout: 1 VTref (+3V3), 2 SWDIO, 3 NRESET (P0.18), 4 SWDCLK, 5 GND, 6 SWO (P1.00).
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

Set these through devicetree in the board files, `&uicr { nfct-pins-as-gpios; gpio-as-nreset; };`. Zephyr's SoC
start-up writes them on first boot and resets once. Check the readback after a **power cycle**:

```
nrfjprog --memrd 0x10001200 --n 16     # PSELRESET[0], PSELRESET[1], APPROTECT, NFCPINS
nrfjprog --memrd 0x10001304 --n 4      # REGOUT0
```

| Address | Register | Expected | Why |
|---|---|---|---|
| 0x10001200 / 0x10001204 | PSELRESET[0] / [1] | Both PIN = 18, CONNECT = 0 (e.g. 0x00000012 or 0x7FFFFFD2), and both identical | P0.18 is the NRESET pin on TC2030 pin 3 (SPEC §4) |
| 0x10001208 | APPROTECT | Rev 2: 0xFFFFFFFF (debug open). Rev 3: 0x0000005A (HwDisabled), and firmware also writes APPROTECT.DISABLE at boot (NCS default unless `CONFIG_NRF_APPROTECT_LOCK`) **[TVP]** | Keep SWD usable during development |
| 0x1000120C | NFCPINS | **0xFFFFFFFE** (PROTECT = 0, P0.09/P0.10 as GPIO) | **CHG_INT_N is on P0.09 (NFC1)** (SPEC §4). Until this is written, the NFC pad protection is active ([DevZone 88707](https://devzone.nordicsemi.com/f/nordic-q-a/88707/nfc-pins-configured-as-gpio-will-short-together/371967)) |
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

There is no discrete LED. Toggle **TP_SPARE1 (P0.03)** at 1 Hz and watch it on the scope or DMM, and print
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
| vs DMM at TP1 (3.0 / 3.7 / 4.5 V bench), uncalibrated | within ±2 % (two 1 % resistors) |
| After a one-point calibration at 3.80 V | within ±20 mV over 3.3–4.5 V **[TVP]** |

On USB this reads SYS (4.5 V), not the battery. Use the BQ25180 CHG_STAT field while charging.

### B-8.6 USB

| Check | Pass |
|---|---|
| USBREGSTATUS.VBUSDETECT with USB plugged | 1 (VBUS ≥ 4.3 V guaranteed) |
| CDC-ACM sample enumerates (`lsusb`, Device Manager) | Enumerates first time, no resets in `dmesg` |
| 1 MB loopback | 0 errors |

D+/D− pass through the base ESD, about 70 mm of harness and the module. Full Speed tolerates that, but watch for
retries.

### B-8.7 MCUboot and recovery (do it after B-9.1 QSPI and B-9.5 battery)

MCUboot uses signed images, with the secondary slot on the QSPI flash ([mcu verifier]). Check:

* Image upload over USB CDC with mcumgr, swap, confirm.
* The same over BLE SMP (nRF Connect Device Manager).
* **Serial recovery:** hold the dial press while resetting or plugging USB. This needs the battery connected
  (B-6 note).

**All three must pass before the OLED is fitted.** After that, SWD is under the glass.

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
* Scope the SCL rise time at 400 kHz. It must be ≤ 300 ns. TWIM1 includes two harness wires; if it is slow, run
  TWIM1 at 100 kHz (housekeeping only) **[TVP]**.

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
| 0x08 | TMR_ILIM | **0xCD** | Long press 20 s, autowake 1 s, ILIM code 500 mA (≈ 475 mA typ) |
| 0x09 | SHIP_RST | 0x09 | Long press = hardware reset, WAKE1 300 ms, WAKE2 2 s, push-button enabled |
| 0x0A | SYS_REG | 0x40 | SYS 4.5 V on USB |

Rev A has no CC-line sensing (CC goes only to 5.1 kΩ), so stay at 400 mA / 0xCD. Do not use the 500 mA / 700 mA
ILIM pair that the verifier allows only for a detected 1.5 A or 3 A source.

| Check | Pass |
|---|---|
| CHG_INT_N (P0.09) on the scope while plugging and unplugging USB | **≈ 128 µs active-low pulses** ([power research]). A line stuck low, or no pulses, points to NFCPINS (B-7.3) or the 10 kΩ pull-up |

**Before firmware writes SHIP_RST:** with the power-on default, a 10 s press enters ship mode and SYS goes off.
Wake with a 2 s press or USB.

### B-9.5 Battery, charging, ship mode, press network

**B-9.5a First battery connection.** Check polarity first (assembly §7.2). Use a pack at 3.5–4.0 V. Connect with
USB unplugged.

| Check | Pass |
|---|---|
| VSYS (base TP) | VBAT ± 50 mV |
| Main +3V3 | 3.30 V |

**B-9.5b Charging.** Use a real protected cell at 3.5–3.9 V, a 5 V ≥ 1 A USB source, and keep the system idle
(LEDs and OLED off).

| Check | Pass |
|---|---|
| Battery current in constant-current phase (DMM in series with the pack lead) | **380–420 mA** (ICHG 400 mA, ILIM ≈ 475 mA) |
| STAT0 CHG_STAT sequence | CC → CV → done |
| VBAT at "done" (measured at J2) | **4.18–4.22 V** (VBATREG 4.20 V ±0.5 %) |
| Termination current | ≈ 40 mA (ITERM 10 %) |
| Board temperature beside the BQ25180 after 15 min, 25 °C ambient | < 60 °C **[TVP]**. Dissipation (5.0 − 3.7) V × 0.4 A ≈ 0.52 W gives a ≈ +27–35 °C junction rise ([power research]); TREG 100 °C throttles beyond that |
| Charge current with LEDs on | Drops (DPPM). This is expected, not a fault |
| JEITA: warm RT1 gently above 45 °C (hand warmth or a hair dryer, not hot air) | Status shows the warm condition and charging adapts |

**B-9.5c Ship mode, shutdown, hardware reset.**

| Action | Expected |
|---|---|
| Write 0x09 = **0x49** (ship) | SYS off within ms. Wake by holding the press ≈ 2 s, or by plugging USB |
| Write 0x09 = **0x29** (shutdown) | SYS off. Wake **only** by USB |
| Hold the press 20 s (after the init writes) | Hardware reset: SYS power-cycles |

The currents for these modes are measured in B-10.

**B-9.5d Press network** (battery connected; SPEC §3).

| Node | At rest | Pressed |
|---|---|---|
| SW_GATE (base) | ≈ 0 V | ≈ VBAT |
| BTN_N (main, P1.10) | 3.3 V | **< 0.4 V** |
| TS/MR (base) | NTC bias level | < 90 mV (pulled down by Q1; charging pauses during a press, as the datasheet specifies) |
| BTN_N release time | | < 1 ms |

Also confirm a press wakes the nRF from System OFF through SENSE on P1.10.

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

**B-9.6c With the rotor installed** (after assembly Stage C). Turn the ring slowly by hand through one full
revolution while logging X (tangential) and Z.

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

| Check | Pass |
|---|---|
| Each pin on the scope | 0–3.3 V, opposite phase |
| Tone | Clear |
| Level at 10 cm (phone SPL app, indicative only) | ≈ 72–79 dB(A). Murata specifies ≥ 65 dB(A) at ±1.5 V0-p ([leds research/verifier](https://www.lcsc.com/product-detail/C910763.html)) |
| Tick: 1–2 cycles | Audible click |

### B-9.8 LED ring (48× WS2812C-2020-V6)

**B-9.8a VLED switch.** Bench into J2 at 3.7 V, 300 mA limit. With LED_PWR_EN (P1.04) low, VLED < 50 mV. Then
assert LED_PWR_EN and scope VLED and VSYS together.

| Check | Pass |
|---|---|
| VLED rise time (10–90 %) | **≈ 1.5–2.5 ms** (CT = 1 nF) |
| Inrush | ≤ ~100 mA |
| VSYS dip during enable | ≤ 100 mV |
| VLED steady | VSYS − I × RON (RON ≈ 80 mΩ) |
| VLED fall after LED_PWR_EN low | Discharged by QOD in about 10–20 ms ([power verifier]) |

If VLED rises in tens of µs and VSYS dips hard, the CT capacitor is not doing its job. Check its return node
(assembly §2.4: TPS22917 CT to VIN, TPS22918 CT to GND) before running any LED test.

**B-9.8b Data timing.** Use Zephyr `worldsemi,ws2812-i2s` on i2s0 with `clock-source = "PCLK32M_HFXO"`,
`chain-length = <48>`, GRB, `lrck-period = <10>` (3.2 MHz), `nibble-zero = <0x8>`, `nibble-one = <0xC>` and
`reset-delay = <300>` ([leds verifier](https://docs.zephyrproject.org/latest/build/dts/api/bindings/led_strip/worldsemi,ws2812-i2s.html)).
The driver default nibble 0xE violates T1L, so it must be overridden. Scope LED_DIN after the 33 Ω resistor:

| Parameter | Expected | V6 spec ([datasheet](https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf)) |
|---|---|---|
| Bit period | 1.25 µs | |
| T0H | 312.5 ns | 220–380 ns |
| T1H | 625 ns | 580 ns–1 µs |
| T0L | 937.5 ns | 580 ns–1 µs |
| T1L | 625 ns | 580 ns–1 µs |
| Reset gap | ≥ 280 µs | |
| Ringing | < 0.5 V | |

**Sequencing:** enable VLED, wait ≥ 5 ms, then send the first frame. To turn off: send an all-zero frame, drive
DIN low, then release LED_PWR_EN. **Never drive DIN high with VLED off**; the input limit is VDD + 0.7 V.

**B-9.8c Walk test.** Light one LED at a time at 10 % red, starting from **D1 at θ = 0° (the USB-C side)** and
stepping **CCW seen from the top** through D48. Repeat in green and blue. Each step must light exactly one LED in
the right place. A dead LED blanks everything after it.

**B-9.8d End of chain.** Send 49 pixel words. The 49th word must appear on the D48 DOUT test pad on the scope,
which proves every LED passes data.

**B-9.8e Current** (VSYS 3.7 V):

| Pattern | Expected |
|---|---|
| VLED on, all pixels 0 | Record. Standby is ≤ 1 µA/LED by datasheet; the "operating" current per IC is unknown, possibly ≈ 0.2 mA each **[TVP]** |
| One LED, one channel at 255 | ≈ 5 mA above baseline |
| Whole ring white at 10 % | ≈ 72 mA (48 × 3 × 5 mA × 0.1) |
| Whole ring white at 25 % | ≈ 180 mA |
| **Once only**, full white ≤ 2 s at a 1 A limit | ≈ 0.72 A; VLED droop ≤ 100 mV; no reset |

Firmware cap: **300 mA burst / 150 mA sustained** ([leds research]). If the WS2812**B**-2020-V6 (12 mA/ch) was
fitted instead, full white is 1.73 A: never test it, and the cap must be active from first boot.

**B-9.8f Logic margin.** Run the walk test for 10 min with VSYS at 4.6 V (bench), then at 3.4 V. There must be no
glitches. At VLED 4.5 V, VIH = 0.55–0.6 × VLED = 2.48–2.70 V, against the nRF's VOH ≥ 2.9 V at VDD 3.3 V. The
margin is small and has to be measured, not assumed ([leds research]).

**B-9.8g Low battery.** At VSYS 3.4–3.5 V with white at 25 %, record the colour shift. Firmware derates below
3.50 V.

**B-9.8h Thermal.** Run 10 min at the 150 mA sustained cap. Board temperature rise near the ring ≤ 15 °C
**[TVP]**.

### B-9.9 OLED (SSD1351, NHD-1.5-128128G)

**B-9.9a Bare boost: panel NOT fitted.** Bench at 3.7 V, 100 mA limit.

| Check | Pass |
|---|---|
| OLED_VCC_EN (P1.02) low | OLED_VIN < 50 mV, +13V_OLED ≈ 0 V |
| OLED_VCC_EN high: OLED_VIN | ≈ VSYS |
| OLED_VCC_EN high: +13V_OLED | **12.7–13.3 V** (1.233 V × (1 + 499/52.3) = 13.00 V) |
| Input current, no load | < 2 mA (TPS61040 IQ 28 µA + 24 µA divider + switching) |
| SW node on the scope | Clean PFM bursts; tune CFF 22–100 pF (SPEC 33 pF) if it is erratic or audible |

**Abort above 13.5 V** (panel limit; Orient abs max 16 V) or below 12.5 V. The datasheet worst case with 0.5 %
resistors is about 12.6–13.4 V before the FB bias-current term ([display verifier](https://www.ti.com/lit/ds/symlink/tps61040.pdf)).

Turn the boost off and **discharge +13V_OLED with 1 kΩ** before fitting the panel. It only decays through
551 kΩ (τ ≈ 6–7 s).

**B-9.9b Panel** (after B-7 and B-8, fitted per assembly §7.4). Bench limit 200 mA.

With VCC_EN low, +13V_OLED floats at about VCI − Vf (≈ 2.5–3 V) through the panel's internal ESD path. That is
expected ([display verifier]).

Bring-up sequence ([NHD datasheet](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf),
[SSD1351](https://cdn-shop.adafruit.com/datasheets/SSD1351-Revision+1.3.pdf)):

1. RES# low ≥ 2 µs (use 10 µs), then high.
2. Vendor init, including `A0 74` (65k RGB565), `B4 A0 B5 55` and `C7 08–0A`.
3. Clear GDDRAM.
4. VCC_EN high.
5. Wait **≥ 200 ms** (vendor).
6. `AF`.

SPI settings: SPIM3 (SPEC §4), mode 0. Start at 8 MHz, then go to 16 MHz. **Never above 20 MHz** (SSD1351
t_cycle ≥ 50 ns). SPIM3 errata:

* Anomaly 198: TX buffers must be in dedicated RAM blocks RAM6/RAM7 (0x2000C000–0x2000FFFF), with
  `CONFIG_NRF52_ANOMALY_198_WORKAROUND`.
* Anomaly 195: after disabling SPIM3, write 1 to 0x4002F004, otherwise the peripheral keeps drawing about 900 µA
  ([errata 198](http://docs.nordicsemi.com/r/bundle/errata_nrf52840_rev3/page/err/nrf52840/rev3/latest/anomaly_840_198.html)).

| Test | Pass |
|---|---|
| Colour bars; solid R/G/B at C7 = 0x08 | Uniform |
| Single-pixel grid every 8 px | No missing rows or columns. Missing lines usually mean the FPC is not fully in the ZIF |
| Orientation | Upright, centred on the active area (the 1.47 mm offset is mechanical) |
| SCK at the ZIF on the scope | t_R/t_F ≤ 15 ns, t_CLKL/H ≥ 20 ns. If not, use H0H1 drive ([display verifier]) |
| Current (battery side, VSYS 3.7 V): black with VCC on | ≈ 5 mA |
| Typical dark UI | ≈ 14–26 mA |
| Full white **only at C7 = 0x08, briefly** | Well under the ≈ 146 mA maximum-contrast figure ([display research]) |
| Below VSYS 3.4 V | Firmware caps brightness; the boost delivers only about 33–40 mA at 3.0 V |
| Sleep: `AE`, `AB 00`, VCC_EN low, RES# held high | Panel ≈ 10 µA typ, 35–40 µA max (measured in B-10) |
| Wake: `AB 01`, VCC on, ≥ 200 ms, `AF`, full redraw | Image back in about 0.2–0.4 s |
| Listen at near-black | No audible PFM whine (about 15 kHz at 1.5 mA). If present, see the CFF note above |

### B-9.10 Detent driver (2× DRV8837), home sensor, actuator

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

**B-9.10b Motor.** Check coil pairs ≈ 20 Ω (VSM08102; measure yours): A on J pins 1–2, B on 3–4. Set a 600 mA
limit.

| Check | Expected |
|---|---|
| Full steps at 100 PPS, ≤ 50 % amplitude | Smooth motion, 0.02 mm per full step |
| Full stroke | 375 full steps = 7.5 mm |
| Phase current at 100 % | ≈ 185 mA (3.7 V) to 225 mA (4.5 V) |
| Supply peak | ≤ 0.45 A |
| After every move | End on a full step, all IN low, nSLEEP low, so hold power is zero (the lead screw self-locks) ([detent research]) |

**B-9.10c Home sensor.** HOME_N (P1.14) comes from a DRV5032FA: push-pull, low = magnet present, always powered,
sampling at 13–37 Hz. Wait ≥ 75 ms before reading after a move. Log HOME_N against step count over park → click
→ park at 50 PPS.

| Position | Expected |
|---|---|
| Within ≈ 4–5 mm of PARK | HOME_N low ([detent research]) |
| At the CLICK end | HOME_N **high** |

**Check this on every unit.** SPEC puts the DRV5032 on the **top** side, so the die sits only ≈ 2.3–2.8 mm from
the magnet (stack-up estimate). The research placed it at 3.0–3.5 mm. At 2.5 mm the field at the click position
is about 1.3 mT, close to the sensor's 1.5 mT minimum operate point ([detent research](https://www.ti.com/lit/ds/symlink/drv5032.pdf)).
If a unit reads "home" at click, use only the HOME *assertion* near park as the lost-step check
([detent verifier]) and log it for rev B.

**B-9.10d Homing and stroke.**

1. From an unknown position, step toward PARK at 50–100 PPS and ≤ 50 % amplitude until HOME asserts, then add
   ≤ 20 overdrive steps into the park stop. Park is force-free, so stalling there is safe.
2. Define position 0 = park. Step 375 to CLICK and back. HOME must re-assert within ±20 steps of the expected
   count. Otherwise re-home; after 3 failures go to FAULT and stay in FREE ([detent research]).
3. Speed profile: ≤ 300–500 PPS through the magnetically loaded 0–4 mm zone, ≤ 800–1000 PPS beyond. Expect
   ≈ 0.6–0.9 s per full stroke ([detent verifier]).

**Robustness:** 50 round trips with the rotor resting in a detent well. HOME error must stay within ±2 steps.

---

## B-10. Sleep and mode currents (PPK2)

### Setup

1. Remove the pack and connect the **PPK2 in source mode to J2** (pin 1 +, pin 2 GND). Use 3.7 V, and repeat
   the key modes at 4.2 V and 3.4 V.
2. **Unplug USB.** Remove the TC2030 cable: the probe back-powers the chip through VTref and SWDIO. Disable RTT
   and UART logging.
3. Enter the mode, wait 10 s, then average over a ≥ 10 s window. TMAG wake samples, the BQ25180 TS bias pulses
   (every 200 ms), DRV5032 sampling (about 20 Hz) and BLE events are all periodic.

The PPK2 replaces the pack, so the pack's own protection circuit (PCM) is not included. Real battery drain is the
reading plus about 3–6 µA. Readings below about 1 µA are at the instrument floor.

### Targets per mode

The targets are derived from datasheet typicals ([TVP]). Tighten them after the first good unit.

| Mode | How to enter | Expected typ | Pass |
|---|---|---|---|
| **Shutdown** | BQ 0x09 = 0x29 | 0.015 µA (BQ) | ≤ 1 µA (floor) |
| **Ship** | BQ 0x09 = 0x49 | 3.2 µA (BQ only) | ≤ 4.5 µA ([BQ25180](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) |
| **System OFF, press wake only**, panel fitted | nRF System OFF; TMAG sleep; IMU power-down; flash deep power-down; OLED `AE` + `AB 00` + VCC off | ≈ 22–25 µA | ≤ 30 µA |
| Same, panel not fitted | | ≈ 11–13 µA | ≤ 16 µA |
| **System OFF + rotation and motion wake** | Above, plus TMAG W&S at 100 ms and IMU low-power at 12.5 Hz | ≈ 27–30 µA | ≤ 35 µA |
| **System ON idle, armed** (no BLE) | Zephyr idle, TMAG W&S at 10 ms, IMU wake | ≈ 45–50 µA | ≤ 60 µA |
| + BLE connected idle (15 ms interval, latency 30) | | + ≈ 7 µA | ≤ 70 µA |
| + BLE advertising at 1 s | | + ≈ 11 µA | ≤ 75 µA |
| Active controller: dark UI, LEDs off, tracking, BLE | | ≈ 20–30 mA | record |
| Game spin, LEDs at the 150 mA sustained cap | | ≈ 170–200 mA | record |

### Contribution budget (for debugging a high reading)

| Contributor | State | Typ µA | Source |
|---|---|---|---|
| BQ25180 | Battery mode, push-button enabled | 4 (5 max) | [BQ25180](https://www.ti.com/lit/ds/symlink/bq25180.pdf) |
| BQ25180 TS bias into the NTC | 60 µA pulsed 4 ms per 200 ms | ≈ 1.2 (may already be in IQ) **[TVP]** | [power research] |
| RT9080 LDO | Always on | ≈ 2 | [DS9080](https://www.richtek.com/assets/product_file/RT9080/DS9080-07.pdf) |
| VSYS divider 2.2 M + 1 M | Always on | 1.16 at 3.7 V | SPEC §3 |
| nRF52840 | System OFF / System ON idle (Zephyr, RTC) | 0.4 / ≈ 3 | [nRF52840 PS](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/_tmp/nrf52840/autodita/current/parameters.i_sleep.html), [mcu verifier] |
| DRV5032FA | Always on (SPEC §5.6) | 1.6 (3.5 max) | [DRV5032](https://www.ti.com/lit/ds/symlink/drv5032.pdf) |
| DRV8837 ×2 | Sleep | 0.07 (0.24 max) | [DRV8837](https://www.ti.com/lit/ds/symlink/drv8837.pdf) |
| W25Q128JV | Deep power-down / standby | ≈ 1 / tens of µA | [mcu research and verifier] |
| TMAG5273 | Sleep / W&S 100 ms / W&S 10 ms / **standby** | 0.005 / ≈ 3 / ≈ 17–20 / **450** | [TMAG5273](https://www.ti.com/lit/ds/symlink/tmag5273.pdf), modelled **[TVP]** |
| LIS2DW12 | Power-down / LP1 at 12.5 Hz | 0.05 / ≈ 1 (at 1.8 V; more at 3.3 V) | [sensing verifier] |
| OLED panel asleep (VCI/VDDIO always on) | ICI 4 + RES# 1 MΩ 3.3 + VCI→VCC ESD path into 551 kΩ ≈ 5 | ≈ 12 (35–40 max) | [display verifier] |
| TPS22917 off; TPS61040 (input disconnected) | Off | 0.01 / ~0 | [power research] |

### Excess current: likely causes

| Excess over target | Likely cause | Check or fix |
|---|---|---|
| ≈ +0.45 mA | TMAG left in standby, e.g. after a threshold wake that was never re-armed | Read DEVICE_CONFIG_2 and re-arm W&S |
| ≈ +0.9 mA | SPIM3 not fully off (anomaly 195) | Write 1 to 0x4002F004 after disable |
| ≈ +15 µA | A wake pin on a GPIOTE IN channel instead of PORT/SENSE (17.37 vs 2.36 µA) | Use `sense-edge-mask` |
| ≈ +70 µA | TMAG_INT_N latched low through its 47 kΩ pull-up | Read CONV_STATUS to clear it |
| +10–50 µA | QSPI flash not in deep power-down | Send B9h; enable the driver's power management |
| +60–170 µA | LIS2DW12 SA0 grounded (address 0x18) | Assembly/schematic fault |
| ≈ +33 µA (+4 µA on base) | BTN_N held low: switch pre-gap is 0 | Mechanical, assembly §11.4 |
| ≈ +5 mA | OLED VCC left on (black screen) | `AE` + VCC_EN low |
| mA level | VLED left on, logging backend active, CPU not sleeping | Check LED_PWR_EN, disable UART/RTT |
| Constant ≈ 1.6–3.5 µA | DRV5032 (always on by design) | Not a fault |

---

## B-11. RF: antenna S11 in the real enclosure, and link checks

The SPEC places a Molex 146153 flex antenna on the base floor, connected by coax to the module's u.FL. There is
**no matching network** anywhere in the design, so tuning means placement or antenna choice.

### B-11.1 VNA setup

1. NanoVNA V2 / V2 Plus4 or LiteVNA. Sweep **2.0–3.0 GHz**, ≥ 401 points, with averaging or a low IF bandwidth.
2. SOL calibration at the SMA reference plane.
3. Add the SMA-to-u.FL-receptacle adapter and apply port extension: with the adapter open, adjust the electrical
   delay until the trace collapses to a point on the right edge of the Smith chart across the sweep.
4. Every mate counts against the u.FL's ~30-cycle rating. Plan the sequence and use the extraction tool.

### B-11.2 Measurements

Record the frequency of minimum |S11| and |S11| at 2400, 2440 and 2480 MHz for each:

| # | Configuration | Purpose |
|---|---|---|
| a | Antenna alone, taped to foam ≥ 30 mm from anything | Baseline ([Molex 146153](https://www.molex.com/ja-jp/products/part-detail/1461530100)) |
| b | In the base-cup recess, cup only | Plastic loading |
| c | Base complete: battery, base board, harness | Nearby conductors |
| d | **Full device**, rotor fitted, top cover and OLED off for access, on a wooden desk. Antenna u.FL unplugged from the module and plugged into the VNA adapter, cable led out through the top | **Acceptance** |
| e | As d, on a metal plate (laptop lid or steel desk), and with a hand gripping the dial | Sensitivity. The antenna faces the desk (SPEC §8) |

**Pass (d):** |S11| ≤ −10 dB from 2400 to 2483.5 MHz. **Marginal:** ≤ −6 dB at the worst band edge, accepted
only if B-11.3 passes **[TVP]** ([mcu research]). Case e is informative; record how far it moves.

**Tuning levers:**

* Move or rotate the flex within the recess.
* Increase spacing to the battery, harness and coax.
* Change the floor thickness or material under the antenna. Molex tunes these flexes for mounting on plastic of a
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
Wheel / Surface Dial settings (report 100 units = 10.0° per detent; configurable) ([mcu research]).

---

## B-13. Spin-down acceptance (FREE mode)

**Conditions:**

* Detent parked (HOME asserted).
* Device on a level wooden desk at 20–25 °C.
* Bearing prepared per assembly §9 and run in (10 spins first).
* Rotor fully assembled and balanced.

**Procedure:**

1. Flick the ring above 10 rev/s. Firmware logs ω(t) from the TMAG at ≥ 100 Hz (decimated).
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
| 3 | B-2 | Visual: 48 LED orientation, polarised parts, ZIF type | All correct | |
| 4 | B-3a | VSYS, +3V3, VLED to GND | > 1 kΩ (no short) | |
| 5 | B-3a | +13V_OLED to GND | 520–580 kΩ | |
| 6 | B-3b | Pull resistors | Within ±10 % of nominal | |
| 7 | B-3c | CC1, CC2 to GND | 5.1 kΩ each | |
| 8 | B-3c | TS/MR to GND | 8–13 kΩ at 20–30 °C | |
| 9 | B-4a | Base VSYS on USB | 4.4–4.6 V; input < 5 mA | |
| 10 | B-4b | Base VSYS on bench battery | VBAT ± 50 mV | |
| 11 | B-5 | Main +3V3 | 3.20–3.40 V; supply < 10 mA unprogrammed | |
| 12 | B-5 | VLED, OLED_VIN off | < 50 mV | |
| 13 | B-6 | Linked on USB: main VSYS, +3V3 | 4.4–4.6 V, 3.30 V; < 20 mA | |
| 14 | B-7.2 | FICR PART / VARIANT recorded | 0x52840; revision noted | |
| 15 | B-7.3 | NFCPINS, PSELRESET, REGOUT0 | 0xFFFFFFFE; PIN 18 ×2; 0xFFFFFFFF | |
| 16 | B-7.3 | SWD after a power cycle | Attaches | |
| 17 | B-8.3 | LFCLKSTAT | 0x00010001 | |
| 18 | B-8.5 | VSYS ADC vs DMM | ±2 % raw; ±20 mV calibrated | |
| 19 | B-8.6 | USB CDC enumeration and loopback | 0 errors | |
| 20 | B-8.7 | MCUboot: USB DFU, BLE DFU, serial recovery | All pass **before the OLED is fitted** | |
| 21 | B-9.1 | QSPI JEDEC ID, quad R/W 1 MB | EF 40 18; 0 errors | |
| 22 | B-9.2 | I2C scans | TWIM0: 0x35. TWIM1: 0x19, 0x6A | |
| 23 | B-9.3 | LIS2DW12 WHO_AM_I, \|a\|, INT1 | 0x44; 0.9–1.1 g; pulse on tap | |
| 24 | B-9.4 | BQ25180 register readback | Matches the table | |
| 25 | B-9.4 | CHG_INT_N pulses on USB plug/unplug | ≈ 128 µs low pulses | |
| 26 | B-9.5b | Charge current in CC | 380–420 mA | |
| 27 | B-9.5b | VBAT at termination | 4.18–4.22 V | |
| 28 | B-9.5b | Charger area temperature | < 60 °C at 25 °C ambient **[TVP]** | |
| 29 | B-9.5c | Ship wake (2 s press, USB) and shutdown wake (USB only) | Both work | |
| 30 | B-9.5d | BTN_N on press (centre + 3 rim points) | < 0.4 V every time | |
| 31 | B-9.6a | TMAG IDs | 0x5449; variant 2 | |
| 32 | B-9.6c | Track signal | 24 periods; Bz 12–25 mT; per-pole ±15 % | |
| 33 | B-9.6d | W&S wake on a small rotation | INT latches; re-arm verified | |
| 34 | B-9.7 | Piezo at 4 kHz | Clear tone, ≈ 72–79 dB(A) at 10 cm | |
| 35 | B-9.8a | VLED rise time; VSYS dip | ≈ 1.5–2.5 ms; ≤ 100 mV | |
| 36 | B-9.8b | LED bit timing | Within the V6 windows | |
| 37 | B-9.8c/d | Walk test, D1 at θ = 0° CCW; 49th word at DOUT | All 48 correct | |
| 38 | B-9.8e | Ring white at 10 % | ≈ 72 mA above baseline (±25 %) | |
| 39 | B-9.8f | Logic margin at 4.6 V and 3.4 V | No glitches in 10 min | |
| 40 | B-9.9a | Bare boost output | 12.7–13.3 V | |
| 41 | B-9.9b | OLED full test pattern, no missing lines | Pass | |
| 42 | B-9.9b | SCK edges at the ZIF | t_R/t_F ≤ 15 ns | |
| 43 | B-9.10a | DRV8837 truth table, both drivers | All five states | |
| 44 | B-9.10c | HOME_N low near park, high at click | Both, on this unit | |
| 45 | B-9.10d | 50 round trips | HOME error ≤ ±2 steps | |
| 46 | B-10 | Ship current | ≤ 4.5 µA | |
| 47 | B-10 | System OFF, press wake only, panel fitted | ≤ 30 µA | |
| 48 | B-10 | System ON idle, armed | ≤ 60 µA | |
| 49 | B-11.2d | S11, full device on a wooden desk | ≤ −10 dB over 2400–2483.5 MHz | |
| 50 | B-11.3 | HID link at 5 m, 10 min, LEDs and OLED animating | No drops | |
| 51 | B-12.2 | 24 detent rest angles | Within ±0.5° of the 15° grid | |
| 52 | B-12.3 | T(0 mm) | 16.4 mN·m ±25 % (slip mass ≈ 36–60 g at r = 35) | |
| 53 | B-12.4 | FREE rest-angle histogram | Uniform (no preferred angle) | |
| 54 | B-13 | Spin-down from 10 rev/s, median of 10 runs | **≥ 45 s (target ≥ 60 s)** | |
| 55 | B-13 | Viscous coefficient c | ≤ 1e-6 N·m·s | |
| 56 | assembly §10 | Residual imbalance | ≤ 2 g·mm target, ≤ 3.6 g·mm max | |
| 57 | final | Unit left in ship or shutdown mode for storage | Done | |

## Open [TVP] items for the first prototype

1. VLED soft-start (CT reference node) and the inrush it produces (B-9.8a).
2. HOME_N release at the click end with the top-side DRV5032 (B-9.10c).
3. Antenna S11 and link margin with the desk-facing antenna, on wood and on metal (B-11).
4. TMAG W&S currents and wake angle; LIS2DW12 current at 3.3 V (B-10).
5. Detent torque at R = 29 mm versus the R_t = 30 mm simulation; ringing count without a damping shoe (B-12).
6. Absolute spin time, and whether the oil holds up (B-13).
7. Register-level ID values (W25Q128 JEDEC, LIS2DW12 WHO_AM_I, TMAG IDs, BQ25180 power-on values), which were
   not confirmed against primary sources in the research set.
