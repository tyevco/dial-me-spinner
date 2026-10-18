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
from sheets import SHEETS  # noqa: E402

PROJECT = "dial-me-spinner"
LIB = "dial_spinner"
DEFAULT_OUT = os.path.join(HW, "kicad")


def load_modules(only=None):
    mods = []
    for name in SHEETS:
        if only and name not in only:
            continue
        mods.append(importlib.import_module(f"sheets.{name}"))
    return mods


def build_libraries(mods, out):
    libdir = os.path.join(out, "lib")
    os.makedirs(libdir, exist_ok=True)
    sym_path = os.path.join(libdir, LIB + ".kicad_sym")
    fp_dir = os.path.join(libdir, LIB + ".pretty")
    syms, seen = [], set()
    for m in load_modules():  # always build the full library so every sheet resolves
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


def make_design(mods):
    d = schgen.Design(PROJECT, "dial-me-spinner — BLE dial spinner", nets.REV, nets.DATE, "dial-me-spinner")
    d.power(*nets.POWER_NETS)
    d.root_notes = list(getattr(nets, "ROOT_NOTES", []))
    for m in mods:
        m.build(d)
    return d


def erc(out):
    sch = os.path.join(out, PROJECT + ".kicad_sch")
    rpt = os.path.join(out, "erc.rpt")
    subprocess.run(["kicad-cli", "sch", "erc", "--severity-all", "-o", rpt, sch], capture_output=True, text=True)
    counts = {}
    with open(rpt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("["):
                key = line.split("]")[0] + "]"
                counts[key] = counts.get(key, 0) + 1
    return rpt, counts


def netlist(out):
    sch = os.path.join(out, PROJECT + ".kicad_sch")
    path = os.path.join(out, PROJECT + ".net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", path, sch], check=True, capture_output=True)
    return path


def render(out, dpi=110):
    """Schematic -> PDF -> one PNG per sheet (for visual review)."""
    sch = os.path.join(out, PROJECT + ".kicad_sch")
    rdir = os.path.join(out, "render")
    os.makedirs(rdir, exist_ok=True)
    pdf = os.path.join(rdir, PROJECT + "-schematic.pdf")
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", pdf, sch], check=True, capture_output=True)
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, os.path.join(rdir, "sheet")], check=True)
    return rdir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--no-erc", action="store_true")
    ap.add_argument("--render", action="store_true", help="also export PDF + PNG per sheet")
    a = ap.parse_args()
    libs = build_libraries(load_modules(), a.out)
    mods = load_modules(a.only)
    d = make_design(mods)
    errs = d.check()
    if a.only:
        errs = [e for e in errs if not any(f"net {n} has only one" in e for n in nets.INTERSHEET)]
    for e in errs:
        print("CHECK:", e)
    d.write(a.out, extra_sym_libs=libs["sym"], extra_fp_libs=libs["fp"])
    print("schematic written to", a.out)
    if not a.no_erc:
        rpt, counts = erc(a.out)
        print("ERC:", counts or "clean", "->", rpt)
        print("netlist:", netlist(a.out))
    if a.render:
        print("render:", render(a.out))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
