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


def local_map(fp):
    """Affine map (footprint-local mm -> board mm) solved from the pads, so flips/rotations are exact."""
    import numpy as np
    ref = pcbnew.FootprintLoad(*fp_lib_path(fp)) if fp_lib_path(fp) else None
    if ref is None:
        return None
    loc = {p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in ref.Pads()}
    src, dst = [], []
    for p in fp.Pads():
        if p.GetNumber() in loc:
            src.append(loc[p.GetNumber()])
            dst.append((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)))
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

    put(lambda c: "TMAG5273" in mpn(c), 29.0, 270.0, 0.0, "B")          # long axis radial (SOT-23 pins along x)
    put(lambda c: "DRV5032" in mpn(c), 21.5, 90.0, 0.0, "F")
    put(lambda c: "MDBT50Q" in mpn(c), 14.5, 215.0, 215.0 + 90.0, "B")   # u.FL end toward the centre
    put(lambda c: "SM12B" in mpn(c) or "BM12B" in mpn(c) or c["value"] == "LINK", 17.5, 330.0, 0.0, "B")
    put(lambda c: "AFC01" in mpn(c) or "FH12" in mpn(c) or "0.5K-HX" in mpn(c) or "ZIF" in c["value"].upper(),
        9.5, 270.0, 0.0, "F")
    put(lambda c: "TC2030" in fp_name(c).upper() or "TAG-CONNECT" in fp_name(c).upper(), 12.0, 150.0, 0.0, "F")
    put(lambda c: "PKMCS" in mpn(c), 22.0, 22.0, 22.0, "B")
    put(lambda c: "SM04B" in mpn(c) or "BM04B" in mpn(c), 25.5, 132.0, 132.0 - 90.0, "B")
    return P


def main_post_fixed(bb, comps, fixed):
    for ref, c in comps.items():
        fp = bb.footprints.get(ref)
        if fp is None:
            continue
        m = mpn(c)
        if "MDBT50Q" in m:
            # u.FL / antenna end (local y ~ -6) toward the spindle so the coax drops straight down the bore
            orient_local_toward(fp, 0.0, -6.0, CX, CY)
        elif "SM12B" in m:
            # side-entry: cable opening (local +y) faces the spindle bore
            orient_local_toward(fp, 0.0, 4.0, CX, CY)
            tx, ty = pol(17.5, 330.0)
            fp.SetPosition(pcbnew.VECTOR2I(pcbgen.MM(tx), pcbgen.MM(ty)))
        elif "TMAG5273" in m:
            # Hall element: 0.40 mm toward pin 3, 0.12 mm toward the pin 1-3 edge (TI fig. 6-2) -> on R_t = 29.0
            pads = {p.GetNumber(): p for p in pcbnew.FootprintLoad(*fp_lib_path(fp)).Pads()}
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
    bb.circle(pcbnew.Edge_Cuts, CX, CY, MAIN_R, 0.1)
    bb.edge_band_keepout(bb.circle_pts(CX, CY, MAIN_R, 180))
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
    # silkscreen
    bb.text(pcbnew.F_SilkS, "dial-me-spinner main rA", CX, CY + 23.0, 1.0)
    x, y = pol(30.6, 90)
    bb.text(pcbnew.B_SilkS, "DETENT", x, y, 0.8, mirror=True)
    for th, label in ((0, "θ0 USB"), (270, "ENC")):
        x, y = pol(31.0, th)
        bb.text(pcbnew.F_Fab, label, x, y, 0.8)


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


def preroute_bga_escape(bb, ref, length=0.7, power=("VBUS", "VSYS", "VBAT", "GND"), via_nets=("VSYS",)):
    """Locked escape stubs for a 2-column fine-pitch BGA: each ball goes straight outward, away from
    the other column, so the autorouter starts outside the 0.4 mm-pitch array."""
    fp = bb.footprints.get(ref)
    if fp is None:
        return
    pads = [p for p in fp.Pads() if p.GetNumber() and p.GetNetname()]
    xs = [p.GetPosition().x for p in pads]
    ys = [p.GetPosition().y for p in pads]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    along_x = (max(xs) - min(xs)) < (max(ys) - min(ys))  # columns separated in x -> escape along x
    for p in pads:
        pos = p.GetPosition()
        if along_x:
            d = pcbnew.VECTOR2I(pcbgen.MM(length) * (1 if pos.x > cx else -1), 0)
        else:
            d = pcbnew.VECTOR2I(0, pcbgen.MM(length) * (1 if pos.y > cy else -1))
        k = 1.6 if p.GetNetname() in via_nets else 1.0  # inner power ball: longer stub ending in a via
        end = pcbnew.VECTOR2I(pos.x + int(d.x * k), pos.y + int(d.y * k))
        t = pcbnew.PCB_TRACK(bb.board)
        t.SetStart(pos)
        t.SetEnd(end)
        t.SetWidth(pcbgen.MM(0.2 if p.GetNetname() in power else 0.15))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(p.GetNet())
        t.SetLocked(True)
        bb.board.Add(t)
        if p.GetNetname() in via_nets:
            v = pcbnew.PCB_VIA(bb.board)
            v.SetPosition(end)
            v.SetWidth(pcbgen.MM(0.5))
            v.SetDrill(pcbgen.MM(0.25))
            v.SetNet(p.GetNet())
            v.SetLocked(True)
            bb.board.Add(v)


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
    put(lambda c: "PH-SM4" in mpn(c) or "S2B-PH" in mpn(c), *pol(17.0, 212.0), 0.0, "F")
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
        elif "S2B-PH" in m:   # battery leads come from the pack end at θ = 180°
            orient_local_toward(fp, 0.0, 6.0, *pol(30.0, 190.0))
            fp.SetPosition(pcbnew.VECTOR2I(*(pcbgen.MM(v) for v in pol(17.0, 212.0))))


def base_anchor_sides(comps):
    sides = {}
    for ref, c in comps.items():
        m = mpn(c)
        if "BQ25180" in m:
            sides[ref] = ("F", (12.0, 330.0))
        elif "USBLC6" in m or "SMF5" in m:
            sides[ref] = ("F", (22.0, 0.0))
        elif "BSS138" in m:
            sides[ref] = ("F", (9.0, 200.0))
        elif "NCP15" in m or "B3435" in c["value"].upper() or "NTC" in c["value"].upper():
            sides[ref] = ("F", (18.0, 270.0))
    return sides


def base_keepouts():
    def bosses(x, y):
        return any(math.hypot(x - hx, y - hy) < 2.8 for hx, hy in (pol(21.0, a) for a in (90, 270)))

    def bottom(x, y):  # battery directly below: no parts on B
        return True

    def usb_preroute(x, y):  # locked D+/D- crossing behind the USB-C signal pads
        return CX + 23.6 <= x <= CX + 27.8 and abs(y - CY) <= 1.9
    return [("*", bosses), ("B", bottom), ("F", usb_preroute)]


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

    for i, th in enumerate((90, 270)):   # clear of the pack (long axis along θ 0/180); USB shell is the 3rd support
        x, y = pol(21.0, th)
        bb.mounting_hole(x, y, "MountingHole:MountingHole_2.2mm_M2", f"H{i + 1}")
    bb.text(pcbnew.F_SilkS, "dial-me-spinner base rA", CX - 2.0, CY + 18.5, 0.8)


def pours_base(bb):
    pts = [(CX + 34.4, CY - 6.3), (CX + 34.4, CY + 6.3)] + bb.circle_pts(CX, CY, BASE_R - 0.3, 96, 20, 340)
    bb.zone("GND", [pcbnew.B_Cu], pts, priority=0, clearance=0.25, name="GND_BOT")
    bb.zone("GND", [pcbnew.F_Cu], pts, priority=0, clearance=0.25, name="GND_TOP")


# --------------------------------------------------------------------------- common flow
BOARDS = {
    "main": dict(layers=4, fixed=main_fixed, anchors=main_anchor_sides, inside=main_inside,
                 keepouts=main_keepouts, build=build_main, pours=pours_main, power_track=0.3,
                 post_fixed=main_post_fixed),
    "base": dict(layers=2, fixed=base_fixed, anchors=base_anchor_sides, inside=base_inside,
                 keepouts=base_keepouts, build=build_base, pours=pours_base, power_track=0.25,
                 post_fixed=base_post_fixed, post_place=base_post_place),
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
    bb.rules(track=0.15, clearance=0.13, via=0.45, via_drill=0.25, edge=0.3)
    bb.set_origin(CX, CY)
    power = [n for n in nets if n in ("VSYS", "VLED", "VBUS", "VBAT", "+3V3", "GND", "+13V_OLED", "OLED_VIN")
             or n.endswith("/VSYS")]
    pt = cfg["power_track"]
    bb.netclass("Power", [n for n in power if n != "GND"], track=pt, clearance=0.13, via=0.5, via_drill=0.25)
    bb.netclass("Ground", ["GND"], track=pt, clearance=0.13, via=0.5, via_drill=0.25)
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
    rest = [fp for ref, fp in bb.footprints.items() if ref not in fixed and ref not in anchor_cfg]
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
    if "post_place" in cfg:
        cfg["post_place"](bb, comps)
    if pours:
        cfg["pours"](bb)
    out = os.path.join(pdir, project_name(board) + ".kicad_pcb")
    bb.save(out)
    set_layer_types(out, cfg["layers"])
    return out


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
    ap.add_argument("--attempts", type=int, default=3, help="re-run Freerouting on the routed board while connections remain")
    a = ap.parse_args()
    for board in BOARDS:
        if a.board and board != a.board:
            continue
        out = generate(board, pours=not a.route)
        print(f"[{board}] placed ->", out)
        if a.route:
            for attempt in range(a.attempts):
                route(out, a.passes + 10 * attempt)
                _, counts = drc(out)
                left = counts.get("[unconnected_items]", 0)
                print(f"[{board}] route attempt {attempt + 1}: {left} unconnected")
                if not left:
                    break
            add_pours(board, out)
            print(f"[{board}] routed")
        rpt, counts = drc(out)
        print(f"[{board}] DRC errors:", counts or "none", "->", rpt)


if __name__ == "__main__":
    main()
