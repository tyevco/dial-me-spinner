"""OLED panel supply: U21 TPS22917 -> OLED_VIN -> U20 TPS61040 boost (L20, D21, C38/C39/C30/C31, R26/R27/C40)
-> +13V_OLED -> SSD1351 / NHD-1.5-128128G VCC (J20 pin 2).

Every passive comes from hardware/kicad/main/dial-me-spinner-main.net (Design.passives / Design.value), so a
schematic change shows up here.  IC behaviour comes from the models in hardware/sim/models/oled_boost__*.lib,
each of which cites its datasheet.  Limits:

  * Panel VCC 12.5-13.5 V ...... NHD-1.5-128128G rev 3, Electrical Characteristics ("Supply Voltage for Display")
  * Panel ICC .................. same table: 50 % ON 29.0 mA max, 100 % ON 42.0 mA max (VCC 13 V)
  * SSD1351 VCC abs max 19 V ... Solomon SSD1351 Rev 1.3 Table 11-1
  * TPS61040 SW <= 30 V, VIN <= 6 V (recommended) / 7 V (abs max) ... SLVS413L 5.1 / 5.3
  * L20 Isat 0.72 A (rated, 30 % L drop) ... Sunlord SWPA series datasheet rev 2019/04/01, SWPA3015S100MT row
  * D21 IFRM 1.5 A, VRRM 40 V ... CJ B5817W-5819W rev D (Mar 2015) Maximum Ratings
  * TPS22917 IMAX 2 A, IPLS 2.5 A ... SLVSDW8B Table 7.1
  * VCC up before AFh: firmware waits >= 200 ms after OLED_VCC_EN (SPEC.md 5.3 / NHD example init sequence)
  * VCC must float when off (no path VSYS -> VCC) ... SSD1351 Rev 1.3 8.9 note (2); TPS61040 SLVS413L 6.3.3

Supply corners: VSYS on battery = VBAT 3.0 / 3.7 / 4.2 V (BQ25180 BATFET path); on USB VSYS = SYS_REG 4.5 V
+2 % = 4.59 -> 4.6 V (BQ25180 SLUSE99C VSYS_REG_ACCURACY).  The firmware low-battery rule (firmware.md 7.4:
below VBAT 3.60 V, C7 <= 08h and <= 30 % white) bounds the panel load at VSYS 3.0 V by the 50 %-ON maximum
(29 mA); above 3.6 V the panel may show full white (42 mA max).
"""

from __future__ import annotations

import math
import os

import pytest

import spicelib

# ----------------------------------------------------------------------------------------------- constants
NETS = {"VSYS", "OLED_VIN", "OLED_BST_SW", "OLED_BST_FB", "+13V_OLED", "OLED_LSW_CT", "OLED_VCC_EN", "GND"}
LIBS = ("oled_boost__tps61040.lib", "oled_boost__tps22917.lib", "oled_boost__b5819w.lib",
        "oled_boost__ssd1351.lib")

# limits (value, source)
VCC_MIN, VCC_MAX = 12.5, 13.5
SRC_VCC = "NHD-1.5-128128G rev 3 Electrical Characteristics: VCC 12.5-13.5 V"
SRC_VCC_ABS = "SSD1351 Rev 1.3 Table 11-1: VCC abs max 19.0 V"
ICC_50_MAX, ICC_100_MAX = 29.0, 42.0          # mA, NHD rev 3 Electrical Characteristics (VCC 13 V)
ICC_LIGHT = 1.0                               # mA: dark UI / near-black content (task range 1-30 mA)
L20_ISAT = 0.72
SRC_ISAT = "Sunlord SWPA (rev 2019/04/01) SWPA3015S100MT: Isat 0.72 A rated (30 % L drop), 0.92 A typ"
D21_IFRM = 1.5
SRC_IFRM = "CJ B5819W rev D Maximum Ratings: IFRM 1.5 A"
SW_MAX = 30.0
SRC_SW = "TPS61040 SLVS413L 5.1 abs max: SW 30 V"
U21_IPLS = 2.5
SRC_IPLS = "TPS22917 SLVSDW8B Table 7.1: IPLS 2.5 A (< 300 us), IMAX 2 A"
VIN_REC_MAX = 6.0
SRC_VIN = "TPS61040 SLVS413L 5.3: VIN 1.8-6 V recommended"
T_AF = 0.200
SRC_TAF = "SPEC.md 5.3 / NHD init sequence: AFh >= 200 ms after OLED_VCC_EN, so VCC must be in range by then"
UVLO_MAX = 1.7
SRC_UVLO = "TPS61040 SLVS413L 5.5: VUVLO 1.7 V max"

# supply corners
VSYS_BAT = (3.0, 3.7, 4.2)                    # VBAT corners (VSYS = VBAT through the 55 mOhm BATFET)
VSYS_USB = 4.6                                # BQ25180 SYS_REG 4.5 V + 2 % (SLUSE99C VSYS_REG_ACCURACY)
# VSYS source: BQ25180 RON_BAT 55 mOhm typ (SLUSE99C 7.5) + link harness 8.5 + 5.7 mOhm (architecture.md 4.2)
R_SRC = 0.055 + 0.0085 + 0.0057

# TPS61040 corners from SLVS413L 5.5 (typ / min / max).  "weak" = least output capability, "strong" = largest
# peak current and fastest repetition.
U20_TYP = dict(ILIM=0.400, TOFF=400e-9, TONMAX=6e-6, VREF=1.233, RDS=0.6, IQ=28e-6, IFB=0.0, UVLO=1.5)
U20_WEAK = dict(U20_TYP, ILIM=0.350, TOFF=550e-9, TONMAX=4e-6, RDS=1.0)
U20_STRONG = dict(U20_TYP, ILIM=0.450, TOFF=250e-9, TONMAX=7.5e-6)

# Passive parasitics from their datasheets
L20_DCR_TYP, L20_DCR_MAX = 0.250, 0.325       # Sunlord SWPA3015S100MT DCR typ / max (20 C)
CU_TCR = 0.00393                              # copper resistance tempco (1/K), DCR referenced to 20 C
C_ESR = 0.008                                 # Samsung CL21A106 |ESR| 5-10 mOhm at 0.1-2 MHz (char. sheet)
# DC-bias derating, Samsung CL21A106KAYNNNG characteristic sheet (0805 / 25 V / X5R, same family as C30 and
# C39): dC = -71 % at 13 V, about -20 % at 3-4.6 V (C38 on OLED_VIN).  Used as the "derated" corner; the
# nominal corner keeps the marked values (largest inrush, smallest ripple).
DERATE_13V = 0.29
DERATE_VSYS = 0.80

TEMPS = (-10.0, 25.0, 60.0)


def u20_at(temp: float, base: dict) -> dict:
    """Scale the typical-curve TPS61040 parameters to `temp` (C).  Max/min corners stay as given."""
    p = dict(base)
    # Fig 5-10: RDS(on) 480 mOhm at -40 C to 800 mOhm at 90 C (linear), 640 mOhm at 25 C -> ratio
    if base["RDS"] < 0.99:
        p["RDS"] = base["RDS"] * (480 + 320 / 130 * (temp + 40)) / 640
    # Fig 5-6: VFB 1.2331 V at -40 C, 1.2341 V from 0 to 80 C (drift only, the corner value is kept)
    p["VREF"] = base["VREF"] - (0.0 if temp >= 0 else 1.0e-3 * (-temp) / 40)
    # Fig 5-7: ILIM about 398 mA at -40 C to 404 mA at 90 C
    p["ILIM"] = base["ILIM"] * (1 + 1.15e-4 * (temp - 25))
    # Fig 5-5: IQ 21 / 27 / 33.5 uA at -40 / 27 / 85 C (VIN 3.6 V)
    p["IQ"] = base["IQ"] * (1 + 0.0055 * (temp - 25))
    return p


def u21_ron(temp: float, worst: bool = False) -> float:
    """TPS22917 RON at VIN 3.6 V, SLVSDW8B Table 7.5: 90 mOhm typ (25 C), 140 mOhm max (-40..85 C)."""
    return 0.140 if worst else 0.090 * (1 + 0.004 * (temp - 25))


def u21_ct_ready(vsys: float) -> float:
    """CT node voltage of the U21 model once the turn-on ramp has finished (used to start in steady state)."""
    v = min(max(vsys, 1.8), 5.0)
    ict = 1.1e-6 + (v - 1.8) * (0.8e-6 / 1.8) if v < 3.6 else 1.9e-6 + (v - 3.6) * (0.4e-6 / 1.4)
    tonk = 3.6e6 + (v - 1.8) * (0.2e6 / 1.8) if v < 3.6 else 3.8e6 + (v - 3.6) * (0.2e6 / 1.4)
    vdel = ict * tonk - 0.9 * v
    return vsys - (vdel + vsys + 1.0)


def pwl(points) -> str:
    return "PWL(" + " ".join(f"{t:.9g} {v:.9g}" for t, v in points) + ")"


def build(d, title, *, vsys=3.7, temp=25.0, u20=None, ron=None, dcr=None, scale=None, derate=True,
          icc=ICC_LIGHT, en="on", t_en=20e-6, init="steady", vcc0=None):
    """ngspice deck for the whole OLED supply path.

    icc   : panel VCC current in mA (number) or a list of (t, mA) PWL points
    en    : "on" (OLED_VCC_EN high from t = 0), "step" (low until t_en, then high), "off_at" (high until t_en)
    init  : "steady" (start at the regulated point: output charged, U21 fully on, soft start done, uic)
            or "cold" (operating point with OLED_VCC_EN low, everything else from the netlist)
    """
    u20 = dict(u20_at(temp, U20_TYP) if u20 is None else u20)
    ron = u21_ron(temp) if ron is None else ron
    dcr = (L20_DCR_TYP if dcr is None else dcr) * (1 + CU_TCR * (temp - 20))
    sc = dict(scale or {})
    if derate:
        for ref in ("C30", "C39"):
            sc[ref] = sc.get(ref, 1.0) * DERATE_13V
        sc["C38"] = sc.get("C38", 1.0) * DERATE_VSYS
    n = {k: d.node(k) for k in ("VSYS", "OLED_VIN", "OLED_BST_SW", "OLED_BST_FB", "+13V_OLED", "OLED_LSW_CT",
                                "OLED_VCC_EN", "+3V3")}
    deck = spicelib.Deck(title)
    for lib in LIBS:
        deck.include(lib)
    # gear + reltol 1e-3: checked against the harness default (trap, reltol 1e-4) on the 23 mA steady state:
    # VCC avg/min/max within 0.3 mV, D21 peak within 0.3 %, 3x faster (trap at 1e-3 rings: not used)
    deck.options = [o for o in deck.options if "reltol" not in o] + ["option reltol=1e-3", "option method=gear",
                                                                       f"temp {temp:g}"]
    # supplies: VSYS through the BATFET + harness, +3V3 (VCI) always on
    deck += f"VSRC n_vsys_src 0 {vsys}"
    deck += f"RSRC n_vsys_src {n['VSYS']} {R_SRC:.6g}"
    deck += f"V3V3 {n['+3V3']} 0 3.3"
    # OLED_VCC_EN from nRF P1.02 (standard drive, ~100 ohm)
    if en == "on":
        deck += "VEN n_en_drv 0 3.3"
    elif en == "step":
        deck += "VEN n_en_drv 0 " + pwl([(0, 0), (t_en, 0), (t_en + 1e-7, 3.3)])
    elif en == "off_at":
        deck += "VEN n_en_drv 0 " + pwl([(0, 3.3), (t_en, 3.3), (t_en + 1e-7, 0)])
    deck += f"RGPIO n_en_drv {n['OLED_VCC_EN']} 100"
    # every netlist passive on these nets (C1/C2/C6/C41/C70/C72/C74 on VSYS, C37 CT, C38, R25, R26, R27, C40,
    # C30, C31, C39), with ESR on the boost caps; L20 added below with its DCR
    esr = {r: C_ESR for r in ("C30", "C38", "C39")}
    deck += d.passives(nets=NETS, exclude=("L20",), scale=sc, esr=esr)
    # L20 is written OLED_VIN -> DCR -> L -> OLED_BST_SW so that i(ll20) is the inductor current into SW
    assert set(d.pins["L20"].values()) == {"OLED_VIN", "OLED_BST_SW"}, d.pins["L20"]
    if d.fitted("L20"):
        if "L20" in d._shorted:
            deck += f"VL20_short {n['OLED_VIN']} {n['OLED_BST_SW']} 0"
        else:
            deck += f"RL20_dcr {n['OLED_VIN']} n_l20_dcr {dcr:.6g}"
            deck += f"LL20 n_l20_dcr {n['OLED_BST_SW']} {d.value('L20') * sc.get('L20', 1.0):.6g}"
    # U21 TPS22917 with a current probe in VIN
    deck += f"VPRB_U21 {d.pin('U21', 'VIN')} n_u21_vin 0"
    deck += (f"XU21 n_u21_vin 0 {d.pin('U21', 'ON')} {d.pin('U21', 'CT')} {d.pin('U21', 'QOD')} "
             f"{d.pin('U21', 'VOUT')} TPS22917_OB params: RON={ron:.6g}")
    # U20 TPS61040
    prm = " ".join(f"{k}={v:.6g}" for k, v in u20.items())
    deck += (f"XU20 {d.pin('U20', 'EN')} {d.pin('U20', 'FB')} {d.pin('U20', 'SW')} {d.pin('U20', 'VIN')} 0 "
             f"TPS61040_OB params: {prm}")
    # D21 B5819W with a current probe at the anode
    deck += f"VPRB_D21 {d.pin('D21', 'A')} n_d21_a 0"
    deck += f"XD21 n_d21_a {d.pin('D21', 'K')} B5819W_OB params: TA={temp:g}"
    # panel VCC load on J20 pin 2, VCI on pin 27
    deck += f"XJ20 {d.pin('J20', '2')} {d.pin('J20', '27')} 0 n_icc SSD1351_VCC_OB"
    deck += f"VICC n_icc 0 {pwl(icc) if isinstance(icc, (list, tuple)) else icc}"
    if init == "steady":
        r26, r27 = d.value("R26") * sc.get("R26", 1.0), d.value("R27") * sc.get("R27", 1.0)
        v0 = vcc0 if vcc0 is not None else u20["VREF"] * (1 + r26 / r27)
        ics = {n["VSYS"]: vsys, n["OLED_VIN"]: vsys, n["OLED_BST_SW"]: vsys, "n_l20_dcr": vsys, "n_d21_a": vsys,
               "n_u21_vin": vsys, n["+13V_OLED"]: v0, n["OLED_BST_FB"]: v0 * r27 / (r26 + r27),
               n["OLED_LSW_CT"]: u21_ct_ready(vsys), n["OLED_VCC_EN"]: 3.3, "xu20.cnt": 600, "xu21.en": 1}
        deck += ".ic " + " ".join(f"v({k})={v:.6g}" for k, v in ics.items())
    return deck


def run(deck, tstop, step="20n", uic=True, tmax=None):
    extra = " ".join(x for x in (f"{tmax}" if tmax else "", "uic" if uic else "") if x)
    deck.tran(step, f"{tstop:.6g}", 0, extra)
    res = deck.run(timeout=600)
    assert not res["_errors"], "\n".join(res["_errors"][:10]) + "\n" + res["_log"][-3000:]
    assert not res.get("_missing"), f"missing measures {res.get('_missing')}\n" + res["_log"][-3000:]
    return res


def meas_window(deck, t0, t1, tag=""):
    vcc = "v(n_p13v_oled)"
    deck.meas(f"tran vavg{tag} AVG {vcc} FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran vmax{tag} MAX {vcc} FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran vmin{tag} MIN {vcc} FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran ilpk{tag} MAX i(ll20) FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran idpk{tag} MAX i(vprb_d21) FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran swpk{tag} MAX v(n_oled_bst_sw) FROM={t0:.6g} TO={t1:.6g}")
    deck.meas(f"tran iin{tag} AVG i(vprb_u21) FROM={t0:.6g} TO={t1:.6g}")


def steady(d, title, *, t_settle=0.3e-3, t_meas=0.5e-3, **kw):
    """Run from the regulated state and measure VCC avg / min / max, peak currents over the last t_meas."""
    deck = build(d, title, **kw)
    t1 = t_settle + t_meas
    meas_window(deck, t_settle, t1)
    return run(deck, t1)


# ----------------------------------------------------------------------------------------------- tests
def test_nominal_regulation(main, check):
    """VBAT 3.7 V, 25 C, typical parts: VCC sits in the panel window at light and 50 %-ON load."""
    for icc in (ICC_LIGHT, 23.2):
        r = steady(main, f"nominal {icc} mA", icc=icc, derate=False, t_meas=0.8e-3 if icc < 5 else 0.4e-3)
        check(f"VCC avg, VBAT 3.7 V, {icc} mA", r["vavg"], VCC_MIN, VCC_MAX, "V", SRC_VCC)
        check(f"VCC min, VBAT 3.7 V, {icc} mA", r["vmin"], VCC_MIN, None, "V", SRC_VCC)
        check(f"VCC max, VBAT 3.7 V, {icc} mA", r["vmax"], None, VCC_MAX, "V", SRC_VCC)
        # the PFM loop must regulate to the datasheet set point (SLVS413L eq. 5) within the load-regulation term
        vset = 1.233 * (1 + main.value("R26") / main.value("R27"))
        check(f"VCC avg vs eq. 5 set point ({vset:.3f} V), {icc} mA", r["vavg"] - vset, -0.05, 0.10, "V",
              "TPS61040 SLVS413L eq. 5 VOUT = 1.233 V (1 + R1/R2); 0.15 %/mA load regulation (5.5)")
