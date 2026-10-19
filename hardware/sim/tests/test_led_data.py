"""LED data line (architecture.md risk R27): nRF52840 P0.06 -> R40 -> LED_DIN_R (R41 pull-down) -> R43 (0 R) ->
D101 DI (first WS2812C-2020-V6), plus the DNP SN74LV1T34 option (U43/C43 fitted, R43 removed).

What is simulated (all passives straight from hardware/kicad/main/dial-me-spinner-main.net):
  * the P0.06 output stage, standard (S0S1) and high (H0H1) drive, at the nRF52840 PS min / typ / max
    IOH / IOL corners (models/led_data__nrf52840_gpio.lib), on +3V3 = RT9080-33 (+/-2 %, dropout at low VSYS);
  * the PCB traces LED_DIN_MCU (U10.22 -> R40, ~1 mm since R40 sits next to pad 22, LED-DATA-1) and LED_DIN
    (R43/U43 -> D101.DI) as LC ladders, and LED_DIN_R (R40 -> R41/R43/U43, the 40-50 mm run) as its lumped capacitance
    (an LC ladder in test_trace_and_r40_placement), with lengths taken from the routed board when routed, else from
    the placed pads (rectilinear MST x ROUTE_FACTOR);
  * D101.DI as CI <= 15 pF, II <= 1 uA and ESD clamps (models/led_data__ws2812c_din.lib), VDD = VLED = VSYS;
  * the WS2812 bit stream as the I2S driver generates it (SCK 3.2 MHz, nibble 0x8 = "0", 0xC = "1").
What is checked: the DI high level against VIH (0.55 x VDD datasheet, 0.6 x VDD PCN) and the low level against
VIL across VSYS = 3.0 ... 4.59 V; the pulse widths the LED can see (worst case over any receiver threshold
between VIL and VIH) against the T0H / T1H / T0L / T1L windows; abs-max at DI and at the P0.06 pad; the same for
the U43 option; tolerance extremes, temperature, load extremes; and fault injection.
0.7 x VDD (the pre-V6 WS2812B threshold) is reported as information only: it is not the fitted part's limit.

Added by the independent verification:
  * the PS-GUARANTEED drive (NRF52840_GPIO_BOUND: I >= IOH,min x min(Vds/0.4 V, 1), the weakest concave I-V the PS
    table allows) for both drive modes; the tanh fit above scales the TYPICAL tRF shape to the min corner, which the
    PS does not guarantee. Standard drive fails the T1H/T0L/T1L windows there (strict xfail, the evidence for
    firmware rule LED-DATA-V1), high drive passes: P0.06 must run at H0H1, as docs/firmware.md 3.1 / 6.1 and
    SPEC 5.4 now require ([HD] is the guard of that rule);
  * +3V3 low corner = RT9080 accuracy -2 % AND load regulation -1 % (DS9080-09 table 14), not accuracy alone;
  * P0.06 high-Z (reset / DFU / pin not yet configured, PIN_CNF reset value): R41 must hold D101.DI (and U43.A)
    below VIL against the +/-1 uA input leakage;
  * a netlist-coverage guard: every part on the three data nets must be modelled by the deck (passives(nets=...)
    silently drops a part with a pin on a net outside the set);
  * fault tests for R41 left off and R41 wired to VLED (both invisible to the driven-data checks).
"""

from __future__ import annotations

import copy
import functools
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

import spicelib
from spicelib import Deck, Design

sys.path.insert(0, os.path.join(spicelib.HW, "tools"))
import sexpr  # noqa: E402
from sexpr import find, find_all  # noqa: E402

GPIO_LIB = "led_data__nrf52840_gpio.lib"
DIN_LIB = "led_data__ws2812c_din.lib"
LV_LIB = "led_data__sn74lv1t34.lib"

# ---------------------------------------------------------------------------------------------- sources
SRC_WS = "WS2812C-2020-V6 DS V1.0 (2026-05-21)"
SRC_WS_EC = SRC_WS + " p.3 电气参数 (TA 25 C, VDD 5 V)"
SRC_WS_T = SRC_WS + " p.3-4 数据传输时间"
SRC_WS_AMR = SRC_WS + " p.2 最大额定值 VI -0.3 ... VDD+0.7 V"
SRC_PCN = "Worldsemi WS2812B-series V6 PCN 2025-09-30 item 6 (0.6 VDD)"
SRC_PS = "nRF52840 PS 4413_417 v1.1"
SRC_PS_GPIO = SRC_PS + " 6.9.3.1"
SRC_PS_AMR = SRC_PS + " Table 173 VI/O -0.3 ... VDD+0.3 V"
SRC_LV = "SN74LV1T34 DS SCLS743E"
SRC_ARCH = "docs/architecture.md 6.4 (I2S SCK 3.2 MHz, nibble 0x8/0xC)"

# ------------------------------------------------------------------- WS2812C-2020-V6 (D101) datasheet numbers
WS_VIH_DS = 0.55        # x VDD, min (SRC_WS_EC)
WS_VIH_PCN = 0.60       # x VDD (SRC_PCN) -- the stricter of the two Worldsemi V6 documents
WS_VIH_LEGACY = 0.70    # x VDD, pre-V6 WS2812B family; NOT the fitted part's limit (information only)
WS_VIL = 0.7            # V, max (SRC_WS_EC)
WS_CI = 15e-12          # F, max (SRC_WS_EC 开关特性)
WS_II = 1e-6            # A, max (SRC_WS_EC)
WS_VI_OVER = 0.7        # V above VDD, abs max (SRC_WS_AMR)
WS_VI_MIN = -0.3        # V, abs max (SRC_WS_AMR)
WS_VDD_MIN = 3.3        # V (SRC_WS p.2)
T0H = (220e-9, 380e-9)  # SRC_WS_T
T1H = (580e-9, 1e-6)
TXL = (580e-9, 1e-6)    # T0L and T1L

# ------------------------------------------------------------------------- nRF52840 GPIO (PS 6.9.3.1)
# (min, typ, max) current at 0.4 V drop; VK / TEDGE fitted to the tRF / tHRF table (see the model header)
DRIVE = {
    "SD": dict(ioh=(1e-3, 2e-3, 4e-3), iol=(1e-3, 2e-3, 4e-3), vk=3.0, tedge=2.5e-9,
               trf={15e-12: 9e-9, 25e-12: 13e-9, 50e-12: 25e-9}),
    "HD": dict(ioh=(6e-3, 9e-3, 14e-3), iol=(6e-3, 10e-3, 15e-3), vk=1.0, tedge=4.0e-9,
               trf={15e-12: 4e-9, 25e-12: 5e-9, 50e-12: 8e-9}),
}
NRF_VIO_OVER = 0.3      # SRC_PS_AMR
# (pull-up corner, pull-down corner): 0 = min, 1 = typ, 2 = max column
SKEW = {"typ": (1, 1), "weak": (0, 0), "slow_rise": (0, 2), "slow_fall": (2, 0), "strong": (2, 2)}

# --------------------------------------------------------------------------------------- supplies
VDD_NOM, VDD_ACC = 3.3, 0.02          # RT9080-33, DS9080-09 VVOUT_ACC +/-2 % (ILOAD 1 mA, TA 25 C)
VDD_LOADREG = 0.01                    # DS9080-09 VLOAD_REG max 1 % (1 mA < ILOAD < 600 mA): only lowers VOUT
VDD_LO = VDD_NOM * (1 - VDD_ACC - VDD_LOADREG)
VDD_HI = VDD_NOM * (1 + VDD_ACC)
RT_RDROP = 0.53 / 0.6                 # ohm: DS9080-09 VDROP max 0.53 V at 600 mA (VOUT >= 3 V)
I_3V3 = 0.05                          # A: +3V3 peak load, docs/architecture.md 8 rail table ("about 50 mA peak")
# BQ25180 SLUSE99C SYS_REG 4.5 V, VSYS_REG_ACCURACY +/-2 %: 4.5 V is the POR default and the highest SYS that
# docs/firmware.md 13.1 allows (it writes 0x20 = 4.4 V; 010 = 4.5 V is the only other allowed value, LED-DATA-V3), so it
# is the worst case for the VIH margin.  Not lowered to 4.4 V: that would loosen every VIH check.
SYS_REG, SYS_ACC = 4.5, 0.02
# VSYS as the charger delivers it: battery (SYS = VBAT through the BATFET) and USB (VBUS 4.5 V is in dropout so
# VSYS <= 4.5 V; VBUS 5.0 / 5.5 V regulate to 4.5 V +/-2 %). VLED = VSYS (dark ring: no TPS22917 drop = highest VIH).
SUPPLY = [("VBAT 3.0 V", 3.0), ("VBAT 3.7 V", 3.7), ("VBAT 4.2 V", 4.2),
          ("USB VSYS_REG -2 %", SYS_REG * (1 - SYS_ACC)), ("USB VBUS 4.5 V / VSYS_REG nom", SYS_REG),
          ("USB VBUS 5.0-5.5 V, VSYS_REG +2 %", SYS_REG * (1 + SYS_ACC))]
VSYS_MAX = SYS_REG * (1 + SYS_ACC)


def vdd_of(vsys: float, k: int) -> float:
    """+3V3 for corner k (-1 = accuracy -2 % and load regulation -1 %, 0 = nominal, +1 = +2 %), limited by the
    LDO dropout at low VSYS."""
    v = {-1: VDD_LO, 0: VDD_NOM, 1: VDD_HI}[k]
    return min(v, vsys - I_3V3 * RT_RDROP)


# --------------------------------------------------------------------------------------- bit stream
SCK = 3.2e6                           # SRC_ARCH
TBIT = 4 / SCK                        # 1.25 us per WS2812 bit (one nibble)
TH = {"0": 1 / SCK, "1": 2 / SCK}     # nibble 0x8 -> 312.5 ns high, 0xC -> 625 ns high
PATTERN = "01100"
T0 = 100e-9
T_HOLD_HI, T_HOLD_LO = 1e-6, 0.5e-6   # DC high / low levels measured at the end of these
T_DATA_END = T0 + len(PATTERN) * TBIT
T_STOP = T_DATA_END + T_HOLD_HI + T_HOLD_LO

# ------------------------------------------------------------------------------------- SN74LV1T34
LV_VIH = [(3.0, 1.39), (3.3, 1.39), (3.6, 1.48), (4.5, 2.03), (5.0, 2.03), (5.5, 2.11)]   # 6.5, -40..125 C
LV_VIL = [(3.0, 0.65), (3.6, 0.65), (4.5, 0.8), (5.5, 0.8)]                              # 6.5, -40..125 C
LV_TPD = [(2.5, 9.5e-9), (3.3, 8.0e-9), (5.0, 6.5e-9)]                                  # 6.6 max, 15 pF
LV_RUP, LV_RDN, LV_CO, LV_CI = 100.0, 50.0, 2.5e-12, 10e-12                              # 6.5 (see the lib)
LV_TEDGE = 1e-9                       # assumption (not in the DS), absorbed by the tpd calibration
LV_DTDV = 20e-9                       # s/V max input transition rate, 6.3
LV_TD_MIN = 1e-12                     # smallest internal delay of the model (XSPICE d_buffer, see the lib)


def interp(tab, x):
    xs, ys = zip(*tab)
    return float(np.interp(x, xs, ys))


def lv_vih(vcc):
    """VIH min between table rows: take the next higher VCC row (conservative)."""
    return next(v for x, v in LV_VIH if x >= vcc - 1e-9)


def lv_vil(vcc):
    """VIL max between table rows: take the lower value (0.65 V for 3.0-4.5 V, conservative)."""
    return 0.8 if vcc >= 4.5 - 1e-9 else 0.65


# --------------------------------------------------------------------------------------- PCB traces
PCB = os.path.join(spicelib.HW, "kicad", "main", "dial-me-spinner-main.kicad_pcb")
PRO = os.path.join(spicelib.HW, "kicad", "main", "dial-me-spinner-main.kicad_pro")
STACK_H = 0.2104e-3      # ASSUMPTION: JLC04161H-7628 outer prepreg (no stack-up is defined in the repo)
STACK_ER = 4.4           # ASSUMPTION: 7628 prepreg
ROUTE_FACTOR = 1.25      # unrouted nets: rectilinear MST of the placed pads x 1.25 detour allowance


def track_width() -> float:
    import json
    try:
        cls = json.load(open(PRO))["net_settings"]["classes"]
        return float(next(c for c in cls if c["name"] == "Default")["track_width"]) * 1e-3
    except Exception:
        return 0.15e-3


def microstrip(w, h=STACK_H, er=STACK_ER):
    """Hammerstad-Jensen: (Z0, L' H/m, C' F/m)."""
    u = w / h
    eeff = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + (0.04 * (1 - u) ** 2 if u < 1 else 0))
    if u <= 1:
        z0 = 60 / math.sqrt(eeff) * math.log(8 / u + u / 4)
    else:
        z0 = 120 * math.pi / (math.sqrt(eeff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    v = 299792458 / math.sqrt(eeff)
    return z0, z0 / v, 1 / (z0 * v)


_PCB_CACHE = {}


def pcb_net_lengths():
    """{net: (length_m, routed?)} for the three data nets, plus pad positions."""
    if _PCB_CACHE:
        return _PCB_CACHE
    tree = sexpr.parse(open(PCB, encoding="utf-8").read())
    netname = {str(n[1]): str(n[2]) for n in find_all(tree, "net") if len(n) >= 3}
    short = lambda s: s.split("/")[-1]  # noqa: E731
    pads = {}
    for fp in find_all(tree, "footprint"):
        ref = next((str(p[2]) for p in find_all(fp, "property") if str(p[1]) == "Reference"), None)
        at = find(fp, "at")
        x0, y0 = float(at[1]), float(at[2])
        rot = math.radians(-float(at[3])) if len(at) > 3 else 0.0
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if not net:
                continue
            nn = short(str(net[2]) if len(net) > 2 else netname.get(str(net[1]), ""))
            pa = find(pad, "at")
            px, py = float(pa[1]), float(pa[2])
            pads.setdefault(nn, []).append(((ref, str(pad[1])),
                                            (x0 + px * math.cos(rot) - py * math.sin(rot),
                                             y0 + px * math.sin(rot) + py * math.cos(rot))))
    seg = {}
    for s in find_all(tree, "segment"):
        net = find(s, "net")
        nn = short(netname.get(str(net[1]), str(net[1])))
        a, b = find(s, "start"), find(s, "end")
        seg[nn] = seg.get(nn, 0.0) + math.dist((float(a[1]), float(a[2])), (float(b[1]), float(b[2])))
    def mst(pts, dist):
        done, rest, tot = [pts[0]], pts[1:], 0.0
        while rest:
            dmin, j = min((dist(a, b), j) for j, b in enumerate(rest) for a in done)
            tot += dmin
            done.append(rest.pop(j))
        return tot

    out = {}
    for net in ("LED_DIN_MCU", "LED_DIN_R", "LED_DIN"):
        pts = [p for _, p in pads.get(net, [])]
        if seg.get(net):
            # a routed net is never shorter than the Euclidean MST of its pads (guards a partially routed net)
            out[net] = (max(seg[net], mst(pts, math.dist)) * 1e-3, True)
            continue
        # rectilinear minimum spanning tree (Prim) x detour allowance
        out[net] = (mst(pts, lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1])) * ROUTE_FACTOR * 1e-3, False)
    out["_pads"] = pads
    _PCB_CACHE.update(out)
    return _PCB_CACHE


def ladder(name, a, b, length, n=6, w=None):
    """LC ladder (plus the copper series R) for a microstrip of `length` m, at least one section per 2 mm."""
    if length <= 0:
        return [f"V{name}_0 {a} {b} 0"]
    n = max(n, math.ceil(length / 2e-3))
    _, lp, cp = microstrip(w or track_width())
    r_cu = 1.7e-8 / ((w or track_width()) * 35e-6) * length / n
    lines, prev = [], a
    for i in range(n):
        mid, nxt = f"{a}_{name}_m{i}", (b if i == n - 1 else f"{a}_{name}_{i}")
        lines += [f"R{name}{i} {prev} {mid} {r_cu:.4g}", f"L{name}{i} {mid} {nxt} {lp * length / n:.4g}",
                  f"C{name}{i} {nxt} 0 {cp * length / n:.4g}"]
        prev = nxt
    return lines


# ------------------------------------------------------------------------------------- deck builder
def ctl_pwl(pattern=PATTERN):
    pts = [(0.0, 0.0)]
    e = 50e-12
    for i, bit in enumerate(pattern):
        t = T0 + i * TBIT
        pts += [(t, 0), (t + e, 1), (t + TH[bit], 1), (t + TH[bit] + e, 0)]
    pts += [(T_DATA_END, 0), (T_DATA_END + e, 1), (T_DATA_END + T_HOLD_HI, 1), (T_DATA_END + T_HOLD_HI + e, 0)]
    return "PWL(" + " ".join(f"{t:.6g} {v}" for t, v in pts) + ")"


def drive_params(mode, skew, temp=None):
    p = DRIVE[mode]
    iu, idn = SKEW[skew]
    ioh, iol = p["ioh"][iu], p["iol"][idn]
    if temp is not None and skew == "typ":
        # typical part at temperature: MOSFET mobility ~ T^-1.5 (textbook), kept inside the PS min/max envelope
        k = ((temp + 273.15) / 298.15) ** -1.5
        ioh = min(max(p["ioh"][1] * k, p["ioh"][0]), p["ioh"][2])
        iol = min(max(p["iol"][1] * k, p["iol"][0]), p["iol"][2])
    tedge = p["tedge"] * 0.5 * (p["ioh"][1] / ioh + p["iol"][1] / iol)
    return dict(IOH=ioh, IOL=iol, VK=p["vk"], TEDGE=tedge)


@functools.lru_cache(maxsize=None)
def _lv_stage_delay(vcc, rup, rdn):
    """(tplh, tphl) of the LV1T34 model with zero internal delay into the 6.6 load (15 pF), VCC/2 to VCC/2."""
    deck = Deck(f"LV1T34 stage delay {vcc}")
    deck.include(LV_LIB)
    prm = dict(VTH=vcc / 2, TDR=LV_TD_MIN, TDF=LV_TD_MIN, RUP=rup, RDN=rdn, TEDGE=LV_TEDGE, CI=LV_CI, CO=LV_CO)
    deck += [f"Vcc vcc 0 {vcc}", f"Va a 0 PULSE(0 {vcc} 5n 1p 1p 50n 100n)", f"X1 a y vcc 0 SN74LV1T34 {fmt(prm)}",
             "Cl y 0 15p"]
    deck.tran("0.01n", "120n", 0, "0.02n")
    deck.meas(f"tran tplh TRIG v(a) VAL={vcc / 2} RISE=1 TARG v(y) VAL={vcc / 2} RISE=1")
    deck.meas(f"tran tphl TRIG v(a) VAL={vcc / 2} FALL=1 TARG v(y) VAL={vcc / 2} FALL=1")
    res = deck.run()
    return res["tplh"] - LV_TD_MIN, res["tphl"] - LV_TD_MIN


def lv_params(vcc, vth_corner="mid", skew="none", typ_out=False):
    vih, vil = lv_vih(vcc), lv_vil(vcc)
    vth = {"vih": vih, "vil": vil, "mid": 0.5 * (vih + vil)}[vth_corner]
    rup, rdn = (LV_RUP, LV_RDN) if not typ_out else (50.0, 37.5)
    tpd = interp(LV_TPD, vcc)
    # internal delay so that the model tpd into 15 pF equals the 6.6 maximum (output-stage delay calibrated out)
    s_r, s_f = _lv_stage_delay(round(vcc, 4), rup, rdn)
    td_r = max(tpd - s_r, LV_TD_MIN)
    td_f = max(tpd - s_f, LV_TD_MIN)
    if skew == "rise_late":       # tPHL at its (unknown, 0) minimum, tPLH at max: high pulses shrink
        td_f = LV_TD_MIN
    elif skew == "fall_late":     # the opposite: high pulses stretch
        td_r = LV_TD_MIN
    return dict(VTH=vth, TDR=td_r, TDF=td_f, RUP=rup, RDN=rdn, TEDGE=LV_TEDGE, CI=LV_CI, CO=LV_CO)


def fmt(params):
    return " ".join(f"{k}={v:.6g}" for k, v in params.items())


_BASE = {}

DATA_NETS = ("LED_DIN_MCU", "LED_DIN_R", "LED_DIN")
RAILS = ("VLED", "+3V3", "GND")          # ideal sources in the deck
# the modelled IC pins on the data nets: (ref, pin) -> model
MODELLED_PINS = {("U10", "22"): "NRF52840_GPIO_* (P0.06)", ("D101", "3"): "WS2812C_DIN", ("U43", "2"): "SN74LV1T34 A",
                 ("U43", "4"): "SN74LV1T34 Y"}


def data_passives(d: Design, scale=None) -> list:
    """Every fitted R/C/L touching the data nets, including any to VLED / +3V3 (a pull-up or a wrong rail would
    otherwise be dropped silently by passives(nets=...)); parts that sit only across the ideal rails are skipped."""
    rail_only = [r for r in d.comps if r[0] in "RCL" and d.pins.get(r) and set(d.pins[r].values()) <= set(RAILS)]
    return d.passives(nets=set(DATA_NETS) | set(RAILS), scale=scale, exclude=rail_only)


def rewire(d: Design, ref: str, pin: str, net: str) -> Design:
    """Fault injection: move one pin of a part to another net (a wrong connection)."""
    old = d.pins[ref][pin]
    d.nets[old] = [x for x in d.nets[old] if not (x[0] == ref and x[1] == pin)]
    d.nets.setdefault(net, []).append((ref, pin, ""))
    d.pins[ref][pin] = net
    return d


def soft(check):
    """check() that records every row and collects the violations instead of stopping at the first one."""
    errs = []

    def _c(*a, **k):
        try:
            return check(*a, **k)
        except AssertionError as e:
            errs.append(str(e))
    return _c, errs


def fresh() -> Design:
    """An unmodified copy of the main-board design (parsed once)."""
    if "main" not in _BASE:
        _BASE["main"] = Design("main")
    return copy.deepcopy(_BASE["main"])


def build(d: Design, *, vsys, vdd_k=-1, mode="SD", skew="typ", ci=WS_CI, ii=WS_II, trace_scale=1.0,
          temp=None, lv=None, scale=None, din_r_line=False, fine=False, tedge_scale=1.0, title="LED data",
          drive="fit"):
    vled = vsys
    vdd = vdd_of(vsys, vdd_k)
    L = pcb_net_lengths()
    deck = Deck(f"{title}: VSYS {vsys:.3f} VDD {vdd:.3f} {mode}/{skew}")
    deck.include(GPIO_LIB)
    deck.include(DIN_LIB)
    if temp is not None:
        deck.options.append(f"option temp={temp}")
    deck.options.append("option method=gear")
    vled_n, vdd_n = d.node("VLED"), d.node("+3V3")
    deck += [f"VVLED {vled_n} 0 DC {vled:.6g}", f"VVDD {vdd_n} 0 DC {vdd:.6g}", f"VCTL ctl 0 {ctl_pwl()}"]
    pad = "n_p006_pad"
    prm = drive_params(mode, skew, temp)
    prm["TEDGE"] *= tedge_scale
    if drive == "bound":
        # PS-guaranteed: a side at the min column gets the weakest I-V the PS allows (constant IOH,min beyond a 0.4 V
        # drop); a side at the typ/max column keeps the fitted tanh shape (the fast edge of a skew corner)
        iu, idn = SKEW[skew]
        prm = dict(IOH=prm["IOH"], IOL=prm["IOL"], VKU=0 if iu == 0 else prm["VK"], VKD=0 if idn == 0 else prm["VK"],
                   TEDGE=prm["TEDGE"])
        deck += f"XP006 {pad} ctl {vdd_n} 0 NRF52840_GPIO_BOUND {fmt(prm)}"
    else:
        deck += f"XP006 {pad} ctl {vdd_n} 0 NRF52840_GPIO_OUT {fmt(prm)}"
    mcu, r_node, din = d.node("LED_DIN_MCU"), d.node("LED_DIN_R"), d.node("LED_DIN")
    _, _, cp = microstrip(track_width())
    deck += ladder("tmcu", pad, mcu, L["LED_DIN_MCU"][0] * trace_scale)
    if not din_r_line:
        # R40 sits next to U10 pad 22 (LED-DATA-1), so LED_DIN_R (R40 -> R41/R43/U43) is the long run; it is lumped
        # here: <= ~0.3 ns of line behind R40 = 220 R (>> Z0 ~83 R) next to edges of several ns
        deck += f"Ctr_r {r_node} 0 {cp * L['LED_DIN_R'][0] * trace_scale:.4g}"
    else:
        # the same run as an LC ladder, with R41/R43/U43 at its far end (cross-check of the lumped model)
        deck += ladder("tr", r_node, f"{r_node}_far", L["LED_DIN_R"][0] * trace_scale)
        r_node_far = f"{r_node}_far"
    passives = data_passives(d, scale=scale)
    if din_r_line:
        # move every LED_DIN_R connection except R40 to the far end of the long trace
        passives = [ln if ln.startswith("RR40 ") else
                    " ".join(r_node_far if tok == r_node else tok for tok in ln.split()) for ln in passives]
    deck += passives
    d101 = "n_d101_di"
    deck += ladder("tdin", din, d101, L["LED_DIN"][0] * trace_scale, n=3)
    deck += f"XD101 {d101} {vled_n} 0 WS2812C_DIN CI={ci:.6g} II={ii:.6g}"
    if d.fitted("U43"):
        deck.include(LV_LIB)
        a = d.pin("U43", "2")
        if din_r_line and a == r_node:
            a = r_node_far
        deck += (f"XU43 {a} {d.pin('U43', '4')} {d.pin('U43', '5')} {d.pin('U43', '3')} SN74LV1T34 "
                 f"{fmt(lv or lv_params(vled))}")
    # 1 ns max step resolves the threshold crossings to ~0.1 ns (checked against 0.1 ns); fine=True for ringing
    deck.tran(*(("0.1n", f"{T_STOP:.6g}", 0, "0.25n") if fine else ("1n", f"{T_STOP:.6g}", 0, "1n")))
    deck.wave(f"v({d101})", f"v({pad})", f"v({r_node})", f"v({din})")
    meta = dict(vsys=vsys, vled=vled, vdd=vdd, mode=mode, skew=skew if drive == "fit" else f"{skew}, PS bound",
                d101=d101, pad=pad, r_node=r_node, u43=d.fitted("U43"))
    return deck, meta


# ------------------------------------------------------------------------------------- waveform analysis
def crossings(t, v, level):
    above = v >= level
    idx = np.nonzero(above[1:] != above[:-1])[0]
    rise, fall = [], []
    for i in idx:
        tc = t[i] + (level - v[i]) * (t[i + 1] - t[i]) / (v[i + 1] - v[i])
        (rise if above[i + 1] else fall).append(tc)
    return rise, fall


def widths(t, v, level):
    """(highs, lows) of the data pattern at this receiver threshold, or None if the pattern is not reproduced."""
    m = t < T_DATA_END - 10e-9
    r, f = crossings(t[m], v[m], level)
    n = len(PATTERN)
    if len(r) != n or len(f) != n or any(not (a < b) for a, b in zip(r, f)):
        return None
    highs = [b - a for a, b in zip(r, f)]
    lows = [r[i + 1] - f[i] for i in range(n - 1)]
    return highs, lows


def analyse(res, meta):
    w = res["waves"]
    t = w["time"]
    v = w[f"v({meta['d101']})"]
    vp = w[f"v({meta['pad']})"]
    vr = w[f"v({meta['r_node']})"]
    vih = WS_VIH_PCN * meta["vled"]
    out = dict(meta)
    out["voh_dc"] = float(np.interp(T_DATA_END + T_HOLD_HI - 5e-9, t, v))
    out["vol_dc"] = float(np.interp(T_STOP - 5e-9, t, v))
    peaks = []
    for i, bit in enumerate(PATTERN):
        ts = T0 + i * TBIT
        sel = (t >= ts) & (t <= ts + TH[bit] + 30e-9)
        peaks.append(float(v[sel].max()))
    out["vhigh_dyn"] = min(peaks)      # lowest peak reached during any data high (the 312 ns "0" bits)
    out["vmax"], out["vmin"] = float(v.max()), float(v.min())
    out["pad_max"], out["pad_min"] = float(vp.max()), float(vp.min())
    lo_hi = {"T0H": [], "T1H": [], "T0L": [], "T1L": []}
    ok = True
    for lvl in (vih, WS_VIL):
        wv = widths(t, v, lvl)
        if wv is None:
            ok = False
            continue
        highs, lows = wv
        for bit, h in zip(PATTERN, highs):
            lo_hi["T1H" if bit == "1" else "T0H"].append(h)
        for bit, lw in zip(PATTERN[:-1], lows):
            lo_hi["T1L" if bit == "1" else "T0L"].append(lw)
    out["widths_ok"] = ok
    out["w"] = {k: ((min(x), max(x)) if x and ok else (None, None)) for k, x in lo_hi.items()}
    # 10-90 % edge times of the first "1" high at D101.DI (information)
    swing = out["voh_dc"] - out["vol_dc"]
    ts = T0 + TBIT
    sel = (t >= ts - 5e-9) & (t <= ts + TBIT - 5e-9)
    r, _ = crossings(t[sel], v[sel], out["vol_dc"] + 0.1 * swing)
    r9, _ = crossings(t[sel], v[sel], out["vol_dc"] + 0.9 * swing)
    _, f9 = crossings(t[sel], v[sel], out["vol_dc"] + 0.9 * swing)
    _, f1 = crossings(t[sel], v[sel], out["vol_dc"] + 0.1 * swing)
    out["t_rise"] = (r9[0] - r[0]) if r and r9 else None
    out["t_fall"] = (f1[-1] - f9[-1]) if f1 and f9 else None
    # LED_DIN_R input transition (for U43's dt/dv rule)
    sw_r = float(np.interp(T_DATA_END + T_HOLD_HI - 5e-9, t, vr))
    rr, ff = crossings(t[sel], vr[sel], 0.1 * sw_r)
    rr9, ff9 = crossings(t[sel], vr[sel], 0.9 * sw_r)
    out["dtdv_r"] = ((rr9[0] - rr[0]) / (0.8 * sw_r)) if rr and rr9 and sw_r > 0 else None
    out["dtdv_f"] = ((ff[-1] - ff9[-1]) / (0.8 * sw_r)) if ff and ff9 and sw_r > 0 else None
    return out


def run_checked(deck):
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    assert "waves" in res, res["_log"][-2000:]
    t = res["waves"]["time"]
    assert t[-1] >= 0.999 * T_STOP, "transient aborted:\n" + res["_log"][-1500:]
    return res


def simulate(d, **kw):
    deck, meta = build(d, **kw)
    return analyse(run_checked(deck), meta)


def run_many(jobs):
    """jobs: list of (Design, kwargs) -> list of analyses (ngspice runs in parallel processes)."""
    with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as ex:
        return list(ex.map(lambda j: simulate(j[0], **j[1]), jobs))


def worst(results, key, fn=min):
    vals = [(r[key], r) for r in results if r[key] is not None]
    return fn(vals, key=lambda x: x[0]) if vals else (None, None)


def label(r):
    return f"VSYS {r['vsys']:.2f} V, VDD {r['vdd']:.3f} V, {r['mode']}/{r['skew']}"


def check_widths(check, results, tag, source=SRC_WS_T):
    """Worst-case widths over all results against the WS2812C-2020-V6 windows."""
    for r in results:
        assert r["widths_ok"], f"{tag}: bit pattern not reproduced at D101.DI ({label(r)})"
    for name, (lo, hi) in (("T0H", T0H), ("T1H", T1H), ("T0L", TXL), ("T1L", TXL)):
        vmin, rmin = worst([dict(r, x=r["w"][name][0]) for r in results], "x", min)
        vmax, rmax = worst([dict(r, x=r["w"][name][1]) for r in results], "x", max)
        check(f"{tag}: {name} seen by D101, shortest ({label(rmin)})", vmin, lo, hi, "s", source)
        check(f"{tag}: {name} seen by D101, longest ({label(rmax)})", vmax, lo, hi, "s", source)


# ======================================================================================================== tests
def test_netlist_topology(main):
    """The chain the models are wired into must exist as assumed (guards the node mapping)."""
    assert main.pin("U10", "P0.06") == main.node("LED_DIN_MCU")
    assert {main.pin("R40", p) for p in "12"} == {main.node("LED_DIN_MCU"), main.node("LED_DIN_R")}
    assert {main.pin("R41", p) for p in "12"} == {main.node("LED_DIN_R"), "0"}
    assert {main.pin("R43", p) for p in "12"} == {main.node("LED_DIN_R"), main.node("LED_DIN")}
    assert main.pin("D101", "DIN") == main.node("LED_DIN") and main.pin("D101", "VDD") == main.node("VLED")
    assert main.pin("U43", "2") == main.node("LED_DIN_R") and main.pin("U43", "4") == main.node("LED_DIN")
    assert main.pin("U43", "5") == main.node("VLED") and main.pin("U43", "3") == "0"
    assert main.fitted("R43") and not main.fitted("U43") and not main.fitted("C43")
    assert "WS2812C-2020-V6" in main.mpn("D101") and "SN74LV1T34" in main.mpn("U43")


def test_netlist_coverage(main):
    """Every part on the data nets must be in the deck: a modelled IC pin, or a 2-pin R/C/L whose other pin is on a
    data net or an ideal rail (data_passives). passives(nets=...) would silently drop anything else."""
    allowed = set(DATA_NETS) | set(RAILS)
    emitted = {ln.split()[0][1:].split("_short")[0] for ln in data_passives(main)}   # "RR40 ..." -> R40
    for net in DATA_NETS:
        for ref, pin, _ in main.nets[net]:
            if (ref, pin) in MODELLED_PINS:
                continue
            assert ref[0] in "RCL" and ref[1:2].isdigit(), f"{ref}.{pin} on {net} has no model in the LED data deck"
            others = set(main.pins[ref].values())
            assert others <= allowed, f"{ref} connects {net} to {others - allowed}, which the deck does not model"
            if main.fitted(ref):
                assert ref in emitted, f"{ref} on {net} is fitted but missing from the deck"


@pytest.mark.parametrize("mode", ["SD", "HD"])
def test_gpio_model_reproduces_ps_tables(check, mode):
    """The output-stage fit must reproduce the PS IOH/IOL points (DC) and the tRF table (typ, VDD 3.0 V)."""
    p = DRIVE[mode]
    for cl, t_ps in p["trf"].items():
        deck = Deck(f"nRF GPIO {mode} tRF {cl}")
        deck.include(GPIO_LIB)
        deck += ["Vdd vdd 0 3.0", "Vc ctl 0 PULSE(0 1 5n 1p 1p 100n 200n)",
                 f"X1 out ctl vdd 0 NRF52840_GPIO_OUT {fmt(drive_params(mode, 'typ'))}", f"Cl out 0 {cl}"]
        deck.tran("0.01n", "200n", 0, "0.02n")
        deck.meas("tran tr TRIG v(out) VAL=0.3 RISE=1 TARG v(out) VAL=2.7 RISE=1")
        deck.meas("tran tf TRIG v(out) VAL=2.7 FALL=1 TARG v(out) VAL=0.3 FALL=1")
        res = deck.run()
        check(f"{mode} model 10-90 % edge into {cl * 1e12:.0f} pF vs PS {t_ps * 1e9:.0f} ns (typ)",
              0.5 * (res["tr"] + res["tf"]), 0.8 * t_ps, 1.2 * t_ps, "s", SRC_PS_GPIO + " tRF/tHRF (fit +/-20 %)")
    for col, nm in ((0, "min"), (2, "max")):
        deck = Deck(f"nRF GPIO {mode} DC {nm}")
        deck.include(GPIO_LIB)
        prm = drive_params(mode, "weak" if col == 0 else "strong")
        deck += ["Vdd vdd 0 3.0", "Vc ctl 0 1", f"X1 out ctl vdd 0 NRF52840_GPIO_OUT {fmt(prm)}",
                 "Vm out 0 2.6", "Vc2 ctl2 0 0", f"X2 out2 ctl2 vdd 0 NRF52840_GPIO_OUT {fmt(prm)}", "Vm2 out2 0 0.4"]
        deck.op()
        deck.print_op("i(Vm)", "-i(Vm2)")
        res = deck.run()
        check(f"{mode} model IOH at VDD-0.4 V ({nm} corner)", res["op_0"], p["ioh"][col] * 0.99,
              p["ioh"][col] * 1.01, "A", SRC_PS_GPIO + f" IOH {nm}")
        check(f"{mode} model IOL at VSS+0.4 V ({nm} corner)", res["op_1"], p["iol"][col] * 0.99,
              p["iol"][col] * 1.01, "A", SRC_PS_GPIO + f" IOL {nm}")


@pytest.fixture(scope="module")
def corner_sweep():
    """Default design (R43 fitted, U43 DNP) over every VSYS corner x VDD +/-2 % x drive x skewed corners."""
    jobs = []
    for _, vsys in SUPPLY:
        for k in (-1, 1):
            for mode in ("SD", "HD"):
                for skew in ("slow_rise", "slow_fall"):   # slow_rise holds the min IOH (lowest high level)
                    jobs.append((fresh(), dict(vsys=vsys, vdd_k=k, mode=mode, skew=skew)))
    return run_many(jobs)


def test_r27_high_level_margin_per_supply(check, corner_sweep):
    """R27 quantified: DI high level vs VIH at every VSYS the charger delivers (worst corner per VSYS)."""
    for lab, vsys in SUPPLY:
        rs = [r for r in corner_sweep if abs(r["vsys"] - vsys) < 1e-9]
        v, r = worst(rs, "voh_dc", min)
        check(f"DC high at D101.DI - 0.6 VDD, {lab} ({label(r)})", v - WS_VIH_PCN * vsys, 0.0, None, "V", SRC_PCN)
        check(f"DC high at D101.DI - 0.55 VDD, {lab}", v - WS_VIH_DS * vsys, 0.0, None, "V",
              SRC_WS_EC + " VIH")
        vd, rd = worst(rs, "vhigh_dyn", min)
        check(f"peak during 312 ns T0H - 0.6 VDD, {lab} ({label(rd)})", vd - WS_VIH_PCN * vsys, 0.0, None, "V",
              SRC_PCN)
        # what architecture.md R27 assumed: the PS table point VOH >= VDD - 0.4 V (valid for loads <= 0.5 mA), here
        # with the DC load (R41 + DI leakage) and the series drop (R40 + R43) taken from the netlist
        d = fresh()
        voh = vdd_of(vsys, -1) - 0.4
        i_load = voh / d.value("R41") + WS_II
        check(f"P0.06 DC load when high <= 0.5 mA (VOH,SD test condition), {lab}", i_load, None, 0.5e-3, "A",
              SRC_PS_GPIO + " VOH,SD")
        v_di = voh - i_load * (d.value("R40") + d.value("R43"))
        check(f"PS-table bound (VOH = VDD-0.4 V, minus R40/R43 drop) - 0.6 VDD, {lab}", v_di - WS_VIH_PCN * vsys, 0.0,
              None, "V", SRC_PS_GPIO + " VOH,SD + " + SRC_PCN)
        check(f"(info) DC high - 0.7 VDD legacy pre-V6 threshold, {lab}", v - WS_VIH_LEGACY * vsys, None, None, "V",
              "legacy WS2812B VIH 0.7 VDD - not the fitted V6 part's limit")
        check(f"(info) VLED - LED rated VDD min, {lab}", vsys - WS_VDD_MIN, None, None, "V",
              SRC_WS + " p.2 VDD +3.3 ... +5.3 V (LED supply, not the data line)")


def test_low_level_and_abs_max(check, corner_sweep):
    v, r = worst(corner_sweep, "vol_dc", max)
    check(f"DC low at D101.DI ({label(r)})", v, None, WS_VIL, "V", SRC_WS_EC + " VIL")
    v, r = worst([dict(x, m=x["vmax"] - x["vled"]) for x in corner_sweep], "m", max)
    check(f"D101.DI max - VDD ({label(r)})", v, None, WS_VI_OVER, "V", SRC_WS_AMR)
    v, r = worst(corner_sweep, "vmin", min)
    check(f"D101.DI min ({label(r)})", v, WS_VI_MIN, None, "V", SRC_WS_AMR)
    v, r = worst([dict(x, m=x["pad_max"] - x["vdd"]) for x in corner_sweep], "m", max)
    check(f"P0.06 pad max - VDD ({label(r)})", v, None, NRF_VIO_OVER, "V", SRC_PS_AMR)
    v, r = worst(corner_sweep, "pad_min", min)
    check(f"P0.06 pad min ({label(r)})", v, -0.3, None, "V", SRC_PS_AMR)


@pytest.mark.parametrize("mode", ["SD", "HD"])
def test_pulse_widths_at_led(check, corner_sweep, mode):
    """T0H/T1H/T0L/T1L after slewing, worst case over VIL...VIH receiver thresholds and all supply corners."""
    rs = [r for r in corner_sweep if r["mode"] == mode]
    check_widths(check, rs, f"{mode} drive")
    v, r = worst(rs, "t_rise", max)
    check(f"(info) {mode} 10-90 % rise at D101.DI, slowest ({label(r)})", v, None, None, "s", "simulation")
    v, r = worst(rs, "t_fall", max)
    check(f"(info) {mode} 10-90 % fall at D101.DI, slowest ({label(r)})", v, None, None, "s", "simulation")


def test_tolerance_extremes(check):
    """R40 / R41 at their 1 % extremes (2^2 corners) at the worst supply corner, both drives, both skews."""
    d0 = fresh()
    refs = [r for r in ("R40", "R41") if d0.fitted(r)]
    jobs = []
    for sc in d0.extremes(refs):
        for mode in ("SD", "HD"):
            for skew in ("slow_rise", "slow_fall"):
                jobs.append((fresh(), dict(vsys=VSYS_MAX, vdd_k=-1, mode=mode, skew=skew, scale=sc)))
    rs = run_many(jobs)
    v, r = worst(rs, "voh_dc", min)
    check(f"tol. extremes: DC high - 0.6 VDD at VSYS {VSYS_MAX:.2f} V", v - WS_VIH_PCN * VSYS_MAX, 0.0, None, "V",
          SRC_PCN)
    check_widths(check, rs, "tol. extremes")


@pytest.mark.parametrize("temp", [-10, 25, 60])
def test_temperature(check, temp):
    """Typical part at -10 / 25 / 60 C (drive strength ~ mobility, inside the PS envelope; .temp for diodes)."""
    rs = run_many([(fresh(), dict(vsys=VSYS_MAX, vdd_k=-1, mode=m, skew="typ", temp=temp)) for m in ("SD", "HD")])
    v, r = worst(rs, "voh_dc", min)
    check(f"{temp} C: DC high - 0.6 VDD at VSYS {VSYS_MAX:.2f} V", v - WS_VIH_PCN * VSYS_MAX, 0.0, None, "V", SRC_PCN)
    check_widths(check, rs, f"{temp} C")


def test_load_extremes(check):
    """DI capacitance 1 / 15 pF, leakage +/-1 uA, traces x1 / x2, weakest standard drive at VSYS max."""
    jobs = []
    for ci in (1e-12, WS_CI):
        for ii in (WS_II, -WS_II):
            for ts in (1.0, 2.0):
                for skew in ("slow_rise", "slow_fall"):
                    jobs.append((fresh(), dict(vsys=VSYS_MAX, vdd_k=-1, mode="SD", skew=skew, ci=ci, ii=ii,
                                                     trace_scale=ts)))
    rs = run_many(jobs)
    v, r = worst(rs, "voh_dc", min)
    check(f"load extremes: DC high - 0.6 VDD at VSYS {VSYS_MAX:.2f} V", v - WS_VIH_PCN * VSYS_MAX, 0.0, None, "V",
          SRC_PCN)
    check_widths(check, rs, "load extremes")
    v, r = worst([dict(x, m=x["pad_max"] - x["vdd"]) for x in rs], "m", max)
    check("load extremes: P0.06 pad max - VDD", v, None, NRF_VIO_OVER, "V", SRC_PS_AMR)


def test_trace_and_r40_placement(check):
    """R40 as placed: next to U10 pad 22 (P0.06), 0.25 mm from it (fix LED-DATA-1, a layout.py pin anchor), so
    LED_DIN_MCU is ~1 mm and the 40-50 mm run is LED_DIN_R (R40 -> R41/R43/U43 at the LED end).  That run is checked
    both lumped (the model of every other test here) and as an LC ladder with its loads at the far end; strongest
    drive, lightest load (most ringing), plus a fast-corner sensitivity beyond the PS fit (pre-driver 2x faster than
    the strong corner, traces x2)."""
    L = pcb_net_lengths()
    z0, _, _ = microstrip(track_width())
    for net in ("LED_DIN_MCU", "LED_DIN_R"):
        length, routed = L[net]
        check(f"(info) {net} length ({'routed' if routed else 'placed, est.'}), Z0 {z0:.0f} ohm", length, None,
              None, "m", "kicad_pcb")
    for line, tes, ts in ((False, 1.0, 1.0), (True, 1.0, 1.0), (False, 0.5, 2.0), (True, 0.5, 2.0)):
        rs = run_many([(fresh(), dict(vsys=v, vdd_k=1, mode="HD", skew="strong", ci=1e-12, ii=-WS_II,
                                       din_r_line=line, fine=True, tedge_scale=tes, trace_scale=ts))
                       for v in (3.0, VSYS_MAX)])
        tag = ("R40 as placed, LED_DIN_R as an LC line" if line else "R40 as placed, LED_DIN_R lumped") + (
            ", TEDGE/2 + traces x2 (sensitivity)" if tes != 1.0 else "")
        v, r = worst([dict(x, m=x["pad_max"] - x["vdd"]) for x in rs], "m", max)
        check(f"{tag}: P0.06 pad max - VDD", v, None, NRF_VIO_OVER, "V", SRC_PS_AMR)
        v, r = worst(rs, "pad_min", min)
        check(f"{tag}: P0.06 pad min", v, -0.3, None, "V", SRC_PS_AMR)
        v, r = worst([dict(x, m=x["vmax"] - x["vled"]) for x in rs], "m", max)
        check(f"{tag}: D101.DI max - VDD", v, None, WS_VI_OVER, "V", SRC_WS_AMR)
        check_widths(check, rs, tag)


# ----------------------------------------------------------------------------------------- U43 option
def u43_design():
    return fresh().fit("U43").fit("C43").remove("R43")


def test_lv1t34_model_tpd_matches_ds(check):
    """Model tpd A->Y into 15 pF must sit at the 6.6 maximum (not faster), both edges, VCC 3.3 and 5.0 V."""
    for vcc in (3.3, 5.0):
        deck = Deck(f"LV1T34 tpd {vcc}")
        deck.include(LV_LIB)
        deck += [f"Vcc vcc 0 {vcc}", f"Va a 0 PULSE(0 {vcc} 5n 1p 1p 50n 100n)",
                 f"X1 a y vcc 0 SN74LV1T34 {fmt(lv_params(vcc, 'mid'))}", "Cl y 0 15p"]
        deck.tran("0.01n", "120n", 0, "0.02n")
        h = vcc / 2
        deck.meas(f"tran tplh TRIG v(a) VAL={h} RISE=1 TARG v(y) VAL={h} RISE=1")
        deck.meas(f"tran tphl TRIG v(a) VAL={h} FALL=1 TARG v(y) VAL={h} FALL=1")
        res = deck.run()
        tpd = interp(LV_TPD, vcc)
        for k in ("tplh", "tphl"):
            check(f"LV1T34 model {k} at VCC {vcc} V, 15 pF (calibrated to tpd max, +/-1 % numerics)", res[k],
                  0.95 * tpd, 1.01 * tpd, "s", SRC_LV + " 6.6 tpd max")


@pytest.fixture(scope="module")
def u43_sweep():
    """U43 fitted / R43 removed: every VSYS at mid threshold (levels), plus threshold x tpd-skew x drive corners
    at the lowest and highest VLED (pulse widths)."""
    jobs = []
    for _, vsys in SUPPLY:
        jobs.append((u43_design(), dict(vsys=vsys, vdd_k=-1, mode="SD", skew="slow_rise", lv=lv_params(vsys))))
    for vsys in (SUPPLY[0][1], VSYS_MAX):
        for vth in ("vil", "vih"):
            for skew in ("rise_late", "fall_late"):
                for mode, dskew in (("SD", "slow_rise"), ("HD", "strong")):
                    jobs.append((u43_design(), dict(vsys=vsys, vdd_k=-1, mode=mode, skew=dskew,
                                                    lv=lv_params(vsys, vth, skew))))
    return run_many(jobs)


def test_u43_option_levels(check, u43_sweep):
    """With U43 fitted: its input sees the nRF levels, its output gives D101 a rail-to-rail VLED swing."""
    for lab, vsys in SUPPLY:
        rs = [r for r in u43_sweep if abs(r["vsys"] - vsys) < 1e-9]
        v, r = worst(rs, "voh_dc", min)
        check(f"U43: DC high at D101.DI - 0.6 VDD, {lab}", v - WS_VIH_PCN * vsys, 0.0, None, "V", SRC_PCN)
        check(f"(info) U43: DC high - 0.7 VDD legacy threshold, {lab}", v - WS_VIH_LEGACY * vsys, None, None, "V",
              "legacy WS2812B VIH 0.7 VDD")
    v, r = worst(u43_sweep, "vol_dc", max)
    check("U43: DC low at D101.DI", v, None, WS_VIL, "V", SRC_WS_EC + " VIL")
    v, r = worst([dict(x, m=x["vmax"] - x["vled"]) for x in u43_sweep], "m", max)
    check("U43: D101.DI max - VDD", v, None, WS_VI_OVER, "V", SRC_WS_AMR)
    v, r = worst(u43_sweep, "vmin", min)
    check("U43: D101.DI min", v, WS_VI_MIN, None, "V", SRC_WS_AMR)


def test_u43_input_conditions(check):
    """U43 A pin (LED_DIN_R): DC levels vs the LV1T34 VIH/VIL at VCC = VLED, and the dt/dv rule."""
    jobs = [(u43_design(), dict(vsys=vsys, vdd_k=-1, mode="SD", skew="weak")) for _, vsys in SUPPLY]
    rs = run_many(jobs)
    # high level at A from a DC operating point (P0.06 high, weakest standard drive)
    for _, vsys in SUPPLY:
        d = u43_design()
        vdd = vdd_of(vsys, -1)
        deck = Deck(f"U43 A level {vsys}")
        deck.include(GPIO_LIB)
        deck.include(DIN_LIB)
        deck.include(LV_LIB)
        deck += [f"VVLED {d.node('VLED')} 0 {vsys}", f"VVDD {d.node('+3V3')} 0 {vdd}", "Vc ctl 0 1", "Vc0 ctl0 0 0",
                 f"X1 {d.node('LED_DIN_MCU')} ctl {d.node('+3V3')} 0 NRF52840_GPIO_OUT {fmt(drive_params('SD', 'weak'))}"]
        deck += data_passives(d)
        deck += f"XU43 {d.pin('U43', '2')} {d.pin('U43', '4')} {d.node('VLED')} 0 SN74LV1T34 {fmt(lv_params(vsys))}"
        deck += f"XD {d.node('LED_DIN')} {d.node('VLED')} 0 WS2812C_DIN"
        deck.op()
        deck.print_op(f"v({d.node('LED_DIN_R')})")
        hi = deck.run()["op_0"]
        check(f"U43 A high - VIH(VCC={vsys:.2f} V)", hi - lv_vih(vsys), 0.0, None, "V", SRC_LV + " 6.5 VIH")
        check(f"U43 A high <= VI max (VCC={vsys:.2f} V)", hi, None, 5.5, "V", SRC_LV + " 6.3 VI")
    v, r = worst(rs, "dtdv_r", max)
    check(f"U43 A rise rate ({label(r)})", v, None, LV_DTDV, "s/V", SRC_LV + " 6.3 dt/dv")
    v, r = worst(rs, "dtdv_f", max)
    check(f"U43 A fall rate ({label(r)})", v, None, LV_DTDV, "s/V", SRC_LV + " 6.3 dt/dv")
    v, r = worst(rs, "vol_dc", max)
    check("U43 Y low at D101.DI", v, None, WS_VIL, "V", SRC_WS_EC + " VIL")


def test_u43_option_pulse_widths(check, u43_sweep):
    check_widths(check, u43_sweep, "U43 fitted")


# ------------------------------------------------------------------------- PS-guaranteed drive (verifier)
BOUND_SD_REASON = (
    "DESIGN ISSUE (firmware-dependent, LED-DATA-V1): with only the drive the nRF52840 PS guarantees (IOH/IOL,SD >= "
    "1 mA at a 0.4 V drop, PS v1.1 6.9.3.1; tRF is typical-only) standard drive (S0S1, the Zephyr/nrfx pinctrl "
    "default) cannot guarantee the WS2812C-2020-V6 windows: T1H down to ~549 ns (< 580 ns), T0L up to ~1014 ns "
    "(> 1 us), T1L down to ~560 ns at VSYS 4.59 V, CI 15 pF, traces x1-x2; with U43 fitted T1H ~577 ns, T1L ~569 ns "
    "and U43.A dt/dv ~21.5 ns/V (> 20 ns/V, SCLS743E 6.3). High drive (H0H1) passes both paths (T1H >= ~606 ns, "
    "T0L <= ~957 ns, T1L >= ~605 ns, dt/dv <= ~5.7 ns/V). The rule is now REQUIRED "
    "by docs/firmware.md 3.1 (i2s0_default) / 6.1 and SPEC 5.4: nordic,drive-mode = NRF_DRIVE_H0H1 on P0.06 "
    "(I2S0 SDOUT); the [HD] case of this test is its guard.")
FW_RULE_V1 = ("firmware rule LED-DATA-V1 (docs/firmware.md 3.1 / 6.1, SPEC 5.4): P0.06 nordic,drive-mode = "
              "NRF_DRIVE_H0H1")


def bound_jobs(mode):
    jobs = []
    for vsys in (SUPPLY[0][1], VSYS_MAX):
        for ts in (1.0, 2.0):
            for skew in ("weak", "slow_rise", "slow_fall"):
                jobs.append((fresh(), dict(vsys=vsys, vdd_k=-1, mode=mode, skew=skew, trace_scale=ts, drive="bound")))
        # U43 option at the longer (slower) trace only: threshold x tpd-skew corners that stretch / shrink highs
        for skew, vth, lsk in (("slow_rise", "vih", "rise_late"), ("slow_rise", "vil", "rise_late"),
                               ("slow_fall", "vil", "fall_late"), ("slow_fall", "vih", "fall_late"),
                               ("weak", "vih", "rise_late"), ("weak", "vil", "fall_late")):
            jobs.append((u43_design(), dict(vsys=vsys, vdd_k=-1, mode=mode, skew=skew, trace_scale=2.0,
                                            drive="bound", lv=lv_params(vsys, vth, lsk), title="U43")))
    return jobs


@pytest.mark.parametrize("mode", ["HD", pytest.param("SD", marks=pytest.mark.xfail(strict=True,
                                                                                    reason=BOUND_SD_REASON))])
def test_pulse_widths_ps_guaranteed_drive(check, mode):
    """The P0.06 drive the PS GUARANTEES (min column with the weakest concave I-V, NRF52840_GPIO_BOUND), CI 15 pF,
    VSYS 3.0 / 4.59 V, default path (traces x1 / x2) and U43 option (traces x2, threshold x tpd-skew corners).
    [SD] (standard drive, the old pinctrl default) is the strict-xfail evidence for firmware rule LED-DATA-V1; [HD]
    is its guard: the same corners and limits with P0.06 at H0H1, as docs/firmware.md 3.1 / 6.1 and SPEC 5.4 require.
    The other LED data rules are applied in every case: exact 3.2 MHz SCK = HFXO clocking (LED-DATA-V2) and VSYS up
    to 4.5 V + 2 %, the highest SYS_REG firmware allows (LED-DATA-V3)."""
    rs = run_many(bound_jobs(mode))
    c, errs = soft(check)
    default = [r for r in rs if not r.get("u43")]
    u43 = [r for r in rs if r.get("u43")]
    pm = f"PS-guaranteed {mode}" + (" (fw rule LED-DATA-V1: H0H1)" if mode == "HD" else " (old pinctrl default)")
    rule = ("; " + FW_RULE_V1) if mode == "HD" else ""
    v, r = worst([dict(x, m=x["voh_dc"] - WS_VIH_PCN * x["vled"]) for x in default], "m", min)
    c(f"{pm}: DC high at D101.DI - 0.6 VDD ({label(r)})", v, 0.0, None, "V", SRC_PCN + rule)
    for tag, sel in ((f"{pm}, default path", default), (f"{pm}, U43 fitted", u43)):
        if not all(x["widths_ok"] for x in sel):
            errs.append(f"{tag}: bit pattern not reproduced")
            continue
        check_widths(c, sel, tag, source=SRC_WS_T + rule)
    v, r = worst(u43, "dtdv_r", max)
    c(f"{pm}, U43 fitted: A rise rate ({label(r)})", v, None, LV_DTDV, "s/V", SRC_LV + " 6.3 dt/dv" + rule)
    v, r = worst(u43, "dtdv_f", max)
    c(f"{pm}, U43 fitted: A fall rate ({label(r)})", v, None, LV_DTDV, "s/V", SRC_LV + " 6.3 dt/dv" + rule)
    assert not errs, "\n".join(errs)


# ------------------------------------------------------------- P0.06 high-Z: R41 holds DI low (verifier)
SRC_R41 = "sheets/leds.py 'LED data input': 100k pull-down holds DIN low while P0.06 is high-Z (reset/DFU)"


def hiz_levels(d: Design, vsys: float, ii: float) -> dict:
    """DC levels with P0.06 high-Z (PIN_CNF reset value) and VLED on, D101 / U43 input leakage = ii."""
    deck = Deck(f"P0.06 high-Z, VSYS {vsys}, II {ii}")
    deck.include(GPIO_LIB)
    deck.include(DIN_LIB)
    vdd = vdd_of(vsys, -1)
    deck += [f"VVLED {d.node('VLED')} 0 {vsys}", f"VVDD {d.node('+3V3')} 0 {vdd}",
             f"XP006 {d.node('LED_DIN_MCU')} {d.node('+3V3')} 0 NRF52840_GPIO_HIZ"]
    deck += data_passives(d)
    deck += f"XD101 {d.node('LED_DIN')} {d.node('VLED')} 0 WS2812C_DIN CI={WS_CI:.6g} II={ii:.6g}"
    if d.fitted("U43"):
        deck.include(LV_LIB)
        prm = dict(lv_params(vsys), II=ii)
        deck += (f"XU43 {d.pin('U43', '2')} {d.pin('U43', '4')} {d.pin('U43', '5')} {d.pin('U43', '3')} SN74LV1T34 "
                 f"{fmt(prm)}")
    deck.op()
    deck.print_op(f"v({d.node('LED_DIN')})", f"v({d.node('LED_DIN_R')})")
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    return dict(di=res["op_0"], a=res["op_1"])


def test_p006_hiz_din_held_low(check):
    """P0.06 not driven (reset, DFU, I2S stopped before the pin is parked low) while VLED is on: R41 must keep
    D101.DI below VIL against the worst-case +/-1 uA input leakage (and U43.A below the LV1T34 VIL)."""
    rows = []
    for vsys in (SUPPLY[0][1], VSYS_MAX):
        for ii in (WS_II, -WS_II):
            rows.append((vsys, ii, hiz_levels(fresh(), vsys, ii), hiz_levels(u43_design(), vsys, ii)))
    v = max(r[2]["di"] for r in rows)
    check("P0.06 high-Z: D101.DI max (R41 vs II +/-1 uA)", v, None, WS_VIL, "V", SRC_WS_EC + " VIL, II; " + SRC_R41)
    v = min(r[2]["di"] for r in rows)
    check("P0.06 high-Z: D101.DI min", v, WS_VI_MIN, None, "V", SRC_WS_AMR)
    for vsys, ii, _, u in rows:
        check(f"U43 fitted, P0.06 high-Z: U43.A - VIL(VCC={vsys:.2f} V), II {ii * 1e6:+.0f} uA", u["a"] - lv_vil(vsys),
              None, 0.0, "V", SRC_LV + " 6.5 VIL, II; " + SRC_R41)
    v = max(r[3]["di"] for r in rows)
    check("U43 fitted, P0.06 high-Z: D101.DI (Y) max", v, None, WS_VIL, "V", SRC_WS_EC + " VIL")


# ------------------------------------------------------------------------------------------ fault injection
def detected(check, name, value, limit_lo, limit_hi, unit, source):
    """Record that a faulted design VIOLATES the limit (value outside [lo, hi] or not measurable): 1 = detected."""
    viol = value is None or (limit_lo is not None and value < limit_lo) or (limit_hi is not None and value > limit_hi)
    shown = "not reproduced" if value is None else spicelib.eng(value, unit)
    lim = " ... ".join("-" if x is None else spicelib.eng(x, unit) for x in (limit_lo, limit_hi))
    check(f"FAULT DETECTED: {name} (faulted value {shown}, limit {lim})", 1.0 if viol else 0.0, 1.0, None, "",
          source)


@pytest.mark.fault
def test_fault_r41_wrong_value(check):
    """R41 fitted as 100 R instead of 100 k: the R40/R41 divider kills the high level -> VIH check must fail."""
    r = simulate(fresh().override("R41", "100"), vsys=VSYS_MAX, vdd_k=-1, mode="SD", skew="weak")
    detected(check, "R41 = 100 R: DC high at D101.DI - 0.6 VDD >= 0", r["voh_dc"] - WS_VIH_PCN * VSYS_MAX, 0.0, None,
             "V", SRC_PCN)


@pytest.mark.fault
def test_fault_u43_fitted_r43_left_on(check):
    """U43 fitted but R43 not removed: Y is shorted to A through 0 R, the buffer latches and fights P0.06."""
    d = fresh().fit("U43").fit("C43")
    r = simulate(d, vsys=VSYS_MAX, vdd_k=-1, mode="HD", skew="strong", lv=lv_params(VSYS_MAX, "mid"))
    detected(check, "U43 + R43 both fitted: bit pattern reproduced at D101.DI",
             1.0 if r["widths_ok"] else None, 1.0, None, "", SRC_WS_T)


@pytest.mark.fault
def test_fault_r43_removed_u43_not_fitted(check):
    """R43 removed but U43 not fitted (half the rework): D101.DI floats -> no data high."""
    r = simulate(fresh().remove("R43"), vsys=4.2, vdd_k=1, mode="HD", skew="strong")
    detected(check, "R43 removed, no U43: DC high at D101.DI - 0.6 VDD >= 0", r["voh_dc"] - WS_VIH_PCN * 4.2, 0.0,
             None, "V", SRC_PCN)


@pytest.mark.fault
def test_fault_r40_wrong_value(check):
    """R40 fitted as 220 k instead of 220 R: RC = 220 k x ~17 pF swallows the 312 ns T0H and divides with R41."""
    r = simulate(fresh().override("R40", "220k"), vsys=4.2, vdd_k=1, mode="HD", skew="strong")
    detected(check, "R40 = 220 k: T0H shortest within window", r["w"]["T0H"][0] if r["widths_ok"] else None,
             T0H[0], T0H[1], "s", SRC_WS_T)


@pytest.mark.fault
def test_fault_r41_left_off(check):
    """R41 left off: invisible while P0.06 drives the line, but with P0.06 high-Z the DI leakage (-1 uA, out of
    the pin) pulls D101.DI up to the clamp -> the high-Z hold-low check must fail (verifier mutation)."""
    v = max(hiz_levels(fresh().remove("R41"), VSYS_MAX, ii)["di"] for ii in (WS_II, -WS_II))
    detected(check, "R41 left off: P0.06 high-Z, D101.DI <= VIL", v, None, WS_VIL, "V", SRC_WS_EC + " VIL; " + SRC_R41)


@pytest.mark.fault
def test_fault_r41_to_vled(check):
    """Wrong connection: R41 pin 2 on VLED instead of GND (a pull-up). passives(nets=...) without the rails would
    drop R41 silently; data_passives keeps it and the high-Z check must fail (verifier mutation)."""
    d = rewire(fresh(), "R41", "2", "VLED")
    v = max(hiz_levels(d, VSYS_MAX, ii)["di"] for ii in (WS_II, -WS_II))
    detected(check, "R41 to VLED: P0.06 high-Z, D101.DI <= VIL", v, None, WS_VIL, "V", SRC_WS_EC + " VIL; " + SRC_R41)


@pytest.mark.fault
def test_fault_r40_ten_times(check):
    """R40 fitted as 2.2 k (one decade off): the R40 x C(DI + trace) edge eats the T1H window (verifier mutation)."""
    r = simulate(fresh().override("R40", "2.2k"), vsys=VSYS_MAX, vdd_k=-1, mode="HD", skew="slow_rise")
    detected(check, "R40 = 2.2 k: T1H shortest within window", r["w"]["T1H"][0] if r["widths_ok"] else None,
             T1H[0], T1H[1], "s", SRC_WS_T)


@pytest.mark.fault
def test_fault_c43_on_led_din(check):
    """Wrong connection with a DNP part fitted: C43 (100 nF) placed from LED_DIN to GND instead of VLED to GND
    (verifier mutation) -> the bit pattern cannot reach D101.DI."""
    d = rewire(fresh().fit("C43"), "C43", "1", "LED_DIN")
    r = simulate(d, vsys=VSYS_MAX, vdd_k=-1, mode="HD", skew="strong")
    detected(check, "C43 on LED_DIN: bit pattern reproduced at D101.DI", 1.0 if r["widths_ok"] else None, 1.0, None,
             "", SRC_WS_T)


# ------------------------------------------------------------------------------------------ Monte Carlo
@pytest.mark.slow
def test_monte_carlo(check):
    """200 draws: R40/R41 within tolerance, IOH/IOL uniform inside the PS envelope, CI 1-15 pF, II +/-1 uA,
    trace x0.8-2, VSYS uniform 4.41-4.59 V on USB, VDD uniform -3 % ... +2 % (RT9080 accuracy + load regulation),
    both drive modes."""
    import random
    rng = random.Random(27)
    d0 = fresh()
    jobs = []
    for i, sc in enumerate(d0.monte_carlo(["R40", "R41"], 200, seed=27)):
        mode = "SD" if i % 2 == 0 else "HD"
        p = DRIVE[mode]
        ioh = rng.uniform(p["ioh"][0], p["ioh"][2])
        iol = rng.uniform(p["iol"][0], p["iol"][2])
        vsys = rng.uniform(SYS_REG * (1 - SYS_ACC), VSYS_MAX)
        kw = dict(vsys=vsys, vdd_k=0, mode=mode, skew="typ", ci=rng.uniform(1e-12, WS_CI),
                  ii=rng.uniform(-WS_II, WS_II), trace_scale=rng.uniform(0.8, 2.0), scale=sc)
        jobs.append((fresh(), kw, ioh, iol, rng.uniform(VDD_LO, VDD_HI)))

    def one(j):
        d, kw, ioh, iol, kv = j
        deck, meta = build(d, **kw)
        vdd = kv
        prm = dict(IOH=ioh, IOL=iol, VK=DRIVE[kw["mode"]]["vk"],
                   TEDGE=DRIVE[kw["mode"]]["tedge"] * 0.5 * (DRIVE[kw["mode"]]["ioh"][1] / ioh +
                                                           DRIVE[kw["mode"]]["iol"][1] / iol))
        deck.lines = [ln if not ln.startswith("XP006") else
                      f"XP006 n_p006_pad ctl {d.node('+3V3')} 0 NRF52840_GPIO_OUT {fmt(prm)}" for ln in deck.lines]
        deck.lines = [ln if not ln.startswith("VVDD") else f"VVDD {d.node('+3V3')} 0 DC {vdd:.6g}"
                      for ln in deck.lines]
        meta["vdd"] = vdd
        meta["skew"] = f"MC IOH {ioh * 1e3:.2f} mA IOL {iol * 1e3:.2f} mA"
        return analyse(run_checked(deck), meta)

    with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as ex:
        rs = list(ex.map(one, jobs))
    v, r = worst([dict(x, m=x["voh_dc"] - WS_VIH_PCN * x["vled"]) for x in rs], "m", min)
    check("MC 200: DC high - 0.6 VDD, worst draw", v, 0.0, None, "V", SRC_PCN)
    check_widths(check, rs, "MC 200")
