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
Added by the independent verifier: MLCC DC-bias / TCC (Samsung curves) on the VLED discharge worst case, the
BQ25180 BUVLO at the 3.465 V true-cell firmware floor (incl. an OLED turn-on during a motor move), the OLED turn-on on
USB with a dead battery at the 100 mA input limit, and fault tests for CT bridged / a decade off and R25 left off.

Firmware-dependent strict xfails keep the OLD firmware behaviour as the evidence for a rule (test_phantom_din_abs_max:
LSW-3; test_u21_turn_on_dead_battery_usb_100ma: NEW-1 / OLED-V1).  Each has a companion *_with_fw_rule guard that runs
the same deck and corners with the rule as docs/firmware.md states it and asserts the same datasheet limit.
"""

from __future__ import annotations

import re
import subprocess

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
BQ_BUVLO = 3.0          # V, VBUVLO setting 3.0 V (CHARGECTRL1 0x92), SLUSE99C Table 7.5; tBUVLO 60 us, Table 7.6
# docs/firmware.md 12.4 (VSENSE-1/4/5, rule R1'): the calibrated VSYS reading has a gain error that grows with VSYS (up
# to about 2.0-2.1 % HIGH, aged unit at -10/60 C: 67.9 mV at a true 3.21 V, 71.4 mV at 3.465 V, 72.3 mV at 3.53 V,
# 79.6 mV at 3.90 V).  Every firmware threshold that protects a datasheet limit compares a TRUE-cell value against
# VBAT_est = VREAD_GAIN x calibrated reading, which covers an over-read of up to 1 - VREAD_GAIN = 2.1 % of the reading
# (test_vsys_sense.py::test_read_margin_covers_over_read_with_fw_rule: VREAD_GAIN x reading <= true at every threshold
# and corner), so a threshold T on VBAT_est (a reading of T / VREAD_GAIN) admits a true cell as low as T; the guards
# run the cell at VBAT_est itself (cell = VREAD_GAIN x reading), the lowest the rule admits.  It replaces the flat
# VBAT_est = reading - 75 mV, which covered the over-read only up to a true 3.72 V.
VREAD_GAIN = 0.979
# V, lowest TRUE rested cell voltage at which firmware still switches the rails: docs/firmware.md 12.4 enters SHIP
# when VBAT_est < 3.465 V (VBATPOR max 3.46 V + 5 mV), i.e. below a 3.465 / VREAD_GAIN = 3.5393 V reading -> cell =
# VREAD_GAIN x reading = 3.465 V (it was 3.48 V = a 3.53 V reading - 46 mV under the former +-46 mV drift budget;
# the lower floor is stricter for the BUVLO and QOD-discharge checks that start from it).  The LEDs are off except
# the <= 2 mA red cue below VBAT_est 3.53 V (docs/firmware.md 6.3).
FW_VBAT_FLOOR = 3.465
WS_VDD_MIN, WS_VDD_MAX = 3.3, 5.3      # V, WS2812C-2020-V6 DS p.2 supply range
WS_VI_OVER_VDD = 0.7    # V, WS2812C-2020-V6 DS p.2 abs max VI <= VDD + 0.7 V
W25_VCC_MIN = 2.7       # V, W25Q128JV DS VCC min (lowest +3V3 consumer, docs/architecture.md section 7 table)
POF_LIMIT = 2.9 * 1.05  # V, firmware POFWARN 2.9 V (docs/firmware.md fault table) + VPOFTOL +5 % (nRF52840 PS v1.1 5.3.8.4)
# s, POF blanking (docs/firmware.md 12.4, R8): firmware ignores POFWARN for this long after raising OLED_VCC_EN or
# LED_PWR_EN, so +3V3 may dip below POF_LIMIT (never below VBOR / the W25Q128 2.7 V) only inside that window.  The
# rule as proposed said 5 ms; the dead-battery charging cue at ILIM 80 mA min / SYS_REG 4.312 V keeps +3V3 below
# POF_LIMIT until 5.82 ms after LED_PWR_EN, so the guards use 10 ms (= the >= 10 ms LED-DATA-V4 / OLED-V2 waits).
FW_POF_BLANK = 10e-3
BST_EN_VIL = 0.4        # V, TPS61040 Table 5.5 EN VIL max (EN is tied to VIN = OLED_VIN)
BST_FB_OVER_VIN = 0.3   # V, TPS61040 Table 5.1 abs max FB <= VIN + 0.3 V
# s, U2 tON budget of the passing turn-on checks: the former firmware LED wait (architecture.md 7 said "wait >= 5 ms"
# before LED-DATA-V4); SPEC 5.1 gives tON ~3.8-4.0 ms.  Kept at 5 ms: FW_LED_WAIT (10 ms) would loosen those checks.
U2_TON_MAX = 5e-3
FW_LED_WAIT = 10e-3     # s, docs/firmware.md 6.4 / SPEC 5.4 / architecture.md 7: after LED_PWR_EN high, wait >= 10 ms
                        # with P0.06 low before DIN goes high (LED-DATA-V4)
# V, LED-DATA-V4 (R9): VLED >= 2.67 V before the first LED frame, the level consistent with the WS2812C abs max
# VI <= VDD + 0.7 V when DIN goes high to +3V3 at its maximum (RT9080 3.3 V +2 % = 3.366 V); was "2.5 V".
FW_VLED_FRAME_MIN = 2.67
V3V3_MAX = 3.3 * 1.02   # V, RT9080-33 DS9080-09 VOUT accuracy +2 % (P0.06 high level = +3V3)
FW_LED_OFF = 30e-3      # s, docs/architecture.md section 7: "allow >= 30 ms for the QOD discharge"
# s, docs/firmware.md 3.1 oled_vcc startup-delay-us / 7.2 step 23: the 200 ms VCC-to-AFh wait may be shortened but MUST
# never be below 10 ms, and its first 10 ms cover U21's tON and the boost soft start (OLED-V2).  The U21 tON check uses
# this floor (tighter than the 200 ms of architecture.md 7 it used before).
FW_OLED_WAIT_MIN = 10e-3

# RT9080 +3V3: dropout <= 0.53 V at 600 mA for VOUT >= 3 V (DS9080-09 Electrical Characteristics) -> 0.88 Ohm;
# +3V3 load 50 mA peak (docs/architecture.md section 7 power tree table).
LDO_RDO, I_3V3 = 0.53 / 0.6, 0.050

# Battery side impedance (cell + PCM + leads) "about 0.25 Ohm of pack plus path resistance" (docs/architecture.md 8.4)
# at 25 C.  ASSUMPTION for temperature: x2 at -10 C, x0.8 at 60 C (generic LiPo DCIR behaviour, no pack datasheet).
RPACK = {-10: 0.50, 25: 0.25, 60: 0.20}
# Link harness (docs/architecture.md 4.2): 2x 28 AWG VSYS wires 8.5 mOhm + 3x GND wires 5.7 mOhm at 80 mm.
R_HARNESS = 8.5e-3 + 5.7e-3

# VSYS corners: battery terminal voltage before the event, or VBUS with the BQ25180 SYS_REG 4.5 V power path (firmware
# writes SYS_REG 0x20 = 4.4 V, docs/firmware.md 13.1; 4.5 V, the POR default, is the only other value it allows).
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


def vsys_network(deck, main, base, corner="bat3.7", temp=25, i3v3=I_3V3, ronbat="55m", ronin="0.27", vsysreg=4.5,
                 i_extra=0.0, ilim=0.475):
    """BQ25180 power path -> base VSYS caps -> link harness -> main-board VSYS caps + always-on +3V3 load.

    Main-board VSYS node is n_vsys; +3V3 is an ideal LDO limited by the RT9080 dropout (n_p3v3).
    i_extra: an additional DC load on VSYS (e.g. the detent motor during a move).
    ilim: BQ25180 input current limit on USB (500 mA code 475 mA typ; 0.1 for the 100 mA code)."""
    if i_extra:
        deck += f"IEXTRA n_vsys 0 DC {i_extra:.6g}"
    c = CORNERS[corner]
    deck.include(LIB_BQ)
    if c["usb"]:
        deck += (f"XBQ n_vsys_b 0 LSW_BQ25180_USB params: vbus={c['vbus']} vbat={c['vbat']} rpack={RPACK[temp]} "
                 f"ronbat={ronbat} ronin={ronin} vsysreg={vsysreg} ilim={ilim:.6g}")
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
    the turn-off edge when a node has no linear capacitance); the rest, C0*(k(V) - kmin), is an E source = its
    normalised charge, a C0 capacitor across it, and that capacitor's current mirrored onto the node by F.
    k(V) - kmin is a degree-6 least-squares polynomial of the curve over 0..6 V (fit error asserted < 0.01 of C0);
    a pwl() charge table makes the capacitance step at every breakpoint and Newton then chatters on a breakpoint."""
    import numpy as np
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
        grid = np.linspace(0.0, 6.0, 121)
        k = np.array([1 + _interp(v, data["dcb"]) / 100 for v in grid])
        kmin = float(k.min())
        p = np.polyfit(grid, k - kmin, 6)
        err = float(np.max(np.abs(np.polyval(p, grid) - (k - kmin))))
        assert err < 0.01, f"DC-bias polynomial fit error {err:.4f} for {members}"
        qpoly = np.polyint(p)                      # normalised charge, Q(0) = 0
        horner = "0"
        for c in qpoly:
            horner = f"({horner})*x + ({c:.9g})"
        out += [f"* DC-bias capacitor group {i}: {' '.join(members)} (C0 {c0:.6g} F at {temp} C, kmin {kmin:.4f}, "
                f"fit error {err:.4f})",
                f".func fdcb{i}(x) = '{horner}'",
                f"CDCBL{i} {a} {b} {c0 * kmin:.6g}",
                f"EDCB{i} n_dcb{i}_q 0 vol = 'fdcb{i}(min(max(V({a},{b}), 0), 6))'",
                f"VDCB{i} n_dcb{i}_q n_dcb{i}_m 0",
                f"RDCB{i} n_dcb{i}_m n_dcb{i}_c {1e-6 / c0:.6g}",      # 1 us lag: an ideal source across C is stiff
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


def oled_input(deck, main, boost=True, panel_esd=False, esd=None):
    """U21's load: C37/C41/C38/R25/L20/D21/output caps/FB divider from the netlist, TPS61040 averaged model
    (boost=False leaves U20 out, for decks that only need the ON/OFF state of U21).
    esd: None (generic panel ESD diode), or dict(is=..., rs=...) for the SSD1351 VCI/VDDIO -> VCC clamp."""
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
        params = (" params: " + " ".join(f"{k}={v:.6g}" for k, v in esd.items())) if esd else ""
        deck += (f"XJ20 {spicelib.node_name(vci)} {spicelib.node_name(vddio)} {spicelib.node_name(vcc)} 0 "
                 f"LSW_SSD1351_ESD{params}")
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


NUMERIC_FALLBACKS = (["option reltol=1e-3"], ["option reltol=1e-3", "option method=gear", "option rshunt=1e12"])


def run(deck, *, need=(), timeout=90):
    # The TPS22917 macro-model's logic edges can stall ngspice's step control at a switching instant ("Timestep too
    # small", or a hang) for some otherwise harmless loads, e.g. with the DNP C43 fitted.  Only those two outcomes
    # trigger a retry with looser numerics (reltol 1e-3, then also Gear + rshunt 1e12); every other error, and any
    # error of the last attempt, stays fatal.  Normal decks finish in a few seconds, so a 90 s attempt is generous.
    base = [o for o in deck.options if not o.startswith("option reltol")] + \
        [o for o in deck.options if o.startswith("option reltol")]
    res = None
    for extra in ([],) + NUMERIC_FALLBACKS:
        deck.options = ([o for o in base if not (extra and o.startswith("option reltol"))] + extra)
        try:
            res = deck.run(timeout=timeout)
        except subprocess.TimeoutExpired:
            res = None
            continue
        if not any(re.search(r"(?i)timestep too small", e) for e in res["_errors"]):
            break
    if res is None:
        raise SimulationError(f"ngspice did not finish in {timeout} s, also with the numerical fallbacks")
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


def u2_turn_on(main, base, corner, temp=25, t_on=0.5e-3, stop=8e-3, extra_waves=()):
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
    d.meas(f"tran vbatmin MIN v(xbq.bat) FROM={t_on} TO={stop}")
    d.meas(f"tran vledend FIND v(n_vled) AT={stop}")
    d.wave("v(n_vled)", *extra_waves)
    r = run(d, need=("vsys0", "vsysmin", "iinrush", "ibat", "vbatmin", "vledend"))
    sane_vsys(r["vsys0"], corner)
    t, v = r["waves"]["time"], r["waves"]["v(n_vled)"]
    # a rail that never reaches 10 % / 90 % inside the window counts as infinitely slow, so the tON / tR checks
    # report it (a None here used to end the test in a TypeError instead of a check failure)
    r["t10"] = first_cross(t, v, 0.1 * r["vsys0"], after=t_on) or float("inf")
    r["t90"] = first_cross(t, v, 0.9 * r["vsys0"], after=t_on) or float("inf")
    r["t_on"] = t_on
    return r


def _rise(r):
    """(tON, tR) from a turn-on result; tR is inf when the 90 % point was never reached."""
    ton = r["t90"] - r["t_on"]
    tr = r["t90"] - r["t10"] if r["t90"] != float("inf") else float("inf")
    return ton, tr


def sane_vsys(v, corner, slack=0.0, vsysreg=4.5):
    """Guard against a converged-but-wrong operating point: VSYS before the event must be where the source puts it
    (slack: extra allowed drop for decks with an additional VSYS load; vsysreg: the SYS_REG target of the deck)."""
    c = CORNERS[corner]
    vreg = min(vsysreg, c["vbus"])
    lo, hi = ((vreg - 0.2, vreg + 0.1) if c["usb"] else (c["vbat"] - 0.2, c["vbat"]))
    lo -= slack
    if not lo <= v <= hi:
        raise SimulationError(f"VSYS operating point {v} V outside {lo}..{hi} V for {corner}")


def check_u2_turn_on(check, main, r, tag, usb, vbat):
    ton, tr = _rise(r)
    c7 = main.value("C7")
    check(f"U2 tON (ON -> VLED 90 %) {tag}", ton, None, U2_TON_MAX, "s",
          "SPEC 5.1 tON ~3.8-4.0 ms; 5 ms budget = the former firmware wait, half the >= 10 ms wait of "
          "docs/firmware.md 6.4 (LED-DATA-V4)")
    vin_k = 3.6 if r["vsys0"] < 4.3 else 5.0
    check(f"U2 tR vs Table 7.6 x C7 {tag}", tr, 0.8 * SW_TR_K[vin_k] * c7 / 1e-12, 1.2 * SW_TR_K[vin_k] * c7 / 1e-12,
          "s", f"{DS_SW} Table 7.6 tR {SW_TR_K[vin_k] * 1e6:.1f} us/pF x C7 (+-20 %, VIN {vin_k} V row)")
    check(f"U2 inrush peak {tag}", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    if not usb:
        check(f"battery current peak {tag}", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A setting")
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check(f"+3V3 min during U2 turn-on {tag}", v3, W25_VCC_MIN, None, "V",
          "W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout 0.53 V @ 0.6 A")
    if usb or vbat >= FW_VBAT_FLOOR:
        check(f"+3V3 min vs POFWARN {tag}", v3, POF_LIMIT, None, "V",
              f"docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 % (firmware envelope VBAT >= {FW_VBAT_FLOOR} V)")
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
    check("U2 tON worst tolerance corner (C7/C8/C9)", worst_ton, None, U2_TON_MAX, "s",
          "SPEC 5.1 tON ~3.8-4.0 ms; 5 ms budget, half the >= 10 ms wait of docs/firmware.md 6.4 (LED-DATA-V4)")
    check("U2 inrush worst tolerance corner (C7/C8/C9)", worst_i, None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")


@pytest.mark.fault
def test_fault_ct_cap_missing_inrush(main, base, check):
    """C7 left off (or tomb-stoned): CT open -> full-speed turn-on into ~49 uF must exceed the switch / BATOCP limit."""
    main.remove("C7")
    r = u2_turn_on(main, base, "bat4.2", stop=3e-3)
    detects(check, "U2 inrush with C7 missing", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    detects(check, "battery current with C7 missing", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A")


@pytest.mark.fault
def test_fault_ct_bridged_to_vin(main, base, check):
    """Wrong connection: C7's pads bridged (CT tied straight to VIN = VSYS).  The CT ramp can never start, so U2 never
    turns on and the ring stays dark: the tON check against the firmware wait must report it."""
    main.short("C7")
    r = u2_turn_on(main, base, "bat3.7")
    detects(check, "U2 tON with CT bridged to VIN", _rise(r)[0], None, FW_LED_WAIT, "s",
            "docs/firmware.md 6.4: firmware waits >= 10 ms after LED_PWR_EN (LED-DATA-V4)")


@pytest.mark.fault
def test_fault_ct_cap_ten_times_too_big(main, base, check):
    """C7 fitted as 10 nF instead of 1 nF: tON ~ 38 ms, so the first LED frame goes out before VLED is up."""
    main.override("C7", "10n")
    r = u2_turn_on(main, base, "bat3.7")
    detects(check, "U2 tON with C7 = 10n", _rise(r)[0], None, FW_LED_WAIT, "s",
            "docs/firmware.md 6.4: firmware waits >= 10 ms after LED_PWR_EN (LED-DATA-V4)")


@pytest.mark.fault
def test_fault_ct_cap_ten_times_too_small(main, base, check):
    """C7 fitted as 100 pF instead of 1 nF: ~0.9 A inrush into ~49 uF for ~0.2 ms.  The +3V3 floor check of
    test_u2_turn_on_supply_and_temperature at VBAT 3.0 V / -10 C (2.88 V with 1 nF) must catch it.  (Inside the
    firmware envelope, VBAT >= FW_VBAT_FLOOR 3.465 V, the 82 uF of unswitched VSYS bulk absorbs the surge: BAT pin
    ~3.10 V at -10 C > BUVLO.)"""
    main.override("C7", "100p")
    r = u2_turn_on(main, base, "bat3.0", -10)
    detects(check, "+3V3 min during U2 turn-on with C7 = 100p, bat3.0 -10C", min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO),
            W25_VCC_MIN, None, "V", "W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout 0.53 V @ 0.6 A")


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


def test_u2_qod_discharge_tolerance_extremes(main, base, check):
    """Guards fix LSW-2 (R4 100 R -> 68 R): from the 3.465 V firmware floor, with C8/C9 at the +20 % of their MPN
    (CL21A226MAQNNNE), the 48 x 100 nF at +10 % and R4 at +1 %, the QOD discharge through R4 + ~150 R now reaches
    10 % in 26.6 ms (25.7 ms from 4.2 V) incl. the Samsung DC-bias derating, 3.4 ms inside the firmware's 30 ms
    VLED-off allowance (it took ~30.6 ms with 100 R).

    C8, C9, R4 at their tolerance corners (MPN tolerance) with the 48 x 100 nF (one reel) at +10 %, and every VLED
    capacitor at its Samsung DC-bias / TCC capacitance at 25 C (the slowest temperature: TCC < 0 at -10 and 60 C).
    Discharge from the lowest VSYS at which firmware still runs VLED (FW_VBAT_FLOOR 3.465 V true cell: SHIP when
    VBAT_est = 0.979 x reading < 3.465 V, docs/firmware.md 12.4, VSENSE-1/4/5, R1'; 26.59 ms from the former 3.48 V
    floor),
    where the DC-bias derating helps least; the 4.2 V start (most derating) is recorded for the all-plus corner.
    The discharge time is monotonic in every R and C, so the 4.2 V run needs only that corner."""
    small = [r for r in main.on_net("VLED", "C") if main.fitted(r) and r not in ("C8", "C9")]
    src = ("docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'; C8/C9 CL21A226MAQNNNE +-20 %, "
           "C101..C148 CL05B104KO5NNNC +-10 %; Samsung DC-bias/TCC curves")
    worst = 0.0
    for sc in main.extremes(["C8", "C9", "R4"]):
        # extremes() uses the value-string tolerance; stretch each corner to the MPN tolerance
        sc = {r: 1 + (k - 1) * mpn_tol(main, r) / main.tol(r) for r, k in sc.items()}
        sc.update({r: 1 + mpn_tol(main, r) for r in small})
        scaled(main, sc)
        worst = max(worst, u2_turn_off(main, base, stop=45e-3, t_off=8e-3, ideal_vsys=FW_VBAT_FLOOR,
                                       dcbias=True)["t_off10"])
        main.reset()
    plus = {r: 1 + mpn_tol(main, r) for r in ["C8", "C9", "R4"] + small}
    scaled(main, plus)
    t42 = u2_turn_off(main, base, stop=45e-3, t_off=8e-3, ideal_vsys=4.2, dcbias=True)["t_off10"]
    main.reset()
    check("VLED to 10 %, all-plus corner incl. DC bias, from 4.2 V (record)", t42, None, None, "s", src)
    check(f"VLED to 10 %, worst corner incl. DC bias, from the {FW_VBAT_FLOOR} V firmware floor", worst, None,
          FW_LED_OFF, "s", src)


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
    """R4 fitted as 1 k instead of 68 R (a BOM slip): the discharge must miss the 30 ms allowance."""
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
    """Both rails on, then the MCU resets at t_rst (pads released, small sourcing leakage): do both switches open?
    U20 is left out (boost=False): OLED_VIN then discharges through U21's QOD alone (QOD tied to OLED_VIN), the
    slowest case, since a running TPS61040 would only pull it down faster."""
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
    nin = main.node("OLED_VIN")
    d.meas(f"tran vled0 FIND v(n_vled) AT={t_rst * 0.99}")
    d.meas(f"tran vin0 FIND v({nin}) AT={t_rst * 0.99}")
    d.meas(f"tran von2 FIND v({main.node('LED_PWR_EN')}) AT={stop}")
    d.meas(f"tran von21 FIND v({main.node('OLED_VCC_EN')}) AT={stop}")
    d.meas(f"tran vinend FIND v({nin}) AT={stop}")
    d.wave("v(n_vled)", f"v({nin})")
    r = run(d, need=("vled0", "vin0", "von2", "von21", "vinend"))
    t, v = r["waves"]["time"], r["waves"]["v(n_vled)"]
    t10 = first_cross(t, v, 0.1 * r["vled0"], rising=False, after=t_rst)
    r["t_off10"] = (t10 - t_rst) if t10 else float("inf")
    tin = first_cross(t, r["waves"][f"v({nin})"], BST_EN_VIL, rising=False, after=t_rst)
    r["t_vin_off"] = (tin - t_rst) if tin else float("inf")
    return r


def test_mcu_reset_turns_both_rails_off(main, base, check):
    """Through an MCU reset the pull-downs (not the TPS22917 smart pull-down, which is disconnected once ON was high)
    must take both ON pins below VIL and the LED rail must discharge within the 30 ms allowance."""
    r = mcu_reset(main, base)
    check("U2 ON after MCU reset (100 nA leak, ASSUMED)", r["von2"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    check("U21 ON after MCU reset (100 nA leak, ASSUMED)", r["von21"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    check("VLED to 10 % after MCU reset", r["t_off10"], None, FW_LED_OFF, "s",
          "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")
    # LSW-1 / SLP-1: with U21's QOD tied to OLED_VIN the boost input is pulled below the TPS61040 EN VIL (EN = VIN)
    # after a reset as well, so U20 is guaranteed off: 0.8 mV at the end of the window, below 0.4 V 1.6 ms after the
    # reset (before the fix, QOD open, OLED_VIN floated and was still 4.1 V at the end of the window)
    check("OLED_VIN at the end of the window after MCU reset (boost EN = VIN)", r["vinend"], None, BST_EN_VIL, "V",
          f"{DS_BST} Table 5.5 EN VIL max 0.4 V; {DS_SW} Table 9-2 ON=L + QOD: VOUT = GND")
    check("OLED_VIN below EN VIL after MCU reset (record, QOD only, U20 not drawing)", r["t_vin_off"], None, None, "s",
          f"informational: C38 + U21 QOD; OLED_VIN before reset {r['vin0']:.3f} V")


@pytest.mark.fault
def test_fault_on_pulldown_missing_in_reset(main, base, check):
    """R3 left off: after ON was driven high the TPS22917 smart pull-down is disconnected (Table 9-1), so a released
    pad with any sourcing leakage keeps the LED rail on through reset."""
    main.remove("R3")
    r = mcu_reset(main, base, stop=30e-3)
    detects(check, "U2 ON after MCU reset with R3 missing", r["von2"], None, SW_VIL_MAX, "V", f"{DS_SW} Table 7.3 VIL max")
    detects(check, "VLED to 10 % after reset with R3 missing", r["t_off10"], None, FW_LED_OFF, "s",
            "docs/architecture.md 7: 'allow >= 30 ms for the QOD discharge'")


@pytest.mark.fault
def test_fault_oled_on_pulldown_missing_in_reset(main, base, check):
    """R25 left off: the same failure on U21 - the OLED boost input stays connected through an MCU reset."""
    main.remove("R25")
    r = mcu_reset(main, base, stop=30e-3)
    detects(check, "U21 ON after MCU reset with R25 missing", r["von21"], None, SW_VIL_MAX, "V",
            f"{DS_SW} Table 7.3 VIL max")
    detects(check, "OLED_VIN after MCU reset with R25 missing (boost EN = VIN)", r["vinend"], None, BST_EN_VIL, "V",
            f"{DS_BST} Table 5.5 EN VIL max 0.4 V")


# ======================================================================================== 5. phantom powering via LED_DIN
def phantom_op(main, base, corner="bat4.2", temp=25, rout=ROUT["hd_max"], esd=None, din_high=True):
    """U2 off (LED_PWR_EN low, QOD active), P0.06 driven HIGH: clamp current into D101.DIN and the VLED it builds.
    din_high=False drives P0.06 LOW instead, as firmware rule LSW-3 requires while VLED is off."""
    d = Deck(f"phantom {corner} {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp)
    tps22917(d, main, "U2")
    led_rail(d, main, esd=esd)
    d += main.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN", "GND"})
    d += ["VCTL0 n_ctl0 0 0", f"VCTL1 n_ctl1 0 {1 if din_high else 0}", "VOE n_oe 0 1"]
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


PHANTOM_CORNERS = [("bat4.2", 25), ("bat3.0", -10)]


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE (firmware-dependent, LSW-3): with P0.06 high and VLED off, R40 = 220 R lets "
                   "~5 mA into D101's DIN clamp, which then sits more than 0.7 V above VLED (WS2812C abs max VI <= "
                   "VDD + 0.7 V); only the firmware rule of docs/firmware.md 6.4 / SPEC 5.4 prevents it (all-zero "
                   "frame, P0.06 low, then LED_PWR_EN low; never P0.06 high while VLED is off), guarded by "
                   "test_phantom_din_abs_max_with_fw_rule. Fitting the DNP U43 SN74LV1T34 + C43 and removing R43 "
                   "would enforce it in hardware")
@pytest.mark.parametrize("corner,temp", PHANTOM_CORNERS)
def test_phantom_din_abs_max(main, base, check, corner, temp):
    r = phantom_op(main, base, corner, temp)
    check(f"DIN - VDD with P0.06 high, VLED off {corner} {temp}C", r["vi_over_vdd"], None, WS_VI_OVER_VDD, "V",
          f"{DS_WS} p.2 abs max VI <= VDD + 0.7 V (clamp I-V ASSUMED generic Si, IS 1e-14)")


def led_rail_sequence(main, base, corner, temp, wait=FW_LED_WAIT, t_on=0.5e-3, t_frame=5e-3, t_qod=35e-3):
    """The LED rail on/off sequence of docs/firmware.md 6.4 (SPEC 5.4) with P0.06 at its strongest pad (hd_max):
    P0.06 low and VLED off; LED_PWR_EN high at t_on; P0.06 held low for `wait`, then HIGH for t_frame (a DC high
    bounds every frame: the clamp current only grows with the high time); then the off order - the all-zero frame
    ends with P0.06 low, LED_PWR_EN goes low 0.1 ms later - and t_qod of QOD discharge (> the 30 ms firmware wait).
    Returns max(V(LED_DIN) - V(VLED)) over the whole run and VLED at the instant P0.06 first goes high.
    Numerics: the TPS22917 logic edges stall the default step control in this deck (90 s timeouts before the
    fallback), so it starts on run()'s last fallback (reltol 1e-3, Gear, rshunt 1e12); the result is unchanged."""
    t_hi = t_on + wait
    t_lo = t_hi + t_frame
    t_off = t_lo + 0.1e-3
    stop = t_off + t_qod
    d = Deck(f"LED rail sequence {corner} {temp}C, P0.06 high {wait * 1e3:g} ms after LED_PWR_EN")
    d.options = [o for o in d.options if not o.startswith("option reltol")] + NUMERIC_FALLBACKS[-1]
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp)
    tps22917(d, main, "U2")
    led_rail(d, main)
    d += main.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN", "GND"})
    d += [f"VEN n_seq_en 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1 {t_off} 1 {t_off + 1e-7} 0)",
          f"VDIN n_seq_din 0 PWL(0 0 {t_hi} 0 {t_hi + 1e-7} 1 {t_lo} 1 {t_lo + 1e-7} 0)", "VOE n_oe 0 1"]
    gpio(d, main, "LED_PWR_EN", "n_seq_en", "n_oe")
    gpio(d, main, "LED_DIN_MCU", "n_seq_din", "n_oe", rout=ROUT["hd_max"])
    n_din = main.node("LED_DIN")
    d += f"BOVER n_din_over 0 V = V({n_din}) - V(n_vled)"
    d.tran("20u", f"{stop}")
    d.meas("tran overmax MAX v(n_din_over)")
    d.meas(f"tran vled_hi FIND v(n_vled) AT={t_hi}")
    d.meas(f"tran vled_end FIND v(n_vled) AT={stop}")
    r = run(d, need=("overmax", "vled_hi", "vled_end"))
    r["t_hi"], r["t_off"], r["stop"] = t_hi, t_off, stop
    return r


@pytest.mark.parametrize("corner,temp", PHANTOM_CORNERS)
def test_phantom_din_abs_max_with_fw_rule(main, base, check, corner, temp):
    """Guard of firmware rule LSW-3 (with LED-DATA-V4), the companion of the strict xfail test_phantom_din_abs_max:
    same corners, same WS2812C abs-max limit, with the rule applied as docs/firmware.md 1.3 / 6.4 and SPEC 5.4 state
    it.  (1) VLED off: P0.06 driven LOW, never high (the same operating-point deck as the xfail).  (2) The documented
    sequence: LED_PWR_EN high, P0.06 held low >= 10 ms (FW_LED_WAIT, LED-DATA-V4), frames, then all-zero frame,
    P0.06 low, LED_PWR_EN low and the >= 30 ms QOD wait: DIN must never sit more than 0.7 V above VLED."""
    rule = "firmware rule LSW-3 (docs/firmware.md 6.4, SPEC 5.4)"
    src = f"{DS_WS} p.2 abs max VI <= VDD + 0.7 V (clamp I-V ASSUMED generic Si, IS 1e-14); "
    r = phantom_op(main, base, corner, temp, din_high=False)
    check(f"DIN - VDD with P0.06 LOW (rule LSW-3), VLED off {corner} {temp}C", r["vi_over_vdd"], None,
          WS_VI_OVER_VDD, "V", src + rule + ": P0.06 never high while VLED is off")
    s = led_rail_sequence(main, base, corner, temp)
    check(f"VLED when P0.06 first goes high, {FW_LED_WAIT * 1e3:g} ms after LED_PWR_EN {corner} {temp}C",
          s["vled_hi"], FW_VLED_FRAME_MIN, None, "V", f"docs/firmware.md 6.4 / SPEC 5.4: VLED >= {FW_VLED_FRAME_MIN} V "
          "before the first LED frame (LED-DATA-V4, R9; was 2.5 V)")
    check(f"+3V3 max - VLED at the first LED frame, {FW_LED_WAIT * 1e3:g} ms after LED_PWR_EN {corner} {temp}C",
          V3V3_MAX - s["vled_hi"], None, WS_VI_OVER_VDD, "V", src + "DIN high = +3V3 up to 3.3 V +2 % (RT9080 "
          "DS9080-09); LED-DATA-V4 (R9)")
    check(f"VLED {(s['stop'] - s['t_off']) * 1e3:.0f} ms after LED_PWR_EN low (record) {corner} {temp}C",
          s["vled_end"], None, None, "V", "informational: QOD discharge after the documented off order")
    check(f"max(DIN - VDD) over the documented on/off sequence {corner} {temp}C", s["overmax"], None,
          WS_VI_OVER_VDD, "V", src + rule + " + LED-DATA-V4: P0.06 low >= 10 ms after LED_PWR_EN high; all-zero "
          "frame, P0.06 low, then LED_PWR_EN low")


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


def u21_turn_on(main, base, corner, temp=25, t_on=0.2e-3, stop=7e-3, i_extra=0.0, ilim=0.475, step="2u",
                extra_waves=()):
    d = Deck(f"U21 turn-on {corner} {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, corner, temp, i_extra=i_extra, ilim=ilim)
    sense(d, "n_vsys", "n_u21_vin", "n_iu21")
    tps22917(d, main, "U21", vin_node="n_u21_vin")
    oled_input(d, main)
    d += [f"VCTL n_ctl 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1)", "VOE n_oe 0 1"]
    gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe")
    d.tran(step, f"{stop}")
    d.meas(f"tran vsys0 FIND v(n_vsys) AT={t_on * 0.9}")
    d.meas(f"tran vsysmin MIN v(n_vsys) FROM={t_on} TO={stop}")
    d.meas(f"tran iinrush MAX v(n_iu21) FROM={t_on} TO={stop}")
    d.meas(f"tran ibat MAX v(n_ibat) FROM={t_on} TO={stop}")
    d.meas(f"tran vbatmin MIN v(xbq.bat) FROM={t_on} TO={stop}")
    d.meas(f"tran v13end FIND v({main.node('+13V_OLED')}) AT={stop}")
    d.meas(f"tran vinend FIND v({main.node('OLED_VIN')}) AT={stop}")
    d.wave(f"v({main.node('OLED_VIN')})", "v(n_iu21)", "v(n_u21_vin)", *extra_waves)
    r = run(d, need=("vsys0", "vsysmin", "iinrush", "ibat", "vbatmin", "v13end", "vinend"))
    sane_vsys(r["vsys0"], corner, slack=i_extra * (RPACK[temp] + 0.1))
    w = r["waves"]
    t, v = w["time"], w[f"v({main.node('OLED_VIN')})"]
    r["t90"] = first_cross(t, v, 0.9 * r["vsys0"], after=t_on) or float("inf")    # never reached -> inf (see u2)
    r["t10"] = first_cross(t, v, 0.1 * r["vsys0"], after=t_on) or float("inf")
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
    ton, tr = _rise(r)
    check(f"U21 tON (ON -> OLED_VIN 90 %) {tag}", ton, None, FW_OLED_WAIT_MIN, "s",
          "docs/firmware.md 3.1 / 7.2 step 23: VCC-to-AFh wait 200 ms, never below 10 ms; its first 10 ms cover "
          "U21's tON and the boost soft start (OLED-V2)")
    c37 = main.value("C37")
    vin_k = 3.6 if r["vsys0"] < 4.3 else 5.0
    check(f"U21 tR vs Table 7.6 x C37 {tag}", tr, 0.8 * SW_TR_K[vin_k] * c37 / 1e-12,
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
    if c["usb"] or c["vbat"] >= FW_VBAT_FLOOR:
        check(f"+3V3 min vs POFWARN, OLED on {tag}", v3, POF_LIMIT, None, "V",
              f"docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 % (firmware envelope VBAT >= {FW_VBAT_FLOOR} V)")
    check(f"OLED_VIN within TPS61040 VIN range after the ramp {tag}", r["vinend"], 1.8, 6.0, "V",
          f"{DS_BST} Table 5.3 VIN 1.8..6 V")


NRF_VBOR_ON_MIN = 1.57   # V, nRF52840 PS v1.1 5.3 VBOR,ON (System ON brown-out reset) 1.57 / 1.60 / 1.63 V
BQ_ILIM_100 = 0.100      # A, BQ25180 SLUSE99C Table 8-17 ILIM code 001 = "100 mA (max.)"; TMR_ILIM 0xC9
BQ_ILIM_100_MIN = 0.080  # A, ILIM 100 mA code minimum (SLUSE99C 7.5; docs/firmware.md 6.3 "ILIM minimum (80 / 450 mA)")
BQ_ILIM_500_MIN = 0.450  # A, ILIM code 101 (TMR_ILIM 0xCD) 450 / 475 / 498 mA min/typ/max (docs/firmware.md 13.1)
BQ_SYSREG_FW = 4.4       # V, SYS_REG 0x20 written by firmware (docs/firmware.md 13.1), VSYS_REG accuracy +-2 %
FW_LED_CUE = 0.020       # A, LEDs <= 20 mA "charging cue" while TMR_ILIM is 0xC9 (docs/firmware.md 6.3 / 7.2 / 13.3)
FW_OLED_SUP_VBAT = 3.21  # V, docs/firmware.md 7.2 / 13.3, SPEC 5.3 (NEW-1, OLED-V1, R6): at TMR_ILIM 0xC9
                         # OLED_VCC_EN only if the battery can supplement SYS: no BUVLO_STAT and VBAT_est >= 3.21 V
                         # (a true-cell value; VBAT_est = VREAD_GAIN x the last battery-only reading, i.e. a
                         # 3.2789 V reading).  The guard runs the cell at 3.21 V, the lowest the rule admits.  It was
                         # "VBAT >= about 3.15 V" on the reading, which failed BUVLO at -10 C.
FW_RULE_NEW1 = ("firmware rule NEW-1 / OLED-V1 (docs/firmware.md 7.2 / 13.3, SPEC 5.3): OLED_VCC_EN never at "
                f"TMR_ILIM 0xC9 unless the battery can supplement (no BUVLO_STAT, VBAT_est >= {FW_OLED_SUP_VBAT} V "
                f"true cell, VBAT_est = {VREAD_GAIN:g} x reading); until ILIM is 500 mA the LEDs show the <= 20 mA "
                "charging cue")
FW_RULE_POF = (f"firmware POF blanking (docs/firmware.md 12.4, R8): POFWARN ignored for {FW_POF_BLANK * 1e3:g} ms "
               "after OLED_VCC_EN or LED_PWR_EN rises")


def u21_on_usb_dead_battery(main, base, ilim, stop=12e-3):
    """OLED_VCC_EN rises on USB (5.0 V) with the cell below BUVLO: the BQ25180 cannot supplement SYS (SLUSE99C 8.3.3,
    'battery voltage has to be higher than VBUVLO'), so SYS is fed only through the input current limit; modelled as
    a 0 V cell (supplement path off).  This is docs/firmware.md 13.3 step 1: 'with a dead battery the system boots
    from VBUS ... write TMR_ILIM = 0xC9 (100 mA)'.  At the 100 mA code this is the OLD rule (OLED allowed on at
    C7 <= 04h), kept as the evidence for NEW-1 / OLED-V1; the 500 mA code is allowed by the current rule."""
    CORNERS["_dead"] = dict(usb=1, vbat=0.0, vbus=5.0)
    try:
        return u21_turn_on(main, base, "_dead", 25, stop=stop, ilim=ilim, step="5u")
    finally:
        CORNERS.pop("_dead")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE (firmware-dependent, NEW-1 / OLED-V1): dead battery (below BUVLO) on USB at "
                   "the 100 mA input limit that firmware sets on VBUS detect (docs/firmware.md 13.3), with the OLED "
                   "allowed on as the OLD rule did: the U21 + TPS61040 start-up surge (~0.4 A for ~1 ms to charge "
                   "+13V_OLED) empties the ~100 uF of VSYS bulk, VSYS falls to ~1.5 V and +3V3 below the nRF52840 "
                   "brown-out level -> reboot loop. The rule now in docs/firmware.md 7.2 / 13.3 and SPEC 5.3 keeps "
                   "OLED_VCC_EN low at TMR_ILIM 0xC9 unless the battery can supplement; guarded by "
                   "test_u21_turn_on_dead_battery_usb_100ma_with_fw_rule")
def test_u21_turn_on_dead_battery_usb_100ma(main, base, check):
    # +3V3 crosses VBOR at ~4 ms; afterwards VSYS parks at the boost UVLO (~1.46 V) while the averaged model chatters
    # there (slow to simulate, and the real nRF has reset by then), so the window ends at 5 ms
    r = u21_on_usb_dead_battery(main, base, BQ_ILIM_100, stop=5e-3)
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check("VSYS min, OLED on, dead battery, USB ILIM 100 mA (record)", r["vsysmin"], None, None, "V",
          f"{DS_BQ} Table 8-17 ILIM 100 mA (max.), 8.3.3 no supplement below VBUVLO")
    check("+3V3 min, OLED on, dead battery, USB ILIM 100 mA", v3, NRF_VBOR_ON_MIN, None, "V",
          "nRF52840 PS v1.1 5.3 VBOR,ON min 1.57 V; OLD rule: docs/firmware.md 13.3 allowed the OLED on at "
          "C7 <= 04h at ILIM 100 mA (superseded by NEW-1 / OLED-V1)")


def test_u21_turn_on_dead_battery_usb_500ma(main, base, check):
    """Same, once firmware has raised the limit to the 500 mA code (450 mA min): the surge is carried.  This is what
    the current rule allows (docs/firmware.md 6.3 / 13.3 no-supplement profile: OLED_VCC_EN only after ILIM = 500 mA,
    OLED C7 <= 08h)."""
    r = u21_on_usb_dead_battery(main, base, BQ_ILIM_500_MIN)
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check("+3V3 min, OLED on, dead battery, USB ILIM 500 mA code (450 mA min)", v3, W25_VCC_MIN, None, "V",
          "W25Q128JV VCC min 2.7 V; BQ25180 ILIM 450 mA min; RT9080 DS9080-09 dropout")


def pof_window(r, t_en, blank=FW_POF_BLANK):
    """+3V3 (wave v(n_p3v3)) against the POF limit around a rail enable at t_en, for the POF blanking rule (R8):
    the time after t_en at which +3V3 is last below POF_LIMIT (0 if never) and the +3V3 minimum after the blanking
    window.  The deck must run past t_en + blank."""
    t, p3 = r["waves"]["time"], r["waves"]["v(n_p3v3)"]
    post = [p3[i] for i in range(len(t)) if t[i] >= t_en + blank]
    if not post:
        raise SimulationError(f"window ends before the {blank * 1e3:g} ms POF blanking does")
    below = [t[i] for i in range(len(t)) if t[i] >= t_en and p3[i] < POF_LIMIT]
    return (max(below) - t_en) if below else 0.0, min(post)


def check_pof_blanking(check, r, t_en, enable, tag):
    """Firmware POF blanking (R8) after `enable` rises at t_en: below POF_LIMIT only inside the blanking window."""
    t_last, v_post = pof_window(r, t_en)
    check(f"time +3V3 is last below the POF limit after {enable} rises, {tag} (record)", t_last, None, None, "s",
          f"informational: POF limit {POF_LIMIT:.3f} V; {FW_RULE_POF} (first proposed as 5 ms; the worst guard "
          "case, the ILIM 80 mA min dead-battery cue, needs 5.82 ms)")
    check(f"+3V3 min after the {FW_POF_BLANK * 1e3:g} ms POF blanking ({enable}), {tag}", v_post, POF_LIMIT, None,
          "V", f"docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 %; {FW_RULE_POF}")


def usb_100ma_charging_cue(main, base, ilim, vsysreg, t_on=0.2e-3, stop=0.2e-3 + FW_POF_BLANK + 5e-3):
    """The dead-battery USB boot of u21_on_usb_dead_battery with firmware rule NEW-1 / OLED-V1 applied: at TMR_ILIM
    0xC9 with the cell below BUVLO (0 V cell, no supplement) OLED_VCC_EN stays LOW (U21 and the boost in the deck,
    held off) and the LEDs show the charging cue instead: LED_PWR_EN rises at t_on (U2 turn-on into the full VLED
    capacitance) and the ring then draws FW_LED_CUE.  With the always-on +3V3 load (I_3V3 = 50 mA peak) that is the
    70 mA total of the no-supplement ILIM-100 profile (docs/firmware.md 6.3).  The window runs 5 ms past the POF
    blanking (FW_POF_BLANK) so the +3V3 recovery can be checked."""
    CORNERS["_dead"] = dict(usb=1, vbat=0.0, vbus=5.0)
    try:
        d = Deck(f"USB ILIM {ilim * 1e3:g} mA, dead battery, OLED off, LED charging cue")
        d += ".temp 25"
        vsys_network(d, main, base, "_dead", 25, ilim=ilim, vsysreg=vsysreg)
        sense(d, "n_vsys", "n_u2_vin", "n_iu2")
        tps22917(d, main, "U2", vin_node="n_u2_vin")
        led_rail(d, main, duty=FW_LED_CUE / N_LEDS_FULL_A)
        tps22917(d, main, "U21")
        oled_input(d, main)
        d += [f"VCTL n_ctl 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1)", "VOE n_oe 0 1", "VOLEDEN n_oled_en 0 0"]
        gpio(d, main, "LED_PWR_EN", "n_ctl", "n_oe")
        gpio(d, main, "OLED_VCC_EN", "n_oled_en", "n_oe")
        d.tran("5u", f"{stop}")
        d.meas(f"tran vsys0 FIND v(n_vsys) AT={t_on * 0.9}")
        d.meas(f"tran vsysmin MIN v(n_vsys) FROM={t_on} TO={stop}")
        d.meas(f"tran iinrush MAX v(n_iu2) FROM={t_on} TO={stop}")
        d.meas(f"tran vledend FIND v(n_vled) AT={stop}")
        d.meas(f"tran vinmax MAX v({main.node('OLED_VIN')})")
        d.wave("v(n_p3v3)")
        r = run(d, need=("vsys0", "vsysmin", "iinrush", "vledend", "vinmax"))
        sane_vsys(r["vsys0"], "_dead", vsysreg=vsysreg)
    finally:
        CORNERS.pop("_dead")
    r["t_on"] = t_on
    return r


@pytest.mark.parametrize("ilim,vsysreg", [(BQ_ILIM_100, 4.5), (BQ_ILIM_100_MIN, BQ_SYSREG_FW * 0.98)],
                         ids=["ILIM100-SYSREG4.5", "ILIM80min-SYSREG4.4-2pct"])
def test_u21_turn_on_dead_battery_usb_100ma_with_fw_rule(main, base, check, ilim, vsysreg):
    """Guard of firmware rule NEW-1 / OLED-V1, the companion of the strict xfail test_u21_turn_on_dead_battery_usb_100ma:
    dead battery on USB 5.0 V at TMR_ILIM 0xC9, with the rule as docs/firmware.md 7.2 / 13.3 and SPEC 5.3 state it -
    OLED_VCC_EN stays low (no supplement) and the LEDs show the <= 20 mA charging cue, whose U2 turn-on is the only
    VSYS surge left.  Same limit as the xfail (+3V3 above the nRF52840 brown-out); also the W25Q128JV VCC minimum.
    Corners: the xfail's (100 mA, SYS_REG 4.5 V POR default) and the worst (ILIM 80 mA min, SYS_REG 4.4 V -2 %).
    The U2 inrush may take +3V3 below the POF limit; with the POF blanking rule (R8, FW_POF_BLANK after LED_PWR_EN)
    +3V3 must be back above it when the blanking ends, or the POF handler would shed the cue."""
    r = usb_100ma_charging_cue(main, base, ilim, vsysreg)
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    tag = f"OLED off + LED cue, dead battery, USB ILIM {ilim * 1e3:g} mA, SYS_REG {vsysreg:.3f} V"
    check(f"OLED_VIN max, U21 held off (boost EN = VIN), {tag}", r["vinmax"], None, BST_EN_VIL, "V",
          f"{DS_BST} Table 5.5 EN VIL max 0.4 V; {FW_RULE_NEW1}")
    check(f"VSYS min, {tag} (record)", r["vsysmin"], None, None, "V",
          f"{DS_BQ} ILIM 100 mA code, 8.3.3 no supplement below VBUVLO; U2 inrush peak {r['iinrush'] * 1e3:.0f} mA")
    check(f"+3V3 min - POFWARN limit, {tag} (record)", v3 - POF_LIMIT, None, None, "V",
          f"informational: below 0 only inside the POF blanking after LED_PWR_EN ({FW_RULE_POF}), checked below")
    check(f"+3V3 min, {tag}", v3, NRF_VBOR_ON_MIN, None, "V",
          f"nRF52840 PS v1.1 5.3 VBOR,ON min 1.57 V; {FW_RULE_NEW1}")
    check(f"+3V3 min vs flash VCC min, {tag}", v3, W25_VCC_MIN, None, "V",
          f"W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout; {FW_RULE_NEW1}")
    check_pof_blanking(check, r, r["t_on"], "LED_PWR_EN", tag)


# The [-10C-*] cases below were strict xfails 'DESIGN ISSUE (firmware rule insufficient)' under the former rule
# (VBAT >= about 3.15 V on the reading, +-46 mV drift -> a 3.104 V cell): at -10 C (pack impedance x2, ASSUMED, RPACK)
# the U21 + TPS61040 surge (~0.4 A for ~1 ms) pulled the BQ25180 BAT pin to 2.948 V (ILIM 100 mA) / 2.935 V (ILIM
# 80 mA min) for 1.24 / 1.37 ms > tBUVLO 60 us.  With rule R6 (VBAT_est >= 3.21 V true cell) they pass: 3.053 /
# 3.040 V, never below BUVLO, so the marks are retired.


def usb_100ma_oled_with_supplement(main, base, temp, ilim, vbat=FW_OLED_SUP_VBAT, t_on=0.2e-3,
                                   stop=0.2e-3 + FW_POF_BLANK + 5e-3):
    """Firmware rule NEW-1 / OLED-V1, its 'battery can supplement' branch: at TMR_ILIM 0xC9 the OLED may be enabled
    when there is no BUVLO_STAT and VBAT_est >= FW_OLED_SUP_VBAT (3.21 V true cell, VBAT_est = VREAD_GAIN x the last
    battery-only reading).  USB 5.0 V, the lowest cell that rule admits (VBAT_est = 3.21 V at a 3.2789 V reading;
    VREAD_GAIN covers a reading up to 2.1 % high, so the cell is >= 3.21 V; the worst simulated over-read, 67.9 mV,
    leaves it >= 3.211 V; a loaded reading only puts the cell higher), the LED charging cue (FW_LED_CUE) on VSYS, and
    OLED_VCC_EN rising at t_on.  The supplement diode of load_switches__bq25180.lib ignores BUVLO, so the BAT pin and
    the time it spends below BQ_BUVLO are returned for the BUVLO check.  The window runs 5 ms past the POF blanking
    (FW_POF_BLANK)."""
    CORNERS["_sup"] = dict(usb=1, vbat=vbat, vbus=5.0)
    try:
        r = u21_turn_on(main, base, "_sup", temp, t_on=t_on, stop=stop, ilim=ilim, i_extra=FW_LED_CUE, step="5u",
                        extra_waves=("v(xbq.bat)", "v(n_p3v3)"))
    finally:
        CORNERS.pop("_sup")
    t, vb = r["waves"]["time"], r["waves"]["v(xbq.bat)"]
    r["t_below_buvlo"] = sum(t[i] - t[i - 1] for i in range(1, len(t)) if 0.5 * (vb[i] + vb[i - 1]) < BQ_BUVLO)
    return r


@pytest.mark.parametrize("temp,ilim", [pytest.param(25, BQ_ILIM_100, id="25C-ILIM100"),
                                       pytest.param(25, BQ_ILIM_100_MIN, id="25C-ILIM80min"),
                                       pytest.param(-10, BQ_ILIM_100, id="-10C-ILIM100"),
                                       pytest.param(-10, BQ_ILIM_100_MIN, id="-10C-ILIM80min")])
def test_u21_turn_on_usb_100ma_supplement_with_fw_rule(main, base, check, temp, ilim):
    """Guard of firmware rule NEW-1 / OLED-V1, second branch (the one the rule still lets the OLED turn on in at
    TMR_ILIM 0xC9): the battery can supplement, VBAT_est exactly at the rule's 3.21 V (R6) and the cell at that
    value, the lowest the rule admits (VBAT_est = 0.979 x reading, docs/firmware.md 12.4, R1').  Same limit as the
    strict xfail test_u21_turn_on_dead_battery_usb_100ma (+3V3 above the nRF52840 brown-out), which holds only while
    the BQ25180 BAT pin stays above BUVLO (else the BATFET opens after tBUVLO 60 us and this is the dead-battery case),
    so the BAT pin is checked against BUVLO as test_bat_pin_vs_buvlo_at_firmware_floor does.  The surge may take
    +3V3 below the POF limit; with the POF blanking rule (R8) it must be back above it when the blanking ends."""
    r = usb_100ma_oled_with_supplement(main, base, temp, ilim)
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    tag = (f"OLED on, VBAT_est {FW_OLED_SUP_VBAT} V (reading {FW_OLED_SUP_VBAT / VREAD_GAIN:.4f} V, cell "
           f"{FW_OLED_SUP_VBAT:.3f} V) supplementing, USB ILIM {ilim * 1e3:g} mA, {temp} C")
    check(f"VSYS min, {tag} (record)", r["vsysmin"], None, None, "V", f"{DS_BQ} Table 7.5 VBSUP1 supplement")
    check(f"time BAT pin < BUVLO, {tag} (record)", r["t_below_buvlo"], None, None, "s",
          f"informational: {DS_BQ} 7.6 tBUVLO 60 us deglitch")
    check(f"+3V3 min - POFWARN limit, {tag} (record)", v3 - POF_LIMIT, None, None, "V",
          f"informational: below 0 only inside the POF blanking after OLED_VCC_EN ({FW_RULE_POF}), checked below")
    check(f"+3V3 min, {tag}", v3, NRF_VBOR_ON_MIN, None, "V",
          f"nRF52840 PS v1.1 5.3 VBOR,ON min 1.57 V; {FW_RULE_NEW1}")
    check(f"BQ25180 BAT pin min, {tag}", r["vbatmin"], BQ_BUVLO, None, "V",
          f"{DS_BQ} 7.5 VBUVLO 3.0 V (CHARGECTRL1 0x92), 7.6 tBUVLO 60 us, 8.3.3 no supplement below VBUVLO; "
          f"{FW_RULE_NEW1}")
    check_pof_blanking(check, r, r["t_on"], "OLED_VCC_EN", tag)


I_MOTOR = 0.42   # A, VM during a detent move, docs/architecture.md 7 power tree ("0.36-0.42 A for <= 0.9 s")


@pytest.mark.parametrize("rail,temp", [("U21", -10), ("U21", 25), ("U2", -10), ("U21+motor", -10)])
def test_bat_pin_vs_buvlo_at_firmware_floor(main, base, check, rail, temp):
    """Lowest battery at which firmware still switches the rails (FW_VBAT_FLOOR 3.465 V true rested cell: SHIP when
    VBAT_est < 3.465 V, a reading below 3.5393 V, docs/firmware.md 12.4 (R2), which parks the motor first; cell =
    VREAD_GAIN x reading (R1'); below VBAT_est 3.53 V the LED rail only carries the red cue): the BQ25180 BAT pin (cell
    minus pack/PCM/lead resistance) must stay above the BUVLO setting during the turn-on surge, or the BATFET opens
    after tBUVLO = 60 us and the system browns out.  The U21 surge (boost soft start, ~0.4 A for ~1 ms) is far longer
    than 60 us, so the plain minimum is compared.  'U21+motor': OLED enabled while the detent motor moves (NEW-2 now
    forbids toggling OLED_VCC_EN during a move below VBAT 3.6 V, so this is a stricter-than-firmware case).
    +3V3 against the POF limit: below it only inside the POF blanking after the enable (R8, FW_POF_BLANK); the window
    runs 5 ms past the blanking."""
    CORNERS["_floor"] = dict(usb=0, vbat=FW_VBAT_FLOOR, vbus=0.0)
    try:
        if rail == "U2":
            t_on = 0.5e-3
            r = u2_turn_on(main, base, "_floor", temp, t_on=t_on, stop=t_on + FW_POF_BLANK + 5e-3,
                           extra_waves=("v(n_p3v3)",))
        else:
            t_on = 0.2e-3
            r = u21_turn_on(main, base, "_floor", temp, t_on=t_on, stop=t_on + FW_POF_BLANK + 5e-3,
                            i_extra=I_MOTOR if "motor" in rail else 0.0, extra_waves=("v(n_p3v3)",))
    finally:
        CORNERS.pop("_floor")
    tag = f"{rail} turn-on at VBAT {FW_VBAT_FLOOR} V rested, {temp} C"
    check(f"BQ25180 BAT pin min, {tag}", r["vbatmin"], BQ_BUVLO,
          None, "V", f"{DS_BQ} 7.5 VBUVLO 3.0 V (CHARGECTRL1 0x92), 7.6 tBUVLO 60 us; docs/firmware.md 12.4 SHIP at "
          f"VBAT_est < 3.465 V (reading < {3.465 / VREAD_GAIN:.4f} V, VBAT_est = {VREAD_GAIN:g} x reading, "
          "VSENSE-1/4/5, R1')" +
          ("; docs/architecture.md 7 VM 0.42 A" if "motor" in rail else ""))
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check(f"+3V3 min - POFWARN limit, {tag} (record)", v3 - POF_LIMIT, None, None, "V",
          f"informational: below 0 only inside the POF blanking ({FW_RULE_POF}), checked below")
    check_pof_blanking(check, r, t_on, "LED_PWR_EN" if rail == "U2" else "OLED_VCC_EN", tag)


# ======================================================================================== 7. U21 off: back-powering
def u21_off_state(main, base, temp, panel_esd=True, stop=20.0, isd_out=None, v13_0=0.0, esd=None):
    """U21 off (OLED_VCC_EN low), +3V3 up.  Paths into OLED_VIN / +13V_OLED: U21 off-state leakage (VIN->VOUT),
    the SSD1351 VCI/VDDIO->VCC ESD path, then D21 reverse leakage from +13V_OLED back into OLED_VIN, which U21's
    QOD (tied to OLED_VIN in the netlist, fix LSW-1) returns to GND.  esd: panel clamp I-V (see oled_input)."""
    d = Deck(f"U21 off {temp}C")
    d += f".temp {temp}"
    vsys_network(d, main, base, "bat3.7", temp)
    isd = isd_out if isd_out is not None else (SW_ISD_MAX_85C if temp > 25 else 10e-9)
    tps22917(d, main, "U21", isd_out=isd)
    oled_input(d, main, panel_esd=panel_esd, esd=esd)
    d += ["VCTL n_ctl 0 0", "VOE n_oe 0 1"]
    gpio(d, main, "OLED_VCC_EN", "n_ctl", "n_oe")
    n13, nin, nfb = main.node("+13V_OLED"), main.node("OLED_VIN"), main.node("OLED_BST_FB")
    # start with OLED_VIN held at 0 V for the operating point (.ic, released at t = 0), as after a power-up with
    # the OLED left off; with QOD open (before fix LSW-1, or a lost QOD tie) the boost would hiccup around its
    # UVLO at 60 C, so there is no free DC operating point, and from 0 V a rising OLED_VIN shows the fault
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


# The SSD1351 datasheet gives no I-V for its VCI/VDDIO -> VCC ESD structure: the generic diode (IS 1e-14, RS 10) and
# a strong (IS 1e-11) and very strong (IS 1e-9) clamp bracket it (verifier).  The stronger the clamp, the closer
# +13V_OLED (and with it FB = VCC x R27/(R26 + R27)) sits to +3V3, so the FB check is tightest for the strongest one.
PANEL_ESD = {"generic ESD": None, "strong ESD IS 1e-11": {"is": 1e-11, "rs": 1.0},
             "very strong ESD IS 1e-9": {"is": 1e-9, "rs": 1.0}}
U21_OFF_CASES = ([(t, "generic ESD") for t in (-10, 25, 60)] +
                 [(t, e) for e in ("strong ESD IS 1e-11", "very strong ESD IS 1e-9") for t in (25, 60)])


@pytest.mark.parametrize("temp,esd", U21_OFF_CASES)
def test_u21_off_backpower_via_panel_and_d21(main, base, check, temp, esd):
    """Guards fix LSW-1 / SLP-1 (U21 QOD tied to OLED_VIN): with OLED_VCC_EN low the SSD1351 VCI->VCC ESD path still
    holds +13V_OLED near +3V3 and D21 leaks backwards into OLED_VIN, but U21's ~150 R QOD now holds OLED_VIN at
    0.05 / 0.7 / 5.4 mV at -10 / 25 / 60 C (any clamp) against the TPS61040 EN VIL max 0.4 V, so the boost (EN tied
    to VIN) is guaranteed off.  FB - OLED_VIN is 0.26 V with the generic clamp and up to 0.293 V with the very
    strong one at 60 C against the 0.3 V abs max: thin, so bring-up measures FB.  Before the fix (QOD open)
    OLED_VIN floated to 0.50 / 0.84 / 1.24 V.  Also carries the clamp bracketing of the former what-if test
    (QOD tied by a 1 mOhm deck resistor), which the netlist now implements."""
    # windows as before the fix: with QOD open D21's leakage charged C38 at roughly 0.2 / 1 / 6 V/s at -10 / 25 /
    # 60 C and reached the 0.4 V EN VIL well inside them, so a lost QOD connection would still be caught
    r = u21_off_state(main, base, temp, panel_esd=True, stop={-10: 8.0, 25: 3.0, 60: 0.25}[temp], esd=PANEL_ESD[esd])
    tag = f"{temp}C {esd}"
    check(f"+13V_OLED held by the panel ESD path (record) {tag}", r["v13_end"], None, None, "V",
          "SSD1351 Rev 1.3 8.9 Note (1)")
    check(f"FB - OLED_VIN with OLED off {tag}", r["vfb_end"] - r["vin_end"], None, BST_FB_OVER_VIN, "V",
          f"{DS_BST} Table 5.1 abs max FB <= VIN + 0.3 V")
    check(f"OLED_VIN with OLED off (boost EN = VIN) {tag}", r["vin_max"], None, BST_EN_VIL, "V",
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


@pytest.mark.parametrize("vbat,i_led,temp", [(3.53, 0.100, 25), (3.53, 0.100, -10), (3.65, 0.300, -10),
                                            (3.60, 0.300, -10)])
def test_vled_at_firmware_led_floor(main, base, check, vbat, i_led, temp):
    """Lowest battery at which firmware still lights the ring (docs/firmware.md 6.3 LED derating: < 3.60 V -> 100 mA
    cap, < 3.53 V -> off except the <= 2 mA red cue; >= 3.65 V re-enables the 300 mA bursts, which then run down to the
    3.60 V hysteresis edge): VLED under that load must stay in the WS2812C supply range.  vbat is the threshold, a
    TRUE-cell value that firmware compares against VBAT_est = VREAD_GAIN x rested reading (R1', docs/firmware.md
    12.4): at the switch point the reading is vbat / 0.979 and the cell is VREAD_GAIN x reading = vbat, the lowest
    the rule admits (VREAD_GAIN covers a reading up to 2.1 % high).  Under the former rule (thresholds on the
    reading itself, then +-46 mV drift) the cells were 46 mV lower and passed: 3.484 V at 100 mA (+125 mV at 25 C,
    +87 mV at -10 C), 3.604 V and 3.554 V at 300 mA, -10 C (+71 / +21 mV).  With the drift R1 documents (72 mV high)
    that comparison would fail the 3.60 V burst edge (cell 3.528 V: VLED 3.2954 V at -10 C), which is why the rule
    applies VBAT_est to these thresholds."""
    reading = vbat / VREAD_GAIN
    cell = VREAD_GAIN * reading
    CORNERS["_floor"] = dict(usb=0, vbat=cell, vbus=0.0)
    try:
        r0 = led_dc(main, base, "_floor", temp, i_led)
        r = led_dc(main, base, "_floor", temp, i_led, ron_add=max(0.0, _ron_max(r0["vin"], 25) - r0["ron"]))
    finally:
        CORNERS.pop("_floor")
    check(f"VLED at VBAT_est {vbat} V (reading {reading:.4f} V, cell {cell:.3f} V rested), {i_led * 1e3:.0f} mA, "
          f"{temp} C", r["vled"], WS_VDD_MIN, None, "V", f"{DS_WS} p.2 VDD 3.3 V min; docs/firmware.md 6.3 LED "
          f"derating table on VBAT_est = {VREAD_GAIN:g} x reading, 12.4 (VSENSE-1/4/5, R1'); {DS_SW} Table 7.5 RON "
          "max")


def test_phantom_clamp_sensitivity(main, base, check):
    """Record how the DIN-over-VDD result depends on the (unspecified) WS2812C clamp I-V: strong / nominal / weak."""
    for tag, esd in (("strong clamp IS 1e-13 RS 0", {"is": 1e-13, "rs": 0.0}), ("nominal IS 1e-14 RS 10", None),
                     ("weak clamp IS 1e-15 RS 20", {"is": 1e-15, "rs": 20.0})):
        r = phantom_op(main, base, "bat4.2", 25, esd=esd)
        check(f"DIN - VDD, P0.06 high, VLED off, {tag} (record)", r["vi_over_vdd"], None, None, "V",
              f"informational bracket for the xfail above; {DS_WS} gives no clamp I-V")
