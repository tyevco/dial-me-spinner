"""USB input of the base board, simulated from the real netlists.

Circuit: USB-C J1 VBUS -> SMF5.0A (D1) + USBLC6-2SC6 (U2, VBUS pin) -> BQ25180 IN (U1) with C1, and
VBUS / D+ / D- on through the 12-way link harness to the nRF52840 module (main U10, C12 on VBUS).
CC: one 5.1 k Rd per CC pin (R1, R2).

Angles covered
  * hot plug of a legacy (hot VBUS) cable, 1-2 m, 0.5-1 uH/m, 50-100 mOhm, from a 4.5 / 5.0 / 5.25 / 5.5 V
    source with 10 uF or 120 uF bulk, into C1 and C12 with DC-bias derating, at -10 / 25 / 60 C and over
    the C1/C12 tolerance extremes; peaks at BQ25180 IN, at the USBLC6 VBUS pin (its clamp current), at
    the nRF VBUS pin; with and without the TVS conducting;
  * IEC 61000-4-2 +-8 kV contact (150 pF / 330 Ohm gun, calibrated against the standard's waveform
    table) on VBUS and on D+ / D-; peak voltage at BQ25180 IN and, through the harness, at the nRF pins;
  * CC: Rd against every Type-C source termination (Rp to 5 V / 3.3 V, current source; Default / 1.5 A /
    3.0 A; tolerance and rail extremes; e-marked cable Ra on the other CC) -> Type-C vRd windows;
  * DC operating point over VBUS corners and charger input-current extremes (0 / ILIM 500 mA / 1.1 A);
  * capacitance budgets: C1 after DC-bias derating (BQ25180 CIN >= 1 uF) and the total VBUS capacitance
    of the sink (Type-C <= 10 uF);
  * vendor-model cross-checks against the datasheet tables, and fault injection.

Layout: trace inductance between J1 and each part is estimated from the pad placement in the .kicad_pcb
files (Manhattan distance x 0.6 nH/mm, the figure ST uses in the USBLC6-2 datasheet section 2.2). The
boards are still being routed, so placement (not copper) is used; if a PCB cannot be read, the
placement of 2026-10-19 (FALLBACK_MM) is used instead.

Models: hardware/sim/models/usb_input__*.lib (each cites its datasheet). Values of every R/C come from
the netlists (Design.value), so a schematic change shows up on the next run.
"""

from __future__ import annotations

import copy
import math
import os
import sys

import pytest

import spicelib
from spicelib import Deck, Design, node_name

HW = spicelib.HW
sys.path.insert(0, os.path.join(HW, "tools"))

LIB_TVS = "usb_input__smf5v0a.lib"
LIB_ESD = "usb_input__usblc6_2.lib"
LIB_BQ = "usb_input__bq25180_in.lib"
LIB_NRF = "usb_input__nrf52840_usb.lib"

# ----------------------------------------------------------------------------------------------- limits
# (value, source) pairs; every pass/fail number below comes from one of these.
BQ_IN_ABS_MAX = (25.0, "BQ25180 DS SLUSE99C Table 7.1 IN abs max 25 V")
BQ_IN_ABS_MIN = (-0.3, "BQ25180 DS SLUSE99C Table 7.1 IN abs min -0.3 V")
BQ_VIN_OP = ((3.0, 5.5), "BQ25180 DS SLUSE99C Table 7.5 VIN_OP 3.0-5.5 V")
BQ_VIN_OVP_MIN = (5.5, "BQ25180 DS SLUSE99C Table 7.5 VIN_OVP rising 5.5 V min")
BQ_CIN = ((1e-6, 10e-6), "BQ25180 DS SLUSE99C 9.2.2.1 + Table 9-2 CIN 1 uF (after derating) .. 10 uF")
BQ_ESD_HBM = (2500.0, "BQ25180 DS SLUSE99C Table 7.2 HBM +-2500 V")
NRF_VBUS_ABS = ((-0.3, 5.8), "nRF52840 PS v1.1 Table 173 VBUS -0.3..+5.8 V")
NRF_VBUS_OP = ((4.35, 5.5), "nRF52840 PS v1.1 5.3.8.5 VBUS 4.35-5.5 V")
NRF_ESD_HBM = (2000.0, "nRF52840 PS v1.1 Table 173 ESD HBM 2 kV (aQFN73)")
TVS_IPP = (21.7, "SMF5.0A DS (Littelfuse 06/07/17) IPP 21.7 A 10/1000 us")
TVS_IT = (10e-3, "SMF5.0A DS (Littelfuse 06/07/17) VBR test current IT 10 mA (VBR min 6.40 V)")
TVS_VBR = ((6.40, 7.00), "SMF5.0A DS (Littelfuse 06/07/17) VBR 6.40-7.00 V at IT 10 mA")
TVS_VC = (9.2, "SMF5.0A DS (Littelfuse 06/07/17) VC 9.2 V max at IPP 21.7 A")
TVS_IR = (400e-6, "SMF5.0A DS (Littelfuse 06/07/17) IR 400 uA max at VR 5.0 V")
LC6_IPP = (5.0, "USBLC6-2 DS 11265 Rev5 Table 2: VCL characterised up to IPP 5 A 8/20 us")
LC6_VCL = ({1.0: 12.0, 5.0: 17.0}, "USBLC6-2 DS 11265 Rev5 Table 2 VCL max (8/20 us, I/O to GND)")
LC6_VBR_MIN = (6.0, "USBLC6-2 DS 11265 Rev5 Table 2 VBR 6 V min at 1 mA")
LC6_VF_MAX = (1.1, "USBLC6-2 DS 11265 Rev5 Table 2 VF 1.1 V max at 10 mA")
LC6_IRM = (150e-9, "USBLC6-2 DS 11265 Rev5 Table 2 IRM 150 nA max at VRM 5.25 V")
TYPEC_VBUS_CAP = (10e-6, "USB Type-C R2.0 Table 4-3 sink VBUS capacitance 10 uF max (not attached)")
TYPEC_RD = ((5.1e3 * 0.9, 5.1e3 * 1.1), "USB Type-C R2.0 Table 4-25 Rd 5.1 k +-10 % (power-capability detect)")
# Table 4-24 source terminations: {advert: {impl: (nominal, rel tol, rail lo, rail hi)}}
TYPEC_RP = {
    "default": {"rp5v": (56e3, 0.20, 4.75, 5.5), "rp3v3": (36e3, 0.20, 3.135, 3.465), "isrc": (80e-6, 0.20, 1.7, 5.5)},
    "1.5A": {"rp5v": (22e3, 0.05, 4.75, 5.5), "rp3v3": (12e3, 0.05, 3.135, 3.465), "isrc": (180e-6, 0.08, 1.7, 5.5)},
    "3.0A": {"rp5v": (10e3, 0.05, 4.75, 5.5), "rp3v3": (4.7e3, 0.05, 3.135, 3.465), "isrc": (330e-6, 0.08, 1.7, 5.5)},
}
# sink-side windows (Table 4-36) and source-side vRd windows (Tables 4-32/33/34)
TYPEC_SINK_WIN = {"default": (0.25, 0.61), "1.5A": (0.70, 1.16), "3.0A": (1.31, 2.04)}
TYPEC_SRC_WIN = {"default": (0.25, 1.50), "1.5A": (0.45, 1.50), "3.0A": (0.85, 2.45)}
TYPEC_RA = ((800.0, 1200.0), "USB Type-C R2.0 Table 4-26 Ra 800-1200 Ohm")
IEC_8KV = {"ip": (30.0, 0.15), "tr": (0.8e-9, 0.25), "i30": (16.0, 0.30), "i60": (8.0, 0.30)}
IEC_SRC = "IEC 61000-4-2:2008 Table 2 level 4 (8 kV contact), reproduced in Vishay SMF DS 85881 Fig. 1"

# ----------------------------------------------------------------------------------------------- assumptions
L_PER_MM = 0.6e-9          # USBLC6-2 DS 11265 Rev5 2.2: 10 mm x 0.5 mm track ~ 6 nH
R_PER_MM = 1.23e-3         # 0.4 mm x 35 um copper (rho 1.72e-8)
MLCC_ESL = 0.6e-9          # 0603 MLCC mounted (typical), assumption
MLCC_ESR = 8e-3            # typical X5R ESR near resonance, assumption
HARNESS_MM = (50.0, 100.0)  # docs/architecture.md 4.2 (50-80 mm) .. docs/assembly.md harness (~100 mm)
HARNESS_L_PER_M = 1.0e-6   # loose single lead with its return in the bundle (same 1 uH/m as a USB cable)
HARNESS_R_PER_M = 0.538    # 32 AWG signal lead (docs/assembly.md: 32 AWG on the signals, VBUS pin 5 incl.)
EMARKER_RA = 1.0e3

# X5R DC-bias derating C(V) = C0 / (1 + (|V| / V0)^n), per MPN.  ESTIMATE: the Yageo / Samsung curves could
# not be downloaded (sites need a browser session); the shapes follow published 0603 X5R curves of the same
# rating class (2.2 uF/25 V: ~80 % at 2.5 V, ~60 % at 5 V, ~35 % at 10 V; 4.7 uF/16 V: ~58 % at 3.3 V, ~45 % at
# 5 V, ~25 % at 10 V).  An unknown MPN on these nets fails the test until its curve is added here.
X5R_DCBIAS = {
    "CC0603KRX5R8BB225": (6.58, 1.48),
    "CL10A475KO8NNNC": (4.28, 1.30),
}
X5R_TEMP_BOUND = 0.15      # EIA X5R: +-15 % over -55..85 C, applied as -15 % at the -10 / 60 C corners

# placement fallback (pad-to-pad Manhattan mm from J1/link pad, measured 2026-10-19)
FALLBACK_MM = {
    ("base", "VBUS", "D1"): 6.3, ("base", "VBUS", "U2"): 10.2, ("base", "VBUS", "U1"): 47.9,
    ("base", "VBUS", "J3"): 54.2, ("base", "USB_DP", "U2"): 9.5, ("base", "USB_DP", "J3"): 50.3,
    ("base", "USB_DM", "U2"): 9.5, ("base", "USB_DM", "J3"): 49.3,
    ("main", "VBUS", "U10"): 26.8, ("main", "USB_DP", "U10"): 26.0, ("main", "USB_DM", "U10"): 25.8,
}


# ============================================================================================ layout
_PADS = {}


def pads(board: str) -> dict:
    """{ref: {pad: (x_mm, y_mm)}} from the board's .kicad_pcb (empty dict if it cannot be read)."""
    if board in _PADS:
        return _PADS[board]
    out = {}
    try:
        import sexpr
        from sexpr import find, find_all
        path = os.path.join(HW, "kicad", board, f"dial-me-spinner-{board}.kicad_pcb")
        tree = sexpr.parse(open(path, encoding="utf-8").read())
        for fp in find_all(tree, "footprint"):
            refs = [str(p[2]) for p in find_all(fp, "property") if str(p[1]) == "Reference"]
            if not refs:
                continue
            at = find(fp, "at")
            x0, y0 = float(at[1]), float(at[2])
            th = math.radians(float(at[3]) if len(at) > 3 else 0.0)
            for pd in find_all(fp, "pad"):
                pa = find(pd, "at")
                px, py = float(pa[1]), float(pa[2])
                out.setdefault(refs[0], {})[str(pd[1])] = (x0 + px * math.cos(th) + py * math.sin(th),
                                                           y0 - px * math.sin(th) + py * math.cos(th))
    except Exception:  # noqa: BLE001 - board mid-edit or missing: fall back to the recorded placement
        out = {}
    _PADS[board] = out
    return out


def dist_mm(d: Design, net: str, ref_from: str, ref_to: str) -> float:
    """Manhattan distance between the closest pads of two parts on `net` (placement estimate)."""
    p = pads(d.board)

    def pins_on(ref):
        return [pin for pin, n in d.pins.get(ref, {}).items() if n == net]

    try:
        a = [p[ref_from][q] for q in pins_on(ref_from)]
        b = [p[ref_to][q] for q in pins_on(ref_to)]
        if a and b:
            return min(abs(x1 - x2) + abs(y1 - y2) for x1, y1 in a for x2, y2 in b)
    except KeyError:
        pass
    return FALLBACK_MM.get((d.board, net, ref_to), 30.0)


# ============================================================================================ netlist helpers
def one(lst, what):
    assert len(lst) == 1, f"expected exactly one {what}, netlist has {lst}"
    return lst[0]


class Parts:
    """Reference designators found from the netlists by MPN / pin function (nothing hard-coded)."""

    def __init__(self, base: Design, main: Design):
        self.usbc = one(base.find("TYPE-C"), "USB-C receptacle")
        self.tvs = one(base.find("SMF5"), "SMF5.0A")
        self.esd = one(base.find("USBLC6"), "USBLC6")
        self.chg = one(base.find("BQ25180"), "BQ25180")
        self.link_b = one(base.find("SM12B"), "base link connector")
        self.link_m = one(main.find("SM12B"), "main link connector")
        self.mcu = one(main.find("MDBT50Q"), "nRF52840 module")
        self.vbus_b = base.funcs[self.chg]["IN"]
        self.cc = [base.funcs[self.usbc]["CC1"], base.funcs[self.usbc]["CC2"]]
        self.dp_b = base.funcs[self.usbc]["D+"]
        self.dm_b = base.funcs[self.usbc]["D-"]
        # link pins carrying VBUS / D+ / D- on the base, the same pin numbers on main (identical pinout)
        self.link_pin = {}
        for key, net in (("vbus", self.vbus_b), ("dp", self.dp_b), ("dm", self.dm_b)):
            self.link_pin[key] = one([p for p, n in base.pins[self.link_b].items() if n == net], f"link pin {key}")
        self.vbus_m = main.pins[self.link_m][self.link_pin["vbus"]]
        self.dp_m = main.pins[self.link_m][self.link_pin["dp"]]
        self.dm_m = main.pins[self.link_m][self.link_pin["dm"]]
        self.nrf_vbus = main.funcs[self.mcu]["VBUS"]
        self.nrf_dp = main.funcs[self.mcu]["D+"]
        self.nrf_dm = main.funcs[self.mcu]["D-"]


def caps_on(d: Design, nets) -> list:
    nets = set(nets)
    return [r for r in sorted(d.comps, key=spicelib._refkey) if r[0] == "C" and r[1:2].isdigit()
            and set(d.pins.get(r, {}).values()) & nets and set(d.pins[r].values()) <= nets | {"GND"}]


def cap_lines(d: Design, ref: str, node: str, prefix: str, scale: float = 1.0, temp_factor: float = 1.0,
              derate: bool = True) -> list:
    """A netlist capacitor (value from the netlist) with X5R DC-bias derating, ESR and ESL."""
    if not d.fitted(ref):
        return []
    tag = f"{prefix}{ref}"
    if ref in d._shorted:
        return [f"V{tag}_short {node} 0 0"]
    c0 = d.value(ref) * scale * temp_factor
    mpn = d.mpn(ref)
    lines = [f"R{tag}_esr {node} {node}_{tag}_a {MLCC_ESR}", f"L{tag}_esl {node}_{tag}_a {node}_{tag}_b {MLCC_ESL}"]
    if derate:
        assert mpn in X5R_DCBIAS, f"{ref} ({mpn}) has no DC-bias curve in X5R_DCBIAS: add one from its datasheet"
        v0, n = X5R_DCBIAS[mpn]
        vx = f"v({node}_{tag}_b)"        # smooth |V| (pow'(0) would be 0/0 inside ngspice)
        lines.append(f"C{tag} {node}_{tag}_b 0 C='{c0:.6g}/(1+pow(({vx}*{vx}+1e-6)/{v0 * v0:.6g},{n / 2:.6g}))'")
    else:
        lines.append(f"C{tag} {node}_{tag}_b 0 {c0:.6g}")
    return lines


def derated(d: Design, ref: str, v: float, scale: float = 1.0, temp_factor: float = 1.0) -> float:
    v0, n = X5R_DCBIAS[d.mpn(ref)]
    return d.value(ref) * scale * temp_factor / (1 + (abs(v) / v0) ** n)


def line(name, a, b, mm, prefix):
    """Series R-L of a trace of `mm` millimetres."""
    if mm <= 0:
        return [f"V{prefix}{name} {a} {b} 0"]
    mid = f"{a}_{prefix}{name}"
    return [f"R{prefix}{name} {a} {mid} {max(mm * R_PER_MM, 1e-6):.4g}", f"L{prefix}{name} {mid} {b} {mm * L_PER_MM:.4g}"]


# ============================================================================================ network builder
class Net:
    """VBUS + D+/D- network of both boards and the harness, ready for a Deck.

    Node names:  vj1 (J1 VBUS pads), vtvs, vesd, vin (BQ IN), vlinkb (base link pin), vlinkm (main link pin),
                 vnrf (nRF VBUS); dpj1 / dmj1, dplinkb / dmlinkb, dplinkm / dmlinkm, dpnrf / dmnrf.
    """

    def __init__(self, base: Design, main: Design, harness_mm=HARNESS_MM[1], cscale=None, temp=25.0,
                 tvs="typ", esd="typ", iq=0.75e-3, iin=0.0, ivbus=2.4e-3, vusb=0.0, series_r_nrf=None,
                 derate=True):
        self.b, self.m = base, main
        self.p = Parts(base, main)
        self.harness_mm = harness_mm
        self.cscale = cscale or {}
        self.temp = temp
        self.tvs, self.esd = tvs, esd
        self.iq, self.iin, self.ivbus, self.vusb = iq, iin, ivbus, vusb
        self.series_r_nrf = series_r_nrf
        self.derate = derate

    # --------------------------------------------------------------------------------------------
    def tfac(self):
        return 1.0 if abs(self.temp - 25.0) < 1 else 1.0 - X5R_TEMP_BOUND

    def tvs_params(self):
        return {"typ": "vbr=6.70 rd=0.02", "clampmax": "vbr=7.00 rd=0.101",
                "leakmax": "vbr=6.41 rd=0.02 ilk=400u nlk=22"}[self.tvs]

    def esd_params(self):
        return {"typ": "rd=0.5 rdt=0.5", "max": "rd=0.965 rdt=0.965"}[self.esd]

    def lines(self) -> list:
        b, m, p = self.b, self.m, self.p
        L = []
        vb = p.vbus_b
        # ---------------- base VBUS: star from the J1 pads, one branch per part (layout estimate)
        branch = {}
        for ref in (p.tvs, p.esd, p.chg, p.link_b):
            branch[ref] = f"vbr_{ref.lower()}"
            L += line(f"tb_{ref}", "vj1", branch[ref], dist_mm(b, vb, p.usbc, ref), "")
        # TVS: netlist pins decide the orientation (pin 1 = cathode per the Littelfuse DS)
        if b.fitted(p.tvs):
            if p.tvs in b._shorted:
                L.append(f"V{p.tvs}_short {branch[p.tvs]} 0 0")
            else:
                k = branch[p.tvs] if b.pins[p.tvs]["1"] == vb else node_name(b.pins[p.tvs]["1"])
                a = branch[p.tvs] if b.pins[p.tvs]["2"] == vb else node_name(b.pins[p.tvs]["2"])
                L.append(f"VItvs {k} {k}_i 0")
                L.append(f"X{p.tvs} {k}_i {a} USBIN_SMF5V0A {self.tvs_params()}")
        # charger IN
        L.append(f"VIin {branch[p.chg]} vin 0")
        L.append(f"X{p.chg} vin 0 USBIN_BQ25180_IN iq={self.iq} iin={self.iin}")
        # caps on VBUS: each joins the branch of the nearest part pin on VBUS
        for ref in caps_on(b, {vb}):
            best = min((p.tvs, p.esd, p.chg, p.link_b),
                       key=lambda r: dist_mm(b, vb, ref, r) if pads(b.board) else (0 if r == p.chg else 1))
            node = "vin" if best == p.chg else branch[best]
            L += cap_lines(b, ref, node, "b", self.cscale.get(ref, 1.0), self.tfac(), self.derate)
        # ESD array: VBUS pin on its branch, I/Os on D+/D- at the U2 pads
        esd_vbus_node = branch[p.esd] if b.pins[p.esd]["5"] == vb else node_name(b.pins[p.esd]["5"])
        L.append(f"VIesd {esd_vbus_node} vesd 0")
        io1 = "dpesd" if b.pins[p.esd]["1"] == p.dp_b else ("dmesd" if b.pins[p.esd]["1"] == p.dm_b else "0")
        io2 = "dmesd" if b.pins[p.esd]["3"] == p.dm_b else ("dpesd" if b.pins[p.esd]["3"] == p.dp_b else "0")
        L.append(f"X{p.esd} {io1} 0 {io2} vesd USBIN_USBLC6_2 {self.esd_params()}")
        # D+/D-: J1 -> U2 -> link connector
        for sig, net in (("dp", p.dp_b), ("dm", p.dm_b)):
            L += line(f"t{sig}1", f"{sig}j1", f"{sig}esd", dist_mm(b, net, p.usbc, p.esd), "")
            L += line(f"t{sig}2", f"{sig}esd", f"{sig}linkb", dist_mm(b, net, p.esd, p.link_b), "")
        L.append(f"VIvlink {branch[p.link_b]} vlinkb 0")
        # ---------------- harness (VBUS, D+, D-), single leads with ideal GND return
        hl, hr = self.harness_mm * 1e-3 * HARNESS_L_PER_M, self.harness_mm * 1e-3 * HARNESS_R_PER_M
        for sig in ("v", "dp", "dm"):
            L += [f"Rh_{sig} {sig}linkb {sig}h_mid {hr:.4g}", f"Lh_{sig} {sig}h_mid {sig}linkm {hl:.4g}"]
        # ---------------- main board: link pad -> trace -> nRF VBUS / D+ / D-
        mv = p.vbus_m
        L += line("tm_v", "vlinkm", "vmain", dist_mm(m, mv, p.link_m, p.mcu), "")
        if self.series_r_nrf is not None:          # what-if: series resistor in front of the nRF VBUS pin
            L.append(f"Rwhatif vmain vnrf {self.series_r_nrf}")
            cap_node = "vnrf"
        else:
            assert p.nrf_vbus == mv, "main VBUS topology changed (series part?): update Net.lines()"
            L.append("Vmain_short vmain vnrf 0")
            cap_node = "vnrf"
        for ref in caps_on(m, {mv}):
            L += cap_lines(m, ref, cap_node, "m", self.cscale.get(ref, 1.0), self.tfac(), self.derate)
        L += line("tm_dp", "dplinkm", "dpnrf", dist_mm(m, p.dp_m, p.link_m, p.mcu), "")
        L += line("tm_dm", "dmlinkm", "dmnrf", dist_mm(m, p.dm_m, p.link_m, p.mcu), "")
        L.append("VInrf_dp dpnrf dpnrf_i 0")
        L.append("VInrf_dm dmnrf dmnrf_i 0")
        L.append(f"X{p.mcu} vnrf dpnrf_i dmnrf_i 0 USBIN_NRF52840_USB ivbus={self.ivbus} vusb={self.vusb}")
        return L

    def deck(self, title: str) -> Deck:
        dk = Deck(title)
        for lib in (LIB_TVS, LIB_ESD, LIB_BQ, LIB_NRF):
            dk.include(lib)
        dk += self.lines()
        if abs(self.temp - 27.0) > 0.01:
            dk.options.append(f"option temp={self.temp}")
        return dk


@pytest.fixture
def parts(base, main):
    return Parts(base, main)
