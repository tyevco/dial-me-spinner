#!/usr/bin/env python3
"""The two bench spacers (bench.scad) against the bench boards they fit (hardware/design/layout.py).

bench.scad repeats a handful of board numbers -- the glass outline, the NFC locating holes, the plate edge --
because OpenSCAD cannot import them.  These tests are what keeps the two copies equal, and they re-check
the panel spacer's feet against the ROUTED shield, so a re-placement that puts a part under a foot fails here
rather than on the bench.

    ~/.venvs/dial-me-spinner/bin/python -m pytest hardware/mechanical/tests -q

Needs KiCad's pcbnew (the board side); skips without it.
"""
import math
import os
import sys

import pytest

pcbnew = pytest.importorskip("pcbnew")

HERE = os.path.dirname(os.path.abspath(__file__))
MECH = os.path.dirname(HERE)
HW = os.path.dirname(MECH)
sys.path.insert(0, MECH)
sys.path.insert(0, os.path.join(HW, "tools"))
sys.path.insert(0, os.path.join(HW, "design"))
import scadvars  # noqa: E402
import layout  # noqa: E402

S = scadvars.load(os.path.join(MECH, "bench.scad"))
SHIELD = os.path.join(HW, "kicad", "bench_display", "dial-me-spinner-bench_display.kicad_pcb")


def test_glass_outline_matches_the_shield_silk():
    assert S["GLASS_D"] == pytest.approx(2 * layout.PANEL_R)
    assert S["GLASS_D"] == pytest.approx(2 * layout.GLASS_R)


@pytest.mark.parametrize("name", ["PLATE_HOLE_R", "PLATE_R"])
def test_nfc_spacer_matches_the_boards(name):
    assert S[name] == pytest.approx(getattr(layout, name))


def test_nfc_spacer_holes_match_the_boards():
    assert list(S["PLATE_HOLES"]) == list(layout.PLATE_HOLES)


def test_panel_spacer_stack():
    """The ring flies over the header plastic, the panel body drops inside the ledge, the glass fits the pocket."""
    assert S["RING_Z0"] > S["HEADER_Z"], "the ring would sit on the header plastic"
    assert 2 * S["LEDGE_RI"] > S["PANEL_BODY_D"], "the panel body would land on the ledge, not the glass"
    assert S["GLASS_D"] < S["POCKET_D"] < S["GLASS_D"] + 0.6
    assert 2 * S["LEDGE_RI"] < S["GLASS_D"], "the glass would fall through"


def test_feet_stay_out_of_the_tail_gap():
    lo, hi = S["TAIL_GAP"]
    for a in S["FOOT_THETA"]:
        assert not lo - 10 <= a <= hi + 10, f"foot at {a} deg is in or beside the tail gap {lo}-{hi}"


def test_feet_land_on_bare_board():
    """Each Ø4 foot clears every courtyard and pad on the routed shield by 0.5 mm, and stays on the board."""
    b = pcbnew.LoadBoard(SHIELD)
    boxes = []
    for fp in b.GetFootprints():
        fp.BuildCourtyardCaches()
        poly = fp.GetCourtyard(pcbnew.F_CrtYd)
        items = [poly.Outline(i).BBox() for i in range(poly.OutlineCount())] + [p.GetBoundingBox() for p in fp.Pads()]
        for bb in items:
            boxes.append((fp.GetReference(), *(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(),
                                                                       bb.GetRight(), bb.GetBottom()))))
    cx, cy = layout.PANEL_C
    r_foot, half = S["FOOT_R"], S["FOOT_D"] / 2
    for a in S["FOOT_THETA"]:
        x, y = cx + r_foot * math.cos(math.radians(a)), cy - r_foot * math.sin(math.radians(a))
        assert layout.SHIELD_X0 + half < x < layout.SHIELD_X0 + layout.SHIELD_W - half
        assert layout.SHIELD_Y0 + half < y < layout.SHIELD_Y0 + layout.SHIELD_H - half
        for ref, l, t, r, bt in boxes:
            d = math.hypot(max(l - x, 0, x - r), max(t - y, 0, y - bt)) - half
            assert d >= 0.5, f"foot at {a} deg is {d:.2f} mm from {ref}"


def test_nfc_spacer_clears_the_coil_contacts_and_the_header():
    """The ring stays inside W1/W2 (r 22-24); the plate tabs keep off their angles and the DK header's."""
    assert S["NFC_RO"] < 22.0
    assert S["TAB_RI"] > S["PLATE_R"]
    assert S["TAB_TOP"] == pytest.approx(S["STACK_GAP"] + S["PLATE_T"])
    for a in S["PLATE_HOLES"]:
        for lo, hi in ((185.0, 215.0), (190.0, 210.0)):   # W1/W2 at 190/210; J2 along 195-205
            assert not lo <= a <= hi, f"tab at {a} deg is over the coil contacts or J2"
