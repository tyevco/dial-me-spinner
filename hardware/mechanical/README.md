# hardware/mechanical

Parametric OpenSCAD model, calculations and printable parts for dial-me-spinner rev A.
Design notes, SPEC conflicts, BOM and assembly order: [`docs/mechanical.md`](../../docs/mechanical.md).

| Path | What |
|---|---|
| `dial_spinner.scad` | Whole-device model (SPEC.md §8). `-D 'view="assembly|section|section_xz|exploded|board_bottom|clash|part"'`, `-D 'part="base_cup"'`, `-D det_offset=7.5` (free spin), `-D press=1` |
| `calcs.py` | Rotor inertia, spin-down (SKF model), detent LUT and ringing, balance, mass budget, press-click force, TMAG aliasing, drop, actuator budget, clearances. Output: `calcs_output.txt`, `renders/calc_*.png` |
| `check_clashes.sh [margin]` | CGAL interference check (rotor envelope / press travel) → `clash_report.txt` |
| `export_stl.sh` | Printable parts → `stl/*.stl` (binary, on the bed) |
| `parts_plate.scad` | Overview of the STLs → `renders/parts.png` |
| `render_all.sh` | Regenerate everything (OpenSCAD 2021.01 + xvfb-run + numpy/matplotlib, ~5 min) |

Known open item shown by the clash check: SPEC's vertical J1 and the MDBT50Q u.FL plug hang into the rotating hub
(see docs/mechanical.md §3, item 7).
