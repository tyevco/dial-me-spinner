#!/usr/bin/env python3
"""Produce fabrication + review outputs for each board into hardware/fab/<board>/.

usage: python3 hardware/design/release.py [--board main|base]

Outputs: gerbers.zip (+ gerbers/), JLCPCB BOM + CPL CSVs, schematic PDF,
board PDFs (copper/silk per side), and 3D renders (top/bottom).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HW, "tools"))

import fab  # noqa: E402

BOARDS = {"main": 4, "base": 2}


def render3d(pcb, png, side, zoom=1.0):
    cmd = ["kicad-cli", "pcb", "render", "-o", png, "--width", "1400", "--height", "1400", "--side", side,
           "--background", "opaque", "--quality", "high", "--zoom", str(zoom), pcb]
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    subprocess.run(cmd, capture_output=True, timeout=600)
    return png


def board_pdf(pcb, pdf, layers):
    subprocess.run(["kicad-cli", "pcb", "export", "pdf", "--layers", ",".join(layers), "--mode-single",
                    "--include-border-title", "-o", pdf, pcb], capture_output=True)
    return pdf


def sync_fields(pcb, net):
    """Copy value/MPN/LCSC/Manufacturer from the (re-exported) netlist onto the board footprints."""
    import pcbnew
    import pcbgen
    comps, _ = pcbgen.load_netlist(net)
    b = pcbnew.LoadBoard(pcb)
    changed = 0
    for fp in b.GetFootprints():
        c = comps.get(fp.GetReference())
        if not c:
            continue
        if fp.GetValue() != c["value"]:
            fp.SetValue(c["value"])
            changed += 1
        for k in ("MPN", "LCSC", "Manufacturer"):
            v = c["fields"].get(k)
            current = fp.GetFieldText(k) if fp.HasFieldByName(k) else None
            if v and current != v:
                fp.SetField(k, v)
                fld = fp.GetFieldByName(k)
                if fld:
                    fld.SetVisible(False)
                changed += 1
    if changed:
        pcbnew.SaveBoard(pcb, b)
    return changed


def release(board):
    kdir = os.path.join(HW, "kicad", board)
    proj = f"dial-me-spinner-{board}"
    pcb = os.path.join(kdir, proj + ".kicad_pcb")
    sch = os.path.join(kdir, proj + ".kicad_sch")
    net = os.path.join(kdir, proj + ".net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", net, sch], check=True, capture_output=True)
    print(f"[{board}] synced {sync_fields(pcb, net)} footprint fields from the schematic")
    out = os.path.join(HW, "fab", board)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    tmp = os.path.join(out, ".tmp")
    os.makedirs(tmp)
    fab.gerbers(pcb, out, BOARDS[board])
    fab.jlc_bom(net, os.path.join(out, f"{proj}-BOM-JLCPCB.csv"))
    fab.jlc_cpl(pcb, os.path.join(out, f"{proj}-CPL-JLCPCB.csv"), tmp)
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", os.path.join(out, f"{proj}-schematic.pdf"), sch],
                   capture_output=True)
    cu = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"] if BOARDS[board] == 4 else ["F.Cu", "B.Cu"]
    board_pdf(pcb, os.path.join(out, f"{proj}-top.pdf"), ["F.Cu", "F.Silkscreen", "F.Fab", "Edge.Cuts"])
    board_pdf(pcb, os.path.join(out, f"{proj}-bottom.pdf"), ["B.Cu", "B.Silkscreen", "B.Fab", "Edge.Cuts"])
    for layer in cu:
        board_pdf(pcb, os.path.join(out, f"{proj}-{layer.replace('.', '_')}.pdf"), [layer, "Edge.Cuts"])
    render3d(pcb, os.path.join(out, f"{proj}-3d-top.png"), "top")
    render3d(pcb, os.path.join(out, f"{proj}-3d-bottom.png"), "bottom")
    shutil.rmtree(tmp)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS))
    a = ap.parse_args()
    for b in BOARDS:
        if a.board and b != a.board:
            continue
        print(f"[{b}] ->", release(b))


if __name__ == "__main__":
    main()
