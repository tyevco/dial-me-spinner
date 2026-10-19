#!/usr/bin/env python3
"""Extract component envelopes from the KiCad boards into the mechanical model.

    python3 extract_board_parts.py        # needs KiCad 9 pcbnew (python3-kicad)

Reads hardware/kicad/{main,base}/*.kicad_pcb and writes
  board_parts.scad   OpenSCAD arrays used by dial_spinner.scad
  board_parts.json   the same data for calcs.py (clearance tables)

Each part becomes an oriented box: its F.Fab/B.Fab outline (courtyard - 0.25 mm if the
footprint has no Fab outline) extruded by a height from HEIGHTS below.  Heights are
datasheet maxima where known; the ones tagged "verify" are assumptions (to verify on
prototype).  Side-entry JST connectors also get a mated-plug box on their mouth side, and
the MDBT50Q gets its mated u.FL plug.  Model frame: x = KiCad x - 100, y = 100 - KiCad y
(board centre at KiCad (100, 100)), z from the desk.
"""
import json
import math
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.join(HERE, "..", "kicad")
BOARDS = {
    "main": (os.path.join(KICAD, "main", "dial-me-spinner-main.kicad_pcb"), 29.1, 30.7),
    "base": (os.path.join(KICAD, "base", "dial-me-spinner-base.kicad_pcb"), 9.5, 11.1),
}
CX, CY = 100.0, 100.0

# (footprint-name regex, height mm, note).  First match wins.
HEIGHTS = [
    (r"MountingHole|TestPoint|Tag-Connect|Fiducial|NFC_Coil_Pads", None, "no body"),
    (r"WS2812", 0.90, "SPEC 30.7-31.6"),
    (r"C_0402", 0.55, "0402 MLCC max"),
    (r"R_0402", 0.40, ""),
    (r"C_0603", 0.90, "10 uF 0603 max"),
    (r"R_0603", 0.50, ""),
    (r"C_0805", 1.45, "22 uF 0805 max"),
    (r"R_1206", 0.65, ""),
    (r"SOT-23-5|SOT-23-6", 1.45, "DBV max"),
    (r"SOT-23", 1.15, "DBZ max"),
    (r"SOT-363|SC-70", 1.10, ""),
    (r"WSON-8|DSG0008", 0.80, ""),
    (r"USON", 0.60, ""),
    (r"LGA-12", 0.80, ""),
    (r"SOIC-8", 2.16, "208 mil SOIC max"),
    (r"SC-20S", 0.60, ""),
    (r"JST_SH", 2.95, "JST SH side entry"),
    (r"S2B-PH-SM4", 5.50, "JST PH SMT side entry, verify (distributor data)"),
    (r"MDBT50Q", 2.20, "Raytac, verify"),
    (r"PKMCS0909", 1.90, "Murata"),
    (r"SWPA3015", 1.50, ""),
    (r"AFC01", 2.00, "ZIF, verify"),
    (r"SOD-123", 1.35, ""),
    (r"CP_EIA-\d+-(\d\d)", "eia", "tantalum, height from the EIA code"),
    (r"D_SMF", 1.10, ""),
    (r"TYPE-C-31-M-12", 3.26, "HRO"),
    (r"TS-1187A", 1.50, "XKB, actuator top"),
    (r"DSBGA", 0.50, ""),
]
PLUG_EXT = {"JST_SH": 3.0, "S2B-PH": 4.5}      # mated housing beyond the header body (verify)


def height_for(fpname):
    for rx, h, note in HEIGHTS:
        m = re.search(rx, fpname)
        if m:
            if h == "eia":
                return int(m.group(1)) / 10.0, note
            return h, note
    return 1.0, "UNKNOWN height, default 1.0"


def w(p):
    return (pcbnew.ToMM(p.x) - CX, CY - pcbnew.ToMM(p.y))


def shape_points(it):
    pts = []
    try:
        st = it.GetShape()
    except Exception:
        return pts
    if st == pcbnew.SHAPE_T_POLY:
        poly = it.GetPolyShape()
        for o in range(poly.OutlineCount()):
            ol = poly.Outline(o)
            for i in range(ol.PointCount()):
                pts.append(w(ol.CPoint(i)))
    elif st == pcbnew.SHAPE_T_CIRCLE:
        c = w(it.GetCenter())
        r = pcbnew.ToMM(it.GetRadius())
        pts += [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in [k * math.pi / 8 for k in range(16)]]
    else:
        pts += [w(it.GetStart()), w(it.GetEnd())]
        if st == pcbnew.SHAPE_T_RECT:
            s, e = w(it.GetStart()), w(it.GetEnd())
            pts += [(s[0], e[1]), (e[0], s[1])]
    return pts


def extract(board_key):
    path, z_bot, z_top = BOARDS[board_key]
    b = pcbnew.LoadBoard(path)
    parts = []
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        fpname = str(fp.GetFPID().GetLibItemName())
        h, note = height_for(fpname)
        if h is None:
            continue
        side = "B" if fp.IsFlipped() else "T"
        phi = fp.GetOrientationDegrees()
        pos = w(fp.GetPosition())
        fab, crt = [], []
        for it in fp.GraphicalItems():
            if it.GetClass() in ("PCB_TEXT", "FP_TEXT", "PCB_FIELD"):
                continue
            ln = it.GetLayerName()
            if ln.endswith("Fab"):
                fab += shape_points(it)
            elif ln.endswith("CrtYd"):
                crt += shape_points(it)
        pts, shrink = (fab, 0.0) if len(fab) >= 3 else (crt, 0.25)
        if len(pts) < 3:
            continue
        a = math.radians(phi)
        u = (math.cos(a), math.sin(a))
        v = (-math.sin(a), math.cos(a))
        lu = [(p[0] - pos[0]) * u[0] + (p[1] - pos[1]) * u[1] for p in pts]
        lv = [(p[0] - pos[0]) * v[0] + (p[1] - pos[1]) * v[1] for p in pts]
        box = [min(lu) + shrink, max(lu) - shrink, min(lv) + shrink, max(lv) - shrink]
        z0 = z_top if side == "T" else z_bot - h
        val = fp.GetValue()
        parts.append(dict(ref=ref, value=val, fp=fpname, side=side, x=round(pos[0], 3), y=round(pos[1], 3),
                          phi=round(phi, 2), box=[round(q, 3) for q in box], z0=round(z0, 3), h=h, note=note))
        # mated plug of side-entry JST headers: extend toward the mouth (signal row -> MP pads direction)
        for key, ext in PLUG_EXT.items():
            if key in fpname:
                sig = [w(p.GetPosition()) for p in fp.Pads() if p.GetNumber().isdigit()]
                mp = [w(p.GetPosition()) for p in fp.Pads() if not p.GetNumber().isdigit()]
                if not sig or not mp:
                    continue
                cs = (sum(p[0] for p in sig) / len(sig), sum(p[1] for p in sig) / len(sig))
                cm = (sum(p[0] for p in mp) / len(mp), sum(p[1] for p in mp) / len(mp))
                d = (cm[0] - cs[0], cm[1] - cs[1])
                dl = math.hypot(*d)
                d = (d[0] / dl, d[1] / dl)
                du, dv = d[0] * u[0] + d[1] * u[1], d[0] * v[0] + d[1] * v[1]
                pb = list(box)
                if abs(dv) >= abs(du):          # mouth along local v
                    if dv > 0:
                        pb[2], pb[3] = box[3], box[3] + ext
                    else:
                        pb[2], pb[3] = box[2] - ext, box[2]
                else:
                    if du > 0:
                        pb[0], pb[1] = box[1], box[1] + ext
                    else:
                        pb[0], pb[1] = box[0] - ext, box[0]
                parts.append(dict(ref=ref + "_plug", value="mated plug", fp=fpname, side=side, x=pos[0], y=pos[1],
                                  phi=round(phi, 2), box=[round(q, 3) for q in pb], z0=round(z0, 3), h=h,
                                  note=f"mated housing, {ext} mm beyond the header (verify)",
                                  mouth=[round(d[0], 3), round(d[1], 3)]))
        if "MDBT50Q" in fpname:
            # u.FL receptacle at footprint-local (0, -6) (layout.py convention, verify on the Raytac
            # drawing), on the module PCB face 0.8 mm below the board; mated U.FL plug 2.5 mm tall.
            lib = os.path.join(KICAD, "main", "lib", "dial_spinner.pretty")
            ref_fp = pcbnew.FootprintLoad(lib, fpname)
            loc = {p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                   for p in ref_fp.Pads()}
            src, dst = [], []
            for p in fp.Pads():
                if p.GetNumber() in loc:
                    src.append(loc[p.GetNumber()])
                    dst.append(w(p.GetPosition()))
            import numpy as np
            A = np.c_[np.array(src), np.ones(len(src))]
            sol, *_ = np.linalg.lstsq(A, np.array(dst), rcond=None)
            ux, uy = (np.array([0.0, -6.0, 1.0]) @ sol).tolist()
            parts.append(dict(ref="U10_uFL", value="mated U.FL plug", fp="u.FL", side="B", x=round(ux, 3),
                              y=round(uy, 3), phi=0.0, box=[-1.3, 1.3, -1.3, 1.3], z0=round(z_bot - 0.8 - 2.5, 3),
                              h=2.5, note="plug bottom = board - 0.8 (module PCB) - 2.5 (mated height); verify"))
    holes = []
    for fp in b.GetFootprints():
        if "MountingHole" in str(fp.GetFPID().GetLibItemName()):
            holes.append([round(v, 3) for v in w(fp.GetPosition())])
    return parts, holes


def scad_list(parts):
    rows = []
    for p in parts:
        bx = p["box"]
        rows.append(f'  ["{p["ref"]}", "{p["side"]}", {p["x"]:.3f}, {p["y"]:.3f}, {p["phi"]:.2f}, '
                    f'{bx[0]:.3f}, {bx[1]:.3f}, {bx[2]:.3f}, {bx[3]:.3f}, {p["z0"]:.3f}, {p["h"]:.2f}]')
    return "[\n" + ",\n".join(rows) + "\n]"


def main():
    out = {}
    lines = ["// GENERATED by extract_board_parts.py from hardware/kicad/*/*.kicad_pcb -- do not edit.",
             "// [ref, side, x, y, phi_deg, u0, u1, v0, v1, z0, h]  (oriented box in the footprint frame)"]
    for key in BOARDS:
        parts, holes = extract(key)
        out[key] = dict(parts=parts, holes=holes)
        lines.append(f"{key.upper()}_PARTS = {scad_list(parts)};")
        lines.append(f"{key.upper()}_HOLES = {json.dumps(holes)};")
        unk = [p["ref"] for p in parts if "UNKNOWN" in p["note"]]
        print(f"{key}: {len(parts)} envelopes, {len(holes)} holes; unknown heights: {unk}")
    with open(os.path.join(HERE, "board_parts.scad"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(HERE, "board_parts.json"), "w") as f:
        json.dump(out, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
