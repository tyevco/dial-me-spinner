# dial-me-spinner

A Bluetooth dial spinner about 70 mm across, built on the nRF52840. A heavy,
balanced stainless flywheel ring spins around a stationary centre that holds a
colour OLED and a ring of 48 addressable RGB LEDs. You can press the whole top
to click. A tiny actuator switches the ring electronically between **free
spin** and **magnetic click detents**, and it holds either position with zero
power.

The same hardware serves three uses:

* **Game / decision spinner.** You flick the ring and a prize wheel animates on
  the LEDs and the OLED, with a tick on every detent and the result shown when
  it stops.
* **PC / phone controller.** It works like a Surface Dial: a BLE or USB HID
  Radial Controller on Windows, and a wheel or consumer-control device on
  macOS, Linux, Android and iOS.
* **Fidget toy.** Long free spins or clicky spins, with a spin and RPM counter.

> **Status: rev A, design in progress. Nothing has been fabricated or
> tested.** Schematic capture is under way. PCB layout, mechanical CAD and
> firmware have not started. Every runtime, force and spin-time figure in the
> docs is a calculation or simulation that still has to be verified on a
> prototype.

## Features (rev A design)

| | |
|---|---|
| Size | Ø70 × 36 mm. Stationary centre, spinning 316L stainless ring (124 g, OD 70 / ID 54 / 10 mm) on a single 608 bearing |
| Detents | 24 clicks per turn, strength continuously variable from 0 to about 16.5 mN·m, or free spin with no perceptible cogging. Switched by a micro linear stepper with a self-locking lead screw (zero holding power) |
| Rotation sensing | TI TMAG5273 3D Hall sensor reading the same 48-magnet track. Interpolated angle, about 0.05–0.1° after self-calibration, plus µA-level wake on rotation |
| Display | 1.5 in 128×128 RGB PMOLED (SSD1351) behind a Ø30 mm round window |
| Lights | 48 × WS2812C-2020-V6 RGB LEDs under an opal diffuser ring, 2 per detent |
| Input | Press-down click (the whole top floats on springs over a centre switch), rotation, tap and pick-up (LIS2DW12 accelerometer) |
| Sound | Magnet-free piezo for detent ticks and UI beeps |
| Radio | nRF52840 module (Raytac MDBT50Q-U1MV2, u.FL) with an off-board flex antenna in the base. BLE HID, a custom GATT service for a companion app, and USB HID |
| Power | 1S LiPo of about 1000 mAh, TI BQ25180 power-path charger, USB-C. Ship mode, about 32 µA sleep |
| Estimated runtime | About 9 h of continuous game mode, about 4 weeks of typical desk-controller use per charge (see the [power budget](docs/architecture.md#8-power-budget-and-battery-life)) |

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System overview, how each requirement is met, block diagram, board partition and link, subsystem decisions with the alternatives that were rejected, power tree, power budget and battery life, RF strategy, risk register, open decisions, rough BOM cost |
| [docs/mechanical.md](docs/mechanical.md) | Mechanical design: stack-up, rotor, bearing, press mechanism, detent carriage, tolerances |
| [docs/power.md](docs/power.md) | Charger configuration (BQ25180 registers) and power-management firmware notes |
| [hardware/design/SPEC.md](hardware/design/SPEC.md) | **Architecture of record** for the schematics: boards, link pinout, power tree, nRF52840 pin map, per-sheet contents, mechanical stack-up |
| [hardware/tools/README.md](hardware/tools/README.md) | The Python → KiCad generator toolchain |

## Repository layout

```
docs/                    design documentation (start with architecture.md)
hardware/
  design/                the circuit as code
    SPEC.md              architecture of record (what the schematics implement)
    nets.py              pin map and the shared net names (the "capture contract")
    build.py             generates the KiCad projects from the sheet modules
    sheets/              one Python module per schematic sheet
                         main board: main_power, mcu, display, leds, sensors, detent
                         base board: base
  tools/                 generator toolchain: S-expression I/O, symbol/footprint
                         generation, schematic writer, PCB builder, fab outputs
  kicad/                 generated KiCad 9 projects (main/, base/); created by build.py
  mechanical/            enclosure and rotor CAD and drawings
firmware/                (planned) nRF Connect SDK / Zephyr application
```

The schematics in `hardware/kicad/` are **generated**. Do not hand-edit the
`.kicad_sch` files. Change the sheet modules in `hardware/design/sheets/` (and
SPEC.md or nets.py if the architecture changes), then rebuild.

## Regenerating the KiCad projects

Requirements:

* **KiCad 9**, providing:
  * `kicad-cli`;
  * the `pcbnew` Python module, used to write custom footprints;
  * the stock symbol and footprint libraries in `/usr/share/kicad`. Override
    the paths with `KICAD9_SYMBOL_DIR` / `KICAD9_FOOTPRINT_DIR` if they live
    elsewhere.
* **Python 3.10+**.
* **poppler-utils** (`pdftoppm`), only for `--render`.

From the repository root:

```sh
# Both boards: writes hardware/kicad/main/ and hardware/kicad/base/,
# runs ERC and exports a netlist for each
python3 hardware/design/build.py

# One board, plus a PDF and one PNG per sheet for review
python3 hardware/design/build.py --board main --render

# Scratch build of selected sheets into another directory, without ERC
python3 hardware/design/build.py --board main --only leds sensors --out /tmp/scratch --no-erc
```

Each board directory receives:
* `dial-me-spinner-<board>.kicad_pro`, the `.kicad_sch` sheets and a `.net`
  netlist;
* the ERC report `erc.rpt`;
* a project-local library in `lib/` (`dial_spinner.kicad_sym` and
  `dial_spinner.pretty`).

Open the `.kicad_pro` in KiCad 9 to inspect the result. `build.py` exits
non-zero if its own connectivity checks fail.

## Status and next steps

* **Done:** subsystem research with independent verification. Architecture
  (SPEC.md). Generator toolchain.
* **In progress:** schematic capture of all sheets with clean ERC.
* **Next:**
  * a printed mechanical mock-up to measure the RF antenna (VNA/RSSI), spin-down
    and detent feel;
  * PCB layout of both boards with DRC, then fab outputs;
  * firmware bring-up.
* Known issues and open decisions are tracked in
  [architecture §10–§13](docs/architecture.md#10-risk-register).

Long-lead parts to order early: the SSD1351 OLED panel (0 stock at major
distributors in Oct 2026) and the MDBT50Q-U1MV2 module (0 stock at JLC).
