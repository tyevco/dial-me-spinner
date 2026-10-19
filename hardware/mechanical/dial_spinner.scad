// =====================================================================
//  dial-me-spinner rev A  --  parametric mechanical model (OpenSCAD 2021.01)
// =====================================================================
//  Follows hardware/design/SPEC.md section 8 (stack-up).  Frame:
//    z = 0 is the desk, z up.  theta = 0 deg is the USB-C direction (+X),
//    angles increase counter-clockwise seen from +Z.  Units: mm.
//  Where this model deviates from SPEC (because SPEC is not buildable as
//  written) the constant is marked  "DEV:"  and explained in docs/mechanical.md.
//
//  Views  (-D 'view="..."'):
//    assembly      full device
//    section       cut on the YZ plane (x = 0): detent carriage, TMAG, battery
//    section_xz    cut on the XZ plane (y = 0): USB-C, antenna, guide pin
//    exploded      exploded along Z (scale with -D explode=1)
//    board_bottom  main board + everything hanging under it, seen from below
//    clash         rotor swept envelope (red) and press-travel overlap (orange)
//                  against all stationary parts, assembly ghosted
//    clash_geom    geometry only (use with -o x.stl; empty result = no clash)
//    part          one printable part, on the bed, for STL export:
//                  -D 'part="base_cup"'  (see part_list below)
//
//  Other switches: det_offset (0 = click, 7.5 = free spin), press (0..1),
//  clash_margin, show_knurl, show_board_parts.
// =====================================================================

/* [View] */
view = "assembly";
part = "base_cup";
det_offset = 0.0;       // detent carriage radial offset, mm (0 = full click .. 7.5 = free)
press = 0.0;            // 0..1, fraction of STOP_TRAVEL the floating assembly is pushed down
explode = 1.0;          // exploded-view scale
clash_margin = 0.0;     // grow the rotor envelope by this (mm) in the clash check
clash_item = -1;        // clash_geom: -1 = all, else index into the stationary list
clash_mode = "rotor";   // clash_geom: "rotor" or "press"
show_knurl = true;
show_board_parts = true;
fn_big = 144;
fn_mid = 64;
fn_small = 24;

// ------------------------------------------------------------------
//  SPEC section 8 stack-up (z ranges and radii)
// ------------------------------------------------------------------
R_OD        = 35.0;     // overall diameter 70
// feet: SPEC "3x rubber/micro-suction feet, r = 28, z 0-1"
FOOT_Z1     = 1.0;
FOOT_RC     = 28.0;
FOOT_RW     = 6.0;      // radial width of each pad (r 25..31)
FOOT_ARC    = 70;       // DEV: pads are 70 deg arcs, not points (tipping, see doc)
FOOT_ANG    = [0, 120, 240];
// base cup: floor z 1.0-2.5, OD 70, wall 1.6, wall top z 14.3
CUP_Z0      = 1.0;
CUP_FLOOR   = 2.5;
CUP_WALL    = 1.6;
CUP_TOP     = 14.3;
CUP_RI      = R_OD - CUP_WALL;      // 33.4
// LiPo bay z 2.5-9.0, protected 603450-class pack <= 6.3 thick, long axis 90/270
BAT_Z0      = 2.5;
BAT_W       = 34.0;
BAT_L       = 52.0;     // 50 mm cell + protection PCB
BAT_T       = 6.3;
BAT_DX      = 2.4;      // DEV: pack shifted 2.4 mm toward theta=0 so the antenna fits
// 2.4 GHz flex antenna Molex 146153 on the floor (z 1.0-2.0), along chord x = -26
ANT_L       = 34.9;
ANT_W       = 9.0;
ANT_T       = 0.2;
ANT_XC      = -23.85;   // DEV: -26 does not fit inside the cup; see doc
ANT_Z0      = 1.4;      // floor pocket, 0.4 mm skin under it
// base board z 9.5-11.1, Ø40 + USB tab to r = 35 at theta = 0
BB_Z0       = 9.5;
BB_T        = 1.6;
BB_Z1       = BB_Z0 + BB_T;          // 11.1
BB_R        = 20.0;
BB_TAB_W    = 11.0;
BB_TAB_X    = 34.4;
BB_SPEC_HOLES_R = 15;                // SPEC 3x M2 at r = 15 (inside battery footprint)
BB_SPEC_HOLES_A = [60, 180, 300];
BB_POST_TAB = [22.5, 0];             // DEV: real supports, outside the battery
BB_POST_PEG = [[-17.0, 6.0], [-17.0, -6.0]];
// press switch TS-1187A-B-A-B (5.1 x 5.1 x 1.5) at base-board centre, z 11.1-12.6
SW_S        = 5.1;
SW_H        = 1.5;
SW_Z1       = BB_Z1 + SW_H;          // 12.6
// floating-assembly (FA) lower plate z 12.8-14.3, r <= 30
FA_Z0       = 12.8;
FA_Z1       = 14.3;
FA_R        = 30.0;
GUIDE_R     = 29.0;
GUIDE_A     = [60, 180, 300];
PREGAP      = 0.15;                  // dot on boss to switch actuator
SW_TRAVEL   = 0.25;                  // TS-1187A travel to actuation (to verify)
STOP_TRAVEL = 0.60;                  // overload stop: plate boss lands on cup ear
DOT_T       = 0.5;                   // TPU/silicone dot on the boss absorbs switch-travel tolerance
FA_BOSS_Z0  = 12.0;                  // plate underside boss (overload-stop face)
EAR_Z1      = FA_BOSS_Z0 - STOP_TRAVEL;   // 11.40 cup ear top
EAR_Z0      = 9.05;                  // above the battery corner (z <= 8.8)
SPRING_D    = 4.4;                   // spring pockets
EAR_POCKET_Z = EAR_Z1 - 1.2;         // 10.25 spring seat in the ear
PLATE_POCKET_TOP = 12.9;             // spring seat in the plate (installed length 2.7)
CBORE_FLOOR = 13.3;                  // stop-screw head seat (head top 14.6)
PIN_D       = 3.0;                   // brass guide pin
// spindle Ø8 x 1.0 wall, bore Ø6
SP_OD       = 8.0;
SP_ID       = 6.0;
SP_Z0       = 13.3;                  // sits on a 0.5 mm floor over the switch boss
SP_Z1       = 29.0;
SLOT_A      = 225;                   // wire/coax exit slots in spindle wall
// rotor ring 316L OD 70 / ID 54, z 15.6-25.6, track on the TOP face
RING_RO     = 35.0;
RING_RI     = 27.0;
RING_Z0     = 15.6;
RING_Z1     = 25.6;
MAG_N       = 48;
MAG_D       = 2.0;
MAG_H       = 2.0;
RT          = 29.0;
POCKET_D    = 2.10;                  // magnet max Ø (2.05) + slip
POCKET_H    = 2.05;
// rotor carrier PA12-GF: web z 17-19, r 11-27
CW_Z0       = 17.0;
CW_Z1       = 19.0;
COLLAR_RI   = 11.0;                  // = 608 outer race
COLLAR_RO   = 12.2;
COLLAR_Z1   = 26.0;
LIP_RI      = 9.9;                   // outer-race seat lip
RIM_RI      = 25.0;                  // bonding register into the ring ID
RIM_Z0      = 16.1;
RIB_Z0      = 16.2;
// 608 bearing z 18.0-25.0
B_D         = 22.0;
B_d         = 8.0;
B_B         = 7.0;
B_Z0        = 18.0;
B_Z1        = B_Z0 + B_B;            // 25.0
// stationary spacers / spindle hub
LS_RO       = 5.75;
LS_FL_RO    = 10.6;
LS_FL_Z1    = CW_Z0 - 0.15;          // 16.85, 0.15 drop-stop gap under the carrier lip
LS_FL_Z0    = LS_FL_Z1 - 0.45;
HUB_FL_Z0   = 26.1;
HUB_FL_RO   = 8.5;                   // SPEC keep-out r <= 8.5
HUB_SCREW_R = 6.5;
HUB_SCREW_A = [30, 150, 270];
// main board Ø64, z 29.1-30.7
MB_Z0       = 29.1;
MB_T        = 1.6;
MB_Z1       = MB_Z0 + MB_T;          // 30.7
MB_R        = 32.0;
MB_BRK_R    = 17.0;
MB_BRK_A    = [60, 120];
// detent: N52 Ø3x2, 1.0 above track, r 29.0 (click) -> 21.5 (free) along theta 90
DET_A       = 90;
DET_D       = 3.0;
DET_H       = 2.0;
DET_GAP     = 1.0;
DET_R_CLICK = 29.0;
DET_STROKE  = 7.5;
DET_Z0      = RING_Z1 + DET_GAP;     // 26.6
CARR_T      = 0.5;
// micro linear stepper placeholder (VIC-TECH VSM08102 class, ~Ø8 x 33)
ST_Y        = 15.5;                  // chord y position (axis along X)
ST_ZA       = 24.4;                  // axis height
ST_CAN_D    = 8.0;
ST_CAN_X    = [6.5, 15.5];
ST_SCREW_X  = [-16.5, 6.5];
ST_STROKE   = 10.0;
SLOT_SLOPE  = DET_STROKE / ST_STROKE; // 0.75: carriage mm per slider mm
// LEDs / optics
LED_N       = 48;
LED_R       = 28.5;
LED_S       = 2.0;
LED_H       = 0.9;
LB_Z0       = 31.6;
LB_Z1       = 34.2;
LB_RI       = 27.0;
LB_RO       = 30.0;
LB_WALL     = 0.6;
SEPTA_N     = 24;
OLED_W      = 33.8;
OLED_L      = 34.0;
OLED_T      = 1.7;
OLED_Z0     = 33.0;
OLED_AA     = 26.86;
OLED_AA_OFF = 1.47;                  // active-area centre offset away from the FPC edge
OLED_YC     = -OLED_AA_OFF;          // glass centre (FPC edge toward theta = 270)
BRK_Z0      = 31.5;
BRK_Z1      = 32.8;                  // + 0.2 tape = glass bottom at 33.0
COV_Z0      = 34.2;
COV_Z1      = 36.0;
COV_R       = 32.5;
WIN_D       = 30.0;
DIF_RI      = 27.0;
DIF_RO      = 30.0;

// ------------------------------------------------------------------
//  colours
// ------------------------------------------------------------------
c_rubber  = "#1b1b1b";
c_cup     = "#3a3e45";
c_plate   = "#5f6b7a";
c_carrier = "#4b5563";
c_steel   = "#c9ced4";
c_steel2  = "#9aa3ad";
c_bear    = "#b8bec6";
c_brass   = "#c9a227";
c_spring  = "#8f969e";
c_pcb     = "#1f6f43";
c_pcb_m   = "#14532d";
c_ic      = "#222222";
c_conn    = "#e8e1cf";
c_module  = "#b0b4b8";
c_led     = "#f4f1e6";
c_N       = "#d64545";
c_S       = "#3b6fd6";
c_magbody = "#a7adb4";
c_detmag  = "#8e44ad";
c_lightbx = "#262626";
c_diff    = "#efeee6";
c_cover   = "#2b2d31";
c_glass   = "#0d1117";
c_aa      = "#10243a";
c_battery = "#8fa3b8";
c_kapton  = "#d08a2c";
c_coax    = "#5a5a5a";
c_motor   = "#6f7378";
c_hub     = "#7c6f5a";
c_pom     = "#e9e6dc";
c_felt    = "#d9cfa8";
c_lens    = [0.8, 0.9, 1.0, 0.35];

// ------------------------------------------------------------------
//  helpers
// ------------------------------------------------------------------
function pol(r, a) = [r * cos(a), r * sin(a)];
module at_polar(r, a, z = 0) translate([r * cos(a), r * sin(a), z]) rotate(a) children();
module tube(ro, ri, z0, z1, fn = fn_big)
    translate([0, 0, z0]) difference() {
        cylinder(r = ro, h = z1 - z0, $fn = fn);
        translate([0, 0, -0.01]) cylinder(r = ri, h = z1 - z0 + 0.02, $fn = fn);
    }
module rsquare(a, b, z0, z1)   // radial annulus profile square for rotate_extrude
    translate([a, z0]) square([b - a, z1 - z0]);
module chain(pts, d) for (i = [0:len(pts) - 2])
    hull() { translate(pts[i]) sphere(d = d, $fn = 12); translate(pts[i + 1]) sphere(d = d, $fn = 12); }

// ==================================================================
//  BASE (stationary): feet, cup, antenna, battery, base board, guides
// ==================================================================
module feet()
    color(c_rubber) for (a = FOOT_ANG) rotate(a - FOOT_ARC / 2)
        rotate_extrude(angle = FOOT_ARC, $fn = fn_big)
            translate([FOOT_RC - FOOT_RW / 2, 0.01]) square([FOOT_RW, FOOT_Z1 - 0.02]);

module guide_ear()
    intersection() {
        hull() {
            translate([GUIDE_R, 0, EAR_Z0]) cylinder(d = 7.0, h = EAR_Z1 - EAR_Z0, $fn = fn_mid);
            translate([CUP_RI + 0.8, -4.5, EAR_Z0]) cube([0.1, 9, EAR_Z1 - EAR_Z0]);
        }
        cylinder(r = R_OD - 0.3, h = 50, $fn = fn_big);
    }

module base_cup()
    color(c_cup) difference() {
        union() {
            rotate_extrude($fn = fn_big) polygon([
                [0, CUP_Z0], [R_OD - 0.6, CUP_Z0], [R_OD, CUP_Z0 + 0.6], [R_OD, CUP_TOP - 0.3],
                [R_OD - 0.3, CUP_TOP], [CUP_RI, CUP_TOP], [CUP_RI, CUP_FLOOR], [0, CUP_FLOOR]]);
            for (a = GUIDE_A) rotate(a) guide_ear();
            // base-board support posts (outside the battery footprint)
            translate([BB_POST_TAB[0], BB_POST_TAB[1], CUP_FLOOR - 0.01])
                cylinder(d = 5.0, h = BB_Z0 - CUP_FLOOR + 0.01, $fn = fn_mid);
            for (p = BB_POST_PEG) translate([p[0], p[1], CUP_FLOOR - 0.01]) {
                cylinder(d = 3.2, h = BB_Z0 - CUP_FLOOR + 0.01, $fn = fn_small);
                cylinder(d = 1.8, h = BB_Z1 + 0.3 - CUP_FLOOR, $fn = fn_small);  // locating peg
            }
            // battery locating rib on the +X side
            translate([BAT_DX + BAT_W / 2 + 0.4, -15, CUP_FLOOR - 0.01]) cube([0.8, 30, 1.2]);
        }
        // USB-C / board-tab slot through the wall at theta = 0
        translate([CUP_RI - 1.5, -(BB_TAB_W + 0.6) / 2, BB_Z0 - 0.2]) cube([5, BB_TAB_W + 0.6, 20]);
        // antenna pocket in the floor (0.4 mm skin left under it)
        translate([ANT_XC - (ANT_W + 0.6) / 2, -(ANT_L + 0.6) / 2, ANT_Z0])
            cube([ANT_W + 0.6, ANT_L + 0.6, CUP_FLOOR - ANT_Z0 + 0.01]);
        // heat-set insert (M2 x 3, Ø3.2) in the tab post
        translate([BB_POST_TAB[0], BB_POST_TAB[1], BB_Z0 - 3.6]) cylinder(d = 3.2, h = 3.7, $fn = fn_small);
        // guide ears: spring pocket + bonded pin hole
        for (a = GUIDE_A) rotate(a) translate([GUIDE_R, 0, 0]) {
            translate([0, 0, EAR_POCKET_Z]) cylinder(d = SPRING_D, h = 5, $fn = fn_small);
            translate([0, 0, EAR_Z0 - 0.1]) cylinder(d = PIN_D + 0.02, h = 5, $fn = fn_small);
        }
    }

module antenna() {
    color(c_kapton) translate([ANT_XC - ANT_W / 2, -ANT_L / 2, ANT_Z0]) cube([ANT_W, ANT_L, ANT_T]);
}
// 1.13 mm coax from the antenna feed, up past the base board, across the FA
// plate (groove), into the spindle bottom slot, up the bore, to the u.FL.
COAX_PTS = [
    [ANT_XC + ANT_W / 2 - 0.8, 0, ANT_Z0 + 0.8],
    [-21.2, 0, 3.2], [-21.2, 0, 13.6], [-19.0, -0.4, 14.0],
    [pol(5.2, SLOT_A)[0], pol(5.2, SLOT_A)[1], 15.3], [0, 0, 16.5], [0, 0, 26.0],
    [pol(3.8, SLOT_A)[0], pol(3.8, SLOT_A)[1], 27.0],
    [pol(8.5, 215)[0], pol(8.5, 215)[1], 26.0]];
module coax() color(c_coax) chain(COAX_PTS, 1.13);

module battery()
    color(c_battery) translate([BAT_DX, 0, BAT_Z0 + 0.05]) {
        translate([-BAT_W / 2 + 1, -BAT_L / 2 + 1, 0]) minkowski() {
            cube([BAT_W - 2, BAT_L - 2, BAT_T - 1]);
            cylinder(r = 1, h = 1, $fn = 16);
        }
    }

module base_board_outline()
    union() {
        circle(r = BB_R, $fn = fn_big);
        translate([0, -BB_TAB_W / 2]) square([BB_TAB_X, BB_TAB_W]);
    }

module base_board() {
    color(c_pcb) difference() {
        translate([0, 0, BB_Z0]) linear_extrude(BB_T) base_board_outline();
        for (a = BB_SPEC_HOLES_A) at_polar(BB_SPEC_HOLES_R, a, BB_Z0 - 1) cylinder(d = 2.2, h = 4, $fn = 12);
        translate([BB_POST_TAB[0], BB_POST_TAB[1], BB_Z0 - 1]) cylinder(d = 2.2, h = 4, $fn = 12);
        for (p = BB_POST_PEG) translate([p[0], p[1], BB_Z0 - 1]) cylinder(d = 2.0, h = 4, $fn = 12);
    }
    if (show_board_parts) base_board_parts();
}
module base_board_parts() {
    // SW1 TS-1187A, centre
    color(c_ic) translate([-SW_S / 2, -SW_S / 2, BB_Z1]) cube([SW_S, SW_S, SW_H - 0.4]);
    color("#cccccc") translate([0, 0, BB_Z1]) cylinder(d = 2.5, h = SW_H, $fn = 16);
    // USB-C HRO TYPE-C-31-M-12, top-mount, mating face at r = 35
    color("#d0d0d0") hull() for (s = [-1, 1])
        translate([27.65, s * (8.94 - 3.26) / 2, BB_Z1 + 3.26 / 2]) rotate([0, 90, 0]) cylinder(d = 3.26, h = 7.35, $fn = 24);
    // J3 link, vertical JST SH 12p (BM12B-SRSS-TB), envelope 15 x 4.25 x 4.25 (verify)
    color(c_conn) translate([-7.5, -11.125, BB_Z1]) cube([15, 4.25, 4.25]);
    // J2 battery JST PH S2B-PH-SM4-TB on the tab underside (beside the pack)
    color(c_conn) translate([26.0, -4.0, BB_Z0 - 4.8]) cube([4.5, 8.0, 4.8]);
    // BQ25180 / BSS138DW / TVS region (low parts) on the tab
    color(c_ic) translate([16, -2.5, BB_Z1]) cube([3, 5, 0.6]);
}

// guide pins (brass Ø3, bonded into the cup ear), stop screws, springs
module guide_pins()
    for (a = GUIDE_A) rotate(a) translate([GUIDE_R, 0, 0]) {
        color(c_brass) translate([0, 0, EAR_Z0]) cylinder(d = PIN_D, h = CBORE_FLOOR - EAR_Z0, $fn = fn_small);
        color(c_brass) translate([0, 0, CBORE_FLOOR]) cylinder(d = 3.8, h = 1.3, $fn = fn_small); // M2 pan head
    }
module guide_springs()   // 0.35 wire, OD 4.0, between ear seat and plate seat
    for (a = GUIDE_A) rotate(a) translate([GUIDE_R, 0, 0]) {
        sz0 = EAR_POCKET_Z; sz1 = PLATE_POCKET_TOP - press * STOP_TRAVEL;
        color(c_spring) for (k = [0:5]) translate([0, 0, sz0 + 0.2 + k * (sz1 - sz0 - 0.4) / 5])
            rotate_extrude($fn = 20) translate([1.82, 0]) circle(d = 0.35, $fn = 8);
    }
module guide_hw() { guide_pins(); guide_springs(); }

// ==================================================================
//  FLOATING ASSEMBLY (non-rotating part): plate, spindle, spacers, hub
// ==================================================================
module fa_outline()
    union() {
        circle(r = FA_R, $fn = fn_big);
        for (a = GUIDE_A) rotate(a) hull() {
            translate([GUIDE_R, 0]) circle(d = 7.0, $fn = fn_mid);
            translate([GUIDE_R - 4, 0]) circle(d = 7.0, $fn = fn_mid);
        }
    }

module fa_lower_plate()
    color(c_plate) difference() {
        union() {
            translate([0, 0, FA_Z0]) linear_extrude(FA_Z1 - FA_Z0) fa_outline();
            for (a = GUIDE_A) rotate(a) translate([GUIDE_R, 0, FA_BOSS_Z0])
                cylinder(d = 6.6, h = FA_Z0 - FA_BOSS_Z0 + 0.01, $fn = fn_mid);
            // centre boss over the switch (the 0.5 mm TPU dot is modelled as part of it)
            translate([0, 0, SW_Z1 + PREGAP]) cylinder(d = 3.0, h = FA_Z0 - SW_Z1 - PREGAP + 0.01, $fn = fn_small);
        }
        for (a = GUIDE_A) rotate(a) translate([GUIDE_R, 0, 0]) {
            translate([0, 0, FA_BOSS_Z0 - 0.1]) cylinder(d = SPRING_D, h = PLATE_POCKET_TOP - FA_BOSS_Z0 + 0.1, $fn = fn_small);
            translate([0, 0, FA_BOSS_Z0 - 1]) cylinder(d = PIN_D + 0.05, h = 5, $fn = fn_small);
            translate([0, 0, CBORE_FLOOR]) cylinder(d = 4.6, h = 2, $fn = fn_small);
        }
        // spindle socket (Ø8 bonded, 1.0 deep) leaving a 0.5 floor over the boss
        translate([0, 0, SP_Z0]) cylinder(d = SP_OD + 0.05, h = 5, $fn = fn_mid);
        // USB-C receptacle notch at theta = 0
        translate([26.5, -6.0, FA_Z0 - 1]) cube([10, 12, 5]);
        // J3 window (vertical SH header pokes through)
        translate([-8.3, -11.6, FA_Z0 - 1]) cube([16.6, 5.2, 5]);
        // coax: hole down to the floor + groove on top toward the spindle slot
        translate([-21.2, 0, FA_Z0 - 1]) cylinder(d = 2.2, h = 5, $fn = fn_small);
        hull() {
            translate([-21.2, 0, FA_Z1 - 0.9]) cylinder(d = 1.4, h = 1, $fn = 12);
            translate([pol(4.5, SLOT_A)[0], pol(4.5, SLOT_A)[1], FA_Z1 - 0.9]) cylinder(d = 1.4, h = 1, $fn = 12);
        }
    }

module spindle()
    color(c_steel2) difference() {
        translate([0, 0, SP_Z0]) cylinder(d = SP_OD, h = SP_Z1 - SP_Z0, $fn = fn_mid);
        translate([0, 0, SP_Z0 - 1]) cylinder(d = SP_ID, h = 40, $fn = fn_mid);
        rotate(SLOT_A) translate([0, -1.75, 14.4]) cube([6, 3.5, 1.9]);   // bottom exit
        rotate(SLOT_A) translate([0, -1.75, 26.3]) cube([6, 3.5, 1.5]);   // top exit
    }

// POM lower spacer: clamps the inner race, carries the drop-stop flange
module lower_spacer()
    color(c_pom) difference() {
        union() {
            tube(LS_RO, SP_OD / 2, FA_Z1, B_Z0, fn_mid);
            tube(LS_FL_RO, LS_RO - 0.01, LS_FL_Z0, LS_FL_Z1, fn_mid);
        }
        rotate(SLOT_A) translate([0, -1.75, FA_Z1 - 0.1]) cube([12, 3.5, 2.0]);
    }

// spindle hub = upper spacer + flange, 3x M2 heat-set inserts at r 6.5
module spindle_hub()
    color(c_hub) difference() {
        union() {
            tube(LS_RO, SP_OD / 2, B_Z1, HUB_FL_Z0 + 0.01, fn_mid);
            tube(HUB_FL_RO, SP_OD / 2, HUB_FL_Z0, MB_Z0, fn_mid);
        }
        for (a = HUB_SCREW_A) at_polar(HUB_SCREW_R, a, MB_Z0 - 3.0) cylinder(d = 3.2, h = 3.1, $fn = fn_small);
        rotate(SLOT_A) translate([0, -1.75, 26.3]) cube([10, 3.5, 1.5]);   // harness/coax channel
    }

// ==================================================================
//  ROTOR: 316L ring + 48 magnets + PA12-GF carrier + 608 outer race
// ==================================================================
module ring_profile()
    polygon([
        [RING_RI + 0.5, RING_Z0], [RING_RO - 0.5, RING_Z0], [RING_RO, RING_Z0 + 0.5],
        [RING_RO, RING_Z1 - 1.0], [RING_RO - 1.0, RING_Z1], [RING_RI + 0.5, RING_Z1],
        [RING_RI, RING_Z1 - 0.5], [RING_RI, RING_Z0 + 0.5]]);

module rotor_ring()
    color(c_steel) difference() {
        rotate_extrude($fn = fn_big * 2) ring_profile();
        for (i = [0:MAG_N - 1]) rotate(i * 360 / MAG_N)
            translate([RT, 0, RING_Z1 - POCKET_H]) cylinder(d = POCKET_D, h = POCKET_H + 0.1, $fn = fn_small);
        for (a = [45:90:315]) rotate(a) translate([31, 0, RING_Z0 - 0.1]) cylinder(d = 1.6, h = 3.1, $fn = 12);
        if (show_knurl) for (i = [0:119]) rotate(i * 3)
            translate([RING_RO, 0, RING_Z0 + 1.5]) rotate(45) translate([-0.3, -0.3, 0]) cube([0.6, 0.6, 7.0]);
    }

module track_magnets()
    for (i = [0:MAG_N - 1]) rotate(i * 360 / MAG_N) translate([RT, 0, RING_Z1 - MAG_H]) {
        color(c_magbody) cylinder(d = MAG_D, h = MAG_H - 0.06, $fn = fn_small);
        color(i % 2 == 0 ? c_N : c_S) translate([0, 0, MAG_H - 0.06]) cylinder(d = MAG_D, h = 0.05, $fn = fn_small);
    }

module carrier_profile()
    union() {
        rsquare(COLLAR_RO - 0.01, RIM_RI + 0.01, CW_Z0, CW_Z1);        // web
        rsquare(RIM_RI, RING_RI - 0.05, RIM_Z0, CW_Z1);                // bonding register
        rsquare(COLLAR_RI, COLLAR_RO, CW_Z0, COLLAR_Z1);               // bearing collar
        rsquare(LIP_RI, COLLAR_RI + 0.01, CW_Z0, B_Z0);                // outer-race seat
    }

module rotor_carrier()
    color(c_carrier) difference() {
        union() {
            rotate_extrude($fn = fn_big) carrier_profile();
            for (i = [0:11]) rotate(i * 30 + 15) translate([13.0, -0.6, RIB_Z0]) cube([RIM_RI - 12.5, 1.2, CW_Z0 - RIB_Z0 + 0.01]);
        }
        // groove for the printed snap retainer above the wave spring
        translate([0, 0, 25.45]) cylinder(r = 11.3, h = 0.4, $fn = fn_big);
    }

module wave_spring() color(c_spring) tube(10.95, 9.95, B_Z1, B_Z1 + 0.4, fn_mid);
module bearing_retainer() color(c_carrier) tube(11.25, LIP_RI, 25.45, 25.95, fn_mid);

module bearing608() {
    color(c_bear) {
        tube(6.05, B_d / 2, B_Z0, B_Z1, fn_mid);           // inner ring (stationary)
        tube(B_D / 2, 9.55, B_Z0, B_Z1, fn_mid);           // outer ring (rotor)
    }
    color("#7d848c") {
        tube(9.56, 6.2, B_Z0 + 0.3, B_Z0 + 0.5, fn_mid);   // 2Z shields
        tube(9.56, 6.2, B_Z1 - 0.5, B_Z1 - 0.3, fn_mid);
    }
    color(c_bear) for (i = [0:6]) rotate(i * 360 / 7) translate([7.6, 0, (B_Z0 + B_Z1) / 2]) sphere(d = 3.97, $fn = 16);
}

module rotor() {
    rotor_ring();
    track_magnets();
    rotor_carrier();
    wave_spring();
    bearing_retainer();
}

// swept envelope of everything that rotates (for the clash check)
module rotor_envelope2d()
    offset(delta = clash_margin) union() {
        ring_profile();
        carrier_profile();
        rsquare(13.0, RIM_RI, RIB_Z0, CW_Z0 + 0.01);        // ribs
        rsquare(9.55, B_D / 2, B_Z0, B_Z1);                 // outer race
        rsquare(LIP_RI, 11.3, B_Z1, 25.95);                 // wave spring + retainer
    }
module rotor_envelope() rotate_extrude($fn = fn_big) rotor_envelope2d();

// ==================================================================
//  MAIN BOARD and its hanging parts
// ==================================================================
module main_board() {
    color(c_pcb_m) difference() {
        translate([0, 0, MB_Z0]) cylinder(r = MB_R, h = MB_T, $fn = fn_big);
        translate([0, 0, MB_Z0 - 1]) cylinder(d = 5, h = 5, $fn = fn_small);
        for (a = HUB_SCREW_A) at_polar(HUB_SCREW_R, a, MB_Z0 - 1) cylinder(d = 2.2, h = 5, $fn = 12);
        for (a = MB_BRK_A) at_polar(MB_BRK_R, a, MB_Z0 - 1) cylinder(d = 2.2, h = 5, $fn = 12);
    }
    if (show_board_parts) { main_board_top(); main_board_bottom(); }
}
module main_board_top() {
    for (i = [0:LED_N - 1]) rotate(i * 360 / LED_N) translate([LED_R, 0, MB_Z1]) {
        color(c_led) translate([-LED_S / 2, -LED_S / 2, 0]) cube([LED_S, LED_S, LED_H]);
        color("#b08d57") translate([-2.5 - 0.25, -0.5, 0]) cube([1.0, 0.5, 0.5]);   // 100 nF at r ~ 26
    }
    at_polar(21.5, 90, MB_Z1) color(c_ic) translate([-0.65, -1.45, 0]) cube([1.3, 2.9, 1.1]); // DRV5032 (top)
    color(c_ic) translate([-9, -14.5, MB_Z1]) cube([18, 4.0, 1.0]);                         // OLED ZIF (top)
    color("#555555") translate([-9.5, 1.0, MB_Z1]) cube([3, 3, 1.5]);                       // 13 V boost L
    // brass M2 screws, heads on the top side
    for (a = HUB_SCREW_A) at_polar(HUB_SCREW_R, a, MB_Z1) color(c_brass) cylinder(d = 2.0, h = 0.8, $fn = 12);
    at_polar(MB_BRK_R, MB_BRK_A[0], MB_Z1) color(c_brass) cylinder(d = 3.8, h = 1.0, $fn = 16);
}
module main_board_bottom() {
    // TMAG5273 (bottom) at r = 29, theta = 270, long axis radial, SOT-23-6
    at_polar(RT, 270, MB_Z0 - 1.1) color(c_ic) translate([-1.45, -0.8, 0]) cube([2.9, 1.6, 1.1]);
    // MDBT50Q-U1MV2 (bottom), r 8..23.5, theta ~215, u.FL end toward the centre (as SPEC)
    at_polar(8.0, 215, MB_Z0 - 2.2) color(c_module) translate([0, -5, 0]) cube([15.5, 10, 2.2]);
    // mated u.FL plug under the module's inner end (~2.5 mm mated height)
    at_polar(9.6, 215, MB_Z0 - 2.2 - 2.5) color("#d4af37") cylinder(d = 2.6, h = 2.5, $fn = 16);
    // J1 link, vertical JST SH 12p (bottom) "next to the centre hole" (as SPEC)
    at_polar(8.6, 300, MB_Z0 - 4.25) color(c_conn) translate([0, -7.5, 0]) cube([4.25, 15, 4.25]);
    // piezo PKMCS0909E (bottom)
    at_polar(18.0, 330, MB_Z0 - 1.9) color("#e0e0e0") translate([-4.5, -4.5, 0]) cube([9, 9, 1.9]);
    // LIS2DW12 + DRV8837 x2 + motor connector (low parts)
    at_polar(16.0, 20, MB_Z0 - 0.9) color(c_ic) translate([-1, -1, 0]) cube([2, 2, 0.9]);
    at_polar(20.0, 45, MB_Z0 - 0.8) color(c_ic) translate([-1, -2.5, 0]) cube([2, 5, 0.8]);
}

// ==================================================================
//  DETENT: rails, carriage + Ø3x2 magnet + shoe, stepper placeholder
// ==================================================================
CAR_STRIP = [[0, -3.0], [-3.0, -4.3], [-5.0, -6.0], [-15.0, -13.5]];   // carriage frame
module carriage_rails()
    color("#b9b9b9") for (s = [-1, 1]) {
        translate([s > 0 ? 3.4 : -4.0, 18.6, MB_Z0 - 1.0]) cube([0.6, 13.0, 1.0]);   // upright
        translate([s > 0 ? 2.6 : -4.0, 18.6, MB_Z0 - 1.0]) cube([1.4, 13.0, 0.5]);   // lip
    }
// local frame: origin = detent-magnet centre, z = 0 at its bottom face, +y radial out
module detent_carriage_local()
    difference() {
        union() {
            translate([-3.0, -2.5, 2.0]) cube([6.0, 5.0, CARR_T]);                // plate
            translate([-1.5, 2.4, 2.0]) cube([3.0, 1.0, CARR_T]);                 // shoe tongue
            cylinder(d = 4.0, h = 2.01, $fn = fn_small);                           // magnet cup
            translate([-1.2, -3.6, 0.4]) cube([2.4, 1.2, 2.1]);                    // web down
            for (i = [0:len(CAR_STRIP) - 2]) hull() {                              // link strip
                translate([CAR_STRIP[i][0], CAR_STRIP[i][1], 0.4]) cylinder(d = 3.0, h = 0.5, $fn = 16);
                translate([CAR_STRIP[i + 1][0], CAR_STRIP[i + 1][1], 0.4]) cylinder(d = 3.0, h = 0.5, $fn = 16);
            }
            translate([-1.5, 2.6, -0.05]) cube([3.0, 0.8, 2.1]);                   // shoe hanger
        }
        translate([0, 0, -0.1]) cylinder(d = DET_D + 0.08, h = DET_H + 0.1, $fn = fn_small);  // magnet pocket
        // inclined slot for the stepper slider pin (slope 0.75)
        hull() {
            translate([CAR_STRIP[2][0] + 0.8, CAR_STRIP[2][1] + 0.6, 0]) cylinder(d = 1.6, h = 1.5, $fn = 12);
            translate([CAR_STRIP[3][0] - 0.8, CAR_STRIP[3][1] - 0.6, 0]) cylinder(d = 1.6, h = 1.5, $fn = 12);
        }
    }
module detent_carriage_placed(off)
    translate([0, DET_R_CLICK - off, DET_Z0]) {
        color("#e2e2e2") detent_carriage_local();
        color(c_detmag) cylinder(d = DET_D, h = DET_H, $fn = fn_small);
        color(c_felt) translate([-1.5, 2.6, -0.95]) cube([3.0, 0.8, 0.9]);        // felt/UHMW shoe
    }

module stepper(off) {
    xs = -15.0 + off * ST_STROKE / DET_STROKE;     // slider pin x (world)
    color(c_motor) {
        translate([ST_CAN_X[0], ST_Y, ST_ZA]) rotate([0, 90, 0]) cylinder(d = ST_CAN_D, h = ST_CAN_X[1] - ST_CAN_X[0], $fn = fn_mid);
        translate([ST_CAN_X[0] - 1, ST_Y - 4, ST_ZA - 4]) cube([1, 8, 8]);                 // front plate
        translate([ST_SCREW_X[0] - 1, ST_Y - 2.5, ST_ZA - 4]) cube([1, 5, 5.5]);            // end tab
        translate([ST_SCREW_X[0] - 1, ST_Y - 2, ST_ZA - 4]) cube([ST_CAN_X[0] - ST_SCREW_X[0] + 1, 4, 0.5]); // bracket bar
    }
    color("#b0b0b0") translate([ST_SCREW_X[0], ST_Y, ST_ZA]) rotate([0, 90, 0]) cylinder(d = 2, h = ST_SCREW_X[1] - ST_SCREW_X[0], $fn = 12);
    color("#d9d9d9") translate([xs - 2.5, ST_Y - 2, ST_ZA - 2]) cube([5, 4, 4]);           // slider nut
    color(c_brass) translate([xs, ST_Y, ST_ZA + 2]) cylinder(d = 1.5, h = 1.4, $fn = 12);   // drive pin into the slot
}
// printed saddle: bonded to the can, M2 into the board hole at (r 17, theta 60)
module stepper_saddle()
    color("#9c8f7a") difference() {
        translate([7.0, ST_Y - 4.6, ST_ZA + 1.5]) cube([3.6, 9.2, MB_Z0 - ST_ZA - 1.5]);
        translate([6.0, ST_Y, ST_ZA]) rotate([0, 90, 0]) cylinder(d = ST_CAN_D + 0.1, h = 6, $fn = fn_mid);
        at_polar(MB_BRK_R, MB_BRK_A[0], MB_Z0 - 3.2) cylinder(d = 3.2, h = 3.3, $fn = fn_small);
    }

module detent_assembly(off = det_offset) {
    carriage_rails();
    detent_carriage_placed(off);
    stepper(off);
    stepper_saddle();
}

// ==================================================================
//  OPTICS + DISPLAY + COVER (on the main-board top)
// ==================================================================
module light_box()
    color(c_lightbx) difference() {
        union() {
            tube(LB_RI + LB_WALL, LB_RI, LB_Z0 + 0.1, LB_Z1);
            tube(LB_RO, LB_RO - LB_WALL, LB_Z0 + 0.1, LB_Z1);
            // 24 septa (one per detent) whose feet stand on the board between LEDs
            for (i = [0:SEPTA_N - 1]) rotate(i * 360 / SEPTA_N - 360 / LED_N / 2)
                translate([LB_RI + 0.01, -0.3, MB_Z1]) cube([LB_RO - LB_RI - 0.02, 0.6, LB_Z1 - MB_Z1]);
        }
        for (i = [0:5]) rotate(i * 60 - 360 / LED_N / 2)
            translate([LB_RI - 0.1, -0.5, LB_Z1 - 0.8]) cube([LB_RO - LB_RI + 0.2, 1.0, 1]);
    }

module diffuser() color(c_diff) tube(DIF_RO - 0.02, DIF_RI + 0.02, COV_Z0 + 0.02, COV_Z1 - 0.02);   // 0.02 reliefs avoid coplanar faces

module oled_bracket()
    color("#4d4d4d") difference() {
        union() {
            translate([-15, OLED_YC - 15, BRK_Z0]) cube([30, 28.5, BRK_Z1 - BRK_Z0]);
            for (a = HUB_SCREW_A) at_polar(HUB_SCREW_R, a, MB_Z1 + 0.8) cylinder(d = 4.0, h = BRK_Z0 - MB_Z1 - 0.79, $fn = fn_small);
        }
        for (a = HUB_SCREW_A) at_polar(HUB_SCREW_R, a, MB_Z1 - 0.1) {
            cylinder(d = 2.3, h = 5, $fn = 12);
            translate([0, 0, BRK_Z1 - MB_Z1 - 1.1]) cylinder(d1 = 2.3, d2 = 4.3, h = 1.01, $fn = 16); // M2 CSK
        }
        translate([-9.5, -15.0, MB_Z1 - 0.1]) cube([19, 5.0, 1.6]);      // ZIF pocket
        translate([-10.0, 0.5, MB_Z1 - 0.1]) cube([4, 4, 2.0]);          // boost inductor pocket
        translate([-9.5, OLED_YC - 16, BRK_Z0 - 0.1]) cube([19, 3.0, 3]); // FPC fold relief
        at_polar(MB_BRK_R, MB_BRK_A[0], MB_Z1 - 0.1) cylinder(d = 4.6, h = 1.5, $fn = 16); // screw head relief
    }

module oled_glass() {
    color(c_glass) translate([-OLED_W / 2, OLED_YC - OLED_L / 2, OLED_Z0]) cube([OLED_W, OLED_L, OLED_T]);
    color(c_aa) translate([-OLED_AA / 2, -OLED_AA / 2, OLED_Z0 + OLED_T]) cube([OLED_AA, OLED_AA, 0.02]);
    // FPC folded 180 deg under the glass to the ZIF
    color(c_kapton) {
        translate([-7.5, OLED_YC - OLED_L / 2 - 0.9, MB_Z1 + 0.6]) cube([15, 0.12, OLED_Z0 - MB_Z1 - 0.4]);
        translate([-7.5, OLED_YC - OLED_L / 2 - 0.9, MB_Z1 + 0.6]) cube([15, 4.5, 0.12]);
    }
}

module top_cover()
    color(c_cover) difference() {
        union() {
            tube(COV_R, WIN_D / 2, COV_Z0, COV_Z1);
            tube(COV_R, 30.6, MB_Z1 + 0.05, COV_Z0 + 0.01);                          // skirt
            for (i = [0:5]) rotate(i * 60 - 360 / LED_N / 2)                          // spokes under the diffuser
                translate([DIF_RI - 0.6, -0.45, LB_Z1 - 0.8]) cube([DIF_RO - DIF_RI + 1.2, 0.9, 0.9]);
            // 3 snap hooks onto the light-box outer wall
            for (a = [30, 150, 270]) rotate(a) translate([30.05, -1.5, LB_Z0 + 0.3]) cube([0.6, 3.0, COV_Z0 - LB_Z0]);
        }
        translate([0, 0, COV_Z0]) difference() {
            cylinder(r = DIF_RO + 0.05, h = 3, $fn = fn_big);
            translate([0, 0, -1]) cylinder(r = DIF_RI - 0.05, h = 5, $fn = fn_big);
        }
        // glass pocket (0.3 air gap above the glass), window lens recess
        translate([-(OLED_W + 0.6) / 2, OLED_YC - (OLED_L + 0.6) / 2, COV_Z0 - 1])
            cube([OLED_W + 0.6, OLED_L + 0.6, OLED_Z0 + OLED_T + 0.3 - COV_Z0 + 1]);
        translate([0, 0, COV_Z1 - 0.5]) cylinder(d = 33.0, h = 1, $fn = fn_big);
        // piezo vent slots near the rim are not needed (piezo vents into the bowl)
    }
module window_lens() color(c_lens) translate([0, 0, COV_Z1 - 0.5]) cylinder(d = 32.8, h = 0.5, $fn = fn_big);

// ==================================================================
//  GROUPS
// ==================================================================
module base_group() {
    feet(); base_cup(); antenna(); battery(); base_board(); guide_hw();
}
module fa_static_group() {                       // non-rotating floating assembly
    fa_lower_plate(); spindle(); lower_spacer(); spindle_hub(); coax();
    main_board(); detent_assembly(det_offset);
    light_box(); oled_bracket(); oled_glass(); diffuser(); top_cover(); window_lens();
    color(c_bear) { tube(6.05, B_d / 2, B_Z0, B_Z1, fn_mid); }   // inner race
}
module rotor_group() { rotor(); bearing608(); }

module assembly() {
    base_group();
    translate([0, 0, -press * STOP_TRAVEL]) { fa_static_group(); rotor_group(); }
}

// ---------- exploded ----------
module exploded() {
    e = explode;
    translate([0, 0, -14 * e]) feet();
    base_cup();
    translate([0, 0, 3 * e]) antenna();
    translate([0, 0, 8 * e]) battery();
    translate([0, 0, 20 * e]) base_board();
    translate([0, 0, 30 * e]) guide_hw();
    translate([0, 0, 40 * e]) fa_lower_plate();
    translate([0, 0, 52 * e]) { spindle(); lower_spacer(); }
    translate([0, 0, 80 * e]) { rotor_carrier(); rotor_ring(); track_magnets(); }
    translate([0, 0, 92 * e]) bearing608();
    translate([0, 0, 98 * e]) { wave_spring(); bearing_retainer(); }
    translate([0, 0, 106 * e]) spindle_hub();
    translate([0, 0, 116 * e]) detent_assembly(det_offset);
    translate([0, 0, 128 * e]) main_board();
    translate([0, 0, 138 * e]) { light_box(); oled_bracket(); }
    translate([0, 0, 146 * e]) oled_glass();
    translate([0, 0, 154 * e]) diffuser();
    translate([0, 0, 164 * e]) { top_cover(); window_lens(); }
}

EXPL_LABELS = [
    [-13.5, "3x micro-suction arc pads"], [6, "base cup (PA12)"], [13, "LiPo 603450 (+2.4 mm in x)"],
    [30.5, "base board + SW1 + USB-C"], [41, "guide pins, springs, stop screws"],
    [53.5, "FA lower plate (PA12-GF)"], [68, "spindle Ø8x1 + POM spacer"],
    [100, "316L ring + 48 magnets + carrier"], [113.5, "608-2Z (re-oiled)"],
    [124, "wave spring + retainer"], [133.5, "spindle hub (M2 inserts)"],
    [143, "detent carriage + stepper"], [158.5, "main board Ø64"],
    [170, "light box + OLED bracket"], [180, "OLED 1.5in SSD1351"], [189.5, "opal diffuser ring"],
    [199.5, "top cover + window lens"]];
module exploded_labels()
    for (l = EXPL_LABELS) translate([40 * 0.744, 40 * 0.668, l[0] * explode]) rotate([0, 0, 41.9]) rotate([90, 0, 0])
        color("#202020") linear_extrude(0.2) text(l[1], size = 3.2, halign = "left", valign = "center", font = "DejaVu Sans");

// ---------- sections (per-part cut keeps colours in preview) ----------
module cut_keep(plane, c, k) {
    // colour applied outside the intersection so the cut faces carry the part colour;
    // k makes each cutting box unique (identical boxes share one cached colour in preview)
    if (plane == "yz") color(c) render(convexity = 6) intersection() { children(); translate([-100 - k, -100, -50]) cube([100 + k, 200, 200]); }
    else color(c) render(convexity = 6) intersection() { children(); translate([-100, -100 - k, -50]) cube([200, 100 + k, 200]); }
}
module section(plane) {
    cut_keep(plane, c_rubber, 0) feet();
    cut_keep(plane, c_cup, 1) base_cup();
    cut_keep(plane, c_kapton, 2) antenna();
    cut_keep(plane, c_battery, 3) battery();
    cut_keep(plane, c_pcb, 4) base_board();
    cut_keep(plane, c_brass, 5) guide_hw();
    cut_keep(plane, c_plate, 6) fa_lower_plate();
    cut_keep(plane, c_steel2, 7) spindle();
    cut_keep(plane, c_pom, 8) lower_spacer();
    cut_keep(plane, c_hub, 9) spindle_hub();
    cut_keep(plane, c_coax, 10) coax();
    cut_keep(plane, c_steel, 11) rotor_ring();
    cut_keep(plane, c_magbody, 12) track_magnets();
    cut_keep(plane, c_carrier, 13) rotor_carrier();
    cut_keep(plane, c_spring, 14) wave_spring();
    cut_keep(plane, c_carrier, 15) bearing_retainer();
    cut_keep(plane, c_bear, 16) bearing608();
    cut_keep(plane, c_pcb_m, 17) main_board();
    cut_keep(plane, "#e2e2e2", 18) detent_assembly(det_offset);
    cut_keep(plane, c_lightbx, 19) light_box();
    cut_keep(plane, "#4d4d4d", 20) oled_bracket();
    cut_keep(plane, c_glass, 21) oled_glass();
    cut_keep(plane, c_diff, 22) diffuser();
    cut_keep(plane, c_cover, 23) top_cover();
    cut_keep(plane, c_lens, 24) window_lens();
}

// ---------- clash checks ----------
STATIONARY_NAMES = ["base_cup", "base_board", "battery", "antenna", "guide_pins", "fa_lower_plate",
                    "spindle", "lower_spacer", "spindle_hub", "main_board", "detent@click", "detent@free",
                    "light_box", "oled_bracket", "oled_glass", "top_cover"];
module stationary_item(i) {
    if (i == 0) base_cup();
    else if (i == 1) base_board();
    else if (i == 2) battery();
    else if (i == 3) antenna();
    else if (i == 4) guide_pins();
    else if (i == 5) fa_lower_plate();
    else if (i == 6) spindle();
    else if (i == 7) lower_spacer();
    else if (i == 8) spindle_hub();
    else if (i == 9) main_board();
    else if (i == 10) detent_assembly(0);
    else if (i == 11) detent_assembly(DET_STROKE);
    else if (i == 12) light_box();
    else if (i == 13) oled_bracket();
    else if (i == 14) oled_glass();
    else if (i == 15) top_cover();
}
BASE_ITEMS = [0, 1, 2, 3, 4];       // do not move on a press
FA_PRESS_ITEMS = [5, 6, 7, 8, 9, 10];
module clash_rotor(i) intersection() { rotor_envelope(); stationary_item(i); }
module clash_press(i)
    intersection() {
        stationary_item(i);
        translate([0, 0, -STOP_TRAVEL]) union() {
            rotor_envelope();
            for (j = FA_PRESS_ITEMS) stationary_item(j);
        }
    }

// ---------- printable parts on the bed ----------
part_list = ["base_cup", "top_cover", "light_box", "diffuser", "fa_lower_plate", "rotor_carrier",
             "detent_carriage", "oled_bracket", "spindle_hub", "lower_spacer", "bearing_retainer",
             "stepper_saddle", "carriage_rail"];
module print_part(p) {
    if (p == "base_cup") translate([0, 0, -CUP_Z0]) base_cup();
    else if (p == "top_cover") translate([0, 0, COV_Z1]) mirror([0, 0, 1]) top_cover();
    else if (p == "light_box") translate([0, 0, -MB_Z1]) light_box();
    else if (p == "diffuser") translate([0, 0, -COV_Z0]) diffuser();
    else if (p == "fa_lower_plate") translate([0, 0, FA_Z1]) mirror([0, 0, 1]) fa_lower_plate();
    else if (p == "rotor_carrier") translate([0, 0, -RIB_Z0]) rotor_carrier();
    else if (p == "detent_carriage") translate([0, 0, 2.0 + CARR_T]) mirror([0, 0, 1]) detent_carriage_local();
    else if (p == "oled_bracket") translate([0, 0, BRK_Z1]) mirror([0, 0, 1]) oled_bracket();
    else if (p == "spindle_hub") translate([0, 0, MB_Z0]) mirror([0, 0, 1]) spindle_hub();
    else if (p == "lower_spacer") translate([0, 0, -FA_Z1]) lower_spacer();
    else if (p == "bearing_retainer") translate([0, 0, -25.45]) bearing_retainer();
    else if (p == "stepper_saddle") translate([0, 0, MB_Z0]) mirror([0, 0, 1]) stepper_saddle();
    else if (p == "carriage_rail") translate([0, 0, MB_Z0]) mirror([0, 0, 1]) carriage_rails();
}

// labels readable from below (mirror Y), placed under everything at z = 14
module label(t, p, sz = 1.9, ha = "center")
    color("#111111") translate([p[0], p[1], 14]) mirror([0, 1, 0]) linear_extrude(0.2)
        text(t, size = sz, halign = ha, valign = "center", font = "DejaVu Sans:style=Bold");
// keep-out sector drawn on the board underside (SPEC: theta 60-120, r 12-32)
module spec_keepout_overlay()
    color("#f2c200") translate([0, 0, MB_Z0 - 0.08]) linear_extrude(0.06)
        difference() {
            intersection() { circle(r = 32, $fn = fn_big); polygon([[0, 0], pol(40, 60), pol(40, 120)]); }
            circle(r = 12, $fn = fn_big);
            intersection() { circle(r = 31.0, $fn = fn_big); polygon([[0, 0], pol(40, 62.5), pol(40, 117.5)]); }
        }
module board_bottom_labels() {
    label("SPEC keep-out θ60–120°", [-3, 30.0], 1.5);
    label("TMAG5273 r29 θ270", [0, -24.5]);
    label("MDBT50Q (θ215)", [-15.5, -16.0]);
    label("u.FL plug: CLASH", [-9.5, -3.5], 1.6, "right");
    label("J1 vertical: CLASH", [9.5, -16.5], 1.6);
    label("piezo", [15.6, -9.0]);
    label("VSM08102 envelope", [-1, 10.0]);
    label("detent carriage", [7.5, 27.5], 1.6, "left");
    label("Ø3×2 N52 @ r29 (click)", [7.5, 25.0], 1.6, "left");
    label("inclined-slot link", [-15.0, 21.0], 1.6);
    label("rotor envelope (ghost)", [0, -33.8], 1.6);
}

// labels for the YZ section (seen from +X: screen right = +Y)
SEC_LABELS = [
    // text, anchor [y, z], label [y, z], halign
    ["top cover + Ø30 window lens", [8, 35.7], [14, 44], "left"],
    ["opal diffuser r27-30 / light box", [28.5, 35.0], [30, 41], "left"],
    ["OLED glass on printed bracket", [-8, 33.8], [-12, 44], "right"],
    ["main board Ø64, 4-layer", [-31, 30.0], [-38, 38], "right"],
    ["J1 vertical (SPEC) hits rotor hub", [-11, 25.5], [-38, 31.5], "right"],
    ["TMAG5273 (bottom), 3.1 mm to track", [-29, 28.5], [-38, 27], "right"],
    ["316L ring, 48 magnets on top face", [-33, 22], [-38, 22.5], "right"],
    ["PA12-GF carrier web", [-20, 18.0], [-38, 18], "right"],
    ["FA lower plate (floats 0.6 mm)", [-26, 13.6], [-38, 13.5], "right"],
    ["base board + TS-1187A press switch", [-14, 10.3], [-38, 9.0], "right"],
    ["LiPo 603450 (bay z 2.5-9.0)", [-10, 5.5], [-38, 4.5], "right"],
    ["base cup + micro-suction arc pads", [-30, 1.2], [-38, 0.0], "right"],
    ["detent carriage, Ø3x2 N52 1.0 above track", [29, 27.8], [38, 31.5], "left"],
    ["stepper slider + drive pin", [15.5, 24.4], [38, 27], "left"],
    ["608-2Z on stationary Ø8 spindle", [7.6, 21.5], [38, 22.5], "left"],
    ["POM spacer / drop stop", [5, 16.6], [38, 18], "left"],
    ["FA plate rim (guide pins at θ 60/180/300)", [29, 13.6], [38, 13.5], "left"],
    ["link J3 (vertical SH) through plate window", [-9, 13.0], [38, 9.0], "left"],
];
module section_labels()
    for (l = SEC_LABELS) {
        a = l[1]; b = l[2];
        color("#555555") hull() {
            translate([2, a[0], a[1]]) cube(0.12, center = true);
            translate([2, b[0] + (l[3] == "left" ? -0.6 : 0.6), b[1]]) cube(0.12, center = true);
        }
        color("#e03131") translate([2, a[0], a[1]]) sphere(d = 0.7, $fn = 8);
        color("#111111") translate([2, b[0], b[1]]) rotate([90, 0, 90]) linear_extrude(0.1)
            text(l[0], size = 1.55, halign = l[3], valign = "center", font = "DejaVu Sans");
    }

// ==================================================================
//  VIEW DISPATCH
// ==================================================================
if (view == "assembly") assembly();
else if (view == "section") { section("yz"); section_labels(); }
else if (view == "section_xz") section("xz");
else if (view == "exploded") { exploded(); exploded_labels(); }
else if (view == "board_bottom") {
    main_board(); detent_assembly(det_offset); spindle_hub();
    spec_keepout_overlay();
    color([0.75, 0.78, 0.82, 0.15]) rotor_envelope();
    board_bottom_labels();
}
else if (view == "clash") {
    // board underside + hub + transparent rotor envelope; red = interference
    main_board(); detent_assembly(det_offset); spindle_hub();
    // nudged 0.08 mm toward the render camera so coplanar faces do not z-fight
    for (i = [0:len(STATIONARY_NAMES) - 1]) color("red") translate([0.036, -0.069, -0.036]) render(convexity = 4) clash_rotor(i);
    color([0.75, 0.78, 0.82, 0.18]) rotor_envelope();
}
else if (view == "clash_geom") {
    if (clash_mode == "rotor") { if (clash_item < 0) for (i = [0:len(STATIONARY_NAMES) - 1]) clash_rotor(i); else clash_rotor(clash_item); }
    else { if (clash_item < 0) for (i = BASE_ITEMS) clash_press(i); else clash_press(clash_item); }
}
else if (view == "part") print_part(part);
else if (view == "top") assembly();
