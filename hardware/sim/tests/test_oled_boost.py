"""OLED panel supply: U21 TPS22917 -> OLED_VIN -> U20 TPS61040 boost (L20, D21, C38/C39/C30/C31, R26/R27/C40)
-> +13V_OLED -> SSD1351 / NHD-1.5-128128G VCC (J20 pin 2).

Every passive comes from hardware/kicad/main/dial-me-spinner-main.net (Design.passives / Design.value), so a
schematic change shows up here.  IC behaviour comes from hardware/sim/models/oled_boost__*.lib, each of which
cites its datasheet (the TPS61040 model is a native-ngspice port of TI's SLVMDA8 PSpice model, cross-checked
against it).  Limits:

  * Panel VCC 12.5-13.5 V ...... NHD-1.5-128128G rev 3, Electrical Characteristics ("Supply Voltage for Display")
  * Panel ICC .................. same table: 50 % ON 29.0 mA max, 100 % ON 42.0 mA max (VCC 13 V)
  * SSD1351 VCC abs max 19 V ... Solomon SSD1351 Rev 1.3 Table 11-1
  * TPS61040 SW <= 30 V (abs max), VIN <= 6 V, f <= 1 MHz, COUT >= 1 uF, CIN 4.7 uF, L 2.2-47 uH
    (SLVS413L 5.1 / 5.3 / 7.2.2); FB <= VIN + 0.3 V (5.1 abs max) with the boost unpowered
  * L20 Isat 0.72 A (rated, 30 % L drop) ... Sunlord SWPA series datasheet rev 2019/04/01, SWPA3015S100MT row
  * D21 IFRM 1.5 A, VRRM 40 V ... CJ B5817W-5819W rev D (Mar 2015) Maximum Ratings
  * TPS22917 IPLS 2.5 A, VIN <= 5.5 V, ISD,VIN <= 100 nA ... SLVSDW8B Tables 7.1 / 7.3 / 7.5
  * VCC up before AFh: firmware waits 200 ms after OLED_VCC_EN (firmware.md 7.2 step 23 / NHD init sequence); the
    same step allows shortening it after measurement, but "the wait MUST never be below 10 ms" (hardware/sim,
    OLED-V2; SPEC 5.3).  The old floor, 5 ms, is kept as the strict-xfail evidence for the rule
    (test_startup_time_vs_firmware_floor); test_startup_time_vs_firmware_floor_with_fw_rule checks the 10 ms rule.
  * VCC must float when off: no path VSYS -> VCC ... SSD1351 Rev 1.3 8.9 note (2); TPS61040 SLVS413L 6.3.3
  * Headroom: at VCC = 12.5 V the boost must deliver the panel ICC firmware allows at that VSYS + the divider
    current (measured with VCC clamped at 12.5 V, see capability(); a run from 13 V can take ms to droop)
  * USB only, battery dead (no BQ25180 supplement): enabling VCC must not pull VSYS below 3.0 V, the level the
    +3V3 rail is designed for (architecture.md; BQ25180 SLUSE99C ILIM, 8.3.3).  Firmware rule (firmware.md 6.3 /
    7.2 / 13.3, SPEC 5.3; hardware/sim NEW-1, OLED-V1): OLED_VCC_EN stays low while ILIM = 100 mA unless the
    battery can supplement SYS; until ILIM = 500 mA the LEDs show the <= 20 mA charging cue.

Off state: EN-low states start from explicit initial conditions (init="off": U21 open, OLED_VIN at 0 V) instead of
a DC operating point.  U21's QOD is tied to OLED_VIN (SLP-1 / LSW-1 fix), so after OLED_VCC_EN falls it discharges
C38 through ~150 ohm: OLED_VIN passes the TPS61040's ~1.5 V UVLO within about 1 ms (0.5 ms at VSYS 3.0 V), the
boost stops and VCC floats near 13 V behind D21 (verified 3 ms window; the model has no UVLO hysteresis).

Supply corners: VSYS on battery = VBAT 3.0 / 3.7 / 4.2 V (BQ25180 BATFET path); on USB VSYS = SYS_REG 4.5 V
+2 % = 4.59 -> 4.6 V (BQ25180 SLUSE99C VSYS_REG_ACCURACY).  Firmware writes SYS_REG = 0x20 (4.4 V, firmware.md
13.1 row 8); 4.6 V is kept as the stress corner because 4.5 V is the POR default (before the init write, after a
BQ reset) and the only other value firmware allows.  The USB-only start-up decks (usb_start) use the firmware's
4.4 V, the lower start for the VSYS dip.  The firmware low-battery rule (firmware.md 7.4 / 12.4: below rested
VBAT 3.75 V, and while the LEDs exceed their 150 mA sustained cap, C7 <= 08h and <= 30 % white; hardware/sim
OLED-BST-2) bounds the panel load there by the 50 %-ON maximum (29 mA); above it the panel may show full white
(42 mA max).  The old threshold was 3.60 V: test_headroom_at_firmware_full_white_threshold keeps it as the
strict-xfail evidence, and icc_max() / the passing headroom, stress and temperature tests keep 3.60 V as their
(stricter) switch point, so they still assume full white at VSYS 3.6-3.75 V.

Simulation settings: gear integration, reltol 1e-3, 50 ns max step.  Checked against the harness defaults
(trap, reltol 1e-4) and a 20 ns step on the 1 mA / 23 mA / 42 mA steady states: VCC avg / min / max within 1 mV,
peak currents within 1 %.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

import spicelib

# ----------------------------------------------------------------------------------------------- constants
NETS = {"VSYS", "OLED_VIN", "OLED_BST_SW", "OLED_BST_FB", "+13V_OLED", "OLED_LSW_CT", "OLED_VCC_EN", "GND"}
LIBS = ("oled_boost__tps61040.lib", "oled_boost__tps22917.lib", "oled_boost__b5819w.lib",
        "oled_boost__ssd1351.lib")
STEP = "50n"

# limits (value, source)
VCC_MIN, VCC_MAX = 12.5, 13.5
SRC_VCC = "NHD-1.5-128128G rev 3 Electrical Characteristics: VCC 12.5-13.5 V"
VCC_ABS = 19.0
SRC_VCC_ABS = "SSD1351 Rev 1.3 Table 11-1: VCC abs max 19.0 V"
ICC_50_MAX, ICC_100_MAX = 29.0, 42.0          # mA, NHD rev 3 Electrical Characteristics (VCC 13 V)
ICC_50_TYP = 23.2
ICC_LIGHT = 1.0                               # mA: near-black content (task range 1-30 mA)
VREF_MIN, VREF_TYP, VREF_MAX = 1.208, 1.233, 1.258
SRC_VFB = "TPS61040 SLVS413L 5.5 VFB 1.208-1.258 V with eq. 5 VOUT = VFB (1 + R1/R2)"
L20_ISAT = 0.72
SRC_ISAT = "Sunlord SWPA rev 2019/04/01, SWPA3015S100MT: Isat 0.72 A rated (30 % L drop)"
D21_IFRM = 1.5
SRC_IFRM = "CJ B5819W rev D Maximum Ratings: IFRM 1.5 A"
SW_MAX = 30.0
SRC_SW = "TPS61040 SLVS413L 5.1 abs max: SW 30 V"
FSW_MAX = 1.0e6
SRC_FSW = "TPS61040 SLVS413L 5.3: switching frequency <= 1 MHz"
U21_IPLS = 2.5
SRC_IPLS = "TPS22917 SLVSDW8B Table 7.1: IPLS 2.5 A (< 300 us, 2 % duty), IMAX 2 A"
U21_ISD_MAX = 100e-9
SRC_ISD = "TPS22917 SLVSDW8B Table 7.5: ISD,VIN 100 nA max (-40..85 C)"
T_AF = 0.200
SRC_TAF = "firmware.md 7.2 step 23 (vendor sequence): AFh 200 ms after OLED_VCC_EN, VCC must be in range by then"
T_AF_MIN_OLD = 5e-3      # OLD firmware floor, kept as the strict-xfail evidence for OLED-V2
SRC_TAF_MIN_OLD = ("OLD firmware.md 7.2 step 23: the VCC-to-AFh wait may be shortened after measurement, "
                   "'never below 5 ms' (superseded by OLED-V2: 10 ms)")
T_AF_MIN_FW = 10e-3      # firmware rule OLED-V2
SRC_TAF_MIN_FW = ("firmware rule (hardware/sim, OLED-V2): firmware.md 7.2 step 23 'the wait MUST never be below "
                  "10 ms', 3.1 oled_vcc startup-delay-us = <10000>; SPEC 5.3")
SRC_FLOAT = ("SSD1351 Rev 1.3 8.9 note (2) VCC floats when off / note (1) held near VCI by ESD path; "
             "TPS61040 SLVS413L 6.3.3 (disabled boost passes VIN to VOUT)")

# supply corners
VSYS_BAT = (3.0, 3.7, 4.2)                    # VBAT corners (VSYS = VBAT through the BATFET)
VSYS_USB = 4.6                                # BQ25180 SYS_REG POR default 4.5 V + 2 % (SLUSE99C VSYS_REG_ACCURACY):
#                                               the stress corner (firmware writes 4.4 V, 4.5 V is the only other
#                                               allowed value and the state before init / after a BQ reset)
SYS_REG_FW = 4.4                              # firmware.md 13.1 row 8: SYS_REG = 0x20 -> SYS 4.4 V on USB
VSYS_FW_OLD = 3.6                             # OLD firmware.md 7.4 full-white threshold (OLED-BST-2 evidence); also
#                                               the stricter switch point icc_max() keeps for the passing tests
VSYS_FW_RULE = 3.75                           # firmware.md 7.4 / 12.4: full white only from rested VBAT 3.75 V
SRC_FW_BST2 = ("firmware rule (hardware/sim, OLED-BST-2): firmware.md 7.4 / 12.4, SPEC 5.3: C7 <= 08h and "
               "<= 30 % white below rested VBAT 3.75 V and while the LEDs exceed their 150 mA sustained cap")
# VSYS source: BQ25180 RON_BAT 55 mOhm typ (SLUSE99C 7.5) + link harness 8.5 + 5.7 mOhm (architecture.md 4.2)
R_SRC = 0.055 + 0.0085 + 0.0057


def icc_max(vsys: float) -> float:
    """Panel VCC current the passing tests load the boost with at this VSYS: full white (42 mA) from the OLD 3.60 V
    threshold up, the 50 %-ON maximum (29 mA) below it.  firmware.md 7.4 now caps the panel below rested VBAT
    3.75 V (OLED-BST-2), so between 3.60 and 3.75 V this asks for more than firmware allows: kept on purpose (moving
    the switch point to 3.75 V would lower the 3.7 V load in the headroom and stress tests from 42 to 29 mA)."""
    return ICC_100_MAX if vsys >= VSYS_FW_OLD else ICC_50_MAX


# TPS61040 corners from SLVS413L 5.5 (typ / min / max).  "weak" = least output capability, "strong" = largest
# peak current and fastest repetition.
U20_TYP = dict(ILIM=0.400, TOFF=400e-9, TONMAX=6e-6, VREF=VREF_TYP, RDS=0.6, IQ=28e-6, IFB=0.0, UVLO=1.5)
U20_WEAK = dict(U20_TYP, ILIM=0.350, TOFF=550e-9, TONMAX=4e-6, RDS=1.0)
U20_STRONG = dict(U20_TYP, ILIM=0.450, TOFF=250e-9, TONMAX=7.5e-6)
IFB_MAX = 1e-6                                # SLVS413L 5.5 IFB max (sign not given: both are tested)

# Passive parasitics from their datasheets
L20_DCR_TYP, L20_DCR_MAX = 0.250, 0.325       # Sunlord SWPA3015S100MT DCR typ / max (20 C)
CU_TCR = 0.00393                              # copper resistance tempco (1/K), DCR referenced to 20 C
C_ESR = 0.008                                 # Samsung CL21A106 |ESR| 5-10 mOhm at 0.1-2 MHz (char. sheet)
# DC-bias derating, Samsung CL21A106KAYNNNG characteristic sheet (0805 / 25 V / X5R, same family as C30 and
# C39 - no sheet was found for the 4.7 uF CL21A475KAQNNNE, the 10 uF curve is used for both): dC = -71 % at
# 13 V, about -20 % at 3-4.6 V (C38 on OLED_VIN).  "derate=True" is the worst ripple / overshoot corner; the
# nominal (marked) values give the largest inrush and the slowest start.
DERATE_13V = 0.29
DERATE_VSYS = 0.80
# The same three curve points (0 V: 1.0, ~4 V: 0.80, 13 V: 0.29), integrated: a cap charged 0 -> 13 V stores
# E = int V C(V) dV, i.e. this fraction of 1/2 C_marked 13^2.  Used where the charge drawn from VSYS during start-up
# matters (marked values overstate it, the 13 V value understates it).
_DB = ((0.0, 1.0), (4.0, DERATE_VSYS), (13.0, DERATE_13V))
DERATE_ENERGY = sum((b[0] - a[0]) * (a[0] * (2 * a[1] + b[1]) + b[0] * (a[1] + 2 * b[1])) / 6
                    for a, b in zip(_DB, _DB[1:])) / (13.0 ** 2 / 2)          # = 0.535

TEMPS = (-10.0, 25.0, 60.0)
WEAK_PASSIVES = dict(ron=0.140, dcr=L20_DCR_MAX, scale={"L20": 0.8})  # TPS22917 RON max, DCR max, L -20 %


def u20_at(temp: float, base: dict) -> dict:
    """Scale the typical-curve TPS61040 parameters to `temp` (C).  Min/max corners are taken as given."""
    p = dict(base)
    if base["RDS"] < 0.99:   # Fig 5-10: 480 mOhm at -40 C to 800 mOhm at 90 C (linear), 640 mOhm at 25 C
        p["RDS"] = base["RDS"] * (480 + 320 / 130 * (temp + 40)) / 640
    p["VREF"] = base["VREF"] - (0.0 if temp >= 0 else 1.0e-3 * (-temp) / 40)   # Fig 5-6 drift
    p["ILIM"] = base["ILIM"] * (1 + 1.15e-4 * (temp - 25))                      # Fig 5-7: 398 -> 404 mA
    p["IQ"] = base["IQ"] * (1 + 0.0055 * (temp - 25))                           # Fig 5-5: 21 / 27 / 33.5 uA
    return p


def u21_ron(temp: float) -> float:
    """TPS22917 RON at VIN 3.6 V, SLVSDW8B Table 7.5: 90 mOhm typ at 25 C (140 mOhm max over -40..85 C)."""
    return 0.090 * (1 + 0.004 * (temp - 25))


def u21_ct_ready(vsys: float) -> float:
    """CT node voltage of the U21 model once its turn-on ramp is complete (to start in steady state)."""
    v = min(max(vsys, 1.8), 5.0)
    ict = 1.1e-6 + (v - 1.8) * (0.8e-6 / 1.8) if v < 3.6 else 1.9e-6 + (v - 3.6) * (0.4e-6 / 1.4)
    tonk = 3.6e6 + (v - 1.8) * (0.2e6 / 1.8) if v < 3.6 else 3.8e6 + (v - 3.6) * (0.2e6 / 1.4)
    vdel = ict * tonk - 0.9 * v
    return vsys - (vdel + vsys + 1.0)


def cout_effective(d) -> float:
    """Every FITTED capacitor between +13V_OLED and GND in the netlist (so a part left off or a changed value is
    seen), at its minimum tolerance; parts >= 1 uF get the X5R DC-bias derating at 13 V."""
    tot = 0.0
    for ref in d.on_net("+13V_OLED", "C"):
        if not d.fitted(ref) or ref in d._shorted or set(d.pins[ref].values()) != {"+13V_OLED", "GND"}:
            continue
        c = d.value(ref) * (1 - d.tol(ref))
        tot += c * (DERATE_13V if d.value(ref) >= 1e-6 else 1.0)
    return tot


def cin_fitted(d) -> float:
    """Marked value of every fitted capacitor between OLED_VIN (U20 VIN) and GND in the netlist."""
    return sum(d.value(r) for r in d.on_net("OLED_VIN", "C")
               if d.fitted(r) and r not in d._shorted and set(d.pins[r].values()) == {"OLED_VIN", "GND"})


def ipeak_eq1(vin: float, l_h: float, ilim: float = 0.450) -> float:
    """TPS61040 SLVS413L 6.3.1 eq. 1: Ipeak = ILIM + VIN / L x 100 ns (ILIM max 450 mA, 5.5)."""
    return ilim + vin / l_h * 100e-9


def pwl(points) -> str:
    return "PWL(" + " ".join(f"{t:.9g} {v:.9g}" for t, v in points) + ")"


def pmap(fn, items):
    """Run independent decks in parallel (each Deck.run is its own ngspice process)."""
    items = list(items)
    with ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1, len(items)))) as ex:
        return list(ex.map(fn, items))


def soft_checks(check, rows):
    """Record every (name, value, lo, hi, unit, source) row, then fail if any is out of limits."""
    bad = []
    for row in rows:
        try:
            check(*row)
        except AssertionError as e:
            bad.append(str(e))
    assert not bad, "\n".join(bad)


def build(d, title, *, vsys=3.7, temp=25.0, u20=None, ron=None, dcr=None, scale=None, derate=True,
          icc=ICC_LIGHT, en="on", t_en=20e-6, init="steady", vcc0=None, vsys_pwl=None):
    """ngspice deck for the whole OLED supply path, parts and connections taken from the main-board netlist.

    icc   : panel VCC current in mA (number) or a list of (t, mA) PWL points
    en    : "on" (OLED_VCC_EN high from t = 0), "step" (low until t_en, then high), "off_at" (high until t_en)
    init  : "steady" (start at the regulated point: output charged, U21 fully on, soft start done; run with uic)
            or "off" (long-term off state: U21 open, OLED_VIN 0 V, VCC near VCI via the panel ESD path; uic)
    """
    u20 = dict(u20_at(temp, U20_TYP) if u20 is None else u20)
    ron = u21_ron(temp) if ron is None else ron
    dcr = (L20_DCR_TYP if dcr is None else dcr) * (1 + CU_TCR * (temp - 20))
    sc = dict(scale or {})
    if derate:   # X5R bulk caps (>= 1 uF) on the boost output and input, found from the netlist
        k13 = DERATE_ENERGY if derate == "energy" else DERATE_13V      # "energy": start-up charge from VSYS
        for net, k in (("+13V_OLED", k13), ("OLED_VIN", DERATE_VSYS)):
            for ref in d.on_net(net, "C"):
                if set(d.pins[ref].values()) == {net, "GND"} and d.value(ref) >= 1e-6:
                    sc[ref] = sc.get(ref, 1.0) * k
    n = {k: d.node(k) for k in ("VSYS", "OLED_VIN", "OLED_BST_SW", "OLED_BST_FB", "+13V_OLED", "OLED_LSW_CT",
                                "OLED_VCC_EN", "+3V3")}
    deck = spicelib.Deck(title)
    for lib in LIBS:
        deck.include(lib)
    deck.options = [o for o in deck.options if "reltol" not in o] + ["option reltol=1e-3", "option method=gear",
                                                                       f"temp {temp:g}"]
    # supplies: VSYS through the BATFET + harness, +3V3 (VCI) always on
    deck += f"VSRC n_vsys_src 0 {pwl(vsys_pwl) if vsys_pwl else vsys}"   # vsys_pwl: line transient (starts at vsys)
    deck += f"RSRC n_vsys_src {n['VSYS']} {R_SRC:.6g}"
    deck += f"V3V3 {n['+3V3']} 0 3.3"
    # OLED_VCC_EN from nRF P1.02 (standard drive, ~100 ohm)
    if en == "on":
        deck += "VEN n_en_drv 0 3.3"
    elif en == "step":
        deck += "VEN n_en_drv 0 " + pwl([(0, 0), (t_en, 0), (t_en + 1e-7, 3.3)])
    elif en == "off_at":
        deck += "VEN n_en_drv 0 " + pwl([(0, 3.3), (t_en, 3.3), (t_en + 1e-7, 0)])
    else:
        deck += "VEN n_en_drv 0 0"
    deck += f"RGPIO n_en_drv {n['OLED_VCC_EN']} 100"
    # every netlist passive on these nets (C1/C2/C6/C41/C70/C72/C74 on VSYS, C37 CT, C38, R25, R26, R27, C40,
    # C30, C31, C39) with ESR on the boost caps; L20 is added below with its DCR
    esr = {r: C_ESR for r in ("C30", "C38", "C39")}
    deck += d.passives(nets=NETS, exclude=("L20",), scale=sc, esr=esr)
    # L20 written OLED_VIN -> DCR -> L -> OLED_BST_SW so that i(ll20) is the inductor current into SW
    assert set(d.pins["L20"].values()) == {"OLED_VIN", "OLED_BST_SW"}, d.pins["L20"]
    if d.fitted("L20"):
        if "L20" in d._shorted:
            deck += f"VL20_short {n['OLED_VIN']} {n['OLED_BST_SW']} 0"
        else:
            deck += f"RL20_dcr {n['OLED_VIN']} n_l20_dcr {dcr:.6g}"
            deck += f"LL20 n_l20_dcr {n['OLED_BST_SW']} {d.value('L20') * sc.get('L20', 1.0):.6g}"
    # U21 TPS22917 with a current probe in VIN
    deck += f"VPRB_U21 {d.pin('U21', 'VIN')} n_u21_vin 0"
    deck += (f"XU21 n_u21_vin {d.pin('U21', 'GND')} {d.pin('U21', 'ON')} {d.pin('U21', 'CT')} "
             f"{d.pin('U21', 'QOD')} {d.pin('U21', 'VOUT')} TPS22917_OB params: RON={ron:.6g}")
    # U20 TPS61040
    prm = " ".join(f"{k}={v:.6g}" for k, v in u20.items())
    deck += (f"XU20 {d.pin('U20', 'EN')} {d.pin('U20', 'FB')} {d.pin('U20', 'SW')} {d.pin('U20', 'VIN')} "
             f"{d.pin('U20', 'GND')} TPS61040_OB params: {prm}")
    # D21 B5819W with a current probe at the anode
    deck += f"VPRB_D21 {d.pin('D21', 'A')} n_d21_a 0"
    deck += f"XD21 n_d21_a {d.pin('D21', 'K')} B5819W_OB params: TA={temp:g}"
    # panel VCC load on J20 pin 2 (VCC), VCI on pin 27
    deck += f"XJ20 {d.pin('J20', '2')} {d.pin('J20', '27')} 0 n_icc SSD1351_VCC_OB"
    deck += f"VICC n_icc 0 {pwl(icc) if isinstance(icc, (list, tuple)) else icc}"
    if init == "steady":
        r26, r27 = d.value("R26") * sc.get("R26", 1.0), d.value("R27") * sc.get("R27", 1.0)
        v0 = vcc0 if vcc0 is not None else min(u20["VREF"] * (1 + r26 / r27), 18.0)
        vfb0 = v0 * r27 / (r26 + r27) if d.fitted("R26") and d.fitted("R27") else u20["VREF"]
        ics = {n["VSYS"]: vsys, n["OLED_VIN"]: vsys, n["OLED_BST_SW"]: vsys, "n_l20_dcr": vsys, "n_d21_a": vsys,
               "n_u21_vin": vsys, n["+13V_OLED"]: v0, n["OLED_BST_FB"]: vfb0,
               n["OLED_LSW_CT"]: u21_ct_ready(vsys), n["OLED_VCC_EN"]: 3.3, "xu20.cnt": 600, "xu20.ena": 1,
               "xu21.en": 1}   # xu20.ena = 1: enabled from t = 0, else the soft-start count is cleared at t = 0
        deck += ".ic " + " ".join(f"v({k})={v:.6g}" for k, v in ics.items())
    elif init == "off":
        # long after OLED_VCC_EN went low: U21 open (CT = VIN), OLED_VIN drained to 0 V (worst case for the FB pin
        # abs max), VCC held below VCI by the panel ESD path (SSD1351 8.9 note (1)) and settling from there
        v0 = 3.3 - 0.4 if vcc0 is None else vcc0     # above the ESD-path equilibrium: settles from above
        r26, r27 = d.value("R26"), d.value("R27")
        ics = {n["VSYS"]: vsys, n["OLED_VIN"]: 0, n["OLED_BST_SW"]: 0, "n_l20_dcr": 0, "n_d21_a": 0,
               "n_u21_vin": vsys, n["+13V_OLED"]: v0, n["OLED_BST_FB"]: v0 * r27 / (r26 + r27),
               n["OLED_LSW_CT"]: vsys, n["OLED_VCC_EN"]: 0, "xu20.cnt": 0, "xu21.en": 0}
        deck += ".ic " + " ".join(f"v({k})={v:.6g}" for k, v in ics.items())
    return deck


def run(deck, tstop, uic=True, tmax=None, may_miss=()):
    """Run a transient; `may_miss` lists WHEN-measures that legitimately find no crossing (they come back as
    +inf so that the check, not the harness, reports the failure)."""
    extra = " ".join(x for x in (tmax or "", "uic" if uic else "") if x)
    deck.tran(STEP, f"{tstop:.6g}", 0, extra)
    res = deck.run(timeout=900)
    errors = [e for e in res["_errors"] if not any(f"meas tran {m} " in e.lower() for m in may_miss)]
    assert not errors, "\n".join(errors[:10]) + "\n" + res["_log"][-3000:]
    missing = [m for m in res.get("_missing", []) if m not in may_miss]
    assert not missing, f"missing measures {missing}\n" + res["_log"][-3000:]
    for m in may_miss:
        res.setdefault(m, float("inf"))
    return res


def meas_window(deck, t0, t1, freq=False):
    w = f"FROM={t0:.6g} TO={t1:.6g}"
    deck.meas(f"tran vavg AVG v(n_p13v_oled) {w}")
    deck.meas(f"tran vmax MAX v(n_p13v_oled) {w}")
    deck.meas(f"tran vmin MIN v(n_p13v_oled) {w}")
    deck.meas(f"tran ilpk MAX i(ll20) {w}")
    deck.meas(f"tran idpk MAX i(vprb_d21) {w}")
    deck.meas(f"tran swpk MAX v(n_oled_bst_sw) {w}")
    deck.meas(f"tran vinmax MAX v(n_oled_vin) {w}")
    deck.meas(f"tran iin AVG i(vprb_u21) {w}")
    if freq:   # 20 switching cycles: inductor current rising through 0.2 A (above it in every full-ILIM pulse)
        deck.meas(f"tran tc1 WHEN i(ll20)=0.2 RISE=2 {w}")
        deck.meas(f"tran tc2 WHEN i(ll20)=0.2 RISE=22 {w}")


def steady(d, title, *, t_settle=0.3e-3, t_meas=0.5e-3, freq=False, **kw):
    """Run from the regulated state; VCC avg / min / max and peak currents over the last t_meas."""
    deck = build(d, title, **kw)
    t1 = t_settle + t_meas
    meas_window(deck, t_settle, t1, freq=freq)
    res = run(deck, t1)
    if freq:
        res["fsw"] = 20.0 / (res["tc2"] - res["tc1"])
    return res


def capability(d, title, *, vsys, **kw):
    """Largest average current the boost delivers into VCC held at the panel minimum (12.5 V) by an ideal
    source: with VCC below the set point FB < VREF, so the TPS61040 runs flat out.  Because the deliverable
    current rises as VOUT falls, capability >= load at 12.5 V means the loaded equilibrium is >= 12.5 V.
    (A time-domain run from 13 V can take several ms to droop to that equilibrium, so it is not used here.)"""
    deck = build(d, title, vsys=vsys, icc=0.0, derate=True, vcc0=VCC_MIN, **kw)
    deck += f"VCLAMP {d.node('+13V_OLED')} 0 {VCC_MIN}"
    deck.meas("tran idav AVG i(vprb_d21) FROM=0.05m TO=0.25m")
    return run(deck, 0.25e-3)["idav"]


def load_at_min(d, icc_ma: float) -> float:
    """Current the boost must deliver at VCC = 12.5 V: panel ICC plus the R26/R27 divider (netlist values)."""
    return icc_ma * 1e-3 + VCC_MIN / (d.value("R26") + d.value("R27"))


def startup(d, title, *, vsys, tstop, derate, **kw):
    """OLED_VCC_EN low -> high at 20 us from the long-term off state (init="off": OLED_VIN 0 V, where U21's QOD,
    tied to OLED_VIN, holds it; VCC held by the panel ESD path; explicit initial conditions, no DC operating
    point), panel display off: ICC = 0."""
    deck = build(d, title, vsys=vsys, icc=0.0, derate=derate, en="step", t_en=20e-6, init="off", **kw)
    deck.meas(f"tran tvin90 WHEN v(n_oled_vin)={0.9 * vsys:.6g} RISE=1")
    deck.meas(f"tran tup WHEN v(n_p13v_oled)={VCC_MIN} RISE=1")
    deck.meas("tran vpk MAX v(n_p13v_oled)")
    deck.meas("tran iu21pk MAX i(vprb_u21)")
    deck.meas("tran ilpk MAX i(ll20)")
    deck.meas("tran idpk MAX i(vprb_d21)")
    deck.meas("tran swpk MAX v(n_oled_bst_sw)")
    deck.meas(f"tran iu21avg AVG i(vprb_u21) FROM=20u TO={tstop:.6g}")
    deck.meas(f"tran vend AVG v(n_p13v_oled) FROM={tstop - 0.3e-3:.6g} TO={tstop:.6g}")
    return run(deck, tstop, may_miss=("tup", "tvin90"))


# =============================================================================================== tests
def test_static_ratings(main, check):
    """Netlist values against the TPS61040 recommended operating conditions and application rules."""
    d = main
    lo = lambda r: d.value(r) * (1 - d.tol(r))   # noqa: E731
    hi = lambda r: d.value(r) * (1 + d.tol(r))   # noqa: E731
    check("L20 min (tolerance)", lo("L20"), 2.2e-6, None, "H", "TPS61040 SLVS413L 5.3 / 7.2.2.1: L 2.2-47 uH")
    check("L20 max (tolerance)", hi("L20"), None, 47e-6, "H", "TPS61040 SLVS413L 7.2.2.1: L 2.2-47 uH")
    check("COUT effective at 13 V (fitted netlist caps, min tol, DC bias)", cout_effective(d), 1e-6, None, "F",
          "TPS61040 SLVS413L 5.3: COUT >= 1 uF (Samsung CL21A106 DC-bias -71 % at 13 V)")
    check("CIN fitted at U20 (marked, OLED_VIN to GND)", cin_fitted(d), 4.7e-6, None, "F",
          "TPS61040 SLVS413L 5.3 CIN 4.7 uF (recommended) / 7.2.2.5")
    check("R27 (R2 of the divider)", d.value("R27"), None, 200e3, "ohm", "TPS61040 SLVS413L 7.2.2.2: R2 <= 200 kOhm")
    check("R26 (R1 of the divider)", d.value("R26"), None, 2.2e6, "ohm", "TPS61040 SLVS413L 7.2.2.2: R1 <= 2.2 MOhm")
    check("VSYS max at U21 VIN", VSYS_USB, None, 5.5, "V", "TPS22917 SLVSDW8B Table 7.3: VIN <= 5.5 V")
    check("VSYS max at U20 VIN", VSYS_USB, None, 6.0, "V", "TPS61040 SLVS413L 5.3: VIN <= 6 V")
    check("D21 reverse voltage (VCC abs max)", VCC_ABS, None, 40.0, "V", "CJ B5819W rev D: VRRM 40 V")
    # SLVS413L 6.3.1 eq. 1 / 7.2.2.1: size L and D for ILIM max + VIN / L x 100 ns at the highest VIN, lowest L
    ipk = ipeak_eq1(VSYS_USB, lo("L20"))
    check("worst-case switch / L20 peak, eq. 1 (ILIM max, VIN 4.6 V, L min)", ipk, None, L20_ISAT, "A",
          "TPS61040 SLVS413L eq. 1 + 7.2.2.1 (use ILIM max); " + SRC_ISAT)
    check("worst-case D21 peak, eq. 1", ipk, None, D21_IFRM, "A", "TPS61040 SLVS413L 7.2.2.6; " + SRC_IFRM)


def test_nominal_regulation(main, check):
    """VBAT 3.7 V, 25 C, typical parts, marked capacitor values: light (1 mA) and 50 %-ON typ (23.2 mA)."""
    vset = (VREF_MIN * (1 + main.value("R26") / main.value("R27")),
            VREF_MAX * (1 + main.value("R26") / main.value("R27")))
    rows = []
    for icc in (ICC_LIGHT, ICC_50_TYP):
        r = steady(main, f"nominal {icc} mA", icc=icc, derate=False, t_meas=0.8e-3 if icc < 5 else 0.4e-3)
        rows += [(f"VCC avg, VBAT 3.7 V, {icc} mA", r["vavg"], VCC_MIN, VCC_MAX, "V", SRC_VCC),
                 (f"VCC min, VBAT 3.7 V, {icc} mA", r["vmin"], VCC_MIN, None, "V", SRC_VCC),
                 (f"VCC max, VBAT 3.7 V, {icc} mA", r["vmax"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC avg in the eq. 5 set-point band, {icc} mA", r["vavg"], vset[0], vset[1], "V", SRC_VFB)]
    soft_checks(check, rows)


def _tolerance_runs(d, ifb):
    """VFB max / light load / derated caps / USB (highest VCC) and VFB min / full white at the OLD firmware
    full-white threshold (3.6 V: lowest VCC; firmware.md 7.4 now allows full white only from 3.75 V, so 3.6 V is
    kept as the stricter corner), for every R26/R27 tolerance corner (Design.extremes), with FB bias current `ifb`
    pushing the same way."""
    jobs = []
    for corner in d.extremes(["R26", "R27"]):
        jobs.append(("hi", corner, dict(U20_TYP, VREF=VREF_MAX, IFB=+ifb), 4.6, ICC_LIGHT))
        jobs.append(("lo", corner, dict(U20_TYP, VREF=VREF_MIN, IFB=-ifb), VSYS_FW_OLD, ICC_100_MAX))

    def one(job):
        side, corner, u20, vsys, icc = job
        r = steady(d, f"tol {side} {corner}", vsys=vsys, icc=icc, u20=u20, scale=corner, derate=True,
                   t_meas=0.5e-3 if side == "hi" else 0.25e-3)
        return side, corner, r
    return pmap(one, jobs)


def test_regulation_over_divider_and_reference_tolerance(main, check):
    """R26 0.5 % / R27 0.1 % extremes x VFB 1.208 / 1.258 V: VCC (incl. ripple) stays in the panel window."""
    out = _tolerance_runs(main, ifb=0.0)
    vmax = max(r["vmax"] for s, _, r in out if s == "hi")
    vmin = min(r["vmin"] for s, _, r in out if s == "lo")
    soft_checks(check, [("VCC max: VFB max, R corners, 1 mA, VSYS 4.6 V", vmax, None, VCC_MAX, "V",
                         SRC_VCC + "; " + SRC_VFB),
                        ("VCC min: VFB min, R corners, 42 mA, VSYS 3.6 V", vmin, VCC_MIN, None, "V",
                         SRC_VCC + "; " + SRC_VFB)])


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: the 499k/52.3k divider turns the TPS61040 FB bias current "
                   "(1 uA max, SLVS413L 5.5) into +-0.5 V on VCC; worst case leaves the 12.5-13.5 V panel window")
def test_regulation_with_fb_bias_current(main, check):
    """Same corners as above plus the datasheet FB input bias current (|IFB| <= 1 uA, sign not specified)."""
    out = _tolerance_runs(main, ifb=IFB_MAX)
    vmax = max(r["vmax"] for s, _, r in out if s == "hi")
    vmin = min(r["vmin"] for s, _, r in out if s == "lo")
    soft_checks(check, [("VCC max with IFB +1 uA: VFB max, R corners, 1 mA", vmax, None, VCC_MAX, "V",
                         SRC_VCC + "; " + SRC_VFB + "; IFB 1 uA max"),
                        ("VCC min with IFB -1 uA: VFB min, R corners, 42 mA", vmin, VCC_MIN, None, "V",
                         SRC_VCC + "; " + SRC_VFB + "; IFB 1 uA max")])


def test_ripple_light_and_full_load(main, check):
    """Output ripple with DC-bias-derated output caps and the strong TPS61040 corner (largest pulse energy)."""
    # light load: L20 +20 % (largest energy per pulse); full load: L20 -20 % (highest pulse rate)
    jobs = [(vs, icc, {"L20": 1.2 if icc < 5 else 0.8}) for vs in (VSYS_BAT[1], VSYS_USB)
            for icc in (ICC_LIGHT, ICC_100_MAX)]

    def one(job):
        vs, icc, sc = job
        return job, steady(main, f"ripple {vs} V {icc} mA {sc}", vsys=vs, icc=icc, derate=True,
                           u20=dict(U20_STRONG), scale=sc, t_meas=0.6e-3 if icc < 5 else 0.25e-3,
                           freq=icc > 5)
    rows = []
    for (vs, icc, sc), r in pmap(one, jobs):
        tag = f"VSYS {vs} V, {icc} mA, L20 x{sc['L20']}"
        rows += [(f"VCC max, {tag}", r["vmax"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC min, {tag}", r["vmin"], VCC_MIN, None, "V", SRC_VCC),
                 (f"VCC ripple p-p, {tag}", r["vmax"] - r["vmin"], None, VCC_MAX - VCC_MIN, "V",
                  SRC_VCC + " (ripple must fit the window)")]
        if icc > 5:
            rows.append((f"switching frequency, {tag}", r["fsw"], None, FSW_MAX, "Hz", SRC_FSW))
    soft_checks(check, rows)


SRC_HEADROOM = ("NHD rev 3: ICC 100 % ON 42 mA / 50 % ON 29 mA max at VCC 13 V, VCC >= 12.5 V; "
                "load cap per firmware.md 7.4; + R26/R27 divider current")


def _headroom_rows(d, corners, weak=True, temp=25.0):
    def one(job):
        vs, icc = job
        kw = dict(u20=dict(U20_WEAK), **WEAK_PASSIVES) if weak else dict(temp=temp)
        return job, capability(d, f"capability {vs} V", vsys=vs, **kw)
    tag = "weak parts" if weak else f"typ parts {temp:g} C"
    return [(f"boost current at VCC 12.5 V, {tag}, VSYS {vs} V (load {icc:g} mA + divider)", i,
             load_at_min(d, icc), None, "A", SRC_HEADROOM) for (vs, icc), i in pmap(one, corners)]


def test_supply_corners_headroom(main, check):
    """Weak TPS61040 (ILIM 350 mA, toff 550 ns, ton 4 us, RDS 1 ohm), L20 -20 %, DCR max, U21 RON max: at every
    VSYS corner the boost must deliver, at VCC = 12.5 V, the largest panel load firmware allows there plus the
    FB divider current (3.0 V: 29 mA low-battery cap; 3.7 / 4.2 / 4.6 V: 42 mA full white)."""
    corners = [(3.0, icc_max(3.0)), (3.7, icc_max(3.7)), (4.2, icc_max(4.2)), (VSYS_USB, icc_max(VSYS_USB))]
    soft_checks(check, _headroom_rows(main, corners))


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (firmware-dependent, OLED-BST-2): at the OLD firmware "
                   "full-white threshold (VBAT 3.60 V) a worst-case TPS61040 + L20 delivers only ~41 mA at VCC 12.5 V, "
                   "less than the 42 mA NHD 100 %-ON maximum; VCC settles near 12.3 V. firmware.md 7.4 now caps the "
                   "panel below rested VBAT 3.75 V: see test_headroom_at_firmware_full_white_threshold_with_fw_rule")
def test_headroom_at_firmware_full_white_threshold(main, check):
    """Same weak-part stack at VSYS 3.6 V, the lowest voltage at which the OLD firmware still allowed full white."""
    soft_checks(check, _headroom_rows(main, [(VSYS_FW_OLD, icc_max(VSYS_FW_OLD))]))


def test_headroom_at_firmware_full_white_threshold_with_fw_rule(main, check):
    """GUARD for the firmware rule OLED-BST-2 (hardware/sim; firmware.md 7.4 / 12.4, SPEC 5.3): C7 <= 08h and
    <= 30 % white below rested VBAT 3.75 V, so full white (42 mA NHD 100 %-ON maximum) is allowed only from
    3.75 V.  Same weak-part stack as test_headroom_at_firmware_full_white_threshold (ILIM 350 mA, toff 550 ns,
    ton 4 us, RDS 1 ohm, L20 -20 %, DCR max, U21 RON max) at VSYS 3.75 V: at 25 C as there, plus -10 / 60 C.
    Below 3.75 V the 29 mA cap is covered down to 3.0 V by test_supply_corners_headroom."""
    vs, icc = VSYS_FW_RULE, ICC_100_MAX

    def one(temp):
        return temp, capability(main, f"capability {vs} V {temp:g} C (fw rule)", vsys=vs, temp=temp,
                                u20=dict(U20_WEAK), **WEAK_PASSIVES)
    soft_checks(check, [(f"boost current at VCC 12.5 V, weak parts, {temp:g} C, VSYS {vs} V (fw rule OLED-BST-2: "
                         f"full white only from rested VBAT 3.75 V; load {icc:g} mA + divider)", i,
                         load_at_min(main, icc), None, "A", SRC_HEADROOM + "; " + SRC_FW_BST2)
                        for temp, i in pmap(one, TEMPS)])


def test_peak_currents_and_stress(main, check):
    """Strong TPS61040 (ILIM 450 mA, toff 250 ns), L20 -20 % (largest Vin/L x 100 ns overshoot), full load:
    inductor / rectifier peak current, SW voltage and switching frequency at every VSYS corner."""
    jobs = [(vs, icc_max(vs)) for vs in VSYS_BAT + (VSYS_USB,)]

    def one(job):
        vs, icc = job
        return job, steady(main, f"stress {vs} V", vsys=vs, icc=icc, derate=True, u20=dict(U20_STRONG),
                           scale={"L20": 0.8}, t_meas=0.2e-3, freq=True)
    rows = []
    for (vs, icc), r in pmap(one, jobs):
        lmin = main.value("L20") * 0.8
        rows += [(f"L20 peak current, VSYS {vs} V", r["ilpk"], None, L20_ISAT, "A", SRC_ISAT),
                 (f"L20 peak vs TPS61040 current limit (eq. 1 bound {ipeak_eq1(vs, lmin):.3f} A), VSYS {vs} V",
                  r["ilpk"], None, ipeak_eq1(vs, lmin), "A", "TPS61040 SLVS413L 6.3.1 eq. 1, ILIM max 450 mA"),
                 (f"D21 peak current, VSYS {vs} V", r["idpk"], None, D21_IFRM, "A", SRC_IFRM),
                 (f"SW peak voltage, VSYS {vs} V", r["swpk"], None, SW_MAX, "V", SRC_SW),
                 (f"switching frequency, VSYS {vs} V, {icc} mA", r["fsw"], None, FSW_MAX, "Hz", SRC_FSW),
                 (f"U20 VIN max, VSYS {vs} V", r["vinmax"], None, 6.0, "V", "TPS61040 SLVS413L 5.3: VIN <= 6 V")]
    soft_checks(check, rows)


def test_temperature(main, check):
    """-10 / 25 / 60 C: TPS61040 RDS(on) (Fig 5-10), ILIM (Fig 5-7), VFB (Fig 5-6), IQ (Fig 5-5); B5819W forward
    drop and leakage (curves); L20 DCR (copper); TPS22917 RON.  Boost capability at VCC 12.5 V with typical parts
    at the low-battery load (3.0 V, 29 mA) and the OLD full-white threshold (3.6 V, 42 mA; kept as the stricter
    corner, firmware.md 7.4 now allows full white only from 3.75 V) - RDS(on) and DCR rise
    with temperature - and USB at light load (highest VCC, largest D21 leakage)."""
    rows = []
    for t in TEMPS:
        rows += _headroom_rows(main, [(3.0, icc_max(3.0)), (VSYS_FW_OLD, icc_max(VSYS_FW_OLD))], weak=False,
                               temp=t)

    def one(t):
        return t, steady(main, f"temp {t} C light", temp=t, vsys=VSYS_USB, icc=ICC_LIGHT, derate=True,
                         t_meas=0.6e-3)
    for t, r in pmap(one, TEMPS):
        rows += [(f"VCC min, {t:g} C, VSYS {VSYS_USB} V, {ICC_LIGHT} mA", r["vmin"], VCC_MIN, None, "V", SRC_VCC),
                 (f"VCC max, {t:g} C, VSYS {VSYS_USB} V, {ICC_LIGHT} mA", r["vmax"], None, VCC_MAX, "V", SRC_VCC)]
    soft_checks(check, rows)


WORST_START = dict(u20=dict(U20_WEAK), ron=0.140, dcr=L20_DCR_MAX)   # slowest start: weak boost, RON / DCR max


def _worst_start_scale(d):
    """L20 -20 % (lowest power per cycle), C37 and the +13V_OLED caps at their maximum tolerance (slowest ramp,
    most charge), all from the netlist tolerances."""
    sc = {"L20": 1 - d.tol("L20"), "C37": 1 + d.tol("C37")}
    for ref in d.on_net("+13V_OLED", "C"):
        sc[ref] = 1 + d.tol(ref)
    return sc


_START_CACHE = {}


def startup_worst(d):
    """VSYS 3.0 V, marked caps at +tol, weak parts (cached: three tests read it)."""
    key = (tuple(sorted(d._override.items())), frozenset(d._removed), frozenset(d._shorted))
    if key not in _START_CACHE:
        _START_CACHE[key] = startup(d, "startup worst", vsys=3.0, derate=False, tstop=9e-3,
                                    scale=_worst_start_scale(d), **WORST_START)
    return _START_CACHE[key]


def test_startup_inrush_and_overshoot(main, check):
    """OLED_VCC_EN rising with the display off: VSYS 3.0 V with marked caps (slowest start, longest inrush), USB
    4.6 V with derated caps (fastest edge, largest overshoot), and VSYS 3.0 V with the slowest parts (weak TPS61040,
    L20 -20 %, C37 and output caps +tol) for the start-up time."""
    jobs = [(3.0, False, 5.6e-3), (VSYS_USB, True, 4.3e-3), "worst"]

    def one(job):
        if job == "worst":
            return job, startup_worst(main)
        vs, der, tstop = job
        return job, startup(main, f"startup {vs} V", vsys=vs, derate=der, tstop=tstop)
    rows = []
    for job, r in pmap(one, jobs):
        if job == "worst":
            rows.append(("VCC reaches 12.5 V after OLED_VCC_EN, VSYS 3.0 V, slowest parts", r["tup"] - 20e-6, None,
                         T_AF, "s", SRC_TAF))
            continue
        vs, der, _ = job
        tag = f"VSYS {vs} V, caps {'derated' if der else 'marked'}"
        rows += [(f"VCC reaches 12.5 V after OLED_VCC_EN, {tag}", r["tup"] - 20e-6, None, T_AF, "s", SRC_TAF),
                 (f"VCC overshoot peak, {tag}", r["vpk"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC settled, {tag}", r["vend"], VCC_MIN, VCC_MAX, "V", SRC_VCC),
                 (f"U21 peak current (inrush), {tag}", r["iu21pk"], None, U21_IPLS, "A", SRC_IPLS),
                 (f"L20 peak current at start-up, {tag}", r["ilpk"], None, L20_ISAT, "A", SRC_ISAT),
                 (f"D21 peak current at start-up, {tag}", r["idpk"], None, D21_IFRM, "A", SRC_IFRM),
                 (f"SW peak at start-up, {tag}", r["swpk"], None, SW_MAX, "V", SRC_SW)]
    soft_checks(check, rows)


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (firmware-dependent, OLED-V2): the OLD floor for the "
                   "VCC-to-AFh wait (firmware.md 7.2 step 23 'never below 5 ms') is shorter than the worst-case VCC "
                   "rise (~6.3 ms at VSYS 3.0 V with a weak TPS61040, L20 -20 %, C37 +10 %); 4.9 ms even with typical "
                   "parts. firmware.md now says never below 10 ms: see "
                   "test_startup_time_vs_firmware_floor_with_fw_rule")
def test_startup_time_vs_firmware_floor(main, check):
    """The slowest start (see startup_worst) against the shortest wait the OLD firmware.md allowed before AFh."""
    r = startup_worst(main)
    check("VCC reaches 12.5 V after OLED_VCC_EN, VSYS 3.0 V, slowest parts (vs the OLD 5 ms firmware floor)",
          r["tup"] - 20e-6, None, T_AF_MIN_OLD, "s", SRC_TAF_MIN_OLD)


def test_startup_time_vs_firmware_floor_with_fw_rule(main, check):
    """GUARD for the firmware rule OLED-V2 (hardware/sim; firmware.md 7.2 step 23 and 3.1 oled_vcc
    startup-delay-us = <10000>, SPEC 5.3): the VCC-to-AFh wait MUST never be below 10 ms.  Same slowest start as
    test_startup_time_vs_firmware_floor (VSYS 3.0 V, weak TPS61040, U21 RON / L20 DCR max, L20 -20 %, C37 and
    the +13V_OLED caps +tol, marked values) against that 10 ms floor."""
    r = startup_worst(main)
    check("VCC reaches 12.5 V after OLED_VCC_EN, VSYS 3.0 V, slowest parts (vs the 10 ms firmware floor, OLED-V2)",
          r["tup"] - 20e-6, None, T_AF_MIN_FW, "s", SRC_VCC + " (VCC >= 12.5 V before AFh); " + SRC_TAF_MIN_FW)


SRC_USB = ("architecture.md +3V3 row: the rail is designed for VSYS >= BUVLO 3.0 V (+3V3 >= 2.9 V, W25Q128 needs "
           ">= 2.7 V); BQ25180 SLUSE99C 7.5 ILIM, 8.3.3 no supplement below BUVLO; firmware.md 13.3 / 6.3")


def usb_start(d, title, ilim, en="step", iload=0.0, vreg=SYS_REG_FW):
    """OLED_VCC_EN rising (en="step"; en="off" holds it low) while VSYS comes only from USB through the BQ25180
    input limit (battery dead or absent: no supplement), SYS regulated at `vreg` (the firmware's SYS_REG 4.4 V),
    with the VSYS capacitors of both boards (marked values) and no other VSYS load than `iload` (A, DC) - all of
    which favour the result.  Output caps at their energy-equivalent C(V) (DERATE_ENERGY)."""
    b = spicelib.Design("base")
    deck = build(d, title, vsys=vreg, icc=0.0, derate="energy", en=en, t_en=20e-6, init="off")
    deck.include("oled_boost__bq25180.lib")
    deck.lines = [ln for ln in deck.lines if not ln.startswith(("VSRC ", "RSRC "))]
    deck += f"XBQ {d.node('VSYS')} 0 BQ25180_SYS_OB params: ILIM={ilim:g} VREG={vreg:g}"
    deck += [ln[0] + "BASE_" + ln[1:] for ln in b.passives(nets={"VSYS", "GND"})]   # base board, via J3
    if iload:
        deck += f"ISYSLOAD {d.node('VSYS')} 0 DC {iload:g}"
    deck.meas("tran vsysmin MIN v(n_vsys)")
    deck.meas("tran vend AVG v(n_p13v_oled) FROM=6.5m TO=7m")
    return run(deck, 7e-3)


def test_usb_500ma_oled_enable(main, check):
    """USB at the 500 mA input-limit code (450 mA min), battery dead, SYS at the firmware's 4.4 V: the OLED supply
    may start (the enable the NEW-1 / OLED-V1 rule defers to ILIM = 500 mA)."""
    r = usb_start(main, "usb 500 mA", 0.450)
    soft_checks(check, [("VSYS min during OLED start-up, USB ILIM 500 mA code (450 mA min), no battery",
                         r["vsysmin"], 3.0, None, "V", SRC_USB),
                        ("VCC settled, USB only", r["vend"], VCC_MIN, VCC_MAX, "V", SRC_VCC)])


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (firmware-dependent, NEW-1 / OLED-V1): with USB at the 100 mA "
                   "pre-enumeration limit and a dead / absent battery (no supplement), the boost start-up (~0.25 A "
                   "for ~2 ms) pulls VSYS to ~2.3-2.5 V; the OLD firmware.md 13.3 / 6.3 allowed the OLED on in that "
                   "state. The rule now keeps OLED_VCC_EN low: see "
                   "test_usb_100ma_dead_battery_oled_enable_with_fw_rule")
def test_usb_100ma_dead_battery_oled_enable(main, check):
    """USB at the 100 mA input-limit code (98 mA max, the most favourable), battery below BUVLO, OLED_VCC_EN raised
    as the OLD firmware did."""
    r = usb_start(main, "usb 100 mA", 0.098)
    check("VSYS min during OLED start-up, USB ILIM 100 mA code (98 mA max), battery below BUVLO", r["vsysmin"],
          3.0, None, "V", SRC_USB)


ILIM100_MIN, ILIM100_MAX = 0.080, 0.098       # BQ25180 SLUSE99C 7.5 ILIM, 100 mA code (TMR_ILIM = 0xC9) min / max
I_CUE_FW = 20e-3                              # firmware.md 6.3 / 7.2 / 13.3: the <= 20 mA charging cue (NEW-1)
I_NOSUP100_FW = 70e-3                         # firmware.md 6.3 no-supplement profile, ILIM 100 mA phase: <= 70 mA total
SRC_FW_NEW1 = ("firmware rule (hardware/sim, NEW-1, OLED-V1): firmware.md 6.3 / 7.2 OLED_VCC_EN rules / 13.3, SPEC "
               "5.3: OLED_VCC_EN MUST stay low while TMR_ILIM = 0xC9 (100 mA) unless the battery can supplement SYS; "
               "LEDs show the <= 20 mA charging cue until ILIM = 500 mA")


def test_usb_100ma_dead_battery_oled_enable_with_fw_rule(main, check):
    """GUARD for the firmware rule NEW-1 / OLED-V1 (hardware/sim; firmware.md 6.3, 7.2 'OLED_VCC_EN rules', 13.3;
    SPEC 5.3): while the BQ25180 input limit is 100 mA and the battery cannot supplement SYS (BUVLO_STAT, or VBAT
    below about 3.15 V, or unknown), OLED_VCC_EN stays low and the LEDs show the <= 20 mA charging cue.  Same
    USB-only, battery-below-BUVLO deck as test_usb_100ma_dead_battery_oled_enable with the rule applied
    (OLED_VCC_EN held low), at both ends of the 100 mA code (80 mA min, 98 mA max as there), loaded with the
    20 mA cue and with the whole 70 mA budget firmware.md 6.3 allows in that phase (no-supplement profile, PI-4).
    The deferred enable at ILIM = 500 mA is test_usb_500ma_oled_enable.  Not covered here: the rule's other branch
    (OLED allowed at 100 mA with C7 <= 04h when the battery can supplement, VBAT >= about 3.15 V): this BQ25180
    model has no battery / supplement path and the docs give no cell resistance or supplement threshold for it."""
    jobs = [(ilim, iload) for ilim in (ILIM100_MIN, ILIM100_MAX) for iload in (I_CUE_FW, I_NOSUP100_FW)]

    def one(job):
        ilim, iload = job
        return job, usb_start(main, f"usb 100 mA fw rule {ilim:g} A {iload:g} A", ilim, en="off", iload=iload)
    soft_checks(check, [(f"VSYS min, USB ILIM 100 mA code ({ilim * 1e3:g} mA), battery below BUVLO, fw rule NEW-1: "
                         f"OLED_VCC_EN held low, {iload * 1e3:g} mA load", r["vsysmin"], 3.0, None, "V",
                         SRC_USB + "; " + SRC_FW_NEW1 + ("; firmware.md 6.3 no-supplement ILIM-100 total <= 70 mA "
                                                         "(PI-4)" if iload > I_CUE_FW else ""))
                        for (ilim, iload), r in pmap(one, jobs)])


def test_load_steps(main, check):
    """Panel content steps (1 us edges): dark -> full white and back at 3.7 V, display-on into the low-battery
    load at 3.0 V with weak parts, full white -> off on USB with strong parts."""
    ts = 0.3e-3
    jobs = [(3.7, ICC_LIGHT, ICC_100_MAX, {}), (3.7, ICC_100_MAX, ICC_LIGHT, {}),
            (3.0, 0.0, ICC_50_MAX, dict(u20=dict(U20_WEAK), **WEAK_PASSIVES)),
            (VSYS_USB, ICC_100_MAX, 0.0, dict(u20=dict(U20_STRONG)))]

    def one(job):
        vs, i0, i1, kw = job
        deck = build(main, f"step {vs} {i0}->{i1}", vsys=vs, icc=[(0, i0), (ts, i0), (ts + 1e-6, i1)],
                     derate=True, **kw)
        deck.meas(f"tran vmin MIN v(n_p13v_oled) FROM={ts} TO={ts + 0.6e-3}")
        deck.meas(f"tran vmax MAX v(n_p13v_oled) FROM={ts} TO={ts + 0.6e-3}")
        return job, run(deck, ts + 0.6e-3)
    rows = []
    for (vs, i0, i1, _), r in pmap(one, jobs):
        rows += [(f"VCC min after {i0}->{i1} mA step, VSYS {vs} V", r["vmin"], VCC_MIN, None, "V", SRC_VCC),
                 (f"VCC max after {i0}->{i1} mA step, VSYS {vs} V", r["vmax"], None, VCC_MAX, "V", SRC_VCC)]
    soft_checks(check, rows)


SRC_LINE = ("NHD rev 3 VCC 12.5-13.5 V; line steps: USB unplug / plug-in moves VSYS between SYS_REG 4.6 V and "
            "VBAT (BQ25180 SLUSE99C 8.3.3 supplement), battery sag 0.2 V at 0.8 A (architecture.md 8.4)")


def test_line_transients(main, check):
    """VSYS steps with the panel at full white (42 mA, typical TPS61040) and at light load with the strong corner:
    USB unplug 4.6 -> 3.7 V and plug-in 3.7 -> 4.6 V (10 us edges), LED-burst sag 3.8 -> 3.6 V (1 us edges)."""
    t0, t1 = 0.3e-3, 0.6e-3

    def step(a, b, tr):
        return [(0, a), (t0, a), (t0 + tr, b), (t1, b), (t1 + tr, a)]
    jobs = [("USB unplug/plug", 4.6, 3.7, 10e-6, ICC_100_MAX, U20_TYP),
            ("USB unplug/plug, light", 4.6, 3.7, 10e-6, ICC_LIGHT, U20_STRONG),
            ("battery sag", 3.8, 3.6, 1e-6, ICC_100_MAX, U20_TYP)]

    def one(job):
        tag, a, b, tr, icc, u20 = job
        deck = build(main, f"line {tag}", vsys=a, vsys_pwl=step(a, b, tr), icc=icc, derate=True, u20=dict(u20))
        deck.meas(f"tran vmin MIN v(n_p13v_oled) FROM={t0:.6g} TO={t1 + 0.3e-3:.6g}")
        deck.meas(f"tran vmax MAX v(n_p13v_oled) FROM={t0:.6g} TO={t1 + 0.3e-3:.6g}")
        return job, run(deck, t1 + 0.3e-3)
    rows = []
    for (tag, a, b, tr, icc, _), r in pmap(one, jobs):
        rows += [(f"VCC min, VSYS {a} <-> {b} V ({tag}), {icc} mA", r["vmin"], VCC_MIN, None, "V", SRC_LINE),
                 (f"VCC max, VSYS {a} <-> {b} V ({tag}), {icc} mA", r["vmax"], None, VCC_MAX, "V", SRC_LINE)]
    soft_checks(check, rows)


def test_shutdown_vcc_float(main, check):
    """OLED_VCC_EN low (after AEh, display off): U21 opens at once, so VSYS stops feeding the boost (ISD only),
    and U21's QOD (tied to OLED_VIN) discharges C38 through ~150 ohm.  The TPS61040 (EN = VIN) runs from the charge
    left on C38 until OLED_VIN falls through its ~1.5 V UVLO (about 0.5 ms at VSYS 3.0 V), then stops; VCC must
    not overshoot, and it is never actively discharged: it floats near 13 V behind D21 (SSD1351 8.9 note (2)).
    3 ms window (the model has no UVLO hysteresis; see test_off_state for the long-term end state)."""
    t_off, t_end = 50e-6, 3e-3

    def one(job):
        vs, temp = job
        deck = build(main, f"shutdown {vs} V {temp} C", vsys=vs, temp=temp, icc=0.0, derate=False,
                     en="off_at", t_en=t_off)
        deck.meas("tran vccmax MAX v(n_p13v_oled)")
        deck.meas(f"tran vccend FIND v(n_p13v_oled) AT={t_end:.6g}")
        deck.meas(f"tran iu21late AVG i(vprb_u21) FROM={t_off + 0.2e-3:.6g} TO={t_end:.6g}")
        return job, run(deck, t_end)
    rows = []
    for (vs, temp), r in pmap(one, [(VSYS_USB, 60.0), (3.0, 25.0), (3.0, -10.0)]):
        tag = f"VSYS {vs} V, {temp:g} C"
        rows += [(f"VCC max during turn-off, {tag}", r["vccmax"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC 3 ms after turn-off (floats, not pulled toward GND), {tag}", r["vccend"], 3.3, None,
                  "V", SRC_FLOAT + "; note (5) never pulled to ground"),
                 (f"VSYS current into U21 while off, {tag}", r["iu21late"], None, U21_ISD_MAX, "A", SRC_ISD)]
    soft_checks(check, rows)


SRC_FB_ABS = "TPS61040 SLVS413L 5.1 abs max: FB <= VIN + 0.3 V (architecture.md risk R31)"


def test_off_state(main, check):
    """Long-term state with OLED_VCC_EN low: OLED_VIN drained to 0 V (worst case), VCC held by the panel's
    VCI -> VCC ESD path.  No path from VSYS may lift VCC above VCI, U21 draws only its shutdown current, and the
    divider must not put the TPS61040 FB pin more than 0.3 V above its (unpowered) VIN.  VCC starts above the
    ESD-path equilibrium (VCI - 0.4 V) and is read after 50-60 ms (time constant ~75 ms, so the reading is an
    upper bound).  The ESD drop falls with temperature, so 60 C gives the highest VCC and FB; D21 leakage, which
    lifts OLED_VIN, is smallest at -10 C."""
    def one(job):
        vs, temp = job
        deck = build(main, f"off {vs} V {temp} C", vsys=vs, temp=temp, icc=0.0, derate=False, en="off",
                     init="off")
        deck += f"BFBX n_fbx 0 V=V({main.node('OLED_BST_FB')})-V({main.node('OLED_VIN')})"   # probe, no load
        w = "FROM=50m TO=60m"
        deck.meas(f"tran vccmax MAX v(n_p13v_oled) {w}")
        deck.meas(f"tran fbx MAX v(n_fbx) {w}")
        deck.meas(f"tran iu21 AVG i(vprb_u21) {w}")
        deck.meas(f"tran v3v3 AVG v(n_p3v3) {w}")
        deck.tran("10u", "60m", 0, "uic")
        r = deck.run(timeout=900)
        assert not r["_errors"] and not r.get("_missing"), r["_log"][-3000:]
        return job, r
    rows = []
    for (vs, temp), r in pmap(one, [(VSYS_USB, 60.0), (VSYS_USB, 25.0), (3.0, -10.0)]):
        tag = f"VSYS {vs} V, {temp:g} C"
        rows += [(f"VCC with OLED_VCC_EN low, {tag}", r["vccmax"], None, r["v3v3"], "V",
                  SRC_FLOAT + ": must not exceed VCI (+3V3)"),
                 (f"FB - OLED_VIN with the boost off, {tag}", r["fbx"], None, 0.3, "V", SRC_FB_ABS),
                 (f"VSYS current into U21 with OLED_VCC_EN low, {tag}", r["iu21"], None, U21_ISD_MAX, "A", SRC_ISD)]
    soft_checks(check, rows)


# ----------------------------------------------------------------------------------------------- faults
@pytest.mark.fault
def test_fault_r27_wrong_value_detected(main, check):
    """R27 fitted as 49.9 kOhm (neighbouring E96 value) instead of 52.3 kOhm: VCC leaves the panel window."""
    main.override("R27", "49.9k 0.1%")
    r = steady(main, "fault R27", vsys=3.7, icc=ICC_LIGHT, derate=False, t_meas=0.6e-3)
    check("FAULT R27 = 49.9k: VCC avg must exceed the panel max (detected)", r["vavg"], VCC_MAX, None, "V", SRC_VCC)


@pytest.mark.fault
def test_fault_r26_open_detected(main, check):
    """R26 (upper FB resistor) left off / open joint: FB sits at 0 V, the boost runs open loop and VCC climbs
    past the panel limit (the TPS61040 has no output over-voltage protection)."""
    main.remove("R26")
    deck = build(main, "fault R26 open", vsys=3.7, icc=ICC_LIGHT, derate=True)
    deck.meas("tran vmax MAX v(n_p13v_oled) FROM=0 TO=0.5m")
    r = run(deck, 0.5e-3)
    check("FAULT R26 open: VCC peak within 0.5 ms must exceed the panel max (detected)", r["vmax"], VCC_MAX, None,
          "V", SRC_VCC + "; " + SRC_VCC_ABS)


@pytest.mark.fault
def test_fault_l20_wrong_value_detected(main, check):
    """L20 fitted as 1 uH (wrong reel) instead of 10 uH: Ipeak = ILIM + VIN/L x 100 ns exceeds Isat."""
    main.override("L20", "1u")
    r = steady(main, "fault L20", vsys=VSYS_USB, icc=ICC_100_MAX, derate=True, u20=dict(U20_STRONG),
               t_settle=0.15e-3, t_meas=0.1e-3)
    check("FAULT L20 = 1 uH: inductor peak must exceed Isat (detected)", r["ilpk"], L20_ISAT, None, "A", SRC_ISAT)


@pytest.mark.fault
def test_fault_ct_capacitor_missing_detected(main, check):
    """C37 (U21 CT) left off: U21 turns on in ~0.1 ms instead of ~4 ms and the OLED_VIN edge drives a resonant
    inrush through L20 / D21 into the output caps; at VSYS 4.6 V L20 exceeds its saturation current."""
    main.remove("C37")
    r = startup(main, "fault C37", vsys=VSYS_USB, derate=False, tstop=1.5e-3)
    check("FAULT C37 missing: L20 peak at start-up must exceed Isat (detected)", r["ilpk"], L20_ISAT, None, "A",
          SRC_ISAT)


@pytest.mark.fault
def test_fault_output_caps_missing_detected(main, check):
    """C30 and C39 (both bulk output caps) left off: the static COUT check, now taken from the fitted netlist
    parts, must see less than the TPS61040 minimum."""
    main.remove("C30").remove("C39")
    check("FAULT C30 + C39 off: effective COUT must fall below 1 uF (detected)", cout_effective(main), None, 1e-6,
          "F", "TPS61040 SLVS413L 5.3: COUT >= 1 uF")


@pytest.mark.fault
def test_fault_cin_missing_detected(main, check):
    """C38 (boost input cap) left off: the static CIN check must flag it."""
    main.remove("C38")
    check("FAULT C38 off: CIN at U20 must fall below 4.7 uF (detected)", cin_fitted(main), None, 4.7e-6 * 0.999,
          "F", "TPS61040 SLVS413L 5.3 CIN 4.7 uF / 7.2.2.5")


@pytest.mark.fault
def test_fault_ct_shorted_detected(main, check):
    """C37 shorted (solder bridge CT-VIN): U21 never turns on, so VCC never reaches the panel minimum; the
    start-up check reports it (time = inf) instead of the harness erroring out."""
    main.short("C37")
    r = startup(main, "fault C37 short", vsys=3.7, derate=False, tstop=8e-3)
    check("FAULT C37 shorted: VCC must not reach 12.5 V within 8 ms (detected)", r["tup"], 8e-3, None, "s",
          SRC_TAF + " (start-up never completes)")


@pytest.mark.fault
def test_fault_r26_bridged_detected(main, check):
    """R26 bridged (solder bridge / 0-ohm fitted): FB sits on VCC, the boost targets VREF = 1.23 V, so after
    OLED_VCC_EN VCC only follows VSYS through L20 / D21 and never reaches the panel window."""
    main.short("R26")
    r = startup(main, "fault R26 short", vsys=VSYS_USB, derate=False, tstop=6e-3)
    check("FAULT R26 bridged: VCC after start-up must stay below the panel minimum (detected)", r["vend"], None,
          VCC_MIN, "V", SRC_VCC)


# ----------------------------------------------------------------------------------------------- Monte Carlo
@pytest.mark.slow
def test_monte_carlo_passives(main, check):
    """200 uniform tolerance draws over the 8 boost passives (R26, R27, C30, C31, C38, C39, C40, L20), derated
    caps, typical TPS61040 at VBAT 3.7 V: 1 mA until 0.6 ms (measured after 0.2 ms), then a step to full white
    (42 mA) for 0.4 ms."""
    refs = ["R26", "R27", "C30", "C31", "C38", "C39", "C40", "L20"]
    ts = 0.6e-3

    def one(draw):
        deck = build(main, "mc", vsys=3.7, icc=[(0, ICC_LIGHT), (ts, ICC_LIGHT), (ts + 1e-6, ICC_100_MAX)],
                     scale=draw, derate=True)
        deck.meas(f"tran vmax MAX v(n_p13v_oled) FROM=0.2m TO={ts}")
        deck.meas(f"tran vmin MIN v(n_p13v_oled) FROM={ts} TO={ts + 0.4e-3}")
        deck.meas(f"tran ilpk MAX i(ll20) FROM=0.2m TO={ts + 0.4e-3}")
        return run(deck, ts + 0.4e-3)
    out = pmap(one, main.monte_carlo(refs, 200, seed=7))
    assert len(out) == 200
    soft_checks(check, [("MC (200): VCC max at 1 mA", max(r["vmax"] for r in out), None, VCC_MAX, "V", SRC_VCC),
                        ("MC (200): VCC min at 42 mA", min(r["vmin"] for r in out), VCC_MIN, None, "V", SRC_VCC),
                        ("MC (200): L20 peak", max(r["ilpk"] for r in out), None, L20_ISAT, "A", SRC_ISAT)])
