#!/usr/bin/env python3
"""Generate the dial-me-spinner KiCad schematic (and libraries) from the sheet modules.

usage: python3 hardware/design/build.py [--only SHEET ...] [--out DIR] [--no-erc]
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HW, "tools"))
sys.path.insert(0, HERE)

import fpgen  # noqa: E402
import schgen  # noqa: E402
import symgen  # noqa: E402
import symlib  # noqa: E402

import nets  # noqa: E402
from sheets import PROJECTS  # noqa: E402

LIB = "dial_spinner"
DEFAULT_OUT = os.path.join(HW, "kicad")
TITLES = {"main": "dial-me-spinner main board", "base": "dial-me-spinner base board"}


def project_name(board):
    return f"dial-me-spinner-{board}"


def load_modules(names):
    return [importlib.import_module(f"sheets.{n}") for n in names]


def build_libraries(mods, out):
    libdir = os.path.join(out, "lib")
    os.makedirs(libdir, exist_ok=True)
    sym_path = os.path.join(libdir, LIB + ".kicad_sym")
    fp_dir = os.path.join(libdir, LIB + ".pretty")
    syms, seen = [], set()
    for m in mods:
        for spec in getattr(m, "SYMBOLS", []):
            if spec["name"] in seen:
                continue
            seen.add(spec["name"])
            syms.append(symgen.box_symbol(**spec))
        if hasattr(m, "footprints"):
            m.footprints(fpgen, fp_dir)
    symgen.write_library(sym_path, syms)
    symlib.register_library(LIB, sym_path)
    return {
        "sym": {LIB: "${KIPRJMOD}/lib/" + LIB + ".kicad_sym"},
        "fp": {LIB: "${KIPRJMOD}/lib/" + LIB + ".pretty"},
    }


def make_design(board, mods):
    d = schgen.Design(project_name(board), TITLES[board], nets.REV, nets.DATE, "dial-me-spinner")
    d.power(*nets.POWER_NETS)
    d.root_notes = list(getattr(nets, "ROOT_NOTES", []))
    for m in mods:
        m.build(d)
    return d


def erc(out, project):
    sch = os.path.join(out, project + ".kicad_sch")
    rpt = os.path.join(out, "erc.rpt")
    subprocess.run(["kicad-cli", "sch", "erc", "--severity-all", "-o", rpt, sch], capture_output=True, text=True)
    counts = {}
    with open(rpt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("["):
                key = line.split("]")[0] + "]"
                counts[key] = counts.get(key, 0) + 1
    return rpt, counts


def netlist(out, project):
    sch = os.path.join(out, project + ".kicad_sch")
    path = os.path.join(out, project + ".net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", path, sch], check=True, capture_output=True)
    return path


def render(out, project, dpi=110):
    """Schematic -> PDF -> one PNG per sheet (for visual review)."""
    sch = os.path.join(out, project + ".kicad_sch")
    rdir = os.path.join(out, "render")
    os.makedirs(rdir, exist_ok=True)
    pdf = os.path.join(rdir, project + "-schematic.pdf")
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", pdf, sch], check=True, capture_output=True)
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, os.path.join(rdir, "sheet")], check=True)
    return rdir


def build_board(board, sheets, out, run_erc=True, do_render=False, partial=False):
    mods = load_modules(sheets)
    libs = build_libraries(mods, out)
    d = make_design(board, mods)
    errs = d.check()
    if partial:
        errs = [e for e in errs if not any(f"net {n} has only one" in e for n in nets.INTERSHEET)]
    for e in errs:
        print(f"[{board}] CHECK:", e)
    d.write(out, extra_sym_libs=libs["sym"], extra_fp_libs=libs["fp"])
    project = project_name(board)
    print(f"[{board}] schematic written to", out)
    if run_erc:
        rpt, counts = erc(out, project)
        print(f"[{board}] ERC:", counts or "clean", "->", rpt)
        print(f"[{board}] netlist:", netlist(out, project))
    if do_render:
        print(f"[{board}] render:", render(out, project))
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(PROJECTS), help="build one board only")
    ap.add_argument("--only", nargs="*", help="build only these sheets (scratch builds; use --out)")
    ap.add_argument("--out", help="output dir (default hardware/kicad/<board>)")
    ap.add_argument("--no-erc", action="store_true")
    ap.add_argument("--render", action="store_true", help="also export PDF + PNG per sheet")
    a = ap.parse_args()
    errs = []
    for board, sheets in PROJECTS.items():
        if a.board and board != a.board:
            continue
        sel = [s for s in sheets if not a.only or s in a.only]
        if not sel:
            continue
        out = a.out or os.path.join(DEFAULT_OUT, board)
        if a.out and not a.board and len(PROJECTS) > 1 and a.only is None:
            out = os.path.join(a.out, board)
        errs += build_board(board, sel, out, not a.no_erc, a.render, partial=bool(a.only))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
