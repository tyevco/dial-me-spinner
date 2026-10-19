# hardware/mechanical

Parametric OpenSCAD model, calculations and part files for dial-me-spinner rev A.
Design notes, SPEC deviations, PCB placement findings, BOM and assembly order: [`docs/mechanical.md`](../../docs/mechanical.md).

| Path | What |
|---|---|
| `dial_spinner.scad` | Whole-device model (SPEC.md §8). `-D 'view="assembly|section|section_xz|exploded|board_bottom|base_top|clash|part|prims"'`, `-D 'part="base_cup"'`, `-D det_offset=7.5` (free spin), `-D press=1` |
| `extract_board_parts.py` → `board_parts.scad` / `.json` | Component envelopes from `hardware/kicad/*/*.kicad_pcb` (KiCad 9 pcbnew). Re-run after any PCB change. |
| `calcs.py` | Rotor inertia, spin-down (SKF model), detent LUT and ringing, balance, mass budget, springs / press pad / click force, TMAG aliasing, drop and pin pull-out, actuator force budget, per-part clearances read from the model, harness/coax/window/USB checks. Output: `calcs_output.txt`, `renders/calc_*.png` |
| `check_clashes.sh [margin]` (→ `clash_check.py`) | CGAL interference check: rotor envelope, press travel, rest, FA-internal pairs → `clash_report.txt` (legend: `clash_legend.txt`) |
| `export_stl.sh` | Printed and machined parts → `stl/*.stl` (binary, on the bed; spindle, hub, spacer, cap ring are drawing aids for turned/cut metal) |
| `parts_plate.scad` | Overview of the STLs → `renders/parts.png` |
| `render_all.sh` | Regenerate everything (OpenSCAD 2021.01 + xvfb-run + numpy/matplotlib, ~6 min) |

Open items shown by the clash check come from the current PCB placement (MDBT50Q and its u.FL in the hub zone, J1 0.15 mm
above the rotating hub, J2 too tall and its plug in the FA ring, R42 under the cover skirt); see docs/mechanical.md §3B.
