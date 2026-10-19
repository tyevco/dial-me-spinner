# SPICE simulation

The analog parts of both boards are checked by an automated ngspice suite in
[`hardware/sim/`](../hardware/sim/). Every simulation is built from the real KiCad
netlists (`hardware/kicad/*/dial-me-spinner-*.net`), so a schematic change is picked up on the
next run. Passive values come straight from the netlist. ICs are behavioural models in
[`hardware/sim/models/`](../hardware/sim/models/), and each model file names the datasheet and
revision it follows, what it models and what it leaves out.

The latest results, with every measured value next to its datasheet or SPEC limit, are on the
[results page](../hardware/sim/results/report.md). CI regenerates that page (see [CI](#ci)).
The suite is part of the design record: the design changes it drove and the risks it leaves open
are listed under [Design findings](#design-findings).

## Running it

```sh
sudo apt install ngspice            # ngspice 42 or newer
python3 -m pip install pytest numpy scipy            # + pytest-xdist for -n
python3 -m pytest hardware/sim -q -ra              # everything; -ra lists the xfails with their reasons
python3 -m pytest hardware/sim -q -m "not slow"    # skip the long Monte Carlo sweeps (what CI runs on a push)
python3 -m pytest hardware/sim -q -m fault         # only the fault-injection tests
python3 -m pytest hardware/sim/tests/test_load_switches.py -q    # one circuit
python3 -m pytest hardware/sim -q -m "not slow" -n 4             # parallel (pytest-xdist); the report merges all workers
```

Results are written to `hardware/sim/results/report.md` and `results.json` at the end of the session.
Every run overwrites them with the checks of that run only: a `not slow` page has no Monte Carlo
sweeps, and a one-file or `-k` run leaves only those checks. With `-n` the page is complete: every
pytest process (the serial run, or each xdist worker) writes its checks to
`hardware/sim/results/parts/<run id>/<worker>.json` when its session ends and then merges all part files
of the run into `report.md` / `results.json` under a file lock. The last merge (the xdist controller, or
the last worker to finish if the run is interrupted) therefore holds every check that ran, in collection
order, the order of a serial run; the page names the workers it merged. A finished run removes its part
directory, and directories left by interrupted runs are pruned after a day. The `not slow` set took about
4 min with `-n 4` on a 4-core machine.

Decks whose models can stall ngspice's step control at a switching instant can call
`deck.run(fallback=True)`. It is opt-in: the default `run()` makes one attempt with a 300 s timeout and leaves
the options alone. With the fallback, only a "Timestep too small" in the log or a hang triggers a retry, first
with `reltol=1e-3`, then with `reltol=1e-3` + Gear integration + `rshunt=1e12`, 90 s per attempt (the same
ladder as the `run()` wrapper in `test_load_switches.py`). Any other error, and whatever the last attempt
reports, reaches the checks unchanged, so a fallback never hides an error; a hang on every attempt raises the
last timeout. The result records the option lines it added in `_fallback`.

The markers are registered in `conftest.py`: `slow` (long Monte Carlo / sweep runs) and `fault`
(fault-injection tests that prove a check detects a broken design).

## How a test is built

```python
def test_led_data_high_level(main, check):          # main = the main-board netlist
    deck = spicelib.Deck("LED data line")
    deck.include("led_data__ws2812c_din.lib")
    deck += main.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN", "GND"})
    ...
    res = deck.run()
    check("DIN high level vs VIH", res["vhigh"], lo=0.7 * vled, unit="V",
          source="WS2812C-2020-V6 DS, VIH = 0.7·VDD")
```

* `spicelib.Design` reads a netlist and gives `value()`, `pin()`, `node()`, `passives()`,
  tolerance draws (`monte_carlo()`, `extremes()`) and fault injection (`override()`, `remove()`,
  `short()`, `fit()`).
* `spicelib.Deck` builds an ngspice deck (transient, DC, AC, operating point, `.meas`) and runs it
  in batch mode.
* `check()` records every measured value with its limits and source for the report, then asserts it.

## What is covered

Each circuit block is tested from several angles:

* **nominal** operation;
* **supply corners**: battery 3.0 / 3.7 / 4.2 V, USB 4.5 / 5.0 / 5.5 V;
* **temperature** −10 / 25 / 60 °C where a parameter really moves;
* **component tolerances**: all corners for a few parts, Monte Carlo (≥ 200 draws) otherwise;
* **load extremes**;
* **fault injection**: each block has tests that break the design on purpose (a wrong value, a
  part left off, a wrong connection, a DNP option fitted) and assert that the checks catch it.

| Block (`hardware/sim/tests/`) | What is checked |
|---|---|
| Power integrity (`test_power_integrity.py`) | VSYS from battery/USB through the charger, the 12-way link harness and the main-board caps into the LED, OLED, motor and radio loads; minimum VSYS/VLED against the LED and LDO limits; aligned LED PWM peaks; USB with the pack absent or low; the WS2812B drop-in; ground bounce across the link |
| 3V3 LDO (`test_ldo_3v3.py`) | RT9080 start-up and inrush, dropout at low battery, load and line transients, stability with the real output caps, quiescent current, reverse bias when VSYS collapses |
| Load switches (`test_load_switches.py`) | Both TPS22917s (U2 → VLED, U21 → OLED_VIN): ramp time from CT, inrush, QOD discharge (U2 through R4 68 Ω, U21 QOD tied to OLED_VIN), ON thresholds, MCU reset; back-powering through the LED data line and the OLED supply |
| LED data (`test_led_data.py`) | WS2812C data line at 800 kHz: edges, high/low levels against VIH/VIL over VLED, pulse widths with the PS-guaranteed drive (standard vs H0H1), R40 placement, the DNP level-shifter option |
| OLED boost (`test_oled_boost.py`) | U21 + TPS61040 13 V: set point over tolerance (incl. the FB bias current), start-up time vs the firmware wait, ripple, inductor peak current, headroom at the firmware full-white threshold, start-up on USB at 100 mA with a dead battery, shutdown |
| VSYS sense (`test_vsys_sense.py`) | Divider + SAADC sampling error, calibrated accuracy over temperature and aging against the SHIP threshold, production and bring-up windows, input range, settling, sleep current |
| USB input (`test_usb_input.py`) | Hot-plug overshoot at the charger and at the nRF VBUS pin (R12/C12), IEC 61000-4-2 ESD on VBUS and on D+/D− through base U2 and main U12 into the nRF pads, Type-C CC voltages, input capacitance after DC bias |
| Charger TS/MR (`test_charger_ts.py`) | NTC thresholds over temperature (default and programmed TS_CONTROL), an open NTC, the button / ship-mode wake network and its release timing |
| Motor drive (`test_motor_drive.py`) | DRV8837 coil currents at the stepping rates and with the firmware's sine microstepping, thrust vs load, VM ripple and capacitors, supply pulses, inductive kick, the DRV5032 home switch |
| Piezo and buses (`test_piezo_bus.py`) | Piezo drive currents vs GPIO limits; I2C rise times, VOL and TWIM tLOW (nRF52840 errata 219); interrupt lines across the harness |
| Sleep current (`test_sleep_current.py`) | DC leakage paths from the netlist plus IC quiescent currents, against the battery-life budget (architecture §8.2) and the sleep pin states of firmware.md §1.3; boost off in sleep; ship mode |

`test_harness.py` checks the harness itself (value parsing, netlist extraction, an RC step against
the closed form).

A check that shows a real design problem is kept honest: the test is marked
`xfail(strict=True, reason="DESIGN ISSUE: …")`, so it cannot quietly start passing or be loosened.
A strict xfail that passes (XPASS) fails the run. The mark goes when the schematic is fixed (the
test then becomes a guard); firmware-dependent items and accepted risks keep it. A firmware-dependent
xfail keeps the old firmware values as evidence, and its `*_with_fw_rule` twin runs the same deck with
the rule as firmware.md states it and must pass
([Remaining strict xfails](#remaining-strict-xfails)).

## Model notes

* **TPS22917** (`load_switches__tps22917.lib`, TI SLVMCE8 vendor model, turn-on re-calibrated to
  SLVSDW8B Table 7.6): TI's QOD resistor and switch are replaced by one equivalent B-source with the
  same I-V. This is for numerics only: with QOD tied to VOUT, as on U21, the floating node between the
  two original elements stalled ngspice at logic edges.
* **TPS22917 slew** (`load_switches__tps22917.lib` and `oled_boost__tps22917.lib`): the CT current, tON
  and delay use VIN low-pass filtered with 1 ms. With the instantaneous VIN a VIN sag was regenerative
  and the models ran away to 24 A and 18.7 A into large loads.
* **MLCC tolerance** comes from the capacitor's own MPN (Samsung CL series: the 9th character, index 8:
  J/K/M = ±5/10/20 %); DC-bias derating comes from the Samsung curves of that MPN. A capacitor whose MPN
  is not in a test's table fails the run instead of being guessed.

## Design findings

The suite found these problems in the rev A schematics. The finding ids (USB-1, LSW-2, …) are the ones
other documents cite as "(hardware/sim, *id*)".

**Found and fixed in the schematic** (the named tests guard the fixes):

| Id | Found | Fix | Result |
|---|---|---|---|
| USB-1 | A USB hot plug drove the nRF52840 VBUS pin to 6.5–8.4 V (abs max 5.8 V) | R12 4.7 Ω (C2909356) in series from link VBUS to the nRF VBUS pin (net VBUS_NRF); C12 moved to the module side | 4.49–5.49 V for 4.5–5.5 V sources, worst 5.488 V: R12·C12 ≈ 20 µs filters the ring (`test_hotplug_nrf_vbus_abs_max`) |
| USB-2 | ±8 kV IEC 61000-4-2 on D+/D− pushed more than the HBM-2 kV class (1.33 A) into the nRF USB pads | second USBLC6-2SC6 U12 (C7519) at the module's D+/D−, rail on VBUS_NRF | 1.27 A at the 100 mm harness with both arrays at datasheet-max clamps (5 % margin, at an assumed 3 Ω on-chip clamp); typical clamps 0.64–0.84 A. Residual: see accepted risks |
| SLP-1 / LSW-1 | U21 QOD open: D21 reverse leakage from the panel's VCI→VCC ESD path floated OLED_VIN up and the TPS61040 hiccupped in sleep | U21 QOD tied to OLED_VIN | the boost is off in sleep and through an MCU reset: OLED_VIN < 0.4 V within 1.6 ms of reset, 0.05–5.4 mV over −10…60 °C (`test_boost_is_really_off_in_sleep`, `test_mcu_reset_turns_both_rails_off`). +13V_OLED still floats when off (D21 blocks) |
| LSW-2 | VLED took 30.6 ms to fall to 10 % with R4 100 Ω, over the firmware's 30 ms wait | R4 68 Ω (RC0402FR-0768RL, C163455) | 26.6 ms worst case (3.465 V start, the SHIP floor, C8/C9 +20 %, DC bias), 25.7 ms from 4.2 V, Monte Carlo max 25.9 ms, nominal ~24 ms (`test_u2_qod_discharge_tolerance_extremes`) |
| MD-5 | The 10 V 0603 10 µF VSYS caps keep only ~28 % of their value at 5 V | main C2/C6/C41 and base C4 → 25 V CL10A106MA8NRNC (C96446) | firmware-drive coast peak 5.31 / 5.36 V (θ 0 / 45°) at the worst corner with C74 (140–190 mV margin). C74 missing is no longer caught electrically, so it is guarded structurally (`test_vm_capacitors_per_spec`) |
| charger_ts-2 | Base R4 1 MΩ discharged the Q1 gates too slowly on button release | base R4 100 kΩ (C25741) | worst 38.5 µs, inside the BQ25180 deglitch; costs ~42 µA from VBAT only while the button is held |
| USB-3 | Base C1 (2.2 µF/25 V 0603 X5R) fell below the BQ25180's 1 µF effective input capacitance at the temperature corners | 2.2 µF/25 V 0805 X7R (CC0805KKX7R8BB225, C277470) | ≥ 1 µF effective at 5.5 V, −10 and 60 °C (`test_cin_after_dc_bias_temperature`) |
| LED-DATA-1 | R40 (LED data series R) sat at the first LED, not at the driver | R40 pinned next to U10 pad 22 (P0.06) by a layout.py pin anchor | `test_trace_and_r40_placement` |

**Accepted for rev A** (documented, no hardware change):

| Id | Finding | Why it is accepted / what covers it |
|---|---|---|
| Sleep budget | With the boost off, D21 (B5819W) reverse leakage from the panel-ESD-held +13V_OLED (~2.7 V) flows continuously through U21's QOD: 5.4 µA at 25 °C, ~30 µA at 60 °C | Sleep total (typ, 25 °C) 36.0 / 37.4 / 37.5 µA at VBAT 3.0 / 3.7 / 4.2 V; 31.5 / 37.4 / 70.0 µA at −10 / 25 / 60 °C (VBAT 3.7 V). Budgeted in architecture §8.2 and guarded by `test_sleep_current.py`. Rev B options (not done): a low-IR rectifier for D21, or TPS61040 EN on its own GPIO with U21 QOD open (32.2 µA simulated) |
| USB-2 residual | 50 mm harness, +8 kV, both arrays at datasheet-max clamps: ~1.62 A into the nRF pad vs 1.33 A | Rev B option: a lower-clamp second stage (TPD2E2U06 class). Strict xfail |
| LSW-1 margin | With the OLED off, FB − OLED_VIN is 0.26 V (generic panel-ESD clamp) to 0.29 V (very strong clamp) vs the TPS61040 0.3 V abs max | Bring-up measures FB with the OLED off |
| OLED-BST-1 | The 499k/52.3k FB divider turns the TPS61040 FB bias current (1 µA max) into ±0.5 V on VCC | A lower divider would cost ~21 µA of sleep current. Every board is screened at bring-up B-9.9a (VCC 12.7–13.3 V), also a production test. Strict xfail |
| LDO-1 | RT9080 Iq is 2 µA typical, 4 µA maximum | SPEC §3 and architecture §8.2 carry 4 µA as the worst case. Guarded, no longer an xfail: `test_quiescent_current_max_vs_spec` reads the SPEC §3 figure and gives 4.000 µA for the datasheet-maximum part against 4 µA max (`test_quiescent_current_typical`: 2.000 µA against 2 µA typ). The RT9080 model's no-load input current is now exactly IQ at every corner |
| LDO-3 | A fast VSYS collapse (shorted LED behind U2, BATOCP trip) reverse-biases the RT9080 past its 0.3 V VOUT − VIN abs max through the body diode | Architecture risk R38. Strict xfail ×2: VOUT − VIN reaches 0.885 V at a BATOCP trip and 1.723 V with a shorted LED |
| USB-1 note | R12 sits in the source resistance the nRF52840 PS limits to RSOURCE,VBUS ≤ 2 Ω, although PS §7.3 recommends this 4R7 | DC check at VBUS 4.5 V / 1.1 A charger load: 4.378 V vs the 4.35 V minimum (28 mV, resting on the typical 2.4 mA IUSB). Bring-up confirms enumeration at a 4.5 V supply through a 1 m cable |
| USB-4 | Protector stand-offs (USBLC6 5.25 V, SMF5.0A 5.0 V) are below vSafe5V max 5.5 V | Leakage only, no damage. Supported VBUS 4.5–5.25 V; at ~5.5 V the BQ25180 VIN_OVP may stop charging (it runs from the battery) |
| MD-4 | The verified worst-case actuator load 0.8–1.15 N exceeds what the VSM08102 delivers at any battery VSYS (0.93 N best case) | Architecture risk R4, still open (cut preloads to ≤ 0.5 N or a stronger actuator; see mechanical.md §7). Strict xfail |

### Remaining strict xfails

47 tests stay `xfail(strict=True)` (count from the collected marks on 2026-10-19; none of them is in the slow
set): 6 accepted risks, 34 old-rule evidence xfails for firmware rules, 4 cases the firmware rule does not allow,
and 3 where the firmware rule is still insufficient. The sleep-budget xfails are gone and the firmware.md §1.3
pin-table check passes: `test_sleep_current.py` now checks against the architecture §8.2 lines (38 µA total) and
the current pin table (its non-strict `pytest.xfail` fires again only if that table drifts from nets.py).

**Accepted risks** (6, table above): `test_esd_data_lines_nrf_pad_current_short_harness` ×2 (USB-2),
`test_force_vs_verified_worst_load` (MD-4), `test_regulation_with_fb_bias_current` (OLED-BST-1),
`test_reverse_bias_on_vsys_collapse` ×2 (LDO-3). LDO-1 has left this list: `test_quiescent_current_max_vs_spec`
now passes against the SPEC §3 maximum.

**Firmware-dependent** (34 old-rule evidence xfails): the hardware alone breaks a datasheet limit in these cases,
and only a firmware rule prevents it. The xfails keep the old firmware values on purpose, as the evidence for the
rule. Each rule has a guard, most named `*_with_fw_rule`, that runs the same deck, corners and datasheet limits
with the rule as firmware.md states it, and passes. The rules belong in [firmware.md](firmware.md); VBAT_est is the
calibrated rested reading less 75 mV (firmware.md §12.4):

| Strict xfail (old rule) | Without the rule | Firmware rule | Guard (passes) |
|---|---|---|---|
| `test_hw_worst_case_uncapped_dc` ×3 | uncapped LEDs + OLED + both coils (~1.33 A) pull VLED to ~3.05 V at VBAT 3.7 V and +3V3 to 2.41–2.68 V at 3.0 V | The LED/OLED/motor limiter is a hardware-protection function: it MUST be active from the first frame after reset, in MCUboot and the USB-recovery image too, and those images MUST keep LED_PWR_EN, OLED_VCC_EN and MOT_NSLEEP low (hardware/sim, PI-1) | `test_hw_worst_case_uncapped_dc_with_fw_rule` ×8 |
| `test_firmware_capped_sync_pwm_transient` ×5 | aligned 2 kHz PWM draws 0.72 A for 70–210 µs per period; VLED 3.08–3.25 V < 3.3 V at VBAT ≤ 3.70 V | Firmware MUST add an instantaneous lit-channel budget (lit channels × 5 mA) on top of the average cap: 0.19 / 0.26 / 0.33 / 0.42 / 0.51 / 0.69 A at VBAT_est 3.48 / 3.53 / 3.60 / 3.65 / 3.70 / 3.80 V, full ring (0.72 A) from 3.90 V, ~0.23 A less while the actuator moves; rows looked up with VBAT_est, assuming the OLED-BST-2 dimming (hardware/sim, PI-2) | `test_firmware_capped_sync_pwm_transient_with_fw_rule` ×7, `test_led_peak_budget_table_with_fw_rule` ×20 (pack at the row) and `test_led_peak_budget_table_reading_high_with_fw_rule` ×20 (row from a reading 72 mV high): lowest worst-corner margin +13.4 mV. The full@3.65 / full@3.70 points keep only +0.4 / +1.8 mV because they run the OLED at 100 %, which OLED-BST-2 forbids there (+41 / +42 mV with the dimming). Under the earlier wording (row from the reading itself, 0.28 A at 3.53 V) six reading-high cases failed, the worst 3.53-sustained at 3.2561 V; it is now 3.3165 V |
| `test_usb_low_pack` ×2 | on USB the pack supplements SYS, and VBAT cannot be measured | On USB, while VBAT_est (the last battery-only estimate) is ≥ 3.48 V, firmware MUST use the 3.48 V row until CHG_STAT reports CV/done, or keep the instantaneous on-USB sum (lit channels × I_ch + OLED boost input + actuator) ≤ 0.40 A; below 3.48 V or with VBAT_est unknown, only the charging cue (hardware/sim, NF-1) | `test_usb_low_pack_with_fw_rule` ×10 (the 3.48 V row idle and moving; the instantaneous 0.40 A with the OLED at 100 %, off, and with the actuator; both corners): lowest +47.5 mV |
| `test_ws2812b_dropin_peak` | the WS2812B-2020-V6 (12 mA/ch) peaks at 1.73 A, I(BAT) ~1.85 A > IBAT_OCP 1.5 A | The drop-in MUST NOT be fitted without the instantaneous cap: 1.0 A only from VBAT_est ≥ 3.91 V, the PI-2 rows in amperes below that; otherwise it leaves the SPEC §5.4 alternates (hardware/sim, PI-3) | `test_ws2812b_dropin_peak_with_fw_rule` ×2 (4.2 V: I(BAT) ≤ 1.226 A), `test_ws2812b_dropin_threshold_with_fw_rule` ×3 (true 3.913 V: burst VLED 3.3108 V, +10.8 mV) |
| `test_usb_without_battery` ×2 | with the pack absent or below BUVLO nothing supplements SYS above ILIM | A "no supplement" profile MUST apply, and a pack counts as absent until a battery-only reading in this power-up: ILIM-100 phase LEDs at most the ≤ 20 mA charging cue, OLED off, no flash erase, TX 0 dBm, ≤ 70 mA; ILIM-500 phase no actuator, LEDs ≤ 100 mA peak-limited, OLED contrast C7h ≤ 08h, ≤ 400 mA; the POF handler also sheds the OLED (hardware/sim, PI-4) | `test_usb_without_battery_with_fw_rule` ×8 (also with all 48 LEDs lit and aligned) |
| `test_u21_turn_on_dead_battery_usb_100ma`, `test_usb_100ma_dead_battery_oled_enable` | the U21 + boost start-up surge (~0.25–0.4 A for 1–2 ms) at the 100 mA input limit with a dead battery pulls VSYS to ~1.5–2.5 V (load-switch / boost model) and +3V3 below the nRF brown-out: a reboot loop | Firmware MUST never set OLED_VCC_EN while TMR_ILIM = 0xC9 (100 mA) unless the battery can supplement (no BUVLO_STAT, VBAT_est ≥ 3.21 V from a battery-only reading in this power-up); until ILIM is 500 mA show the charging cue on the LEDs (≤ 20 mA). POFWARN is ignored for 10 ms after OLED_VCC_EN or LED_PWR_EN rises (hardware/sim, NEW-1, OLED-V1) | `test_u21_turn_on_dead_battery_usb_100ma_with_fw_rule` ×2, `test_usb_100ma_dead_battery_oled_enable_with_fw_rule`, `test_u21_turn_on_usb_100ma_supplement_with_fw_rule` ×4 (3.21 V cell: BAT pin ≥ 3.040 V at −10 °C; at the earlier 3.15 V reading, a 3.104 V cell, the two −10 °C cases fell to 2.935–2.948 V for > 1.2 ms), `test_u21_turn_on_dead_battery_usb_500ma`. The first and the supplement guard also check +3V3 after the POF blanking |
| `test_phantom_din_abs_max` ×2 | P0.06 high with VLED off puts ~5 mA into D101's DIN clamp, DIN > VLED + 0.7 V | Firmware MUST never drive P0.06 high while VLED is off: send an all-zero frame, drive P0.06 low, then LED_PWR_EN low; after LED_PWR_EN goes high, wait ≥ 10 ms with P0.06 low so VLED is ≥ 2.67 V before the first frame. Fitting the DNP U43 + C43 and removing R43 enforces it in hardware (hardware/sim, LSW-3, LED-DATA-V4) | `test_phantom_din_abs_max_with_fw_rule` ×2 (VLED at the first frame ≥ 2.972 V) |
| `test_pulse_widths_ps_guaranteed_drive[SD]` | standard drive cannot guarantee the WS2812C T1H/T0L/T1L windows | P0.06 (I2S SDOUT) MUST use `nordic,drive-mode = NRF_DRIVE_H0H1` in the default pinctrl state (hardware/sim, LED-DATA-V1) | `test_pulse_widths_ps_guaranteed_drive[HD]` |
| `test_twim_tlow_400k_errata219` | the TWIM at 400 kHz holds SCL low 1.25 µs < 1.3 µs tLOW at every receiver | nRF52840 errata 219: firmware MUST write TWIM0 FREQUENCY = 0x06200000 after init, MUST run TWIM1 at 250 kHz (0x04000000) or 100 kHz, and keeps S0D1 drive on the TWIM pins (hardware/sim, NF-1 I2C) | `test_twim_tlow_errata219_remedy` (TMAG5273 1.306 µs, 6 ns over the minimum; the 100 kHz fallback is not simulated) |
| `test_jeita_charge_prohibit_worst_case[0x00]` | with the default TS_CONTROL the worst-case trips are about −2 °C and +65 °C | Firmware MUST write TS_CONTROL (0x0B) = 0x90 at init (TS_HOT 50 °C, TS_COLD 3 °C) (hardware/sim, charger_ts-1) | `test_jeita_charge_prohibit_worst_case[0x90]` |
| `test_open_ntc_keeps_ts_monitoring_enabled` | an open RT1 can disable TS monitoring instead of reading cold | Firmware MUST treat STAT0.TS_OPEN_STAT = 1 as a fault: set ICHG_CTRL.CHG_DIS = 1 and show "temperature sensor fault". It SHOULD also treat TS COLD with the nRF die above about 10 °C as that fault, since a resistive 46–90 kΩ RT1 leaves TS_OPEN_STAT at 0 (no test) (hardware/sim, charger_ts-v1) | `test_open_ntc_keeps_ts_monitoring_enabled_with_fw_rule` |
| `test_startup_time_vs_firmware_floor` | VCC rises in up to ~6.3 ms, over the old 5 ms floor | The VCC-to-AFh wait MUST never be below 10 ms (hardware/sim, OLED-V2) | `test_startup_time_vs_firmware_floor_with_fw_rule` |
| `test_headroom_at_firmware_full_white_threshold` | at VBAT 3.60 V a worst-case boost delivers ~41 mA < the panel's 42 mA | Firmware MUST apply the OLED contrast cap (C7h ≤ 08h, ≤ 30 % white) below VBAT_est 3.75 V and whenever the LED current exceeds the 150 mA sustained cap (hardware/sim, OLED-BST-2) | `test_headroom_at_firmware_full_white_threshold_with_fw_rule` (also with 150 mA of LED load on VSYS) |
| `test_required_current_at_firmware_move_threshold` | at 3.40 V idle the stroke-load sag leaves the coils below the rated 165 mA | Non-park actuator moves MUST start only from VSYS_est ≥ 3.54 V, i.e. an idle reading ≥ 3.615 V (hardware/sim, MD-2) | `test_required_current_at_firmware_move_threshold_with_fw_rule` (true 3.54 V: 165.3 mA), `test_required_current_at_measured_move_threshold_with_fw_rule` ×2 (reading 24 / 73 mV high: 167.8 / 165.4 mA; the earlier 3.55 V reading, 46 mV high, gave 163.6 mA) |
| `test_firmware_microstep_pwm[VBAT3.7-60C]` | a fixed 20.3 Ω in the duty formula under-drives the hot coil | Firmware MUST use the temperature-compensated duty d = I × (20 Ω × (1 + 0.00393 × (max(T, 25 °C) − 25 °C)) + 0.33 Ω) / VSYS (hardware/sim, MD-3) | `test_firmware_microstep_pwm_with_fw_rule` ×8, every case ≥ 0.500 N (the −10 °C case gave 0.493 N with the earlier (T − 25 °C) form, 0.586 N now) |
| `test_turnoff_kick[usb-chargedone-worst-coast]` | coasting both coils from a full-current hold on USB after charge termination lifts VSYS above the BQ25180 5.5 V abs max | Firmware MUST brake before sleep on every actuator stop path, FAULT and abort included (IN1 = IN2 = 1 for ≥ 3 ms, then IN = 00 and nSLEEP low); keep sine microstepping, never full-current full steps on USB (hardware/sim, MD-1) | `test_turnoff_kick[usb-chargedone-worst-brake-then-sleep]` |
| `test_calibrated_accuracy_over_temperature` ×2, `test_ship_threshold_above_vbatpor` ×2, `test_calibrated_accuracy_after_aging`, `test_ship_threshold_after_aging` | the calibrated VSYS reading drifts by tens of mV over −10…60 °C and with ageing, against the old ±10 mV budget and 3.48 V SHIP threshold | Every protective threshold is a true-cell value compared against VBAT_est; SHIP below VBAT_est 3.465 V, i.e. a 3.54 V reading (was 3.48 V, then 3.53 V); documented drift about ±24 mV at 15–35 °C fresh, +48/−55 mV fresh over −10…60 °C, +30/−36 mV aged at 25 °C, +73/−79 mV aged at −10/60 °C; production calibration MUST take its reference from a DMM at TP1 or with board current < 5 mA (hardware/sim, VSENSE-1/4/5) | `test_calibrated_accuracy_fresh_15_35c_with_fw_rule` ×3, `test_calibrated_accuracy_over_temperature_with_fw_rule` ×2, `test_ship_threshold_above_vbatpor_with_fw_rule` ×2, `test_calibrated_accuracy_after_aging_with_fw_rule`, `test_ship_threshold_after_aging_with_fw_rule`, `test_calibrated_accuracy_aged_over_temperature_with_fw_rule` ×2, `test_ship_threshold_aged_over_temperature_with_fw_rule` ×2 (worst true VBAT at the SHIP reading 3.4676 V against VBATPOR max 3.46 V; 3.4577 V at the earlier 3.53 V), and 8 of the 11 `test_read_margin_covers_over_read_with_fw_rule` thresholds (below) |
| `test_raw_gain_production_window`, `test_uncalibrated_error_bringup` | the ±3 % / ±2 % windows ignore the SAADC ±3 % gain error | Production test 8 MUST use a ±5.5 % raw-gain window and bring-up B-8.5 a ±5.5 % uncalibrated pass (hardware/sim, VSENSE-2/3) | `test_raw_gain_production_window_with_fw_rule`, `test_uncalibrated_error_bringup_with_fw_rule` |

Retired with the current rules (each failed under the earlier rule wording and now passes because the rule is
applied, numbers in the guard column): the six PI-2 reading-high cases, the two NEW-1 supplement cases at −10 °C,
MD-3 at −10 °C, the MD-2 case with an aged-unit reading, and four VSENSE cases at −10 / 60 °C (the fresh-unit
accuracy over temperature and the aged-unit SHIP threshold over temperature).

**Not allowed by the rule** (4): `test_usb_low_pack_with_fw_rule[nominal-total0.40-avg]`, `[worst-total0.40-avg]`,
`[nominal-total0.40-inst-lowpack]` and `[worst-total0.40-inst-lowpack]` run what NF-1 forbids, as the evidence for
its wording: the 0.40 A taken as the limiter's average (VLED 3.156 V worst / 3.258 V nominal at a 3.48 V pack), and
the instantaneous 0.40 A at a 3.30 V pack, below the VBAT_est ≥ 3.48 V condition (3.164 / 3.202 V).

**Firmware rule still insufficient** (3): `test_read_margin_covers_over_read_with_fw_rule[OLED-BST-2-3.75]`,
`[PI-2-row-3.80]` and `[PI-2-row-3.90]`. The fixed 75 mV margin covers the worst calibrated over-read (aged board at
−10 / 60 °C, calibrated with the board under 5 mA) only up to a true 3.72 V; at 3.75 / 3.80 / 3.90 V it is
75.66 / 76.99 / 79.63 mV, so VBAT_est can exceed the true VBAT by 0.7–4.6 mV there. The other eight thresholds pass
(3.21, 3.465, 3.48, 3.53, 3.54, 3.60, 3.65 and 3.70 V; the thinnest is 3.70 V, +0.35 mV). This is open in
firmware.md §18 item 12, with the fix options.

The suite's other firmware rules have no xfail of their own and live in firmware.md only: HFXO before
every LED frame (LED-DATA-V2), SYS_REG 4.4 V (LED-DATA-V3/LDO-2), the ≥ 30 ms wait after LED_PWR_EN low
before VLED counts as off (LSW-2), ≥ 10 ms with P0.06 low after LED_PWR_EN
(LED-DATA-V4, also checked by `test_phantom_din_abs_max_with_fw_rule`), LEDs off below loaded VSYS ~3.3 V
(LED-DATA-3), the LED derating thresholds taken against VBAT_est (`test_vled_at_firmware_led_floor`), the 10 ms
POF blanking after LED_PWR_EN or OLED_VCC_EN (checked in the NEW-1 guards and
`test_bat_pin_vs_buvlo_at_firmware_floor`), the VLED fault latches (NF-3, NEW-5), no
OLED_VCC_EN toggling during moves below VBAT_est 3.6 V (NEW-2), the OLED brown-out latch (OLED-V3), the cold-charge
and press-blanking TS rules (charger_ts-3, charger_ts-v2), QSPI sleep pull-downs (SLP-4) and USB suspend
(V-2, V-3).

## CI

* **Simulation** workflow (`.github/workflows/sim.yml`) is the gate. On a push to `main` and on every
  pull request it runs `pytest hardware/sim -q -ra -m "not slow"` (about 20 min). Every week (Monday
  06:17 UTC) and on a manual dispatch it runs everything, slow sweeps included. A failed check or an
  XPASS of a strict xfail fails the job. The report is appended to the job summary and uploaded as the
  `spice-results` artifact. A new push cancels the suite still running for the same ref.
* **Docs** workflow (`.github/workflows/docs.yml`) runs the `not slow` set again to publish the results
  page with the docs. That step may fail without failing the build; it is interrupted after 17 min with
  SIGINT, so pytest still writes the report of the tests that ran. If no report exists, the build writes
  a placeholder page that points to the Simulation workflow.
