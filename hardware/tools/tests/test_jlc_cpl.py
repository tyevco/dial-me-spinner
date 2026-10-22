#!/usr/bin/env python3
"""The JLC pick-and-place file must put every part where the board has its pads.

jlc_cpl.write_cpl simulates JLC's placement of each row (the EasyEDA pads cached in
hardware/design/jlc_offsets.json, put down at the row's point and angle) and refuses
to write a CPL with a pad off copper or on another-numbered pad. These tests hold that
check to the committed boards and show that it catches the mistakes it exists for:
a wrong rotation on a symmetric package, a 90-degree error, and a misplaced origin
(the rev A release had that last one on seven connector/switch rows).

    python3 -m pytest hardware/tools/tests -q

Needs KiCad's pcbnew Python module (not in CI); skips without it.
"""
import csv
import json
import os
import sys

import pytest

pcbnew = pytest.importorskip("pcbnew")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
HW = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import jlc_cpl  # noqa: E402

BOARDS = ("main", "base")


def board(name):
    kdir = os.path.join(HW, "kicad", name)
    return (os.path.join(kdir, f"dial-me-spinner-{name}.kicad_pcb"),
            {"dial_spinner": os.path.join(kdir, "lib", "dial_spinner.pretty")})


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


@pytest.mark.parametrize("name", BOARDS)
def test_released_cpl_is_what_the_checked_writer_makes(name, tmp_path):
    pcb, lib = board(name)
    out = tmp_path / "cpl.csv"
    _, missing, problems, _ = jlc_cpl.write_cpl(pcb, str(out), lib)
    assert not missing and not problems
    assert rows(out) == rows(os.path.join(HW, "fab", name, f"dial-me-spinner-{name}-CPL-JLCPCB.csv"))


@pytest.mark.parametrize("name", BOARDS)
def test_every_part_with_pads_is_simulated(name):
    pcb, _ = board(name)
    table = json.load(open(jlc_cpl.OFFSETS))
    unsimulated = set()
    for fp in pcbnew.LoadBoard(pcb).GetFootprints():
        code = fp.GetFieldText("LCSC") if fp.HasFieldByName("LCSC") else ""
        if code and not fp.IsDNP() and not table.get(code, {}).get("ee"):
            unsimulated.add(code)
    assert unsimulated <= {"C4167968"}  # R26 0402: EasyEDA has no footprint for this code


@pytest.mark.parametrize("name", BOARDS)
def test_simulation_matches_kicad_geometry_both_sides(name):
    """With the KiCad library footprint itself as the 'JLC' footprint (α = 0, origin 0), every simulated pad must
    land on the same-numbered board pad on both sides. This ties the CPL angle formula (top θ, bottom 180 − θ) and
    the placement simulation to KiCad's own rotation and flip."""
    pcb, lib = board(name)
    for fp in pcbnew.LoadBoard(pcb).GetFootprints():
        lib_fp = jlc_cpl._lib_footprint(fp, lib)
        ee = [[p.GetNumber(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)]
              for p in lib_fp.Pads() if p.GetNumber() and p.IsOnCopperLayer()]
        if not ee:
            continue
        th = fp.GetOrientationDegrees()
        ang = (180 - th) if fp.IsFlipped() else th
        res = jlc_cpl.simulate(fp, jlc_cpl._local_to_board(fp, 0.0, 0.0), ang % 360, ee)
        assert all(hit == num for num, hit, _ in res), (fp.GetReference(), res)


@pytest.mark.parametrize("code, change, expect", [
    ("C2681320", {"rot": 0}, "other-numbered"),   # SOT-23-6 turned 180°: every pad still on copper
    ("C841192", {"rot": 90}, "off copper"),       # SOT-23-5 turned 90°
    ("C262671", {"dy": 0.0}, "off copper"),       # OLED FPC connector: JLC origin taken as KiCad's
])
def test_check_catches_wrong_corrections(code, change, expect, tmp_path, monkeypatch):
    table = json.load(open(jlc_cpl.OFFSETS))
    table[code].update(change)
    p = tmp_path / "offsets.json"
    p.write_text(json.dumps(table))
    monkeypatch.setattr(jlc_cpl, "OFFSETS", str(p))
    pcb, lib = board("main")
    with pytest.raises(RuntimeError, match=expect):
        jlc_cpl.write_cpl(pcb, str(tmp_path / "cpl.csv"), lib)
