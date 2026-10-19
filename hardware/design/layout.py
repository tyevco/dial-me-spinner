#!/usr/bin/env python3
"""Generate the dial-me-spinner PCBs (main + base) from the KiCad netlists.

usage: python3 hardware/design/layout.py [--board main|base] [--route] [--minutes N]

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
import silk  # noqa: E402
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


_LIB_FP_CACHE = {}


def _lib_fp(fp):
    """Library copy of a footprint, loaded once (FootprintLoad parses the whole .pretty and leaks ~30 MB a call)."""
    key = fp.GetFPIDAsString()
    if key not in _LIB_FP_CACHE:
        path = fp_lib_path(fp)
        _LIB_FP_CACHE[key] = pcbnew.FootprintLoad(*path) if path else None
    return _LIB_FP_CACHE[key]


def local_map(fp):
    """Affine map (footprint-local mm -> board mm) solved from the pads, so flips/rotations are exact."""
    import numpy as np
    ref = _lib_fp(fp)
    if ref is None:
        return None
    lib_pads, brd_pads = list(ref.Pads()), list(fp.Pads())
    xy = lambda p: (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))  # noqa: E731
    if len(lib_pads) == len(brd_pads) and all(a.GetNumber() == b.GetNumber() for a, b in zip(lib_pads, brd_pads)):
        # same library footprint: pair pads by position in the list, so repeated numbers (MP, GND, "") pair correctly
        src, dst = [xy(a) for a in lib_pads], [xy(b) for b in brd_pads]
    else:  # otherwise only pad numbers that are unique on both sides
        nums = [p.GetNumber() for p in lib_pads]
        loc = {p.GetNumber(): xy(p) for p in lib_pads if p.GetNumber() and nums.count(p.GetNumber()) == 1}
        bnums = [p.GetNumber() for p in brd_pads]
        pairs = [(loc[p.GetNumber()], xy(p)) for p in brd_pads if p.GetNumber() in loc and bnums.count(p.GetNumber()) == 1]
        src, dst = [a for a, _ in pairs], [b for _, b in pairs]
    A = np.c_[np.array(src), np.ones(len(src))]
    sol, *_ = np.linalg.lstsq(A, np.array(dst), rcond=None)
    return lambda x, y: tuple(float(v) for v in np.array([x, y, 1.0]) @ sol)


_FP_LIBS = {}


def fp_lib_path(fp):
    nick, name = fp.GetFPIDAsString().split(":", 1) if ":" in fp.GetFPIDAsString() else (None, None)
    if nick is None:
        return None
    path = _FP_LIBS.get(nick, os.path.join(pcbgen.FP_DIR, nick + ".pretty"))
    return path, name


def place_local_point(fp, lx, ly, tx, ty):
    """Shift fp so its local point (lx, ly) lands on board point (tx, ty)."""
    m = local_map(fp)
    if m is None:
        return
    bx, by = m(lx, ly)
    pos = fp.GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(pos.x + pcbgen.MM(tx - bx), pos.y + pcbgen.MM(ty - by)))


def orient_local_toward(fp, lx, ly, tx, ty):
    """Rotate fp (about its origin) so its local point (lx, ly) is as close as possible to (tx, ty)."""
    best = None
    for rot in range(0, 360, 5):
        fp.SetOrientationDegrees(rot)
        m = local_map(fp)
        bx, by = m(lx, ly)
        dist = math.hypot(bx - tx, by - ty)
        if best is None or dist < best[0]:
            best = (dist, rot)
    fp.SetOrientationDegrees(best[1])
    return best[1]


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

    for i, th in enumerate((90, 210, 330)):                              # plated GND spindle holes
        ref = f"H{i + 1}"
        if ref in comps:
            x, y = pol(6.5, th)
            P[ref] = (x, y, 0.0, "F")
    put(lambda c: "TMAG5273" in mpn(c), 29.0, 270.0, 0.0, "B")          # long axis radial (SOT-23 pins along x)
    put(lambda c: "DRV5032" in mpn(c), 21.5, 90.0, 0.0, "F")
    put(lambda c: "MDBT50Q" in mpn(c), *MODULE_POS, 0.0, "B")   # oriented in main_post_fixed (u.FL end outward)
    put(lambda c: "SM12B" in mpn(c) or "BM12B" in mpn(c) or c["value"] == "LINK", J1_MAIN_R, 330.0, 0.0, "B")
    put(lambda c: "AFC01" in mpn(c) or "FH12" in mpn(c) or "0.5K-HX" in mpn(c) or "ZIF" in c["value"].upper(),
        9.5, 270.0, 0.0, "F")
    put(lambda c: "TC2030" in fp_name(c).upper() or "TAG-CONNECT" in fp_name(c).upper(), 12.0, 150.0, 0.0, "F")
    put(lambda c: "PKMCS" in mpn(c), 22.0, 22.0, 22.0, "B")
    # NFC coil tail pads on the top, right above the module's NFC1/NFC2 pins (the coil sits in the top cover)
    put(lambda c: c["value"] == "NFC_COIL", 21.5, 222.0, 222.0 - 90.0, "F")
    put(lambda c: "SM04B" in mpn(c) or "BM04B" in mpn(c), 25.5, 132.0, 132.0 - 90.0, "B")
    return P


def main_post_fixed(bb, comps, fixed):
    for ref, c in comps.items():
        fp = bb.footprints.get(ref)
        if fp is None:
            continue
        m = mpn(c)
        if "MDBT50Q" in m:
            # inner end at r ≥ 8.8 (brass hub) and the u.FL end facing OUT: a u.FL plug over r 9.5-12.5 would hang
            # into the rotating bearing hub (top z 26.0); the coax then runs back under the board to the spindle slot
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(MODULE_POS[0], MODULE_POS[1]))))
            orient_local_toward(fp, 0.0, -6.0, *pol(MODULE_POS[0] + 20.0, MODULE_POS[1]))
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(MODULE_POS[0], MODULE_POS[1]))))
        elif "SM12B" in m:
            # side-entry: cable opening (local +y) faces the spindle bore
            orient_local_toward(fp, 0.0, 4.0, CX, CY)
            tx, ty = pol(J1_MAIN_R, 330.0)
            fp.SetPosition(pcbnew.VECTOR2I(pcbgen.MM(tx), pcbgen.MM(ty)))
        elif "TMAG5273" in m:
            # Hall element: 0.40 mm toward pin 3, 0.12 mm toward the pin 1-3 edge (TI fig. 6-2) -> on R_t = 29.0
            pads = {p.GetNumber(): p for p in _lib_fp(fp).Pads()}
            p1, p3 = pads["1"].GetPosition(), pads["3"].GetPosition()
            ux, uy = pcbnew.ToMM(p3.x - p1.x), pcbnew.ToMM(p3.y - p1.y)
            ul = math.hypot(ux, uy)
            ux, uy = ux / ul, uy / ul                      # toward pin 3 (along the pin row)
            sx = -1.0 if pcbnew.ToMM(p1.x) < 0 else 1.0     # toward the pin 1-3 side
            lx, ly = 0.40 * ux + 0.12 * sx * abs(uy), 0.40 * uy + 0.12 * sx * abs(ux)
            tx, ty = pol(29.0, 270.0)
            place_local_point(fp, lx, ly, tx, ty)
        if "WS2812" in m or (ref.startswith("C") and 101 <= refnum(ref) <= 199):
            fp.Reference().SetVisible(False)


MODULE_POS = (17.3, 215.0)   # MDBT50Q centre (r, θ), bottom side
J1_MAIN_R = 19.5             # link J1 radius: its mated plug's back must stay outside the rotating hub (r ≤ 12.5)


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
            sides[ref] = ("B", (19.0, 140.0) if not sides.get("_drv") else (19.0, 158.0))
            sides["_drv"] = True
    sides.pop("_drv", None)
    return sides


def main_inside(x, y, side):
    r = radius(x, y)
    if r > MAIN_R - 0.5:
        return False
    if r < 3.2:  # centre hole
        return False
    if side == "F" and (r < 4.6 or r > 25.3):  # M4 spindle nut (OD 7) / LED-cap ring, light box and cover skirt beyond
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

    def corridor(x, y):  # stepper chord + inclined-slot link sweep θ 35-160 under the board (docs/mechanical.md A11)
        r, th = radius(x, y), angle(x, y)
        return 8.5 <= r <= 27.0 and 30.0 <= th <= 160.0

    def low_profile(fp):  # ≤ 1.3 mm tall: chip passives and test pads only
        fpid = fp.GetFPIDAsString()
        return any(k in fpid for k in ("_0402_", "_0201_", "_0603_", "TestPoint", "Fiducial"))

    return [("B", actuator), ("*", spindle_screws), ("B", tmag_zone), ("B", corridor, low_profile)]


def build_main(bb, comps, nets):
    bb.circle(pcbnew.Edge_Cuts, CX, CY, MAIN_R, 0.1)
    bb.edge_band_keepout(bb.circle_pts(CX, CY, MAIN_R, 180))
    bb.circle(pcbnew.Edge_Cuts, CX, CY, 2.5, 0.1)  # Ø5 harness hole
    for i, th in enumerate((90, 210, 330)):   # plated GND spindle holes come from the schematic (H1-H3)
        ref = f"H{i + 1}"
        if ref in bb.footprints:
            x, y = pol(6.5, th)
            bb.footprints[ref].SetPosition(pcbnew.VECTOR2I(pcbgen.MM(x), pcbgen.MM(y)))
        else:
            x, y = pol(6.5, th)
            bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", ref)
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
    # silkscreen
    bb.text(pcbnew.F_SilkS, "dial-me-spinner main rA", CX, CY + 23.0, 1.0)
    x, y = pol(30.6, 90)
    bb.text(pcbnew.B_SilkS, "DETENT", x, y, 0.8, mirror=True)
    for th, label in ((0, "θ0 USB"), (270, "ENC")):
        x, y = pol(31.0, th)
        bb.text(pcbnew.F_Fab, label, x, y, 0.8)


def add_fiducials(bb, placer, spots):
    """1 mm fiducials (2 mm mask opening) at the nearest free spot to each (side, r, θ)."""
    for i, (side, r, th) in enumerate(spots, start=1):
        x, y = pol(r, th)
        fp = bb.board_only("Fiducial:Fiducial_1mm_Mask2mm", f"FID{i}", x, y, side)
        if not placer.place_near(fp, x, y, side, max_r=6, rotations=(0,)):
            print("WARN: no room for fiducial", fp.GetReference())
        # the router does not see the fiducial's 0.6 mm pad clearance or its 2 mm mask opening: keep tracks and vias
        # out of r 1.35 mm on its side (pad r 0.5 + 0.6 clearance + track margin; the mask opening is r 1.0)
        px, py = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
        bb.keepout([pcbnew.B_Cu if side == "B" else pcbnew.F_Cu], bb.circle_pts(px, py, 1.35, 24), pads=False,
                   pours=False, name=f"FID{i}_KEEPCLEAR")


def pours_main(bb):
    """Outer-layer GND pours (added after routing): F.Cu everywhere, B.Cu only r < 26."""
    bb.zone("GND", [pcbnew.F_Cu], bb.circle_pts(CX, CY, MAIN_R - 0.3, 96), priority=0, clearance=0.25, name="GND_TOP")
    bb.zone("GND", [pcbnew.B_Cu], bb.circle_pts(CX, CY, 25.7, 96), priority=0, clearance=0.25, name="GND_BOT")


# --------------------------------------------------------------------------- base board
BASE_R = 23.0


def base_outline(bb):
    """Ø46 disc plus a 13 mm wide tab toward θ = 0° reaching r = 35 (USB-C)."""
    half = 6.5
    a = math.degrees(math.asin(half / BASE_R))
    pts = []
    for k in range(0, 101):
        th = a + (360 - 2 * a) * k / 100
        pts.append(pol(BASE_R, th))
    # arc runs CCW (seen from the top) from (x0, CY - half) to (x0, CY + half); close through the tab
    pts += [(CX + 34.6, CY + half), (CX + 34.6, CY - half)]
    bb.polyline(pcbnew.Edge_Cuts, pts, 0.1, closed=True)
    return pts


def preroute_usb_c(bb, ref):
    """Locked pre-route for the interleaved USB-C D+/D- pad pairs (A6/B6, A7/B7).

    D+ (A6, B6) drops to two vias just behind the pads and is joined on B.Cu;
    D- (A7, B7) is joined on F.Cu by a U-shaped track behind those vias.
    """
    fp = bb.footprints.get(ref)
    if fp is None:
        return
    pads = {p.GetNumber(): p for p in fp.Pads()}
    if not all(k in pads for k in ("A6", "A7", "B6", "B7")):
        return
    a6, a7, b6, b7 = (pads[k] for k in ("A6", "A7", "B6", "B7"))
    org = fp.GetPosition()
    mid = a6.GetPosition()
    # unit vector from the connector origin toward the pad row = "rear" direction
    dx, dy = mid.x - org.x, mid.y - org.y
    # project out the along-row component: use the row normal
    rx, ry = b6.GetPosition().x - b7.GetPosition().x, b6.GetPosition().y - b7.GetPosition().y
    rl = math.hypot(rx, ry)
    rx, ry = rx / rl, ry / rl
    dot = dx * rx + dy * ry
    nx, ny = dx - dot * rx, dy - dot * ry
    nl = math.hypot(nx, ny)
    nx, ny = nx / nl, ny / nl

    def off(pad, back_mm):
        p = pad.GetPosition()
        return pcbnew.VECTOR2I(int(p.x + nx * pcbgen.MM(back_mm)), int(p.y + ny * pcbgen.MM(back_mm)))

    def track(a, b, layer, net):
        t = pcbnew.PCB_TRACK(bb.board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(pcbgen.MM(0.15))
        t.SetLayer(layer)
        t.SetNet(net)
        t.SetLocked(True)
        bb.board.Add(t)

    def via(at, net):
        v = pcbnew.PCB_VIA(bb.board)
        v.SetPosition(at)
        v.SetWidth(pcbgen.MM(0.45))
        v.SetDrill(pcbgen.MM(0.25))
        v.SetNet(net)
        v.SetLocked(True)
        bb.board.Add(v)

    dp, dm = a6.GetNet(), a7.GetNet()
    back_pad = 0.5 + max(pcbgen.pcbnew.ToMM(a6.GetSize().y), pcbgen.pcbnew.ToMM(a6.GetSize().x)) / 2
    for pad in (a6, b6):
        v = off(pad, back_pad + 0.45)
        track(pad.GetPosition(), v, pcbnew.F_Cu, dp)
        via(v, dp)
    track(off(a6, back_pad + 0.45), off(b6, back_pad + 0.45), pcbnew.B_Cu, dp)
    far = back_pad + 1.45
    track(a7.GetPosition(), off(a7, far), pcbnew.F_Cu, dm)
    track(off(a7, far), off(b7, far), pcbnew.F_Cu, dm)
    track(off(b7, far), b7.GetPosition(), pcbnew.F_Cu, dm)


def preroute_bga_escape(bb, ref):
    """Locked fan-out for the 2x4, 0.4 mm-pitch DSBGA charger (BQ25180 YBG).

    The column holding A1..D1 (INT, SCL, SDA, TS) escapes away from the other column. In the power column, A2 (VBUS)
    escapes up out of the end row, B2 (VSYS) and C2 (VBAT) escape sideways with staggered lengths, and D2 (GND)
    escapes out of the other end row into a via, so the autorouter starts outside the array.
    """
    fp = bb.footprints.get(ref)
    if fp is None:
        return
    pads = {p.GetNumber(): p for p in fp.Pads() if p.GetNumber()}
    if not all(k in pads for k in ("A1", "A2", "D1", "D2")):
        return
    P = {k: (p.GetPosition().x, p.GetPosition().y) for k, p in pads.items()}
    # unit vectors: 'col' from column 1 to column 2, 'row' from row A to row D
    cx = (P["A2"][0] - P["A1"][0], P["A2"][1] - P["A1"][1])
    rx = (P["D1"][0] - P["A1"][0], P["D1"][1] - P["A1"][1])
    cl, rl = math.hypot(*cx), math.hypot(*rx)
    col = (cx[0] / cl, cx[1] / cl)
    row = (rx[0] / rl, rx[1] / rl)

    def add(pad, segs, width, via=False):
        x, y = P[pad]
        net = pads[pad].GetNet()
        for dc, dr in segs:
            nx = x + pcbgen.MM(dc * col[0] + dr * row[0])
            ny = y + pcbgen.MM(dc * col[1] + dr * row[1])
            t = pcbnew.PCB_TRACK(bb.board)
            t.SetStart(pcbnew.VECTOR2I(int(x), int(y)))
            t.SetEnd(pcbnew.VECTOR2I(int(nx), int(ny)))
            t.SetWidth(pcbgen.MM(width))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(net)
            t.SetLocked(True)
            bb.board.Add(t)
            x, y = nx, ny
        if via:
            v = pcbnew.PCB_VIA(bb.board)
            v.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
            v.SetWidth(pcbgen.MM(0.45))
            v.SetDrill(pcbgen.MM(0.25))
            v.SetNet(net)
            v.SetLocked(True)
            bb.board.Add(v)

    # Each stub leaves the 0.23 mm NSMD land at 0.12 mm wide (about half the land, so no solder wicking or
    # skew). Power stubs widen to 0.2 mm once they are clear of the array; (dc, dr) steps are in mm along
    # (col, row).
    neck = 0.35
    for k in ("A1", "B1", "C1", "D1"):             # signals: straight out, away from the power column
        add(k, [(-0.8, 0)], 0.12)
    power_routes = {
        "A2": ((0, -neck), [(0, -0.45)], False),                   # VBUS: out of the end row
        "B2": ((neck, 0), [(1.05, 0)], False),                     # VSYS: long sideways stub
        "C2": ((neck, 0), [(0.35, 0), (0.45, 0.45)], False),      # VBAT: sideways, then angled off VSYS
        "D2": ((0, neck), [(0, 0.6)], True),                       # GND: out of the far row into a via
    }
    for k, (first, rest, via) in power_routes.items():
        add(k, [first], 0.12)
        x0, y0 = P[k]
        P[k + "_n"] = (x0 + pcbgen.MM(first[0] * col[0] + first[1] * row[0]),
                       y0 + pcbgen.MM(first[0] * col[1] + first[1] * row[1]))
        pads[k + "_n"] = pads[k]
        add(k + "_n", rest, 0.2, via)


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

    put(lambda c: "TYPE-C" in mpn(c), CX + 31.35, CY, 90.0, "F")   # mating face (local y +3.65) at r = 35
    put(lambda c: "TS-1187" in mpn(c) or c["value"].upper().startswith("SW_PRESS"), CX, CY, 0.0, "F")
    put(lambda c: "SM12B" in mpn(c) or "BM12B" in mpn(c) or c["value"] == "LINK", *pol(15.5, 120.0), 0.0, "F")
    put(lambda c: c["value"] == "BATT", *pol(J2_POS[0], J2_POS[1]), 0.0, "F")
    # NTC on the top side over the middle of the pack, away from the charger: the board is single-sided
    # (the pack sits 1 mm under it), so RT1 reads board/pack-air temperature
    put(lambda c: "NCP15" in mpn(c) or "B3435" in c["value"].upper(), *pol(8.0, 200.0), 0.0, "F")
    return P


def base_post_fixed(bb, comps, fixed):
    for ref, c in comps.items():
        fp = bb.footprints.get(ref)
        if fp is None:
            continue
        m = mpn(c)
        if "SM12B" in m:      # harness arrives from the spindle side-slot near the centre
            orient_local_toward(fp, 0.0, 4.0, CX, CY)
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(15.5, 120.0))))
        elif c["value"] == "BATT":   # mouth radially outward in the open sector; the leads drop past the board edge
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(*J2_POS))))
            orient_local_toward(fp, 0.0, 6.0, *pol(J2_POS[0] + 13.0, J2_POS[1]))
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(*J2_POS))))
            m2 = local_map(fp)
            # polarity marks behind the pin tails (local -y), where they stay visible with the plug fitted
            for lx, label in ((-1.0, "BAT+"), (1.0, "GND")):  # SH 4-pin: pins 1-2 BAT+, 3-4 GND
                x, y = m2(lx, -4.9)
                ux, uy = m2(0.0, 1.0)
                ox, oy = m2(0.0, 0.0)
                ang = math.degrees(math.atan2(-(uy - oy), ux - ox))  # text runs along the pin direction
                ang = (ang + 90) % 180 - 90
                bb.text(pcbnew.F_SilkS, label, x, y, 0.8, angle=ang)


def base_anchor_sides(comps):
    sides = {}
    for ref, c in comps.items():
        m = mpn(c)
        if "BQ25180" in m:  # off the pack (|y| > 17.25) in the open θ 240 sector, near the board edge
            sides[ref] = ("F", BQ_POS)
        elif "USBLC6" in m or "SMF5" in m:
            sides[ref] = ("F", (22.0, 0.0))
        elif "BSS138" in m:  # SOT-363 is up to 1.1 mm tall: keep it out of the θ 180 spoke sector (162-198)
            sides[ref] = ("F", (9.0, 218.0))

    return sides


def base_keepouts():
    def bosses(x, y):
        hx, hy = pol(BOSS_R, 270.0)
        return math.hypot(x - hx, y - hy) < 2.8

    def bottom(x, y):  # battery directly below: no parts on B (the NTC is placed explicitly)
        return True

    def usb_preroute(x, y):  # locked D+/D- crossing behind the USB-C signal pads
        return CX + 23.6 <= x <= CX + 27.8 and abs(y - CY) <= 1.9
    return [("*", bosses), ("B", bottom), ("F", usb_preroute)]


J2_POS = (17.0, 222.0)   # battery connector (r, θ)
BOSS_R = 20.0            # M2 boss at θ 270: Ø4.5 boss clears the pack (|y| ≤ 17.25); 1.9 mm FR4 to the edge
ANT_Y_INNER = 19.0       # antenna inner edge (device y), hardware/mechanical/dial_spinner.scad ANT_YC - ANT_W/2
ANT_B_CLEAR = 3.6        # B.Cu pour: with the 3.5 mm height gap, ≥ 5 mm from the antenna
ANT_B_TRACK_CLEAR = 1.5  # thin B.Cu tracks/vias may come closer (≈ 3.8 mm): they hardly load a ground-plane-free antenna
ANT_F_POUR_CLEAR = 2.0   # top pour held back from over the antenna
BQ_POS = (19.5, 255.0)   # charger (r, θ)
PIN_ANCHOR_MM = 3.0  # sheets: R40 within 3 mm of P0.06, U12 within 3 mm of the module's D+/D-
BGA_CLEAR_MM = 1.6  # free radius around the BQ25180 so its escape stubs and first vias have room


def base_post_place(bb, comps):
    for ref, c in comps.items():
        if "BQ25180" in mpn(c):
            preroute_bga_escape(bb, ref)


def build_base(bb, comps, nets):
    bb.edge_band_keepout(base_outline(bb))
    for ref, c in comps.items():
        if "TYPE-C" in mpn(c):
            preroute_usb_c(bb, ref)

    # supports: one M2 boss at θ 270 (outside the pack), a printed rib under the θ 90 edge (the antenna shelf
    # leaves no room for a boss there) and the USB-C shell clamped in the cup wall
    x, y = pol(BOSS_R, 270.0)
    bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", "H1")
    # 2.4 GHz antenna under the θ 90 edge (inner edge at y = ANT_Y_INNER, z ≈ 6): bottom copper (z 9.5) stays
    # ≥ 5 mm away; top copper (z 11.1) is ≥ 5 mm above it anyway, so only the top pour is held back
    seg = lambda y0: [(px, py) for px, py in bb.circle_pts(CX, CY, BASE_R + 1.0, 96) if py < CY - y0] or []  # noqa: E731
    # 4-layer base: In1 = GND plane (as on the main board), In2 = signals/power. The planes and pours keep the same
    # clearance from the antenna as B.Cu; In2 tracks the same as B.Cu tracks
    inner = [pcbnew.In1_Cu, pcbnew.In2_Cu]
    for y0, layers, kw in ((ANT_Y_INNER - ANT_B_CLEAR, [pcbnew.B_Cu] + inner, dict(tracks=False, vias=False, pads=False)),
                           (ANT_Y_INNER - ANT_B_TRACK_CLEAR, [pcbnew.B_Cu, pcbnew.In2_Cu], dict(pours=False)),
                           (ANT_Y_INNER - ANT_F_POUR_CLEAR, [pcbnew.F_Cu], dict(tracks=False, vias=False, pads=False))):
        half = math.sqrt((BASE_R + 1.0) ** 2 - y0 ** 2)
        pts = [(CX - half, CY - y0)] + sorted(seg(y0), key=lambda q: -math.atan2(CY - q[1], q[0] - CX)) + \
              [(CX + half, CY - y0)]
        kind = "TRACKS" if kw.get("pours") is False else "POUR"
        side = "F" if layers == [pcbnew.F_Cu] else "INNER_B"
        bb.keepout(layers, pts, name=f"ANTENNA_KEEPOUT_{side}_{kind}", **kw)
    # GND plane on In1 (layer type "power", so Freerouting drops GND to it through vias instead of routing it)
    bb.zone("GND", [pcbnew.In1_Cu], [(CX + 34.4, CY - 6.3), (CX + 34.4, CY + 6.3)] +
            bb.circle_pts(CX, CY, BASE_R - 0.3, 96, 20, 340), priority=0, name="GND_PLANE")
    bb.text(pcbnew.F_SilkS, "dial-me-spinner base rA", CX - 2.0, CY + 15.5, 0.8)


def pours_base(bb):
    pts = [(CX + 34.4, CY - 6.3), (CX + 34.4, CY + 6.3)] + bb.circle_pts(CX, CY, BASE_R - 0.3, 96, 20, 340)
    bb.zone("GND", [pcbnew.B_Cu], pts, priority=0, clearance=0.25, name="GND_BOT")
    bb.zone("GND", [pcbnew.F_Cu], pts, priority=0, clearance=0.25, name="GND_TOP")


# --------------------------------------------------------------------------- common flow
BOARDS = {
    "main": dict(layers=4, fixed=main_fixed, anchors=main_anchor_sides, inside=main_inside,
                 keepouts=main_keepouts, build=build_main, pours=pours_main, power_track=0.3,
                 light_power=("+3V3", "VBUS", "+13V_OLED"),  # +3V3 < 0.1 A, VBUS sense 2.4 mA, +13V_OLED < 30 mA
                 gnd_fanout=True,  # every GND SMD pad gets a via to the In1 plane before routing; GND is not routed
                 # finer signal rules around the module's LGA (JLC 4-layer minimum 0.09/0.09 mm, 0.15 mm drill)
                 rules=dict(track=0.12, clearance=0.10, via=0.40, via_drill=0.20),
                 post_fixed=main_post_fixed,
                 # LED data series R at the driving pin (P0.06), not at the first LED 30 mm away
                 pin_anchors={"R40": ("U10", "LED_DIN_MCU"), "U12": ("U10", "USB_DM")},
                 fiducials=[("F", 23.5, 45), ("F", 23.5, 165), ("F", 23.5, 285),
                            ("B", 23.5, 0), ("B", 23.0, 140), ("B", 23.0, 250)]),
    "base": dict(layers=4, fixed=base_fixed, anchors=base_anchor_sides, inside=base_inside,
                 keepouts=base_keepouts, build=build_base, pours=pours_base, power_track=0.3,
                 post_fixed=base_post_fixed, post_place=base_post_place,
                 fiducials=[("F", 19.5, 45), ("F", 19.5, 170), ("F", 19.5, 300)]),
}


def project_dir(board):
    return os.path.join(KICAD_DIR, board)


def project_name(board):
    return f"dial-me-spinner-{board}"


def group_anchors(board):
    """ref -> anchor ref, from the schematic groups (largest-pin-count part of each group)."""
    sys.path.insert(0, HERE)
    import build as sch  # noqa: E402
    import symlib  # noqa: E402
    from sheets import PROJECTS  # noqa: E402
    mods = sch.load_modules(PROJECTS[board])
    sch.build_libraries(mods, os.path.join(project_dir(board)))
    d = sch.make_design(board, mods)
    out = {}
    npins = lambda p: len(symlib.get(p.lib_id).pins)  # noqa: E731
    for sheet in d.sheets:
        sheet_ics = [p for p in sheet.parts() if p.on_board and npins(p) >= 3]
        for g in sheet.groups:
            parts = [p for p in g.parts if p.on_board]
            if not parts:
                continue
            anchor = max(parts, key=lambda p: (npins(p), -refnum(p.ref)))
            for p in parts:
                if npins(anchor) >= 3:
                    out[p.ref] = anchor.ref
                    continue
                # group without an IC (e.g. decoupling): the same-sheet IC sharing a non-GND net, most pins first
                nets = {n for n in p.pins.values() if n and n != "GND"}
                cands = [ic for ic in sheet_ics if nets & {n for n in ic.pins.values() if n}]
                if cands:
                    out[p.ref] = max(cands, key=lambda ic: (npins(ic), -refnum(ic.ref))).ref
    return out


def generate(board, pours=True):
    cfg = BOARDS[board]
    pdir = project_dir(board)
    netpath = os.path.join(pdir, project_name(board) + ".net")
    comps, nets = pcbgen.load_netlist(netpath)
    bb = pcbgen.BoardBuilder(cfg["layers"], {LIB: os.path.join(pdir, "lib", LIB + ".pretty")})
    rules = cfg.get("rules", dict(track=0.15, clearance=0.13, via=0.45, via_drill=0.25))
    bb.rules(edge=0.3, **rules)
    bb.set_origin(CX, CY)
    power = [n for n in nets if n in ("VSYS", "VLED", "VBUS", "VBAT", "+3V3", "GND", "+13V_OLED", "OLED_VIN")
             or n.endswith("/VSYS")]
    pt = cfg["power_track"]
    light = [n for n in power if n in cfg.get("light_power", ())]  # low-current rails: 0.2 mm eases the dense areas
    clr = rules["clearance"]
    bb.netclass("Power", [n for n in power if n != "GND" and n not in light], track=pt, clearance=clr, via=0.5,
                via_drill=0.25)
    if light:
        bb.netclass("Supply", light, track=0.2, clearance=clr, via=rules["via"], via_drill=rules["via_drill"])
    bb.netclass("Ground", ["GND"], track=pt, clearance=clr, via=0.5, via_drill=0.25)
    fixed = cfg["fixed"](comps)
    bb.place_from_netlist(comps, nets, fixed, default=(CX, CY, 0.0, "F"))
    cfg["build"](bb, comps, nets)

    _FP_LIBS[LIB] = os.path.join(pdir, "lib", LIB + ".pretty")
    if "post_fixed" in cfg:
        cfg["post_fixed"](bb, comps, fixed)
    placer = Placer(bb.board, cfg["inside"], cfg["keepouts"](), power_nets=("GND",))
    for ref in fixed:
        placer.mark(bb.footprints[ref])
    for fp in bb.board.GetFootprints():  # mounting holes added by the board builder
        if fp.GetReference().startswith("H"):
            placer.mark(fp)
    # parts that must sit at a specific IC pin (series terminations at the driver, ESD arrays at the pins), placed
    # before everything else: within PIN_ANCHOR_MM on the IC's side, else on the other side over the pad (one via),
    # else as close as possible on the IC's side (a module's own courtyard can keep its side > 3 mm away)
    for ref, (ic, net) in cfg.get("pin_anchors", {}).items():
        if ref in bb.footprints and ic in bb.footprints:
            pads = [p for p in bb.footprints[ic].Pads() if p.GetNetname().split("/")[-1] == net]
            if pads:
                px, py = pcbnew.ToMM(pads[0].GetPosition().x), pcbnew.ToMM(pads[0].GetPosition().y)
                side = Placer.side(bb.footprints[ic])
                other = "F" if side == "B" else "B"
                fp = bb.footprints[ref]
                if not (placer.place_near(fp, px, py, side, max_r=PIN_ANCHOR_MM) or
                        placer.place_near(fp, px, py, other, max_r=PIN_ANCHOR_MM)):
                    if placer.place_near(fp, px, py, side, max_r=6):
                        print(f"WARN: {ref} is more than {PIN_ANCHOR_MM} mm from {ic} {net}")
                    else:
                        print("WARN: could not place", ref, "at", ic, net)
                fixed[ref] = None
    # anchors: explicit side/region parts first, placed near their region centre
    anchor_cfg = cfg["anchors"](comps)
    anchors = [bb.footprints[r] for r in fixed if r in bb.footprints]
    for ref, (side, (r, th)) in sorted(anchor_cfg.items(), key=lambda kv: refnum(kv[0])):
        if ref in fixed or ref not in bb.footprints:
            continue
        x, y = pol(r, th)
        fp = bb.footprints[ref]
        if not placer.place_near(fp, x, y, side, max_r=20):
            print("WARN: could not place anchor", ref)
        if "BQ25180" in mpn(comps[ref]):  # reserve room for the BGA escape stubs + first vias
            px, py = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
            placer.occupied[side].append((ref + "_esc", (px - BGA_CLEAR_MM, py - BGA_CLEAR_MM,
                                                         px + BGA_CLEAR_MM, py + BGA_CLEAR_MM)))
        anchors.append(fp)
    # everything else clusters around its schematic-group anchor (fallback: the part it shares most nets with)
    gmap = group_anchors(board)
    rest = [fp for ref, fp in bb.footprints.items()  # board-only holes/fiducials stay where the builder put them
            if ref in comps and ref not in fixed and ref not in anchor_cfg]
    # group anchors (ICs) first so their passives can cluster around them
    rest.sort(key=lambda fp: (0 if gmap.get(fp.GetReference()) == fp.GetReference() else 1,
                              -fp.GetPadCount(), refnum(fp.GetReference())))
    placed_refs = set(fixed) | set(anchor_cfg)
    unplaced = []
    for fp in rest:
        ga = gmap.get(fp.GetReference())
        a = None
        if ga and ga != fp.GetReference() and ga in placed_refs and ga in bb.footprints:
            a = bb.footprints[ga]
            # a decoupling/support part sharing no net with its group anchor still goes next to it
        if a is None or not ({p.GetNetname() for p in fp.Pads()} & {p.GetNetname() for p in a.Pads()}):
            a = placer.anchor_for(fp, anchors) or a or anchors[0]
        tx, ty = placer.target(fp, a)
        side = Placer.side(a)
        if not placer.place_near(fp, tx, ty, side, max_r=18) and \
                not placer.place_near(fp, tx, ty, "F" if side == "B" else "B", max_r=25):
            unplaced.append(fp.GetReference())
        placed_refs.add(fp.GetReference())
        if fp.GetPadCount() > 2:
            anchors.append(fp)
    if unplaced:
        print("WARN: unplaced:", ", ".join(unplaced))
    if "fiducials" in cfg:
        add_fiducials(bb, placer, cfg["fiducials"])
    if "post_place" in cfg:
        cfg["post_place"](bb, comps)
    moved, hidden = silk.place_refs(bb.board)
    print(f"[{board}] silk: {moved} references placed, {hidden} hidden (no room)")
    if pours:
        cfg["pours"](bb)
    out = os.path.join(pdir, project_name(board) + ".kicad_pcb")
    bb.save(out)
    set_layer_types(out, cfg["layers"])
    return out


def thermal_points(b):
    """Priority stitching spots: rings around the charger's GND ball (BQ25180 D2) for its heat path."""
    pts = []
    for fp in b.GetFootprints():
        if "BQ25180" in (fp.GetFieldText("MPN") if fp.HasFieldByName("MPN") else ""):
            for pad in fp.Pads():
                if pad.GetNumber() == "D2":
                    x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
                    pts += [(x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a)))
                            for r in (0.9, 1.2, 1.5, 1.8) for a in range(0, 360, 20)]
    return pts


def prune_dangling(path, rounds=6):
    """Delete the wiring that KiCad's DRC flags as dangling (track_dangling / via_dangling), keeping a deletion only
    if the board stays fully connected.  Locked BGA escape stubs count too: they are locked only so the router keeps
    them, and one the router bypassed (it reached the ball directly) is a dead stub."""
    removed = 0
    for _ in range(rounds):
        rpt, _ = drc(path)
        spots = []
        kind = None
        for line in open(rpt, encoding="utf-8"):
            if line.startswith("["):
                kind = line[1:].split("]")[0]
            elif kind in ("track_dangling", "via_dangling") and line.strip().startswith("@("):
                xy = line.split("@(")[1].split(")")[0].replace("mm", "").split(",")
                m = re.search(r" on (\S+), length ([0-9.]+) mm", line)
                spots.append((kind, float(xy[0]), float(xy[1]), m.group(1) if m else None,
                              float(m.group(2)) if m else None))
                kind = None
        if not spots:
            break
        backup = path + ".bak"
        shutil.copyfile(path, backup)
        b = pcbnew.LoadBoard(path)
        doomed = []
        for kind, x, y, layer, length in spots:
            p = pcbnew.VECTOR2I(pcbgen.MM(x), pcbgen.MM(y))
            for t in b.GetTracks():
                if t in doomed:
                    continue
                if kind == "via_dangling" and t.Type() == pcbnew.PCB_VIA_T and (t.GetStart() - p).EuclideanNorm() < 2000:
                    doomed.append(t)
                elif kind == "track_dangling" and t.Type() == pcbnew.PCB_TRACE_T and \
                        b.GetLayerName(t.GetLayer()) == layer and abs(pcbnew.ToMM(t.GetLength()) - length) < 0.002 and \
                        min((t.GetStart() - p).EuclideanNorm(), (t.GetEnd() - p).EuclideanNorm()) < 2000:
                    doomed.append(t)
        if not doomed:
            os.remove(backup)
            break
        for t in doomed:
            b.Delete(t)
        pcbnew.SaveBoard(path, b)
        pcbgen.refill(path)
        _, after = drc(path)
        if after.get("[unconnected_items]", 0):
            shutil.copyfile(backup, path)  # that piece was load-bearing after all: keep the board as it was
            os.remove(backup)
            break
        os.remove(backup)
        removed += len(doomed)
    return removed


def finish(board, path):
    """Post-route clean-up (needs the pours): duplicate/dangling/overlaid wiring, GND stitching, silk, refill."""
    b = pcbnew.LoadBoard(path)
    dups, trimmed = pcbgen.dedupe_tracks(b), pcbgen.trim_dangling(b)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    debris = pcbgen.remove_debris(b)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    stitched = pcbgen.stitch_vias(b, "GND", pitch=BOARDS[board].get("stitch_pitch", 3.0), priority=thermal_points(b))
    moved, hidden = silk.place_refs(b)
    pcbnew.SaveBoard(path, b)
    pcbgen.refill(path)
    pruned = prune_dangling(path)
    print(f"[{board}] finish: {dups} duplicate tracks, {trimmed} stubs trimmed, {debris + pruned} debris items removed, "
          f"{stitched} GND stitching vias, {moved} references placed, {hidden} hidden")


def add_pours(board, path):
    bb = pcbgen.BoardBuilder.load(path)
    BOARDS[board]["pours"](bb)
    bb.save(path)


def set_layer_types(path, layers):
    """Mark In1.Cu as a power plane so Freerouting keeps signals off it."""
    if layers != 4:
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r'\((\d+) "In1\.Cu" signal\)', r'(\1 "In1.Cu" power)', s)  # KiCad 9 numbers In1 as layer 4
    if not n:
        raise RuntimeError("In1.Cu layer entry not found: the GND plane would be routed as a signal layer")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


def drc(path, warnings=None):
    """Errors as {type: n}; warnings (silk etc.) go into the optional `warnings` dict. Includes schematic parity."""
    rpt = path.replace(".kicad_pcb", "-drc.rpt")
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--schematic-parity", "-o", rpt, path],
                   capture_output=True)
    counts, kind = {}, None
    with open(rpt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("["):
                kind = line.split("]")[0] + "]"
            elif kind and line.startswith("    ") and ("; error" in line or "; warning" in line):
                target = counts if "; error" in line else warnings
                if target is not None:
                    target[kind] = target.get(kind, 0) + 1
                kind = None
    return rpt, counts


def _sexpr_end(s, i):
    """Index just past the s-expression that opens at s[i] == "("."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if not depth:
                return k + 1
    raise ValueError("unbalanced s-expression")


def dsn_plane_as_layer_rule(dsn, net="GND", layer="In1.Cu"):
    """Freerouting 2.1 does not route against a (plane ...) on a power layer: it places no vias through the plane,
    so GND pads and every layer change stay unrouted (base board: 34 connections for 500 passes).  The DSN therefore
    gives In1 as a signal layer without the plane, and every class except the plane net's own is kept off it
    (circuit use_layer).  GND may still run on In1; KiCad refills the plane around everything after the route."""
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r"(\(layer %s\s*\(type )power\)" % re.escape(layer), r"\1signal)", s)
    if not n:
        return
    while (i := s.find(f"(plane {net} ")) >= 0:
        s = s[:i] + s[_sexpr_end(s, i):]
    others = [m for m in re.findall(r"\(layer (\S+)\s*\(type", s) if m != layer]
    out, pos = [], 0
    for m in re.finditer(r"\(class (\S+)", s):
        start = m.start()
        end = _sexpr_end(s, start)
        block = s[start:end]
        nets = re.findall(r'"[^"]*"|[^\s()]+', block[:block.index("(", 1)])[2:]
        if nets != [net]:
            c = block.index("(circuit") + len("(circuit")
            block = block[:c] + f"\n        (use_layer {' '.join(others)})" + block[c:]
        out += [s[pos:start], block]
        pos = end
    out.append(s[pos:])
    with open(dsn, "w", encoding="utf-8") as f:
        f.write("".join(out))


def dsn_drop_net(dsn, net="GND"):
    """Leave a net out of the routing: its pins become no-net obstacles, and its pre-placed copper (the locked GND
    fan-out vias and tracks) is handed over as keepouts so the router still keeps clear of it.  Used where the net
    reaches an inner plane through fan-out vias placed before routing (Freerouting cannot route against a plane,
    and wiring every GND pad as a trace swamps the main board)."""
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    m = re.search(r"\(net %s\s" % re.escape(net), s)
    if not m:
        return
    s = s[:m.start()] + s[_sexpr_end(s, m.start()):]
    # classes: drop the net from its class; a class left with no nets goes
    out, pos = [], 0
    for m in re.finditer(r"\(class (\S+)", s):
        if m.start() < pos:
            continue
        end = _sexpr_end(s, m.start())
        block = s[m.start():end]
        head, rest = block[:block.index("(", 1)], block[block.index("(", 1):]
        names = re.findall(r'"[^"]*"|[^\s()]+', head)[2:]
        if net in names:
            names = [n for n in names if n != net]
            block = (f"(class {m.group(1)} {' '.join(names)}\n      " + rest) if names else ""
        out += [s[pos:m.start()], block]
        pos = end
    out.append(s[pos:])
    s = "".join(out)
    # pre-placed copper of the net -> keepouts in the structure
    layers = re.findall(r"\(layer (\S+)\s*\(type", s)
    keep = []
    for m in list(re.finditer(r"\(wire \(path (\S+) ([0-9.]+) ([^)]*)\)\s*\(net %s\)[^\n]*" % re.escape(net), s))[::-1]:
        keep.append(f'    (keepout "" (path {m.group(1)} {m.group(2)} {m.group(3)}))')
        s = s[:m.start()] + s[m.end():]
    for m in list(re.finditer(r'\(via "([^"]+)"\s+([-0-9.]+) ([-0-9.]+)\s*\(net %s\)[^\n]*' % re.escape(net), s))[::-1]:
        dia = re.search(r"Via\[[0-9]+-[0-9]+\]_([0-9.]+):", m.group(1))
        d = float(dia.group(1)) if dia else 500.0
        keep += [f'    (keepout "" (circle {lay} {d:g} {m.group(2)} {m.group(3)}))' for lay in layers]
        s = s[:m.start()] + s[m.end():]
    st = s.find("(structure")
    end = _sexpr_end(s, st)
    s = s[:end - 1] + "\n".join(keep) + "\n  )" + s[end:]
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def dsn_clearance_margin(dsn, margin_um=10):
    """Freerouting approximates rotated pads (the 48 ring LEDs sit at 7.5° steps) with octagons and lands a few µm
    inside KiCad's clearance; route with the plain clearances raised by margin_um so the result passes KiCad's DRC."""
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r"\(clearance ([0-9.]+)\)", lambda m: f"(clearance {float(m.group(1)) + margin_um:g})", s)
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def route(path, minutes=30, threads=1, optimizer_passes=20, drop_nets=()):
    """Freerouting batch run; its log goes next to the board (*.freerouting.log) so progress can be followed.
    Freerouting 2.1 ignores the pass limit in batch mode (-mp and router.max_passes never reach the batch loop), so
    the run is bounded by its job timeout, after which it writes the best board so far.  The post-route optimizer
    is capped (its default of 100 passes takes hours on the 4-layer main board)."""
    jar = FREEROUTING or os.path.join(os.environ.get("SCRATCH", "/tmp"), "freerouting.jar")
    if not os.path.exists(jar):
        raise SystemExit(f"Freerouting jar not found ({jar}); set FREEROUTING_JAR")
    dsn = path.replace(".kicad_pcb", ".dsn")
    ses = path.replace(".kicad_pcb", ".ses")
    if os.path.exists(ses):
        os.remove(ses)
    pcbgen.export_dsn(path, dsn)
    dsn_plane_as_layer_rule(dsn)
    for n in drop_nets:
        dsn_drop_net(dsn, n)
    dsn_clearance_margin(dsn)
    with open(path.replace(".kicad_pcb", ".freerouting.log"), "w") as log:
        subprocess.run(["java", "-jar", jar, "-de", dsn, "-do", ses, "-mt", str(threads),
                        f"--router.job_timeout={minutes // 60:02d}:{minutes % 60:02d}:00",
                        f"--router.optimizer.max_passes={optimizer_passes}", "--gui.enabled=false"],
                       timeout=(minutes + 60) * 60, stdout=log, stderr=subprocess.STDOUT)
    if not os.path.exists(ses):
        raise RuntimeError("Freerouting produced no session file")
    pcbgen.import_ses(path, ses, path)
    for f in (dsn, ses):
        os.remove(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS))
    ap.add_argument("--route", action="store_true")
    ap.add_argument("--minutes", type=int, default=30, help="Freerouting time budget for the first attempt")
    ap.add_argument("--attempts", type=int, default=3, help="re-run Freerouting on the routed board while connections remain")
    ap.add_argument("--finish", action="store_true", help="only clean up an already routed board (no re-placement)")
    a = ap.parse_args()
    for board in BOARDS:
        if a.board and board != a.board:
            continue
        if a.finish:
            out = os.path.join(project_dir(board), project_name(board) + ".kicad_pcb")
            finish(board, out)
            warn = {}
            rpt, counts = drc(out, warn)
            print(f"[{board}] DRC errors:", counts or "none", "| warnings:", warn or "none", "->", rpt)
            continue
        out = generate(board, pours=not a.route)
        print(f"[{board}] placed ->", out)
        if a.route:
            drop = ()
            if BOARDS[board].get("gnd_fanout"):
                b = pcbnew.LoadBoard(out)
                done, left = pcbgen.fanout_vias(b, "GND")
                pcbnew.SaveBoard(out, b)
                pcbgen.refill(out)
                print(f"[{board}] GND fan-out: {done} pads, {len(left)} without room:",
                      [(p.GetParentFootprint().GetReference(), p.GetNumber()) for p in left])
                drop = ("GND",)
            for attempt in range(a.attempts):
                route(out, a.minutes * (attempt + 1), drop_nets=drop)
                _, counts = drc(out)
                left = counts.get("[unconnected_items]", 0)
                print(f"[{board}] route attempt {attempt + 1}: {left} unconnected")
                if not left:
                    break
            add_pours(board, out)
            finish(board, out)
            print(f"[{board}] routed")
        warn = {}
        rpt, counts = drc(out, warn)
        print(f"[{board}] DRC errors:", counts or "none", "| warnings:", warn or "none", "->", rpt)


if __name__ == "__main__":
    main()
