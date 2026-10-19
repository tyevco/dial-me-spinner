"""RT9080-33 3V3 LDO (U1 on main_power, VSYS -> +3V3): start-up, dropout, load and line transients,
output-capacitor stability, quiescent current, thermal, and fault injection.

Circuit key "ldo_3v3". IC model: models/ldo_3v3__rt9080.lib (Richtek DS9080-09, Dec 2024). Everything on +3V3
and VSYS comes from the main netlist (U1 is found by MPN, its pins by pin name, the output capacitors and pull-ups
by net), so a schematic change shows up in the next run. MLCC DC-bias, temperature and ESR data come from the
Samsung Electro-Mechanics component library, keyed by the MPN field of each capacitor (MLCC table below); a
capacitor whose MPN is not in the table fails the run instead of being silently guessed.

Load currents are datasheet figures of the +3V3 consumers (nRF52840 PS v1.1, W25Q128JV Rev F, TMAG5273 SLYS045C,
SSD1351 / NHD panel spec, DRV8837 SLVSBA4F, DRV5032 ti.com/lit/ds/symlink/drv5032.pdf) and the architecture.md
section 8.2 sleep budget. VSYS is applied at the main-board link connector: the harness drop belongs to the link
harness tests (it is ~mV at the +3V3 load currents used here).

Independent verification (second pass) changed: U1's VIN/EN connections now come from the netlist (an EN or VIN
miswire shows up in every simulation, not only in the topology assert); the U1 pinout is checked against DS section 7;
the Monte Carlo batch no longer couples its copies through shared ESR nodes (capacitors whose +3V3 pin is pin 2 had
an un-suffixed '0_cNN_esr' node); start-up uses voltage-dependent MLCC capacitance (the 0 V capacitance is ~2x the
3.3 V value, so the fixed-C deck under-stated the inrush: 0.71 -> 0.94 A); COUT minimum is the DS 17.1 / Fig. 1
1 uF effective (stricter than the 0.7 uF of section 8); tolerances come from the MPN letter everywhere; TJ uses the
JEDEC theta-JA; reverse bias (VOUT > VIN) on VSYS collapse is checked against the DS abs max.
"""

from __future__ import annotations

import itertools
import math
import random
import re

import numpy as np
import pytest

import spicelib

LIB = "ldo_3v3__rt9080.lib"
DS = "RT9080 DS9080-09"

# --------------------------------------------------------------------------------------------- limits
W25Q_VMIN = 2.7          # W25Q128JV Rev F 9.2: VCC 2.7-3.0 V allowed at FR <= 104 MHz (nRF QSPI <= 32 MHz)
VCI_MAX = 3.5            # SSD1351 VCI 2.4-3.5 V (NHD panel spec, display research); tighter than the 3.6 V parts
NRF_TR_VDD_MAX = 60e-3   # nRF52840 PS recommended operating conditions: tR_VDD (0 -> 1.7 V) <= 60 ms
TMAG_RAMP_MIN = 3.0e3    # TMAG5273 SLYS045C: VCC ramp >= 3 V/ms, else firmware must run one W&S cycle after POR
WS_VIH_K = 0.6           # WS2812C-2020-V6 VIH = 0.6 x VDD (Worldsemi PCN 30 Sep 2025; 0.55 x VDD in DS V1.0)
NRF_VOH_DROP = 0.4       # nRF52840 PS: VOH >= VDD - 0.4 V (standard drive)
COUT_MIN_STAB = 1.0e-6   # DS9080-09 17.1 "minimum output capacitance ... 1 uF, considering the temperature and voltage
#                          coefficient" and Fig. 1 "COUT (Effective Capacitance >= 1 uF)"; section 8 says 0.7 uF
#                          effective - the stricter DS statement is used
ESR_MIN = 1e-3           # DS9080-09 section 18: output capacitor ESR >= 1 mohm
TJ_MAX = 125.0           # DS9080-09 section 12: recommended junction temperature range -40..125 C
THETA_JA = 189.4         # DS9080-09 section 13: theta-JA (JEDEC) TSOT-23-5. The 100.7 C/W theta-JA(EVB) needs Richtek's
#                          high-conductivity 70x50 mm board; the main board is a crowded 64 mm disc, so use JEDEC
VIN_MAX = 5.5            # DS9080-09 section 12: recommended input voltage 1.2-5.5 V
REV_MAX = 0.3            # DS9080-09 section 10 absolute maximum: VOUT to VIN -6.5 .. +0.3 V
PINOUT = {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"}   # DS9080-09 sections 7/8, TSOT-23-5
SYS_OVP_K = 1.05         # BQ25180 SLUSE99C 8.3.6: SYS_OVP rising threshold ~105 % of the SYS target
RON_BAT = 0.055          # BQ25180 SLUSE99C 7.5 RON_BAT 55 mohm typ (BATFET, battery -> SYS)
VBSUP1 = 0.04            # BQ25180 SLUSE99C 7.5 VBSUP1: SYS supplemented from BAT below VBAT - 40 mV
BATOCP_SET = 1.5         # BQ25180 IBAT_OCP after firmware init (CHARGECTRL1 0x92 = 1.5 A, firmware.md 13.1)
RON_LSW = 0.08           # TPS22917 RON 80 mohm typ (power research / TPS22917 DS) - U2 in a VLED short
SPEC_IQ_MAX = 2e-6       # SPEC.md section 3: "LDO ... Iq <= 2 uA"
BATOCP_DEFAULT = 1.0     # BQ25180 SLUSE99C 7.5 IBAT_OCP code 01 = 1 A (POR default per power research; firmware
#                          later writes 1.5 A, so start-up happens at 1 A)
BQ_ILIM_500_MAX = 0.498  # BQ25180 SLUSE99C 7.5 ILIM 500 mA code: 498 mA max (TMR_ILIM 0xCD, firmware.md)
SYS_REG = 4.5            # BQ25180 SYS_REG = 4.5 V on USB (architecture 6.5 / firmware register table)
SYS_REG_ACC = 0.02       # BQ25180 SLUSE99C 7.5 VSYS_REG accuracy +/-2 %
VBUVLO = 3.0             # BQ25180 BUVLO setting 3.0 V (CHARGECTRL1 0x92): lowest VSYS on battery
SAG = 0.3                # power research design rule: total system peak keeps the cell sag below 0.3 V

# battery and USB corners for VSYS as the charger delivers it: VBAT 3.0 / 3.7 / 4.2 V (SYS = VBAT on battery);
# on USB SYS is regulated to 4.5 V +/-2 % (VBUS 5.0 / 5.5 V); at VBUS 4.5 V SYS = VBUS - IIN*RON_IN (<= 4.5 V),
# which lies inside the same 4.41-4.59 V window.
VSYS_BATT = [3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 4.2]
VSYS_USB = [round(SYS_REG * (1 - SYS_REG_ACC), 3), SYS_REG, round(SYS_REG * (1 + SYS_REG_ACC), 3)]
VSYS_USB_MAX = VSYS_USB[-1]
TEMPS = [-10, 25, 60]

# --------------------------------------------------------------------------------------------- RT9080 corners
# DS9080-09 Table 14: accuracy +/-2 %, dropout 0.31 typ / 0.53 V max at 600 mA, load regulation 0.5 / 1 %,
# line regulation 0.13 / 0.35 %, IQ 2 / 4 uA, ILIM 1.1 typ (0.98 A for the 3.3 V option in Fig. "Current Limit vs
# Temperature") / 0.61 A min; fold-back ~0.72 A (Fig.), scaled with ILIM for the min corner.
TYP = dict(ACC=0, RDSK=1, LREG=0.005, LINE=0.0013, IQ="2u", ILIM=0.98, IFB=0.72)
LOW = dict(ACC=-0.02, RDSK=round(0.53 / 0.31, 4), LREG=0.01, LINE=-0.0035, IQ="4u", ILIM=0.61,
           IFB=round(0.72 * 0.61 / 0.98, 4))
HIGH = dict(ACC=0.02, RDSK=1, LREG=0.01, LINE=0.0035, IQ="4u", ILIM=0.98, IFB=0.72)

# --------------------------------------------------------------------------------------------- +3V3 loads (A)
SLEEP = 22.2e-6   # architecture.md 8.2 sleep column, +3V3 consumers: nRF 3.0, TMAG 3.0, IMU 1.5, DRV5032 1.6,
#                   2x DRV8837 0.1, OLED 12, flash 1.0 uA
TX = 14.8e-3 + 3.3e-3   # nRF52840 PS v1.1: ITX,PLUS8dBM,DCDC 14.8 mA + ICPU0 (64 MHz from flash) 3.3 mA
ACTIVE_MIN = 3.3e-3     # lowest +3V3 load while the system is awake: nRF52840 PS ICPU0 3.3 mA (CPU only)
DIM_VSYS = 7.7e-3 + 2e-3   # VSYS-side load in the dimmest awake state at low battery: OLED + 13 V boost 7.7 mA
#                            (architecture.md 8.2 "Fidget dim") + the <= 2 mA red low-battery LED cue (firmware.md LED
#                            derating, VBAT < 3.53 V: all other LEDs off)
OTHERS = {        # added on top of TX for the peak step
    "W25Q128 page program": 25e-3,   # W25Q128JV Rev F 9.4 ICC5 max
    "TMAG5273 active": 3.0e-3,       # TMAG5273 SLYS045C active LP_LN=1, typ
    "LIS2DW12 HP": 0.09e-3,          # LIS2DW12 high-performance mode (~90 uA, sensing research)
    "SSD1351 VCI": 0.3e-3,           # NHD panel spec ICI max 300 uA
    "2x DRV8837 VCC": 3.0e-3,        # DRV883x SLVSBA4F IVCC awake, 1.5 mA max each
    "DRV5032 sample": 2.7e-3,        # DRV5032 ICC peak during sampling, max
}

# --------------------------------------------------------------------------------------------- MLCC data
# Samsung SEM component library (weblib.samsungsem.com mlcc-ec-data-sheet, read 2026-10): DC-bias curve (% change vs V,
# 25 C), TCC (% vs 25 C, no bias) and ESR (ohm) vs frequency (0 V bias, 25 C). Keyed by MPN without the packaging
# letter. Tolerance comes from the MPN tolerance letter (K = 10 %, M = 20 %).
MLCC = {
    "CL10A106KP8NNN": dict(dcb=[(0, 0), (1, -10.9), (2, -33.0), (2.5, -42.5), (3.0, -51.2), (3.3, -55.7), (3.6, -59.5),
                                (4.0, -63.5), (4.5, -68.0), (5.0, -71.7)],
                           tcc={-10: 1.9, 25: 0, 60: -7.7},
                           esr={1e4: 51.4e-3, 3e4: 19.9e-3, 1e5: 8.09e-3, 3e5: 4.34e-3, 1e6: 3.17e-3}),
    "CL05B104KO5NNN": dict(dcb=[(0, 0), (1, 0.2), (2, -0.8), (2.5, -1.8), (3.0, -3.1), (3.3, -3.9), (3.6, -4.8),
                                (4.0, -6.1), (4.5, -7.8), (5.0, -9.5)],
                           tcc={-10: -1.3, 25: 0, 60: -2.7},
                           esr={1e4: 3.25, 3e4: 1.115, 1e5: 0.341, 3e5: 0.126, 1e6: 51.5e-3}),
    "CL05A105KA5NQN": dict(dcb=[(0, 0), (1, -5.6), (2, -21.4), (2.5, -29.7), (3.0, -37.9), (3.3, -42.4), (3.6, -46.5),
                                (4.0, -51.2), (4.5, -56.4), (5.0, -60.9)],
                           tcc={-10: 0.2, 25: 0, 60: -4.8},
                           esr={1e4: 0.401, 3e4: 0.135, 1e5: 47.7e-3, 3e5: 19.9e-3, 1e6: 10.6e-3}),
    "CL21A475KAQNNN": dict(dcb=[(0, 0), (1, -0.1), (2, -5.0), (2.5, -8.9), (3.0, -13.4), (3.3, -16.1), (3.6, -19.0),
                                (4.0, -22.8), (4.5, -27.4), (5.0, -31.8)],
                           tcc={-10: -4.9, 25: 0, 60: -2.8},
                           esr={1e4: 99.7e-3, 3e4: 37.2e-3, 1e5: 14.0e-3, 3e5: 6.96e-3, 1e6: 4.81e-3}),
    "CL21A226MAQNNN": dict(dcb=[(0, 0), (1, -1.1), (2, -13.5), (2.5, -20.7), (3.0, -28.1), (3.3, -32.3), (3.6, -36.2),
                                (4.0, -41.0), (4.5, -46.5), (5.0, -51.3)],
                           tcc={-10: -4.0, 25: 0, 60: -3.5},
                           esr={1e4: 22.2e-3, 3e4: 9.29e-3, 1e5: 4.34e-3, 3e5: 2.84e-3, 1e6: 3.0e-3}),
    "CL21A106KAYNNN": dict(dcb=[(0, 0), (1, -2.7), (2, -12.7), (2.5, -19.3), (3.0, -26.4), (3.3, -30.5), (3.6, -34.5),
                                (4.0, -39.5), (4.5, -45.2), (5.0, -50.3)],
                           tcc={-10: -0.7, 25: 0, 60: -7.2},
                           esr={1e4: 37.8e-3, 3e4: 14.4e-3, 1e5: 6.41e-3, 3e5: 3.57e-3, 1e6: 2.97e-3}),
    "CL10A106MA8NRN": dict(dcb=[(0, 0), (1, -3.6), (2, -15.5), (2.5, -22.6), (3.0, -29.9), (3.3, -34.0), (3.6, -37.9),
                                (4.0, -42.6), (4.5, -48.1), (5.0, -52.8)],
                           tcc={-10: -3.6, 25: 0, 60: -5.5},
                           esr={1e4: 39.1e-3, 3e4: 14.7e-3, 1e5: 5.85e-3, 3e5: 3.21e-3, 1e6: 2.6e-3}),
}
ESR_F = 1e5   # ESR used in the time-domain decks: 100 kHz, the band of the LDO response


def mlcc(d, ref):
    mpn = d.mpn(ref)
    for key, data in MLCC.items():
        if mpn.upper().startswith(key):
            return data
    raise KeyError(f"{d.board} {ref}: no DC-bias/ESR data for MPN {mpn!r}; add it to MLCC in test_ldo_3v3.py")


def cap_tol(d, ref):
    mpn = d.mpn(ref)
    if mpn.upper().startswith("CL") and len(mpn) >= 9:   # Samsung: CL + size + dielectric + 3-digit value + tol
        return {"J": 0.05, "K": 0.10, "M": 0.20}[mpn[8].upper()]
    return d.tol(ref)


def cap_factor(d, ref, vbias, temp, tol_sign=0.0):
    """Effective / nominal capacitance: DC bias at vbias, TCC at temp, tolerance at tol_sign (-1..+1)."""
    data = mlcc(d, ref)
    vs, ps = zip(*data["dcb"])
    dcb = float(np.interp(vbias, vs, ps)) / 100
    ts = sorted(data["tcc"])
    tcc = float(np.interp(temp, ts, [data["tcc"][t] for t in ts])) / 100
    return (1 + dcb) * (1 + tcc) * (1 + tol_sign * cap_tol(d, ref))


def cap_esr(d, ref, f=ESR_F):
    fs = sorted(mlcc(d, ref)["esr"])
    return float(np.interp(math.log10(f), [math.log10(x) for x in fs], [mlcc(d, ref)["esr"][x] for x in fs]))


def cap_corners(d, refs):
    """All 2^n tolerance corners as signs (-1/+1) - applied with cap_tol (MPN letter), not the value-string default."""
    refs = list(refs)
    for signs in itertools.product((-1, 1), repeat=len(refs)):
        yield dict(zip(refs, signs))


def cap_draws(d, refs, n, seed):
    """n uniform tolerance draws as signs in [-1, 1] (scaled by cap_tol when used)."""
    rng = random.Random(seed)
    for _ in range(n):
        yield {r: rng.uniform(-1, 1) for r in refs}


# --------------------------------------------------------------------------------------------- netlist access
def ldo_ref(d):
    refs = d.find("RT9080")
    assert len(refs) == 1, f"expected one RT9080 on {d.board}, found {refs}"
    return refs[0]


def ldo_vnom(d):
    """Output option from the part value (fault injection can override it): RT9080-33GJ5 -> 3.3 V, -2H -> 2.85 V."""
    u = ldo_ref(d)
    value = d._override.get(u, d.comps[u]["value"])
    m = re.search(r"RT9080N?-(\d)([0-9H])", value.upper())
    assert m, f"cannot read the RT9080 output option from {value!r}"
    return float(m.group(1)) + (0.85 if m.group(2) == "H" else int(m.group(2)) / 10)


def nets(d):
    f = d.funcs[ldo_ref(d)]
    return f["VIN"], f["EN"], f["VOUT"], f["GND"]


def en_node(d, vsys_node):
    """U1's EN node from the netlist. The decks drive the VSYS net, so VIN must sit on it; EN tied to VIN follows VSYS,
    EN on GND is simulated as off; anything else has no driver model here and fails loudly."""
    u = ldo_ref(d)
    vin, en, _, gnd = nets(d)
    assert vin == "VSYS" and gnd == "GND", f"{u}: VIN on {vin!r}, GND on {gnd!r} - the decks drive VSYS"
    if en == vin:
        return vsys_node
    if en == gnd:
        return "0"
    raise AssertionError(f"{u}: EN on {en!r}, which these decks do not drive")


def pin_functions(d, ref):
    """{pin number: pin function} of a part as the netlist has it (unconnected pins included)."""
    return {p: f for lst in d.nets.values() for r, p, f in lst if r == ref}


def rewire(d, ref, func, net):
    """Fault injection: move one pin (by function) of a part to another net. spicelib.Design has no API for a wrong
    connection, so this edits the parsed netlist of this Design instance only."""
    pin = next(p for p, f in pin_functions(d, ref).items() if f == func)
    old = d.pins[ref][pin]
    d.nets[old] = [e for e in d.nets[old] if not (e[0] == ref and e[1] == pin)]
    d.nets.setdefault(net, []).append((ref, pin, func))
    d.pins[ref][pin] = net
    d.funcs[ref][func] = net
    return d


def out_caps(d):
    vout = nets(d)[2]
    return [r for r in d.on_net(vout, "C") if d.fitted(r) and set(d.pins[r].values()) == {vout, "GND"}]


def local_out_caps(d):
    """Output capacitors on the LDO's own sheet: the ones placed at U1 (DS: 'place COUT close to the device')."""
    sheet = d.comps[ldo_ref(d)]["props"].get("Sheetname")
    return [r for r in out_caps(d) if d.comps[r]["props"].get("Sheetname") == sheet]


def pullup_load(d):
    """Worst case (line held low) current of every fitted pull-up from +3V3 to a signal net."""
    vout = nets(d)[2]
    total = 0.0
    for r in d.on_net(vout, "R"):
        others = set(d.pins[r].values()) - {vout}
        if d.fitted(r) and others and "GND" not in others:
            total += ldo_vnom(d) / d.value(r)
    return total


def peak_load(d):
    return TX + sum(OTHERS.values()) + pullup_load(d)


def caps_to_gnd(d, net):
    return [r for r in d.on_net(net, "C") if d.fitted(r) and set(d.pins[r].values()) == {net, "GND"}]


# --------------------------------------------------------------------------------------------- deck building
def params(corner, temp, vnom, slow=1):
    p = dict(corner, VNOM=vnom, TEMPC=temp, SLOW=slow)
    return " ".join(f"{k}={v}" for k, v in p.items())


def ldo_lines(d, vsys_node, corner=TYP, temp=25, slow=1, cap_sign=None, suffix="", vdep=False):
    """U1 with its +3V3 capacitors (DC-bias / TCC / tolerance derated, ESR at 100 kHz) behind a 0 V sense source.

    VIN must be on VSYS (driven by the deck); EN follows its netlist net (see en_node).
    cap_sign: {ref: -1..+1} tolerance position per capacitor (default 0 = nominal), scaled by the MPN tolerance.
    suffix: makes node and element names unique so several copies fit in one deck (Monte Carlo batches). Every node
        except ground gets it: passives() puts the ESR mid-node on the GND side for capacitors whose +3V3 pin is
        pin 2 ('0_c33_esr'), and those must not be shared between copies.
    vdep: voltage-dependent capacitance C(V) from the Samsung DC-bias curve (for large swings: start-up, collapse);
        otherwise the capacitance is fixed at its DC-bias value at VNOM (small-signal decks).
    """
    vnom = ldo_vnom(d)
    _, _, vout, _ = nets(d)
    n_out = d.node(vout)
    n_en = en_node(d, vsys_node)
    caps = out_caps(d)
    scale = {r: cap_factor(d, r, 0.0 if vdep else vnom, temp, (cap_sign or {}).get(r, 0.0)) for r in caps}
    esr = {r: cap_esr(d, r) for r in caps}
    lines = [f"VSENSE{suffix} {vsys_node} n_u1vin{suffix} 0",
             f"XU1{suffix} n_u1vin{suffix} {n_en} {n_out}{suffix} 0 LDO3V3_RT9080 params: "
             + params(corner, temp, vnom, slow)]
    for ln in d.passives(nets={vout, "GND"}, scale=scale, esr=esr):
        tok = ln.split()
        name = tok[0]
        tok[0] += suffix
        tok[1:3] = [t if t == "0" else t + suffix for t in tok[1:3]]
        if vdep and name.startswith("C") and name[1:] in scale:
            pts = ", ".join(f"{v:g},{1 + p / 100:.4f}" for v, p in mlcc(d, name[1:])["dcb"])
            tok[3] = f"C='{tok[3]}*pwl(abs(v({tok[1]},{tok[2]})), {pts})'"
        lines.append(" ".join(tok))
    return lines, n_out + suffix


def check_clean(res, exc=AssertionError):
    """ngspice ran without unrecovered errors (gmin-stepping retries that end in 'completed' are fine).
    xfail tests pass exc=RuntimeError so that a simulator failure cannot masquerade as the expected check failure."""
    log = res["_log"]
    errs = [e for e in res["_errors"] if not ("gmin stepping failed" in e.lower() and "stepping completed" in log)]
    if errs or res.get("_missing"):
        raise exc(f"ngspice errors {errs[:5]}, missing measures {res.get('_missing')}")


def pwl(points):
    return "PWL(" + " ".join(f"{t:.9g} {v:.9g}" for t, v in points) + ")"


# ============================================================================================= tests
def test_netlist_topology(main, check):
    """U1 is an RT9080 fed from VSYS with EN tied to VIN, output on +3V3 (SPEC 3, main_power sheet); the symbol's pin
    numbers match the DS TSOT-23-5 pinout (the simulations use pin names, so a symbol pin-number error would otherwise
    pass every other test); VSYS stays inside the DS input range even at the charger's SYS over-voltage threshold."""
    u = ldo_ref(main)
    vin, en, vout, gnd = nets(main)
    assert (vin, en, vout, gnd) == ("VSYS", "VSYS", "+3V3", "GND"), (u, vin, en, vout, gnd)
    assert pin_functions(main, u) == PINOUT, f"{u} pinout {pin_functions(main, u)} != DS9080-09 section 7 {PINOUT}"
    assert "SOT-23-5" in main.comps[u]["fields"].get("Footprint", ""), main.comps[u]["fields"].get("Footprint")
    assert ldo_vnom(main) == pytest.approx(3.3)
    assert out_caps(main), "no output capacitors on +3V3"
    for r in out_caps(main) + caps_to_gnd(main, "VSYS"):
        mlcc(main, r)   # every capacitor has derating data
    check("VSYS max (SYS_OVP rising, SYS_REG +2 %) vs U1 VIN range", SYS_OVP_K * VSYS_USB_MAX, None, VIN_MAX, "V",
          f"{DS} section 12 VIN 1.2-5.5 V; BQ25180 SLUSE99C 8.3.6 SYS_OVP ~105 % of target, 7.5 VSYS_REG +/-2 %")


def test_model_matches_datasheet_figures(check):
    """The behavioural model reproduces the DS9080-09 conditions it was fitted to (no design data involved)."""
    # Load transient (Fig. "Load Transient": RT9080-08, VIN 1.8 V, 1 mA -> 600 mA, ~20 us edges, 1 uF):
    # DS shows ~27 mV undershoot and ~23 mV overshoot. The model must not be more optimistic than the figure.
    # The bench runs at VIN 2.0 V: at 1.8 V the Table 14 dropout of the 0.8 V option (1.05 V typ at 600 mA) would
    # already bind in the model, although the figure shows the part regulating.
    deck = spicelib.Deck("RT9080 DS load transient")
    deck.include(LIB)
    deck += ["VIN vin 0 2.0", "XU vin vin out 0 LDO3V3_RT9080 params: VNOM=0.8", "C1 out 0 1u", "RL out 0 800",
             "IL out 0 " + pwl([(0, 0), (300e-6, 0), (320e-6, 0.599), (700e-6, 0.599), (720e-6, 0)])]
    deck.tran("0.1u", "1.1m", extra="0.2u")
    deck.meas("tran v0 FIND v(out) AT=290u")
    deck.meas("tran vlo MIN v(out) FROM=300u TO=600u")
    deck.meas("tran vset FIND v(out) AT=690u")
    deck.meas("tran vhi MAX v(out) FROM=700u TO=1.0m")
    deck.meas("tran ripple PP v(out) FROM=1.0m TO=1.09m")
    r = deck.run()
    check_clean(r)
    check("DS load step 1 mA->600 mA undershoot (model >= DS Fig.)", r["v0"] - r["vlo"], 27e-3, 3 * 27e-3, "V",
          f"{DS} Fig. Load Transient ~27 mV (fit: model may be up to 3x pessimistic)")
    check("DS load step 600 mA->1 mA overshoot (model >= DS Fig.)", r["vhi"] - r["vset"], 0.9 * 23e-3, 3 * 23e-3, "V",
          f"{DS} Fig. Load Transient ~23 mV")
    check("DS load regulation 1->600 mA, % of VOUT", (r["v0"] - r["vset"]) / 0.8 * 100, 0, 1.0, "%",
          f"{DS} Table 14 load regulation 0.5 typ / 1 % max")
    check("DS bench settles (no sustained ringing)", r["ripple"], 0, 1e-3, "V", f"{DS} section 17.1: stable with >=1 uF")

    # PSRR at 1 kHz (Table 14: VIN 3 V, VOUT 2.5 V, 50 mA, COUT 1 uF: 75 dB typ)
    deck = spicelib.Deck("RT9080 DS PSRR")
    deck.include(LIB)
    deck += ["VIN vin 0 DC 3.0 AC 1", "XU vin vin out 0 LDO3V3_RT9080 params: VNOM=2.5", "C1 out 0 1u", "RL out 0 50"]
    deck.ac("dec", 10, 100, 1e6)
    deck.meas("ac psrr1k FIND vdb(out) AT=1000")
    r = deck.run()
    check_clean(r)
    check("DS PSRR @ 1 kHz", -r["psrr1k"], 72, 78, "dB", f"{DS} Table 14 PSRR 75 dB typ (fit +/-3 dB)")

    # Dropout at 600 mA (Table 14, VOUT >= 3 V: 0.31 V typ, 0.53 V max; defined at VOUT = 98 % of nominal)
    for name, corner, lo, hi in (("typ", TYP, 0.28, 0.34), ("max corner", LOW, 0.45, 0.53)):
        deck = spicelib.Deck("RT9080 DS dropout")
        deck.include(LIB)
        c = dict(corner, ACC=0, LINE=0, ILIM=0.98, IFB=0.72)   # dropout spec only: typ current limit
        deck += ["VIN vin 0 4", f"XU vin vin out 0 LDO3V3_RT9080 params: {params(c, 25, 3.3)}", "IL out 0 0.6"]
        deck.dc("VIN", 3.0, 4.2, 0.002)
        deck.meas(f"dc vdrop WHEN v(out)={0.98 * 3.3} RISE=1")
        r = deck.run()
        check_clean(r)
        check(f"DS dropout @600 mA, 25 C ({name})", r["vdrop"] - 0.98 * 3.3, lo, hi, "V",
              f"{DS} Table 14 VDROP 0.31 typ / 0.53 V max (3 V <= VOUT)")

    # Power-on from EN (Fig. "Power On from EN": VIN 4 V, VOUT 3.3 V, 600 mA): ~92 % at ~195 us
    deck = spicelib.Deck("RT9080 DS power on")
    deck.include(LIB)
    deck += ["VIN vin 0 4", "VEN en 0 " + pwl([(0, 0), (50e-6, 0), (51e-6, 4)]),
             "XU vin en out 0 LDO3V3_RT9080 params: VNOM=3.3", "C1 out 0 1u", "RL out 0 5.5"]
    deck.tran("0.5u", "1.5m", extra="1u")
    deck.meas(f"tran t92 WHEN v(out)={0.92 * 3.3} RISE=1")
    r = deck.run()
    check_clean(r)
    check("DS soft start, EN -> 92 % VOUT", r["t92"] - 51e-6, 0.5 * 195e-6, 2 * 195e-6, "s",
          f"{DS} Fig. Power On from EN (~195 us to 92 %, read from the plot)")


def test_spec_section3_ldo_requirements(main, check):
    """SPEC 3: 'LDO >= 200 mA, Iq <= 2 uA, dropout <= 300 mV at 200 mA ... Input 10 uF, output 10 uF + 100 nF'.
    Dropout with the DS max-dropout part at 60 C; capacitors from the netlist (nominal, and effective at the input
    against the DS 1 uF input recommendation)."""
    deck = spicelib.Deck("LDO SPEC dropout 200 mA")
    deck.include(LIB)
    c = dict(LOW, ACC=0, LINE=0, ILIM=0.98, IFB=0.72)
    deck += ["VIN vin 0 4", f"XU vin vin out 0 LDO3V3_RT9080 params: {params(c, 60, ldo_vnom(main))}", "IL out 0 0.2"]
    deck.dc("VIN", 3.0, 4.2, 0.002)
    deck.meas(f"dc vdrop WHEN v(out)={0.98 * ldo_vnom(main)} RISE=1")
    r = deck.run()
    check_clean(r)
    check("dropout @200 mA, DS max part, 60 C", r["vdrop"] - 0.98 * ldo_vnom(main), None, 0.300, "V",
          "SPEC.md 3: dropout <= 300 mV at 200 mA")
    check("current limit, DS min", LOW["ILIM"], 0.200, None, "A", f"SPEC.md 3: >= 200 mA ({DS} Table 14 ILIM >= 610 mA)")
    loc = local_out_caps(main)
    check(f"output capacitance at U1, nominal ({'+'.join(loc)})", sum(main.value(r) for r in loc), 10.1e-6 * 0.999, None, "F",
          "SPEC.md 3: output 10 uF + 100 nF")
    sheet = main.comps[ldo_ref(main)]["props"].get("Sheetname")
    vin_loc = [r for r in caps_to_gnd(main, nets(main)[0]) if main.comps[r]["props"].get("Sheetname") == sheet]
    c_in = min(sum(main.value(r) * cap_factor(main, r, VSYS_USB_MAX, t, -1) for r in vin_loc) for t in (-10, 60))
    check(f"VSYS capacitance on U1's sheet ({'+'.join(vin_loc)}), effective at {VSYS_USB_MAX} V, -tol", c_in, 1e-6,
          None, "F", f"{DS} section 18: input capacitor >= 1 uF close to VIN (SPEC 3: 10 uF)")


def test_nominal_regulation(main, check):
    """VBAT 3.7 V, 25 C, typical part, nRF TX burst load: +3V3 within the +/-2 % accuracy band."""
    vnom = ldo_vnom(main)
    deck = spicelib.Deck("LDO nominal")
    deck.include(LIB)
    deck += "VSYS n_vsys 0 3.7"
    lines, n_out = ldo_lines(main, "n_vsys")
    deck += lines
    deck += f"ILOAD {n_out} 0 {TX}"
    deck.op()
    deck.print_op(f"v({n_out})", "i(VSENSE)")
    r = deck.run()
    check_clean(r)
    check("+3V3 at VBAT 3.7 V, 25 C, TX load", r["op_0"], vnom * 0.98, vnom * 1.02, "V", f"{DS} Table 14 accuracy +/-2 %")
    check("LDO input current = load + GND current", r["op_1"], TX, TX * 1.02, "A",
          f"{DS} Fig. Ground Current vs Load Current (~150 uA at 18 mA)")


@pytest.mark.parametrize("temp", TEMPS)
def test_dc_supply_and_temperature_corners(main, check, temp):
    """+3V3 over every VSYS the charger can deliver (VBAT 3.0-4.2 V, USB 4.41-4.59 V), at -10/25/60 C.

    Worst-low corner (-2 %, max dropout, max load/line regulation, peak load) against the consumers' minimums:
    W25Q128JV 2.7 V and the WS2812C data-high requirement VDD >= 0.6*VSYS + 0.4 V (nRF VOH = VDD - 0.4 V).
    Worst-high corner (+2 %, sleep load) against the SSD1351 VCI maximum 3.5 V.
    """
    i_peak = peak_load(main)
    res = {}
    for tag, corner, load in (("lo", LOW, i_peak), ("hi", HIGH, SLEEP)):
        deck = spicelib.Deck(f"LDO DC corners {tag} {temp} C")
        deck.include(LIB)
        deck += "VSYS n_vsys 0 3.7"
        lines, n_out = ldo_lines(main, "n_vsys", corner=corner, temp=temp)
        deck += lines
        deck += f"ILOAD {n_out} 0 {load}"
        deck.dc("VSYS", 2.9, 4.65, 0.005)
        for k, v in enumerate(VSYS_BATT + VSYS_USB):
            deck.meas(f"dc v{tag}{k} FIND v({n_out}) AT={v}")
        r = deck.run()
        check_clean(r)
        res[tag] = r
    for k, v in enumerate(VSYS_BATT + VSYS_USB):
        need = max(W25Q_VMIN, WS_VIH_K * v + NRF_VOH_DROP)
        check(f"+3V3 min @ VSYS {v} V, {temp} C, peak load {i_peak * 1e3:.1f} mA", res["lo"][f"vlo{k}"], need, None, "V",
              "W25Q128JV Rev F 9.2 VCC >= 2.7 V; WS2812C-V6 VIH 0.6*VDD (PCN) + nRF52840 PS VOH = VDD-0.4 V")
        check(f"+3V3 max @ VSYS {v} V, {temp} C, sleep load", res["hi"][f"vhi{k}"], None, VCI_MAX, "V",
              "SSD1351 VCI <= 3.5 V (NHD spec); nRF/W25Q/TMAG/LIS2DW12 <= 3.6 V")


def _startup_run(d, ramp, vfinal, corner, temp, cap_sign, label):
    vnom = ldo_vnom(d)
    t0 = 10e-6
    tstop = t0 + ramp + 2e-3
    deck = spicelib.Deck(f"LDO start-up {label}")
    deck.include(LIB)
    deck += "VSYS n_vsys 0 " + pwl([(0, 0), (t0, 0), (t0 + ramp, vfinal)])
    lines, n_out = ldo_lines(d, "n_vsys", corner=corner, temp=temp, vdep=True,
                             cap_sign={r: cap_sign for r in out_caps(d)})
    deck += lines
    deck += f"RLOAD {n_out} 0 {vnom / peak_load(d):.6g}"   # consumers as a resistor at their peak current
    deck.tran(f"{max(ramp / 2000, 0.2e-6):.3g}", f"{tstop:.6g}", extra=f"{max(ramp / 500, 1e-6):.3g}")
    deck.meas(f"tran t17 WHEN v({n_out})=1.7 RISE=1")
    vtop = min(vnom, vfinal - 0.1)
    deck.meas(f"tran t10 WHEN v({n_out})={0.1 * vtop} RISE=1")
    deck.meas(f"tran t90 WHEN v({n_out})={0.9 * vtop} RISE=1")
    deck.meas(f"tran vmax MAX v({n_out})")
    deck.meas(f"tran vend FIND v({n_out}) AT={tstop * 0.999:.6g}")
    deck.meas("tran iinpk MAX i(VSENSE)")
    r = deck.run()
    check_clean(r)
    return r, t0, vtop


@pytest.mark.parametrize("ramp,vfinal,label", [
    (10e-6, 4.2, "battery hot-plug"),
    (10e-6, VSYS_USB_MAX, "USB, fast SYS"),
    (1e-3, VSYS_USB_MAX, "USB, 1 ms SYS ramp"),
    (20e-3, VBUVLO, "slow ramp to BUVLO"),
])
def test_startup_vsys_ramp(main, check, ramp, vfinal, label):
    """Power-up with EN = VIN = VSYS ramping from 0 V. MLCCs use their voltage-dependent capacitance (C(0 V) is about
    twice C(3.3 V)), so the soft start is current-limit controlled. Three corners, each worst for its check:
    inrush = typ ILIM (the DS gives no max) with every capacitor at +tol / -10 C; rise time and ramp rate = DS min ILIM
    and max dropout part with +tol / -10 C; overshoot and final value = +2 % part with -tol / 60 C."""
    rin, t0, _ = _startup_run(main, ramp, vfinal, HIGH, -10, +1, f"{label} inrush")
    rtm, _, vtop = _startup_run(main, ramp, vfinal, LOW, -10, +1, f"{label} timing")
    rov, _, _ = _startup_run(main, ramp, vfinal, HIGH, 60, -1, f"{label} overshoot")
    check(f"[{label}] tR_VDD (0 -> 1.7 V), DS min ILIM, max C", rtm["t17"] - t0, 0, NRF_TR_VDD_MAX, "s",
          "nRF52840 PS recommended operating conditions tR_VDD <= 60 ms")
    check(f"[{label}] +3V3 peak during start-up", rov["vmax"], None, VCI_MAX, "V", "SSD1351 VCI <= 3.5 V (NHD spec)")
    check(f"[{label}] +3V3 after start-up", min(rov["vend"], rtm["vend"]), W25Q_VMIN, None, "V", "W25Q128JV 9.2 >= 2.7 V")
    check(f"[{label}] +3V3 after start-up (max)", max(rov["vend"], rin["vend"]), None, VCI_MAX, "V",
          "SSD1351 VCI <= 3.5 V (NHD spec)")
    check(f"[{label}] LDO input current peak (current-limit controlled, typ ILIM, C(V) at +tol)", rin["iinpk"], None,
          BATOCP_DEFAULT, "A", "BQ25180 SLUSE99C IBAT_OCP 1 A (POR value, before firmware sets 1.5 A); "
          f"{DS} Table 14 gives ILIM >= 0.61 A and no max")
    if ramp <= 1e-3:   # rail rise set by the LDO soft start / current limit (or a >= 3 V/ms SYS ramp)
        check(f"[{label}] +3V3 ramp rate 10-90 %, DS min ILIM, max C", 0.8 * vtop / (rtm["t90"] - rtm["t10"]),
              TMAG_RAMP_MIN, None, "V/s", "TMAG5273 SLYS045C VCC ramp >= 3 V/ms")


def _load_step_deck(d, vsys, temp, corner, slow=1, title="load step"):
    i_peak = peak_load(d)
    deck = spicelib.Deck(f"LDO {title}")
    deck.include(LIB)
    deck += f"VSYS n_vsys 0 {vsys}"
    lines, n_out = ldo_lines(d, "n_vsys", corner=corner, temp=temp, slow=slow)
    deck += lines
    # sleep -> nRF TX burst (1 us edge) -> + flash program and every other consumer (peak) -> back to sleep
    deck += f"ISLEEP {n_out} 0 {SLEEP}"
    deck += f"ITX {n_out} 0 " + pwl([(0, 0), (200e-6, 0), (201e-6, TX - SLEEP), (1.7e-3, TX - SLEEP), (1.701e-3, 0)])
    deck += f"IPK {n_out} 0 " + pwl([(0, 0), (700e-6, 0), (701e-6, i_peak - TX), (1.7e-3, i_peak - TX),
                                     (1.701e-3, 0)])
    deck.tran("0.2u", "3m", extra="1u")
    deck.meas(f"tran vpre FIND v({n_out}) AT=190u")
    deck.meas(f"tran vmin MIN v({n_out}) FROM=200u TO=1.7m")
    deck.meas(f"tran vmax MAX v({n_out}) FROM=1.7m TO=3m")
    return deck


@pytest.mark.parametrize("vsys", [VBUVLO, 3.7, VSYS_USB_MAX])
@pytest.mark.parametrize("temp", [-10, 60])
def test_load_steps(main, check, vsys, temp):
    """Sleep -> nRF TX burst -> TX + flash program + all consumers -> sleep, 1 us edges, at each supply corner."""
    lo = _load_step_deck(main, vsys, temp, LOW).run()
    check_clean(lo)
    hi = _load_step_deck(main, vsys, temp, HIGH).run()
    check_clean(hi)
    need = max(W25Q_VMIN, WS_VIH_K * vsys + NRF_VOH_DROP)
    check(f"+3V3 min during TX / flash steps, VSYS {vsys} V, {temp} C", lo["vmin"], need, None, "V",
          "W25Q128JV 9.2 VCC >= 2.7 V; WS2812C-V6 VIH 0.6*VDD + nRF VOH = VDD-0.4 V")
    check(f"+3V3 max after peak -> sleep release, VSYS {vsys} V, {temp} C", hi["vmax"], None, VCI_MAX, "V",
          "SSD1351 VCI <= 3.5 V (NHD spec)")


def test_load_steps_slow_loop_sensitivity(main, check):
    """The DS characterises the loop only from a 1 mA start; from the ~22 uA sleep load the adaptive bias makes it slower.
    Re-run the worst cases with the loop 3x slower than the (already 2.4x pessimistic) fit."""
    for vsys, temp, tag in ((VBUVLO, 60, "BUVLO, 60 C"), (VSYS_USB_MAX, -10, "USB max, -10 C")):
        lo = _load_step_deck(main, vsys, temp, LOW, slow=3, title="load step slow").run()
        check_clean(lo)
        hi = _load_step_deck(main, vsys, temp, HIGH, slow=3, title="load step slow").run()
        check_clean(hi)
        need = max(W25Q_VMIN, WS_VIH_K * vsys + NRF_VOH_DROP)
        check(f"+3V3 min, loop 3x slower, {tag}", lo["vmin"], need, None, "V",
              "W25Q128JV 9.2 VCC >= 2.7 V; WS2812C-V6 VIH 0.6*VDD + nRF VOH = VDD-0.4 V")
        check(f"+3V3 max, loop 3x slower, {tag}", hi["vmax"], None, VCI_MAX, "V", "SSD1351 VCI <= 3.5 V (NHD spec)")


def _vsys_slew_usb(main, base):
    """Fastest SYS rise on USB plug-in: BQ25180 ILIM (500 mA code, 498 mA max) into the smallest VSYS capacitance
    of both boards (DC bias at 4.5 V, -tolerance, 60 C), ignoring every load (all of which slow it down)."""
    c = 0.0
    for d in (main, base):
        for r in caps_to_gnd(d, "VSYS"):
            c += d.value(r) * cap_factor(d, r, SYS_REG, 60, -1)
    return BQ_ILIM_500_MAX / c, c


@pytest.mark.parametrize("case", ["led sag 3.7", "led sag 3.4", "usb plug fast", "usb plug ilim", "usb unplug"])
def test_line_transients(main, base, check, case):
    """VSYS steps: LED/motor sag (0.3 V, 1 us edge), USB plug-in (VBAT 3.0 V -> SYS_REG max) and unplug."""
    slew, c_vsys = _vsys_slew_usb(main, base)
    if case.startswith("led sag"):
        v0 = float(case.split()[-1])
        v1, edge = v0 - SAG, 1e-6
    elif case == "usb plug fast":
        v0, v1, edge = VBUVLO, VSYS_USB_MAX, 10e-6
    elif case == "usb plug ilim":
        v0, v1 = VBUVLO, VSYS_USB_MAX
        edge = (v1 - v0) / slew
    else:
        v0, v1, edge = VSYS_USB_MAX, VBUVLO, 10e-6
    t1, t2 = 200e-6, 1.5e-3
    wave = pwl([(0, v0), (t1, v0), (t1 + edge, v1), (t2, v1), (t2 + edge, v0)])
    out = {}
    for tag, corner, load in (("lo", LOW, peak_load(main)), ("hi", HIGH, SLEEP)):
        for temp in (-10, 60):
            deck = spicelib.Deck(f"LDO line {case}")
            deck.include(LIB)
            deck += "VSYS n_vsys 0 " + wave
            lines, n_out = ldo_lines(main, "n_vsys", corner=corner, temp=temp)
            deck += lines
            deck += f"ILOAD {n_out} 0 {load}"
            deck.tran("0.2u", "3m", extra="1u")
            deck.meas(f"tran vmin MIN v({n_out}) FROM=150u TO=3m")
            deck.meas(f"tran vmax MAX v({n_out}) FROM=150u TO=3m")
            r = deck.run()
            check_clean(r)
            out[(tag, temp)] = r
    extra = f" (ILIM-limited {slew * 1e-3:.1f} V/ms into {c_vsys * 1e6:.1f} uF)" if case == "usb plug ilim" else ""
    check(f"[{case}] +3V3 min{extra}", min(out[("lo", t)]["vmin"] for t in (-10, 60)), W25Q_VMIN, None, "V",
          "W25Q128JV 9.2 VCC >= 2.7 V")
    check(f"[{case}] +3V3 max{extra}", max(out[("hi", t)]["vmax"] for t in (-10, 60)), None, VCI_MAX, "V",
          "SSD1351 VCI <= 3.5 V (NHD spec)")


def _local_ceff_min(d):
    """Smallest effective capacitance of the capacitors at U1 over their tolerance corners, -10/60 C, at VOUT +2 %."""
    loc = local_out_caps(d)
    vb = ldo_vnom(d) * 1.02
    worst = math.inf
    for corner in cap_corners(d, loc):
        for temp in (-10, 60):
            c = sum(d.value(r) * cap_factor(d, r, vb, temp, corner[r]) for r in loc)
            worst = min(worst, c)
    return worst, loc


def test_output_capacitor_stability(main, check):
    """DS9080-09 stability conditions with the real capacitors: >= 1 uF effective at U1 (DC bias, tolerance, TCC),
    and every output capacitor's ESR >= 1 mohm over the loop band (10 kHz - 1 MHz, Samsung data)."""
    c_loc, loc = _local_ceff_min(main)
    check(f"COUT effective at U1 ({'+'.join(loc)}), worst corner", c_loc, COUT_MIN_STAB, None, "F",
          f"{DS} 17.1 / Fig. 1: >= 1 uF effective incl. voltage and temperature coefficient (section 8: 0.7 uF)")
    # whole rail, Monte Carlo over all output capacitor tolerances (200 draws), both temperatures
    caps = out_caps(main)
    vb = ldo_vnom(main) * 1.02
    c_all = min(sum(main.value(r) * cap_factor(main, r, vb, t, mc[r]) for r in caps)
                for mc in cap_draws(main, caps, 200, seed=7) for t in (-10, 60))
    check(f"COUT effective on +3V3 ({len(caps)} caps), MC min", c_all, 1e-6, None, "F",
          f"{DS} Fig. 1 typical application: COUT effective capacitance >= 1 uF")
    for r in caps:
        esr_min = min(mlcc(main, r)["esr"].values())
        check(f"{r} ({main.mpn(r)}) ESR min over 10 kHz-1 MHz", esr_min, ESR_MIN, None, "ohm",
              f"{DS} section 18: output capacitor ESR >= 1 mohm")


@pytest.mark.slow
def test_load_step_monte_carlo(main, check):
    """200 draws: every +3V3 capacitor within its tolerance and the RT9080 anywhere inside its DS limits
    (accuracy, dropout, load/line regulation), TX + flash step at BUVLO / 60 C and at USB max / -10 C."""
    caps = out_caps(main)
    rng = np.random.default_rng(11)
    n, batch = 200, 50
    worst_lo = {VBUVLO: math.inf, VSYS_USB_MAX: math.inf}
    worst_hi = -math.inf
    for vsys, temp in ((VBUVLO, 60), (VSYS_USB_MAX, -10)):
        draws = list(cap_draws(main, caps, n, seed=5 if vsys == VBUVLO else 6))
        for b0 in range(0, n, batch):
            deck = spicelib.Deck("LDO MC load step")
            deck.include(LIB)
            deck += f"VSYS n_vsys 0 {vsys}"
            i_peak = peak_load(main)
            for k, mc in enumerate(draws[b0:b0 + batch]):
                corner = dict(ACC=round(rng.uniform(-0.02, 0.02), 5), RDSK=round(rng.uniform(1, 0.53 / 0.31), 4),
                              LREG=round(rng.uniform(0.005, 0.01), 5), LINE=round(rng.uniform(-0.0035, 0.0035), 6),
                              IQ="4u", ILIM=0.98, IFB=0.72)
                lines, n_out = ldo_lines(main, "n_vsys", corner=corner, temp=temp, cap_sign=mc, suffix=f"_k{k}")
                deck += lines
                deck += f"IS_k{k} {n_out} 0 {SLEEP}"
                deck += f"IL_k{k} {n_out} 0 " + pwl([(0, 0), (200e-6, 0), (201e-6, i_peak - SLEEP),
                                                     (1.2e-3, i_peak - SLEEP), (1.201e-3, 0)])
                deck.meas(f"tran mn{k} MIN v({n_out}) FROM=200u TO=1.2m")
                deck.meas(f"tran mx{k} MAX v({n_out}) FROM=1.2m TO=2m")
            deck.tran("0.5u", "2m", extra="2u")
            r = deck.run(timeout=600)
            check_clean(r)
            for k in range(len(draws[b0:b0 + batch])):
                worst_lo[vsys] = min(worst_lo[vsys], r[f"mn{k}"])
                worst_hi = max(worst_hi, r[f"mx{k}"])
    for vsys, v in worst_lo.items():
        check(f"MC +3V3 min, peak step, VSYS {vsys} V", v, max(W25Q_VMIN, WS_VIH_K * vsys + NRF_VOH_DROP), None, "V",
              "W25Q128JV 9.2 VCC >= 2.7 V; WS2812C-V6 VIH 0.6*VDD + nRF VOH = VDD-0.4 V")
    check("MC +3V3 max after release", worst_hi, None, VCI_MAX, "V", "SSD1351 VCI <= 3.5 V (NHD spec)")


def _iq_deck(d, corner):
    deck = spicelib.Deck("LDO Iq")
    deck.include(LIB)
    deck += "VSYS n_vsys 0 3.7"
    lines, n_out = ldo_lines(d, "n_vsys", corner=corner)
    deck += lines
    deck.op()
    deck.print_op("i(VSENSE)", f"v({n_out})")
    return deck


def test_quiescent_current_typical(main, check):
    """No load, VBAT 3.7 V: the LDO's own draw from VSYS (DS IQ, typical part) against SPEC 3."""
    r = _iq_deck(main, TYP).run()
    check_clean(r)
    check("LDO quiescent current, typ part, no load", r["op_0"], 0, SPEC_IQ_MAX * 1.001, "A",
          f"SPEC.md 3 LDO Iq <= 2 uA ({DS} Table 14 IQ 2 uA typ)")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DESIGN ISSUE: SPEC 3 asks for LDO Iq <= 2 uA, but DS9080-09 Table 14 guarantees "
                                       "only 4 uA max (2 uA is typical); a max part breaks the SPEC sleep budget")
def test_quiescent_current_max_vs_spec(main, check):
    r = _iq_deck(main, LOW).run()
    check_clean(r, exc=RuntimeError)   # a simulator failure must not pass as the expected check failure
    check("LDO quiescent current, DS max part, no load", r["op_0"], 0, SPEC_IQ_MAX * 1.001, "A",
          f"SPEC.md 3 LDO Iq <= 2 uA vs {DS} Table 14 IQ 4 uA max")


def _thermal(d, vsys, temp_amb, corner=TYP):
    deck = spicelib.Deck("LDO thermal")
    deck.include(LIB)
    deck += f"VSYS n_vsys 0 {vsys}"
    lines, n_out = ldo_lines(d, "n_vsys", corner=corner, temp=temp_amb)
    deck += lines
    deck += f"ILOAD {n_out} 0 {peak_load(d)}"
    deck.op()
    deck.print_op("i(VSENSE)", f"v({n_out})")
    r = deck.run()
    check_clean(r)
    i_in = r["op_0"]
    v_out = max(r["op_1"], 0.0)
    i_out = i_in if v_out < 0.1 else peak_load(d)   # a shorted output takes the whole input current
    p = vsys * i_in - v_out * i_out
    return temp_amb + THETA_JA * p, p, r


def test_thermal(main, check):
    """Worst dissipation: USB SYS_REG max, every consumer at peak, 60 C ambient."""
    tj, p, _ = _thermal(main, VSYS_USB_MAX, 60)
    check(f"RT9080 TJ at {p * 1e3:.0f} mW, TA 60 C", tj, None, TJ_MAX, "C",
          f"{DS} section 12 TJ <= 125 C, theta-JA (JEDEC) 189.4 C/W (section 13)")


# --------------------------------------------------------------------------------------------- reverse bias
def _reverse_run(main, base, case):
    """VSYS falls faster than +3V3 can follow: U1 sees VOUT > VIN and the +3V3 capacitors discharge into VSYS through
    the PMOS body diode. +3V3: +2 % part at 60 C (highest rail), every capacitor at +tol with C(V) (most hold-up),
    lowest awake load. VSYS: both boards' VSYS capacitors at -tol, DC bias at the starting voltage, 60 C (fastest fall).
    """
    v0 = SYS_REG if case == "usb unplug" else 3.7
    c_vsys = sum(dd.value(r) * cap_factor(dd, r, v0, 60, -1) for dd in (main, base) for r in caps_to_gnd(dd, "VSYS"))
    # The rail powers up from 0 V first (ngspice cannot start 16 voltage-dependent capacitors from a 3.3 V operating
    # point: 'timestep too small' at the first step), the event happens at t_ev once everything has settled.
    t_ev = 1e-3
    up = f"PWL(0 0 10u {v0})"
    deck = spicelib.Deck(f"LDO reverse bias {case}")
    deck.include(LIB)
    deck += [".model SWREV SW(VT=0.5 VH=0.01 RON=1m ROFF=1G)",
             f"VOPEN nopen 0 PWL(0 1 {t_ev} 1 {t_ev + 0.1e-6} 0)",
             f"CVSYS n_vsys 0 {c_vsys:.6g}"]
    if case == "usb unplug":
        # USB path opens; the BATFET supplements SYS (ideal diode) once SYS < VBAT - VBSUP1, VBAT at BUVLO
        deck += [f"VUSB nusb 0 {up}", "SUSB nusb n_vsys nopen 0 SWREV",
                 # BATFET in supplement mode: conducts through RON_BAT once SYS < VBAT - VBSUP1 (smooth ideal diode)
                 f"BSUP 0 n_vsys I=0.5*(({VBUVLO - VBSUP1}-v(n_vsys)) + sqrt(({VBUVLO - VBSUP1}-v(n_vsys))**2 + 1e-8))"
                 f"/{RON_BAT}", f"IVS n_vsys 0 {DIM_VSYS}"]
        tstop = t_ev + 8e-3
    elif case == "batocp trip":
        # a VSYS overload at the BATOCP setting (e.g. a shorted motor lead) switched on at t_ev: the BATFET opens
        deck += [f"VBAT nbat 0 {up}", f"RBAT nbat nbf {RON_BAT}", "SBAT nbf n_vsys nopen 0 SWREV",
                 f"RVS n_vsys nvs {3.7 / BATOCP_SET:.6g}", "SVS nvs 0 nsc 0 SWREV",
                 f"VSC nsc 0 PWL(0 0 {t_ev - 1e-6} 0 {t_ev - 0.9e-6} 1)"]
        tstop = t_ev + 1e-3
    else:
        # a WS2812C shorted VDD-GND behind U2 (RON) at t_ev; BATOCP opens the BATFET 10 us later
        deck += [f"VBAT nbat 0 {up}", f"RBAT nbat nbf {RON_BAT}", "SBAT nbf n_vsys nbt 0 SWREV",
                 f"VBT nbt 0 PWL(0 1 {t_ev + 10e-6} 1 {t_ev + 10.1e-6} 0)",
                 "SSH n_vsys nsh nsc 0 SWREV", f"VSC nsc 0 PWL(0 0 {t_ev} 0 {t_ev + 0.1e-6} 1)", f"RSH nsh 0 {RON_LSW}"]
        tstop = t_ev + 1e-3
    lines, n_out = ldo_lines(main, "n_vsys", corner=HIGH, temp=60, vdep=True, cap_sign={r: 1 for r in out_caps(main)})
    deck += lines
    deck += [f"ILOAD {n_out} 0 {ACTIVE_MIN}", f"BDIF ndif 0 V=v({n_out})-v(n_vsys)"]
    deck.tran("0.1u", f"{tstop:.6g}", extra="1u")
    deck.meas(f"tran vpre FIND v({n_out}) AT={t_ev - 2e-6}")
    deck.meas(f"tran vrev MAX v(ndif) FROM={t_ev - 2e-6} TO={tstop:.6g}")
    deck.meas(f"tran irev MIN i(VSENSE) FROM={t_ev - 2e-6} TO={tstop:.6g}")
    r = deck.run()
    check_clean(r, exc=RuntimeError)   # a simulator failure must not pass as an expected (xfail) check failure
    if not r["vpre"] > 3.3:
        raise RuntimeError(f"+3V3 not settled before the event: {r['vpre']}")
    return r


def test_reverse_bias_usb_unplug_at_buvlo(main, base, check):
    """Normal operation, worst case: USB unplugged while charging a flat cell (VBAT at BUVLO), display awake. VSYS
    drops from SYS_REG to VBAT - VBSUP1 while +3V3 is held up by its capacitors; the firmware LED derating
    (VBAT < 3.53 V: LEDs off) keeps the VSYS-side load small enough that U1 stays inside its abs max."""
    r = _reverse_run(main, base, "usb unplug")
    check(f"[USB unplug, VBAT = BUVLO, dim awake] U1 VOUT - VIN max (reverse I {-min(r['irev'], 0) * 1e3:.1f} mA)",
          r["vrev"], None, REV_MAX, "V", f"{DS} section 10 abs max VOUT - VIN <= 0.3 V")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DESIGN ISSUE: any VSYS collapse with VSYS-side load (shorted LED behind U2, "
                                       "BATOCP trip on a VSYS overload) drives U1 to VOUT - VIN ~0.9-1.2 V, above the "
                                       "DS9080-09 0.3 V abs max; ~19 uF of +3V3 dumps 0.2-1.4 A through the PMOS body "
                                       "diode (no reverse-current path besides it)")
@pytest.mark.parametrize("case", ["batocp trip", "led short"])
def test_reverse_bias_on_vsys_collapse(main, base, check, case):
    """Fault conditions: VSYS is pulled down by a VSYS-side fault while the charger disconnects the battery."""
    r = _reverse_run(main, base, case)
    check(f"[{case}] U1 VOUT - VIN max (reverse I {-min(r['irev'], 0):.2f} A)", r["vrev"], None, REV_MAX, "V",
          f"{DS} section 10 abs max VOUT - VIN <= 0.3 V")


# ============================================================================================= fault injection
@pytest.mark.fault
def test_fault_output_cap_left_off(main, check):
    """C3 (the 10 uF at U1) not fitted: the remaining 100 nF at U1 is below the DS stability minimum."""
    loc = local_out_caps(main)
    assert "C3" in loc
    main.remove("C3")
    c_loc, _ = _local_ceff_min(main)
    with pytest.raises(AssertionError):
        check("FAULT C3 left off: COUT effective at U1 (must fail)", c_loc, COUT_MIN_STAB, None, "F",
              f"{DS} 17.1 / Fig. 1: >= 1 uF effective")


@pytest.mark.fault
def test_fault_output_cap_wrong_value(main, check):
    """C3 entered as 1 uF instead of 10 uF: the 0603 X5R loses ~56 % at 3.3 V, so U1 sees < 1 uF effective."""
    main.override("C3", "1u")
    c_loc, _ = _local_ceff_min(main)
    with pytest.raises(AssertionError):
        check("FAULT C3 = 1u: COUT effective at U1 (must fail)", c_loc, COUT_MIN_STAB, None, "F",
              f"{DS} 17.1 / Fig. 1: >= 1 uF effective")


@pytest.mark.fault
def test_fault_wrong_ldo_variant(main, check):
    """RT9080-28GJ5 (2.8 V option) fitted instead of -33: flash still runs, but on USB the nRF can no longer drive the
    WS2812C data-high (VOH = VDD - 0.4 V < 0.6 x VSYS) - the DC corner check must catch it."""
    main.override(ldo_ref(main), "RT9080-28GJ5")
    assert ldo_vnom(main) == pytest.approx(2.8)
    deck = spicelib.Deck("LDO fault variant")
    deck.include(LIB)
    deck += f"VSYS n_vsys 0 {VSYS_USB_MAX}"
    lines, n_out = ldo_lines(main, "n_vsys", corner=LOW, temp=25)
    deck += lines
    deck += f"ILOAD {n_out} 0 {peak_load(main)}"
    deck.op()
    deck.print_op(f"v({n_out})")
    r = deck.run()
    check_clean(r)
    with pytest.raises(AssertionError):
        check(f"FAULT RT9080-28: +3V3 min @ VSYS {VSYS_USB_MAX} V (must fail)", r["op_0"],
              max(W25Q_VMIN, WS_VIH_K * VSYS_USB_MAX + NRF_VOH_DROP), None, "V",
              "WS2812C-V6 VIH 0.6*VDD + nRF VOH = VDD-0.4 V")


@pytest.mark.fault
def test_fault_en_strapped_to_gnd(main, check):
    """EN tied to GND instead of VIN (wrong connection on the sheet): +3V3 never comes up. The decks take EN from the
    netlist, so the regulation check itself must catch it (not only the topology assert)."""
    rewire(main, ldo_ref(main), "EN", "GND")
    deck = spicelib.Deck("LDO fault EN on GND")
    deck.include(LIB)
    deck += "VSYS n_vsys 0 3.7"
    lines, n_out = ldo_lines(main, "n_vsys")
    deck += lines
    deck += f"ILOAD {n_out} 0 {TX}"
    deck.op()
    deck.print_op(f"v({n_out})")
    r = deck.run()
    check_clean(r)
    with pytest.raises(AssertionError):
        check("FAULT EN on GND: +3V3 at VBAT 3.7 V (must fail)", r["op_0"], W25Q_VMIN, None, "V",
              "W25Q128JV 9.2 VCC >= 2.7 V")


@pytest.mark.fault
def test_fault_symbol_pinout_swapped(main, check):
    """Symbol with the VIN and VOUT pad numbers swapped (VIN on pad 5): every net looks right by pin NAME, so only the
    DS pinout check in test_netlist_topology can catch it."""
    u = ldo_ref(main)
    swap = {"1": "5", "5": "1"}
    for net, lst in main.nets.items():
        main.nets[net] = [(r, swap.get(p, p) if r == u else p, f) for r, p, f in lst]
    main.pins[u]["1"], main.pins[u]["5"] = main.pins[u]["5"], main.pins[u]["1"]
    assert nets(main) == ("VSYS", "VSYS", "+3V3", "GND")   # by name nothing changed
    with pytest.raises(AssertionError, match="pinout"):
        test_netlist_topology(main, check)


@pytest.mark.fault
def test_fault_output_short(main, check):
    """C4 bridged (solder short on the 0402 at U1): the rail collapses and U1 sits in fold-back current limit at
    VSYS x ~0.7 A, far above what the package can dissipate - both the rail and the thermal check must catch it."""
    main.short("C4")
    tj, p, r = _thermal(main, VSYS_USB_MAX, 25)
    with pytest.raises(AssertionError):
        check("FAULT +3V3 shorted: TJ (must fail)", tj, None, TJ_MAX, "C", f"{DS} section 12 TJ <= 125 C")
    with pytest.raises(AssertionError):
        check("FAULT +3V3 shorted: +3V3 (must fail)", r["op_1"], W25Q_VMIN, None, "V", "W25Q128JV 9.2 VCC >= 2.7 V")
