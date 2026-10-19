# dial-me-spinner

**Docs site:** <https://tyevco.github.io/dial-me-spinner/>

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

> **Status: rev A. Schematics and both PCB placements are generated; nothing
> has been built or tested.** The schematics of both boards pass ERC. The only
> report is one intended pin pair that `build.py` waives and lists (U21's QOD
> tied to its VOUT). Both boards are placed by `layout.py`; for the routing,
> DRC and fab-output status, see the PR. `release.py` writes fab outputs into
> `hardware/fab/` only after DRC and schematic parity pass. The mechanical
> model's clash check of the generated boards reports only the intended
> contacts. A SPICE suite (`hardware/sim/`, [docs/simulation.md](docs/simulation.md))
> checks the analog design against the netlists; the part changes it drove
> are in the schematics. No prototype has been built and no firmware has been written.
> Every runtime, force and spin-time figure in the docs is a calculation or
> simulation that still has to be verified on a prototype.

## Features (rev A design)

| | |
|---|---|
| Size | Ø70 × 36 mm. Stationary centre, spinning 316L stainless ring (≈ 117 g, OD 70 / ID 54 / 10 mm) on a single 608 bearing |
| Detents | 24 clicks per turn, strength continuously variable from 0 to about 16.5 mN·m, or free spin (the detent magnet's residual cogging is 2.7 µN·m; the stepper's own cogging still has to be bench-tested, [mechanical §7](docs/mechanical.md#7-detent-mechanism)). Switched by a micro linear stepper with a self-locking lead screw (zero holding power) |
| Rotation sensing | TI TMAG5273 3D Hall sensor reading the same 48-magnet track. Interpolated angle, about 0.05–0.1° after self-calibration, plus µA-level wake on rotation |
| Display | 1.5 in 128×128 RGB PMOLED (SSD1351) behind a Ø30 mm round window |
| Lights | 48 × WS2812C-2020-V6 RGB LEDs under an opal diffuser ring, 2 per detent |
| Input | Press-down click (the whole top floats on springs over a centre switch), rotation, tap and pick-up (LIS2DW12 accelerometer) |
| Sound | Magnet-free piezo for detent ticks and UI beeps |
| Radio | nRF52840 module (Raytac MDBT50Q-U1MV2, u.FL) with an off-board flex antenna in the base. BLE HID, a custom GATT service for a companion app, and USB HID |
| NFC | NFC-A tag emulation (Type 2 / Type 4) on the nRF52840 NFCT, with a coil in the top cover. Phones read it; the spinner cannot read tags (the phone app reads one and sends the content over BLE) |
| Power | 1S LiPo of about 1000 mAh, TI BQ25180 power-path charger, USB-C. Ship mode, about 38 µA sleep (25 °C typical; [power budget](docs/architecture.md#8-power-budget-and-battery-life)) |
| Estimated runtime | About 9 h of continuous game mode, about 4 weeks of typical desk-controller use per charge (see the [power budget](docs/architecture.md#8-power-budget-and-battery-life)) |

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System overview, how each requirement is met, block diagram, board partition and link, subsystem decisions with the alternatives that were rejected, power tree, power budget and battery life, RF strategy, risk register, open decisions, rough BOM cost |
| [docs/assembly.md](docs/assembly.md) | Fabrication and assembly: JLCPCB order settings, sourcing, the link harness and antenna coax, magnet track, bearing prep, rotor balancing, mechanical assembly order |
| [docs/bringup.md](docs/bringup.md) | Bring-up and acceptance tests (steps B-x), from bare PCBA to an accepted unit |
| [docs/mechanical.md](docs/mechanical.md) | Mechanical design: stack-up and where SPEC §8 is not buildable as written, bearing, flywheel and balancing, magnet track, detent mechanism, press click, antenna placement, drop, feet, assembly order, mechanical BOM, calculations |
| [docs/firmware.md](docs/firmware.md) | Firmware architecture plan (nRF Connect SDK / Zephyr, MCUboot), including the BQ25180 register init table (§13.1). A plan only: no firmware code exists yet |
| [docs/simulation.md](docs/simulation.md) | The SPICE suite in `hardware/sim/`: how to run it, how a test is built, what each block covers; the latest values are on its [results page](hardware/sim/results/report.md) |
| [docs/display-study.md](docs/display-study.md) | Rev-B study (future work): a larger round touch AMOLED. Rev A keeps the SSD1351 OLED |
| [hardware/design/SPEC.md](hardware/design/SPEC.md) | **Architecture of record** for the schematics: boards, link pinout, power tree, nRF52840 pin map, per-sheet contents, mechanical stack-up |
| [hardware/tools/README.md](hardware/tools/README.md) | The Python → KiCad generator toolchain |

## Repository layout

```
docs/                    design documentation (start with architecture.md;
                         simulation.md for the SPICE suite, display-study.md
                         for rev B)
hardware/
  design/                the circuit as code
    SPEC.md              architecture of record (what the schematics implement)
    nets.py              pin map and the shared net names (the "capture contract")
    build.py             generates the schematics (.kicad_sch), project file and
                         netlist from the sheet modules, and runs ERC
    layout.py            generates the boards (.kicad_pcb) from the netlists:
                         SPEC §8 placement of the constrained parts, clustering
                         of the rest, outline, keep-outs, zones, fiducials,
                         optional Freerouting autoroute, then the grid router
                         (hardware/tools/finish_route.py) for what it leaves
                         open, clean-up (GND stitching vias, silkscreen
                         references), then DRC
    release.py           fab and review outputs into hardware/fab/<board>/:
                         gerbers, JLCPCB BOM + CPL, ORDER-NOTES.md, schematic and
                         board PDFs, 3D renders; refuses to write them unless DRC
                         and schematic parity are clean
    jlc_offsets.json     cached per-LCSC-part rotation/origin corrections for the
                         JLC CPL (written by tools/jlc_cpl.py)
    sheets/              one Python module per schematic sheet
                         main board: main_power, mcu, display, leds, sensors, detent
                         base board: base
  tools/                 generator toolchain: S-expression I/O, symbol/footprint
                         generation, schematic writer, PCB builder, placer, fab outputs
    silk.py              places silkscreen references clear of pads, other silk
                         and the board edge
    jlc_cpl.py           fits JLC's EasyEDA footprints to the KiCad ones and writes
                         the CPL (top θ+α, bottom 180−θ+α)
  kicad/                 generated KiCad 9 projects (main/, base/): schematics from
                         build.py, .kicad_pcb from layout.py
  fab/                   generated by release.py, one directory per board (main/,
                         base/): gerbers.zip, *-BOM-JLCPCB.csv, *-CPL-JLCPCB.csv,
                         ORDER-NOTES.md (DNP list, bottom-side parts, board-only
                         parts), PDFs, renders
  mechanical/            enclosure and rotor CAD (OpenSCAD), calculations, renders
                         and STLs; board parts imported from the generated PCBs
                         (extract_board_parts.py) for the clash check
  sim/                   SPICE test suite (ngspice + pytest) that builds its
                         decks from the generated netlists: tests/test_*.py,
                         IC models in models/, report written to results/
                         when run (docs/simulation.md)
firmware/                (planned) nRF Connect SDK / Zephyr application
```

The schematics in `hardware/kicad/` are **generated**. Do not hand-edit the
`.kicad_sch` files. Change the sheet modules in `hardware/design/sheets/` (and
SPEC.md or nets.py if the architecture changes), then rebuild.

## Regenerating the KiCad projects

Requirements:

* **KiCad 9**, providing:
  * `kicad-cli`;
  * the `pcbnew` Python module, used to write custom footprints and by
    `layout.py` and `release.py`;
  * the stock libraries and project template in `/usr/share/kicad`.
    `KICAD9_SYMBOL_DIR` overrides the symbol path (used by `build.py`).
    `KICAD9_FOOTPRINT_DIR` overrides the footprint path, and only `layout.py`
    reads it. The project template path
    (`/usr/share/kicad/template/kicad.kicad_pro`) is fixed in `schgen.py`.
* **Python 3.10+**, with numpy for `layout.py` and the CPL writer, and matplotlib for the grid router.
* **poppler-utils** (`pdftoppm`), only for `--render`.
* Optionally `xvfb-run`, which `release.py` uses for headless 3D renders.
* For autorouting only: **Java 21** and the **Freerouting 2.1.x** jar, given
  by `FREEROUTING_JAR`.

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

Boards and fab outputs (after `build.py`, which writes the netlists they read):

```sh
# Place both boards and run DRC; add --route to autoroute with Freerouting
# (--minutes N is the Freerouting time budget of the first attempt, default 30,
# and attempt k gets k x N; --attempts N, default 3, re-runs it while
# connections remain; whatever is still open then goes to the grid router;
# --resume continues routing the board as it is; --complete runs only the grid
# router on it; --finish only cleans up an already routed board)
python3 hardware/design/layout.py [--board main|base] [--route] [--minutes N] [--attempts N] [--resume] [--complete] [--finish]

# Gerbers, JLCPCB BOM + CPL, ORDER-NOTES.md, PDFs and 3D renders into
# hardware/fab/<board>/; stops if DRC or schematic parity reports an error
# (--force writes a review-only package)
python3 hardware/design/release.py [--board main|base] [--force]
```

The CPL corrections come from `hardware/design/jlc_offsets.json`, so
`release.py` needs no network access. It stops if a placed part has no entry
there; `jlc_cpl.update_offsets()` adds one by fetching that part's EasyEDA
footprint.

## Running the SPICE suite

The suite reads the netlists that `build.py` writes, so run it after a
schematic change. It needs ngspice 42 or newer and pytest, numpy and scipy
([docs/simulation.md](docs/simulation.md)):

```sh
python3 -m pytest hardware/sim -q                  # everything
python3 -m pytest hardware/sim -q -m "not slow"    # skip the long Monte Carlo sweeps
```

It writes `hardware/sim/results/report.md` and `results.json`. A check that
shows a real design problem is a strict `xfail` with the reason, so it cannot
quietly start passing.

## Status and next steps

* **Done:** subsystem research with independent verification. Architecture
  (SPEC.md). Generator toolchain. Schematics of both boards, ERC-clean
  apart from the one documented `build.py` waiver.
  Both boards placed (`layout.py`: SPEC §8 placement of the constrained parts,
  clustering of the rest); for routing, DRC and fab outputs, see the PR.
  The fab-output script `release.py`, which writes Gerbers, the JLCPCB BOM and
  CPL (rotations corrected per LCSC part), ORDER-NOTES.md, PDFs and renders
  behind a DRC and schematic-parity gate. The placement fixes from the
  mechanical model's clash check (module u.FL facing outward, link connector
  J1 at r 19.5, the 2.95 mm SM04B battery connector, R42 clear of the cover
  skirt), after which the check reports only the intended contacts. The SPICE
  suite in `hardware/sim/` and the part changes it drove (VBUS series resistor
  R12, a second USB ESD array U12 at the module, the OLED load switch's QOD
  tied to its output, R4 68 Ω for the LED rail discharge, 25 V VSYS caps, base
  C1 and R4). Assembly, bring-up, mechanical, simulation and firmware-plan
  documents.
* **In progress:** the SPEC items in mechanical §3A. The remaining strict
  `xfail`s of the SPICE suite are firmware-dependent rules (written into
  firmware.md and SPEC §5) or accepted rev-A risks, such as the USB ESD
  margin with a short harness, the actuator thrust and the OLED boost's
  FB-bias spread ([docs/simulation.md](docs/simulation.md)).
* **Not done:** no prototype has been built or tested, and no firmware code has
  been written. Every item marked "to verify on prototype" in the docs is
  still open. The detent actuator's thrust margin is open (architecture risk
  R4).
* **Next:**
  * close the pre-order checks in [assembly §2.4](docs/assembly.md#24-pre-order-checks-do-them-in-the-gerber-viewer-not-only-in-kicad)
    and [§13](docs/assembly.md#13-open-items-and-tvp-list-assembly)
    (LED-cavity silk, boost-inductor spacing), then order both boards with
    the outputs `release.py` writes into `hardware/fab/`: two-sided assembly
    for the main board, top side only for the base board (4-layer, ENIG), the
    MDBT50Q through JLC Global Sourcing or consignment, the DNP list from
    ORDER-NOTES.md;
  * a printed mechanical mock-up to check the antenna shelf, the harness and
    coax path and the ring's ESD bleed path, and to measure the RF antenna
    (VNA/RSSI), spin-down and detent feel, plus a bench test of the stepper's
    free-mode cogging before the PCB is frozen;
  * bring-up of the first prototype ([docs/bringup.md](docs/bringup.md)) and
    the items to verify on it;
  * firmware, following [docs/firmware.md](docs/firmware.md).
* Known issues and open decisions are tracked in
  [architecture §10–§13](docs/architecture.md#10-risk-register) and
  [assembly §13](docs/assembly.md#13-open-items-and-tvp-list-assembly).

Long-lead parts to order early: the SSD1351 OLED panel (0 stock at major
distributors in Oct 2026), the MDBT50Q-U1MV2 module (0 stock at JLC: use JLC
Global Sourcing or consign it) and the Molex 146153-0100 antenna (DigiKey/Mouser;
LCSC stocks only the -0050, which is too short).
