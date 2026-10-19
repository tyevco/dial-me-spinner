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

import math

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
DS_NRF = "nRF52840 PS v1.1 6.9.2"

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
POF_LIMIT = 2.9 * 1.05  # V, firmware POFWARN 2.9 V (docs/firmware.md fault table) + VPOFTOL +5 % (nRF52840 PS 5.3.7)
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

# nRF52840 GPIO output resistance = 0.4 V / I(VDD-0.4 V)  (PS v1.1 IOH,SD 1/2/4 mA, IOH,HDH 6/9/14 mA)
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


def led_rail(deck, main, duty=0.0, esd=None):
    """U2's load: every fitted R/C on VLED / QOD / CT and each WS2812C pixel from the netlist."""
    deck.include(LIB_WS)
    deck += main.passives(nets={"VLED", "GND", "LSW_QOD", "LSW_CT", "VSYS", "LED_PWR_EN"},
                          exclude=_vsys_only(main))
    esd = esd or {}
    extra = " ".join(f"{k}={v:.6g}" for k, v in esd.items())
    for ref in main.find("WS2812C"):
        deck += (f"X{ref} {main.pin(ref, 'DIN')} {main.pin(ref, 'VDD')} {main.pin(ref, 'VSS')} LSW_WS2812C "
                 f"params: duty={duty:.6g} {extra}")
    return deck


def _vsys_only(main):
    """Parts whose pins are all VSYS/GND are emitted by vsys_network(); skip them elsewhere."""
    return [r for r in main.comps if set(main.pins.get(r, {}).values()) <= {"VSYS", "GND"}]


def oled_input(deck, main, temp_boost=True, panel_esd=False):
    """U21's load: C37/C41/C38/R25/L20/D21/output caps/FB divider from the netlist, TPS61040 averaged model."""
    deck.include(LIB_BST).include(LIB_D21)
    deck += main.passives(nets={"OLED_VIN", "OLED_BST_SW", "+13V_OLED", "OLED_BST_FB", "GND", "VSYS",
                                "OLED_LSW_CT", "OLED_VCC_EN"}, exclude=_vsys_only(main))
    a, k = main.pin("D21", "A"), main.pin("D21", "K")
    deck += f"XD21 {a} {k} LSW_B5819W"
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
    assert not errors, errors[:5]
    missing = [n for n in need if n not in res]
    assert not missing, (missing, res["_log"][-3000:])
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
    # the rising-edge trip (VOUT starts after the CT ramp, so measure the comparator via CT release) must sit
    # inside the guaranteed window VIL max .. VIH min
    for nm, v in (("ON rising trip", r["vrise"]), ("ON falling trip", r["vfall"])):
        check(f"{nm} model @{vin} V", v, SW_VIL_MAX, SW_VIH_MIN, "V", f"{DS_SW} Table 7.3 VIL max / VIH min")


# ======================================================================================== 2. U2 LED rail turn-on
def _u2_turn_on_deck(main, base, corner, temp=25, t_on=0.5e-3, stop=9e-3, ron_add=0.0):
    d = Deck(f"U2 turn-on {corner} {temp}C")
    vsys_network(d, main, base, corner, temp)
    sense(d, "n_vsys", "n_u2_vin", "n_iu2")               # U2 VIN pin current -> V(n_iu2)
    tps22917(d, main, "U2", ron_add=ron_add, vin_node="n_u2_vin")
    led_rail(d, main)
    d += f"VCTL n_ctl_led 0 PWL(0 0 {t_on} 0 {t_on + 1e-7} 1)"
    d += "VOE n_oe_led 0 1"
    gpio(d, main, "LED_PWR_EN", "n_ctl_led", "n_oe_led")
    d.tran("2u", f"{stop}")
    d.meas(f"tran vsys0 FIND v(n_vsys) AT={t_on * 0.9}")
    d.meas(f"tran vsysmin MIN v(n_vsys) FROM={t_on} TO={stop}")
    d.meas(f"tran iinrush MAX v(n_iu2) FROM={t_on} TO={stop}")
    d.meas(f"tran ibat MAX v(n_ibat) FROM={t_on} TO={stop}")
    d.meas(f"tran vledend FIND v(n_vled) AT={stop}")
    return d


@pytest.mark.parametrize("corner", list(CORNERS))
def test_u2_turn_on_supply_corners(main, base, check, corner):
    """LED_PWR_EN rises: VLED ramp time, inrush through U2 and the battery, VSYS droop -> +3V3 floor."""
    t_on, stop = 0.5e-3, 9e-3
    d = _u2_turn_on_deck(main, base, corner, t_on=t_on, stop=stop)
    r = run(d, need=("vsys0", "vsysmin", "iinrush", "ibat", "vledend"))
    v0 = r["vsys0"]
    d2 = _u2_turn_on_deck(main, base, corner, t_on=t_on, stop=stop)
    d2.meas(f"tran t10 WHEN v(n_vled)={0.1 * v0} RISE=1")
    d2.meas(f"tran t90 WHEN v(n_vled)={0.9 * v0} RISE=1")
    r2 = run(d2, need=("t10", "t90"))
    ton, tr = r2["t90"] - t_on, r2["t90"] - r2["t10"]
    c7 = main.value("C7")
    check(f"U2 tON (ON -> VLED 90 %) {corner}", ton, None, FW_LED_WAIT, "s",
          "docs/architecture.md 7: firmware waits >= 5 ms after LED_PWR_EN; SPEC 5.1 '~4 ms'")
    vin_k = 3.6 if v0 < 4.3 else 5.0
    check(f"U2 tR vs Table 7.6 {corner}", tr, 0.8 * SW_TR_K[vin_k] * c7 / 1e-12, 1.2 * SW_TR_K[vin_k] * c7 / 1e-12, "s",
          f"{DS_SW} Table 7.6 tR {SW_TR_K[vin_k] * 1e6:.1f} us/pF x C7 (+-20 %, VIN {vin_k} V row)")
    check(f"U2 inrush peak {corner}", r["iinrush"], None, SW_IMAX, "A", f"{DS_SW} Table 7.1 IMAX 2 A")
    if not CORNERS[corner]["usb"]:
        check(f"battery current peak {corner}", r["ibat"], None, BQ_BATOCP, "A", f"{DS_BQ} IBAT_OCP 1.5 A setting")
    v3 = min(3.3, r["vsysmin"] - I_3V3 * LDO_RDO)
    check(f"+3V3 min during U2 turn-on {corner}", v3, W25_VCC_MIN, None, "V",
          "W25Q128JV VCC min 2.7 V; RT9080 DS9080-09 dropout 0.53 V @ 0.6 A")
    if CORNERS[corner]["usb"] or CORNERS[corner]["vbat"] >= 3.48:
        check(f"+3V3 min vs POFWARN {corner}", v3, POF_LIMIT, None, "V",
              "docs/firmware.md POFWARN 2.9 V + nRF52840 PS VPOFTOL 5 % (in the firmware's VBAT >= 3.48 V envelope)")
    check(f"VLED settles to VSYS {corner}", r["vledend"], 0.98 * v0, None, "V", f"{DS_SW} Table 9-2 ON=H: VOUT = VIN")
