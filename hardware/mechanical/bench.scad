// Rev B bench fixtures: the two printed spacers the bench boards need (docs/rev-b-bench.md).
// Not part of the product: dial_spinner.scad models the device, this file only the bench.
//
//   bench_panel_spacer  holds the 1.75" panel face-up 4 mm over the AMOLED shield, glass on a ledge
//   bench_nfc_spacer    holds the NFC coil plate 3.0 mm over the NFC base, pinned through both boards
//
// Board positions are in the shield's own frame: origin at the glass outline's centre, x toward the
// shield's +x, y UP (KiCad's y is down).  tests/test_bench.py holds these constants to layout.py.

part = "bench_panel_spacer";
fn_big = 128;
fn_small = 32;

// ---- panel spacer -------------------------------------------------------------------------------
GLASS_D      = 48.96;     // Huaxin cover glass (Viewe Ø48.16 sits in the same pocket with 0.4 of play)
GLASS_T      = 1.1;       // cover glass, Huaxin drawing side view
PANEL_BODY_D = 46.35;     // bare panel, largest dimension: must pass inside the ledge
GLASS_Z      = 4.0;       // glass underside above the shield top (the 4 mm the silk says)
HEADER_Z     = 2.54;      // male header plastic on the shield's top: the ring flies over it
RING_Z0      = 2.8;       // ring underside: HEADER_Z + 0.26
RING_RO      = 26.5;
LEDGE_RI     = 23.5;      // glass rests on r 23.5-24.6; the panel body (r <= 23.18) hangs inside
POCKET_D     = GLASS_D + 0.4;
LIP_H        = GLASS_T;   // lip flush with the glass top
FOOT_D       = 4.0;
FOOT_R       = 24.5;
// Clear spots on the routed board at r 24.5 about the glass centre, from a scan of every courtyard and
// pad (>= 0.5 mm clear for a Ø4 foot): 0-55, 100-140, 200-230, 305-355 deg.  These three are each
// >= 7 mm from the nearest part.  Theta CCW seen from the top, 0 toward the shield's +x.
FOOT_THETA   = [25, 115, 215];
// The tail folds under at the panel's left edge (theta 180) to reach J2.  Open the ring there.
TAIL_GAP     = [155, 200];

// ---- NFC stack spacer ---------------------------------------------------------------------------
// Prints flat with nothing hanging: M2 x 4 screws from under the base (its Ø2.2 holes) self-tap into the
// spacer's Ø1.6 holes, and the plate drops in between three tabs at its edge.  Pins both ways would need
// support for one set or the other.
PLATE_HOLE_R = 19.0;      // the locating holes in both boards (layout.py PLATE_HOLE_R)
PLATE_HOLES  = [30, 150, 270];
TAP_D        = 1.6;       // M2 self-tapping into printed plastic
PLATE_R      = 26.6;      // coil plate edge (layout.py PLATE_R)
PLATE_T      = 0.4;
FERRITE_T    = 0.24;      // IFL05K with its adhesive, stuck to the plate's bottom
STACK_GAP    = 3.0;       // base top to plate bottom: puts the coil 3.4 over ground copper, as in the device
NFC_H        = STACK_GAP - FERRITE_T;   // the spacer meets the ferrite, not the plate
NFC_RI       = 16.5;
NFC_RO       = 21.5;      // inside the base's coil contacts W1/W2 (r 22-24, theta 190-210)
ARM_W        = 4.0;
TAB_RI       = PLATE_R + 0.1;           // 0.1 radial play around the plate
TAB_RO       = TAB_RI + 1.0;
TAB_TOP      = STACK_GAP + PLATE_T;     // flush with the plate top: the panel sits on the plate, not the tabs
TAB_W        = 20;        // degrees of arc per tab

// ---- modules (constants above: scadvars reads up to the first module) ------------------------------

// An annulus, optionally with the sector gap[0]..gap[1] (degrees, CCW) cut out of it.
module arc_ring(ri, ro, z0, z1, gap = [0, 0]) {
    difference() {
        translate([0, 0, z0]) difference() {
            cylinder(r = ro, h = z1 - z0, $fn = fn_big);
            translate([0, 0, -0.1]) cylinder(r = ri, h = z1 - z0 + 0.2, $fn = fn_big);
        }
        if (gap[1] > gap[0])
            translate([0, 0, z0 - 0.1]) linear_extrude(z1 - z0 + 0.2)
                polygon(concat([[0, 0]], [for (a = [gap[0] : 2.5 : gap[1]]) 2 * ro * [cos(a), sin(a)]]));
    }
}

module bench_panel_spacer() {
    // ring under the glass edge: ledge at GLASS_Z, lip up to the glass top
    arc_ring(LEDGE_RI, RING_RO, RING_Z0, GLASS_Z, TAIL_GAP);
    arc_ring(POCKET_D / 2, RING_RO, GLASS_Z - 0.01, GLASS_Z + LIP_H, TAIL_GAP);   // overlap: one solid
    for (a = FOOT_THETA) rotate(a) translate([FOOT_R, 0, 0])
        cylinder(d = FOOT_D, h = RING_Z0 + 0.01, $fn = fn_small);
}

module bench_nfc_spacer() {
    difference() {
        union() {
            arc_ring(NFC_RI, NFC_RO, 0, NFC_H);
            for (a = PLATE_HOLES) rotate(a) {
                translate([NFC_RO - 0.5, -ARM_W / 2, 0]) cube([TAB_RO - NFC_RO + 0.5, ARM_W, NFC_H]);
                arc_ring(TAB_RI, TAB_RO, 0, TAB_TOP, [TAB_W / 2, 360 - TAB_W / 2]);
            }
        }
        for (a = PLATE_HOLES) rotate(a) translate([PLATE_HOLE_R, 0, -0.1])
            cylinder(d = TAP_D, h = NFC_H + 0.2, $fn = fn_small);
    }
}

// Exported in print orientation: the panel spacer lip-down (the ring then bridges nothing and the feet
// grow upward), the NFC spacer as modelled.
if (part == "bench_panel_spacer") translate([0, 0, GLASS_Z + LIP_H]) mirror([0, 0, 1]) bench_panel_spacer();
else if (part == "bench_nfc_spacer") bench_nfc_spacer();
else if (part == "assembly_panel") bench_panel_spacer();
