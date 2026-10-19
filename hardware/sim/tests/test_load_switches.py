"""Load switches: U2 (TPS22917, VSYS -> VLED, 48x WS2812C ring) and U21 (TPS22917, VSYS -> OLED_VIN, TPS61040 input).

Everything on the switched rails comes from the main netlist (C7/C37 CT caps, R3/R25 ON pull-downs, R4 QOD resistor,
C8/C9 + C101..C148 on VLED, C38 / L20 / C30 / C31 / C39 / R26 / R27 / C40 on the boost side, R40 / R41 / R43 on the
LED data input) and the base netlist (VSYS caps on the base board).  ICs are the load_switches__*.lib models:

  load_switches__tps22917.lib   TI SLVMCE8 vendor model, turn-on block re-calibrated to SLVSDW8B Table 7.6
  load_switches__bq25180.lib    VSYS source (battery / USB power path) as the charger delivers it
  load_switches__ws2812c.lib    WS2812C-2020-V6 supply current + DIN clamp diodes (+ CI)
  load_switches__nrf52840_gpio.lib   nRF52840 GPIO Thevenin driver / disconnected pad
  load_switches__tps61040.lib   averaged TPS61040 start-up / input model (U21 load)
  load_switches__b5819w.lib     D21 Schottky incl. temperature-dependent reverse leakage
  load_switches__ssd1351.lib    SSD1351 VCI/VDDIO -> VCC ESD path (datasheet section 8.9 Note 1)

Angles covered: datasheet correlation of the switch model, supply corners (VBAT 3.0/3.7/4.2 V, VBUS 4.5/5.0/5.5 V
through the BQ25180 power path), temperature (-10/25/60 C on the battery impedance, the TPS22917 RON / leakage
limits, the clamp diodes and the D21 leakage), component tolerances (extremes / Monte Carlo), load extremes
(full-white ring, firmware LED caps), MCU reset, back-powering of both rails, and fault injection.
"""

from __future__ import annotations

import re

import pytest

import spicelib
from spicelib import Deck

LIB_SW = "load_switches__tps22917.lib"
LIB_WS = "load_switches__ws2812c.lib"
LIB_IO = "load_switches__nrf52840_gpio.lib"
LIB_BQ = "load_switches__bq25180.lib"
LIB_BST = "load_switches__tps61040.lib"
LIB_D21 = "load_switches__b5819w.lib"
LIB_PNL = "load_switches__ssd1351.lib"

DS_SW = "TPS22917 DS SLVSDW8B"
DS_BQ = "BQ25180 DS SLUSE99C"
DS_WS = "WS2812C-2020-V6 DS"
DS_BST = "TPS61040 DS SLVS413L"
DS_NRF = "nRF52840 PS v1.1 6.9.3.1"

# ---------------------------------------------------------------- datasheet limits (every one cited where used)
SW_IMAX = 2.0           # A, Table 7.1 max continuous switch current
SW_TJMAX = 125.0        # C, Table 7.1
SW_THETA_JA = 183.0     # C/W, Table 7.4 (DBV)
SW_VIH_MIN, SW_VIH_MAX, SW_VIL_MAX = 1.0, 5.5, 0.35   # V, Table 7.3
SW_RON_MAX = {3.6: {25: 0.110, 85: 0.140}, 5.0: {25: 0.100, 85: 0.120}}   # Ohm, Table 7.5 (IOUT 200 mA)
SW_ISD_MAX_85C = 100e-9  # A, Table 7.5 ISD,VIN disabled, -40..85 C
SW_TON_K = {3.6: 3.8e-6, 5.0: 4.0e-6}   # s per pF of CT, Table 7.6 tON (CT >= 100 pF)
SW_TR_K = {3.6: 1.6e-6, 5.0: 1.8e-6}    # s per pF of CT, Table 7.6 tR
SW_SR_K = {3.6: 1900.0, 5.0: 2300.0}    # (mV/us)*pF, Table 7.6 SRON
SW_QOD = 150.0          # Ohm typ, Table 7.5
BQ_BATOCP = 1.5         # A, IBAT_OCP setting 10 (CHARGECTRL1 0x92, docs/architecture.md 6.5), Table 7.5
WS_VDD_MIN, WS_VDD_MAX = 3.3, 5.3      # V, WS2812C-2020-V6 DS p.2 supply range
WS_VI_OVER_VDD = 0.7    # V, WS2812C-2020-V6 DS p.2 abs max VI <= VDD + 0.7 V
W25_VCC_MIN = 2.7       # V, W25Q128JV DS VCC min (lowest +3V3 consumer, docs/architecture.md section 7 table)
POF_LIMIT = 2.9 * 1.05  # V, firmware POFWARN 2.9 V (docs/firmware.md fault table) + VPOFTOL +5 % (nRF52840 PS v1.1 5.3.8.4)
BST_EN_VIL = 0.4        # V, TPS61040 Table 5.5 EN VIL max (EN is tied to VIN = OLED_VIN)
BST_FB_OVER_VIN = 0.3   # V, TPS61040 Table 5.1 abs max FB <= VIN + 0.3 V
FW_LED_WAIT = 5e-3      # s, docs/architecture.md section 7: "LEDs on: set LED_PWR_EN, wait >= 5 ms"
FW_LED_OFF = 30e-3      # s, docs/architecture.md section 7: "allow >= 30 ms for the QOD discharge"
FW_OLED_WAIT = 0.2      # s, docs/architecture.md section 7: "set OLED_VCC_EN, wait >= 200 ms, then AFh"

# RT9080 +3V3: dropout <= 0.53 V at 600 mA for VOUT >= 3 V (DS9080-09 Electrical Characteristics) -> 0.88 Ohm;
# +3V3 load 50 mA peak (docs/architecture.md section 7 power tree table).
LDO_RDO, I_3V3 = 0.53 / 0.6, 0.050

# Battery side impedance (cell + PCM + leads) "about 0.25 Ohm of pack plus path resistance" (docs/architecture.md 8.4)
# at 25 C.  ASSUMPTION for temperature: x2 at -10 C, x0.8 at 60 C (generic LiPo DCIR behaviour, no pack datasheet).
RPACK = {-10: 0.50, 25: 0.25, 60: 0.20}
# Link harness (docs/architecture.md 4.2): 2x 28 AWG VSYS wires 8.5 mOhm + 3x GND wires 5.7 mOhm at 80 mm.
R_HARNESS = 8.5e-3 + 5.7e-3

# VSYS corners: battery terminal voltage before the event, or VBUS with the BQ25180 SYS_REG 4.5 V power path.
CORNERS = {
    "bat3.0": dict(usb=0, vbat=3.0, vbus=0.0),
    "bat3.7": dict(usb=0, vbat=3.7, vbus=0.0),
    "bat4.2": dict(usb=0, vbat=4.2, vbus=0.0),
    "usb4.5": dict(usb=1, vbat=3.7, vbus=4.5),
    "usb5.0": dict(usb=1, vbat=3.7, vbus=5.0),
    "usb5.5": dict(usb=1, vbat=3.7, vbus=5.5),
}

# nRF52840 GPIO output resistance = 0.4 V / I(VDD-0.4 V), keyed by the PS current column (PS v1.1 6.9.3.1:
# IOH,SD 1/2/4 mA, IOH,HDH 6/9/14 mA min/typ/max): "sd_min" is the weakest pad (400 Ohm), "hd_max" the strongest
ROUT = {"sd_min": 0.4 / 1e-3, "sd_typ": 0.4 / 2e-3, "sd_max": 0.4 / 4e-3,
        "hd_min": 0.4 / 6e-3, "hd_typ": 0.4 / 9e-3, "hd_max": 0.4 / 14e-3}


# ======================================================================================== deck builders
def _rename(lines, tag):
    """Re-prefix element names and the VSYS node of another board's passives so they can share a deck."""
    out = []
    for ln in lines:
        tok = ln.split()
        tok[0] = tok[0][0] + tag + "_" + tok[0][1:]
        tok = [("n_vsys_" + tag) if t == "n_vsys" else t for t in tok]
        out.append(" ".join(tok))
    return out


def vsys_network(deck, main, base, corner="bat3.7", temp=25, i3v3=I_3V3, ronbat="55m", ronin="0.27", vsysreg=4.5):
    """BQ25180 power path -> base VSYS caps -> link harness -> main-board VSYS caps + always-on +3V3 load.

    Main-board VSYS node is n_vsys; +3V3 is an ideal LDO limited by the RT9080 dropout (n_p3v3)."""
    c = CORNERS[corner]
    deck.include(LIB_BQ)
    if c["usb"]:
        deck += (f"XBQ n_vsys_b 0 LSW_BQ25180_USB params: vbus={c['vbus']} vbat={c['vbat']} rpack={RPACK[temp]} "
                 f"ronbat={ronbat} ronin={ronin} vsysreg={vsysreg}")
    else:
        deck += f"XBQ n_vsys_b 0 LSW_BQ25180_BAT params: vbat={c['vbat']} rpack={RPACK[temp]} ronbat={ronbat}"
    deck += _rename(base.passives(nets={"VSYS", "GND"}), "b")
    deck += f"RHARN n_vsys_b n_vsys {R_HARNESS:.6g}"
    v_guess = min(vsysreg, c["vbus"]) if c["usb"] else c["vbat"]
    deck += f".nodeset v(n_vsys)={v_guess} v(n_vsys_b)={v_guess} v(n_p3v3)={min(3.3, v_guess)}"   # OP guide
    deck += main.passives(nets={"VSYS", "GND", "VSYS_SENSE"})
    deck += f"I3V3 n_vsys 0 DC {i3v3}"
    deck += f"BIBAT n_ibat 0 V = (V(xbq.vcell) - V(xbq.bat))/{RPACK[temp]}"     # battery current (A as V)
    deck += f"B3V3 n_p3v3 0 V = min(3.3, V(n_vsys) - {i3v3 * LDO_RDO:.6g})"
    return deck


R_SENSE = 1e-3   # Ohm, current-sense element (a short PCB trace); 0 V sources upset the TPS22917 model's logic


def sense(deck, a, b, out):
    """1 mOhm sense resistor a->b; V(out) = current in A (a 0 V source in series with the switch upsets the model)."""
    deck += f"RS_{out} {a} {b} {R_SENSE}"
    deck += f"BS_{out} {out} 0 V = (V({a}) - V({b}))/{R_SENSE}"
    return deck


def gpio(deck, main, net, out, oe, rout=ROUT["hd_typ"], ileak=0.0, name=None):
    """nRF52840 pad on `net` (an MCU pin of U10), level from node `out`, driver enable from node `oe`."""
    assert "U10" in main.on_net(net), net
    deck.include(LIB_IO)
    deck += (f"XIO_{name or net} {main.node(net)} n_p3v3 0 {out} {oe} LSW_NRF_GPIO "
             f"params: rout={rout:.6g} ileak={ileak:.6g}")
    return deck


def tps22917(deck, main, ref, ron_add=0.0, isd_out=0.0, vin_node=None):
    """Instantiate a TPS22917 by its netlist pins (vendor pin order CT GND ON QOD VIN VOUT)."""
    deck.include(LIB_SW)
    p = {f: main.pin(ref, f) for f in ("CT", "GND", "ON", "QOD", "VIN", "VOUT")}
    vin = vin_node or p["VIN"]
    deck += (f"X{ref} {p['CT']} {p['GND']} {p['ON']} {p['QOD']} {vin} {p['VOUT']} LSW_TPS22917 "
             f"params: ron_add={ron_add:.6g} isd_out={isd_out:.6g}")
    return deck


# MLCC DC-bias and temperature data, Samsung Electro-Mechanics component library, MLCC characteristic data sheet
# (https://weblib.samsungsem.com/mlcc/mlcc-ec-data-sheet.do?partNumber=<MPN>, read 2026-10-19): "DCBias" curve
# (% capacitance change vs DC volts, 25 C) and "TCC" curve (% vs 25 C, no bias).  Keyed by MPN without the packaging
# letter; a VLED capacitor whose MPN is not listed raises KeyError, so a BOM change forces new data.
MLCC_DCB = {
    "CL21A226MAQNNN": dict(dcb=[(0, 0.0), (0.5, 1.09), (1, -1.08), (1.5, -6.9), (2, -13.5), (2.5, -20.71),
                                (3, -28.12), (3.5, -34.96), (4, -41.05), (4.5, -46.52), (5, -51.3), (5.5, -55.49),
                                (6, -59.22)],
                           tcc={-10: -4.0, 25: 0.0, 60: -3.5}),
    "CL05B104KO5NNN": dict(dcb=[(0, 0.0), (0.5, 0.11), (1, 0.17), (1.5, -0.17), (2, -0.78), (2.5, -1.83),
                                (3, -3.1), (3.5, -4.51), (4, -6.14), (4.5, -7.8), (5, -9.54), (5.5, -11.32),
                                (6, -13.14)],
                           tcc={-10: -1.34, 25: 0.0, 60: -2.74}),
}


def _interp(x, pts):
    xs, ys = zip(*pts)
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])
    return ys[-1]


def mlcc_data(main, ref):
    mpn = main.mpn(ref).upper()
    for key, data in MLCC_DCB.items():
        if mpn.startswith(key):
            return data
    raise KeyError(f"{ref}: no Samsung DC-bias data for MPN {mpn!r}; add it to MLCC_DCB")


def dcbias_caps(main, refs, scale=None, temp=25):
    """Charge-based voltage-dependent capacitors (one per node and MPN): Q(V) = C0 * integral(1 + dC(v)/100) dv with
    the Samsung DC-bias curve, C0 = sum of netlist values x tolerance multiplier x (1 + TCC(temp)/100).  ngspice:
    a linear part C0*kmin (kmin = smallest 1 + dC/100 up to 6 V) stays a real capacitor on the node (ngspice stalls at
    the turn-off edge when a node has no linear capacitance); the rest, C0*(k(V) - kmin) >= 0, is an E source = its
    normalised charge, a C0 capacitor across it, and that capacitor's current mirrored onto the node by F."""
    groups = {}
    for ref in refs:
        pins = main.pins[ref]
        a, b = (spicelib.node_name(pins[p]) for p in sorted(pins))
        data = mlcc_data(main, ref)
        key = (a, b, id(data))
        c0 = main.value(ref) * (scale or {}).get(ref, 1.0) * (1 + _interp(temp, sorted(data["tcc"].items())) / 100)
        groups.setdefault(key, [data, 0.0, []])
        groups[key][1] += c0
        groups[key][2].append(ref)
    out = []
    for i, ((a, b, _), (data, c0, members)) in enumerate(groups.items()):
        step = 0.05
        grid = [j * step for j in range(int(round(6.0 / step)) + 1)]
        kmin = min(1 + _interp(v, data["dcb"]) / 100 for v in grid)
        q, pts = 0.0, [(-1.0, 0.0), (0.0, 0.0)]
        for v in grid[1:]:
            k0 = 1 + _interp(v - step, data["dcb"]) / 100 - kmin
            k1 = 1 + _interp(v, data["dcb"]) / 100 - kmin
            q += 0.5 * (k0 + k1) * step
            pts.append((v, q))
        tab = ", ".join(f"{x:.3g},{y:.6g}" for x, y in pts)
        out += [f"* DC-bias capacitor group {i}: {' '.join(members)} (C0 {c0:.6g} F at {temp} C, kmin {kmin:.4f})",
                f"CDCBL{i} {a} {b} {c0 * kmin:.6g}",
                f"EDCB{i} n_dcb{i}_q 0 vol = 'pwl(V({a},{b}), {tab})'",
                f"VDCB{i} n_dcb{i}_q n_dcb{i}_c 0",
                f"CDCB{i} n_dcb{i}_c 0 {c0:.6g}",
                f"FDCB{i} {a} {b} VDCB{i} 1"]
    return out


def led_rail(deck, main, duty=0.0, esd=None, dcbias=None):
    """U2's load: every fitted R/C on VLED / QOD / CT and each WS2812C pixel from the netlist.

    dcbias: None (capacitors at their netlist value), or dict(temp=..., scale={ref: k}) to replace every VLED
    capacitor by its Samsung DC-bias / TCC capacitance (tolerance multipliers from scale)."""
    deck.include(LIB_WS)
    vled_caps = [r for r in main.on_net("VLED", "C") if main.fitted(r)] if dcbias is not None else []
    deck += main.passives(nets={"VLED", "GND", "LSW_QOD", "LSW_CT", "VSYS", "LED_PWR_EN"},
                          exclude=_vsys_only(main) + vled_caps)
    if dcbias is not None:
        deck += dcbias_caps(main, vled_caps, scale=dcbias.get("scale"), temp=dcbias.get("temp", 25))
    esd = esd or {}
    extra = " ".join(f"{k}={v:.6g}" for k, v in esd.items())
    for ref in main.find("WS2812C"):
        deck += (f"X{ref} {main.pin(ref, 'DIN')} {main.pin(ref, 'VDD')} {main.pin(ref, 'VSS')} LSW_WS2812C "
                 f"params: duty={duty:.6g} {extra}")
    return deck


def _vsys_only(main):
    """Parts whose pins are all VSYS/GND are emitted by vsys_network(); skip them elsewhere."""
    return [r for r in main.comps if set(main.pins.get(r, {}).values()) <= {"VSYS", "GND"}]


def oled_input(deck, main, boost=True, panel_esd=False):
    """U21's load: C37/C41/C38/R25/L20/D21/output caps/FB divider from the netlist, TPS61040 averaged model
    (boost=False leaves U20 out, for decks that only need the ON/OFF state of U21)."""
    deck.include(LIB_D21)
    deck += main.passives(nets={"OLED_VIN", "OLED_BST_SW", "+13V_OLED", "OLED_BST_FB", "GND", "VSYS",
                                "OLED_LSW_CT", "OLED_VCC_EN"}, exclude=_vsys_only(main))
    a, k = main.pin("D21", "A"), main.pin("D21", "K")
    deck += f"XD21 {a} {k} LSW_B5819W"
    if boost:
        deck.include(LIB_BST)
        u = {f: main.pin("U20", f) for f in ("VIN", "SW", "FB", "EN", "GND")}
        deck += f"XU20 {u['VIN']} {u['SW']} {u['FB']} {u['EN']} {u['GND']} {k} LSW_TPS61040_AVG"
    if panel_esd:
        deck.include(LIB_PNL)
        j = main.pins["J20"]
        vci = next(n for p, n in j.items() if p == "27")
        vddio = next(n for p, n in j.items() if p == "4")
        vcc = next(n for p, n in j.items() if p == "2")
        deck += (f"XJ20 {spicelib.node_name(vci)} {spicelib.node_name(vddio)} {spicelib.node_name(vcc)} 0 "
                 f"LSW_SSD1351_ESD")
    return deck


def si(v):
    """Value string the netlist parser accepts (spicelib.parse_value has no exponent form): 1.1e-9 -> '1.1n'."""
    for mult, suf in ((1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= mult:
            return f"{v / mult:.6g}{suf}"
    return f"{v / 1e-15:.6g}f"


def scaled(main, scale):
    """Apply a {ref: multiplier} tolerance draw to the design as value overrides."""
    for ref, k in scale.items():
        main.override(ref, si(main.value(ref) * k))
    return main


class SimulationError(RuntimeError):
    """ngspice reported an error or a measurement is missing (kept distinct from check() failures, so an
    xfail(raises=AssertionError) can only be satisfied by a violated limit, never by a broken simulation)."""


def run(deck, *, need=()):
    res = deck.run()
    errors = list(res["_errors"])
    # The XSPICE ilimit block (BQ25180 USB input FET) prints "**** ERROR **** / CLIMIT function linear range less
    # than zero" for one Newton iteration while ngspice's gmin stepping explores the operating point; the step
    # then completes normally.  Drop exactly that pair, nothing else.
    lines = res["_log"].splitlines()
    benign = sum(1 for i, ln in enumerate(lines[:-1]) if "**** ERROR ****" in ln and "CLIMIT" in lines[i + 1])
    for _ in range(benign):
        if "**** ERROR ****" in errors:
            errors.remove("**** ERROR ****")
    # ngspice's operating-point homotopy reports intermediate failures ("Dynamic/True gmin stepping failed",
    # "singular matrix") before a later method succeeds; accept them only if that success is in the log.
    # "source stepping failed" (the last resort) is never accepted.
    if any("stepping completed" in ln for ln in lines) and not any("source stepping failed" in ln for ln in lines):
        errors = [e for e in errors if not re.search(r"gmin stepping failed|singular matrix", e)]
    if errors:
        raise SimulationError(errors[:5])
    missing = [n for n in need if n not in res]
    if missing:
        raise SimulationError((missing, res["_log"][-3000:]))
    return res


def detects(check, name, value, lo=None, hi=None, unit="", source=""):
    """Fault-injection helper: the faulted design must VIOLATE the limit, i.e. check() must fail."""
    with pytest.raises(AssertionError):
        check("FAULT DETECTED: " + name, value, lo, hi, unit, source)


# ======================================================================================== 1. model vs datasheet
@pytest.mark.parametrize("vin", [3.6, 5.0])
def test_model_turn_on_matches_table_7_6(check, vin):
    """TPS22917 model in the datasheet test circuit (Figure 8-1: CT 1 nF to VIN, CL 1 uF, RL 10 Ohm, QOD to VOUT)."""
    d = Deck(f"TPS22917 Table 7.6 at {vin} V")
    d.include(LIB_SW)
    d += [f"VIN vin 0 {vin}", "VON on 0 PWL(0 0 100u 0 100.1u 3.3)", "XU ct 0 on vout vin vout LSW_TPS22917",
          "CT1 ct vin 1000p", "CL vout 0 1u", "RL vout 0 10"]
    d.tran("2u", "7m")
    d.meas(f"tran t10 WHEN v(vout)={0.1 * vin} RISE=1")
    d.meas(f"tran t90 WHEN v(vout)={0.9 * vin} RISE=1")
    d.meas(f"tran t30 WHEN v(vout)={0.3 * vin} RISE=1")
    d.meas(f"tran t70 WHEN v(vout)={0.7 * vin} RISE=1")
    r = run(d, need=("t10", "t90", "t30", "t70"))
    tr, ton = r["t90"] - r["t10"], r["t90"] - 100.05e-6
    sr = 0.4 * vin / (r["t70"] - r["t30"]) / 1e3          # mV/us over the linear middle of the ramp
    ref = f"{DS_SW} Table 7.6 @{vin} V, CT 1000 pF (typ, +-15 % model correlation)"
    check(f"tR model @{vin} V", tr, 0.85 * SW_TR_K[vin] * 1000, 1.15 * SW_TR_K[vin] * 1000, "s", ref)
    check(f"tON model @{vin} V", ton, 0.85 * SW_TON_K[vin] * 1000, 1.15 * SW_TON_K[vin] * 1000, "s", ref)
    check(f"SRON model @{vin} V", sr, 0.85 * SW_SR_K[vin] / 1000, 1.15 * SW_SR_K[vin] / 1000, "mV/us", ref)


@pytest.mark.parametrize("vin", [3.6, 5.0])
def test_model_ron_qod_and_on_threshold(check, vin):
    """RON at 200 mA, QOD resistance and ON thresholds of the model against Table 7.3 / 7.5."""
    d = Deck(f"TPS22917 DC at {vin} V")
    d.include(LIB_SW)
    # switch A: on, 200 mA load; switch B: off, VOUT forced to 1 V through 0 V sense -> QOD current;
    # switch C: ON ramps 0 -> 1.2 -> 0 V slowly to find the thresholds (RL 1 kOhm).
    d += [f"VIN vin 0 {vin}", "VONA ona 0 3.3", "XA cta 0 ona va vin va LSW_TPS22917", f"RLA va 0 {vin / 0.2:.6g}",
          "VONB onb 0 0", "XB ctb 0 onb qb vin vb LSW_TPS22917", "VQ vb vf 0", "VF vf 0 1", "RQ qb vb 1u",
          "VONC onc 0 PWL(0 0 10m 1.2 20m 0)", "XC ctc 0 onc vc vin vc LSW_TPS22917", "RLC vc 0 1k"]
    d.tran("5u", "20m")
    d.meas("tran vla FIND v(va) AT=9m")
    d.meas("tran iqod FIND i(vq) AT=9m")
    d.meas("tran vrise FIND v(onc) WHEN v(vc)=0.5 RISE=1")
    d.meas("tran vfall FIND v(onc) WHEN v(ctc)=" + str(vin - 0.05) + " RISE=1")
    r = run(d, need=("vla", "iqod", "vrise", "vfall"))
    ron = (vin - r["vla"]) / (r["vla"] / (vin / 0.2))
    check(f"RON model @{vin} V 200 mA", ron, None, SW_RON_MAX[vin][25], "Ohm", f"{DS_SW} Table 7.5 RON max 25 C")
    check(f"QOD model @{vin} V", 1.0 / abs(r["iqod"]), 0.8 * SW_QOD, 1.2 * SW_QOD, "Ohm",
          f"{DS_SW} Table 7.5 QOD 150 Ohm typ (+-20 % correlation)")
    # comparator trips (rising: ON level when VOUT passes 0.5 V, ~15 mV late because of the CT-open ramp delay;
    # falling: ON level when CT is released back to VIN) must sit inside the guaranteed window VIL max .. VIH min
    for nm, v in (("ON rising trip", r["vrise"]), ("ON falling trip", r["vfall"])):
        check(f"{nm} model @{vin} V", v, SW_VIL_MAX, SW_VIH_MIN, "V", f"{DS_SW} Table 7.3 VIL max / VIH min")


# ======================================================================================== helpers on waveforms
def first_cross(t, v, level, rising=True, after=0.0):
    """Time of the first crossing of `level` after `after` (linear interpolation), or None."""
    for i in range(1, len(t)):
        if t[i] < after:
            continue
        a, b = v[i - 1], v[i]
        if (rising and a < level <= b) or (not rising and a > level >= b):
            return t[i - 1] + (level - a) * (t[i] - t[i - 1]) / (b - a)
    return None


# ======================================================================================== 2. U2 LED rail turn-on
U2_CASES = [(c, 25) for c in CORNERS] + [("bat3.0", -10), ("bat4.2", 60)]


def u2_turn_on(main, base, corner, temp=25, t_on=0.5e-3, stop=8e-3):
    d = Deck(f"U2 turn-on {corner} {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp)
    sense(d, "n_vsys", "n_u2_vin", "n_iu2")               # U2 VIN pin current -> V(n_iu2)
    tps22917(d, main, "U2", vin_node="n_u2_vin")
    led_rail(d, main)
    d += f"VCTL n_ctl_led 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1)"
    d += "VOE n_oe_led 0 1"
    gpio(d, main, "LED_PWR_EN", "n_ctl_led", "n_oe_led")
    d.tran("5u", f"{stop}")
    d.meas(f"tran vsys0 FIND v(n_vsys) AT={t_on * 0.9}")
    d.meas(f"tran vsysmin MIN v(n_vsys) FROM={t_on} TO={stop}")
    d.meas(f"tran iinrush MAX v(n_iu2) FROM={t_on} TO={stop}")
    d.meas(f"tran ibat MAX v(n_ibat) FROM={t_on} TO={stop}")
    d.meas(f"tran vledend FIND v(n_vled) AT={stop}")
    d.wave("v(n_vled)")
    r = run(d, need=("vsys0", "vsysmin", "iinrush", "ibat", "vledend"))
    sane_vsys(r["vsys0"], corner)
    t, v = r["waves"]["time"], r["waves"]["v(n_vled)"]
    r["t10"] = first_cross(t, v, 0.1 * r["vsys0"], after=t_on)
    r["t90"] = first_cross(t, v, 0.9 * r["vsys0"], after=t_on)
    r["t_on"] = t_on
    return r


def sane_vsys(v, corner):
    """Guard against a converged-but-wrong operating point: VSYS before the event must be where the source puts it."""
    c = CORNERS[corner]
    lo, hi = ((min(4.5, c["vbus"]) - 0.2, min(4.5, c["vbus"]) + 0.1) if c["usb"] else (c["vbat"] - 0.2, c["vbat"]))
    if not lo <= v <= hi:
        raise SimulationError(f"VSYS operating point {v} V outside {lo}..{hi} V for {corner}")


def check_u2_turn_on(check, main, r, tag, usb, vbat):
    ton, tr = r["t90"] - r["t_on"], r["t90"] - r["t10"]
    c7 = main.value("C7")
    check(f"U2 tON (ON -> VLED 90 %) {tag}", ton, None, FW_LED_WAIT, "s",
          "docs/architecture.md 7: firmware waits >= 5 ms after LED_PWR_EN (SPEC 5.1 '~4 ms')")
    vin_k = 3.6 if r["vsys0"] < 4.3 else 5.0
    check(f"U2 tR vs Table 7.6 x C7 {tag}", tr, 0.8 * SW_TR_K[vin_k] * c7 / 1e-12, 1.2 * SW_TR_K[vin_k] * c7 / 1e-12,
          "s", f"{DS_SW} Table 7.6 tR {SW_TR_K[vin_k] * 1e6:.1f} us/pF x C7 (+-20 %, VIN {vin_k} V row)")
    check(f"U2 inrush peak {tag}", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    if not usb:
        check(f"battery current peak {tag}", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A setting")
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check(f"+3V3 min during U2 turn-on {tag}", v3, W25_VCC_MIN, None, "V",
          "W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout 0.53 V @ 0.6 A")
    if usb or vbat >= 3.48:
        check(f"+3V3 min vs POFWARN {tag}", v3, POF_LIMIT, None, "V",
              "docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 % (firmware envelope VBAT >= 3.48 V)")
    check(f"VLED settles to VSYS {tag}", r["vledend"], 0.98 * r["vsys0"], None, "V", f"{DS_SW} Table 9-2 ON=H: VOUT = VIN")


@pytest.mark.parametrize("corner,temp", U2_CASES)
def test_u2_turn_on_supply_and_temperature(main, base, check, corner, temp):
    """LED_PWR_EN rises: VLED ramp time, inrush through U2 and the battery, VSYS droop -> +3V3 floor."""
    r = u2_turn_on(main, base, corner, temp)
    c = CORNERS[corner]
    check_u2_turn_on(check, main, r, f"{corner} {temp}C", c["usb"], c["vbat"])


def test_u2_turn_on_tolerance_extremes(main, base, check):
    """C7 (CT) and the bulk C8/C9 at their netlist tolerance corners: slowest tON and largest inrush."""
    worst_ton, worst_i = 0.0, 0.0
    for sc in main.extremes(["C7", "C8", "C9"]):
        scaled(main, sc)
        r = u2_turn_on(main, base, "bat4.2", stop=7e-3)
        main.reset()
        worst_ton = max(worst_ton, r["t90"] - r["t_on"])
        worst_i = max(worst_i, r["iinrush"])
    check("U2 tON worst tolerance corner (C7/C8/C9)", worst_ton, None, FW_LED_WAIT, "s",
          "docs/architecture.md 7: firmware waits >= 5 ms after LED_PWR_EN")
    check("U2 inrush worst tolerance corner (C7/C8/C9)", worst_i, None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")


@pytest.mark.fault
def test_fault_ct_cap_missing_inrush(main, base, check):
    """C7 left off (or tomb-stoned): CT open -> full-speed turn-on into ~49 uF must exceed the switch / BATOCP limit."""
    main.remove("C7")
    r = u2_turn_on(main, base, "bat4.2", stop=3e-3)
    detects(check, "U2 inrush with C7 missing", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    detects(check, "battery current with C7 missing", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A")


# ======================================================================================== 3. U2 off: QOD discharge of VLED
def u2_turn_off(main, base, corner="bat4.2", temp=25, t_off=5e-3, stop=50e-3, ideal_vsys=None, dcbias=False):
    """U2 on, then LED_PWR_EN low at t_off: time until VLED < 10 % (datasheet tFALL end point).
    dcbias=True replaces the VLED capacitors by their Samsung DC-bias / TCC capacitance at `temp`."""
    d = Deck(f"U2 QOD {corner}")
    if ideal_vsys is None:
        vsys_network(d, main, base, corner, temp)
    else:                                                  # fast variant for Monte Carlo
        d += [f"VSYSI n_vsys 0 {ideal_vsys}", f"B3V3 n_p3v3 0 V = min(3.3, V(n_vsys) - {I_3V3 * LDO_RDO:.6g})"]
    tps22917(d, main, "U2")
    led_rail(d, main, dcbias=dict(temp=temp) if dcbias else None)
    d += f"VCTL n_ctl_led 0 PWL(0 0 0.1m 0 0.1001m 1 {t_off} 1 {t_off + 1e-7} 0)"
    d += "VOE n_oe_led 0 1"
    gpio(d, main, "LED_PWR_EN", "n_ctl_led", "n_oe_led")
    d.tran("20u", f"{stop}")
    d.meas(f"tran vled0 FIND v(n_vled) AT={t_off * 0.99}")
    d.wave("v(n_vled)")
    r = run(d, need=("vled0",))
    t, v = r["waves"]["time"], r["waves"]["v(n_vled)"]
    t10 = first_cross(t, v, 0.1 * r["vled0"], rising=False, after=t_off)
    t90 = first_cross(t, v, 0.9 * r["vled0"], rising=False, after=t_off)
    r["t_off10"] = (t10 - t_off) if t10 else float("inf")
    r["tfall"] = (t10 - t90) if (t10 and t90) else float("inf")
    return r


def _cl_vled(main):
    return sum(main.value(r) for r in main.on_net("VLED", "C") if main.fitted(r))


@pytest.mark.parametrize("corner", ["bat3.0", "bat4.2", "usb5.0"])
def test_u2_qod_discharge(main, base, check, corner):
    """LED_PWR_EN low: VLED must be discharged (< 10 %) within the firmware's 30 ms allowance; tFALL vs Eq. 4."""
    r = u2_turn_off(main, base, corner)
    check(f"VLED to 10 % after LED_PWR_EN low {corner}", r["t_off10"], None, FW_LED_OFF, "s",
          "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")
    eq4 = 2.2 * (main.value("R4") + SW_QOD) * _cl_vled(main)
    check(f"tFALL vs SLVSDW8B Eq. 4 {corner}", r["tfall"], 0.85 * eq4, 1.15 * eq4, "s",
          f"{DS_SW} 9.3.3 Eq. 4 tFALL = 2.2 (R4 + QOD 150 Ohm) CL (+-15 % model correlation)")


SAMSUNG_TOL = {"J": 0.05, "K": 0.10, "M": 0.20}   # Samsung CL-series MPN, 9th character = capacitance tolerance


def mpn_tol(main, ref):
    """Tolerance encoded in the part's own MPN field (Samsung CL MLCCs, e.g. CL21A226MAQNNNE -> 'M' = +-20 %),
    else the netlist value-string tolerance (spicelib default)."""
    mpn = main.mpn(ref)
    if mpn.startswith("CL") and len(mpn) > 8 and mpn[8] in SAMSUNG_TOL:
        return SAMSUNG_TOL[mpn[8]]
    return main.tol(ref)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE: the firmware's 30 ms VLED-off allowance has no margin: with C8/C9 at the "
                   "+20 % of their MPN (CL21A226MAQNNNE) the QOD discharge through R4 + 150 R takes ~33 ms to 10 % "
                   "(30.0 ms already at +10 %) (fix: R4 68 R, or a 35 ms firmware wait)")
def test_u2_qod_discharge_tolerance_extremes(main, base, check):
    """C8, C9, R4 at their tolerance corners (MPN tolerance; the 48 x 100 nF at nominal): slowest VLED discharge."""
    refs = ["C8", "C9", "R4"]
    worst = 0.0
    for sc in main.extremes(refs):
        # extremes() uses the value-string tolerance; stretch each corner to the MPN tolerance
        scaled(main, {r: 1 + (k - 1) * mpn_tol(main, r) / main.tol(r) for r, k in sc.items()})
        worst = max(worst, u2_turn_off(main, base, "bat4.2", stop=45e-3, ideal_vsys=4.2)["t_off10"])
        main.reset()
    check("VLED to 10 % worst C8/C9/R4 corner (MPN tolerances)", worst, None, FW_LED_OFF, "s",
          "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'; C8/C9 CL21A226MAQNNNE +-20 %")


@pytest.mark.slow
def test_u2_qod_discharge_monte_carlo(main, base, check):
    """Monte Carlo (200 draws) over every VLED capacitor and R4 within their netlist tolerances."""
    refs = [r for r in main.on_net("VLED", "C") if main.fitted(r)] + ["R4"]
    times = []
    for sc in main.monte_carlo(refs, 200, seed=7):
        scaled(main, sc)
        times.append(u2_turn_off(main, base, stop=40e-3, ideal_vsys=4.2)["t_off10"])
        main.reset()
    times.sort()
    check("VLED to 10 %: Monte Carlo max of 200", times[-1], None, FW_LED_OFF, "s",
          "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")


@pytest.mark.fault
def test_fault_qod_resistor_wrong_value(main, base, check):
    """R4 fitted as 1 k instead of 100 R (a one-digit BOM slip): the discharge must miss the 30 ms allowance."""
    main.override("R4", "1k")
    r = u2_turn_off(main, base, "bat4.2", stop=60e-3, ideal_vsys=4.2)
    detects(check, "VLED to 10 % with R4 = 1k", r["t_off10"], None, FW_LED_OFF, "s",
            "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")


# ======================================================================================== 4. ON pins vs GPIO, reset
@pytest.mark.parametrize("corner", ["bat3.0", "bat4.2"])
def test_on_pins_vs_gpio_levels(main, base, check, corner):
    """ON levels for both switches with the nRF pin driven high (min drive), low, and released (reset, leakage)."""
    out = {}
    for state, (ctl, oe, leak) in {"high": (1, 1, 0.0), "low": (0, 1, 0.0), "reset": (0, 0, 1e-6)}.items():
        d = Deck(f"ON pins {state} {corner}")
        vsys_network(d, main, base, corner)
        tps22917(d, main, "U2")
        tps22917(d, main, "U21")
        d += main.passives(nets={"LED_PWR_EN", "OLED_VCC_EN", "GND"})
        d += [f"VCTL n_ctl 0 {ctl}", f"VOE n_oe 0 {oe}"]
        # min drive (largest output resistance) and +1 uA sourcing pad leakage in reset: worst for each level
        gpio(d, main, "LED_PWR_EN", "n_ctl", "n_oe", rout=ROUT["sd_min"], ileak=leak)
        gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe", rout=ROUT["sd_min"], ileak=leak)
        d.op()
        d.print_op(f"v({main.node('LED_PWR_EN')})", f"v({main.node('OLED_VCC_EN')})", "v(n_p3v3)")
        r = run(d, need=("op_0", "op_1"))
        out[state] = (r["op_0"], r["op_1"])
    src_hi = f"{DS_SW} Table 7.3 VIH 1.0..5.5 V; {DS_NRF} VOH (IOH,SD min)"
    src_lo = f"{DS_SW} Table 7.3 VIL max 0.35 V"
    for i, ref in enumerate(("U2", "U21")):
        check(f"{ref} ON driven high {corner}", out["high"][i], SW_VIH_MIN, SW_VIH_MAX, "V", src_hi)
        check(f"{ref} ON driven low {corner}", out["low"][i], None, SW_VIL_MAX, "V", src_lo)
        check(f"{ref} ON in MCU reset (+1 uA leak, ASSUMED) {corner}", out["reset"][i], None, SW_VIL_MAX, "V",
              src_lo + "; R3/R25 pull-down; nRF pad leakage not specified -> 1 uA assumed")


def mcu_reset(main, base, stop=40e-3, t_rst=6e-3, leak=100e-9):
    """Both rails on, then the MCU resets at t_rst (pads released, small sourcing leakage): do both switches open?"""
    d = Deck("MCU reset")
    vsys_network(d, main, base, "bat4.2")
    tps22917(d, main, "U2")
    led_rail(d, main)
    tps22917(d, main, "U21")
    oled_input(d, main, boost=False)          # only U21's ON/OFF state matters here
    d += ["VCTL n_ctl 0 PWL(0 0 0.1m 0 0.1001m 1)", f"VOE n_oe 0 PWL(0 1 {t_rst} 1 {t_rst + 1e-7} 0)"]
    gpio(d, main, "LED_PWR_EN", "n_ctl", "n_oe", ileak=leak)
    gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe", ileak=leak)
    d.tran("20u", f"{stop}")
    d.meas(f"tran vled0 FIND v(n_vled) AT={t_rst * 0.99}")
    d.meas(f"tran von2 FIND v({main.node('LED_PWR_EN')}) AT={stop}")
    d.meas(f"tran von21 FIND v({main.node('OLED_VCC_EN')}) AT={stop}")
    d.wave("v(n_vled)")
    r = run(d, need=("vled0", "von2", "von21"))
    t, v = r["waves"]["time"], r["waves"]["v(n_vled)"]
    t10 = first_cross(t, v, 0.1 * r["vled0"], rising=False, after=t_rst)
    r["t_off10"] = (t10 - t_rst) if t10 else float("inf")
    return r


def test_mcu_reset_turns_both_rails_off(main, base, check):
    """Through an MCU reset the pull-downs (not the TPS22917 smart pull-down, which is disconnected once ON was high)
    must take both ON pins below VIL and the LED rail must discharge within the 30 ms allowance."""
    r = mcu_reset(main, base)
    check("U2 ON after MCU reset (100 nA leak, ASSUMED)", r["von2"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    check("U21 ON after MCU reset (100 nA leak, ASSUMED)", r["von21"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    check("VLED to 10 % after MCU reset", r["t_off10"], None, FW_LED_OFF, "s",
          "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")


@pytest.mark.fault
def test_fault_on_pulldown_missing_in_reset(main, base, check):
    """R3 left off: after ON was driven high the TPS22917 smart pull-down is disconnected (Table 9-1), so a released
    pad with any sourcing leakage keeps the LED rail on through reset."""
    main.remove("R3")
    r = mcu_reset(main, base, stop=30e-3)
    detects(check, "U2 ON after MCU reset with R3 missing", r["von2"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    detects(check, "VLED to 10 % after reset with R3 missing", r["t_off10"], None, FW_LED_OFF, "s",
            "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")


# ======================================================================================== 5. phantom powering via LED_DIN
def phantom_op(main, base, corner="bat4.2", temp=25, rout=ROUT["hd_max"], esd=None):
    """U2 off (LED_PWR_EN low, QOD active), P0.06 driven HIGH: clamp current into D101.DIN and the VLED it builds."""
    d = Deck(f"phantom {corner} {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp)
    tps22917(d, main, "U2")
    led_rail(d, main, esd=esd)
    d += main.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN", "GND"})
    d += ["VCTL0 n_ctl0 0 0", "VCTL1 n_ctl1 0 1", "VOE n_oe 0 1"]
    gpio(d, main, "LED_PWR_EN", "n_ctl0", "n_oe")
    gpio(d, main, "LED_DIN_MCU", "n_ctl1", "n_oe", rout=rout)
    d.op()
    n_mcu, n_r, n_din = main.node("LED_DIN_MCU"), main.node("LED_DIN_R"), main.node("LED_DIN")
    d.print_op(f"v({n_mcu})", f"v({n_r})", f"v({n_din})", "v(n_vled)", "v(n_vsys)")
    r = run(d, need=("op_0", "op_1", "op_2", "op_3"))
    r["i_din"] = (r["op_0"] - r["op_1"]) / main.value("R40") - r["op_1"] / main.value("R41")
    r["vi_over_vdd"] = r["op_2"] - r["op_3"]
    r["vled"] = r["op_3"]
    return r


@pytest.mark.parametrize("corner,temp", [("bat4.2", 25), ("bat3.0", -10), ("usb5.0", 60)])
def test_phantom_vled_and_din_current(main, base, check, corner, temp):
    """Firmware fault: P0.06 high (high drive, strongest pad) while VLED is off.  The 220 R limits the clamp current
    and U2's QOD (R4 + 150 R) holds VLED down; VLED must stay far below the LED supply range."""
    r = phantom_op(main, base, corner, temp)
    check(f"phantom VLED (P0.06 high, U2 off) {corner} {temp}C", r["vled"], None, WS_VDD_MIN, "V",
          f"{DS_WS} p.2 VDD 3.3 V min (ring must not be phantom-powered into operation)")
    check(f"DIN clamp current (record) {corner} {temp}C", r["i_din"], None, None, "A",
          "informational: (V(P0.06) - V(LED_DIN_R))/R40 - V(LED_DIN_R)/R41")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE: with P0.06 high and VLED off, R40 = 220 R lets ~5 mA into D101's DIN clamp, "
                   "which then sits more than 0.7 V above VLED (WS2812C abs max VI <= VDD + 0.7 V); only firmware "
                   "prevents it (fit the DNP U43 SN74LV1T34 + C43 and remove R43, see design_findings)")
@pytest.mark.parametrize("corner,temp", [("bat4.2", 25), ("bat3.0", -10)])
def test_phantom_din_abs_max(main, base, check, corner, temp):
    r = phantom_op(main, base, corner, temp)
    check(f"DIN - VDD with P0.06 high, VLED off {corner} {temp}C", r["vi_over_vdd"], None, WS_VI_OVER_VDD, "V",
          f"{DS_WS} p.2 abs max VI <= VDD + 0.7 V (clamp I-V ASSUMED generic Si, IS 1e-14)")


def test_phantom_normal_off_state(main, base, check):
    """Normal sequence (firmware drives P0.06 low before LED_PWR_EN low): VLED and DIN stay at ground."""
    d = Deck("LED rail off, DIN low")
    vsys_network(d, main, base, "bat4.2")
    tps22917(d, main, "U2", isd_out=SW_ISD_MAX_85C)
    led_rail(d, main)
    d += main.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN", "GND"})
    d += ["VCTL0 n_ctl0 0 0", "VOE n_oe 0 1"]
    gpio(d, main, "LED_PWR_EN", "n_ctl0", "n_oe")
    gpio(d, main, "LED_DIN_MCU", "n_ctl0", "n_oe")
    d.op()
    d.print_op("v(n_vled)", f"v({main.node('LED_DIN')})")
    r = run(d, need=("op_0", "op_1"))
    check("VLED off (ISD max leaking into VOUT)", r["op_0"], None, 0.1 * 4.2, "V",
          f"{DS_SW} Table 9-2 ON=L + QOD: VOUT = GND; Table 7.5 ISD 100 nA max; 10 % = tFALL end point")
    check("LED_DIN with P0.06 low", r["op_1"], None, 0.7, "V", f"{DS_WS} p.3 VIL max 0.7 V")


# ======================================================================================== 6. U21 OLED boost input turn-on
U21_CASES = [(c, 25) for c in ("bat3.0", "bat3.7", "bat4.2", "usb4.5", "usb5.5")] + [("bat3.0", -10)]


def u21_turn_on(main, base, corner, temp=25, t_on=0.2e-3, stop=7e-3):
    d = Deck(f"U21 turn-on {corner} {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp)
    sense(d, "n_vsys", "n_u21_vin", "n_iu21")
    tps22917(d, main, "U21", vin_node="n_u21_vin")
    oled_input(d, main)
    d += [f"VCTL n_ctl 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1)", "VOE n_oe 0 1"]
    gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe")
    d.tran("2u", f"{stop}")
    d.meas(f"tran vsys0 FIND v(n_vsys) AT={t_on * 0.9}")
    d.meas(f"tran vsysmin MIN v(n_vsys) FROM={t_on} TO={stop}")
    d.meas(f"tran iinrush MAX v(n_iu21) FROM={t_on} TO={stop}")
    d.meas(f"tran ibat MAX v(n_ibat) FROM={t_on} TO={stop}")
    d.meas(f"tran v13end FIND v({main.node('+13V_OLED')}) AT={stop}")
    d.meas(f"tran vinend FIND v({main.node('OLED_VIN')}) AT={stop}")
    d.wave(f"v({main.node('OLED_VIN')})", "v(n_iu21)", "v(n_u21_vin)")
    r = run(d, need=("vsys0", "vsysmin", "iinrush", "ibat", "v13end", "vinend"))
    sane_vsys(r["vsys0"], corner)
    w = r["waves"]
    t, v = w["time"], w[f"v({main.node('OLED_VIN')})"]
    r["t90"] = first_cross(t, v, 0.9 * r["vsys0"], after=t_on)
    r["t10"] = first_cross(t, v, 0.1 * r["vsys0"], after=t_on)
    r["t_on"] = t_on
    # energy dissipated in U21 during the ramp: (VIN - VOUT) * I
    e = 0.0
    for i in range(1, len(t)):
        p0 = (w["v(n_u21_vin)"][i - 1] - v[i - 1]) * w["v(n_iu21)"][i - 1]
        p1 = (w["v(n_u21_vin)"][i] - v[i]) * w["v(n_iu21)"][i]
        e += 0.5 * (p0 + p1) * (t[i] - t[i - 1])
    r["e_u21"] = e
    return r


@pytest.mark.parametrize("corner,temp", U21_CASES)
def test_u21_turn_on_with_boost_start(main, base, check, corner, temp):
    """OLED_VCC_EN rises: OLED_VIN ramp, then the TPS61040 (EN tied to OLED_VIN) starts at its UVLO while U21 is still
    ramping, so the U21 inrush is the boost's soft-start current, not C x dV/dt."""
    r = u21_turn_on(main, base, corner, temp)
    tag = f"{corner} {temp}C"
    c = CORNERS[corner]
    check(f"U21 tON (ON -> OLED_VIN 90 %) {tag}", r["t90"] - r["t_on"], None, FW_OLED_WAIT, "s",
          "docs/architecture.md 7: 'set OLED_VCC_EN, wait >= 200 ms, then AFh'")
    c37 = main.value("C37")
    vin_k = 3.6 if r["vsys0"] < 4.3 else 5.0
    check(f"U21 tR vs Table 7.6 x C37 {tag}", r["t90"] - r["t10"], 0.8 * SW_TR_K[vin_k] * c37 / 1e-12,
          1.2 * SW_TR_K[vin_k] * c37 / 1e-12, "s",
          f"{DS_SW} Table 7.6 tR {SW_TR_K[vin_k] * 1e6:.1f} us/pF x C37 (+-20 %, VIN {vin_k} V row)")
    check(f"U21 inrush peak (boost soft start) {tag}", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    check(f"U21 energy during the ramp (record) {tag}", r["e_u21"], None, None, "J",
          "informational: no SOA / transient thermal data in SLVSDW8B")
    if not c["usb"]:
        check(f"battery current peak, OLED on {tag}", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A setting")
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check(f"+3V3 min during U21 turn-on {tag}", v3, W25_VCC_MIN, None, "V",
          "W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout 0.53 V @ 0.6 A")
    if c["usb"] or c["vbat"] >= 3.48:
        check(f"+3V3 min vs POFWARN, OLED on {tag}", v3, POF_LIMIT, None, "V",
              "docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 % (firmware envelope VBAT >= 3.48 V)")
    check(f"OLED_VIN within TPS61040 VIN range after the ramp {tag}", r["vinend"], 1.8, 6.0, "V",
          f"{DS_BST} Table 5.3 VIN 1.8..6 V")


# ======================================================================================== 7. U21 off: back-powering
def u21_off_state(main, base, temp, panel_esd=True, stop=20.0, isd_out=None, v13_0=0.0):
    """U21 off (OLED_VCC_EN low), +3V3 up.  Paths into OLED_VIN / +13V_OLED: U21 off-state leakage (VIN->VOUT),
    the SSD1351 VCI/VDDIO->VCC ESD path, then D21 reverse leakage from +13V_OLED back into OLED_VIN (QOD open)."""
    d = Deck(f"U21 off {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, "bat3.7", temp)
    isd = isd_out if isd_out is not None else (SW_ISD_MAX_85C if temp > 25 else 10e-9)
    tps22917(d, main, "U21", isd_out=isd)
    oled_input(d, main, panel_esd=panel_esd)
    d += ["VCTL n_ctl 0 0", "VOE n_oe 0 1"]
    gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe")
    n13, nin, nfb = main.node("+13V_OLED"), main.node("OLED_VIN"), main.node("OLED_BST_FB")
    # start with OLED_VIN held at 0 V for the operating point (.ic, released at t = 0), as after a power-up with
    # the OLED left off; at 60 C the boost would hiccup around its UVLO, so there is no free DC operating point
    d += f".ic v({nin})=0" + (f" v({n13})={v13_0}" if v13_0 else "")
    d.tran(f"{stop / 2000:.3g}", f"{stop}")
    d.meas(f"tran vin_end FIND v({nin}) AT={stop}")
    d.meas(f"tran vin_max MAX v({nin})")
    d.meas(f"tran v13_end FIND v({n13}) AT={stop}")
    d.meas(f"tran vfb_end FIND v({nfb}) AT={stop}")
    return run(d, need=("vin_end", "vin_max", "v13_end", "vfb_end"))


def test_u21_off_leakage_alone_keeps_boost_off(main, base, check):
    """Without the panel's ESD path, U21's worst-case off leakage (ISD max) alone cannot enable the boost."""
    r = u21_off_state(main, base, 60, panel_esd=False, stop=10.0)
    check("OLED_VIN, U21 off, ISD max, no panel path, 60 C", r["vin_max"], None, BST_EN_VIL, "V",
          f"{DS_BST} Table 5.5 EN VIL max 0.4 V (EN tied to VIN) / {DS_SW} Table 7.5 ISD 100 nA max")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE: with OLED_VCC_EN low, the SSD1351 VCI->VCC ESD path holds "
                   "+13V_OLED near +3V3 and D21's reverse leakage then charges the floating OLED_VIN (U21 QOD open) "
                   "above the TPS61040 EN VIL max (EN tied to VIN): the boost is not guaranteed off and draws IQ "
                   "from +3V3 (fix: tie U21 QOD to OLED_VIN, see design_findings)")
@pytest.mark.parametrize("temp", [-10, 25, 60])
def test_u21_off_backpower_via_panel_and_d21(main, base, check, temp):
    # D21 leakage charges C38 at roughly 0.2 / 1 / 6 V/s at -10 / 25 / 60 C: simulate long enough to settle or to
    # reach the boost UVLO region (where it would start hiccuping), not longer
    r = u21_off_state(main, base, temp, panel_esd=True, stop={-10: 8.0, 25: 3.0, 60: 0.25}[temp])
    check(f"+13V_OLED held by the panel ESD path (record) {temp}C", r["v13_end"], None, None, "V",
          "SSD1351 Rev 1.3 8.9 Note (1)")
    check(f"FB - OLED_VIN with OLED off {temp}C", r["vfb_end"] - r["vin_end"], None, BST_FB_OVER_VIN, "V",
          f"{DS_BST} Table 5.1 abs max FB <= VIN + 0.3 V")
    check(f"OLED_VIN with OLED off (boost EN = VIN) {temp}C", r["vin_max"], None, BST_EN_VIL, "V",
          f"{DS_BST} Table 5.5 EN VIL max 0.4 V (EN tied to VIN): boost guaranteed off")


# ======================================================================================== 8. DC load extremes
N_LEDS_FULL_A = 48 * 3 * 5e-3     # A, 48 pixels x 3 channels x 5 mA (WS2812C DS p.1) = hardware maximum


def _ron_max(vin, temp_row):
    """Table 7.5 RON max, linear in VIN between the 3.6 V and 5 V rows (clamped outside)."""
    a, b = SW_RON_MAX[3.6][temp_row], SW_RON_MAX[5.0][temp_row]
    x = min(max((vin - 3.6) / 1.4, 0.0), 1.0)
    return a + (b - a) * x


def led_dc(main, base, corner, temp, i_led, ron_add=0.0, vsysreg=4.5):
    d = Deck(f"LED DC {corner} {temp}C {i_led} A")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp, vsysreg=vsysreg)
    sense(d, "n_vsys", "n_u2_vin", "n_iu2")
    tps22917(d, main, "U2", ron_add=ron_add, vin_node="n_u2_vin")
    led_rail(d, main, duty=i_led / N_LEDS_FULL_A)
    d += ["VCTL n_ctl 0 1", "VOE n_oe 0 1"]
    gpio(d, main, "LED_PWR_EN", "n_ctl", "n_oe")
    d.op()
    d.print_op("v(n_u2_vin)", "v(n_vled)", "v(n_iu2)", "v(n_ibat)")
    r = run(d, need=("op_0", "op_1", "op_2", "op_3"))
    r["vin"], r["vled"], r["i"], r["ibat"] = r["op_0"], r["op_1"], r["op_2"], r["op_3"]
    r["ron"] = (r["vin"] - r["vled"]) / max(r["i"], 1e-9)
    return r


@pytest.mark.parametrize("corner,vsysreg", [("usb5.0", 4.5 * 1.02), ("bat4.2", 4.5)])
def test_u2_full_white_thermal(main, base, check, corner, vsysreg):
    """Hardware-maximum ring current (full white, no firmware cap) at 60 C ambient with RON at its 85 C maximum."""
    ta = 60
    r0 = led_dc(main, base, corner, ta, N_LEDS_FULL_A, vsysreg=vsysreg)
    ron_t = _ron_max(r0["vin"], 85)
    r = led_dc(main, base, corner, ta, N_LEDS_FULL_A, ron_add=max(0.0, ron_t - r0["ron"]), vsysreg=vsysreg)
    p = r["i"] ** 2 * r["ron"]
    check(f"U2 current, full white {corner}", r["i"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    check(f"U2 TJ at 60 C ambient, full white {corner}", ta + p * SW_THETA_JA, None, SW_TJMAX, "C",
          f"{DS_SW} Table 7.1 TJ max 125 C; Table 7.4 theta-JA 183 C/W; Table 7.5 RON max 85 C row")
    r_nl = led_dc(main, base, corner, ta, 0.0, vsysreg=vsysreg)
    check(f"VLED max, no load (VSYS_REG +2 %) {corner}", r_nl["vled"], None, WS_VDD_MAX, "V",
          f"{DS_WS} p.2 VDD 5.3 V max; {DS_BQ} VSYS_REG accuracy +2 %")
    if not CORNERS[corner]["usb"]:
        check(f"battery current, full white {corner}", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A")


@pytest.mark.parametrize("vbat,i_led,temp", [(3.53, 0.100, 25), (3.53, 0.100, -10), (3.65, 0.300, -10)])
def test_vled_at_firmware_led_floor(main, base, check, vbat, i_led, temp):
    """Lowest battery at which firmware still lights the ring (docs/firmware.md LED derating: < 3.60 V -> 100 mA cap,
    < 3.53 V -> off; >= 3.65 V -> 300 mA bursts): VLED under that load must stay in the WS2812C supply range."""
    CORNERS["_floor"] = dict(usb=0, vbat=vbat, vbus=0.0)
    try:
        r0 = led_dc(main, base, "_floor", temp, i_led)
        r = led_dc(main, base, "_floor", temp, i_led, ron_add=max(0.0, _ron_max(r0["vin"], 25) - r0["ron"]))
    finally:
        CORNERS.pop("_floor")
    check(f"VLED at VBAT {vbat} V rested, {i_led * 1e3:.0f} mA, {temp} C", r["vled"], WS_VDD_MIN, None, "V",
          f"{DS_WS} p.2 VDD 3.3 V min; docs/firmware.md LED derating table; {DS_SW} Table 7.5 RON max")


def test_u21_off_whatif_qod_tied_to_vout(main, base, check):
    """WHAT-IF (not in the netlist): U21 pin 5 (QOD) tied to OLED_VIN, the fix proposed for the back-power issue.
    The internal 150 R then holds OLED_VIN near 0 V while U21 is off, and FB stays within VIN + 0.3 V."""
    for temp in (25, 60):
        d = Deck(f"U21 off, QOD tied, {temp}C")
        d += f".temp {temp}"
        vsys_network(d, main, base, "bat3.7", temp)
        tps22917(d, main, "U21", isd_out=SW_ISD_MAX_85C if temp > 25 else 10e-9)
        oled_input(d, main, panel_esd=True)
        d += f"RWHATIF_QOD {main.pin('U21', 'QOD')} {main.node('OLED_VIN')} 1m"
        d += ["VCTL n_ctl 0 0", "VOE n_oe 0 1"]
        gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe")
        d.op()
        d.print_op(f"v({main.node('OLED_VIN')})", f"v({main.node('OLED_BST_FB')})")
        r = run(d, need=("op_0", "op_1"))
        check(f"WHAT-IF QOD tied: OLED_VIN with OLED off {temp}C", r["op_0"], None, BST_EN_VIL, "V",
              f"{DS_BST} Table 5.5 EN VIL max 0.4 V (EN tied to VIN)")
        check(f"WHAT-IF QOD tied: FB - OLED_VIN {temp}C", r["op_1"] - r["op_0"], None, BST_FB_OVER_VIN, "V",
              f"{DS_BST} Table 5.1 abs max FB <= VIN + 0.3 V")


def test_phantom_clamp_sensitivity(main, base, check):
    """Record how the DIN-over-VDD result depends on the (unspecified) WS2812C clamp I-V: strong / nominal / weak."""
    for tag, esd in (("strong clamp IS 1e-13 RS 0", {"is": 1e-13, "rs": 0.0}), ("nominal IS 1e-14 RS 10", None),
                     ("weak clamp IS 1e-15 RS 20", {"is": 1e-15, "rs": 20.0})):
        r = phantom_op(main, base, "bat4.2", 25, esd=esd)
        check(f"DIN - VDD, P0.06 high, VLED off, {tag} (record)", r["vi_over_vdd"], None, None, "V",
              f"informational bracket for the xfail above; {DS_WS} gives no clamp I-V")
