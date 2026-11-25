"""Rev B bench board: the NFC coil on a display support plate, for issue #5's NFC test.

docs/display-study.md §3.3: a 4-turn coil on the rim of a 0.4 mm FR4 support plate,
r 24.6-26.3, copper >= 0.3 mm from the r 26.6 edge, over a TDK IFL05K ferrite sheet, 3.5 mm
above the main board's ground plane.  This plate is that coil and nothing else.  It stacks on
bench_nfc_base (a copy of the main board's ground plane with the tuning network) and carries
the real panel on top, so L, Q and resonance can be measured with the NanoVNA and reads
tried with 2-3 phones, with and without the ferrite notches.

The coil is one footprint (L1) holding all its copper: a 4-turn coil cannot be drawn as
tracks, because it joins NFC1 to NFC2 and DRC would call it a short.  The footprint is a net
tie between its two contact pads, the way commercial NFC antenna footprints are built.

Geometry: four concentric turns 0.25 mm wide on a 0.483 mm pitch (0.233 mm gap), each
joined to the next by a 10-degree jog at theta 190-200.  An Archimedean spiral would need a
0.115 mm gap to fit four turns in the 1.7 mm band.  The outer end crosses the turns on
B.Cu at theta 210.  Both contact pads are on the BOTTOM at r 23.0, theta 190 and 210: where the
study proposes moving J11 (r 22.5-24.5, theta 195-205, outside the glass) and where spring
contacts from the main board would meet them.  theta is CCW seen from the top, 0 toward +x
(the USB-C side), as everywhere in the repo.
"""

import math

SHEET = ("bench_nfc_plate", "bench_nfc_plate.kicad_sch", "NFC coil plate")
TITLE = "dial-me-spinner rev B bench: NFC coil support plate"
REV = "1"
DATE = "2026-10-23"
POWER_NETS = []
# The plate's only part is the coil; its ends meet the base board by wire or spring contact.
SINGLE_PIN_NETS = ["COIL_A", "COIL_B"]

COIL_FP_NAME = "NFC_Coil_4T_R24.6-26.3_SupportPlate"
COIL_FP = "dial_spinner:" + COIL_FP_NAME

R_OUT_EDGE, R_IN_EDGE = 26.3, 24.6     # study §3.3 copper band
TRACK = 0.25
TURNS = 4
PITCH = (R_OUT_EDGE - R_IN_EDGE - TRACK) / (TURNS - 1)     # 0.4833: centreline to centreline
R0 = R_OUT_EDGE - TRACK / 2                                 # outermost centreline, 26.175
JOG = (190.0, 200.0)                                        # turn k (r_k, 190) -> turn k+1 (r_k+1, 200)
A_THETA, B_THETA = 210.0, 190.0                             # outer (A) and inner (B) ends
PAD_R = 23.0
VIA, VIA_DRILL = 0.45, 0.25
UNDER = 0.30                                                # B.Cu underpass width
EDGE = 0.30                                                 # copper to the r 26.6 plate edge (study §3.3)
A_VIA_R = 26.6 - EDGE - VIA / 2                             # 26.075: the outer end steps 0.1 in to its via
# The via cannot sit 0.483 mm outside the next turn: the inner three turns dip 0.3 mm over theta 200-220 to clear it
# (full depth 204-216, linear ramps).  The innermost copper goes to r 24.3 there; electrically nothing.
DIP, DIP_SPAN = 0.30, (200.0, 204.0, 216.0, 220.0)

SYMBOLS = [
    dict(
        name="NFC_Coil",
        ref="L",
        footprint=COIL_FP,
        description="NFC tag coil, 4 turns, on the display support plate (net tie between the ends)",
        keywords="nfc antenna coil",
        pins=[(1, "A", "passive", "T"), (2, "B", "passive", "B")],   # vertical: the generator lays 2-pin parts out flat
    ),
]


def _xy(r, deg):
    a = math.radians(deg)
    return r * math.cos(a), -r * math.sin(a)


def footprints(fpgen, lib_dir):
    pcbnew = fpgen.pcbnew
    fp = fpgen.Footprint(
        COIL_FP_NAME,
        f"NFC tag coil, {TURNS} concentric turns {TRACK} mm on a {PITCH:.3f} mm pitch, copper r "
        f"{R_IN_EDGE}-{R_OUT_EDGE}; B.Cu underpass at {A_THETA:g} deg; contact pads on B.Cu at r {PAD_R}. "
        "Net tie 1-2: the coil IS the connection. docs/display-study.md 3.3.",
        "nfc coil antenna net-tie")
    fp.fp.SetAttributes(pcbnew.FP_SMD)

    def seg(layer, p0, p1, w):
        s = pcbnew.PCB_SHAPE(fp.fp)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(fpgen._v(*p0))
        s.SetEnd(fpgen._v(*p1))
        s.SetLayer(layer)
        s.SetWidth(fpgen.MM(w))
        fp.fp.Add(s)

    def dip(th):
        a, b, c, e = DIP_SPAN
        th = th % 360.0
        if b <= th <= c:
            return DIP
        if a < th < b:
            return DIP * (th - a) / (b - a)
        if c < th < e:
            return DIP * (e - th) / (e - c)
        return 0.0

    def arc(r, a0, a1, dips, step=1.0):
        """CCW from a0 to a1 (degrees, a1 > a0), as short chords: sagitta at r 26 and 1 deg is 0.001 mm."""
        n = max(2, int(math.ceil((a1 - a0) / step)))
        ths = [a0 + (a1 - a0) * i / n for i in range(n + 1)]
        pts = [_xy(r - (dip(t) if dips else 0.0), t) for t in ths]
        for p0, p1 in zip(pts, pts[1:]):
            seg(pcbnew.F_Cu, p0, p1, TRACK)

    radii = [R0 - k * PITCH for k in range(TURNS)]
    for k, r in enumerate(radii):
        start = A_THETA if k == 0 else JOG[1]
        arc(r, start, JOG[0] + 360.0, dips=k > 0)
        if k + 1 < TURNS:
            seg(pcbnew.F_Cu, _xy(r, JOG[0]), _xy(radii[k + 1], JOG[1]), TRACK)

    # pad 1 (A): the outer end steps in to its via, then a B.Cu underpass runs inward across the turns to the
    # contact pad.  The underpass is a mask-covered copper PAD, not a graphic: footprint graphics carry no
    # connectivity, so DRC would see the via and the contact pad as unconnected.
    seg(pcbnew.F_Cu, _xy(R0, A_THETA), _xy(A_VIA_R, A_THETA), TRACK)
    via = fp.tht("1", *_xy(A_VIA_R, A_THETA), VIA, VIA_DRILL)
    # 0.117 mm from turn 0 a degree past its start -- the same conductor that feeds this via, so the clearance
    # is not between two nets.  KiCad still checks net-tie graphics against pads, hence the local value.
    via.SetLocalClearance(fpgen.MM(0.10))
    run = A_VIA_R - PAD_R
    fp._pad("1", *_xy(PAD_R + run / 2, A_THETA), run, UNDER, "rect", pcbnew.PAD_ATTRIB_SMD, [pcbnew.B_Cu],
                 rot=A_THETA)
    fp.smd("1", *_xy(PAD_R, A_THETA), 2.0, 1.6, rot=A_THETA, paste=False, layer="B")
    # pad 2 (B): the inner end comes in on F.Cu, drops through a via clear of the inner turn, then to its pad
    r_via = R_IN_EDGE - 0.5
    seg(pcbnew.F_Cu, _xy(radii[-1], B_THETA), _xy(r_via, B_THETA), TRACK)
    fp.tht("2", *_xy(r_via, B_THETA), VIA, VIA_DRILL)
    seg(pcbnew.B_Cu, _xy(r_via, B_THETA), _xy(PAD_R, B_THETA), UNDER)
    fp.smd("2", *_xy(PAD_R, B_THETA), 2.0, 1.6, rot=B_THETA, paste=False, layer="B")

    fp.fp.AddNetTiePadGroup("1,2")
    # courtyard: one keyhole outline (outer circle, a 0.1 slit at theta 90, inner circle back), so the plate's
    # middle stays free for the locating holes -- two concentric circles would read as a filled disc
    ro, ri, n = R_OUT_EDGE + 0.1, PAD_R - 1.1, 180
    ring = [_xy(ro, 90.5 + 359.0 * i / n) for i in range(n + 1)] +            [_xy(ri, 89.5 - 359.0 * i / n + 360.0) for i in range(n + 1)]
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        c = pcbnew.PCB_SHAPE(fp.fp)
        c.SetShape(pcbnew.SHAPE_T_POLY)
        c.SetPolyPoints([fpgen._v(*q) for q in ring])
        c.SetLayer(layer)
        c.SetWidth(fpgen.MM(0.05))
        c.SetFilled(False)
        fp.fp.Add(c)
    for (x, y), t in ((_xy(PAD_R - 2.3, A_THETA), "A"), (_xy(PAD_R - 2.3, B_THETA), "B")):
        s = pcbnew.PCB_TEXT(fp.fp)
        s.SetText(t)
        s.SetPosition(fpgen._v(x, y))
        s.SetLayer(pcbnew.B_SilkS)
        s.SetMirrored(True)
        s.SetTextSize(pcbnew.VECTOR2I(fpgen.MM(1.0), fpgen.MM(1.0)))
        s.SetTextThickness(fpgen.MM(0.15))
        fp.fp.Add(s)
    fp.save(lib_dir)


def build(d):
    d.sheet(*SHEET)
    d.group("Coil",
            f"{TURNS} turns, {TRACK} mm / {PITCH - TRACK:.3f} mm gap, r {R_IN_EDGE}-{R_OUT_EDGE} (study 3.3).  ~1.41 uH bare,\n"
            "more over the IFL05K.  Ends on B.Cu pads A (theta 210) and B (theta 190) at r 23: wire or spring them\n"
            "to bench_nfc_base's W1/W2, which sit directly under them.")
    d.add("L1", "dial_spinner:NFC_Coil", "NFC coil 4T", COIL_FP, pins={"A": "COIL_A", "B": "COIL_B"},
          in_bom=False, description="PCB coil: copper only, nothing to assemble")
