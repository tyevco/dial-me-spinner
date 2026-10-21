#!/usr/bin/env python3
"""Hold the two descriptions of the machined parts together.

models.py rebuilds the five turned / cut metal parts as exact B-rep solids so they
can be exported as STEP and drawn, while dial_spinner.scad still describes them as
a mesh for the assembly views.  That is two descriptions of one geometry, and the
usual way such a pair drifts is silently: someone edits one and the other keeps
rendering happily.  These tests make the drift loud.

    ~/.venvs/dial-me-spinner/bin/python -m pytest hardware/mechanical/tests -q

Needs stl/*.stl, so run export_stl.sh (or render_all.sh) first; the mesh
comparisons skip if a file is missing.  Requires build123d.
"""
import math
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MECH = os.path.dirname(HERE)
sys.path.insert(0, MECH)

import calcs                                        # noqa: E402
import models                                        # noqa: E402

STL = os.path.join(MECH, "stl")

#: An OpenSCAD mesh approximates every round surface with an inscribed polygon, so
#: it under-states added material *and* under-states removed material.  Which way
#: the residual points depends on the part: the spindle is 0.33 % light (mostly
#: outer surfaces, fn_mid = 48 on Ø8), while the ring comes out 0.023 % heavy,
#: because its 48 pockets at fn_small = 24 and 4 balance holes at fn = 12 each cut
#: a shade less than the true cylinder.  So only the magnitude is asserted.
MESH_TOL = 0.005
#: Bounding boxes agree much more closely, but not exactly: an extent set by a
#: facet *vertex* lands on the true surface, while one set by a cut through a
#: faceted surface lands inside it.  The hub's Y extent is the latter -- the Ø17
#: flange chopped at x = ±2.5 by the C-gap -- and sits one facet sagitta
#: (8.5 * (1 - cos(pi/48)) = 0.018) inside the exact 16.624.  A real dimensional
#: error is at least an order of magnitude bigger than this budget.
BBOX_TOL = 0.05


def read_binary_stl(path):
    """(volume mm^3, (dx, dy, dz), triangle count) of a binary STL."""
    with open(path, "rb") as fh:
        fh.read(80)
        n = struct.unpack("<I", fh.read(4))[0]
        data = fh.read(50 * n)
    vol = 0.0
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in range(n):
        v = struct.unpack_from("<12f", data, i * 50)[3:]
        a, b, c = v[0:3], v[3:6], v[6:9]
        # signed volume of the tetrahedron (origin, a, b, c)
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        for p in (a, b, c):
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    return abs(vol), tuple(hi[k] - lo[k] for k in range(3)), n


@pytest.fixture(scope="module")
def exact():
    """name -> (solid, volume, mass, bbox), built once."""
    return {name: models.summary(name) for name in models.PARTS}


@pytest.mark.parametrize("name", list(models.PARTS))
def test_volume_matches_the_mesh(name, exact):
    """The exact solid and the OpenSCAD mesh describe the same part."""
    path = os.path.join(STL, f"{name}.stl")
    if not os.path.exists(path):
        pytest.skip(f"{path} missing: run export_stl.sh")
    mesh_v, _, _ = read_binary_stl(path)
    _, v, _, _ = exact[name]
    assert v == pytest.approx(mesh_v, rel=MESH_TOL), (
        f"{name}: exact {v:.4f} mm^3 vs mesh {mesh_v:.4f} mm^3 "
        f"({100 * (v - mesh_v) / mesh_v:+.3f} %, budget {100 * MESH_TOL:.1f} %)")


@pytest.mark.parametrize("name", list(models.PARTS))
def test_bbox_matches_the_mesh(name, exact):
    path = os.path.join(STL, f"{name}.stl")
    if not os.path.exists(path):
        pytest.skip(f"{path} missing: run export_stl.sh")
    _, mesh_bb, _ = read_binary_stl(path)
    _, _, _, bb = exact[name]
    # print_part() mirrors some parts onto the bed, which preserves every extent but
    # not which axis it is on, so compare the three sizes as a sorted triple.
    assert sorted((bb.size.X, bb.size.Y, bb.size.Z)) == pytest.approx(
        sorted(mesh_bb), abs=BBOX_TOL), f"{name}: exact {bb.size} vs mesh {mesh_bb}"


def test_ring_mass_matches_calcs_section_14(exact):
    """calcs.py's analytic ring, the exact solid and the knurl callout agree.

    calcs.rotor_parts() subtracts the knurl, which models.py does not cut (it is a
    drawing callout, not a modelled feature), so add it back to compare.
    """
    _, _, mass, _ = exact["rotor_ring"]
    v_knurl = 120 * (0.6 ** 2 / 2) * 7.0            # as calcs.rotor_parts()
    analytic = next(m for n, m, _i, _z in calcs.rotor_parts() if n.startswith("316L ring"))
    assert mass - v_knurl * calcs.RHO_316L == pytest.approx(analytic, rel=0.001)


@pytest.mark.parametrize("name", ["RING_RO", "RING_RI", "RING_Z0", "RING_Z1", "CH_TO", "CH_BO",
                                  "CH_IN", "MAG_N", "MAG_D", "MAG_H", "RT", "POCKET_D",
                                  "POCKET_H", "B_Z0", "B_Z1", "MB_Z0", "FA_Z0", "FA_Z1",
                                  "SHIM_RI", "SHIM_RO", "SHIM_T", "SHIM_PLATE_T"])
def test_calcs_constants_match_the_scad(name):
    """calcs.py keeps its own copy of the geometry table; it must not drift either."""
    assert getattr(calcs, name) == pytest.approx(getattr(models.C, name)), (
        f"calcs.{name} = {getattr(calcs, name)} but dial_spinner.scad says "
        f"{getattr(models.C, name)}")


def test_ring_height_constant_is_consistent():
    """calcs.RING_H is written out rather than derived from RING_Z0/RING_Z1."""
    assert calcs.RING_H == pytest.approx(models.C.RING_Z1 - models.C.RING_Z0)


def test_recess_is_exactly_magnet_deep():
    """The magnets bottom on steel, so the detent gap cannot drift with the shim.

    SHIM_T == MAG_H is the whole reason the printed shim does not enter the gap
    tolerance stack: the magnet crown lands flush with the ring's top face whatever
    the shim's printed thickness turns out to be.  mechanical sections 5 and 7.
    """
    assert models.C.SHIM_T == pytest.approx(models.C.MAG_H)
    assert models.C.SHIM_Z0 == pytest.approx(models.C.RING_Z1 - models.C.MAG_H)
    assert models.C.SHIM_PLATE_T < models.C.MAG_H, "the shim must not stand proud of the magnets"


def test_shim_has_printable_walls_and_clears_the_damping_pad():
    """Geometry the recess bounds have to satisfy, and which a tweak could silently break."""
    C = models.C
    wall_o = C.SHIM_RO - (C.RT + C.POCKET_D / 2)
    wall_i = (C.RT - C.POCKET_D / 2) - C.SHIM_RI
    assert wall_o >= 0.9, f"shim outer wall {wall_o:.2f} too thin to print"
    assert wall_i >= 0.9, f"shim inner wall {wall_i:.2f} too thin to print"
    # doc section 7: the felt damping pad lands at r 31.6-32.4 and must stay on bare steel
    assert C.SHIM_RO <= 31.6, f"recess OD {C.SHIM_RO} reaches under the damping pad"


def test_ring_has_no_milled_features():
    """The point of the recess: the flywheel must stay a turning-only part.

    Every face is then either a plane normal to Z or a surface of revolution about it.
    The four balance holes are the one exception -- they are drilled, and on the drawing
    they are a note, not a milled feature -- so they are excluded by radius.
    """
    solid = models.PARTS["rotor_ring"].build()
    for f in solid.faces():
        if abs(f.center().X) > 1e-6 or abs(f.center().Y) > 1e-6:
            continue                       # off-axis: a balance hole
        n = f.normal_at(f.center())
        is_planar = abs(abs(n.Z) - 1.0) < 1e-6
        is_revolved = getattr(f, "radius", None) is not None
        assert is_planar or is_revolved, f"non-turnable face at z {f.center().Z:.2f}"


@pytest.mark.parametrize("name", list(models.PARTS))
def test_solid_is_a_single_watertight_body(name, exact):
    solid, _, _, _ = exact[name]
    assert len(solid.solids()) == 1, f"{name} built {len(solid.solids())} solids"
    assert solid.is_valid, f"{name} is not a valid B-rep"
