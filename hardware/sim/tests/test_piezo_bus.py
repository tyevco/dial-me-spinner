"""SPICE tests, circuit key `piezo_bus`: the piezo sounder and the I2C / open-drain lines.

Circuits (main board `sensors` sheet, plus the base board across the 12-way link):
  1. Piezo: BZ1 PKMCS0909E4000-R1 driven differentially by nRF P0.12 (BUZZ_A) / P1.08 (BUZZ_B) through
     R57 / R58, R59 bleed across BZ1. Complementary 4 kHz PWM (docs/firmware.md 8.1, H0H1 drive).
  2. TMAG bus (TWIM0, about 390 kHz: FREQUENCY = 0x06200000, docs/firmware.md 4.4): TMAG_SCL / TMAG_SDA
     (R50 / R51), TMAG_INT_N (R52), U30 TMAG5273,
     U32 TPD4E05U06 clamps.
  3. System bus (TWIM1, 250 kHz, or 100 kHz per docs/firmware.md 3.1): I2C_SCL / I2C_SDA (R53 / R54) to U31
     LIS2DW12 and, through main J1 -
     harness - base J3, to base U1 BQ25180. CHG_INT_N (R55) from the BQ25180 /INT, BTN_N (R56) from base
     Q1B (BSS138DW, gate from SW1 / R3 / R4), IMU_INT1 / IMU_INT2 push-pull from the LIS2DW12.

Passives come from the netlists (Design.passives / Design.value), so a schematic change shows up on
the next run. IC behaviour comes from the piezo_bus__*.lib models; each file cites its datasheet.
Numbers that no document fixes yet (trace lengths, harness capacitance) are in LAYOUT / CSETS below,
and the worst-case set doubles them.

Supply corners. Every circuit here runs from +3V3, an RT9080-33 LDO on VSYS (DS9080-09: +/-2 % accuracy,
0.31 V dropout at 600 mA). VBAT 3.7 / 4.2 V and USB VBUS 4.5 / 5.0 / 5.5 V (VSYS = the BQ25180 SYS_REG:
4.4 V as docs/firmware.md 13.1 row 8 sets it, 4.5 V POR default) all leave the LDO in regulation, so
+3V3 = 3.3 V +/-2 %. At VBAT 3.0 V the LDO is in dropout,
so +3V3 is about 2.99 V. The base-side parts see VBAT directly (BTN_N gate drive).

TWIM master timing (TWIM table below): the nRF52840 at 400 kHz holds SCL low for only 1.25 us (Nordic errata
219), which test_twim_tlow_400k_errata219 shows violating tLOW at every receiver (strict xfail: the OLD firmware
configuration, kept as the evidence for rule NF-1); test_twim_tlow_errata219_remedy is the configuration
firmware.md now documents (TWIM0 0x06200000, TWIM1 250 kHz, S0D1) and guards it. The bus-quality tests
(test_system_bus_transaction & co.) keep the 400 kHz SCL pattern: its shorter low / high phases are stricter for
tSU;DAT and tHIGH than the firmware's 250 kHz. The pin model's gate ramp (EDGE) is calibrated to the PS
tHRF,25pF / tRF,25pF edge rates.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

import spicelib
sys.path.insert(0, os.path.join(spicelib.HW, "design"))
from nets import MCU_PINS  # noqa: E402
from spicelib import Deck

LIB = {k: f"piezo_bus__{k}.lib" for k in
       ("nrf52840_gpio", "pkmcs0909e", "tmag5273", "lis2dw12", "bq25180", "tpd4e05u06", "bss138dw",
        "link_harness")}

# ------------------------------------------------------------------------------------------------ sources
S_NRF = "nRF52840 PS v1.1 §6.9.3.1"
S_UM = "NXP UM10204 Rev 7.0"
S_TMAG = "TMAG5273 DS SLYS045C"
S_LIS = "LIS2DW12 DS11811 Rev 8"
S_BQ = "BQ25180 DS SLUSE99C"
S_MUR = "Murata PKMCS0909E4000-R1 data sheet (2024-02-26)"

# ------------------------------------------------------------------------------------------------ limits
I_PIN_MAX = 14e-3      # nRF IOH,HDH max 14 mA (IOL,HDH max 15 mA): the largest characterised pin current
I_EXT_MAX = 25e-3      # nRF IEXT,HIGH 25 mA, PS v1.1 §5.3.8.2: the only Nordic sum-of-GPIO-currents limit
VOP_MIN = 1.5          # Murata SPL rating condition: +/-1.5 Vo-p, 4.0 kHz square wave (65 dB min)
VOP_MAX = 12.5         # Murata maximum input voltage +/-12.5 Vo-p
F_PIEZO = 4.0e3        # Murata rated frequency 4.0 kHz (docs/firmware.md 8.1 drives at 4.0 kHz)
TR_FM, TR_FMP = 300e-9, 120e-9          # UM10204 Table 11 tr (Fm / Fm+), TMAG Table 5.10 ticr / ticr_fmp
TF_FM = 300e-9                          # UM10204 Table 11 tf (Fm)
VOL_I2C = 0.4                           # UM10204 Table 10 VOL1
T_SU_DAT, T_HIGH, T_LOW = 100e-9, 0.6e-6, 1.3e-6   # UM10204 Table 11 Fm; LIS2DW12 Table 7 (same values)
V_ABS_MIN = -0.3                        # nRF Table 173, LIS2DW12 abs max, BQ25180 §7.1 "all other pins"
V_MAX_RX = {"LIS2DW12": lambda vdd: vdd + 0.3, "BQ25180": lambda vdd: 5.5}   # overshoot limit per receiver
V_MAX_SRC = {"LIS2DW12": "LIS2DW12 DS11811 Table 9 Vin ≤ Vdd_IO + 0.3 V; nRF PS Table 173 VDD + 0.3 V",
             "BQ25180": "BQ25180 DS SLUSE99C §7.1 all other pins 5.5 V"}
TMAG_IOUT_MAX = 2e-3                    # TMAG5273 Table 5.3 IOUT (SDA, INT) recommended max (steady)
TMAG_IOUT_ABS = 10e-3                   # TMAG5273 Table 5.1 IOUT (SDA, INT) absolute max (edge peak)
LIS_IOL_MAX = 4e-3                      # LIS2DW12 Table 4 note 5: 4 mA maximum driving capability
BQ_IOL_MAX = 5e-3                       # BQ25180 §7.5 VOL test condition 5 mA
BQ_VIL, BQ_VIH = 0.4, 1.3               # BQ25180 §7.5 I2C VIL max / VIH min
T_INT_TMAG = 10e-6                      # TMAG5273 Table 5.5 tINT (pulse mode), 10 us TYP (no min/max published)
T_CONV_MIN_TMAG = 50e-6                 # TMAG5273 Table 5.11 tmeasure 50 us TYP (no min published), CONV_AVG =
#                                         000b, one channel: the shortest INT period; more channels only lengthen it
T_INT_BQ = 128e-6                       # BQ25180 Table 6-1 /INT 128 us active-low pulse

# nRF52840 TWIM master timing. The PS (§6.31.8.2) gives only tTWIM,HD_DAT >= 500 ns and tTWIM,SU_DAT >= 300 ns,
# not the SCL duty cycle. Nordic errata 219 ("TWIM: I2C timing spec is violated at 400 kHz", nRF52840 Rev 3,
# https://docs.nordicsemi.com/bundle/errata_nRF52840_Rev3/page/ERR/nRF52840/Rev3/latest/anomaly_840_219.html)
# documents the actual SCL low period at 400 kHz: 1.25 us, below the 1.3 us that UM10204 / LIS2DW12 / TMAG5273
# require. Workaround: FREQUENCY = 0x06200000 (390 kHz), "the SCL low period is greater than 1.3 us" (the
# boundary 1.30 us is used). The high phase is taken as 1.2 us at 400 / 390 kHz (conservative: the period minus
# the 1.3 us spec low, shorter than the errata's 2.5 - 1.25 us). 250 kbps (PS K250) is not in errata 219; its
# low phase is not published, so it is INFERRED as half the 4 us period, as the errata's 1.25 us is at 400 kHz.
TWIM = {"400k": dict(tlow=1.25e-6, thigh=1.2e-6), "390k": dict(tlow=1.30e-6, thigh=1.2e-6),
        "250k": dict(tlow=2.0e-6, thigh=2.0e-6)}
T_HD_DAT_TWIM = 500e-9                  # PS v1.1 §6.31.8.2 tTWIM,HD_DAT min: master changes SDA >= 500 ns after SCL
#                                         falls. The data edge is placed there (setup = tLOW - 500 ns). The PS
#                                         also allows it as late as tTWIM,SU_DAT = 300 ns before SCL rises.

# ------------------------------------------------------------------------------------------------ supplies
RT9080_ACC = 0.02                       # DS9080-09 VVOUT_ACC +/-2 %
RT9080_RDROP = 0.31 / 0.6               # DS9080-09 dropout 0.31 V at 600 mA (VOUT >= 3 V)
I_3V3_ACTIVE = 0.02                     # +3V3 load while sounding / bus active (estimate: nRF CPU + radio)
VDD = {
    "vbat3.0": 3.0 - RT9080_RDROP * I_3V3_ACTIVE,   # VBAT 3.0 V: LDO in dropout
    "lo": 3.3 * (1 - RT9080_ACC),                   # VBAT 3.7/4.2 V or USB 4.5-5.5 V (VSYS 4.4/4.5 V), +3V3 -2 %
    "nom": 3.3,
    "hi": 3.3 * (1 + RT9080_ACC),                   # same supply states, +3V3 +2 %
}
SUPPLY_IDS = list(VDD)

# nRF52840 drive corners (PS v1.1 §6.9.3.1): (IOH, IOL) at 0.4 V from the rail
DRIVE = {"SD": {"min": (1e-3, 1e-3), "typ": (2e-3, 2e-3), "max": (4e-3, 4e-3)},
         "HD": {"min": (6e-3, 6e-3), "typ": (9e-3, 10e-3), "max": (14e-3, 15e-3)}}
# Gate-ramp time of the pin model's onp/onn controls, calibrated against PS §6.9.3.1 (10-90 % into 25 pF, typ
# pin): an 11 ns ramp gives 5.0 ns for H0H1/H0D1 typ = tHRF,25pF (the ramp is not the edge: a 5 ns ramp gave
# 3.6 ns, 1.4x too fast). Standard drive is current-limited at 15-16 ns for any ramp (tRF,25pF 13 ns typ).
EDGE = {"SD": 13e-9, "HD": 11e-9}

# ------------------------------------------------------------------------------------------------ layout / harness
# Trace budget (main is not routed yet): straight-line placement distance (SPEC §8 positions) x 1.5.
# 1.2 pF/cm is a 50-ohm microstrip on the JLC 4-layer stack (C = sqrt(eps_eff)/(c0*Z0)); thinner I2C
# traces have less. The worst-case set doubles the length.
C_PER_MM = 0.12e-12
LAYOUT = {"tmag_mm": 40, "sys_main_mm": 60, "sys_base_mm": 45}
CSETS = {
    # c_nrf: CPAD 3 pF typ (worst: UM10204 Ci max 10 pF; the PS has no max). c_dev: TMAG / LIS / BQ pin C,
    # unpublished, so UM10204 Ci max 10 pF in both sets. Harness per piezo_bus__link_harness.lib.
    "nom": dict(c_nrf=3e-12, c_dev=10e-12, c_tpd=0.5e-12, trace=1.0, h_len=0.08, h_cg=60e-12, h_cm=45e-12),
    "worst": dict(c_nrf=10e-12, c_dev=10e-12, c_tpd=0.57e-12, trace=2.0, h_len=0.10, h_cg=90e-12, h_cm=68e-12),
}
# Ground offset between the boards: main-board current returns through 3 GND wires (pins 3, 4, 8),
# 28 AWG (SPEC §2) 0.213 ohm/m x 0.10 m plus 2 x 40 mohm JST SH contacts (eSH, after environment tests).
R_GND = (0.213 * 0.10 + 2 * 0.040) / 3
I_GND = {"idle": 0.0, "fw_cap": 0.7, "hw_worst": 1.35,    # docs/architecture.md §4.2 (A)
         # fault angle (stalled motor, shorted LED, ...): the BQ25180 caps what SYS can deliver at its abs max
         # discharge current, 1.5 A DC and 2.5 A for < 20 ms (SLUSE99C §7.1); an I2C transfer can fall inside.
         "sys_absmax_dc": 1.5, "sys_absmax_20ms": 2.5}
GB = "n_gnd_b"                                              # base-board ground node


# ================================================================================================ helpers
def run(deck: Deck) -> dict:
    res = deck.run()
    assert not res["_errors"], "ngspice: " + " | ".join(res["_errors"][:5])
    return res


def gpio(inst, pad, vdd_node, onp, onn, mode, corner, vdd, nfc=False):
    ioh, iol = DRIVE[mode][corner]
    cpad = 4e-12 if nfc else 3e-12
    return (f"X{inst} {pad} {vdd_node} 0 {onp} {onn} NRF52840_GPIO ioh={ioh:g} iol={iol:g} "
            f"vddc={vdd:.5g} cpad={cpad:g}")


def gpio_in(inst, pad, vdd_node, vdd, cpad):
    """Input (output stage disconnected) nRF pad."""
    return (f"X{inst} {pad} {vdd_node} 0 0 0 NRF52840_GPIO ioh=1m iol=1m vddc={vdd:.5g} cpad={cpad:g}")


def ctl(name, spec, ref="0"):
    """Logic control source (0..1 V); returns the node name."""
    return f"VC_{name} c_{name} {ref} {spec}", f"c_{name}"


def bnode(node: str) -> str:
    """Base-board node names get a suffix so they do not merge with the main-board net of the same name."""
    return GB if node == "0" else node + "_b"


def base_lines(lines):
    out = []
    for ln in lines:
        tok = ln.split()
        tok[1], tok[2] = bnode(tok[1]), bnode(tok[2])
        out.append(" ".join(tok))
    return out


def tr3070(w, t, vdd, start=0.0):
    """30 % -> 70 % rise time (UM10204 definition) of the first rising edge after `start`."""
    m = t >= start
    t, w = t[m], w[m]
    return _cross(t, w, 0.7 * vdd, +1) - _cross(t, w, 0.3 * vdd, +1)


def _cross(t, w, level, direction, start=None, nth=1):
    """Time of the nth crossing of `level` (direction +1 rising, -1 falling), linear interpolation."""
    if start is not None:
        m = t >= start
        t, w = t[m], w[m]
    s = np.sign(w - level)
    idx = np.where((s[:-1] * direction < 0) & (s[1:] * direction >= 0))[0]
    if len(idx) < nth:
        return math.nan
    i = idx[nth - 1]
    return t[i] + (level - w[i]) * (t[i + 1] - t[i]) / (w[i + 1] - w[i])


def fundamental(t, v, f, t0, t1):
    """Amplitude of the f component of v over [t0, t1] (an integer number of periods)."""
    m = (t >= t0) & (t <= t1)
    tt, vv = t[m], v[m]
    w = 2 * math.pi * f
    a = 2 / (t1 - t0) * np.trapezoid(vv * np.cos(w * tt), tt)
    b = 2 / (t1 - t0) * np.trapezoid(vv * np.sin(w * tt), tt)
    return math.hypot(a, b)


# ================================================================================================ piezo
CF_NOM = 9e-9           # piezo_bus__pkmcs0909e.lib (distributor-listed Murata value)
CF_TOL = 0.30           # Murata piezo-element practice (7BB series +/-30 %), see the model header


def _piezo_nodes(d):
    a, b = d.pin("U10", "P0.12"), d.pin("U10", "P1.08")
    assert (a, b) == (d.node("BUZZ_A"), d.node("BUZZ_B")), "pin map changed: BUZZ_A/B must be P0.12/P1.08"
    return a, b, d.pin("BZ1", "1"), d.pin("BZ1", "2")


def piezo_drive(d, vdd, mode="HD", corner="max", cf=CF_NOM, scale=None, pz="", ncyc=4):
    """Complementary 4 kHz square drive. Returns peak pin currents, swing and 4 kHz fundamental across BZ1."""
    a, b, p, n = _piezo_nodes(d)
    T, tr = 1 / F_PIEZO, EDGE[mode]
    td = T / 4
    deck = Deck(f"piezo drive {mode}-{corner} vdd={vdd:.3f}")
    deck.include(LIB["nrf52840_gpio"]).include(LIB["pkmcs0909e"])
    v3 = d.node("+3V3")
    deck += f"V3V3 {v3} 0 DC {vdd:.5g}"
    deck += d.passives(nets={"BUZZ_A", "BUZZ_B", "BZ_P", "BZ_N"}, scale=scale)
    deck += [f"VIA {a}_pad {a} 0", f"VIB {b}_pad {b} 0"]       # + = current out of the pin
    hi, lo = f"PULSE(0 1 {td:g} {tr:g} {tr:g} {T / 2 - tr:g} {T:g})", f"PULSE(1 0 {td:g} {tr:g} {tr:g} {T / 2 - tr:g} {T:g})"
    for line, _ in (ctl("ap", hi), ctl("an", lo), ctl("bp", lo), ctl("bn", hi)):
        deck += line
    deck += gpio("A", f"{a}_pad", v3, "c_ap", "c_an", mode, corner, vdd)
    deck += gpio("B", f"{b}_pad", v3, "c_bp", "c_bn", mode, corner, vdd)
    deck += f"XBZ {p} {n} PKMCS0909E cf={cf:g} {pz}"
    tstop = td + ncyc * T
    deck.tran("20n", f"{tstop:g}", 0, "100n")
    deck.wave(f"v({p})", f"v({n})", "i(via)", "i(vib)", f"v({a})", f"v({b})")
    w = run(deck)["waves"]
    t, vd, ia, ib = w["time"], w[f"v({p})"] - w[f"v({n})"], w["i(via)"], w["i(vib)"]
    vpins = np.concatenate([w[f"v({a})"], w[f"v({b})"]])
    edges = [td + k * T / 2 for k in range(1, 2 * ncyc)]
    settled = [abs(np.interp(e - 1e-6, t, vd)) for e in edges]          # swing just before each edge
    return dict(ipk_a=float(np.max(np.abs(ia))), ipk_b=float(np.max(np.abs(ib))),
                isum=float(np.max(np.abs(ia) + np.abs(ib))),
                vop=float(min(settled)), vpk=float(np.max(np.abs(vd))),
                vpin_min=float(np.min(vpins)), vpin_max=float(np.max(vpins)) - vdd,
                v1=fundamental(t, vd, F_PIEZO, td + (ncyc - 2) * T, td + ncyc * T))


def piezo_checks(check, r, tag, current=True, swing=True):
    if current:
        check(f"BUZZ_A peak pin current [{tag}]", r["ipk_a"], None, I_PIN_MAX, "A", f"{S_NRF} IOH,HDH max")
        check(f"BUZZ_B peak pin current [{tag}]", r["ipk_b"], None, I_PIN_MAX, "A", f"{S_NRF} IOH,HDH max")
        check(f"sum of BUZZ pin currents [{tag}]", r["isum"], None, I_EXT_MAX, "A",
              "nRF52840 PS v1.1 §5.3.8.2 IEXT,HIGH (budget)")
    if swing:
        check(f"BZ1 settled swing Vo-p [{tag}]", r["vop"], VOP_MIN, None, "V", f"{S_MUR} SPL condition ±1.5 Vo-p")
        check(f"BZ1 4 kHz fundamental [{tag}]", r["v1"], 4 / math.pi * VOP_MIN, None, "V",
              f"{S_MUR} ±1.5 Vo-p square (fundamental 4/π·1.5 V)")
    check(f"BZ1 peak voltage [{tag}]", r["vpk"], None, VOP_MAX, "V", f"{S_MUR} max input ±12.5 Vo-p")
    check(f"BUZZ pin minimum voltage (piezo ringing) [{tag}]", r["vpin_min"], V_ABS_MIN, None, "V",
          "nRF52840 PS v1.1 Table 173 VI/O min −0.3 V")
    check(f"BUZZ pin maximum voltage above VDD [{tag}]", r["vpin_max"], None, 0.3, "V",
          "nRF52840 PS v1.1 Table 173 VI/O max VDD + 0.3 V")


@pytest.mark.parametrize("drive", [("HD", "max"), ("HD", "min"), ("SD", "min")], ids=lambda x: "-".join(x))
@pytest.mark.parametrize("supply", SUPPLY_IDS)
def test_piezo_drive_supply_and_drive_corners(main, check, supply, drive):
    """4 kHz complementary drive at every +3V3 corner. H0H1 is what firmware.md 8.1 configures (max = the
    strongest pin, worst for current; min = weakest); S0S1 min is the case where firmware forgets H0H1."""
    mode, corner = drive
    r = piezo_drive(main, VDD[supply], mode, corner)
    piezo_checks(check, r, f"{supply} {mode}-{corner}")


def test_piezo_tolerance_extremes(main, check):
    """R57/R58/R59 tolerance corners x BZ1 capacitance +/-30 %, strongest pins at +3V3 max for the current
    checks, weakest pins at the VBAT 3.0 V dropout supply for the swing checks."""
    for k, sc in enumerate(main.extremes(["R57", "R58", "R59"])):
        for cfk in (1 - CF_TOL, 1 + CF_TOL):
            tag = f"corner {k} cf×{cfk:.1f}"
            r = piezo_drive(main, VDD["hi"], "HD", "max", cf=CF_NOM * cfk, scale=sc, ncyc=2)
            piezo_checks(check, r, tag + " strongest", swing=False)
            r = piezo_drive(main, VDD["vbat3.0"], "HD", "min", cf=CF_NOM * cfk, scale=sc, ncyc=3)
            piezo_checks(check, r, tag + " weakest", current=False)


@pytest.mark.parametrize("pz", ["ka=0.2 qa=4", "ka=0.05 qa=15", "kb=0.6 qb=7", "kb=0.316 qb=20"],
                         ids=["4k-strong", "4k-highQ", "8k-strong", "8k-highQ"])
def test_piezo_motional_sensitivity(main, check, pz):
    """The BVD motional branches are assumptions (model header): stronger coupling / higher Q loads the
    470 ohm drive more at 4 kHz. Weakest high-drive pins, VBAT 3.0 V supply."""
    r = piezo_drive(main, VDD["vbat3.0"], "HD", "min", pz=pz)
    piezo_checks(check, r, f"motional {pz}", current=False)


def piezo_bleed(d, vdd, cf=CF_NOM):
    """Drive BZ1 to +VDD (A high, B low), then disconnect both pins (pwm1_sleep, firmware.md) and fit the
    decay time constant of the voltage across BZ1."""
    a, b, p, n = _piezo_nodes(d)
    t0 = 100e-6
    deck = Deck("piezo bleed")
    deck.include(LIB["nrf52840_gpio"]).include(LIB["pkmcs0909e"])
    v3 = d.node("+3V3")
    deck += f"V3V3 {v3} 0 DC {vdd:.5g}"
    deck += d.passives(nets={"BUZZ_A", "BUZZ_B", "BZ_P", "BZ_N"})
    off = f"PWL(0 1 {t0:g} 1 {t0 + 5e-9:g} 0)"
    for line, _ in (ctl("ap", off), ctl("an", "DC 0"), ctl("bp", "DC 0"), ctl("bn", off)):
        deck += line
    deck += gpio("A", a, v3, "c_ap", "c_an", "HD", "typ", vdd)
    deck += gpio("B", b, v3, "c_bp", "c_bn", "HD", "typ", vdd)
    deck += f"XBZ {p} {n} PKMCS0909E cf={cf:g}"
    deck.tran("2u", "25m", 0, "20u")
    deck.wave(f"v({p})", f"v({n})")
    w = run(deck)["waves"]
    t, vd = w["time"], w[f"v({p})"] - w[f"v({n})"]
    m = (t > t0 + 1e-3) & (vd > 1e-3)
    if np.count_nonzero(m) < 10:            # no charge left to fit (e.g. BZ1 shorted): tau ~ 0, not a crash
        return 0.0, float(np.interp(t0, t, vd))
    slope = np.polyfit(t[m], np.log(vd[m]), 1)[0]
    return -1 / slope if slope < 0 else math.inf, float(np.interp(t0, t, vd))


def test_piezo_bleed_time_constant(main, check):
    """R59 bleeds BZ1 while the pins are disconnected (sheet note). Closed form tau = R59 * C(BZ1)."""
    tau, v0 = piezo_bleed(main, VDD["nom"])
    tau_cf = main.value("R59") * CF_NOM
    check("BZ1 charge at disconnect", v0, 0.95 * VDD["nom"], None, "V", "drive reached +VDD before disconnect")
    check("bleed time constant (R59 ∥ BZ1)", tau, 0.95 * tau_cf, 1.05 * tau_cf, "s",
          "closed form R59·C(BZ1) ±5 % (sensors sheet: R59 bleeds BZ1 in sleep)")


@pytest.mark.fault
def test_fault_piezo_series_r_100_ohm_per_spec(main, check):
    """Fault: R57/R58 fitted at SPEC §5.5's 100 ohm. The per-pin check must flag it."""
    main.override("R57", "100").override("R58", "100")
    r = piezo_drive(main, VDD["hi"], "HD", "max", ncyc=2)
    check("FAULT R57/R58=100Ω: BUZZ_A peak pin current exceeds limit", r["ipk_a"], I_PIN_MAX, None, "A",
          f"fault must violate {S_NRF} IOH,HDH max")
    check("FAULT R57/R58=100Ω: pin-current sum exceeds budget", r["isum"], I_EXT_MAX, None, "A",
          "fault must violate PS §5.3.8.2 IEXT,HIGH")


@pytest.mark.fault
def test_fault_piezo_series_r_bridged(main, check):
    """Fault: R57 and R58 replaced by 0-ohm links (a single bridged resistor still leaves 470 ohm in the
    loop: about 12-13 mA, inside the limit, which is why both are needed)."""
    main.short("R57").short("R58")
    r = piezo_drive(main, VDD["nom"], "HD", "typ", ncyc=2)
    check("FAULT R57+R58 bridged: BUZZ_A peak pin current exceeds limit", r["ipk_a"], I_PIN_MAX, None, "A",
          f"fault must violate {S_NRF} IOH,HDH max")


@pytest.mark.fault
def test_fault_piezo_bleed_missing(main, check):
    tau_cf = main.value("R59") * CF_NOM
    main.remove("R59")
    tau, _ = piezo_bleed(main, VDD["nom"])
    check("FAULT R59 left off: bleed tau outside closed form", tau, 1.05 * tau_cf, None, "s",
          "fault must violate closed form R59·C(BZ1)")


@pytest.mark.fault
def test_fault_piezo_pads_bridged(main, check):
    """Fault: BZ_P and BZ_N bridged (solder bridge across the R59 0402, or under BZ1). The swing and
    fundamental checks must flag the silent sounder; the author's fault tests exercise only the current
    and bleed checks."""
    main.short("R59")
    r = piezo_drive(main, VDD["nom"], "HD", "typ", ncyc=2)
    check("FAULT BZ_P-BZ_N bridged: BZ1 swing below the rating condition", r["vop"], None, VOP_MIN, "V",
          f"fault must violate {S_MUR} SPL condition ±1.5 Vo-p")
    check("FAULT BZ_P-BZ_N bridged: 4 kHz fundamental below the rating condition", r["v1"], None,
          4 / math.pi * VOP_MIN, "V", f"fault must violate {S_MUR} ±1.5 Vo-p square")


# ================================================================================================ TMAG bus
def tmag_bus(d, vdd, cs, ctls, scale=None, temp=25, tstop=None, waves=(), meas=(), op=False, prints=(),
             drive=("SD", "min")):
    """TMAG_SCL / TMAG_SDA / TMAG_INT_N on one deck. ctls: {'scl_nrf','sda_nrf','sda_tmag','int_tmag'} ->
    PWL/PULSE/DC spec of the logic control (1 = pull low). drive: nRF TWIM0 pin corner (S0D1 weakest default)."""
    v3 = d.node("+3V3")
    scl, sda, intn = d.node("TMAG_SCL"), d.node("TMAG_SDA"), d.node("TMAG_INT_N")
    assert d.pin("U10", "P0.24") == scl and d.pin("U10", "P0.25") == sda and d.pin("U10", "P0.27") == intn
    assert d.pin("U30", "SCL") == scl and d.pin("U30", "SDA") == sda and d.pin("U30", "INT") == intn
    tpd = {scl: d.pin("U32", "1"), sda: d.pin("U32", "2"), intn: d.pin("U32", "4")}
    assert tpd == {scl: scl, sda: sda, intn: intn}, "U32 must clamp TMAG_SCL/SDA/INT_N"
    deck = Deck("TMAG bus")
    for k in ("nrf52840_gpio", "tmag5273", "tpd4e05u06"):
        deck.include(LIB[k])
    deck += f"V3V3 {v3} 0 DC {vdd:.5g}"
    deck += d.passives(nets={"+3V3", "TMAG_SCL", "TMAG_SDA", "TMAG_INT_N"}, scale=scale)
    c = {}
    for k in ("scl_nrf", "sda_nrf", "sda_tmag", "int_tmag"):
        line, c[k] = ctl(k, ctls.get(k, "DC 0"))
        deck += line
    deck += gpio("NSCL", scl, v3, "0", c["scl_nrf"], *drive, vdd).replace("cpad=3e-12", f"cpad={cs['c_nrf']:g}")
    deck += gpio("NSDA", sda, v3, "0", c["sda_nrf"], *drive, vdd).replace("cpad=3e-12", f"cpad={cs['c_nrf']:g}")
    deck += gpio_in("NINT", intn, v3, vdd, cs["c_nrf"])
    deck += f"XTSCL {scl} 0 TMAG5273_IN ci={cs['c_dev']:g}"
    deck += f"VAM_TSDA {sda} {sda}_t 0"
    deck += f"XTSDA {sda}_t 0 {c['sda_tmag']} TMAG5273_OD vg={vdd:.5g} ci={cs['c_dev']:g}"
    deck += f"VAM_TINT {intn} {intn}_t 0"
    deck += f"XTINT {intn}_t 0 {c['int_tmag']} TMAG5273_OD vg={vdd:.5g} ci={cs['c_dev']:g}"
    ileak = 10e-9 * (4 if temp >= 60 else 1)        # TPD ILEAK 10 nA max, x4 at 60 C (Fig. 5-5 trend)
    for i, node in enumerate((scl, sda, intn)):
        deck += f"XESD{i} {node} 0 TPD4E05U06_CH cl={cs['c_tpd']:g} ileak={ileak:g}"
        deck += f"CTRACE{i} {node} 0 {LAYOUT['tmag_mm'] * cs['trace'] * C_PER_MM:g}"
    if op:
        deck.op()
        deck.print_op(*prints)
    else:
        deck.tran("1n", f"{tstop:g}", 0, "2n")
        for m in meas:
            deck.meas(m)
        if waves:
            deck.wave(*waves)
    return run(deck)


REL = "PWL(0 1 100n 1 113n 0)"          # pulled low, released at 100 ns (13 ns ramp = tRF,25pF)


@pytest.mark.parametrize("cset", list(CSETS))
@pytest.mark.parametrize("supply", SUPPLY_IDS)
def test_tmag_bus_rise_time(main, check, supply, cset):
    vdd, cs = VDD[supply], CSETS[cset]
    for k, sc in enumerate(main.extremes(["R50", "R51"])):
        scl, sda = main.node("TMAG_SCL"), main.node("TMAG_SDA")
        r = tmag_bus(main, vdd, cs, {"scl_nrf": REL, "sda_nrf": REL}, scale=sc, tstop=1.5e-6,
                     waves=(f"v({scl})", f"v({sda})"))
        w = r["waves"]
        for name, node in (("TMAG_SCL", scl), ("TMAG_SDA", sda)):
            tr = tr3070(w[f"v({node})"], w["time"], vdd)
            tag = f"{supply} {cset} R-corner {k}"
            check(f"{name} rise 30-70 % @400k [{tag}]", tr, None, TR_FM, "s",
                  f"{S_UM} Table 11 tr (Fm); {S_TMAG} Table 5.10 ticr")
            if cset == "nom":
                check(f"{name} rise 30-70 % Fm+ headroom [{tag}]", tr, None, TR_FMP, "s",
                      f"{S_UM} Table 11 tr (Fm+); {S_TMAG} ticr_fmp (nRF TWIM itself is limited to 400 kbps)")


@pytest.mark.parametrize("supply", SUPPLY_IDS)
def test_tmag_bus_vol(main, check, supply):
    """Strongest pull-up current (R -1 %) against the weakest pull-down: nRF S0D1 at IOL,SD min 1 mA, and
    the TMAG at VOL 0.4 V / 2 mA."""
    vdd = VDD[supply]
    sc = {"R50": 1 - main.tol("R50"), "R51": 1 - main.tol("R51")}
    scl, sda = main.node("TMAG_SCL"), main.node("TMAG_SDA")
    for drv, ctls in (("nRF S0D1 SCL", {"scl_nrf": "DC 1"}), ("nRF S0D1 SDA", {"sda_nrf": "DC 1"}),
                      ("TMAG SDA", {"sda_tmag": "DC 1"})):
        node = scl if "SCL" in drv else sda
        r = tmag_bus(main, vdd, CSETS["nom"], ctls, scale=sc, op=True, prints=(f"v({node})", "i(vam_tsda)"))
        vol = r["op_0"]
        check(f"TMAG bus VOL, {drv} [{supply}]", vol, None, VOL_I2C, "V", f"{S_UM} Table 10 VOL1")
        check(f"TMAG bus VOL vs VIL, {drv} [{supply}]", vol, None, 0.3 * vdd, "V",
              f"{S_NRF} VIL 0.3·VDD; {S_TMAG} Table 5.3 VIL 0.3·VCC")
        if drv.startswith("TMAG"):
            check(f"TMAG SDA sink current [{supply}]", r["op_1"], None, TMAG_IOUT_MAX, "A",
                  f"{S_TMAG} Table 5.3 IOUT max")


def tmag_int(d, vdd, temp=25, scale=None):
    intn = d.node("TMAG_INT_N")
    t0 = 1e-6
    pulse = f"PULSE(0 1 {t0:g} 5n 5n {T_INT_TMAG:g} 1)"
    r = tmag_bus(d, vdd, CSETS["worst"], {"int_tmag": pulse}, scale=scale, temp=temp, tstop=t0 + 60e-6,
                 waves=(f"v({intn})", "i(vam_tint)"))
    w = r["waves"]
    t, v = w["time"], w[f"v({intn})"]
    during = (t > t0 + 1e-6) & (t < t0 + T_INT_TMAG)
    vol = float(np.max(v[during]))
    t_vih = _cross(t, v, 0.7 * vdd, +1, start=t0 + T_INT_TMAG) - (t0 + T_INT_TMAG)
    i = w["i(vam_tint)"]                             # VAM_TINT: + = current into the TMAG pin (sinking)
    isink = float(np.max(i[during]))                 # steady sink current while INT is held low
    ipeak = float(np.max(i))                         # includes the line-capacitance discharge at the edge
    rop = tmag_bus(d, vdd, CSETS["worst"], {}, scale=scale, temp=temp, op=True, prints=(f"v({intn})",))
    return vol, t_vih, isink, ipeak, rop["op_0"]


@pytest.mark.parametrize("temp", [-10, 25, 60])
@pytest.mark.parametrize("supply", ["vbat3.0", "hi"])
def test_tmag_int_pulse(main, check, supply, temp):
    """TMAG INT pulse mode (10 us low). The line must be low at the nRF during the pulse and back above
    VIH before the next conversion can end (tmeasure 50 us min). Leakage (TMAG IOZ 100 nA + TPD) at temp."""
    vdd = VDD[supply]
    for k, sc in enumerate(main.extremes(["R52"])):
        vol, t_vih, isink, ipeak, voh = tmag_int(main, vdd, temp, sc)
        tag = f"{supply} {temp}°C R52-corner {k}"
        check(f"TMAG_INT_N low during pulse [{tag}]", vol, None, 0.3 * vdd, "V", f"{S_NRF} VIL 0.3·VDD")
        check(f"TMAG_INT_N back above VIH after pulse [{tag}]", t_vih, None, T_CONV_MIN_TMAG - T_INT_TMAG, "s",
              f"{S_TMAG} Table 5.11 tmeasure 50 µs typ (shortest INT period) − Table 5.5 tINT 10 µs typ")
        check(f"TMAG INT steady sink current [{tag}]", isink, None, TMAG_IOUT_MAX, "A",
              f"{S_TMAG} Table 5.3 IOUT recommended max")
        check(f"TMAG INT peak sink current at the edge [{tag}]", ipeak, None, TMAG_IOUT_ABS, "A",
              f"{S_TMAG} Table 5.1 IOUT absolute max")
        check(f"TMAG_INT_N idle high with leakage [{tag}]", voh, 0.7 * vdd, None, "V",
              f"{S_NRF} VIH 0.7·VDD (TMAG IOZ 100 nA, TPD ILEAK)")


@pytest.mark.fault
def test_fault_tmag_sda_pullup_47k(main, check):
    """Fault: R51 fitted as 47k (decade slip). The rise-time check must flag it."""
    main.override("R51", "47k")
    sda = main.node("TMAG_SDA")
    r = tmag_bus(main, VDD["nom"], CSETS["nom"], {"sda_nrf": REL}, tstop=8e-6, waves=(f"v({sda})",))
    tr = tr3070(r["waves"][f"v({sda})"], r["waves"]["time"], VDD["nom"])
    check("FAULT R51=47k: TMAG_SDA rise exceeds Fm limit", tr, TR_FM, None, "s", f"fault must violate {S_UM} tr")


@pytest.mark.fault
def test_fault_tmag_int_pullup_missing(main, check):
    main.remove("R52")
    voh = tmag_int(main, VDD["nom"], 25)[-1]
    check("FAULT R52 left off: TMAG_INT_N idle level below VIH", voh, None, 0.7 * VDD["nom"], "V",
          f"fault must violate {S_NRF} VIH")


# ================================================================================================ system bus
def sys_bus(d, b, vdd, cs, ctls, scale=None, vofs=0.0, vbat=3.7, temp=25, tstop=None, meas=(), waves=(),
            op=False, prints=(), drive=("SD", "min")):
    """System I2C + CHG_INT_N + BTN_N: main board, harness, base board in one deck.

    ctls keys (logic 1 = pull low / switch closed): scl_nrf, sda_nrf, sda_lis, sda_bq, int_bq, sw1.
    The base ground sits vofs below the main ground (harness GND return drop).
    drive: nRF TWIM pin corner (mode, min/typ/max). S0D1 is the TWIM default (no nordic,drive-mode in the
    i2c1 pinctrl, docs/firmware.md); ("SD", "min") is the weakest pin (worst for VOL and rise/fall),
    ("SD", "max") the fastest edge (worst for ringing, undershoot and crosstalk)."""
    v3 = d.node("+3V3")
    nets = ("I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N")
    mn = {n: d.node(n) for n in nets}
    bn = {n: bnode(b.node(n)) for n in nets}
    for i, n in enumerate(nets):             # link pins 9..12 on both ends (nets.LINK_PINOUT)
        assert d.pin("J1", str(9 + i)) == mn[n] and bnode(b.pin("J3", str(9 + i))) == bn[n], f"link pin {9 + i}"
    assert d.pin("U10", "P0.08") == mn["I2C_SCL"] and d.pin("U10", "P1.09") == mn["I2C_SDA"]
    pin_of = {net: pin for pin, net in MCU_PINS.items() if net}      # nets.py is the pin map of record
    assert d.pin("U10", pin_of["CHG_INT_N"]) == mn["CHG_INT_N"] and d.pin("U10", pin_of["BTN_N"]) == mn["BTN_N"]
    assert d.pin("U31", "SCL/SPC") == mn["I2C_SCL"] and d.pin("U31", "SDA/SDI/SDO") == mn["I2C_SDA"]
    assert bnode(b.pin("U1", "SCL")) == bn["I2C_SCL"] and bnode(b.pin("U1", "SDA")) == bn["I2C_SDA"]
    assert bnode(b.pin("U1", "~{INT}")) == bn["CHG_INT_N"] and bnode(b.pin("Q1", "3")) == bn["BTN_N"]

    deck = Deck("system bus")
    # Gear integration at SPICE-default reltol: the harness ladder has ~1 GHz LC modes that trapezoidal
    # integration keeps ringing on (45k points per 6 us). Checked against trap / reltol 1e-4: < 0.5 ns.
    deck.options = ["option noacct", "option reltol=1e-3", "option method=gear"]
    for k in ("nrf52840_gpio", "lis2dw12", "bq25180", "bss138dw", "link_harness"):
        deck.include(LIB[k])
    deck += f"V3V3 {v3} 0 DC {vdd:.5g}"
    deck += f"VGOFS {GB} 0 DC {-vofs:.6g}"
    deck += d.passives(nets={"+3V3", *nets}, scale=scale)                       # R53..R56
    c = {}
    for k in ("scl_nrf", "sda_nrf", "sda_lis", "sda_bq", "int_bq"):
        line, c[k] = ctl(k, ctls.get(k, "DC 0"), "0" if k.endswith(("nrf", "lis")) else GB)
        deck += line
    line, c["sw1"] = ctl("sw1", ctls.get("sw1", "DC 0"), GB)
    deck += line
    # ---- main board
    cn = f"cpad={cs['c_nrf']:g}"
    deck += gpio("NSCL", mn["I2C_SCL"], v3, "0", c["scl_nrf"], *drive, vdd).replace("cpad=3e-12", cn)
    deck += gpio("NSDA", mn["I2C_SDA"], v3, "0", c["sda_nrf"], *drive, vdd).replace("cpad=3e-12", cn)
    deck += gpio_in("NINT", mn["CHG_INT_N"], v3, vdd, cs["c_nrf"])   # CHG_INT_N on a plain GPIO (P1.03)
    deck += gpio_in("NBTN", mn["BTN_N"], v3, vdd, cs["c_nrf"])
    deck += f"XLSCL {mn['I2C_SCL']} 0 LIS2DW12_IN ci={cs['c_dev']:g}"
    deck += f"VAM_LSDA {mn['I2C_SDA']} {mn['I2C_SDA']}_l 0"
    deck += f"XLSDA {mn['I2C_SDA']}_l 0 {c['sda_lis']} LIS2DW12_OD vg={vdd:.5g} ci={cs['c_dev']:g}"
    for i, n in enumerate(nets):
        deck += f"CTM{i} {mn[n]} 0 {LAYOUT['sys_main_mm'] * cs['trace'] * C_PER_MM:g}"
        deck += f"CTB{i} {bn[n]} {GB} {LAYOUT['sys_base_mm'] * cs['trace'] * C_PER_MM:g}"
    # ---- harness (J1 9..12 -> J3 9..12)
    deck += (f"XLINK {' '.join(mn[n] for n in nets)} {' '.join(bn[n] for n in nets)} 0 LINK_SIG4 "
             f"len={cs['h_len']:g} cg={cs['h_cg']:g} cm={cs['h_cm']:g}")
    # ---- base board (ground GB)
    deck += f"XBSCL {bn['I2C_SCL']} {GB} BQ25180_IN ci={cs['c_dev']:g}"
    deck += f"VAM_BSDA {bn['I2C_SDA']} {bn['I2C_SDA']}_q 0"
    deck += f"XBSDA {bn['I2C_SDA']}_q {GB} {c['sda_bq']} BQ25180_OD ci={cs['c_dev']:g}"
    deck += f"VAM_BINT {bn['CHG_INT_N']} {bn['CHG_INT_N']}_q 0"
    deck += f"XBINT {bn['CHG_INT_N']}_q {GB} {c['int_bq']} BQ25180_OD ci={cs['c_dev']:g}"
    # R3, R4, C3. RT1 (NTC on CHG_TSMR) is skipped by passives() (ref "RT1" is not R<digit>); it only loads
    # Q1A's drain on TS/MR, not BTN_N, and Q1A's drain is otherwise held by its body diode / IDSS here.
    deck += base_lines(b.passives(nets={"VBAT", "SW_HI", "SW_GATE", "CHG_TSMR", "GND"}))
    deck += f"VVBAT {bnode(b.node('VBAT'))} {GB} DC {vbat:.4g}"
    # SW1 (TS-1187A, generic 0.1 ohm contact) between SW_HI and SW_GATE
    deck += (f"SSW1 {bnode(b.pin('SW1', '1'))} {bnode(b.pin('SW1', '2'))} {c['sw1']} {GB} SWTACT")
    deck += ".model SWTACT SW(VT=0.5 VH=0.1 RON=0.1 ROFF=1e12)"
    vth = 1.5 + (25 - temp) * 3.5e-3                                   # DS30203 table max + Fig. 4 slope
    rdsf = float(np.interp(temp, [-55, -5, 45, 95, 145], [0.70, 0.88, 1.10, 1.38, 1.85]))   # Fig. 3
    idss = 0.5e-6 * 2 ** ((temp - 25) / 10)
    q = f"vth={vth:.4g} rds10={3.5 * rdsf:.4g} idss={idss:.4g}"
    deck += f"XQ1B {bnode(b.pin('Q1', '3'))} {bnode(b.pin('Q1', '5'))} {bnode(b.pin('Q1', '4'))} BSS138DW_FET {q}"
    deck += f"XQ1A {bnode(b.pin('Q1', '6'))} {bnode(b.pin('Q1', '2'))} {bnode(b.pin('Q1', '1'))} BSS138DW_FET {q}"
    if op:
        deck.op()
        deck.print_op(*prints)
    else:
        deck.tran("1n", f"{tstop:g}", 0, "2n")
        for m in meas:
            deck.meas(m)
        if waves:
            deck.wave(*waves)
    return run(deck), mn, bn


def i2c_transaction(d, b, vdd, cs, scale=None, vofs=0.0, rate="400k", drive=("SD", "min")):
    """TWIM pattern at `rate` (TWIM table: errata 219 SCL low 1.25 us at 400 kHz, >= 1.3 us at the 390 kHz
    workaround; high 1.2 us); SDA released tTWIM,HD_DAT = 500 ns after SCL falls, one '1' bit, then driven
    low again. Returns per receiver the bus quantities: tr, tf, tSU;DAT, tHIGH, tLOW (at the receiver's own
    VIL), crosstalk dip, undershoot and overshoot."""
    t0, tl, th, hd = 0.5e-6, TWIM[rate]["tlow"], TWIM[rate]["thigh"], T_HD_DAT_TWIM
    e = EDGE[drive[0]]
    f1, r1, f2, r2 = t0, t0 + tl, t0 + tl + th, t0 + 2 * tl + th
    scl = f"PWL(0 0 {f1:g} 0 {f1 + e:g} 1 {r1:g} 1 {r1 + e:g} 0 {f2:g} 0 {f2 + e:g} 1 {r2:g} 1 {r2 + e:g} 0)"
    sda = f"PWL(0 1 {f1 + hd:g} 1 {f1 + hd + e:g} 0 {f2 + hd:g} 0 {f2 + hd + e:g} 1)"
    tstop = r2 + 1.0e-6
    nodes = [d.node(n) for n in ("I2C_SCL", "I2C_SDA")] + [bnode(b.node(n)) for n in ("I2C_SCL", "I2C_SDA")]
    r, mn, bn = sys_bus(d, b, vdd, cs, {"scl_nrf": scl, "sda_nrf": sda}, scale=scale, vofs=vofs, tstop=tstop,
                        waves=tuple(f"v({x})" for x in nodes), drive=drive)
    w = r["waves"]
    t = w["time"]
    out = {}
    rx = {  # receiver: (scl node, sda node, ground offset, VIL, VIH)
        "LIS2DW12": (mn["I2C_SCL"], mn["I2C_SDA"], 0.0, 0.2 * vdd, 0.8 * vdd),
        "BQ25180": (bn["I2C_SCL"], bn["I2C_SDA"], -vofs, 0.3 * vdd, 0.7 * vdd),
    }
    for name, (ns, nd, g, vil, vih) in rx.items():
        vs, vd = w[f"v({ns})"] - g, w[f"v({nd})"] - g
        out[name] = dict(
            tr=tr3070(vs, t, vdd, start=r1),
            tf=_cross(t, vs, 0.3 * vdd, -1, start=f2 - 0.1e-6) - _cross(t, vs, 0.7 * vdd, -1, start=f2 - 0.1e-6),
            tsu=_cross(t, vs, vil, +1, start=r1 - 0.2e-6) - _cross(t, vd, vih, +1, start=f1),
            thigh=_cross(t, vs, vih, -1, start=r1) - _cross(t, vs, vih, +1, start=r1 - 0.2e-6),
            tlow=_cross(t, vs, vil, +1, start=r1 - 0.2e-6) - _cross(t, vs, vil, -1, start=f1 - 0.1e-6),
            sda_dip=float(np.min(vd[(t > f2 - 20e-9) & (t < f2 + 0.3e-6)])),
            vmin=float(min(np.min(vs), np.min(vd))),
            vmax=float(max(np.max(vs), np.max(vd))),
            vih=vih)
    return out


def transaction_checks(check, out, vdd, tag):
    for name, m in out.items():
        src_t = f"{S_UM} Table 11" + (f"; {S_LIS} Table 7 (0.2/0.8·VDD_IO points)" if name == "LIS2DW12" else "")
        check(f"I2C_SCL rise 30-70 % at {name} [{tag}]", m["tr"], None, TR_FM, "s", f"{S_UM} Table 11 tr (Fm)")
        check(f"I2C_SCL fall 70-30 % at {name} [{tag}]", m["tf"], None, TF_FM, "s", f"{S_UM} Table 11 tf (Fm)")
        check(f"I2C tSU;DAT at {name} [{tag}]", m["tsu"], T_SU_DAT, None, "s",
              src_t + "; master SDA edge at nRF PS §6.31.8.2 tTWIM,HD_DAT 500 ns after SCL falls")
        check(f"I2C tHIGH at {name} [{tag}]", m["thigh"], T_HIGH, None, "s", src_t)
        check(f"I2C_SDA crosstalk dip at SCL fall, {name} [{tag}]", m["sda_dip"], m["vih"], None, "V",
              f"{S_UM} Table 11 VnH 0.2·VDD / receiver VIH")
        check(f"I2C undershoot at {name} [{tag}]", m["vmin"], V_ABS_MIN, None, "V",
              "abs max −0.3 V (nRF PS Table 173, LIS2DW12, BQ25180 §7.1)")
        check(f"I2C overshoot at {name} [{tag}]", m["vmax"], None, V_MAX_RX[name](vdd), "V", V_MAX_SRC[name])


@pytest.mark.parametrize("cset", list(CSETS))
@pytest.mark.parametrize("supply", SUPPLY_IDS)
def test_system_bus_transaction(main, base, check, supply, cset):
    """Rise/fall, setup, high/low times, crosstalk and undershoot at the IMU (main) and the charger (base,
    through the harness), for every R53/R54 tolerance corner, with the worst ground offset."""
    vdd, cs = VDD[supply], CSETS[cset]
    for k, sc in enumerate(main.extremes(["R53", "R54"])):
        out = i2c_transaction(main, base, vdd, cs, scale=sc, vofs=I_GND["hw_worst"] * R_GND)
        transaction_checks(check, out, vdd, f"{supply} {cset} R-corner {k}")


@pytest.mark.slow
def test_system_bus_monte_carlo(main, base, check):
    """200 draws: R53/R54 within tolerance plus the unpublished quantities drawn across their whole
    ranges (device pin C 2-10 pF, nRF pad 3-10 pF, trace x0.5-2, harness 50-100 mm, 30-90 pF/m to the
    bundle, 20-68 pF/m between neighbours, ground offset 0..hw worst), +3V3 anywhere in its corners."""
    rng = np.random.default_rng(7)
    worst = {}
    for k, sc in enumerate(main.monte_carlo(["R53", "R54"], 200, seed=7)):
        cs = dict(c_nrf=rng.uniform(3e-12, 10e-12), c_dev=rng.uniform(2e-12, 10e-12), c_tpd=0.5e-12,
                  trace=rng.uniform(0.5, 2.0), h_len=rng.uniform(0.05, 0.10), h_cg=rng.uniform(30e-12, 90e-12),
                  h_cm=rng.uniform(20e-12, 68e-12))
        vdd = rng.uniform(VDD["vbat3.0"], VDD["hi"])
        out = i2c_transaction(main, base, vdd, cs, scale=sc, vofs=rng.uniform(0, I_GND["hw_worst"]) * R_GND)
        for name, m in out.items():
            for key, val in m.items():
                if key in ("vih", "vmax", "tlow"):      # tLOW: test_twim_tlow_*; overshoot: RC edges, none
                    continue
                if key in ("sda_dip", "vmin"):
                    val = val - (m["vih"] if key == "sda_dip" else V_ABS_MIN)     # margin, worst = lowest
                    best = worst.get((name, key))
                    worst[(name, key)] = val if best is None else min(best, val)
                elif key in ("tr", "tf"):
                    worst[(name, key)] = max(worst.get((name, key), -1.0), val)
                else:
                    worst[(name, key)] = min(worst.get((name, key), 1.0), val)
    for name in ("LIS2DW12", "BQ25180"):
        check(f"MC worst I2C_SCL rise at {name}", worst[(name, "tr")], None, TR_FM, "s", f"{S_UM} Table 11 tr")
        check(f"MC worst I2C_SCL fall at {name}", worst[(name, "tf")], None, TF_FM, "s", f"{S_UM} Table 11 tf")
        check(f"MC worst tSU;DAT at {name}", worst[(name, "tsu")], T_SU_DAT, None, "s", f"{S_UM} Table 11")
        check(f"MC worst tHIGH at {name}", worst[(name, "thigh")], T_HIGH, None, "s", f"{S_UM} Table 11")
        check(f"MC worst SDA dip margin above VIH at {name}", worst[(name, "sda_dip")], 0.0, None, "V",
              f"{S_UM} Table 11 VnH")
        check(f"MC worst undershoot margin at {name}", worst[(name, "vmin")], 0.0, None, "V", "abs max −0.3 V")


@pytest.mark.parametrize("cset", list(CSETS))
@pytest.mark.parametrize("supply", ["vbat3.0", "hi"])
def test_system_bus_fast_edges(main, base, check, supply, cset):
    """Harness ringing, undershoot, overshoot and SDA crosstalk are worst with the FASTEST pull-down, not the
    weakest pin the timing tests use: S0D1 max (IOL,SD 4 mA), the strongest pin in the configured TWIM mode.
    No ground offset: an offset lifts the base-side waveform, so zero is worst for undershoot at the BQ25180.
    (H0D1 max, with the calibrated 5 ns edge, reaches -0.30 V at the BQ25180 here: at the abs max.)"""
    vdd, drive = VDD[supply], ("SD", "max")
    out = i2c_transaction(main, base, vdd, CSETS[cset], vofs=0.0, drive=drive)
    tag = f"{supply} {cset} nRF {drive[0]}-{drive[1]}"
    for name, m in out.items():
        check(f"I2C undershoot at {name}, fast edge [{tag}]", m["vmin"], V_ABS_MIN, None, "V",
              "abs max −0.3 V (nRF PS Table 173, LIS2DW12 Table 9, BQ25180 §7.1)")
        check(f"I2C overshoot at {name}, fast edge [{tag}]", m["vmax"], None, V_MAX_RX[name](vdd), "V",
              V_MAX_SRC[name])
        check(f"I2C_SDA crosstalk dip at SCL fall, {name}, fast edge [{tag}]", m["sda_dip"], m["vih"], None, "V",
              f"{S_UM} Table 11 VnH 0.2·VDD / receiver VIH")


# ------------------------------------------------------------------------------------------------ tLOW (errata 219)
TLOW_SRC = {"LIS2DW12": f"{S_LIS} Table 7 tw(SCLL) 1.3 µs at the 0.2·Vdd_IO point (Table 7 note); {S_UM} Table 11",
            "BQ25180": f"{S_UM} Table 11 tLOW 1.3 µs (Fm, 0.3·VDD); {S_BQ} §8.3.14 F/S-mode device"}


def tmag_tlow(d, vdd, cs, tlow, scale=None, drive=("SD", "min")):
    """TWIM0 holds TMAG_SCL low for `tlow`; returns the low time at the TMAG5273 (0.3·VCC, Table 5.3 VIL)."""
    scl = d.node("TMAG_SCL")
    t0, e = 0.2e-6, EDGE[drive[0]]
    pwl = f"PWL(0 0 {t0:g} 0 {t0 + e:g} 1 {t0 + tlow:g} 1 {t0 + tlow + e:g} 0)"
    r = tmag_bus(d, vdd, cs, {"scl_nrf": pwl}, scale=scale, tstop=t0 + tlow + 0.8e-6, waves=(f"v({scl})",),
                 drive=drive)
    t, v = r["waves"]["time"], r["waves"][f"v({scl})"]
    return _cross(t, v, 0.3 * vdd, +1, start=t0 + tlow - 0.05e-6) - _cross(t, v, 0.3 * vdd, -1, start=t0 - 0.1e-6)


def twim_tlow_checks(main, base, check, sys_rate, tmag_rate, drive=("SD", "min"), fw=""):
    """SCL low time at every receiver of both buses: TWIM1 (system bus) at `sys_rate`, TWIM0 (TMAG) at
    `tmag_rate`. Stronger pull-up (R -1 %) and the weakest pull-down are worst: both slow the fall into VIL
    and speed the rise out of it. `fw` is appended to every check source (the firmware configuration under test)."""
    for cset in CSETS:
        for supply in ("vbat3.0", "hi"):
            vdd = VDD[supply]
            tag = f"{supply} {cset} nRF {'-'.join(drive)}"
            tl = tmag_tlow(main, vdd, CSETS[cset], TWIM[tmag_rate]["tlow"], scale={"R50": 1 - main.tol("R50")},
                           drive=drive)
            check(f"TMAG_SCL tLOW at TMAG5273, TWIM0 @{tmag_rate} [{tag}]", tl, T_LOW, None, "s",
                  f"{S_TMAG} Table 5.10 twlow 1300 ns (0.3·VCC, Table 5.3 VIL); {S_UM} Table 11 tLOW{fw}")
            sc = {"R53": 1 - main.tol("R53"), "R54": 1 - main.tol("R54")}
            out = i2c_transaction(main, base, vdd, CSETS[cset], scale=sc, rate=sys_rate, drive=drive)
            for name, m in out.items():
                check(f"I2C_SCL tLOW at {name}, TWIM1 @{sys_rate} [{tag}]", m["tlow"], T_LOW, None, "s",
                      TLOW_SRC[name] + fw)


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE (firmware-dependent, NF-1 I2C): nRF52840 errata 219, the TWIM at 400 kHz drives SCL low for only "
    "1.25 us; the bus tLOW is 1.26 us at the TMAG5273, 1.22-1.23 us at the LIS2DW12 and 1.27-1.28 us at the "
    "BQ25180, below 1.3 us (UM10204 Table 11, LIS2DW12 Table 7, TMAG5273 Table 5.10). The OLD docs/firmware.md set "
    "I2C_BITRATE_FAST on i2c0 and i2c1 with no workaround; it now writes TWIM0 FREQUENCY = 0x06200000 and runs "
    "TWIM1 at 250 kHz, guarded by test_twim_tlow_errata219_remedy"))
def test_twim_tlow_400k_errata219(main, base, check):
    """OLD firmware configuration: both TWIMs at 400 kHz (I2C_BITRATE_FAST), default S0D1 pins (weakest corner)."""
    twim_tlow_checks(main, base, check, "400k", "400k", fw="; OLD firmware: I2C_BITRATE_FAST on i2c0 and i2c1")


SRC_FW_NF1 = ("; firmware rule (hardware/sim, NF-1 I2C, nRF52840 errata 219): docs/firmware.md 1.3 / 3.1 / 4.4 - "
              "TWIM0 FREQUENCY = 0x06200000 written after init, TWIM1 clock-frequency 250000 (K250, 0x04000000), "
              "TWIM pins keep the default S0D1 drive")


def test_twim_tlow_errata219_remedy(main, base, check):
    """GUARD for the firmware rule NF-1 I2C (hardware/sim; nRF52840 errata 219; docs/firmware.md 1.3 TWIM pin
    table, 3.1 &i2c0 / &i2c1, 4.4 TWIM0 register table): TWIM0 (TMAG) at the errata 219 workaround
    FREQUENCY = 0x06200000 (390 kHz, SCL low > 1.3 us), TWIM1 (system bus) at 250 kHz (K250, 0x04000000), S0D1
    pins unchanged (the weakest S0D1 corner). 390 kHz is not enough on TWIM1: the weakest S0D1 pin needs 20-30 ns
    to pull the 45-72 pF harness line to the LIS2DW12's 0.2·Vdd_IO point, leaving 1.27-1.29 us there. H0D1 would
    fix that but puts the BQ25180 undershoot at the -0.3 V abs max (test_system_bus_fast_edges note).
    firmware.md also allows TWIM1 at I2C_BITRATE_STANDARD (100 kHz); that case is not simulated: no document gives
    the TWIM SCL low phase at 100 kHz (the 250 kHz one is already inferred, TWIM table)."""
    twim_tlow_checks(main, base, check, "250k", "390k", fw=SRC_FW_NF1)


SYS_DRIVERS = {  # driver -> (control key, node key, sink ammeter, max sink)
    "nRF S0D1 SDA": ("sda_nrf", "I2C_SDA", None, None),
    "nRF S0D1 SCL": ("scl_nrf", "I2C_SCL", None, None),
    "LIS2DW12 SDA": ("sda_lis", "I2C_SDA", "vam_lsda", (LIS_IOL_MAX, f"{S_LIS} Table 4 note 5")),
    "BQ25180 SDA": ("sda_bq", "I2C_SDA", "vam_bsda", (BQ_IOL_MAX, f"{S_BQ} §7.5 VOL condition")),
}


@pytest.mark.parametrize("ignd", list(I_GND))
@pytest.mark.parametrize("supply", SUPPLY_IDS)
def test_system_bus_vol(main, base, check, supply, ignd):
    """Each open-drain driver alone against the strongest pull-up (R -1 %), read at every receiver relative
    to its own ground (the base ground sits I*R_GND below the main ground)."""
    vdd, vofs = VDD[supply], I_GND[ignd] * R_GND
    sc = {"R53": 1 - main.tol("R53"), "R54": 1 - main.tol("R54")}
    for drv, (ck, net, am, imax) in SYS_DRIVERS.items():
        mnode, bnd = main.node(net), bnode(base.node(net))
        prints = [f"v({mnode})", f"v({bnd})-v({GB})"] + ([f"i({am})"] if am else [])
        r, _, _ = sys_bus(main, base, vdd, CSETS["nom"], {ck: "DC 1"}, scale=sc, vofs=vofs, op=True, prints=prints)
        v_main, v_base = r["op_0"], r["op_1"]
        tag = f"{drv} {supply} Ignd={ignd}"
        v_drv = v_base if drv.startswith("BQ") else v_main
        check(f"I2C VOL at driver [{tag}]", v_drv, None, VOL_I2C, "V", f"{S_UM} Table 10 VOL1")
        if not drv.startswith("nRF"):
            check(f"I2C low at nRF [{tag}]", v_main, None, 0.3 * vdd, "V", f"{S_NRF} VIL 0.3·VDD")
        if not drv.startswith("LIS"):
            check(f"I2C low at LIS2DW12 [{tag}]", v_main, None, 0.2 * vdd, "V", f"{S_LIS} Table 4 VIL 0.2·VDD_IO")
        if not drv.startswith("BQ"):
            check(f"I2C low at BQ25180 [{tag}]", v_base, None, BQ_VIL, "V", f"{S_BQ} §7.5 VIL 0.4 V")
        if am:
            check(f"{drv} sink current [{tag}]", abs(r["op_2"]), None, imax[0], "A", imax[1])


@pytest.mark.parametrize("supply", ["vbat3.0", "hi"])
def test_system_bus_idle_high(main, base, check, supply):
    """Released bus: the high level at every receiver with the BQ25180 ILKG (1 uA) on both lines."""
    vdd = VDD[supply]
    sc = {"R53": 1 + main.tol("R53"), "R54": 1 + main.tol("R54")}
    for net in ("I2C_SCL", "I2C_SDA"):
        mnode, bnd = main.node(net), bnode(base.node(net))
        r, _, _ = sys_bus(main, base, vdd, CSETS["worst"], {}, scale=sc, op=True,
                          prints=(f"v({mnode})", f"v({bnd})-v({GB})"))
        check(f"{net} idle high at LIS2DW12 [{supply}]", r["op_0"], 0.8 * vdd, None, "V", f"{S_LIS} Table 4 VIH 0.8·VDD_IO")
        check(f"{net} idle high at BQ25180 [{supply}]", r["op_1"], BQ_VIH, None, "V", f"{S_BQ} §7.5 VIH 1.3 V")


@pytest.mark.fault
def test_fault_i2c_sda_pullup_1k(main, base, check):
    """Fault: R54 = 1k (someone 'speeds up' the bus). The nRF S0D1 pin (1 mA min at 0.4 V) can then no
    longer pull SDA below the BQ25180 VIL."""
    main.override("R54", "1k")
    sda, bsda = main.node("I2C_SDA"), bnode(base.node("I2C_SDA"))
    r, _, _ = sys_bus(main, base, VDD["hi"], CSETS["nom"], {"sda_nrf": "DC 1"}, vofs=I_GND["hw_worst"] * R_GND,
                      op=True, prints=(f"v({sda})", f"v({bsda})-v({GB})"))
    check("FAULT R54=1k: SDA low at BQ25180 above VIL", r["op_1"], BQ_VIL, None, "V", f"fault must violate {S_BQ} VIL")


# ------------------------------------------------------------------------------------------------ CHG_INT_N
def test_chg_int_pullup_in_range(main, check):
    check("R55 CHG_INT_N pull-up", main.value("R55"), 1e3, 20e3, "Ω", f"{S_BQ} Table 6-1 /INT pull-up 1–20 kΩ")


@pytest.mark.parametrize("supply", ["vbat3.0", "lo", "hi"])
def test_chg_int_pulse(main, base, check, supply):
    """BQ25180 /INT 128 us pulse across the harness; idle high with ILKG 1 uA."""
    vdd = VDD[supply]
    t0 = 2e-6
    for k, sc in enumerate(main.extremes(["R55"])):
        mnode = main.node("CHG_INT_N")
        pulse = f"PULSE(0 1 {t0:g} 13n 13n {T_INT_BQ:g} 1)"
        # base-side driver read on main: a ground offset only helps (base GND sits below main GND),
        # so the worst case is no offset
        r, _, _ = sys_bus(main, base, vdd, CSETS["worst"], {"int_bq": pulse}, scale=sc,
                          vofs=I_GND["idle"], tstop=t0 + T_INT_BQ + 20e-6,
                          waves=(f"v({mnode})", "i(vam_bint)"))
        w = r["waves"]
        t, v = w["time"], w[f"v({mnode})"]
        vol = float(np.max(v[(t > t0 + 2e-6) & (t < t0 + T_INT_BQ)]))
        tag = f"{supply} R55-corner {k}"
        check(f"CHG_INT_N low at nRF during /INT pulse [{tag}]", vol, None, 0.3 * vdd, "V", f"{S_NRF} VIL 0.3·VDD")
        i_int = np.abs(w["i(vam_bint)"])[(t > t0 + 2e-6) & (t < t0 + T_INT_BQ)]
        check(f"BQ25180 /INT steady sink current [{tag}]", float(np.max(i_int)), None, BQ_IOL_MAX, "A",
              f"{S_BQ} §7.5 /INT VOL condition 5 mA")
        rop, _, _ = sys_bus(main, base, vdd, CSETS["worst"], {}, scale=sc, op=True, prints=(f"v({mnode})",))
        check(f"CHG_INT_N idle high with ILKG [{tag}]", rop["op_0"], 0.7 * vdd, None, "V",
              f"{S_NRF} VIH 0.7·VDD ({S_BQ} ILKG 1 µA)")


@pytest.mark.fault
def test_fault_chg_int_pullup_missing(main, base, check):
    main.remove("R55")
    mnode = main.node("CHG_INT_N")
    r, _, _ = sys_bus(main, base, VDD["nom"], CSETS["nom"], {}, op=True, prints=(f"v({mnode})",))
    check("FAULT R55 left off: CHG_INT_N idle below VIH", r["op_0"], None, 0.7 * VDD["nom"], "V",
          f"fault must violate {S_NRF} VIH")


# ------------------------------------------------------------------------------------------------ BTN_N
BTN_VDD = {3.0: VDD["vbat3.0"], 3.7: VDD["lo"], 4.2: VDD["lo"]}


@pytest.mark.parametrize("temp", [-10, 25, 60])
@pytest.mark.parametrize("vbat", [3.0, 3.7, 4.2])
def test_btn_n_levels(main, base, check, vbat, temp):
    """Press: SW1 puts VBAT on both BSS138DW gates (R3 1k / R4 1M), Q1B pulls BTN_N low across the
    harness. Release: R56 must hold BTN_N above VIH against Q1B IDSS at temperature."""
    vdd = BTN_VDD[vbat]
    mnode = main.node("BTN_N")
    for k, sc in enumerate(main.extremes(["R56"])):
        tag = f"VBAT {vbat} V {temp}°C R56-corner {k}"
        r, _, _ = sys_bus(main, base, vdd, CSETS["nom"], {"sw1": "DC 1"}, scale=sc, vofs=I_GND["idle"],
                          vbat=vbat, temp=temp, op=True, prints=(f"v({mnode})",))   # no offset = worst
        check(f"BTN_N pressed, low at nRF [{tag}]", r["op_0"], None, 0.3 * vdd, "V", f"{S_NRF} VIL 0.3·VDD")
        r, _, _ = sys_bus(main, base, vdd, CSETS["nom"], {}, scale=sc, vbat=vbat, temp=temp, op=True,
                          prints=(f"v({mnode})",))
        check(f"BTN_N released, high at nRF [{tag}]", r["op_0"], 0.7 * vdd, None, "V",
              f"{S_NRF} VIH 0.7·VDD (BSS138DW DS30203 IDSS 0.5 µA, ×2/10 °C)")


@pytest.mark.fault
def test_fault_btn_pullup_1meg(main, base, check):
    """Fault: R56 fitted as 1M. Q1B leakage at 60 C must pull BTN_N below VIH."""
    main.override("R56", "1M")
    mnode = main.node("BTN_N")
    r, _, _ = sys_bus(main, base, VDD["lo"], CSETS["nom"], {}, vbat=4.2, temp=60, op=True, prints=(f"v({mnode})",))
    check("FAULT R56=1M: BTN_N released level below VIH at 60 °C", r["op_0"], None, 0.7 * VDD["lo"], "V",
          f"fault must violate {S_NRF} VIH")


@pytest.mark.fault
def test_fault_btn_gate_pulldown_missing(main, base, check):
    """Fault (base board): R4, the 1 Mohm SW_GATE pull-down, left off. After a press the BSS138DW gates keep
    their charge (only IGSS and the open switch remain), so Q1B holds BTN_N low: the dial reads as pressed
    forever (and Q1A holds TS/MR low). In the DC solution the open SW1 (ROFF 1e12) is the gate's only path,
    to VBAT, which is that post-press state. The released-level check must flag it."""
    base.remove("R4")
    mnode = main.node("BTN_N")
    r, _, _ = sys_bus(main, base, VDD["lo"], CSETS["nom"], {}, vbat=3.7, temp=25, op=True, prints=(f"v({mnode})",))
    check("FAULT R4 left off: BTN_N released level below VIH", r["op_0"], None, 0.7 * VDD["lo"], "V",
          f"fault must violate {S_NRF} VIH 0.7·VDD")


# ------------------------------------------------------------------------------------------------ IMU INT
@pytest.mark.parametrize("supply", ["vbat3.0", "hi"])
def test_imu_int_push_pull(main, check, supply):
    """LIS2DW12 INT1/INT2 are push-pull (CTRL3.PP_OD = 0 default) straight into nRF inputs, no pull resistor."""
    vdd = VDD[supply]
    v3 = main.node("+3V3")
    for net, pin, gpin in (("IMU_INT1", "INT1", "P1.12"), ("IMU_INT2", "INT2", "P0.30")):
        node = main.node(net)
        assert main.pin("U31", pin) == node and main.pin("U10", gpin) == node
        check(f"{net} has no pull resistor", len(main.on_net(net, "R")), 0, 0, "",
              f"{S_LIS} Table 12: push-pull default; Table 34 CTRL3.PP_OD = 0 (firmware keeps it)")
        for level in (0, 1):
            deck = Deck(f"{net} level {level}")
            deck.include(LIB["nrf52840_gpio"]).include(LIB["lis2dw12"])
            deck += f"V3V3 {v3} 0 DC {vdd:.5g}"
            deck += main.passives(nets={"+3V3", net})
            deck += f"VC_IN c_in 0 DC {level}"
            deck += f"XL {node} {v3} 0 c_in LIS2DW12_PP vg={vdd:.5g}"
            deck += gpio_in("N", node, v3, vdd, 3e-12)
            deck.op()
            deck.print_op(f"v({node})")
            v = run(deck)["op_0"]
            if level:
                check(f"{net} high at nRF [{supply}]", v, 0.7 * vdd, None, "V", f"{S_NRF} VIH 0.7·VDD")
            else:
                check(f"{net} low at nRF [{supply}]", v, None, 0.3 * vdd, "V", f"{S_NRF} VIL 0.3·VDD")
