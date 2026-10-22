#!/usr/bin/env python3
"""Exact B-rep solids for the six machined parts of dial-me-spinner rev A.

dial_spinner.scad is the whole-device model, but OpenSCAD has no geometry
kernel: it can only emit a mesh, and a mesh is not something a machine shop can
quote from -- JLCCNC's uploader rejects STL and asks for STEP, DWG, DXF or PDF.
So the five turned / cut metal parts get a second description here, in build123d
(OpenCascade), which carries exact surfaces: STEP for the vendor and projected
views for drawgen.py's drawings.  The magnet shim is the sixth, and the only one
that is not metal: it is printed, but its 48 bores and its OD are *machined*, and
a mesh cannot carry +0.01/-0.00 or a true-position callout any better for a
plastic part than for a steel one.

Dimensions are read from dial_spinner.scad by scadvars, so this file repeats only
the *topology*, and tests/test_models.py holds the two descriptions together by
comparing every solid's volume and bounding box against the STL that OpenSCAD
exports from the same constants (plus the ring's mass against mechanical §14).

Solids are built in **assembly coordinates** -- the same z values as the .scad
modules, so the two can be read side by side.  on_bed() drops a part to
bottom-face-on-origin, which is what the STEP files and the drawings use.

    python3 models.py          # build all six and print volume / mass / bbox
"""
import math
from types import SimpleNamespace

from build123d import (Axis, Box, BuildLine, BuildPart, BuildSketch, Cylinder, Plane,
                       Polyline, Pos, Rot, make_face, revolve)

import scadvars
from calcs import RHO_316L, RHO_BRASS, RHO_PA12GF

C = SimpleNamespace(**scadvars.load())

# Cutter sizes that dial_spinner.scad spells out inside the metal modules rather
# than in its constant table; everything dimensional comes from scadvars.
SLOT_CUT_LEN = 12.0        # radial_slot() reach: well past the outer radius
FLAT_CUT = 10.0            # dflat_keep() cutter depth / half-width


# ---------------------------------------------------------------------------
# dial_spinner.scad's helper modules, as exact solids
# ---------------------------------------------------------------------------
def _tube(ro, ri, z0, z1):
    """scad tube(ro, ri, z0, z1)."""
    zc, h = (z0 + z1) / 2, z1 - z0
    return Pos(0, 0, zc) * Cylinder(ro, h) - Pos(0, 0, zc) * Cylinder(ri, h)


def _disc(d, z0, h):
    """A diameter-d cylinder spanning z0..z0+h."""
    return Pos(0, 0, z0 + h / 2) * Cylinder(d / 2, h)


def _at_polar(solid, r, a_deg, z):
    """scad at_polar(r, a, z), without the local rotation (all callers are round)."""
    a = math.radians(a_deg)
    return Pos(r * math.cos(a), r * math.sin(a), z) * solid


def _radial_slot(a_deg, w, z0, z1, length=SLOT_CUT_LEN):
    """scad radial_slot(a, w, z0, z1, len): a w-wide box from the axis outward."""
    return Rot(0, 0, a_deg) * Pos(length / 2, 0, (z0 + z1) / 2) * Box(length, w, z1 - z0)


def _dflat_keep(a_deg, r, depth, z0, z1):
    """scad dflat_keep(a, r, depth, z0, z1): removes material beyond r - depth."""
    return (Rot(0, 0, a_deg) * Pos(r - depth + FLAT_CUT / 2, 0, (z0 + z1) / 2)
            * Box(FLAT_CUT, 2 * FLAT_CUT, z1 - z0))


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------
def ring_profile():
    """The 8-point turned profile of the flywheel ring, as (r, z) pairs."""
    return [(C.RING_RI + C.CH_IN, C.RING_Z0), (C.RING_RO - C.CH_BO, C.RING_Z0),
            (C.RING_RO, C.RING_Z0 + C.CH_BO), (C.RING_RO, C.RING_Z1 - C.CH_TO),
            (C.RING_RO - C.CH_TO, C.RING_Z1), (C.RING_RI + C.CH_IN, C.RING_Z1),
            (C.RING_RI, C.RING_Z1 - C.CH_IN), (C.RING_RI, C.RING_Z0 + C.CH_IN)]


def _revolve_profile(points):
    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline(*points, close=True)
            make_face()
        revolve(axis=Axis.Z)
    return part.part


def rotor_ring():
    """316L flywheel: revolved profile, one turned shim recess, 4 balance holes.

    The 48 magnets are not pockets in the steel any more -- they sit in a printed shim
    (dial_spinner.scad `magnet_shim`) that drops into this recess.  That is the whole
    point of the recess: it leaves the flywheel a turning-only part, which took the
    JLCCNC quote from $71.45 to $52.49 (mechanical section 13).
    """
    s = _revolve_profile(ring_profile())
    s -= Pos(0, 0, C.SHIM_Z0 + C.SHIM_T / 2) * Cylinder(C.RECESS_RO, C.SHIM_T)
    for a in range(45, 360, 90):
        s -= _at_polar(Cylinder(C.BAL_D / 2, C.BAL_DEPTH), C.BAL_R, a,
                       C.RING_Z0 + C.BAL_DEPTH / 2)
    return s


def spindle():
    """316L spindle: Ø8 tube, M4 spigot, keyed flange, two wire slots, two D-flats."""
    s = _disc(C.SP_OD, C.SP_Z0, C.SP_Z1 - C.SP_Z0)
    s += _disc(C.SPIGOT_D, C.SP_Z1, C.SPIGOT_Z1 - C.SP_Z1)
    flange = _disc(C.SP_FL_D, C.SP_Z0, C.SP_FL_T)
    flange -= _dflat_keep(90, C.SP_FL_D / 2, C.FLAT_DEPTH, C.SP_Z0, C.SP_Z0 + C.SP_FL_T)
    s += flange
    s -= _disc(C.SP_ID, C.SP_BORE_Z0, C.SP_BORE_Z1 - C.SP_BORE_Z0)
    s -= _disc(C.SP_RELIEF_D, C.SP_Z0, C.SP_RELIEF_H)
    s -= _disc(C.PAD_POCKET_D, C.SP_Z0 + C.SP_RELIEF_H, C.PAD_POCKET_H)
    s -= _radial_slot(C.BOT_SLOT_A, C.SLOT_W, *C.BOT_SLOT_Z)
    s -= _radial_slot(C.TOP_SLOT_A, C.SLOT_W, *C.TOP_SLOT_Z)
    for z0, z1 in ((C.FA_Z0, C.B_Z0), (C.B_Z1, C.SP_Z1)):
        s -= _dflat_keep(90, C.SP_OD / 2, C.FLAT_DEPTH, z0, z1)
    return s


def lower_spacer():
    """C360 brass: inner-race spacer with the drop-stop flange and a wire window."""
    s = _tube(C.LS_RO, C.SP_OD / 2, C.FA_Z1, C.B_Z0)
    s += _tube(C.LS_FL_RO, C.SP_OD / 2, C.LS_FL_Z0, C.LS_FL_Z1)
    s -= _radial_slot(C.BOT_SLOT_A, C.SLOT_W, C.FA_Z1, C.BOT_SLOT_Z[1])
    return s


def spindle_hub():
    """C360 brass: upper inner-race spacer, Ø17 flange, 3x M2 tapped, C-gap."""
    s = _tube(C.LS_RO, C.SP_OD / 2, C.B_Z1, C.HUB_FL_Z0)
    s += _tube(C.HUB_FL_RO, C.SP_OD / 2, C.HUB_FL_Z0, C.MB_Z0)
    for a in C.HUB_SCREW_A:
        s -= _at_polar(Cylinder(C.HUB_TAP_D / 2, C.HUB_TAP_H), C.HUB_SCREW_R, a,
                       C.MB_Z0 - C.HUB_TAP_H / 2)
    s -= _radial_slot(C.TOP_SLOT_A, C.SLOT_W, C.B_Z1, C.MB_Z0)
    return s


def cap_ring():
    """0.5 mm 316 sheet washer bonded on the carrier collar."""
    return _tube(C.COLLAR_RO, C.CAP_RI, C.CAP_Z[0], C.CAP_Z[1])


def magnet_shim():
    """PA12-GF plate carrying the 48 magnets: printed solid, bores and OD machined.

    The one part here that is not metal, and it earns a drawing for exactly the
    reason the metal ones do.  A printed hole holds +/-0.3 mm at JLC3DP's published
    figure, so a 2.10 nominal spans 1.80-2.40: at the top it leaves 0.225 mm of
    float and at the bottom it refuses a 1.95 mm magnet outright.  There is no
    printed nominal that both admits the magnet and locates it, which is why the
    blank is printed solid and the bores are reamed (mechanical section 5).
    """
    s = _tube(C.SHIM_RO, C.SHIM_RI, C.SHIM_Z0, C.SHIM_Z0 + C.SHIM_PLATE_T)
    for i in range(int(C.MAG_N)):
        s -= _at_polar(Cylinder(C.BORE_D / 2, C.SHIM_PLATE_T + 0.2), C.RT,
                       i * 360.0 / C.MAG_N, C.SHIM_Z0 + C.SHIM_PLATE_T / 2)
    return s


# ---------------------------------------------------------------------------
# Registry: what drawgen.py and the tests need to know about a part
# ---------------------------------------------------------------------------
def _part(name, number, material, density, build, stock, process, notes):
    return SimpleNamespace(name=name, number=number, material=material, density=density,
                           build=build, stock=stock, process=process, notes=notes)


#: name -> metadata.  `number` is the mechanical §13 BOM line, so a drawing and a
#: purchase order name the same thing.  `notes` carry what a solid cannot: finish,
#: threads, fits, knurl and the general tolerance.
PARTS = {p.name: p for p in (
    _part("rotor_ring", "DMS-07", "316L stainless", RHO_316L, rotor_ring,
          "Ø74 bar or ring forging", "turn",
          ["TURNING ONLY -- no milled features. Straight knurl on the OD, 1.5 to",
           "8.5 from the bottom face (flick grip).",
           "The recess seats the printed magnet shim, and its floor is the magnet",
           "seat: face it flat and square to 0.02 and hold the depth +0.02/-0.00,",
           "because that is what sets the 1.0 mm detent and sensor gap.",
           "The top face OUTSIDE the recess is the encoder datum and the damping-pad",
           "land: flat and square to 0.02, runout 0.05 TIR.",
           "316L required. 304 can become weakly magnetic after cold working and the",
           "track runs 1.0 mm under a Hall sensor: check the blank with an N52 magnet."]),
    _part("spindle", "DMS-08", "316L stainless", RHO_316L, spindle,
          "Ø12 bar", "turn / mill",
          ["Ø8 journal h6 over the bearing seat, 5.2 to 12.2 from the bottom face.",
           "Spigot thread M4 x 0.5 (fine), full length above the shoulder.",
           "Bore Ø6.00 from 1.65 to 15.45; 0.8 mm end wall under the spigot.",
           "One flat plane 3.70 off the axis over 0.0-5.2 and 12.2-16.25: the two",
           "flats are COPLANAR, which is what keys the plate, spacer and hub to each",
           "other. 0.3 deep on the Ø8 journal, 1.3 deep where it crosses the flange.",
           "Slots 5.0 wide break through into the bore; deburr inside the bore.",
           "316L required, non-magnetic: check the blank with an N52 magnet."]),
    _part("spindle_hub", "DMS-09", "C360 brass", RHO_BRASS, spindle_hub,
          "Ø18 bar", "turn / mill",
          ["3x M2 x 0.4 tapped 2.6 deep from the flange top face. Tapped, not",
           "heat-set: the 0.4 mm wall around an insert would split.",
           "C-gap 5.0 wide through the full height, for the harness.",
           "The flange top face is the main-board seat: flat within 0.05.",
           "OPEN: the bore is drawn round. Mechanical 13 calls for a D-bore on the",
           "spindle flat (3.70 off axis) to key it; the model has not got it yet."]),
    _part("lower_spacer", "DMS-10", "C360 brass", RHO_BRASS, lower_spacer,
          "Ø22 bar", "turn / mill",
          ["The top face clamps the 608 inner race: flat and square within 0.03.",
           "The flange is the rotor drop stop.",
           "5.0 window through the boss wall for the harness.",
           "OPEN: the bore is drawn round. Mechanical 13 calls for a D-bore on the",
           "spindle flat (3.70 off axis) to key it; the model has not got it yet."]),
    _part("cap_ring", "DMS-04", "316 stainless", RHO_316L, cap_ring,
          "0.5 mm sheet", "laser cut / shim washer",
          ["0.5 mm 316 sheet, laser-cut; a stock shim washer of these sizes also works.",
           "Flatness matters more than edge finish: it runs against a wave washer.",
           "Non-magnetic."]),
    _part("magnet_shim", "DMS-07A", "PA12-GF (SLS)", RHO_PA12GF, magnet_shim,
          "printed blank", "print solid, then ream / turn",
          ["DO NOT PRINT THE BORES OR THE OD. Print the blank solid and machine",
           "both: a printed hole holds +/-0.3 at best, which cannot locate a",
           "magnet and at the low end will not admit one.",
           "Hold on the printed ID to turn the OD, then take the bore pattern",
           "from the OD, so the pattern and datum B share one setup.",
           "THE BORES LOCATE THE MAGNETS. Ream against a diameter-sorted lot",
           "(bin 1.99-2.00) for 0.015-0.037 radial clearance.",
           "Bond the magnets alternating N/S, centred on a mandrel in the RING",
           "ID, not on the recess wall: pattern eccentricity is a 1/rev encoder",
           "error. Keep the part and the magnets below 60 C at every stage."]),
)}


def on_bed(solid):
    """Drop a solid to bottom-face-on-origin: the STEP and drawing pose.

    Z only.  All six parts are turned or cut about Z, so X and Y stay as modelled
    and the axis of revolution stays on the origin -- which is what a lathe
    drawing and a STEP file both want.  Centring the bounding box in XY instead
    would shift the axis by half of any asymmetry (0.5 mm on the spindle, whose
    flange is round but D-flatted on one side).
    """
    return Pos(0, 0, -solid.bounding_box().min.Z) * solid


def summary(name):
    """(solid on the bed, volume mm^3, mass g, bbox) for one part."""
    p = PARTS[name]
    solid = on_bed(p.build())
    return solid, solid.volume, solid.volume * p.density, solid.bounding_box()


if __name__ == "__main__":
    print(f"{'part':<14}{'material':<17}{'vol cm3':>9}{'mass g':>9}   bbox (mm)")
    for name in PARTS:
        solid, v, m, bb = summary(name)
        print(f"{name:<14}{PARTS[name].material:<17}{v / 1000:>9.4f}{m:>9.3f}   "
              f"{bb.size.X:.3f} x {bb.size.Y:.3f} x {bb.size.Z:.3f}  "
              f"({len(solid.faces())} faces)")
