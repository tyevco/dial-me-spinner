#!/usr/bin/env python3
"""Generate the dial-me-spinner PCBs (main + base) from the KiCad netlists.

usage: python3 hardware/design/layout.py [--board main|base] [--route] [--passes N]

The script places mechanically constrained parts explicitly (SPEC §8): LED ring,
Hall sensors, module, connectors, switch. It then greedily clusters every other
part around the IC it connects to, draws the outlines, holes, keep-outs and
zones, and optionally autoroutes with Freerouting (Specctra DSN/SES).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HW, "tools"))

import pcbnew  # noqa: E402

import pcbgen  # noqa: E402
from placer import Placer  # noqa: E402

CX, CY = 100.0, 100.0          # board centre in KiCad page coordinates (mm)
KICAD_DIR = os.path.join(HW, "kicad")
FREEROUTING = os.environ.get("FREEROUTING_JAR", "")
LIB = "dial_spinner"


def pol(r, deg):
    """Polar (θ CCW seen from the top, θ = 0 toward +x / USB-C) -> page coords."""
    a = math.radians(deg)
    return CX + r * math.cos(a), CY - r * math.sin(a)


def radius(x, y):
    return math.hypot(x - CX, y - CY)


def angle(x, y):
    return math.degrees(math.atan2(CY - y, x - CX)) % 360


def refnum(ref):
    m = re.match(r"[A-Za-z]+(\d+)", ref)
    return int(m.group(1)) if m else 0


def find(comps, pred):
    return sorted([r for r, c in comps.items() if pred(c)], key=lambda r: (re.sub(r"\d", "", r), refnum(r)))


def mpn(c):
    return (c["fields"].get("MPN") or c["value"] or "").upper()


def fp_name(c):
    return c["footprint"].split(":")[-1]


# --------------------------------------------------------------------------- main board
MAIN_R = 32.0


def main_fixed(comps):
    """Explicit placements for the main board: ref -> (x, y, rot, side)."""
    P = {}
    leds = find(comps, lambda c: "WS2812" in mpn(c))
    n = len(leds)
    for i, ref in enumerate(leds):
        th = i * 360.0 / n
        x, y = pol(28.5, th)
        P[ref] = (x, y, th + 90.0, "F")
    # per-LED decoupling caps: 100 nF whose nets are exactly {VLED, GND} and that sit next to an LED in the schematic
    led_caps = [r for r in find(comps, lambda c: c["value"].lower().startswith("100n") and "C" in c["ref"][:1])
                if 101 <= refnum(r) <= 199]
    for i, ref in enumerate(sorted(led_caps, key=refnum)[:n]):
        th = i * 360.0 / n
        x, y = pol(25.9, th)
        P[ref] = (x, y, th + 90.0, "F")

    def put(pred, r, th, rot, side):
        for ref in find(comps, pred):
            if ref not in P:
                x, y = pol(r, th)
                P[ref] = (x, y, rot, side)
                return ref

    put(lambda c: "TMAG5273" in mpn(c), 29.0, 270.0, 0.0, "B")          # long axis radial (SOT-23 pins along x)
    put(lambda c: "DRV5032" in mpn(c), 21.5, 90.0, 0.0, "F")
    put(lambda c: "MDBT50Q" in mpn(c), 14.5, 215.0, 215.0 + 90.0, "B")   # u.FL end toward the centre
    put(lambda c: "BM12B" in mpn(c) or c["value"] == "LINK", 8.5, 330.0, 90.0, "B")
    put(lambda c: "AFC01" in mpn(c) or "FH12" in mpn(c) or "0.5K-HX" in mpn(c) or "ZIF" in c["value"].upper(),
        9.5, 270.0, 0.0, "F")
    put(lambda c: "TC2030" in fp_name(c).upper() or "TAG-CONNECT" in fp_name(c).upper(), 12.0, 150.0, 0.0, "F")
    put(lambda c: "PKMCS" in mpn(c), 20.0, 0.0, 0.0, "B")
    put(lambda c: "SM04B" in mpn(c) or "BM04B" in mpn(c), 24.0, 140.0, 90.0, "B")
    return P


def main_anchor_sides(comps):
    """Anchors for greedy clustering and their side (parts placed near their anchor)."""
    sides = {}
    for ref, c in comps.items():
        m = mpn(c)
        if any(k in m for k in ("W25Q", "SC-20S", "32.768")):
            sides[ref] = ("B", (16.0, 165.0))
        elif any(k in m for k in ("RT9080", "TPS22917", "TPS22918")):
            sides[ref] = ("F", (16.0, 30.0))
        elif any(k in m for k in ("TPS61040", "AO3401", "2N7002", "SWPA3015", "B5819")):
            sides[ref] = ("F", (14.0, 300.0))
        elif "LIS2DW12" in m:
            sides[ref] = ("F", (12.0, 200.0))
        elif "DRV8837" in m:
            sides[ref] = ("B", (22.0, 155.0) if not sides.get("_drv") else (22.0, 35.0))
            sides["_drv"] = True
    sides.pop("_drv", None)
    return sides


def main_inside(x, y, side):
    r = radius(x, y)
    if r > MAIN_R - 0.5:
        return False
    if r < 3.2:  # centre hole
        return False
    if side == "B" and r < 8.5:  # spindle flange
        return False
    return True


def main_keepouts():
    def actuator(x, y):
        r, th = radius(x, y), angle(x, y)
        return 12.0 <= r <= 32.5 and 60.0 <= th <= 120.0

    def spindle_screws(x, y):
        return any(math.hypot(x - hx, y - hy) < 2.6 for hx, hy in (pol(6.5, a) for a in (90, 210, 330)))

    def tmag_zone(x, y):  # nothing else within 4 mm of the encoder sensor on the bottom
        hx, hy = pol(29.0, 270.0)
        return math.hypot(x - hx, y - hy) < 4.0

    return [("B", actuator), ("*", spindle_screws), ("B", tmag_zone)]


def build_main(bb, comps, nets):
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    bb.circle(pcbnew.Edge_Cuts, CX, CY, MAIN_R, 0.1)
    bb.circle(pcbnew.Edge_Cuts, CX, CY, 2.5, 0.1)  # Ø5 harness hole
    for i, th in enumerate((90, 210, 330)):
        x, y = pol(6.5, th)
        bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", f"H{i + 1}")
    for i, th in enumerate((60, 120)):
        x, y = pol(17.0, th)
        bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", f"H{i + 4}")
    # GND plane on In1 (layer set to "power" so Freerouting treats it as a plane)
    outer = bb.circle_pts(CX, CY, MAIN_R - 0.3, 96)
    bb.zone("GND", [pcbnew.In1_Cu], outer, priority=0, name="GND_PLANE")
    # no pours facing the magnet track (eddy drag): B.Cu / In2.Cu, r >= 26
    ring_out = bb.circle_pts(CX, CY, MAIN_R + 1, 96)
    ring_in = bb.circle_pts(CX, CY, 26.0, 96)
    z = bb.keepout([pcbnew.B_Cu, pcbnew.In2_Cu], ring_out, tracks=False, vias=False, pads=False, pours=True,
                   name="NO_POUR_OVER_TRACK")
    ol = z.Outline()
    ol.NewHole()
    for x, y in reversed(ring_in):
        ol.Append(pcbgen.MM(x), pcbgen.MM(y), -1, 0)
    # actuator / carriage corridor (bottom): documented on B.Fab, enforced by the placer
    sector = [pol(12.0, a) for a in range(60, 121, 5)] + [pol(31.5, a) for a in range(120, 59, -5)]
    bb.polyline(pcbnew.B_Fab, sector, 0.15, closed=True)
    x, y = pol(24.0, 90)
    bb.text(pcbnew.B_Fab, "ACTUATOR / CARRIAGE CORRIDOR", x, y, 0.8, mirror=True)
    # GND pours on F.Cu (all) and B.Cu (r < 26) — filled after routing
    bb.zone("GND", [pcbnew.F_Cu], outer, priority=0, clearance=0.25, name="GND_TOP")
    bb.zone("GND", [pcbnew.B_Cu], bb.circle_pts(CX, CY, 25.7, 96), priority=0, clearance=0.25, name="GND_BOT")
    # silkscreen
    bb.text(pcbnew.F_SilkS, "dial-me-spinner main rA", CX, CY + 23.0, 1.0)
    x, y = pol(30.6, 90)
    bb.text(pcbnew.B_SilkS, "DETENT", x, y, 0.8, mirror=True)
    for th, label in ((0, "θ0 USB"), (270, "ENC")):
        x, y = pol(31.0, th)
        bb.text(pcbnew.F_Fab, label, x, y, 0.8)


# --------------------------------------------------------------------------- base board
BASE_R = 20.0


def base_outline(bb):
    """Ø40 disc plus a 13 mm wide tab toward θ = 0° reaching r = 35 (USB-C)."""
    half = 6.5
    a = math.degrees(math.asin(half / BASE_R))
    pts = []
    for k in range(0, 101):
        th = a + (360 - 2 * a) * k / 100
        pts.append(pol(BASE_R, th))
    pts += [(CX + 34.6, CY + half), (CX + 34.6, CY - half)]
    # pts runs CCW from +a to -a; close via the tab
    bb.polyline(pcbnew.Edge_Cuts, [pts[-1], pts[-2]] + pts[:-2], 0.1, closed=True)
    return pts


def base_inside(x, y, side):
    if radius(x, y) <= BASE_R - 0.5:
        return True
    return CX + 15 <= x <= CX + 34.1 and abs(y - CY) <= 6.0


def base_fixed(comps):
    P = {}

    def put(pred, x, y, rot, side):
        for ref in find(comps, pred):
            if ref not in P:
                P[ref] = (x, y, rot, side)
                return ref

    put(lambda c: "TYPE-C" in mpn(c), CX + 31.0, CY, 90.0, "F")
    put(lambda c: "TS-1187" in mpn(c) or c["value"].upper().startswith("SW_PRESS"), CX, CY, 0.0, "F")
    put(lambda c: "BM12B" in mpn(c) or c["value"] == "LINK", *pol(9.0, 90.0), 0.0, "F")
    put(lambda c: "PH-SM4" in mpn(c) or "S2B-PH" in mpn(c), *pol(13.0, 0.0), 270.0, "B")
    return P


def base_anchor_sides(comps):
    sides = {}
    for ref, c in comps.items():
        m = mpn(c)
        if "BQ25180" in m:
            sides[ref] = ("F", (11.0, 220.0))
        elif "USBLC6" in m or "SMF5" in m:
            sides[ref] = ("F", (19.0, 0.0))
        elif "BSS138" in m:
            sides[ref] = ("F", (8.0, 300.0))
        elif "NCP15" in m or "NTC" in c["value"].upper():
            sides[ref] = ("B", (6.0, 180.0))
    return sides


def base_keepouts():
    def bosses(x, y):
        return any(math.hypot(x - hx, y - hy) < 2.8 for hx, hy in (pol(15.0, a) for a in (60, 180, 300)))
    return [("*", bosses)]


def build_base(bb, comps, nets):
    base_outline(bb)
    for i, th in enumerate((60, 180, 300)):
        x, y = pol(15.0, th)
        bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", f"H{i + 1}")
    pts = [(CX + 34.4, CY - 6.3), (CX + 34.4, CY + 6.3)] + bb.circle_pts(CX, CY, BASE_R - 0.3, 96, 20, 340)
    bb.zone("GND", [pcbnew.B_Cu], pts, priority=0, clearance=0.25, name="GND_BOT")
    bb.zone("GND", [pcbnew.F_Cu], pts, priority=0, clearance=0.25, name="GND_TOP")
    bb.text(pcbnew.F_SilkS, "dial-me-spinner base rA", CX - 2.0, CY + 15.5, 0.8)


# --------------------------------------------------------------------------- common flow
BOARDS = {
    "main": dict(layers=4, fixed=main_fixed, anchors=main_anchor_sides, inside=main_inside,
                 keepouts=main_keepouts, build=build_main),
    "base": dict(layers=2, fixed=base_fixed, anchors=base_anchor_sides, inside=base_inside,
                 keepouts=base_keepouts, build=build_base),
}


def project_dir(board):
    return os.path.join(KICAD_DIR, board)


def project_name(board):
    return f"dial-me-spinner-{board}"


def generate(board):
    cfg = BOARDS[board]
    pdir = project_dir(board)
    netpath = os.path.join(pdir, project_name(board) + ".net")
    comps, nets = pcbgen.load_netlist(netpath)
    bb = pcbgen.BoardBuilder(cfg["layers"], {LIB: os.path.join(pdir, "lib", LIB + ".pretty")})
    bb.rules(track=0.15, clearance=0.15, via=0.45, via_drill=0.25, edge=0.3)
    bb.set_origin(CX, CY)
    power = [n for n in nets if n in ("VSYS", "VLED", "VBUS", "VBAT", "+3V3", "GND", "+13V_OLED", "OLED_VIN")
             or n.endswith("/VSYS")]
    bb.netclass("Power", [n for n in power if n != "GND"], track=0.4, clearance=0.15, via=0.6, via_drill=0.3)
    bb.netclass("Ground", ["GND"], track=0.4, clearance=0.15, via=0.6, via_drill=0.3)
    fixed = cfg["fixed"](comps)
    bb.place_from_netlist(comps, nets, fixed, default=(CX, CY, 0.0, "F"))
    cfg["build"](bb, comps, nets)

    placer = Placer(bb.board, cfg["inside"], cfg["keepouts"](), power_nets=("GND",))
    for ref in fixed:
        placer.mark(bb.footprints[ref])
    # anchors: explicit side/region parts first, placed near their region centre
    anchor_cfg = cfg["anchors"](comps)
    anchors = [bb.footprints[r] for r in fixed if r in bb.footprints]
    for ref, (side, (r, th)) in sorted(anchor_cfg.items(), key=lambda kv: refnum(kv[0])):
        if ref in fixed or ref not in bb.footprints:
            continue
        x, y = pol(r, th)
        if not placer.place_near(bb.footprints[ref], x, y, side, max_r=20):
            print("WARN: could not place anchor", ref)
        anchors.append(bb.footprints[ref])
    # everything else clusters around the anchor it shares the most nets with
    rest = [fp for ref, fp in bb.footprints.items() if ref not in fixed and ref not in anchor_cfg]
    rest.sort(key=lambda fp: (-fp.GetPadCount(), refnum(fp.GetReference())))
    unplaced = []
    for fp in rest:
        a = placer.anchor_for(fp, anchors) or anchors[0]
        tx, ty = placer.target(fp, a)
        side = Placer.side(a)
        if not placer.place_near(fp, tx, ty, side, max_r=18) and \
                not placer.place_near(fp, tx, ty, "F" if side == "B" else "B", max_r=25):
            unplaced.append(fp.GetReference())
        if fp.GetPadCount() > 2:
            anchors.append(fp)
    if unplaced:
        print("WARN: unplaced:", ", ".join(unplaced))
    out = os.path.join(pdir, project_name(board) + ".kicad_pcb")
    bb.save(out)
    set_layer_types(out, cfg["layers"])
    return out


def set_layer_types(path, layers):
    """Mark In1.Cu as a power plane so Freerouting keeps signals off it."""
    if layers != 4:
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r'\(1 "In1\.Cu" signal\)', '(1 "In1.Cu" power)', s)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


def drc(path):
    rpt = path.replace(".kicad_pcb", "-drc.rpt")
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-error", "-o", rpt, path], capture_output=True)
    counts = {}
    with open(rpt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("["):
                k = line.split("]")[0] + "]"
                counts[k] = counts.get(k, 0) + 1
    return rpt, counts


def route(path, passes=12, timeout=3600):
    jar = FREEROUTING or os.path.join(os.environ.get("SCRATCH", "/tmp"), "freerouting.jar")
    if not os.path.exists(jar):
        raise SystemExit(f"Freerouting jar not found ({jar}); set FREEROUTING_JAR")
    dsn = path.replace(".kicad_pcb", ".dsn")
    ses = path.replace(".kicad_pcb", ".ses")
    pcbgen.export_dsn(path, dsn)
    subprocess.run(["java", "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(passes), "--gui.enabled=false"],
                   timeout=timeout, capture_output=True)
    if not os.path.exists(ses):
        raise RuntimeError("Freerouting produced no session file")
    pcbgen.import_ses(path, ses, path)
    for f in (dsn, ses):
        os.remove(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS))
    ap.add_argument("--route", action="store_true")
    ap.add_argument("--passes", type=int, default=12)
    a = ap.parse_args()
    for board in BOARDS:
        if a.board and board != a.board:
            continue
        out = generate(board)
        print(f"[{board}] placed ->", out)
        if a.route:
            route(out, a.passes)
            print(f"[{board}] routed")
        rpt, counts = drc(out)
        print(f"[{board}] DRC errors:", counts or "none", "->", rpt)


if __name__ == "__main__":
    main()
