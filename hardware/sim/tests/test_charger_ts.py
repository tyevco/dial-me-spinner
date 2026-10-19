"""charger_ts: BQ25180 TS/MR network on the base board, simulated from the KiCad netlists.

Circuit (hardware/design/sheets/base.py, netlist hardware/kicad/base):
  * U1 BQ25180 ball D1 TS/MR = net CHG_TSMR. The charger biases it with 38 uA (adapter present, always
    on) or 60 uA pulsed 4 ms / 196 ms (battery only, EN_PUSH = 1), compares it with the JEITA
    COLD/COOL/WARM/HOT thresholds and with the 90 mV push-button threshold.
  * RT1 Murata NCP15XH103F03RC 10 kOhm NTC to GND. It is the only NTC: the pack is a 2-wire PH lead, so
    the charger's temperature input is this board NTC.
  * SW1 press: VBAT -> R3 -> SW1 -> SW_GATE (R4 to GND) drives both halves of Q1 BSS138DW:
    Q1A pulls CHG_TSMR low (BQ25180 ship wake / WAKE1-2 / long-press reset), Q1B pulls BTN_N low.
  * BTN_N crosses the 12-way link (base J3 / main J1, same pin) to the main board, where R56 pulls it up
    to +3V3 (RT9080-33) and the nRF52840 module U10 reads it on P1.10 (SENSE wake, 5 ms gpio-keys debounce).

Every R/C value comes from the netlists (Design.passives / Design.value); RT1's R25 and B come from its
netlist value string ("10k B3435"). IC behaviour comes from models/charger_ts__*.lib; the comparator
thresholds and every limit below are datasheet / SPEC numbers, cited in each check().
"""

from __future__ import annotations

import math
import random
import re

import numpy as np
import pytest

import spicelib
from spicelib import Deck

# ----------------------------------------------------------------------------------------------- sources
BQ = "BQ25180 DS SLUSE99C (rev. Jan 2023)"
QDS = "BSS138DW DS DS30203 Rev.16-2"
NTC = "Murata NCP15XH103F03RC DS (08/2021)"
SWD = "XKB TS-1187A-X-X-X drawing rev A0"
NRF = "nRF52840 PS v1.6 §6.9.3.1 GPIO"
LDO = "RT9080 DS9080-09"
JEITA = "JEITA charge-prohibit limits 0 °C / 60 °C as adopted in docs/architecture.md §8.5 and firmware.md §13.1"

# ----------------------------------------------------------------------------------------------- BQ25180
ITS = {"min": 36.5e-6, "typ": 38e-6, "max": 39.5e-6}           # Table 7.5 ITS_BIAS = ITSMR (adapter present)
_ITS_BAT_TYP = 60e-6                                             # Table 7.5 ITSMR battery-only mode (typ only)
_ITS_REL = ITS["max"] / ITS["typ"] - 1                            # ASSUMPTION: same +-3.9 % spread as ITS_BIAS
ITS_BAT = {"min": _ITS_BAT_TYP * (1 - _ITS_REL), "typ": _ITS_BAT_TYP, "max": _ITS_BAT_TYP * (1 + _ITS_REL)}
VTSMR = 0.090                                                    # Table 7.5 VTSMR, button press detect (max)
# Table 7.5 BATTERY NTC MONITOR entry thresholds at VIN = 5 V: (min, typ, max, "Approx." degC, name)
THR = {
    "COLD00": (0.9575, 1.0075, 1.0575, 0.0, "VT1_Entry"),
    "COLD01": (0.8450, 0.8900, 0.9325, 3.0, "VT2_Entry"),
    "COOL": (0.6350, 0.6700, 0.7025, 10.0, "VT5_Entry"),
    "WARM": (0.1730, 0.1850, 0.1980, 45.0, "VT6_Entry"),
    "HOT00": (0.1050, 0.1150, 0.1250, 60.0, "VT7_Entry"),
    "HOT10": (0.1475, 0.1575, 0.1675, 50.0, "VT9_Entry"),
}
VWARM_EXIT_MAX = 0.235                                           # Table 7.5 VT6_Exit max (warm exit, ~41 C)
VTS_ENZ_MIN = 1.8                                                # Table 7.5 VTS_ENZ min (TS function enabled below)
VTS_CLAMP = {"min": 2.2, "typ": 2.8, "max": 3.3}                 # Table 7.5 VTS_CLAMP (open pin)
VPIN_MIN, VPIN_MAX = -0.3, 5.5                                   # Table 7.1 abs max, "all other pins"
T_TS_ON, T_TS_OFF = 4e-3, 196e-3                                 # Table 7.6 tTS_DUTY_ON / tTS_DUTY_OFF
T_DGL = 64e-6        # Table 7.6 tSLEEP_DGL (VIN falling): NOT a TS parameter; SLUSE99C gives no TS deglitch at all
# TS_CONTROL (0x0B, Table 8-20) settings under test: firmware.md §13.1 leaves the 0x00 default;
# 0x90 = TS_HOT 10 (50 C) + TS_COLD 01 (3 C) is the fix proposed by this test file.
TS_CONTROL = {"0x00": ("COLD00", "HOT00"), "0x90": ("COLD01", "HOT10")}
T_JEITA_MIN, T_JEITA_MAX = 0.0, 60.0

# ----------------------------------------------------------------------------------------------- BSS138DW
FET = {  # model corners (models/charger_ts__bss138dw.lib)
    "typ": dict(vth=1.2, beta=0.31, rs=1.0),     # VGS(th) typ, RDS(ON) typ 1.4 Ohm @ 10 V
    "weak": dict(vth=1.5, beta=0.124, rs=2.5),   # VGS(th) max 1.5 V + RDS(ON) max 3.5 Ohm @ 10 V
    "strong": dict(vth=0.5, beta=0.31, rs=1.0),  # VGS(th) min 0.5 V
}
VTH_MIN = 0.5            # DS EC table VGS(th) min (25 C)
TCV = -3.5e-3            # DS Fig. 4 VGS(th) tempco (1.85 V at -55 C .. 1.12 V at 150 C), as in the model
IDSS_MAX = 0.5e-6        # DS EC table IDSS max
VGSS_MAX = 20.0          # DS maximum ratings VGSS
# Capacitances. Fig. 10 (VGS = 0, 1 MHz), digitised: Ciss 33, Crss 3.3 pF at VDS = 10 V; Crss 22.3 pF at 0 V.
# EC table maxima at VDS = 10 V ("guaranteed by design"): Ciss 50, Coss 25, Crss 8 pF. The slow corner sets
# Cgs = Ciss - Crss, Cds = Coss - Crss, and scales the whole Crss(VDS) curve so that it meets 8 pF at 10 V.
FIG10 = {"ciss10": 33e-12, "crss10": 3.3e-12, "crss0": 22.3e-12}
CISS_MAX, COSS_MAX, CRSS_MAX = 50e-12, 25e-12, 8e-12
CRSS_MODEL10 = 22.3e-12 / (1 + 10 / 0.6) ** 0.64   # model Cgd at VDG = 10 V (cgd0/vjgd/mgd fit in the .lib)
C_SLOW = dict(cgs=CISS_MAX - CRSS_MAX, cds=COSS_MAX - CRSS_MAX, cgd0=22.3e-12 * CRSS_MAX / CRSS_MODEL10)
QA = ("6", "2", "1")     # Q1 unit A pins (D, G, S), KiCad Q_Dual_NMOS_S1G1D2S2G2D1 (sheets/base.py)
QB = ("3", "5", "4")     # Q1 unit B pins (D, G, S)

# ----------------------------------------------------------------------------------------------- others
NTC_B_TOL = 0.01         # Murata B25/50 3380 K +-1 %
NTC_B2550 = 3380.0       # Murata B-constant (25/50 C)
NTC_IMAX, NTC_VMAX = 0.1e-3, 5.0   # Murata max operating current (25 C), max voltage
SW_RON, SW_ROFF = 0.1, 100e6       # XKB: contact resistance 100 mOhm max, insulation resistance 100 MOhm min
SW_IMAX = 50e-3                    # XKB contact rating 50 mA, 12 V DC
VIL_K, VIH_K = 0.3, 0.7            # nRF52840 GPIO VIL max = 0.3 VDD, VIH min = 0.7 VDD
VDD_NOM, VDD_TOL = 3.3, 0.02       # RT9080-33 VOUT accuracy -2 / +2 % (ILOAD 1 mA)
LDO_DROP = 0.01                    # RT9080 dropout 0.31 V @ 600 mA (~0.5 Ohm) -> ~10 mV at the ~mA load
DEBOUNCE = 5e-3                    # docs/firmware.md gpio-keys debounce-interval-ms = <5>
# Link harness, signal wire: architecture.md §2 link (50-80 mm, 28 AWG 0.21 Ohm/m) + 2 JST SH contacts
# (20 mOhm max each). The capacitances are ASSUMPTIONS (no source gives them); both are negligible here.
R_HARNESS = 0.08 * 0.21 + 2 * 0.02
C_HARNESS, C_NRF = 20e-12, 3e-12

TEMPS = (-10.0, 25.0, 60.0)
VBATS = (3.0, 3.7, 4.2)
MODES = {"usb4.5": 4.5, "usb5.0": 5.0, "usb5.5": 5.5, "bat": 0.0}   # VBUS at J1; 0 V = battery only
BASE_NETS = {"VBAT", "SW_HI", "SW_GATE", "CHG_TSMR", "BTN_N", "GND"}
MODELS = ("charger_ts__bq25180.lib", "charger_ts__bss138dw.lib", "charger_ts__ncp15xh103.lib")


# =============================================================================================== helpers
def new_deck(title: str) -> Deck:
    deck = Deck(title)
    for m in MODELS:
        deck.include(m)
    deck += ".model CTS_SW sw vt=0.5 vh=0 ron=%g roff=%g" % (SW_RON, SW_ROFF)
    return deck


def sim_errors(res):
    """Simulator errors, without failed WHEN measurements (those come back as None and fail their check)."""
    return [e for e in res["_errors"] if not re.match(r"\s*meas\s", e)]


def raw_value(d, ref):
    return d._override.get(ref, d.comps[ref]["value"])   # see harness_requests: Design.raw_value()


def ntc_r25_b(d):
    """R25 and B of RT1 from the netlist value string, e.g. '10k B3435'."""
    m = re.search(r"\bB\s*(\d{4})\b", raw_value(d, "RT1"))
    assert m, f"RT1 value {raw_value(d, 'RT1')!r} gives no B constant"
    return d.value("RT1"), float(m.group(1))


def link_ref(d):
    refs = [r for r, c in d.comps.items() if c["value"] == "LINK"]
    assert len(refs) == 1, refs
    return refs[0]


def link_pin(base, main, net="BTN_N"):
    """The link pin of `net` on the base connector, which must carry the same net on main."""
    jb, jm = link_ref(base), link_ref(main)
    pins = [p for p, n in base.pins[jb].items() if n == net]
    assert len(pins) == 1, (jb, pins)
    p = pins[0]
    assert main.pins[jm].get(p) == net, f"link pin {p}: base {net}, main {main.pins[jm].get(p)}"
    return jb, jm, p


def suffix(lines, sfx):
    out = []
    for ln in lines:
        toks = ln.split()
        toks[0] += sfx
        out.append(" ".join(t + sfx if re.fullmatch(r"n_\w+", t) else t for t in toks))
    return out


def vdd_for(vbat, mode, corner):
    """+3V3 on main: RT9080-33 from VSYS (4.5 V on USB, VBAT on battery, SPEC §3), -2/+2 % (corner -1/+1)."""
    v = VDD_NOM * (1 + corner * VDD_TOL)
    return v if MODES[mode] > 0 else min(v, vbat - LDO_DROP)


def build_cell(base, main, *, vbat=3.7, mode="usb5.0", pressed=False, switch=None, fet="typ",
               its="typ", dr=0.0, db=0.0, idss=IDSS_MAX, vdd=None, rscale=None, mscale=None,
               vclamp="typ", pulsed=0, tdel=0.0, caps=None):
    """One copy of the TS/MR + BTN_N circuit from both netlists. Returns (lines, probe nodes)."""
    its_ad = ITS[its] if isinstance(its, str) else its
    its_bat = ITS_BAT[its] if isinstance(its, str) else its * _ITS_BAT_TYP / ITS["typ"]
    vcl = VTS_CLAMP[vclamp] if isinstance(vclamp, str) else vclamp
    vdd = vdd_for(vbat, mode, 0) if vdd is None else vdd
    b = [f"VBATT {base.pin('J2', '1')} 0 {vbat:g}",              # cell on the battery connector
         f"VUSB {base.pin('J1', 'A4')} 0 {MODES[mode]:g}"]       # USB-C VBUS
    b += base.passives(nets=BASE_NETS, scale=rscale)            # R3, R4 (and C3 on VBAT)
    if base.fitted("SW1"):
        a, c = base.pin("SW1", "1"), base.pin("SW1", "2")
        b.append(f"SSW1 {a} {c} {switch} 0 CTS_SW" if switch else
                 f"RSW1 {a} {c} {SW_RON if pressed else SW_ROFF:g}")
    if base.fitted("Q1"):
        fp = FET[fet]
        prm = f"vth={fp['vth']} beta={fp['beta']} rs={fp['rs']} idss={idss:g}"
        prm += "".join(f" {k}={v:g}" for k, v in (caps or {}).items())
        for name, (pd, pg, ps) in (("XQ1A", QA), ("XQ1B", QB)):
            b.append(f"{name} {base.pin('Q1', pd)} {base.pin('Q1', pg)} {base.pin('Q1', ps)} CTS_BSS138DW_N params: {prm}")
    if base.fitted("RT1"):
        r25, bnet = ntc_r25_b(base)
        b.append(f"VIRT1 {base.pin('RT1', '1')} n_rt1_i 0")
        if "RT1" in base._shorted:   # RT1 is not emitted by passives(), so honour Design.short() here
            b.append(f"VRT1_short n_rt1_i {base.pin('RT1', '2')} 0")
        else:
            b.append(f"XRT1 n_rt1_i {base.pin('RT1', '2')} CTS_NCP15XH103 params: r25={r25:g} bnet={bnet:g} "
                     f"dr={dr:g} db={db:g}")
    if base.fitted("U1"):
        b.append(f"XU1 {base.pin('U1', 'TS/MR')} {base.pin('U1', 'IN')} {base.pin('U1', 'BAT')} CTS_BQ25180_TSMR "
                 f"params: its_ad={its_ad:g} its_bat={its_bat:g} pulsed={pulsed} tdel={tdel:g} vclamp={vcl:g}")
    jb, jm, p = link_pin(base, main)
    m = [f"VDD {main.node('+3V3')} 0 {vdd:g}"]
    m += main.passives(nets={"+3V3", "BTN_N"}, scale=mscale)    # R56
    nrf = main.pin("U10", "P1.10")
    m.append(f"CNRF {nrf} 0 {C_NRF:g}")
    m = suffix(m, "_m")
    b.append(f"RHARN {base.pin(jb, p)} {main.pin(jm, p)}_m {R_HARNESS:g}")
    b.append(f"CHARN {main.pin(jm, p)}_m 0 {C_HARNESS:g}")
    probes = {"ts": f"v({base.pin('U1', 'TS/MR')})", "gate": f"v({base.pin('Q1', QA[1])})",
              "btn": f"v({nrf}_m)", "irt": "i(virt1)", "ibat": "i(vbatt)"}   # ibat < 0 = cell sourcing
    return b + m, probes, vdd


def cells_deck(title, base, main, cfgs):
    deck = new_deck(title)
    probes, vdds = [], []
    for k, cfg in enumerate(cfgs):
        lines, pr, vdd = build_cell(base, main, **cfg)
        deck += suffix(lines, f"_{k}")
        probes.append({q: re.sub(r"\((\w+)\)", lambda m: f"({m.group(1)}_{k})", e) for q, e in pr.items()})
        vdds.append(vdd)
    return deck, probes, vdds


def run_dc(title, base, main, cfgs, quantities=("ts",), temps=TEMPS):
    """DC temperature sweep over many circuit copies; returns [{q: [value at each temp]}] per config."""
    deck, probes, vdds = cells_deck(title, base, main, cfgs)
    deck.dc("temp", min(temps), max(temps), 5)
    for k, pr in enumerate(probes):
        for q in quantities:
            for i, t in enumerate(temps):
                deck.meas(f"dc k{k}_{q}_{i} FIND {pr[q]} AT={t:g}")
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    out = []
    for k in range(len(cfgs)):
        row = {q: [res.get(f"k{k}_{q}_{i}") for i in range(len(temps))] for q in quantities}
        row["vdd"] = vdds[k]
        out.append(row)
    return out


def worst(rows, cfgs, q, pick, key=None):
    """(value, temperature, config) of the worst (pick = max/min) entry of quantity q over rows and TEMPS."""
    items = []
    for r, c in zip(rows, cfgs):
        for t, v in zip(TEMPS, r[q]):
            assert v is not None, (q, c, t)
            items.append((key(v, r) if key else v, t, c))
    return pick(items, key=lambda x: x[0])


def desc(cfg, t=None):
    parts = []
    for k in ("mode", "vbat", "fet", "its", "dr", "db"):
        if cfg.get(k) is not None:
            x = cfg[k]
            parts.append(f"{k}={x:+.3g}" if k in ("dr", "db") else f"{k}={x:.4g}" if isinstance(x, float) else f"{k}={x}")
    for k in ("rscale", "mscale"):
        if cfg.get(k):
            parts.append(" ".join(f"{r}x{m:.3f}" for r, m in cfg[k].items()))
    return ", ".join(parts) + (f", T={t:g} °C" if t is not None else "")


# ------------------------------------------------------------------------------------------- JEITA deck
def jeita_cells(base):
    tol = base.tol("RT1")
    cells = []
    for its in ("min", "typ", "max"):
        for dr in (-tol, 0.0, tol):
            for db in (-NTC_B_TOL, 0.0, NTC_B_TOL):
                for idss in (0.0, IDSS_MAX):
                    cells.append(dict(its=its, dr=dr, db=db, idss=idss))
    return cells


def jeita_run(base, main, cells=None, levels=None, title="TS/MR JEITA trip temperatures"):
    """Trip temperature of every TS threshold level for each cell (adapter present, released, 38 uA mode).

    levels: {tag: voltage}; default = min/typ/max of every THR entry + VTS_ENZ min.
    Returns ([{tag: T or None, 'v-10': V_TS at -10 C, 'v25': V_TS at 25 C}], cells).
    """
    cells = cells or jeita_cells(base)
    if levels is None:
        levels = {f"{k}_{lv}": THR[k][i] for k in THR for i, lv in enumerate(("min", "typ", "max"))}
        levels["ENZ"] = VTS_ENZ_MIN
    cfgs = [dict(c, its=c["its"], mode="usb5.0", vbat=3.7) for c in cells]
    deck, probes, _ = cells_deck(title, base, main, cfgs)
    deck.dc("temp", -30, 90, 0.05)
    for k, pr in enumerate(probes):
        for tag, v in levels.items():
            deck.meas(f"dc j{k}_{tag.lower()} WHEN {pr['ts']}={v:g} CROSS=1")
        deck.meas(f"dc j{k}_vm10 FIND {pr['ts']} AT=-10")
        deck.meas(f"dc j{k}_v25 FIND {pr['ts']} AT=25")
    res = deck.run()
    errors = sim_errors(res)
    assert not errors, errors[:5]
    out = []
    for k in range(len(cells)):
        row = {tag: res.get(f"j{k}_{tag.lower()}") for tag in levels}
        row["v-10"], row["v25"] = res.get(f"j{k}_vm10"), res.get(f"j{k}_v25")
        out.append(row)
    return out, cells


@pytest.fixture(scope="module")
def jeita():
    return jeita_run(spicelib.Design("base"), spicelib.Design("main"))


def jdesc(c):
    its = c["its"] if isinstance(c["its"], str) else f"{c['its'] * 1e6:.2f} µA"
    return f"ITS {its}, R25 {c['dr']:+.0%}, B {c['db']:+.0%}, IDSS {c['idss'] * 1e6:.1f} µA"


def nominal_index(cells):
    return next(i for i, c in enumerate(cells) if c["its"] == "typ" and c["dr"] == 0 and c["db"] == 0
                and c["idss"] == 0)


def mapping(rows, cells, key):
    """Nominal trip temperature of threshold `key` and the spread the IC's own min/max threshold gives."""
    r = rows[nominal_index(cells)]
    t_typ, t_a, t_b = r[f"{key}_typ"], r[f"{key}_min"], r[f"{key}_max"]
    if None in (t_typ, t_a, t_b):      # threshold never crossed in -30..90 C: the check gets None and fails
        return None, 0.0
    return t_typ, max(abs(t_a - t_typ), abs(t_b - t_typ))


def pick_none(items, pick):
    """min/max of (value, info) pairs; any None value (no crossing) wins, so its check fails."""
    for it in items:
        if it[0] is None:
            return it
    return pick(items, key=lambda x: x[0])


def diff_none(a, b):
    return None if a is None or b is None else a - b


# =============================================================================================== tests
def test_models_match_datasheets(check):
    """The behavioural models reproduce the datasheet anchor points they were fitted to."""
    deck = new_deck("model anchors")
    deck += [".temp 25"]
    for name, fp in FET.items():   # VGS(th): VGS = VDS, ID = 250 uA
        deck += [f"I{name} 0 nd_{name} 250u",
                 f"X{name} nd_{name} nd_{name} 0 CTS_BSS138DW_N params: vth={fp['vth']} beta={fp['beta']} rs={fp['rs']}"]
    for name in ("typ", "weak"):   # RDS(ON) at VGS = 10 V, ID = 0.22 A
        fp = FET[name]
        deck += [f"IR{name} 0 nr_{name} 0.22",
                 f"XR{name} nr_{name} ng10 0 CTS_BSS138DW_N params: vth={fp['vth']} beta={fp['beta']} rs={fp['rs']}"]
    deck += ["VG10 ng10 0 10", "IN1 0 nntc 10u", "XN1 nntc 0 CTS_NCP15XH103"]
    deck.dc("temp", 25, 50, 25)
    for name in FET:
        deck.meas(f"dc vth_{name} FIND v(nd_{name}) AT=25")
    for name in ("typ", "weak"):
        deck.meas(f"dc rds_{name} FIND v(nr_{name}) AT=25")
    deck.meas("dc vn25 FIND v(nntc) AT=25")
    deck.meas("dc vn50 FIND v(nntc) AT=50")
    res = deck.run()
    for name, (lo, nom, hi) in (("strong", (0.5, 0.5, 0.5)), ("typ", (1.2, 1.2, 1.2)), ("weak", (1.5, 1.5, 1.5))):
        check(f"model VGS(th) @250 µA, {name} corner", res[f"vth_{name}"], nom * 0.99, nom * 1.01, "V",
              f"{QDS} EC table VGS(th) {lo}/{nom}/{hi} V")
    check("model RDS(ON) @VGS 10 V, 0.22 A, typ", res["rds_typ"] / 0.22, 1.4 * 0.9, 1.4 * 1.1, "Ω",
          f"{QDS} EC table RDS(ON) typ 1.4 Ω")
    check("model RDS(ON) @VGS 10 V, 0.22 A, weak corner", res["rds_weak"] / 0.22, 3.5 * 0.97, 3.5 * 1.03, "Ω",
          f"{QDS} EC table RDS(ON) max 3.5 Ω")
    b2550 = math.log(res["vn25"] / res["vn50"]) / (1 / 298.15 - 1 / 323.15)
    check("model NTC B25/50", b2550, NTC_B2550 * 0.995, NTC_B2550 * 1.005, "K", f"{NTC} B25/50 3380 K")
    check("model NTC R25", res["vn25"] / 10e-6, 9.99e3, 10.01e3, "Ω", f"{NTC} R25 10 kΩ")

    # capacitances at VGS = 0, f = 1 MHz (AC): Ciss from the gate current, Crss from the drain current
    deck = new_deck("model capacitances")
    corners = (("fig10", {}), ("ecmax", C_SLOW))
    for name, caps in corners:
        prm = "vth=1.2 beta=0.31 rs=1.0" + "".join(f" {k}={v:g}" for k, v in caps.items())
        for vds in (0, 10):
            tag = f"{name}{vds}"
            deck += [f"VD{tag} nd{tag} 0 DC {vds} AC 0", f"VG{tag} ng{tag} 0 DC 0 AC 1",
                     f"X{tag} nd{tag} ng{tag} 0 CTS_BSS138DW_N params: {prm}"]
    deck.ac("lin", 1, "1meg", "1meg")
    exprs = [f"abs(imag(i(vg{n}{v})))/(2*pi*1e6)" for n, _ in corners for v in (0, 10)]
    exprs += [f"abs(imag(i(vd{n}{v})))/(2*pi*1e6)" for n, _ in corners for v in (0, 10)]
    deck.print_op(*exprs)
    r = deck.run()
    keys = [f"ciss_{n}{v}" for n, _ in corners for v in (0, 10)] + [f"crss_{n}{v}" for n, _ in corners for v in (0, 10)]
    cap = {k: r.get(f"op_{i}") for i, k in enumerate(keys)}
    for k, ref, tol, src in (("crss_fig100", FIG10["crss0"], 0.1, "Fig. 10 Crss at VDS = 0 (digitised 22.3 pF)"),
                             ("crss_fig1010", FIG10["crss10"], 0.15, "Fig. 10 Crss at VDS = 10 V (digitised 3.3 pF)"),
                             ("ciss_fig1010", FIG10["ciss10"], 0.15, "Fig. 10 Ciss at VDS = 10 V (digitised 33 pF)"),
                             ("crss_ecmax10", CRSS_MAX, 0.05, "EC table Crss max 8 pF at VDS = 10 V"),
                             ("ciss_ecmax10", CISS_MAX, 0.05, "EC table Ciss max 50 pF at VDS = 10 V")):
        check(f"model {k}", cap[k], ref * (1 - tol), ref * (1 + tol), "F", f"{QDS} {src}")


def test_link_carries_btn_n_on_the_same_pin(base, main, check):
    jb, jm, p = link_pin(base, main)      # asserts the same pin carries BTN_N on both connectors
    same = float(main.pin("U10", "P1.10") == main.node("BTN_N") and base.pin("Q1", QB[0]) == base.node("BTN_N"))
    check(f"BTN_N: Q1B drain -> base {jb}.{p} -> main {jm}.{p} -> nRF P1.10 (1 = connected)", same, 1.0, 1.0, "",
          "SPEC §2 link pinout (pin 12 BTN_N, both boards), SPEC §4 pin map (P1.10 BTN_N), SPEC §3 Q2 -> BTN_N")


# ------------------------------------------------------------------------------------- JEITA thresholds
@pytest.mark.parametrize("key", ["COLD00", "COOL", "WARM", "HOT00"])
def test_jeita_nominal_mapping(jeita, key, check):
    """With typical IC parameters and the nominal NTC, each default threshold trips at the temperature the
    datasheet states, within the spread the IC's own threshold min/max alone would give."""
    rows, cells = jeita
    t_typ, spread = mapping(rows, cells, key)
    approx, name = THR[key][3], THR[key][4]
    check(f"{key} trip, typ IC + nominal RT1", t_typ, approx - spread, approx + spread, "°C",
          f"{BQ} Table 7.5 {name} 'Approx. {approx:g} °C'; band = ±{spread:.2f} °C from {name} min/max at 38 µA")


@pytest.mark.parametrize("reg", [
    pytest.param("0x00", marks=pytest.mark.xfail(strict=True, reason=(
        "DESIGN ISSUE: with the default TS_CONTROL (0x00) the worst-case COLD trip is about -2 °C and the "
        "worst-case HOT trip about +64 °C (IC threshold + bias tolerance with RT1 R25/B tolerance), so the "
        "charger may charge outside the JEITA 0-60 °C window; write TS_CONTROL = 0x90 at init"))),
    "0x90",
])
def test_jeita_charge_prohibit_worst_case(jeita, reg, check):
    """No combination of ITS, threshold, RT1 R25/B tolerance and Q1A leakage lets charging continue below
    0 °C or above 60 °C (adapter present: 38 uA continuous bias)."""
    rows, cells = jeita
    cold, hot = TS_CONTROL[reg]
    t_cold = [(r[f"{cold}_max"], c) for r, c in zip(rows, cells)]   # highest threshold = coldest trip
    t_hot = [(r[f"{hot}_min"], c) for r, c in zip(rows, cells)]     # lowest threshold = hottest trip
    tc, cc = pick_none(t_cold, min)
    th, ch = pick_none(t_hot, max)
    errors = []
    for args in ((f"TS_CONTROL {reg}: coldest COLD trip ({THR[cold][4]} max; {jdesc(cc)})", tc, T_JEITA_MIN, None),
                 (f"TS_CONTROL {reg}: hottest HOT trip ({THR[hot][4]} min; {jdesc(ch)})", th, None, T_JEITA_MAX)):
        try:
            check(*args, "°C", f"{JEITA}; {BQ} Table 7.5 thresholds + ITS_BIAS; {NTC} R25/B ±1 %; {QDS} IDSS")
        except AssertionError as e:   # record both limits before failing
            errors.append(e)
    if errors:
        raise errors[0]


@pytest.mark.parametrize("reg", ["0x00", "0x90"])
def test_jeita_zone_order_all_corners(jeita, reg, check):
    """The COOL (reduced current) and WARM (reduced voltage) zones never collapse at any corner."""
    rows, cells = jeita
    cold, hot = TS_CONTROL[reg]
    gap_c, _ = pick_none([(diff_none(r["COOL_max"], r[f"{cold}_min"]), 0) for r in rows], min)  # coldest COOL vs warmest COLD
    gap_h, _ = pick_none([(diff_none(r[f"{hot}_max"], r["WARM_min"]), 0) for r in rows], min)    # coldest HOT vs hottest WARM
    check(f"TS_CONTROL {reg}: COOL trip minus COLD trip, worst corner", gap_c, 0.0, None, "°C",
          f"{BQ} §8.3.13.1 JEITA zones (VCOLD > VCOOL), Table 7.5")
    check(f"TS_CONTROL {reg}: HOT trip minus WARM trip, worst corner", gap_h, 0.0, None, "°C",
          f"{BQ} §8.3.13.1 JEITA zones (VWARM > VHOT), Table 7.5")


def test_ts_stays_below_enz_at_minus_10c(jeita, check):
    """At -10 °C the pin stays below VTS_ENZ (above it the datasheet disables the TS function)."""
    rows, cells = jeita
    vmax, c = max(((r["v-10"], c) for r, c in zip(rows, cells)), key=lambda x: x[0])
    check(f"V(TS/MR) at -10 °C, worst corner ({jdesc(c)})", vmax, None, VTS_ENZ_MIN, "V", f"{BQ} Table 7.5 VTS_ENZ min 1.8 V")
    t_enz = max((r["ENZ"] for r in rows if r["ENZ"] is not None), default=None)
    check("warmest temperature at which any corner reaches VTS_ENZ min (informational)", t_enz,
          unit="°C", source=f"{BQ} Table 7.5 VTS_ENZ; behaviour above it is not specified")


def test_board_ntc_alone_gives_normal_zone_at_25c(jeita, check):
    """No pack NTC (2-wire PH lead): RT1 alone puts TS/MR in the normal (full-current) zone at 25 °C at
    every corner, so the charger charges normally."""
    rows, cells = jeita
    v = [r["v25"] for r in rows]
    check("V(TS/MR) at 25 °C, lowest corner", min(v), VWARM_EXIT_MAX, None, "V",
          f"{BQ} Table 7.5 VT6_Exit max 0.235 V (warm exit)")
    check("V(TS/MR) at 25 °C, highest corner", max(v), None, THR["COOL"][0], "V",
          f"{BQ} Table 7.5 VT5_Entry min 0.635 V (cool entry)")


@pytest.mark.slow
def test_jeita_monte_carlo(base, main, check):
    """300 uniform draws of ITS, RT1 R25 (netlist tolerance) and B, Q1A leakage and the IC thresholds."""
    rng = random.Random(7)
    n = 300
    tol_b = NTC_B_TOL
    cells = []
    for s in base.monte_carlo(["RT1"], n, seed=11):
        cells.append(dict(its=ITS["typ"] * (1 + rng.uniform(-1, 1) * _ITS_REL), dr=s["RT1"] - 1,
                          db=rng.uniform(-tol_b, tol_b), idss=rng.uniform(0, IDSS_MAX)))
    draws = {k: [rng.uniform(THR[k][0], THR[k][2]) for _ in range(n)] for k in ("COLD00", "COLD01", "HOT00", "HOT10")}
    levels = {f"{k}_{i}": draws[k][i] for k in draws for i in range(n)}
    # one WHEN measure per cell for its own threshold draw: build per-cell level sets
    deck, probes, _ = cells_deck("TS/MR JEITA Monte Carlo", base, main,
                                 [dict(c, mode="usb5.0", vbat=3.7) for c in cells])
    deck.dc("temp", -30, 90, 0.05)
    for k, pr in enumerate(probes):
        for key in draws:
            deck.meas(f"dc m{k}_{key.lower()} WHEN {pr['ts']}={levels[f'{key}_{k}']:g} CROSS=1")
    res = deck.run()
    errors = sim_errors(res)
    assert not errors, errors[:5]
    missing = [k for k in range(n) for key in draws if res.get(f"m{k}_{key.lower()}") is None]
    assert not missing, f"no threshold crossing in -30..90 °C for draws {missing[:5]}"
    t = {key: np.array([res[f"m{k}_{key.lower()}"] for k in range(n)]) for key in draws}
    for reg, (cold, hot) in TS_CONTROL.items():
        below = float(np.mean(t[cold] < T_JEITA_MIN))
        above = float(np.mean(t[hot] > T_JEITA_MAX))
        if reg == "0x00":   # default: informational (the worst-case test above carries the xfail)
            check(f"MC TS_CONTROL {reg}: share of units whose COLD trip is below 0 °C", below, unit="",
                  source=f"{JEITA} (informational)")
            check(f"MC TS_CONTROL {reg}: share of units whose HOT trip is above 60 °C", above, unit="",
                  source=f"{JEITA} (informational)")
        else:
            check(f"MC TS_CONTROL {reg}: coldest COLD trip of {n}", float(t[cold].min()), T_JEITA_MIN, None, "°C", JEITA)
            check(f"MC TS_CONTROL {reg}: hottest HOT trip of {n}", float(t[hot].max()), None, T_JEITA_MAX, "°C", JEITA)


# ------------------------------------------------------------------------------------- button: TS/MR
def press_cfgs(base, mode):
    return [dict(mode=mode, vbat=vb, fet=f, its="max", pressed=True, rscale=s)
            for vb in VBATS for f in FET for s in base.extremes(["R3", "R4"])]


@pytest.mark.parametrize("mode", list(MODES))
def test_press_pulls_tsmr_below_mr_threshold(base, main, mode, check):
    """A press pulls TS/MR below VTSMR at every VBAT, FET, R3/R4 and temperature corner (max bias)."""
    cfgs = press_cfgs(base, mode)
    rows = run_dc(f"press {mode}", base, main, cfgs, ("ts", "gate", "ibat"))
    v, t, c = worst(rows, cfgs, "ts", max)
    check(f"V(TS/MR) pressed, {mode}, worst of {len(cfgs)}x3 ({desc(c, t)})", v, None, VTSMR, "V",
          f"{BQ} Table 7.5 VTSMR 90 mV (button press detect)")
    check(f"V(TS/MR) pressed, {mode}: a press also sits below VT7_Entry min 0.105 V, i.e. the TS comparators read "
          "HOT for the whole press (informational; firmware must ignore TS status while BTN_N is low)", v, unit="V",
          source=f"{BQ} Table 7.5 VT7_Entry; §8.3.13.1 (charging suspended while the button is pressed)")
    g, t, c = worst(rows, cfgs, "gate", max)
    check(f"Q1 VGS pressed, {mode}, max", g, None, VGSS_MAX, "V", f"{QDS} max ratings VGSS ±20 V")
    i, t, c = worst(rows, cfgs, "ibat", max, key=lambda v, r: -v)
    check(f"SW1 current pressed, {mode}, max", i, None, SW_IMAX, "A", f"{SWD} contact rating 50 mA")
    check(f"VBAT drain while held, {mode}, max (informational)", i, unit="A",
          source="sheets/base.py note (~4 uA while held)")


def test_press_minimum_vbat_for_detection(base, main, check):
    """Lowest VBAT at which a press still pulls TS/MR below 90 mV (weak FET, max bias, coldest corner)."""
    deck, probes, _ = cells_deck("press vs VBAT", base, main,
                                 [dict(mode="bat", vbat=3.0, fet="weak", its="max", pressed=True,
                                       rscale={"R3": 1 + base.tol("R3"), "R4": 1 - base.tol("R4")})])
    deck += [".temp -10"]
    deck.dc("VBATT_0", 3.0, 0.5, -0.005)
    deck.meas(f"dc vbat_min WHEN {probes[0]['ts']}={VTSMR} CROSS=1")
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    check("lowest VBAT with TS/MR < 90 mV pressed (weak FET, -10 °C)", res["vbat_min"], None, 3.0, "V",
          "firmware.md §13.1 CHARGECTRL1 BUVLO 3.0 V (lowest VBAT the system runs at); "
          f"{BQ} Table 7.5 VTSMR")


@pytest.mark.parametrize("mode", list(MODES))
def test_released_tsmr_never_reads_as_press(base, main, mode, check):
    """Released: RT1 alone (min bias, low NTC corner, Q1A IDSS max, SW1 insulation at its 100 MOhm
    minimum) keeps TS/MR above VTSMR over -10..60 °C, and the Q1 gates stay below VGS(th) min."""
    tol = base.tol("RT1")
    cfgs = [dict(mode=mode, vbat=vb, fet=f, its="min", dr=-tol, db=db, rscale=s)
            for vb in VBATS for f in ("typ", "strong") for db in (-NTC_B_TOL, NTC_B_TOL)
            for s in base.extremes(["R3", "R4"])]
    rows = run_dc(f"released {mode}", base, main, cfgs, ("ts", "gate"))
    v, t, c = worst(rows, cfgs, "ts", min)
    check(f"V(TS/MR) released, {mode}, worst of {len(cfgs)}x3 ({desc(c, t)})", v, VTSMR, None, "V",
          f"{BQ} Table 7.5 VTSMR 90 mV (must not detect a press)")
    # gate vs the VGS(th) minimum AT that temperature (Fig. 4 tempco: 0.38 V at 60 C), worst margin
    items = [(g - (VTH_MIN + TCV * (t - 25)), g, t, c) for r, c in zip(rows, cfgs) for t, g in zip(TEMPS, r["gate"])]
    _, g, t, c = max(items, key=lambda x: x[0])
    check(f"Q1 gate released (SW1 at 100 MΩ insulation), {mode}, worst vs VGS(th) min at T ({desc(c, t)})", g, None,
          VTH_MIN + TCV * (t - 25), "V",
          f"{QDS} VGS(th) min 0.5 V at 25 °C, Fig. 4 tempco -3.5 mV/°C; {SWD} insulation 100 MΩ min")


def test_ntc_and_pin_stress(base, main, check):
    """Highest bias (battery-only 60 uA +3.9 %, the clamp at its max) into the low/high NTC corners."""
    tol = base.tol("RT1")
    cfgs = [dict(mode=m, vbat=4.2, its="max", dr=dr, db=db, vclamp="max", idss=0.0)
            for m in ("bat", "usb5.0") for dr in (-tol, tol) for db in (-NTC_B_TOL, NTC_B_TOL)]
    rows = run_dc("NTC stress", base, main, cfgs, ("ts", "irt"))
    i, t, c = worst(rows, cfgs, "irt", max)
    check(f"RT1 current, max ({desc(c, t)})", i, None, NTC_IMAX, "A", f"{NTC} max operating current 0.1 mA")
    v, t, c = worst(rows, cfgs, "ts", max)
    check(f"V(TS/MR) = V(RT1), max ({desc(c, t)})", v, None, min(NTC_VMAX, VPIN_MAX), "V",
          f"{NTC} max voltage 5 V; {BQ} Table 7.1 5.5 V")


# ------------------------------------------------------------------------------------- button: BTN_N
def btn_cfgs(base, main, pressed):
    tol56 = main.tol("R56")
    out = []
    for vb, mode, corner in ((3.0, "bat", 0), (3.7, "bat", -1), (3.7, "bat", 1), (4.2, "usb5.0", -1),
                             (4.2, "usb5.0", 1)):
        for f in FET:
            for s in (1 - tol56, 1 + tol56):
                out.append(dict(mode=mode, vbat=vb, fet=f, pressed=pressed, vdd=vdd_for(vb, mode, corner),
                                mscale={"R56": s}, its="max"))
    return out


@pytest.mark.parametrize("pressed", [True, False], ids=["pressed", "released"])
def test_btn_n_logic_level_at_nrf(base, main, pressed, check):
    """BTN_N at nRF P1.10 (through the link harness, R56 to +3V3) reads low pressed / high released at
    every VBAT / +3V3 / FET / R56 corner over -10..60 °C (Q1B IDSS max)."""
    cfgs = btn_cfgs(base, main, pressed)
    rows = run_dc(f"BTN_N {'pressed' if pressed else 'released'}", base, main, cfgs, ("btn",))
    if pressed:
        r, t, c = worst(rows, cfgs, "btn", max, key=lambda v, row: v / row["vdd"])
        check(f"BTN_N / VDD pressed, worst ({desc(c, t)})", r, None, VIL_K, "×VDD", f"{NRF} VIL max 0.3 VDD")
    else:
        r, t, c = worst(rows, cfgs, "btn", min, key=lambda v, row: v / row["vdd"])
        check(f"BTN_N / VDD released, worst ({desc(c, t)})", r, VIH_K, None, "×VDD",
              f"{NRF} VIH min 0.7 VDD; {QDS} IDSS 0.5 µA")


# ------------------------------------------------------------------------------------- transients
def fault_look(t, v, t0, t1, refs):
    """Time in [t0, t1] that TS/MR spends neither below VTSMR (press) nor within 5 % of a steady state."""
    sel = (t >= t0) & (t <= t1)
    tt, vv = t[sel], v[sel]
    ok = vv < VTSMR
    for r in refs:
        ok |= np.abs(vv - r) <= 0.05 * abs(r)
    if not ok[-1]:          # still not settled at the end of the window: the tail is longer than the window
        return math.inf
    dt = np.diff(tt)
    return float(np.sum(dt[~ok[:-1]]))


def first_cross(t, v, t0, level, rising):
    sel = t >= t0
    tt, vv = t[sel], v[sel]
    idx = np.nonzero(vv >= level if rising else vv <= level)[0]
    return float(tt[idx[0]] - t0) if len(idx) else math.inf


# SLUSE99C specifies NO TS deglitch. A false reading must end within the window in which the charger itself
# evaluates TS/MR (battery-only: tTS_DUTY_ON 4 ms, Table 7.6) and within the 5 ms firmware debounce, so that
# firmware can blank TS status while BTN_N is low plus one debounce. The release window must exceed that limit.
T_SETTLE = min(T_TS_ON, DEBOUNCE)
T_PRESS, T_REL = 50e-6, 450e-6
T_END = T_REL + 1.25 * T_SETTLE
TRAN_CELLS = [  # slowest press edge (weak FET, low VBAT); slowest release (strong FET turns off last,
    dict(vbat=3.0, fet="weak", its="max"),                  # EC-table capacitance maxima); typical
    dict(vbat=4.2, fet="strong", its="min", caps=C_SLOW),
    dict(vbat=3.7, fet="typ", its="typ"),
]
_TRAN_CACHE = {}


def press_release(temp, r4=None):
    """USB present (38 uA always on), SW1 pressed at T_PRESS and released at T_REL, three FET/VBAT corners.
    Returns [(cfg, vdd, summary)] where summary holds the edge measurements. Cached per (temp, R4)."""
    key = (temp, r4)
    if key in _TRAN_CACHE:
        return _TRAN_CACHE[key]
    base, main = spicelib.Design("base"), spicelib.Design("main")
    if r4:
        base.override("R4", r4)
    cfgs = [dict(c, mode="usb5.0", switch="ctl_sw", dr=0.0, db=0.0) for c in TRAN_CELLS]
    deck, probes, vdds = cells_deck(f"press/release transient {temp:g} C, R4 {r4 or 'netlist'}", base, main, cfgs)
    deck += [f".temp {temp:g}",
             f"VCTL ctl_sw 0 PWL(0 0 {T_PRESS:g} 0 {T_PRESS + 1e-9:g} 1 {T_REL:g} 1 {T_REL + 1e-9:g} 0)"]
    deck.tran("20n", f"{T_END:g}", 0, "200n")
    deck.wave(*[p[q] for p in probes for q in ("ts", "btn")])
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    w = res["waves"]
    t = w["time"]
    out = []
    for c, p, vdd in zip(cfgs, probes, vdds):
        ts, btn = w[p["ts"]], w[p["btn"]]
        v_rest = float(np.median(ts[t < T_PRESS * 0.9]))   # released steady state (before and after)
        out.append((c, vdd, dict(
            press_band=fault_look(t, ts, T_PRESS, T_REL, [v_rest]),
            release_band=fault_look(t, ts, T_REL, T_END, [v_rest]),
            ts_release=first_cross(t, ts, T_REL, VTSMR, True),
            ts_min=float(ts.min()), ts_max=float(ts.max()), v_rest=v_rest,
            btn_low=first_cross(t, btn, T_PRESS, VIL_K * vdd, False),
            btn_high=first_cross(t, btn, T_REL, VIH_K * vdd, True))))
    _TRAN_CACHE[key] = out
    return out


def tran_tag(temp, c):
    return f"{temp:g} °C, {c['fet']} FET, VBAT {c['vbat']}, C {'EC max' if c.get('caps') else 'Fig. 10'}"


SETTLE_SRC = (f"{BQ}: no TS deglitch specified. Limit = Table 7.6 tTS_DUTY_ON 4 ms (TS/MR evaluation window) and "
              "firmware.md gpio-keys debounce 5 ms (TS status blanking after release). For information, Table 7.6 "
              "tSLEEP_DGL (a VIN deglitch, not a TS one) is 64 µs")


def check_bands(temp, rows, check, label):
    errors = []
    for c, _, m in rows:
        for edge in ("press", "release"):
            try:
                check(f"{label}{edge} edge: time TS/MR reads a false temperature ({tran_tag(temp, c)})",
                      m[f"{edge}_band"], None, T_SETTLE, "s", SETTLE_SRC)
            except AssertionError as e:   # record every corner before failing
                errors.append(e)
    if errors:
        raise errors[0]


@pytest.mark.parametrize("temp", TEMPS)
def test_press_release_edges_pin_and_btn_n(temp, check):
    """USB present: over the press and release edges TS/MR stays inside its abs-max range, and BTN_N at
    the nRF crosses VIL / VIH well inside the 5 ms firmware debounce."""
    for c, vdd, m in press_release(temp):
        tag = tran_tag(temp, c)
        check(f"V(TS/MR) min over press+release ({tag})", m["ts_min"], VPIN_MIN, None, "V", f"{BQ} Table 7.1 -0.3 V")
        check(f"V(TS/MR) max over press+release ({tag})", m["ts_max"], None, VPIN_MAX, "V", f"{BQ} Table 7.1 5.5 V")
        check(f"BTN_N below VIL after press ({tag})", m["btn_low"], None, DEBOUNCE, "s",
              f"{NRF} VIL 0.3 VDD; firmware.md gpio-keys debounce-interval-ms 5")
        check(f"BTN_N above VIH after release ({tag})", m["btn_high"], None, DEBOUNCE, "s",
              f"{NRF} VIH 0.7 VDD; firmware.md gpio-keys debounce-interval-ms 5")
        check(f"TS/MR back above VTSMR after release ({tag}, informational)", m["ts_release"], unit="s",
              source=f"{BQ} Table 7.5 VTSMR")


@pytest.mark.parametrize("temp", TEMPS)
def test_press_release_false_temperature_tail(temp, check):
    """USB present: after each press / release edge, TS/MR must be back at a valid reading (pressed, or its true
    NTC value within 5 %) before one TS evaluation window / one firmware debounce has passed. (During the press
    itself TS/MR also reads HOT, < VT7_Entry; the release tail only extends that by R4 x C_gate, ~0.02-0.3 ms.)"""
    check_bands(temp, press_release(temp), check, "")


@pytest.mark.parametrize("temp", [-10.0, 60.0])
def test_battery_only_pulsed_bias(base, main, temp, check):
    """Battery only (ship mode wake / EN_PUSH): the 60 uA bias is pulsed 4 ms every 200 ms. Every ON window
    inside a press reads below VTSMR, every ON window outside it reads above, and the pin settles inside
    the ON window."""
    tol = base.tol("RT1")
    tdel, p0, p1, t_end = 10e-3, 300e-3, 700e-3, 1.0
    cfgs = [dict(mode="bat", vbat=3.0, fet="weak", its="max", switch="ctl_sw", tdel=tdel, pulsed=1),
            dict(mode="bat", vbat=4.2, fet="strong", its="min", dr=-tol, db=NTC_B_TOL if temp > 25 else -NTC_B_TOL,
                 switch="ctl_sw", tdel=tdel, pulsed=1, caps=C_SLOW)]
    deck, probes, _ = cells_deck(f"battery-only pulsed {temp:g} C", base, main, cfgs)
    deck += [f".temp {temp:g}", f"VCTL ctl_sw 0 PWL(0 0 {p0:g} 0 {p0 + 1e-6:g} 1 {p1:g} 1 {p1 + 1e-6:g} 0)"]
    deck.tran("2u", f"{t_end:g}", 0, "20u")
    deck.wave(*[p["ts"] for p in probes])
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    w = res["waves"]
    t = w["time"]
    period = T_TS_ON + T_TS_OFF
    starts = [tdel + n * period for n in range(int((t_end - tdel) / period) + 1) if tdel + n * period + T_TS_ON < t_end]
    for c, p in zip(cfgs, probes):
        v = w[p["ts"]]
        tag = f"{temp:g} °C, {c['fet']} FET, VBAT {c['vbat']}"
        in_press, out_press, settle = [], [], []
        for s in starts:
            win = (t >= s + 50e-6) & (t <= s + T_TS_ON - 50e-6)
            final = float(v[win][-1])
            near = (t >= s) & (t <= s + T_TS_ON)
            idx = np.nonzero(np.abs(v[near] - final) <= 0.01 * max(final, VTSMR))[0]
            settle.append(float(t[near][idx[0]] - s) if len(idx) else math.inf)
            if p0 < s and s + T_TS_ON < p1:
                in_press.append((float(v[win].max()), float(v[win].min())))
            elif s + T_TS_ON < p0 or s > p1:
                out_press.append((float(v[win].max()), float(v[win].min())))
        assert in_press and out_press
        check(f"ON windows during the press: max V(TS/MR) ({tag})", max(x[0] for x in in_press), None, VTSMR, "V",
              f"{BQ} Table 7.5 VTSMR (battery only), Table 7.6 tTS_DUTY_ON/OFF")
        check(f"ON windows outside the press: min V(TS/MR) ({tag})", min(x[1] for x in out_press), VTSMR, None, "V",
              f"{BQ} Table 7.5 VTSMR (battery only)")
        check(f"TS/MR settling inside an ON window ({tag})", max(settle), None, T_TS_ON, "s",
              f"{BQ} Table 7.6 tTS_DUTY_ON 4 ms")


# ------------------------------------------------------------------------------------- fault injection
def window_25c(base, main):
    rows = run_dc("TS window 25 C", base, main, [dict(mode="usb5.0", vbat=3.7)], ("ts",), temps=(25.0, 30.0))
    return rows[0]["ts"][0]


@pytest.mark.fault
def test_fault_rt1_not_fitted_is_detected(base, main, check):
    """RT1 left off: the pin floats to the clamp. The 25 °C window check must flag it, and the pin stays inside
    its abs-max rating. (Whether the charger then suspends charging is NOT guaranteed: see
    test_open_ntc_keeps_ts_monitoring_enabled.)"""
    assert window_25c(base, main) < THR["COOL"][0]
    base.remove("RT1")
    v = window_25c(base, main)
    check("faulted (RT1 off): V(TS/MR) at 25 °C leaves the normal zone", v, THR["COOL"][0], None, "V",
          f"{BQ} Table 7.5 VT5_Entry min (the window check must fail)")
    check("faulted (RT1 off): V(TS/MR) inside the pin rating", v, None, VPIN_MAX, "V", f"{BQ} Table 7.1 5.5 V")


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE: an open RT1 (part missing, cracked 0402, open joint) lets TS/MR float to VTS_CLAMP "
    "(2.2-3.3 V), above VTS_ENZ min (1.8 V). SLUSE99C Table 7.5 enables the TS function only below VTS_ENZ, so "
    "JEITA protection may switch off silently instead of reading COLD (typ: clamp 2.8 V > ENZ 2.1 V). Fix "
    "(firmware, docs/firmware.md §13.1/13.2, bq25180.c): treat STAT0.TS_OPEN_STAT = 1 as a fault and set "
    "ICHG_CTRL.CHG_DIS = 1 while it is set; correct docs/bringup.md TS/MR row ('open = cold')"))
def test_open_ntc_keeps_ts_monitoring_enabled(base, main, check):
    """Fault condition: with RT1 open, TS/MR must stay below VTS_ENZ so the charger keeps monitoring TS (and reads
    COLD = charging suspended). Best case for the design: VTS_CLAMP at its minimum."""
    base.remove("RT1")
    rows = run_dc("RT1 open, clamp min", base, main, [dict(mode="usb5.0", vbat=3.7, vclamp="min")], ("ts",),
                  temps=(25.0, 30.0))
    check("RT1 open: V(TS/MR) with VTS_CLAMP at its min vs VTS_ENZ min", rows[0]["ts"][0], None, VTS_ENZ_MIN, "V",
          f"{BQ} Table 7.5 VTS_ENZ min 1.8 V ('VTSMR < VTS_ENZ for TS function to be enabled'), VTS_CLAMP 2.2 V min")


@pytest.mark.fault
def test_fault_rt1_shorted_is_detected(base, main, check):
    """RT1 shorted (solder bridge under the 0402): TS/MR sits at 0 V, i.e. a permanent press (ship / reset loop)
    and a permanent HOT. The released check must fail."""
    base.short("RT1")
    rows = run_dc("released, RT1 shorted", base, main, [dict(mode="usb5.0", vbat=3.7, fet="typ", its="max")], ("ts",))
    check("faulted (RT1 shorted): V(TS/MR) released at 25 °C", rows[0]["ts"][1], None, VTSMR, "V",
          f"{BQ} Table 7.5 VTSMR (the released check must fail)")


@pytest.mark.fault
def test_fault_r3_r4_values_swapped_is_detected(base, main, check):
    """R3 and R4 values swapped at assembly (1M in series, 1k to GND): the press must no longer pass."""
    base.override("R3", base.comps["R4"]["value"]).override("R4", base.comps["R3"]["value"])
    rows = run_dc("press, R3/R4 swapped", base, main, [dict(mode="usb5.0", vbat=3.7, fet="typ", pressed=True)],
                  ("ts",))
    check("faulted (R3/R4 swapped): V(TS/MR) pressed at 25 °C", rows[0]["ts"][1], VTSMR, None, "V",
          f"{BQ} Table 7.5 VTSMR (the press check must fail)")


@pytest.mark.fault
def test_fault_r4_not_fitted_is_detected(base, main, check):
    """R4 left off: nothing discharges SW_GATE, so the SW1 insulation leakage (100 MOhm min) against the
    Q1 gate leakage (IGSS bound) holds both FETs on: a stuck press (and a 20 s reset loop)."""
    base.remove("R4")
    rows = run_dc("released, R4 off", base, main, [dict(mode="usb5.0", vbat=3.7, fet="typ", its="min")],
                  ("ts", "btn"))
    check("faulted (R4 off): V(TS/MR) released at 25 °C", rows[0]["ts"][1], None, VTSMR, "V",
          f"{BQ} Table 7.5 VTSMR (the released check must fail)")
    check("faulted (R4 off): BTN_N / VDD released at 25 °C", rows[0]["btn"][1] / rows[0]["vdd"], None, VIH_K, "×VDD",
          f"{NRF} VIH (the released check must fail)")


@pytest.mark.fault
def test_fault_r56_not_fitted_is_detected(base, main, check):
    """Main-board pull-up R56 left off: BTN_N released must fail the VIH check."""
    main.remove("R56")
    rows = run_dc("BTN_N, R56 off", base, main, [dict(mode="usb5.0", vbat=3.7, fet="typ")], ("btn",))
    check("faulted (R56 off): BTN_N / VDD released at 25 °C", rows[0]["btn"][1] / rows[0]["vdd"], None, VIH_K,
          "×VDD", f"{NRF} VIH min 0.7 VDD (the released check must fail)")


@pytest.mark.fault
def test_fault_rt1_wrong_beta_is_detected(base, main, check):
    """RT1 replaced by a 10k B3950 NTC: the nominal JEITA mapping check must flag the COLD threshold."""
    base.override("RT1", "10k B3950")
    rows, cells = jeita_run(base, main, cells=[dict(its="typ", dr=0.0, db=0.0, idss=0.0)],
                            levels={f"COLD00_{lv}": THR["COLD00"][i] for i, lv in enumerate(("min", "typ", "max"))},
                            title="JEITA mapping, RT1 B3950")
    t_typ, spread = mapping(rows, cells, "COLD00")
    check("faulted (RT1 B3950): COLD trip offset from 'Approx. 0 °C' beyond the IC spread",
          abs(t_typ - THR["COLD00"][3]) - spread, 0.0, None, "°C", f"{BQ} Table 7.5 VT1_Entry (mapping check must fail)")
