# hardware/mechanical

Parametric OpenSCAD model, calculations and part files for dial-me-spinner rev A.
Design notes, SPEC deviations, PCB placement findings, BOM and assembly order: [`docs/mechanical.md`](../../docs/mechanical.md).

| Path | What |
|---|---|
| `dial_spinner.scad` | Whole-device model (SPEC.md §8). `-D 'view="assembly|section|section_xz|exploded|board_bottom|base_top|clash|nfc|part|prims"'`, `-D 'part="base_cup"'`, `-D det_offset=7.5` (free spin), `-D press=1` |
| `extract_board_parts.py` → `board_parts.scad` / `.json` | Component envelopes from `hardware/kicad/*/*.kicad_pcb` (KiCad 9 pcbnew); the NFC pads J11 become a solder-joint body. Re-run after any PCB change. |
| `calcs.py` | Rotor inertia, spin-down (SKF model), detent LUT and ringing, balance, mass budget, springs / press pad / click force, TMAG aliasing, drop and pin pull-out, actuator force budget, per-part clearances read from the model (board parts vs rotor, hub, actuator and the harness, coax and battery leads), harness/coax/window/USB checks, NFC coil inductance and C16/C17 retune, coil and tail clearances (§13). Output: `calcs_output.txt`, `renders/calc_*.png` |
| `check_clashes.sh [margin]` (→ `clash_check.py`) | CGAL interference check: rotor envelope, press travel, rest, FA-internal pairs (NFC coil and tail included) → `clash_report.txt` (legend: `clash_legend.txt`); margin > 0 checks the rotor envelope only (near misses) |
| `export_stl.sh` | Printed and machined parts → `stl/*.stl` (binary, on the bed). For the five metal parts the mesh is only the assembly view: order them from `step/` + `drawings/` below. `magnet_shim_blank` is the one STL that *is* an order: it is the solid plate to print before its bores are machined |
| `parts_plate.scad` | Overview of the STLs → `renders/parts.png` |
| `scadvars.py` | Parses the constant table out of `dial_spinner.scad` so the B-rep models below are not a second source of truth for any dimension |
| `models.py` | The six machined parts (`rotor_ring`, `spindle`, `spindle_hub`, `lower_spacer`, `cap_ring`, `magnet_shim`) as **exact B-rep** solids (build123d / OpenCascade), plus each one's material, stock and shop notes. The shim is the one that is not metal: it is printed, but its 48 bores and its OD are machined, and a mesh cannot carry +0.01/−0.00 any better for plastic than for steel |
| `drawgen.py` | → `step/*.step` (exact geometry, what a CNC vendor's uploader actually accepts) and `drawings/*.pdf` (dimensioned ISO sheets carrying the fits, threads, knurl and general tolerance that no solid can hold). `--only NAME`, `--no-pdf` |
| `tests/test_models.py` | Holds the B-rep and the OpenSCAD mesh together: volume, bounding box, ring mass against `calcs.py` §14, and `calcs.py`'s own geometry constants against the `.scad`. Also guards the magnet-shim invariants — recess depth = magnet height, printable shim walls, and that the ring stays turning-only |
| `render_all.sh` | Regenerate everything (OpenSCAD 2021.01 + xvfb-run + numpy/matplotlib + build123d, ~7 min) |

OpenSCAD has no geometry kernel, so it can only emit a mesh — and JLCCNC's uploader rejects STL outright,
asks for STEP/DWG/DXF/PDF, and demands a drawing as soon as a part has a thread. Hence the second,
kernel-backed description of the six machined parts. It repeats only their *topology*; every number comes
from `dial_spinner.scad` through `scadvars.py`, and `tests/test_models.py` fails if the two drift:

```
~/.venvs/dial-me-spinner/bin/python -m pytest hardware/mechanical/tests -q    # 48 tests, ~7 s
```

The exact and meshed volumes agree to 0.011 % on the ring and 0.34 % on the spindle, in the direction
and magnitude tessellation predicts, and JLCCNC's own reader measured `rotor_ring.step` at 13 725.38 mm³
against build123d's 13 726.36 (0.007 %). STEP export is byte-deterministic apart from its timestamp line;
STL export is not, because CGAL emits triangles in an unstable order.

With the routed boards as placed (MDBT50Q at r 17.3 with its u.FL outward, J1 at r 19.5, side-entry SH SM04B J2 at
r 17, θ 222°, R42 at r 24.1) the clash check shows only the intended contacts listed in `clash_legend.txt`, and
`calcs_output.txt` §11 lists no part needing action. Re-run `extract_board_parts.py`, `check_clashes.sh` (margins 0
and 0.3, as in `render_all.sh`) and `calcs.py` after every placement change: the harness, coax and battery-lead paths
(`HARN_PTS`, `COAX_PTS`, `LEAD_PTS`) are hand-routed around the parts and must follow them. The coax passes 0.84 mm
from U12, 0.25 mm from U10 and 0.44 mm above the rotating cap ring, so it is tacked up with Kapton tape at assembly.

The NFC tag coil is modelled (`nfc_coil()`, `nfc_tail()`, `renders/nfc.png`; `docs/mechanical.md` §9). It is an annular
flex sheet, Ø31/Ø52.5 × 0.15 with its copper turns at r 24.9–26.15, bonded to the top cover's pocket ceiling (z 35.0,
r ≤ 26.35) and 0.1 mm above the OLED glass. Its tail is a 2.0 mm tongue cut from the sheet at θ 222°. It folds down at
r 24.1, 0.34 mm outside the glass edge, and runs under a relief in the OLED bracket rim (underside raised to z 32.3)
onto the J11 pads at r 21.5. J11 is a 0.35 mm solder-joint body in `board_parts`, and the clash check tests the coil
and the tail against the board, its top parts, the bracket, the glass, the light box and the cover. Coil and tail
dimensions are tagged `TVP` (to verify on prototype). All renders and STLs were regenerated on 2026-10-19 from this
model and the routed boards (the OLED bracket is now pocketed over D20).
