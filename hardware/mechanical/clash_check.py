#!/usr/bin/env python3
"""CGAL interference check of dial_spinner.scad (OpenSCAD 2021.01).

    python3 clash_check.py [margin_mm] [-j N]      (check_clashes.sh calls this)

Checks, each as an OpenSCAD intersection exported to STL (empty = no clash):
  rotor  every stationary item vs the rotor's swept envelope (grown by margin)
  press  base items vs the floating assembly + rotor moved down by STOP_TRAVEL (0.50)
  rest   base items vs the floating assembly + rotor at rest
  pair   FA-internal pairs: board-bottom parts vs actuator / hub / harness / coax, harness and
         coax vs everything they pass, board-top parts vs bracket / light box / cover
Per-part names for board-part clashes come from calcs.py section 11 (analytic, exact for the
rotor and the hub, sampled for the actuator).
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCAD = os.path.join(HERE, "dial_spinner.scad")
src = open(SCAD).read()
m = re.search(r"STATIONARY_NAMES\s*=\s*\[(.*?)\];", src, re.S)
NAMES = re.findall(r'"([^"]+)"', m.group(1))
IDX = {n: i for i, n in enumerate(NAMES)}
BASE = ["base_cup", "base_board", "base_parts", "battery", "battery_leads", "antenna", "guide_pins"]
PAIRS = [
    ("main_bottom_parts", "detent@click"), ("main_bottom_parts", "detent@free"),
    ("main_bottom_parts", "hub+nut"), ("main_bottom_parts", "harness"), ("main_bottom_parts", "coax"),
    ("main_top_parts", "oled_bracket"), ("main_top_parts", "light_box"), ("main_top_parts", "top_cover"),
    ("main_top_parts", "hub+nut"),
    ("harness", "hub+nut"), ("harness", "lower_spacer"), ("harness", "fa_lower_plate"), ("harness", "spindle+pad"),
    ("harness", "detent@click"), ("harness", "detent@free"), ("harness", "base_cup"),
    ("coax", "hub+nut"), ("coax", "lower_spacer"), ("coax", "fa_lower_plate"), ("coax", "spindle+pad"),
    ("coax", "detent@click"), ("coax", "detent@free"), ("coax", "base_cup"), ("coax", "base_parts"),
    ("coax", "base_board"), ("battery_leads", "base_cup"), ("battery_leads", "guide_pins"),
    ("battery_leads", "fa_lower_plate"),
    ("detent@click", "hub+nut"), ("detent@free", "hub+nut"), ("oled_bracket", "hub+nut"),
    ("detent@click", "main_board"), ("detent@free", "main_board"),
]


def stl_volume(path):
    v = 0.0
    tri = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln.startswith("vertex"):
                tri.append(tuple(map(float, ln.split()[1:4])))
                if len(tri) == 3:
                    a, b, c = tri
                    tri = []
                    v += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                          + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
    return abs(v)


def run(job, margin, tmp):
    mode, a, b = job
    out = os.path.join(tmp, f"{mode}_{a}_{b}.stl".replace("@", "_").replace("+", "_"))
    args = ["openscad", "-o", out, "-D", 'view="clash_geom"', "-D", f'clash_mode="{mode}"',
            "-D", f"clash_item={IDX[a]}", "-D", f"clash_b={IDX[b] if b else -1}", "-D", f"clash_margin={margin}",
            "-D", "fn_big=96", "-D", "fn_mid=48", "-D", "show_knurl=false", SCAD]
    p = subprocess.run(args, capture_output=True, text=True)
    log = p.stdout + p.stderr
    label = f"{mode:5s}  {a}" + (f"  x  {b}" if b else "")
    if re.search(r"top level object is empty|No top level geometry", log, re.I):
        return f"CLEAR  {label}"
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return f"CLASH  {label}  overlap ~ {stl_volume(out):.3f} mm^3"
    return f"??     {label}  ({log.strip().splitlines()[-1] if log.strip() else 'no output'})"


def main():
    margin = 0.0
    jobs_n = 4
    argv = sys.argv[1:]
    if "-j" in argv:
        jobs_n = int(argv[argv.index("-j") + 1])
        del argv[argv.index("-j"):argv.index("-j") + 2]
    if argv:
        margin = float(argv[0])
    jobs = [("rotor", n, None) for n in NAMES]
    if margin == 0:
        jobs += [("press", n, None) for n in BASE] + [("rest", n, None) for n in BASE if n != "guide_pins"]
        jobs += [("pair", a, b) for a, b in PAIRS]
    with tempfile.TemporaryDirectory() as tmp, cf.ThreadPoolExecutor(jobs_n) as ex:
        res = list(ex.map(lambda j: run(j, margin, tmp), jobs))
    order = {"rotor": 0, "press": 1, "rest": 2, "pair": 3}
    res.sort(key=lambda s: (order.get(s.split()[1], 9), s.split()[0] != "CLASH", s))
    print("\n".join(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
