#!/usr/bin/env python3
"""STEP files and dimensioned drawings for the five machined parts.

    python3 drawgen.py                  # step/*.step + drawings/*.{svg,dxf,pdf}
    python3 drawgen.py --only spindle
    python3 drawgen.py --no-pdf

Why this exists: a CNC vendor cannot quote from a mesh.  JLCCNC's uploader takes
STEP, STP, DWG, DXF, PDF or an archive and rejects STL outright, and the moment a
part needs a thread it stops accepting geometry alone and demands a drawing --
which is the whole point, because a solid cannot carry a fit, a thread, a knurl,
a finish or a general tolerance.  So each part gets both: a STEP for the geometry
and a sheet for everything the geometry cannot say.

The solids come from models.py (exact B-rep over dial_spinner.scad's constants).
Section views are cut from the solid with `section()` and plan views are projected
through OpenCascade's hidden-line removal, so a view cannot drift from the part.
Only the *choice* of dimensions is authored here, part by part, because nothing
can usefully guess which dimensions a machinist needs.

Coordinates: each part is placed bottom-face-on-origin with its axis on the
origin, so a drawing's z is "from the bottom face" and a radius is a radius.
"""
import argparse
import os
import shutil
import subprocess
import sys

from build123d import (Align, PageSize, Plane, Pos, Rectangle, Rot, Sketch, Text, Unit,
                       export_step, scale, section)
from build123d.drafting import Draft, ExtensionLine, TechnicalDrawing
from build123d.exporters import Drawing, ExportDXF, ExportSVG

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models                                               # noqa: E402
from models import C                                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DIA = "⌀"

#: One Draft for every sheet.  display_units=False because the labels are built by
#: dim() below rather than formatted by the library -- see its docstring.
DRAFT = Draft(font_size=2.2, font="DejaVu Sans", arrow_length=1.5, line_width=0.3,
              decimal_precision=2, extension_gap=1.2, pad_around_text=1.0,
              display_units=False)
NOTE_SIZE = 2.0
NOTE_LEAD = 2.7
LABEL_SIZE = 2.6
#: A4 at nominal_text_size 3.0: TechnicalDrawing's frame is (297 - 2*5 - 2*3) = 281
#: wide and 2/3 of that tall, centred on the origin, with the title block filling
#: x 0..140.5, y -93.7..-46.8.  Every layout below works in that space.
SHEET_TEXT = 3.0


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def dim(value, tol=None, dia=False, fit=None, suffix=None):
    """One dimension label, formatted here rather than by build123d.

    The library cannot produce "Ø54.00 H7" or "Ø70.00 +0.00/-0.10" on its own:
    DimensionLine and ExtensionLine ignore `tolerance=` as soon as an explicit
    `label=` is passed, drop the diameter prefix when it is not, and render a
    negative tolerance with a doubled minus.  So build the whole string here.

    `tol` is (upper, lower), both signed, as a machinist reads them.
    """
    s = f"{DIA if dia else ''}{value:.2f}"
    if fit:
        s += f" {fit}"
    if tol is not None:
        s += f"  {tol[0]:+.2f}/{tol[1]:+.2f}"
    if suffix:
        s += f" {suffix}"
    return s


def _text(txt, x, y, size=NOTE_SIZE, align=(Align.MIN, Align.CENTER)):
    return Pos(x, y) * Text(txt, size, font="DejaVu Sans", align=align)


def _lines(lines, x, y, size=NOTE_SIZE, lead=NOTE_LEAD):
    s = Sketch()
    for i, line in enumerate(lines):
        if line:
            s += _text(line, x, y - i * lead, size)
    return s


#: ExtensionLine measures `offset` perpendicular to the border, and for a border
#: written left-to-right a POSITIVE offset puts the dimension line *below* it --
#: the opposite way round from a bottom-to-top border, where positive is to the
#: right.  These two names keep the per-part code readable instead of sprinkling
#: signs that have to be rediscovered every time.
def below(d):
    return d


def above(d):
    return -d


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def axial_section(solid):
    """Full axial section through the axis, rotated into the sheet plane.

    Cut from the solid, so it shows every chamfer, relief and notch the part has
    and nothing it has not.  After the rotation, sheet x is the part radius
    (signed, both halves) and sheet y is the part z.
    """
    return Rot(-90, 0, 0) * section(solid, Plane.XZ)


def plan(solid, from_below=False):
    """Projected view on the top (or bottom) face: visible edges only."""
    look = (0, 0, -1) if from_below else (0, 0, 1)
    return Drawing(solid, look_from=look, look_up=(0, 1, 0), with_hidden=False).visible_lines


def view(shape, centre, k=1.0, shift=0.0):
    """Place a view at `centre`, enlarged `k` times, after dropping `shift`.

    `shift` is the part coordinate that should land on the centre's y -- half the
    part height for a section, so the view sits centred on its own middle.
    """
    s = shape if k == 1.0 else scale(shape, k)
    return Pos(centre[0], centre[1] - k * shift) * s


def mapper(centre, k=1.0, shift=0.0):
    """The same transform as `view`, for placing dimensions in part coordinates.

    Returns f(a, b) -> (sheet x, sheet y), where (a, b) is (radius, height) for a
    section or (x, y) for a plan view.  Every dimension below is therefore
    written in the part's own numbers, and moving a view never means re-deriving
    one.
    """
    def f(a, b):
        return (centre[0] + k * a, centre[1] + k * (b - shift))
    return f


# ---------------------------------------------------------------------------
# Per-part sheets.  Each returns (filled_sketch, [stroked_shapes]): the frame,
# dimensions and text are traced ribbons that want filling, while the views are
# outlines that must not be filled, so they go onto separate export layers.
# ---------------------------------------------------------------------------
def _frame(part, k=1.0, extra_sub=""):
    """The border and title block.

    TechnicalDrawing can only render a scale as "1:x", so an enlarged sheet gets
    the reciprocal there and the conventional ratio in the subtitle and on every
    view label.  The notes say not to scale the drawing in any case.
    """
    ratio = "1:1" if k == 1.0 else f"{k:g}:1"
    return TechnicalDrawing(
        designed_by="dial-me-spinner / hardware-as-code",
        page_size=PageSize.A4, title=part.name.replace("_", " "),
        sub_title=f"{part.material}  rev A  {ratio}{extra_sub}",
        drawing_number=part.number, sheet_number=1, drawing_scale=round(1 / k, 3),
        nominal_text_size=SHEET_TEXT, line_width=0.3)


def _vlabel(txt, x, y, k=1.0):
    return _text(txt if k == 1.0 else f"{txt}  {k:g}:1", x, y, LABEL_SIZE,
                 (Align.CENTER, Align.CENTER))


def _common_notes(part, extra=()):
    """The block every sheet carries, built from the part's registry entry."""
    return ([f"MATERIAL: {part.material}.  STOCK: {part.stock}.  {part.process}.",
             "GENERAL TOLERANCE ISO 2768-m; UNMARKED EDGES DEBURRED.",
             "DIMENSIONS IN MM FROM THE BOTTOM FACE AND THE AXIS.",
             "DO NOT SCALE THE DRAWING; TAKE DIMENSIONS FROM THE FIGURES.",
             ""] + list(extra) + list(part.notes))


def sheet_rotor_ring(part, solid):
    K = 1.0
    sc, pc = (52, 46), (-78, 20)
    H = C.RING_Z1 - C.RING_Z0
    S, P = mapper(sc, K, H / 2), mapper(pc, K)

    faces = _frame(part, K)
    faces += ExtensionLine(border=[S(-C.RING_RO, 0), S(C.RING_RO, 0)], offset=below(16),
                           draft=DRAFT, label=dim(2 * C.RING_RO, dia=True, tol=(0.00, -0.10)))
    faces += ExtensionLine(border=[S(-C.RING_RI, H), S(C.RING_RI, H)], offset=above(16),
                           draft=DRAFT, label=dim(2 * C.RING_RI, dia=True, fit="H7"))
    faces += ExtensionLine(border=[S(C.RING_RO, 0), S(C.RING_RO, H)], offset=20, draft=DRAFT,
                           label=dim(H, tol=(0.05, -0.05)))
    faces += ExtensionLine(border=[S(-C.RT, H - C.POCKET_H), S(-C.RT, H)], offset=-20, draft=DRAFT,
                           label=dim(C.POCKET_H, tol=(0.05, 0.00), suffix="DEEP"))
    faces += _vlabel("SECTION A-A", sc[0], sc[1] + 26, K)

    faces += ExtensionLine(border=[P(-C.RT, 0), P(C.RT, 0)], offset=below(48), draft=DRAFT,
                           label=dim(2 * C.RT, dia=True, suffix=f"PCD, {int(C.MAG_N)} POCKETS"))
    faces += ExtensionLine(border=[P(-C.BAL_R, 0), P(C.BAL_R, 0)], offset=above(48), draft=DRAFT,
                           label=dim(2 * C.BAL_R, dia=True, suffix="PCD, 4 HOLES"))
    faces += _vlabel("VIEW ON THE TOP FACE  (A-A VERTICAL)", pc[0], pc[1] + 52, K)

    faces += _lines(_common_notes(part, [
        f"CHAMFERS: {C.CH_TO:.1f} x 45 TOP OUTER, {C.CH_BO:.1f} x 45 BOTTOM OUTER, "
        f"{C.CH_IN:.1f} x 45 BOTH INNER.",
        f"{int(C.MAG_N)}x {DIA}{C.POCKET_D:.2f} POCKETS EQUALLY SPACED "
        f"({360 / C.MAG_N:.1f} APART) ON THE {DIA}{2 * C.RT:.2f} PCD.",
        f"4x {DIA}{C.BAL_D:.2f} x {C.BAL_DEPTH:.1f} DEEP AT 45/135/225/315.",
        ""]), -138, -42)
    return faces, [view(plan(solid), pc, K), view(axial_section(solid), sc, K, H / 2)]


def sheet_spindle(part, solid):
    K, KD = 3.0, 6.0
    sc, pc, dc = (-95, 22), (35, 55), (72, 5)
    H = C.SPIGOT_Z1 - C.SP_Z0
    S, P = mapper(sc, K, H / 2), mapper(pc, K)
    z = {k: getattr(C, k) - C.SP_Z0 for k in ("SP_Z1", "SP_BORE_Z0", "SP_BORE_Z1", "B_Z0", "B_Z1")}

    faces = _frame(part, K)
    for r, off, label in ((C.SP_FL_D / 2, 13, dim(C.SP_FL_D, dia=True)),
                          (C.SP_OD / 2, 21, dim(C.SP_OD, dia=True, fit="h6")),
                          (C.SP_ID / 2, 29, dim(C.SP_ID, dia=True)),
                          (C.SPIGOT_D / 2, 37, "M4 x 0.5")):
        faces += ExtensionLine(border=[S(-r, 0), S(r, 0)], offset=below(off), draft=DRAFT,
                               label=label)
    for zz, off in ((H, 13), (z["SP_Z1"], 23), (z["B_Z1"], 33), (z["B_Z0"], 43)):
        faces += ExtensionLine(border=[S(C.SP_FL_D / 2, 0), S(C.SP_FL_D / 2, zz)], offset=off,
                               draft=DRAFT, label=dim(zz))
    faces += ExtensionLine(border=[S(-C.SP_FL_D / 2, z["SP_BORE_Z0"]),
                                   S(-C.SP_FL_D / 2, z["SP_BORE_Z1"])], offset=-13, draft=DRAFT,
                           label=dim(z["SP_BORE_Z1"] - z["SP_BORE_Z0"], suffix="BORE"))
    faces += _vlabel("SECTION A-A", sc[0], sc[1] + 36, K)

    flat_y = C.SP_OD / 2 - C.FLAT_DEPTH
    faces += ExtensionLine(border=[P(0, -C.SP_FL_D / 2), P(0, flat_y)], offset=26, draft=DRAFT,
                           label=dim(flat_y + C.SP_FL_D / 2, suffix="ACROSS THE FLAT"))
    faces += ExtensionLine(border=[P(-C.SP_FL_D / 2, 0), P(C.SP_FL_D / 2, 0)], offset=below(20),
                           draft=DRAFT, label=dim(C.SP_FL_D, dia=True, suffix="FLANGE"))
    faces += _vlabel("VIEW ON THE TOP FACE", pc[0], pc[1] + 22, K)

    # Detail of the bottom 2.5 mm: the pad pocket, relief and flange are all
    # sub-millimetre and still unreadable at 3:1.
    det_h, det_mid = 2.5, 1.25
    det = axial_section(solid) & (Pos(0, det_mid) * Rectangle(2 * C.SP_FL_D, det_h))
    D = mapper(dc, KD, det_mid)
    faces += ExtensionLine(border=[D(-C.SP_RELIEF_D / 2, 0), D(C.SP_RELIEF_D / 2, 0)],
                           offset=below(12), draft=DRAFT, label=dim(C.SP_RELIEF_D, dia=True))
    faces += ExtensionLine(border=[D(-C.PAD_POCKET_D / 2, 0), D(C.PAD_POCKET_D / 2, 0)],
                           offset=below(20), draft=DRAFT, label=dim(C.PAD_POCKET_D, dia=True))
    faces += ExtensionLine(border=[D(C.SP_FL_D / 2, 0), D(C.SP_FL_D / 2, C.SP_RELIEF_H)],
                           offset=8, draft=DRAFT, label=dim(C.SP_RELIEF_H))
    faces += ExtensionLine(border=[D(C.SP_FL_D / 2, C.SP_RELIEF_H),
                                   D(C.SP_FL_D / 2, C.SP_RELIEF_H + C.PAD_POCKET_H)],
                           offset=18, draft=DRAFT, label=dim(C.PAD_POCKET_H))
    faces += ExtensionLine(border=[D(-C.SP_FL_D / 2, 0), D(-C.SP_FL_D / 2, C.SP_FL_T)],
                           offset=-10, draft=DRAFT, label=dim(C.SP_FL_T))
    faces += _vlabel("DETAIL B  (RELIEF, PAD POCKET, FLANGE)", dc[0], dc[1] - 34, KD)

    faces += _lines(_common_notes(part, [
        f"SLOTS {C.SLOT_W:.1f} WIDE, BOTH BREAKING INTO THE BORE: "
        f"{z['SP_BORE_Z0']:.2f}-{C.BOT_SLOT_Z[1] - C.SP_Z0:.2f} AT {int(C.BOT_SLOT_A)} AND "
        f"{C.TOP_SLOT_Z[0] - C.SP_Z0:.2f}-{z['SP_BORE_Z1']:.2f} AT {int(C.TOP_SLOT_A)}.",
        f"BORE {DIA}{C.SP_ID:.2f} +0.05/-0.00; SPIGOT M4 x 0.5 ON {DIA}{C.SPIGOT_D:.2f}.",
        ""]), -138, -50)
    return faces, [view(plan(solid), pc, K), view(axial_section(solid), sc, K, H / 2),
                   view(det, dc, KD, det_mid)]


def sheet_spindle_hub(part, solid):
    K = 3.0
    sc, pc = (-80, 50), (40, 25)
    H = C.MB_Z0 - C.B_Z1
    S, P = mapper(sc, K, H / 2), mapper(pc, K)

    faces = _frame(part, K)
    faces += ExtensionLine(border=[S(-C.HUB_FL_RO, H), S(C.HUB_FL_RO, H)], offset=above(16),
                           draft=DRAFT, label=dim(2 * C.HUB_FL_RO, dia=True, suffix="FLANGE"))
    faces += ExtensionLine(border=[S(-C.LS_RO, 0), S(C.LS_RO, 0)], offset=below(14), draft=DRAFT,
                           label=dim(2 * C.LS_RO, dia=True, suffix="SPACER BOSS"))
    faces += ExtensionLine(border=[S(-C.SP_OD / 2, 0), S(C.SP_OD / 2, 0)], offset=below(24),
                           draft=DRAFT,
                           label=dim(C.SP_OD, dia=True, suffix="BORE"))
    faces += ExtensionLine(border=[S(C.HUB_FL_RO, 0), S(C.HUB_FL_RO, H)], offset=14, draft=DRAFT,
                           label=dim(H))
    faces += ExtensionLine(border=[S(-C.HUB_FL_RO, 0), S(-C.HUB_FL_RO, C.HUB_FL_Z0 - C.B_Z1)],
                           offset=-14, draft=DRAFT, label=dim(C.HUB_FL_Z0 - C.B_Z1))
    faces += _vlabel("SECTION A-A", sc[0], sc[1] + 34, K)

    faces += ExtensionLine(border=[P(-C.HUB_SCREW_R, 0), P(C.HUB_SCREW_R, 0)], offset=above(36),
                           draft=DRAFT,
                           label=dim(2 * C.HUB_SCREW_R, dia=True, suffix="PCD, 3x M2 x 0.4"))
    faces += ExtensionLine(border=[P(-C.SLOT_W / 2, -C.HUB_FL_RO), P(C.SLOT_W / 2, -C.HUB_FL_RO)],
                           offset=below(16), draft=DRAFT, label=dim(C.SLOT_W, suffix="C-GAP"))
    faces += _vlabel("VIEW ON THE FLANGE TOP FACE", pc[0], pc[1] + 44, K)

    faces += _lines(_common_notes(part, [
        "TAPPED HOLES AT " + "/".join(str(int(a)) for a in C.HUB_SCREW_A)
        + f", C-GAP AT {int(C.TOP_SLOT_A)}, {C.HUB_TAP_H:.1f} DEEP "
          f"({DIA}{C.HUB_TAP_D:.2f} TAP DRILL).",
        f"BORE {DIA}{C.SP_OD:.2f} +0.05/-0.00, SLIP FIT ON THE SPINDLE.",
        ""]), -138, -42)
    return faces, [view(plan(solid), pc, K), view(axial_section(solid), sc, K, H / 2)]


def sheet_lower_spacer(part, solid):
    K = 3.0
    sc, pc = (-75, 44), (45, 18)
    H = C.B_Z0 - C.FA_Z1
    fl0, fl1 = C.LS_FL_Z0 - C.FA_Z1, C.LS_FL_Z1 - C.FA_Z1
    S = mapper(sc, K, H / 2)

    faces = _frame(part, K)
    faces += ExtensionLine(border=[S(-C.LS_FL_RO, fl0), S(C.LS_FL_RO, fl0)], offset=below(20),
                           draft=DRAFT, label=dim(2 * C.LS_FL_RO, dia=True, suffix="FLANGE"))
    faces += ExtensionLine(border=[S(-C.LS_RO, H), S(C.LS_RO, H)], offset=above(14), draft=DRAFT,
                           label=dim(2 * C.LS_RO, dia=True))
    faces += ExtensionLine(border=[S(-C.SP_OD / 2, H), S(C.SP_OD / 2, H)], offset=above(24),
                           draft=DRAFT,
                           label=dim(C.SP_OD, dia=True, suffix="BORE"))
    faces += ExtensionLine(border=[S(C.LS_FL_RO, 0), S(C.LS_FL_RO, fl0)], offset=14, draft=DRAFT,
                           label=dim(fl0))
    faces += ExtensionLine(border=[S(C.LS_FL_RO, 0), S(C.LS_FL_RO, H)], offset=26, draft=DRAFT,
                           label=dim(H))
    faces += ExtensionLine(border=[S(-C.LS_FL_RO, fl0), S(-C.LS_FL_RO, fl1)], offset=-14,
                           draft=DRAFT, label=dim(fl1 - fl0))
    faces += _vlabel("SECTION A-A", sc[0], sc[1] + 38, K)
    faces += _vlabel("VIEW ON THE BOTTOM FACE", pc[0], pc[1] + 42, K)

    faces += _lines(_common_notes(part, [
        f"WINDOW {C.SLOT_W:.1f} WIDE THROUGH THE BOSS WALL AT {int(C.BOT_SLOT_A)}, "
        f"0.00-{C.BOT_SLOT_Z[1] - C.FA_Z1:.2f}.",
        f"BORE {DIA}{C.SP_OD:.2f} +0.05/-0.00, SLIP FIT ON THE SPINDLE.",
        ""]), -138, -42)
    # The window opens at the BOTTOM face, so a top view hides it behind the boss.
    return faces, [view(plan(solid, from_below=True), pc, K),
                   view(axial_section(solid), sc, K, H / 2)]


def sheet_cap_ring(part, solid):
    """No section: at 0.5 mm thick it would be a hairline.  Plan plus a thickness
    callout, which is how a sheet part is drawn anyway."""
    K = 2.0
    pc = (-60, 20)
    P = mapper(pc, K)
    t = C.CAP_Z[1] - C.CAP_Z[0]

    faces = _frame(part, K, extra_sub=f"  THK {t:.2f}")
    faces += ExtensionLine(border=[P(-C.COLLAR_RO, 0), P(C.COLLAR_RO, 0)], offset=below(32),
                           draft=DRAFT, label=dim(2 * C.COLLAR_RO, dia=True, tol=(0.00, -0.10)))
    faces += ExtensionLine(border=[P(-C.CAP_RI, 0), P(C.CAP_RI, 0)], offset=above(32), draft=DRAFT,
                           label=dim(2 * C.CAP_RI, dia=True, tol=(0.10, 0.00)))
    faces += _vlabel("VIEW ON THE FACE", pc[0], pc[1] + 44, K)
    faces += _lines(_common_notes(part, [
        f"MATERIAL THICKNESS {t:.2f}; FLAT WITHIN 0.05 OVER THE FULL FACE.", ""]), -138, -42)
    return faces, [view(plan(solid), pc, K)]


SHEETS = {"rotor_ring": sheet_rotor_ring, "spindle": sheet_spindle,
          "spindle_hub": sheet_spindle_hub, "lower_spacer": sheet_lower_spacer,
          "cap_ring": sheet_cap_ring}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_step(name, solid, out):
    path = os.path.join(out, "step", f"{name}.step")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    export_step(solid, path)
    return path


def write_drawing(name, faces, outlines, out, pdf=True):
    d = os.path.join(out, "drawings")
    os.makedirs(d, exist_ok=True)
    svg_path = os.path.join(d, f"{name}.svg")
    svg = ExportSVG(unit=Unit.MM, line_weight=0.25)
    svg.add_layer("sheet", fill_color=(0, 0, 0), line_color=(0, 0, 0))
    svg.add_layer("views", fill_color=None, line_color=(0, 0, 0), line_weight=0.4)
    svg.add_shape(faces, layer="sheet")
    svg.add_shape(outlines, layer="views")
    svg.write(svg_path)

    dxf_path = os.path.join(d, f"{name}.dxf")
    dxf = ExportDXF(unit=Unit.MM)
    dxf.add_layer("sheet")
    dxf.add_layer("views")
    dxf.add_shape(faces, layer="sheet")
    dxf.add_shape(outlines, layer="views")
    dxf.write(dxf_path)

    written = [svg_path, dxf_path]
    if pdf:
        rsvg = shutil.which("rsvg-convert")
        if rsvg:
            pdf_path = os.path.join(d, f"{name}.pdf")
            subprocess.run([rsvg, "-f", "pdf", "-o", pdf_path, svg_path], check=True)
            written.append(pdf_path)
        else:
            print("  note: rsvg-convert not found, so no PDF "
                  "(apt install librsvg2-bin); the DXF is the orderable file")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", metavar="PART",
                    help="one part name; repeatable (default: all five)")
    ap.add_argument("--out", default=HERE, help="output root (default: this directory)")
    ap.add_argument("--no-step", action="store_true")
    ap.add_argument("--no-drawings", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)

    names = args.only or list(models.PARTS)
    bad = [n for n in names if n not in models.PARTS]
    if bad:
        ap.error(f"unknown part(s) {bad}; known: {list(models.PARTS)}")

    for name in names:
        part = models.PARTS[name]
        solid = models.on_bed(part.build())
        bb = solid.bounding_box()
        print(f"{name}: {solid.volume / 1000:.4f} cm3, {solid.volume * part.density:.3f} g, "
              f"{bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} mm")
        if not args.no_step:
            print(f"  {os.path.relpath(write_step(name, solid, args.out), args.out)}")
        if not args.no_drawings:
            faces, outlines = SHEETS[name](part, solid)
            for p in write_drawing(name, faces, outlines, args.out, pdf=not args.no_pdf):
                print(f"  {os.path.relpath(p, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
