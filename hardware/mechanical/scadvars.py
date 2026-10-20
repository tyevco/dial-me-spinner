#!/usr/bin/env python3
"""Read the constant table out of dial_spinner.scad.

models.py describes the five machined parts a second time, as exact B-rep solids
instead of a mesh (STEP for the CNC vendor, projected views for the drawings).
Repeating the *numbers* as well would be two sources of truth, so they are parsed
from the .scad here and only the topology is written twice -- which
tests/test_models.py pins down by comparing volumes and bounding boxes against
the STLs OpenSCAD exports from the same constants.

Only top-level `NAME = expr;` assignments above the first module / function are
read, with OpenSCAD's expression subset that overlaps Python (arithmetic, list
literals, indexing, earlier names) plus its degree-based cos/sin/tan.  Anything
else -- `$fn`, strings, vectors spanning several lines -- is skipped, so adding
an exotic constant to the .scad cannot break this; using one in a model will
raise a KeyError, which is the failure mode we want.
"""
import math
import os
import re

SCAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dial_spinner.scad")

_ASSIGN = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(.+?)\s*;\s*$")
_DEF = re.compile(r"^(module|function)\s")
_ENV = {
    "cos": lambda a: math.cos(math.radians(a)),
    "sin": lambda a: math.sin(math.radians(a)),
    "tan": lambda a: math.tan(math.radians(a)),
    "sqrt": math.sqrt, "abs": abs, "min": min, "max": max, "pow": pow, "len": len,
    "PI": math.pi,
}


def load(path=SCAD):
    """{name: value} for every top-level constant dial_spinner.scad defines."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("//")[0].strip()
            if not line:
                continue
            if _DEF.match(line):
                break
            m = _ASSIGN.match(line)
            if not m:
                continue
            name, expr = m.groups()
            try:
                out[name] = eval(expr, {"__builtins__": {}}, dict(_ENV, **out))
            except Exception:
                continue        # not an expression we need; see the module docstring
    return out


if __name__ == "__main__":
    v = load()
    print(f"{len(v)} constants from {SCAD}")
    for k in sorted(v):
        print(f"  {k:<16} {v[k]!r}")
