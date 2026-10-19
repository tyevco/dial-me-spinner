"""OLED panel supply: U21 TPS22917 -> OLED_VIN -> U20 TPS61040 boost (L20, D21, C38/C39/C30/C31, R26/R27/C40)
-> +13V_OLED -> SSD1351 / NHD-1.5-128128G VCC (J20 pin 2).

Every passive comes from hardware/kicad/main/dial-me-spinner-main.net (Design.passives / Design.value), so a
schematic change shows up here.  IC behaviour comes from hardware/sim/models/oled_boost__*.lib, each of which
cites its datasheet (the TPS61040 model is a native-ngspice port of TI's SLVMDA8 PSpice model, cross-checked
against it).  Limits:

  * Panel VCC 12.5-13.5 V ...... NHD-1.5-128128G rev 3, Electrical Characteristics ("Supply Voltage for Display")
  * Panel ICC .................. same table: 50 % ON 29.0 mA max, 100 % ON 42.0 mA max (VCC 13 V)
  * SSD1351 VCC abs max 19 V ... Solomon SSD1351 Rev 1.3 Table 11-1
  * TPS61040 SW <= 30 V (abs max), VIN <= 6 V, f <= 1 MHz, COUT >= 1 uF, L 2.2-47 uH (SLVS413L 5.1 / 5.3 / 7.2.2)
  * L20 Isat 0.72 A (rated, 30 % L drop) ... Sunlord SWPA series datasheet rev 2019/04/01, SWPA3015S100MT row
  * D21 IFRM 1.5 A, VRRM 40 V ... CJ B5817W-5819W rev D (Mar 2015) Maximum Ratings
  * TPS22917 IPLS 2.5 A, VIN <= 5.5 V, ISD,VIN <= 100 nA ... SLVSDW8B Tables 7.1 / 7.3 / 7.5
  * VCC up before AFh: firmware waits >= 200 ms after OLED_VCC_EN (SPEC.md 5.3 / NHD example init sequence)
  * VCC must float when off: no path VSYS -> VCC ... SSD1351 Rev 1.3 8.9 note (2); TPS61040 SLVS413L 6.3.3
  * Headroom: at VCC = 12.5 V the boost must deliver the panel ICC firmware allows at that VSYS + the divider
    current (measured with VCC clamped at 12.5 V, see capability(); a run from 13 V can take ms to droop)

Supply corners: VSYS on battery = VBAT 3.0 / 3.7 / 4.2 V (BQ25180 BATFET path); on USB VSYS = SYS_REG 4.5 V
+2 % = 4.59 -> 4.6 V (BQ25180 SLUSE99C VSYS_REG_ACCURACY).  The firmware low-battery rule (firmware.md 7.4:
below VBAT 3.60 V, C7 <= 08h and <= 30 % white) bounds the panel load below 3.6 V by the 50 %-ON maximum
(29 mA); from 3.6 V up the panel may show full white (42 mA max).

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
SRC_TAF = "SPEC.md 5.3 / NHD init sequence: AFh >= 200 ms after OLED_VCC_EN, VCC must be in range by then"
UVLO_MAX = 1.7
SRC_UVLO = "TPS61040 SLVS413L 5.5: VUVLO 1.7 V max (boost off below it); SSD1351 8.9: VCC off before tOFF 100 ms"
SRC_FLOAT = ("SSD1351 Rev 1.3 8.9 note (2) VCC floats when off / note (1) held near VCI by ESD path; "
             "TPS61040 SLVS413L 6.3.3 (disabled boost passes VIN to VOUT)")

# supply corners
VSYS_BAT = (3.0, 3.7, 4.2)                    # VBAT corners (VSYS = VBAT through the BATFET)
VSYS_USB = 4.6                                # BQ25180 SYS_REG 4.5 V + 2 % (SLUSE99C VSYS_REG_ACCURACY)
VSYS_FW = 3.6                                 # firmware.md 7.4 low-battery threshold for full-white content
# VSYS source: BQ25180 RON_BAT 55 mOhm typ (SLUSE99C 7.5) + link harness 8.5 + 5.7 mOhm (architecture.md 4.2)
R_SRC = 0.055 + 0.0085 + 0.0057


def icc_max(vsys: float) -> float:
    """Largest panel VCC current firmware allows at this VSYS (see module docstring)."""
    return ICC_100_MAX if vsys >= VSYS_FW else ICC_50_MAX


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
          icc=ICC_LIGHT, en="on", t_en=20e-6, init="steady", vcc0=None):
    """ngspice deck for the whole OLED supply path, parts and connections taken from the main-board netlist.

    icc   : panel VCC current in mA (number) or a list of (t, mA) PWL points
    en    : "on" (OLED_VCC_EN high from t = 0), "step" (low until t_en, then high), "off_at" (high until t_en)
    init  : "steady" (start at the regulated point: output charged, U21 fully on, soft start done; run with uic)
            or "cold" (DC operating point with OLED_VCC_EN low)
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
               n["OLED_LSW_CT"]: u21_ct_ready(vsys), n["OLED_VCC_EN"]: 3.3, "xu20.cnt": 600, "xu21.en": 1}
        deck += ".ic " + " ".join(f"v({k})={v:.6g}" for k, v in ics.items())
    return deck


def run(deck, tstop, uic=True, tmax=None):
    extra = " ".join(x for x in (tmax or "", "uic" if uic else "") if x)
    deck.tran(STEP, f"{tstop:.6g}", 0, extra)
    res = deck.run(timeout=900)
    assert not res["_errors"], "\n".join(res["_errors"][:10]) + "\n" + res["_log"][-3000:]
    assert not res.get("_missing"), f"missing measures {res.get('_missing')}\n" + res["_log"][-3000:]
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
    """OLED_VCC_EN low -> high at 20 us from the cold operating point (panel display off: ICC = 0)."""
    deck = build(d, title, vsys=vsys, icc=0.0, derate=derate, en="step", t_en=20e-6, init="cold", **kw)
    deck.meas(f"tran tvin90 WHEN v(n_oled_vin)={0.9 * vsys:.6g} RISE=1")
    deck.meas(f"tran tup WHEN v(n_p13v_oled)={VCC_MIN} RISE=1")
    deck.meas("tran vpk MAX v(n_p13v_oled)")
    deck.meas("tran iu21pk MAX i(vprb_u21)")
    deck.meas("tran ilpk MAX i(ll20)")
    deck.meas("tran idpk MAX i(vprb_d21)")
    deck.meas("tran swpk MAX v(n_oled_bst_sw)")
    deck.meas(f"tran iu21avg AVG i(vprb_u21) FROM=20u TO={tstop:.6g}")
    deck.meas(f"tran vend AVG v(n_p13v_oled) FROM={tstop - 0.3e-3:.6g} TO={tstop:.6g}")
    return run(deck, tstop, uic=False)


# =============================================================================================== tests
def test_static_ratings(main, check):
    """Netlist values against the TPS61040 recommended operating conditions and application rules."""
    d = main
    lo = lambda r: d.value(r) * (1 - d.tol(r))   # noqa: E731
    hi = lambda r: d.value(r) * (1 + d.tol(r))   # noqa: E731
    check("L20 min (tolerance)", lo("L20"), 2.2e-6, None, "H", "TPS61040 SLVS413L 5.3 / 7.2.2.1: L 2.2-47 uH")
    check("L20 max (tolerance)", hi("L20"), None, 47e-6, "H", "TPS61040 SLVS413L 7.2.2.1: L 2.2-47 uH")
    cout = sum(lo(r) * DERATE_13V for r in ("C30", "C39")) + lo("C31")
    check("COUT effective at 13 V (min tol, DC bias)", cout, 1e-6, None, "F",
          "TPS61040 SLVS413L 5.3: COUT >= 1 uF (Samsung CL21A106 DC-bias -71 % at 13 V)")
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
    """VFB max / light load / derated caps (highest VCC) and VFB min / full load (lowest VCC), for every
    R26/R27 tolerance corner (Design.extremes), with FB bias current `ifb` pushing the same way."""
    jobs = []
    for corner in d.extremes(["R26", "R27"]):
        jobs.append(("hi", corner, dict(U20_TYP, VREF=VREF_MAX, IFB=+ifb), 4.6, ICC_LIGHT))
        jobs.append(("lo", corner, dict(U20_TYP, VREF=VREF_MIN, IFB=-ifb), 4.2, ICC_100_MAX))

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
                        ("VCC min: VFB min, R corners, 42 mA, VSYS 4.2 V", vmin, VCC_MIN, None, "V",
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


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: at the firmware full-white threshold (VBAT 3.60 V, "
                   "firmware.md 7.4) a worst-case TPS61040 + L20 delivers only ~41 mA at VCC 12.5 V, less than the "
                   "42 mA NHD 100 %-ON maximum; VCC settles near 12.3 V")
def test_headroom_at_firmware_full_white_threshold(main, check):
    """Same weak-part stack at VSYS 3.6 V, the lowest voltage at which firmware still allows full white."""
    soft_checks(check, _headroom_rows(main, [(VSYS_FW, icc_max(VSYS_FW))]))


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
    at the low-battery load (3.0 V, 29 mA) and the full-white threshold (3.6 V, 42 mA) - RDS(on) and DCR rise
    with temperature - and USB at light load (highest VCC, largest D21 leakage)."""
    rows = []
    for t in TEMPS:
        rows += _headroom_rows(main, [(3.0, icc_max(3.0)), (VSYS_FW, icc_max(VSYS_FW))], weak=False, temp=t)

    def one(t):
        return t, steady(main, f"temp {t} C light", temp=t, vsys=VSYS_USB, icc=ICC_LIGHT, derate=True,
                         t_meas=0.6e-3)
    for t, r in pmap(one, TEMPS):
        rows += [(f"VCC min, {t:g} C, VSYS {VSYS_USB} V, {ICC_LIGHT} mA", r["vmin"], VCC_MIN, None, "V", SRC_VCC),
                 (f"VCC max, {t:g} C, VSYS {VSYS_USB} V, {ICC_LIGHT} mA", r["vmax"], None, VCC_MAX, "V", SRC_VCC)]
    soft_checks(check, rows)


def test_startup_inrush_and_overshoot(main, check):
    """OLED_VCC_EN rising with the display off: VSYS 3.0 V with marked caps (slowest start, longest inrush) and
    USB 4.6 V with derated caps (fastest edge, largest overshoot)."""
    jobs = [(3.0, False, 5.6e-3), (VSYS_USB, True, 4.3e-3)]

    def one(job):
        vs, der, tstop = job
        return job, startup(main, f"startup {vs} V", vsys=vs, derate=der, tstop=tstop)
    rows = []
    for (vs, der, _), r in pmap(one, jobs):
        tag = f"VSYS {vs} V, caps {'derated' if der else 'marked'}"
        rows += [(f"VCC reaches 12.5 V after OLED_VCC_EN, {tag}", r["tup"] - 20e-6, None, T_AF, "s", SRC_TAF),
                 (f"VCC overshoot peak, {tag}", r["vpk"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC settled, {tag}", r["vend"], VCC_MIN, VCC_MAX, "V", SRC_VCC),
                 (f"U21 peak current (inrush), {tag}", r["iu21pk"], None, U21_IPLS, "A", SRC_IPLS),
                 (f"L20 peak current at start-up, {tag}", r["ilpk"], None, L20_ISAT, "A", SRC_ISAT),
                 (f"D21 peak current at start-up, {tag}", r["idpk"], None, D21_IFRM, "A", SRC_IFRM),
                 (f"SW peak at start-up, {tag}", r["swpk"], None, SW_MAX, "V", SRC_SW)]
    soft_checks(check, rows)


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


def test_shutdown_vcc_discharge(main, check):
    """OLED_VCC_EN low (after AEh, display off): U21 opens, the boost drains C38 into VCC until UVLO and stops,
    VCC then floats down through the divider (no active discharge, never pulled to ground), and with the
    switch open nothing feeds VSYS into VCC."""
    t_off, t_end = 50e-6, 0.1

    def one(job):
        vs, temp = job
        deck = build(main, f"shutdown {vs} V {temp} C", vsys=vs, temp=temp, icc=0.0, derate=False,
                     en="off_at", t_en=t_off)
        deck.meas("tran vinlate MAX v(n_oled_vin) FROM=20m TO=100m")
        deck.meas("tran vccmax MAX v(n_p13v_oled)")
        deck.meas("tran vccend FIND v(n_p13v_oled) AT=100m")
        deck.meas("tran iu21late AVG i(vprb_u21) FROM=20m TO=100m")
        return job, run(deck, t_end, tmax="1u")
    rows = []
    for (vs, temp), r in pmap(one, [(VSYS_USB, 60.0), (3.0, 25.0)]):
        tag = f"VSYS {vs} V, {temp:g} C"
        rows += [(f"OLED_VIN max 20-100 ms after OLED_VCC_EN low, {tag}", r["vinlate"], None, UVLO_MAX, "V",
                  SRC_UVLO),
                 (f"VCC max during turn-off, {tag}", r["vccmax"], None, VCC_MAX, "V", SRC_VCC),
                 (f"VCC 100 ms after turn-off (floats, not pulled below VCI), {tag}", r["vccend"], 3.3, None,
                  "V", SRC_FLOAT + "; note (5) never pulled to ground"),
                 (f"VSYS current into U21 while off, {tag}", r["iu21late"], None, U21_ISD_MAX, "A", SRC_ISD)]
    # long-term state with OLED_VCC_EN low at the highest VSYS: VCC is held only by the panel ESD path from VCI
    deck = build(main, "off DC", vsys=VSYS_USB, icc=0.0, en="off", init="cold")
    deck.op()
    deck.print_op("v(n_p13v_oled)", "v(n_p3v3)", "i(vprb_u21)")
    r = deck.run()
    assert not r["_errors"], r["_log"][-2000:]
    rows += [("VCC with OLED_VCC_EN low (DC), VSYS 4.6 V", r["op_0"], None, r["op_1"], "V",
              SRC_FLOAT + ": must not exceed VCI (+3V3)"),
             ("VSYS current into U21 with OLED_VCC_EN low (DC)", r["op_2"], None, U21_ISD_MAX, "A", SRC_ISD)]
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
