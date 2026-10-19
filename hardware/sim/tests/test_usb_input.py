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
EMARKER_RA = 800.0         # lowest Ra of USB Type-C R2.0 Table 4-26 (800-1200 Ohm) on the unused CC pin

# X5R DC-bias derating C(V) = C0 / (1 + (V / V0)^2), charge Q(V) = C0 V0 atan(V / V0) (charge-conserving and
# smooth: ngspice's behavioural C='expr' element does not converge in these decks).  V0 per MPN.
# ESTIMATE: the Yageo / Samsung DC-bias curves could not be downloaded (vendor sites need a browser session);
# V0 is set so the retained capacitance at 5 V matches published 0603 X5R curves of the same rating class
# (2.2 uF/25 V: ~60 % at 5 V -> V0 6.12 V; 4.7 uF/16 V: ~45 % at 5 V -> V0 4.52 V).  An MPN that is not listed
# here fails the test until its curve is added (see harness request in the summary).
X5R_DCBIAS = {
    "CC0603KRX5R8BB225": 6.12,
    "CL10A475KO8NNNC": 4.52,
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
class NetlistError(LookupError):
    """The netlist no longer matches what this test models (never mistaken for a check failure)."""


def one(lst, what):
    if len(lst) != 1:
        raise NetlistError(f"expected exactly one {what}, netlist has {lst}")
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
        self.main_vbus_nets = {self.vbus_m, self.nrf_vbus}


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
        if mpn not in X5R_DCBIAS:
            raise NetlistError(f"{ref} ({mpn}) has no DC-bias curve in X5R_DCBIAS: add one from its datasheet")
        v0 = X5R_DCBIAS[mpn]
        b = f"{node}_{tag}_b"
        # charge in uC on an auxiliary node, 1 uF sense cap -> i = dQ/dt, mirrored into the capacitor node
        lines += [f"B{tag}_q {b}_q 0 V={c0 * v0 * 1e6:.6g}*atan(v({b})/{v0})",
                  f"V{tag}_qs {b}_q {b}_qc 0", f"C{tag}_qc {b}_qc 0 1u",
                  f"F{tag} {b} 0 V{tag}_qs 1", f"R{tag}_dc {b} 0 1e9"]
    else:
        lines.append(f"C{tag} {node}_{tag}_b 0 {c0:.6g}")
    return lines


def line(name, a, b, mm, prefix):
    """Series R-L of a trace of `mm` millimetres."""
    if mm <= 0:
        return [f"V{prefix}{name} {a} {b} 0"]
    mid = f"{a}_{prefix}{name}"
    return [f"R{prefix}{name} {a} {mid} {max(mm * R_PER_MM, 1e-6):.4g}", f"L{prefix}{name} {mid} {b} {mm * L_PER_MM:.4g}"]


# ============================================================================================ network builder
class Net:
    """VBUS + D+/D- network of both boards and the harness, ready for a Deck.

    Node names:  vj1 (J1 VBUS pads), vbr_<ref> (end of each VBUS branch, e.g. vbr_d1 at the TVS), vesd (U2 VBUS
                 pin), vin (BQ IN), vlinkb / vlinkm (link VBUS pin on base / main), vmain, vnrf (nRF VBUS);
                 dpj1 / dmj1 (J1 pads), dpesd / dmesd (U2 I/O), dplinkb.., dplinkm.., dpnrf / dmnrf (nRF pads).
    Current probes: i(vitvs) (into the TVS cathode), i(v.x<U2>.vtr) (U2 Transil), i(v.x<U1>.vesd) (BQ IN clamp),
                 i(vinrf_dp) / i(vinrf_dm) / i(vinrf_vb) (into the nRF pins).
    """

    def __init__(self, base: Design, main: Design, harness_mm=HARNESS_MM[1], cscale=None, temp=25.0,
                 tvs="typ", esd="typ", iq=0.75e-3, iin=0.0, ivbus=2.4e-3, vusb=0.0, series_r_nrf=None,
                 derate=True, resd=3.0):
        self.b, self.m = base, main
        self.p = Parts(base, main)
        self.harness_mm = harness_mm
        self.cscale = cscale or {}
        self.temp = temp
        self.tvs, self.esd = tvs, esd
        self.iq, self.iin, self.ivbus, self.vusb = iq, iin, ivbus, vusb
        self.series_r_nrf = series_r_nrf
        self.derate = derate
        self.resd = resd

    # --------------------------------------------------------------------------------------------
    def tfac(self):
        return 1.0 if abs(self.temp - 25.0) < 1 else 1.0 - X5R_TEMP_BOUND

    def tvs_params(self):
        return {"typ": "vbr=6.70 rd=0.02", "clampmax": "vbr=6.995 rd=0.0924",
                "leakmax": "vbr=6.42 rd=0.02 ilk=400u nlk=22"}[self.tvs]

    def esd_params(self):
        return {"typ": "rd=0.5 rdt=0.5", "max": "rd=0.953 rdt=0.953"}[self.esd]

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
        L.append(f"X{p.chg} vin 0 USBIN_BQ25180_IN iq={self.iq} iin={self.iin} resd={self.resd}")
        # caps on VBUS: each joins the branch of the nearest part pin on VBUS
        for ref in caps_on(b, {vb}):
            best = min((p.tvs, p.esd, p.chg, p.link_b),
                       key=lambda r: dist_mm(b, vb, ref, r) if pads(b.board) else (0 if r == p.chg else 1))
            node = "vin" if best == p.chg else branch[best]
            L += cap_lines(b, ref, node, "b", self.cscale.get(f"b:{ref}", 1.0), self.tfac(), self.derate)
        # ESD array: VBUS pin on its branch, I/Os on D+/D- at the U2 pads
        f = b.funcs[p.esd]
        esd_vbus_node = branch[p.esd] if f["VBUS"] == vb else node_name(f["VBUS"])
        L.append(f"VIesd {esd_vbus_node} vesd 0")
        sig_node = {p.dp_b: "dpesd", p.dm_b: "dmesd"}
        gnd = "0" if f["GND"] == "GND" else node_name(f["GND"])
        L.append(f"X{p.esd} {sig_node.get(f['I/O1'], node_name(f['I/O1']))} {gnd} "
                 f"{sig_node.get(f['I/O2'], node_name(f['I/O2']))} vesd USBIN_USBLC6_2 {self.esd_params()}")
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
        nets_m = {mv, p.nrf_vbus}
        if self.series_r_nrf is not None:          # what-if: series resistor in front of the nRF VBUS pin
            if p.nrf_vbus != mv:
                raise NetlistError("what-if R requested but the schematic already has a series part")
            L.append(f"Rwhatif vmain vnrf {self.series_r_nrf}")
        elif p.nrf_vbus == mv:
            L.append("Vmain_short vmain vnrf 0")
        else:
            # the schematic has series part(s) between the link VBUS and the nRF VBUS pin: take them (R/L, values
            # from the netlist) and map their nets onto vmain / vnrf
            ren = {node_name(mv): "vmain", node_name(p.nrf_vbus): "vnrf"}
            caps_m = set(caps_on(m, nets_m))
            for ln in m.passives(nets=nets_m | {"GND"}, exclude=tuple(caps_m)):
                tok = ln.split()
                L.append(" ".join([tok[0][0] + "m_" + tok[0][1:]] + [ren.get(t, t) for t in tok[1:3]] + tok[3:]))
        for ref in caps_on(m, nets_m):
            node = "vnrf" if p.nrf_vbus in m.pins[ref].values() else "vmain"
            L += cap_lines(m, ref, node, "m", self.cscale.get(f"m:{ref}", 1.0), self.tfac(), self.derate)
        L += line("tm_dp", "dplinkm", "dpnrf", dist_mm(m, p.dp_m, p.link_m, p.mcu), "")
        L += line("tm_dm", "dmlinkm", "dmnrf", dist_mm(m, p.dm_m, p.link_m, p.mcu), "")
        L.append("VInrf_dp dpnrf dpnrf_i 0")
        L.append("VInrf_dm dmnrf dmnrf_i 0")
        L.append("VInrf_vb vnrf vnrf_i 0")
        L.append(f"X{p.mcu} vnrf_i dpnrf_i dmnrf_i 0 USBIN_NRF52840_USB ivbus={self.ivbus} vusb={self.vusb} "
                 f"resd={self.resd}")
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


# ============================================================================================ stimuli
# IEC 61000-4-2 gun: 150 pF / 330 Ohm main network (the standard's values) plus a 6 pF / 1 k fast branch and
# 100 nH tip inductance that shape the first peak; calibrated in test_iec_gun_calibration against Table 2.
GUN = dict(cm=150e-12, rm=330.0, cf=6e-12, rf=1e3, lt=100e-9, t_on=1e-9)


def gun_lines(node: str, kv: float) -> list:
    v = kv * 1e3
    g = GUN
    return [f"Cg_m g_m 0 {g['cm']}", f"Rg_m g_m g_tip {g['rm']}", f"Cg_f g_f 0 {g['cf']}", f"Rg_f g_f g_tip {g['rf']}",
            f"Lg_t g_tip g_out {g['lt']}",
            # relay contact: closes at t_on (smooth conductance step, 1 pS -> 100 S over ~0.2 ns)
            f"Bg_sw g_out g_in I=(v(g_out)-v(g_in))*(1e-12+1e2*0.5*(1+tanh((time-{g['t_on']})/50p)))",
            f"Vg_i g_in {node} 0", f".ic v(g_m)={v} v(g_f)={v}"]


# hot-plug cable cases (task: 1-2 m, 0.5-1 uH/m, 50-100 mOhm loop resistance)
CABLES = {"1m_0.5uH_100m": (1.0, 0.5e-6, 0.10), "2m_1uH_100m": (2.0, 1.0e-6, 0.10),
          "1m_1uH_50m": (1.0, 1.0e-6, 0.05), "2m_1uH_50m": (2.0, 1.0e-6, 0.05)}
VBUS_SRC = (4.5, 5.0, 5.25, 5.5)       # task corners + USB 2.0 max 5.25 V; 5.5 V = USB-C vSafe5V max
BULK = (10e-6, 120e-6)                 # source bulk: small charger / USB 2.0 host port (>= 120 uF)
WORST = (5.5, "1m_1uH_50m", 10e-6)     # worst nRF overshoot of the grid (found by test_hotplug_grid)


def hotplug_deck(net: Net, vsrc: float, cable: str, c_bulk: float, stop: float = 100e-6) -> Deck:
    length, lpm, rc = CABLES[cable]
    dk = net.deck(f"hot plug {vsrc} V {cable} bulk {c_bulk}")
    dk += [f"Vsrc srcv 0 {vsrc}", "Rsrc srcv srcb 10m", f"Cbulk srcb srcb_c {c_bulk}", "Rbulk srcb_c 0 20m",
           # plug contact closes at 1 us (smooth conductance step, 1 nS -> 1 kS in ~10 ns)
           "Bplug srcb cab I=(v(srcb)-v(cab))*(1e-9+1e3*0.5*(1+tanh((time-1u)/2n)))",
           f"Ccab1 cab 0 {50e-12 * length:.4g}", f"Rcab cab cab_m {rc}", f"Lcab cab_m vj1 {lpm * length:.4g}",
           f"Ccab2 vj1 0 {50e-12 * length:.4g}", f".ic v(srcb)={vsrc} v(srcb_c)={vsrc}"]
    dk.options.append("option method=gear")
    dk.tran("5n", f"{stop}", 0, "10n")
    p = net.p
    tvs_fitted = net.b.fitted(p.tvs) and p.tvs not in net.b._shorted
    for name, expr in (("vin", "v(vin)"), ("vesd", "v(vesd)"), ("vtvs", f"v(vbr_{p.tvs.lower()})"),
                       ("vnrf", "v(vnrf)"), ("itvs", "i(vitvs)" if tvs_fitted else None),
                       ("itr", f"i(v.x{p.esd.lower()}.vtr)")):
        if expr:
            dk.meas(f"tran {name}_max MAX {expr}")
    dk.meas(f"tran vnrf_end FIND v(vnrf) AT={stop * 0.99:.4g}")
    dk.meas(f"tran vin_end FIND v(vin) AT={stop * 0.99:.4g}")
    return dk


def esd_deck(net: Net, node: str, kv: float, stop: float = 2e-6) -> Deck:
    dk = net.deck(f"IEC 61000-4-2 {kv:+} kV at {node}")
    dk += gun_lines(node, kv)
    dk.options += ["option method=gear", "option gmin=1e-11"]   # gmin: pA-level junctions before the strike
    dk.tran("10p", f"{stop}", 0, "100p")
    p = net.p
    for name, expr in (("vin", "v(vin)"), ("vnrf", "v(vnrf)"), ("vesd", "v(vesd)"), ("dpesd", "v(dpesd)"),
                       ("dmesd", "v(dmesd)"), ("dpnrf", "v(dpnrf)"), ("dmnrf", "v(dmnrf)"),
                       ("inrfdp", "i(vinrf_dp)"), ("inrfdm", "i(vinrf_dm)"), ("inrfvb", "i(vinrf_vb)"),
                       ("ibq", f"i(v.x{p.chg.lower()}.vesd)"), ("itvs", "i(vitvs)"),
                       ("itr", f"i(v.x{p.esd.lower()}.vtr)"), ("ig", "i(vg_i)")):
        if name == "itvs" and not (net.b.fitted(p.tvs) and p.tvs not in net.b._shorted):
            continue
        dk.meas(f"tran {name}_max MAX {expr}")
        dk.meas(f"tran {name}_min MIN {expr}")
    return dk


class SimError(RuntimeError):
    """ngspice failed: never mistaken for a check failure (xfail markers only accept AssertionError)."""


def run(dk: Deck, timeout: int = 120) -> dict:
    r = dk.run(timeout=timeout)
    if r["_errors"] or r.get("_missing"):
        raise SimError(f"{dk.title}: ngspice reported {r['_errors'][:3]}, missing measures {r.get('_missing')}")
    return r


_CACHE = {}


def design_key(d: Design) -> tuple:
    """Everything fault injection can change on a Design (so cached runs are never reused across faults)."""
    return (tuple(sorted(d._override.items())), tuple(sorted(d._removed)), tuple(sorted(d._shorted)),
            tuple(sorted((r, tuple(sorted(p.items()))) for r, p in d.pins.items())),
            tuple(sorted(r for r, c in d.comps.items() if c["dnp"])))


def cached(key, fn):
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


def hbm_amps(v_hbm: float) -> float:
    """Peak current of the HBM network the pin is qualified to (JS-001: 100 pF through 1.5 kOhm)."""
    return v_hbm / 1.5e3


# ============================================================================================ model checks
def test_tvs_model_matches_datasheet(check):
    """SMF5.0A model against the Littelfuse table (VBR window at IT, VC at IPP, IR at VR), every corner."""
    dk = Deck("SMF5.0A DC points")
    dk.include(LIB_TVS)
    corners = {"lo": "vbr=6.42 rd=0.02 ilk=400u nlk=22", "typ": "", "hi": "vbr=6.995 rd=0.0924"}
    dk += ["Vs s 0 0"]
    for k, prm in corners.items():          # each instance follows the swept node through an E source
        dk += [f"E{k} k{k} 0 s 0 1", f"X{k} k{k} 0 USBIN_SMF5V0A {prm}"]
    dk.dc("Vs", 0, 10, 0.0005)
    for k in corners:
        dk.meas(f"dc vbr_{k} FIND v(s) WHEN i(e{k})=-10m")
        dk.meas(f"dc vc_{k} FIND v(s) WHEN i(e{k})=-21.7")
        dk.meas(f"dc ir_{k} FIND i(e{k}) AT=5")
    r = run(dk)
    for k in corners:
        check(f"SMF5.0A model ({k}) VBR at IT 10 mA", r[f"vbr_{k}"], *TVS_VBR[0], "V", TVS_VBR[1])
        check(f"SMF5.0A model ({k}) VC at IPP 21.7 A", r[f"vc_{k}"], None, TVS_VC[0], "V", TVS_VC[1])
        check(f"SMF5.0A model ({k}) IR at VR 5.0 V", abs(r[f"ir_{k}"]), None, TVS_IR[0], "A", TVS_IR[1])


def test_usblc6_model_matches_datasheet(check):
    """USBLC6-2 model against ST Table 2: VBR (VBUS-GND), VF, VCL at 1 A and 5 A (I/O to GND, VBUS pin
    open as in ST's measurement), IRM at VRM, for the typical and the datasheet-max corner."""
    dk = Deck("USBLC6-2 DC points")
    dk.include(LIB_ESD)
    corners = {"typ": "rd=0.5 rdt=0.5", "max": "rd=0.953 rdt=0.953"}
    dk += ["Vs s 0 0"]
    for k, prm in corners.items():
        dk += [f"Ev{k} vb{k} 0 s 0 1", f"Xv{k} nc1{k} 0 nc2{k} vb{k} USBIN_USBLC6_2 {prm}",      # VBUS-GND
               f"Rn1{k} nc1{k} 0 1G", f"Rn2{k} nc2{k} 0 1G",
               f"Ei{k} io{k} 0 s 0 1", f"Xi{k} io{k} 0 io2{k} vbo{k} USBIN_USBLC6_2 {prm}",      # I/O-GND
               f"Rio2{k} io2{k} 0 1G", f"Rvbo{k} vbo{k} 0 1G",
               f"Ef{k} 0 fio{k} s 0 1", f"Xf{k} fio{k} 0 fio2{k} fvb{k} USBIN_USBLC6_2 {prm}",  # forward GND->I/O
               f"Rf2{k} fio2{k} 0 1G", f"Rfvb{k} fvb{k} 0 1G"]
    dk.dc("Vs", 0, 20, 0.001)
    for k in corners:
        dk.meas(f"dc vbr_{k} FIND v(s) WHEN i(ev{k})=-1m")
        dk.meas(f"dc irm_{k} FIND i(ev{k}) AT=5.25")
        dk.meas(f"dc vcl1_{k} FIND v(s) WHEN i(ei{k})=-1")
        dk.meas(f"dc vcl5_{k} FIND v(s) WHEN i(ei{k})=-5")
        dk.meas(f"dc vf_{k} FIND v(s) WHEN i(ef{k})=-10m")
    r = run(dk)
    for k in corners:
        check(f"USBLC6 model ({k}) VBR at 1 mA", r[f"vbr_{k}"], LC6_VBR_MIN[0], None, "V", LC6_VBR_MIN[1])
        check(f"USBLC6 model ({k}) IRM at 5.25 V", abs(r[f"irm_{k}"]), None, LC6_IRM[0], "A", LC6_IRM[1])
        check(f"USBLC6 model ({k}) VF at 10 mA", r[f"vf_{k}"], None, LC6_VF_MAX[0], "V", LC6_VF_MAX[1])
        check(f"USBLC6 model ({k}) VCL at 1 A", r[f"vcl1_{k}"], None, LC6_VCL[0][1.0], "V", LC6_VCL[1])
        check(f"USBLC6 model ({k}) VCL at 5 A", r[f"vcl5_{k}"], None, LC6_VCL[0][5.0], "V", LC6_VCL[1])


# ============================================================================================ ESD gun calibration
def test_iec_gun_calibration(check):
    """The gun network into the standard's 2 Ohm current target meets IEC 61000-4-2 Table 2 at 8 kV."""
    import numpy as np
    dk = Deck("IEC gun into 2 Ohm target")
    dk += gun_lines("tgt", 8.0) + ["Rtgt tgt 0 2"]
    dk.tran("5p", "120n", 0, "20p")
    dk.wave("i(vg_i)")
    r = run(dk)
    w = r["waves"]
    t, i = w[list(w)[0]], w["i(vg_i)"]
    k = int(np.argmax(i))
    ip = float(i[k])
    t10 = float(np.interp(0.1 * ip, i[:k + 1], t[:k + 1]))
    t90 = float(np.interp(0.9 * ip, i[:k + 1], t[:k + 1]))
    i30, i60 = (float(np.interp(t10 + d, t, i)) for d in (30e-9, 60e-9))
    for name, val, unit in (("ip", ip, "A"), ("tr", t90 - t10, "s"), ("i30", i30, "A"), ("i60", i60, "A")):
        nom, tol = IEC_8KV[name]
        check(f"8 kV contact waveform {name}", val, nom * (1 - tol), nom * (1 + tol), unit, IEC_SRC)


# ============================================================================================ CC / Rd
def cc_voltage(base: Design, active: str, advert: str, impl: str, corner: tuple, rd_scale: dict) -> float:
    """DC voltage on the active CC pin: source termination on it, e-marker Ra on the other CC pin."""
    nom, tol, rail_lo, rail_hi = TYPEC_RP[advert][impl]
    rp_sign, rail_sel = corner
    usbc = one(base.find("TYPE-C"), "USB-C receptacle")
    cc_nets = [base.funcs[usbc]["CC1"], base.funcs[usbc]["CC2"]]
    act, other = (node_name(n) for n in (cc_nets if active == "CC1" else cc_nets[::-1]))
    dk = Deck(f"CC {advert} {impl} {active}")
    dk += base.passives(nets=set(cc_nets) | {"GND"}, scale=rd_scale)
    rail = rail_hi if rail_sel > 0 else rail_lo
    val = nom * (1 + rp_sign * tol)
    if impl == "isrc":
        # current source with compliance to `rail` (diode clamp to the rail)
        dk += [f"Irp 0 {act} {val:.6g}", f"Vrail rail 0 {rail}", f"Dcmp {act} rail DCMP", ".model DCMP D(IS=1e-12 N=0.01)"]
    else:
        dk += [f"Vrail rail 0 {rail}", f"Rrp rail {act} {val:.6g}"]
    dk += [f"Rra {other} 0 {EMARKER_RA}", f"Rnum1 {act} 0 1e12", f"Rnum2 {other} 0 1e12"]
    dk.op()
    dk.print_op(f"v({act})")
    r = run(dk)
    return r["op_0"]


@pytest.mark.parametrize("advert", ["default", "1.5A", "3.0A"])
@pytest.mark.parametrize("impl", ["rp5v", "rp3v3", "isrc"])
def test_cc_rd_windows(base, parts, check, advert, impl):
    """Rd (R1/R2 from the netlist, tolerance extremes) with every Type-C source termination at its
    tolerance and rail extremes, both plug orientations, e-marked cable Ra on the other CC pin."""
    rds = [one([r for r in base.on_net(n, "R")], f"Rd on {n}") for n in parts.cc]
    lo_sink, hi_sink = TYPEC_SINK_WIN[advert]
    lo_src, hi_src = TYPEC_SRC_WIN[advert]
    vals = []
    for active, rd in zip(("CC1", "CC2"), rds):
        for sc in base.extremes([rd]):
            for corner in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                vals.append(cc_voltage(base, active, advert, impl, corner, sc))
    check(f"{advert}/{impl}: min CC voltage (sink window, Table 4-36)", min(vals), lo_sink, hi_sink, "V",
          "USB Type-C R2.0 Table 4-36 vRd-" + {"default": "USB", "1.5A": "1.5", "3.0A": "3.0"}[advert])
    check(f"{advert}/{impl}: max CC voltage (sink window, Table 4-36)", max(vals), lo_sink, hi_sink, "V",
          "USB Type-C R2.0 Table 4-36 vRd-" + {"default": "USB", "1.5A": "1.5", "3.0A": "3.0"}[advert])
    check(f"{advert}/{impl}: max CC voltage (source detects Rd)", max(vals), lo_src, hi_src, "V",
          "USB Type-C R2.0 Tables 4-32/33/34 Sink (vRd)")
    check(f"{advert}/{impl}: min CC voltage (source detects Rd)", min(vals), lo_src, hi_src, "V",
          "USB Type-C R2.0 Tables 4-32/33/34 Sink (vRd)")


def test_cc_rd_value(base, parts, check):
    """Each CC pin sees exactly one Rd to GND, inside the 5.1 k +-10 % class that allows power detection."""
    for n in parts.cc:
        rd = one([r for r in base.on_net(n, "R")], f"Rd on {n}")
        if set(base.pins[rd].values()) != {n, "GND"}:
            raise NetlistError(f"{rd} is not CC->GND")
        for sc in base.extremes([rd]):
            check(f"{rd} on {n} (tolerance extreme)", base.value(rd) * sc[rd], *TYPEC_RD[0], "Ohm", TYPEC_RD[1])


# ============================================================================================ capacitance budgets
def vbus_capacitance(base: Design, main: Design, vbias: float, cscale: dict, temp_factor: float,
                     only_cin: bool = False) -> float:
    """Small-signal capacitance seen at the J1 VBUS pads (or at BQ25180 IN with only_cin) at a DC bias."""
    net = Net(base, main, cscale=cscale)
    dk = Deck(f"VBUS capacitance at {vbias} V")
    for lib in (LIB_TVS, LIB_ESD, LIB_BQ, LIB_NRF):
        dk.include(lib)
    if only_cin:
        node = "vin"
        for ref in caps_on(base, {net.p.vbus_b}):
            dk += cap_lines(base, ref, "vin", "b", cscale.get(f"b:{ref}", 1.0), temp_factor)
    else:
        node = "vj1"
        net.tfac = lambda: temp_factor
        dk += net.lines()
    dk += [f"Vb bias 0 {vbias}", f"Lb bias {node} 1k", f"Iac 0 {node} DC 0 AC 1"]
    dk.ac("lin", 1, "1k", "1k")
    dk.print_op(f"imag(1/v({node}))/(2*pi*1000)")      # 1 A AC into the node: Y = 1/V, C = Im(Y)/omega
    r = run(dk)
    return r["op_0"]


def vbus_cap_scale(base, main, parts, sign: int) -> dict:
    """{'b:C1': 1 +- tol, 'm:C12': 1 +- tol} for the VBUS capacitors of both boards (tolerance from the netlist)."""
    out = {f"b:{r}": 1 + sign * base.tol(r) for r in caps_on(base, {parts.vbus_b})}
    out.update({f"m:{r}": 1 + sign * main.tol(r) for r in caps_on(main, parts.main_vbus_nets)})
    return out


def test_vbus_capacitance_typec_limit(base, main, parts, check):
    """Type-C sink: <= 10 uF between VBUS and GND while not attached (0 V bias), all caps at +tolerance
    and the X5R +15 % temperature bound."""
    hi = vbus_cap_scale(base, main, parts, +1)
    worst = max(vbus_capacitance(base, main, 0.0, hi, tf) for tf in (1.0, 1.0 + X5R_TEMP_BOUND))
    check("sink VBUS capacitance, unattached (C1 + C12 + TVS CJ, +tol, +15 % temp)", worst, None,
          TYPEC_VBUS_CAP[0], "F", TYPEC_VBUS_CAP[1])
    check("BQ25180 IN capacitance, 0 V, +tol, +15 % temp",
          vbus_capacitance(base, main, 0.0, hi, 1.0 + X5R_TEMP_BOUND, True), None, BQ_CIN[0][1], "F", BQ_CIN[1])


@pytest.mark.parametrize("vin", [5.0, 5.5])
def test_cin_after_dc_bias_25c(base, parts, check, vin, main):
    """C1 at the charger after DC-bias derating at the operating VIN, -tolerance, 25 C: >= 1 uF."""
    c = vbus_capacitance(base, main, vin, vbus_cap_scale(base, main, parts, -1), 1.0, only_cin=True)
    check(f"CIN effective at {vin} V, -tol, 25 C", c, BQ_CIN[0][0], BQ_CIN[0][1], "F", BQ_CIN[1])


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DESIGN ISSUE (margin): C1 2.2 uF/25 V 0603 X5R falls below the BQ25180's "
                   "1 uF effective CIN at 5.5 V with -10 % tolerance and the -15 % X5R temperature bound "
                   "(DC-bias curve is an estimate, see X5R_DCBIAS)")
@pytest.mark.parametrize("temp", [-10, 60])
def test_cin_after_dc_bias_temperature(base, parts, check, temp, main):
    c = vbus_capacitance(base, main, BQ_VIN_OP[0][1], vbus_cap_scale(base, main, parts, -1), 1 - X5R_TEMP_BOUND,
                         only_cin=True)
    check(f"CIN effective at 5.5 V, -tol, {temp} C (X5R -15 %)", c, BQ_CIN[0][0], BQ_CIN[0][1], "F", BQ_CIN[1])


# ============================================================================================ DC operating point
def dc_point(base, main, vsrc, r_cable, iin, temp=25.0, tvs="typ", ivbus=2.4e-3):
    net = Net(base, main, temp=temp, tvs=tvs, iin=iin, ivbus=ivbus, vusb=3.3)
    dk = net.deck(f"DC VBUS {vsrc} V, IIN {iin} A")
    dk += [f"Vsrc srcv 0 {vsrc}", f"Rcab srcv vj1 {r_cable}"]
    dk.op()
    dk.print_op("v(vin)", "v(vnrf)", "i(vitvs)", "v(vesd)")
    r = run(dk)
    return dict(vin=r["op_0"], vnrf=r["op_1"], itvs=r["op_2"], vesd=r["op_3"])


@pytest.mark.parametrize("vsrc", [4.5, 5.0, 5.5])
@pytest.mark.parametrize("iin", [0.0, 0.498, 1.1])
def test_dc_operating_point(base, main, check, vsrc, iin):
    """VBUS corners x charger input current (off / ILIM 500 mA setting max 498 mA / IIN abs max 1.1 A) through a
    100 mOhm cable: BQ25180 IN inside VIN_OP and below VIN_OVP; nRF VBUS inside its USB operating range."""
    op = dc_point(base, main, vsrc, CABLES["2m_1uH_100m"][2], iin)
    check(f"IN at VBUS {vsrc} V, IIN {iin} A", op["vin"], BQ_VIN_OP[0][0], BQ_VIN_OP[0][1], "V", BQ_VIN_OP[1])
    check(f"IN below OVP at VBUS {vsrc} V, IIN {iin} A", op["vin"], None, BQ_VIN_OVP_MIN[0], "V", BQ_VIN_OVP_MIN[1])
    check(f"nRF VBUS at VBUS {vsrc} V, IIN {iin} A", op["vnrf"], *NRF_VBUS_OP[0], "V", NRF_VBUS_OP[1])
    # informational: USBLC6 VBUS pin vs its stand-off voltage (IRM is only specified up to VRM 5.25 V)
    check(f"(info) USBLC6 VBUS pin at VBUS {vsrc} V (VRM 5.25 V)", op["vesd"], None, None, "V",
          "USBLC6-2 DS 11265 Rev5 Table 2 VRM 5.25 V (test condition of IRM, not an abs max)")


def test_tvs_not_in_breakdown_at_usb_max(base, main, check):
    """At the USB-C maximum (5.5 V, no load) the SMF5.0A must stay below breakdown: current < IT (10 mA) with the
    VBR-min / leakage-max corner (25 C: the datasheet gives no VBR or IR temperature coefficient)."""
    op = dc_point(base, main, 5.5, 0.05, 0.0, tvs="leakmax")
    check("D1 current at VBUS 5.5 V (VBR min, IR max corner)", abs(op["itvs"]), None, TVS_IT[0], "A", TVS_IT[1])


# ============================================================================================ hot plug
def hotplug(base, main, vsrc, cable, c_bulk, **kw) -> dict:
    key = ("hp", vsrc, cable, c_bulk, tuple(sorted((k, str(v)) for k, v in kw.items())), design_key(base))
    return cached(key, lambda: run(hotplug_deck(Net(base, main, **kw), vsrc, cable, c_bulk)))


GRID = [(v, c, b) for v in VBUS_SRC for c in CABLES for b in BULK]


@pytest.mark.parametrize("vsrc,cable,c_bulk", GRID, ids=[f"{v}V-{c}-{b * 1e6:.0f}uF" for v, c, b in GRID])
def test_hotplug_grid(base, main, check, vsrc, cable, c_bulk):
    """Legacy (hot VBUS) plug-in: peaks at BQ25180 IN and on the clamps; nRF VBUS peak recorded (its limit is
    checked in test_hotplug_nrf_vbus_abs_max)."""
    r = hotplug(base, main, vsrc, cable, c_bulk)
    tag = f"{vsrc} V, {cable}, {c_bulk * 1e6:.0f} uF"
    conducting = r["vtvs_max"] >= TVS_VBR[0][0]
    check(f"(info) D1 in breakdown ({tag}): peak at D1 {'>=' if conducting else '<'} VBR min", r["vtvs_max"], None,
          None, "V", TVS_VBR[1])
    check(f"IN peak ({tag})", r["vin_max"], None, BQ_IN_ABS_MAX[0], "V", BQ_IN_ABS_MAX[1])
    check(f"D1 peak current ({tag})", r["itvs_max"], None, TVS_IPP[0], "A", TVS_IPP[1])
    check(f"U2 VBUS clamp peak current ({tag})", r["itr_max"], None, LC6_IPP[0], "A", LC6_IPP[1])
    check(f"(info) U2 VBUS pin peak ({tag})", r["vesd_max"], None, None, "V", "USBLC6-2 DS 11265 Rev5 (no VBUS abs max)")
    check(f"(info) IN peak vs VIN_OVP min ({tag}): charger input FET trips", r["vin_max"], None, None, "V",
          BQ_VIN_OVP_MIN[1])
    check(f"(info) nRF VBUS peak ({tag})", r["vnrf_max"], None, None, "V", NRF_VBUS_ABS[1])
    check(f"(info) IN at the end of the run, ringing tail ({tag})", r["vin_end"], None, None, "V",
          "steady state is checked in test_dc_operating_point")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DESIGN ISSUE: hot plug overshoots the nRF52840 VBUS abs max 5.8 V "
                   "(link VBUS goes straight to U10 VBUS with only C12; no series R as in Nordic's reference)")
def test_hotplug_nrf_vbus_abs_max(base, main, check):
    worst = max((hotplug(base, main, v, c, b)["vnrf_max"], (v, c, b)) for v, c, b in GRID)
    lowest = min((hotplug(base, main, v, c, b)["vnrf_max"], (v, c, b)) for v, c, b in GRID)
    check(f"(info) lowest nRF VBUS peak of the grid {lowest[1]}", lowest[0], None, None, "V", NRF_VBUS_ABS[1])
    check(f"nRF VBUS peak, worst of the grid {worst[1]}", worst[0], None, NRF_VBUS_ABS[0][1], "V", NRF_VBUS_ABS[1])


CORNERS = [(t, tvs) for t in (-10, 25, 60) for tvs in ("typ", "clampmax")]


@pytest.mark.parametrize("temp,tvs", CORNERS, ids=[f"{t}C-{v}" for t, v in CORNERS])
def test_hotplug_corners(base, main, check, temp, tvs):
    """Worst grid point at -10/25/60 C (X5R -15 % bound away from 25 C, SPICE temperature for the diodes), TVS
    typical and datasheet clamp-max, C1/C12 tolerance extremes: BQ25180 IN and clamp currents."""
    v, c, b = WORST
    p = Parts(base, main)
    for sc in base.extremes(caps_on(base, {p.vbus_b})):
        for sm in main.extremes(caps_on(main, p.main_vbus_nets)):
            scale = {**{f"b:{k}": x for k, x in sc.items()}, **{f"m:{k}": x for k, x in sm.items()}}
            r = hotplug(base, main, v, c, b, temp=temp, tvs=tvs, cscale=scale)
            tag = f"{temp} C, TVS {tvs}, " + ", ".join(f"{k} x{x:.2f}" for k, x in scale.items())
            check(f"IN peak ({tag})", r["vin_max"], None, BQ_IN_ABS_MAX[0], "V", BQ_IN_ABS_MAX[1])
            check(f"D1 peak current ({tag})", r["itvs_max"], None, TVS_IPP[0], "A", TVS_IPP[1])
            check(f"U2 VBUS clamp peak current ({tag})", r["itr_max"], None, LC6_IPP[0], "A", LC6_IPP[1])
            check(f"(info) nRF VBUS peak ({tag})", r["vnrf_max"], None, None, "V", NRF_VBUS_ABS[1])


@pytest.mark.parametrize("temp,tvs", [(-10, "clampmax"), (25, "typ"), (60, "clampmax")])
def test_hotplug_fix_preview_nrf_series_r(base, main, check, temp, tvs):
    """WHAT-IF (not in the schematic yet): Nordic's reference 4.7 Ohm in series with the nRF VBUS pin (nRF52840 PS
    v1.1 section 7.3, circuit configuration 1, R1 4R7, 'recommended for new designs'), C12 behind it.
    Shows the proposed fix for test_hotplug_nrf_vbus_abs_max at the worst grid point and corners, and that the
    DC drop keeps nRF VBUS inside its operating range at the lowest VBUS with the charger at 1.1 A."""
    p = Parts(base, main)
    if p.nrf_vbus != p.vbus_m:
        pytest.skip("the schematic already has a series part in front of the nRF VBUS pin "
                    "(test_hotplug_nrf_vbus_abs_max checks the real design)")
    v, c, b = WORST
    for sm in main.extremes(caps_on(main, p.main_vbus_nets)):
        sm = {f"m:{k}": x for k, x in sm.items()}
        r = hotplug(base, main, v, c, b, temp=temp, tvs=tvs, cscale=sm, series_r_nrf=4.7)
        check(f"nRF VBUS peak with 4.7 Ohm ({temp} C, TVS {tvs}, {sm})", r["vnrf_max"], None, NRF_VBUS_ABS[0][1], "V",
              NRF_VBUS_ABS[1])
    net = Net(base, main, iin=1.1, vusb=3.3, series_r_nrf=4.7)
    dk = net.deck("DC with 4.7 Ohm")
    dk += ["Vsrc srcv 0 4.5", f"Rcab srcv vj1 {CABLES['2m_1uH_100m'][2]}"]
    dk.op()
    dk.print_op("v(vnrf)")
    check("nRF VBUS DC with 4.7 Ohm at VBUS 4.5 V, IIN 1.1 A", run(dk)["op_0"], *NRF_VBUS_OP[0], "V", NRF_VBUS_OP[1])


# ============================================================================================ ESD
def esd(base, main, node, kv, **kw) -> dict:
    key = ("esd", node, kv, tuple(sorted((k, str(v)) for k, v in kw.items())), design_key(base))
    return cached(key, lambda: run(esd_deck(Net(base, main, **kw), node, kv)))


# unplugged device (the only case where the VBUS / D+ / D- contacts can be touched): VBUS and VUSB33 at 0 V
ESD_WORST = dict(tvs="clampmax", esd="max")     # datasheet-max clamp corners = most stress downstream


@pytest.mark.parametrize("harness", HARNESS_MM)
@pytest.mark.parametrize("kv", [8.0, -8.0])
def test_esd_vbus(base, main, check, kv, harness):
    """IEC 61000-4-2 +-8 kV contact on the J1 VBUS pads: BQ25180 IN and (through the link) nRF VBUS."""
    r = esd(base, main, "vj1", kv, harness_mm=harness, **ESD_WORST)
    tag = f"{kv:+.0f} kV on VBUS, harness {harness:.0f} mm"
    check(f"(info) gun peak current ({tag})", max(r["ig_max"], -r["ig_min"]), None, None, "A", IEC_SRC)
    check(f"(info) D1 peak current ({tag})", max(r["itvs_max"], -r["itvs_min"]), None, None, "A",
          "SMF5.0A DS: IEC 61000-4-2 30 kV contact rating")
    check(f"(info) U2 VBUS clamp peak current ({tag})", max(r["itr_max"], -r["itr_min"]), None, None, "A",
          "USBLC6-2 DS 11265 Rev5 Table 1: IEC 61000-4-2 15 kV contact")
    check(f"IN max ({tag})", r["vin_max"], None, BQ_IN_ABS_MAX[0], "V", BQ_IN_ABS_MAX[1])
    check(f"IN clamp current ({tag})", max(r["ibq_max"], -r["ibq_min"]), None, hbm_amps(BQ_ESD_HBM[0]), "A",
          BQ_ESD_HBM[1] + " -> 1.67 A HBM peak (100 pF / 1.5 kOhm)")
    check(f"nRF VBUS max ({tag})", r["vnrf_max"], None, NRF_VBUS_ABS[0][1], "V", NRF_VBUS_ABS[1])
    check(f"nRF VBUS pad current ({tag})", max(r["inrfvb_max"], -r["inrfvb_min"]), None, hbm_amps(NRF_ESD_HBM[0]),
          "A", NRF_ESD_HBM[1] + " -> 1.33 A HBM peak (100 pF / 1.5 kOhm)")
    check(f"(info) IN min, open-circuit view ({tag})", r["vin_min"], None, None, "V", BQ_IN_ABS_MIN[1])


DATA = [(sig, kv) for sig in ("dp", "dm") for kv in (8.0, -8.0)]


@pytest.mark.parametrize("harness", HARNESS_MM)
@pytest.mark.parametrize("sig,kv", DATA, ids=[f"{s}{k:+.0f}kV" for s, k in DATA])
def test_esd_data_lines_vbus_side(base, main, check, sig, kv, harness):
    """IEC +-8 kV on D+ / D-: U2 steers the strike into VBUS; BQ25180 IN and nRF VBUS must stay in rating."""
    r = esd(base, main, f"{sig}j1", kv, harness_mm=harness, **ESD_WORST)
    tag = f"{kv:+.0f} kV on {sig.upper()}, harness {harness:.0f} mm"
    check(f"(info) U2 I/O clamp peak ({tag})", max(r[f"{sig}esd_max"], -r[f"{sig}esd_min"]), None, None, "V",
          "USBLC6-2 DS 11265 Rev5 2.1 (VCL+ ~31 V at 24 A typ)")
    check(f"IN max ({tag})", r["vin_max"], None, BQ_IN_ABS_MAX[0], "V", BQ_IN_ABS_MAX[1])
    check(f"nRF VBUS max ({tag})", r["vnrf_max"], None, NRF_VBUS_ABS[0][1], "V", NRF_VBUS_ABS[1])


NRF_PAD_LIMIT = (hbm_amps(NRF_ESD_HBM[0]), NRF_ESD_HBM[1] + " -> 1.33 A HBM peak (100 pF / 1.5 kOhm)")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="DESIGN ISSUE: IEC 8 kV on D+/D- drives 2.6-3.7 A for ~100 ns into the nRF52840 USB pads "
                   "through the ~145 nH link path (USBLC6 at J1 only); the nRF is rated HBM 2 kV (1.33 A)")
@pytest.mark.parametrize("sig,kv", DATA, ids=[f"{s}{k:+.0f}kV" for s, k in DATA])
def test_esd_data_lines_nrf_pad_current(base, main, check, sig, kv):
    """Residual current into the nRF52840 D+/D- pad (assumed on-chip clamp 3 Ohm, U2 at its datasheet-max clamp,
    100 mm harness) against the peak current of the HBM 2 kV test the pin is qualified to."""
    r = esd(base, main, f"{sig}j1", kv, **ESD_WORST)
    tag = f"{kv:+.0f} kV on {sig.upper()}"
    check(f"(info) nRF {sig.upper()} pad voltage ({tag})", max(r[f"{sig}nrf_max"], -r[f"{sig}nrf_min"]), None, None,
          "V", "nRF52840 PS v1.1 Table 173 I/O pin VDD + 0.3 V (DC rating, not an ESD limit)")
    check(f"nRF {sig.upper()} pad current, on-chip clamp 3 Ohm ({tag})",
          max(r[f"inrf{sig}_max"], -r[f"inrf{sig}_min"]), None, *NRF_PAD_LIMIT[:1], "A", NRF_PAD_LIMIT[1])


SENS = [(kv, h, esdc, resd) for kv in (8.0, -8.0) for h in HARNESS_MM for esdc in ("typ", "max") for resd in (1.0, 3.0, 10.0)]


@pytest.mark.slow
def test_esd_data_lines_sensitivity(base, main, check):
    """Record (no limit) how the nRF D+ pad current depends on what is not known exactly: harness length,
    USBLC6 clamp corner (typical / datasheet max) and the nRF's on-chip clamp resistance (1 / 3 / 10 Ohm),
    without and with the proposed second-stage USBLC6 at U10."""
    for kv, h, esdc, resd in SENS:
        for second in (False, True):
            net = Net(base, main, harness_mm=h, tvs="clampmax", esd=esdc, resd=resd)
            dk = esd_deck(net, "dpj1", kv)
            if second:
                dk += [f"Xesd2 dpnrf 0 dmnrf vnrf USBIN_USBLC6_2 {net.esd_params()}"]
            r = run(dk)
            check(f"(info) nRF D+ pad current, {kv:+.0f} kV, harness {h:.0f} mm, USBLC6 {esdc}, on-chip clamp "
                  f"{resd:g} Ohm{', 2nd-stage USBLC6' if second else ''}", max(r["inrfdp_max"], -r["inrfdp_min"]),
                  None, None, "A", NRF_PAD_LIMIT[1])


@pytest.mark.parametrize("harness", HARNESS_MM)
@pytest.mark.parametrize("sig,kv", DATA, ids=[f"{s}{k:+.0f}kV" for s, k in DATA])
def test_esd_fix_preview_second_stage(base, main, check, sig, kv, harness):
    """WHAT-IF (not in the schematic yet): a second USBLC6-2SC6 next to U10 on the main board (I/O on USB_DP/USB_DM,
    VBUS pin on VBUS). The link inductance then decouples the two stages. Typical clamp corners for both arrays
    (the datasheet-max combination is recorded by test_esd_data_lines_sensitivity)."""
    net = Net(base, main, harness_mm=harness, tvs="clampmax", esd="typ")
    dk = esd_deck(net, f"{sig}j1", kv)
    dk += [f"Xesd2 dpnrf 0 dmnrf vnrf USBIN_USBLC6_2 {net.esd_params()}"]
    r = run(dk)
    check(f"nRF {sig.upper()} pad current with 2nd-stage USBLC6 ({kv:+.0f} kV, harness {harness:.0f} mm)",
          max(r[f"inrf{sig}_max"], -r[f"inrf{sig}_min"]), None, *NRF_PAD_LIMIT[:1], "A", NRF_PAD_LIMIT[1])


# ============================================================================================ fault injection
@pytest.mark.fault
def test_fault_c1_wrong_value_breaks_vbus_capacitance(base, main, parts, check):
    """C1 fitted as 10 uF (the SYS value) instead of 2.2 uF: the sink VBUS capacitance check must catch it."""
    c1 = one(caps_on(base, {parts.vbus_b}), "IN capacitor")
    base.override(c1, "10u/25V")
    c = vbus_capacitance(base, main, 0.0, {}, 1.0)
    check(f"FAULT {c1}=10u: sink VBUS capacitance exceeds the Type-C limit (detected)", c, TYPEC_VBUS_CAP[0], None, "F",
          TYPEC_VBUS_CAP[1])


@pytest.mark.fault
def test_fault_rd_left_off(base, parts, check):
    """R1 (Rd on CC1) not fitted: in the CC1 orientation the source sees an open CC and must not attach."""
    rd = one(base.on_net(parts.cc[0], "R"), "Rd on CC1")
    base.remove(rd)
    v = cc_voltage(base, "CC1", "default", "rp5v", (1, 1), {})
    check(f"FAULT {rd} off: CC1 voltage above the Default vRd window (detected)", v, TYPEC_SRC_WIN["default"][1], None,
          "V", "USB Type-C R2.0 Table 4-32 vRd max 1.50 V / vOPEN >= 1.65 V")


@pytest.mark.fault
def test_fault_rd_wired_to_wrong_cc(base, parts, check):
    """Wrong connection: both Rd resistors land on CC1 (copy-paste error), CC2 left open."""
    base = copy.deepcopy(base)
    rd2 = one(base.on_net(parts.cc[1], "R"), "Rd on CC2")
    pin = one([p for p, n in base.pins[rd2].items() if n == parts.cc[1]], "Rd2 CC pin")
    base.pins[rd2][pin] = parts.cc[0]
    v = cc_voltage(base, "CC2", "3.0A", "rp5v", (-1, -1), {})
    check("FAULT Rd2 on CC1: CC2 voltage above the 3.0 A vRd window (detected)", v, TYPEC_SRC_WIN["3.0A"][1], None,
          "V", "USB Type-C R2.0 Table 4-34 vRd max 2.45 V")


@pytest.mark.fault
def test_fault_tvs_reversed(base, main, parts, check):
    """Wrong orientation: D1 placed with the cathode band on GND. At 5 V the TVS is forward biased."""
    base = copy.deepcopy(base)
    pins = base.pins[parts.tvs]
    pins["1"], pins["2"] = pins["2"], pins["1"]
    op = dc_point(base, main, 5.0, CABLES["1m_1uH_50m"][2], 0.0)
    check("FAULT D1 reversed: D1 DC current at VBUS 5 V far above IT (detected)", abs(op["itvs"]), TVS_IT[0], None, "A",
          TVS_IT[1])
