# SPICE simulation

The analog parts of both boards are checked by an automated ngspice suite in
[`hardware/sim/`](../hardware/sim/). Every simulation is built from the real KiCad
netlists (`hardware/kicad/*/dial-me-spinner-*.net`), so a schematic change is picked up on the
next run. Passive values come straight from the netlist. ICs are behavioural models in
[`hardware/sim/models/`](../hardware/sim/models/), and each model file names the datasheet and
revision it follows, what it models and what it leaves out.

The latest results, with every measured value next to its datasheet or SPEC limit, are on the
[results page](../hardware/sim/results/report.md). CI regenerates that page on every build.

## Running it

```sh
sudo apt install ngspice            # ngspice 42 or newer
python3 -m pip install pytest numpy scipy
python3 -m pytest hardware/sim -q                  # everything
python3 -m pytest hardware/sim -q -m "not slow"    # skip the long Monte Carlo sweeps
python3 -m pytest hardware/sim -q -m fault         # only the fault-injection tests
```

Results are written to `hardware/sim/results/report.md` and `results.json`.

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

| Block | What is checked |
|---|---|
| Power integrity | VSYS from battery/USB through the charger, the 12-way link harness and the main-board caps into the LED, OLED, motor and radio loads; minimum VSYS/VLED against the LED and LDO limits; ground bounce across the link |
| 3V3 LDO | RT9080 start-up, dropout at low battery, load and line transients, stability with the real output caps |
| Load switches | Both TPS22917s: ramp time from CT, inrush, QOD discharge, ON thresholds; back-powering through the LED data line and the OLED supply |
| LED data | WS2812C data line at 800 kHz: edges, high/low levels against VIH/VIL over VLED, pulse widths, the DNP level-shifter option |
| OLED boost | TPS61040 13 V: set point over tolerance, start-up, ripple, inductor peak current, shutdown |
| VSYS sense | Divider + SAADC sampling error, input range, settling, sleep current |
| USB input | Hot-plug overshoot at the charger and the ESD array, IEC 61000-4-2 ESD, Type-C CC voltages |
| Charger TS/MR | NTC thresholds over temperature, the button / ship-mode wake network |
| Motor drive | DRV8837 coil currents at the stepping rates, VM ripple, supply pulses, inductive kick |
| Piezo and buses | Piezo drive currents vs GPIO limits; I2C rise times and VOL, interrupt lines across the harness |
| Sleep current | DC leakage paths from the netlist plus IC quiescent currents, against the battery-life budget |

A check that shows a real design problem is kept honest: the test is marked
`xfail(strict=True, reason="DESIGN ISSUE: …")` until the schematic is fixed, so it cannot quietly
start passing or be loosened.
