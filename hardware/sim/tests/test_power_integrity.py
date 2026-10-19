"""Power integrity of VSYS, end to end (circuit key: power_integrity).

Path simulated (every passive from the two netlists, every connector contact count from the netlists):

    1S LiPo (OCV + R_int) -> battery connector J2 (contacts per rail from the base netlist)
      -> BQ25180 BAT/SYS power path (or USB VBUS -> IN -> SYS regulation, ILIM, supplement)
      -> base VSYS caps -> 12-way link harness (VSYS / GND conductors counted from J1 / J3 in the netlists,
         2 JST SH contacts + 28 AWG wire each, R and L)
      -> main VSYS caps -> loads:
           TPS22917 U2 -> VLED -> 48x WS2812C-2020-V6 (full white, and PWM edges of all LEDs together)
           TPS22917 U21 -> OLED_VIN -> TPS61040 U20 input (constant power + DCM ripple)
           DRV8837 U40/U41 VM (both coils, full-on or 25 kHz PWM with aligned edges)
           RT9080 U1 -> +3V3 (nRF52840 incl. +8 dBm TX bursts, W25Q128JV erase, sensors)

Each board keeps its own ground: base GND is SPICE node 0, main GND is node `gm`, joined only by the
harness GND conductors, so the ground offset between the boards (I*R + L*di/dt) is simulated and checked
against the logic thresholds of the lines that cross the link (I2C_SCL/SDA, CHG_INT_N, BTN_N).

Limits (every one from a datasheet or SPEC.md, quoted in each check's source string):
    VLED >= 3.3 V and <= 5.3 V           WS2812C-2020-V6 DS p.2 (VDD 3.3-5.3 V)
    +3V3 >= 2.7 V                         W25Q128JV DS Rev F 9.2 (binding; nRF52840 PS 8 and TMAG5273 5.3 need 1.7 V)
    I(BAT) <= 1.5 A                       BQ25180 SLUSE99C 7.5 IBAT_OCP (CHARGECTRL1 = 0x92 -> 1.5 A)
    I(SYS) <= 1.5 A DC                    BQ25180 SLUSE99C 7.1 SYS discharge current
    V(BAT) >= 3.0 V for <= 60 us          BQ25180 SLUSE99C 7.5 VBUVLO (BUVLO 010) and 7.6 tBUVLO
    I(IN) <= 1.1 A                        BQ25180 SLUSE99C 7.1 / 7.4 input current
    link contact <= 1.0 A (average)       JST SH datasheet, 1.0 A per contact with AWG #28
    BQ25180 SCL/SDA low <= 0.4 V          BQ25180 SLUSE99C 7.5 VIL
    nRF input low <= 0.3 x VDD            nRF52840 PS v1.1 6.9.3.1 VIL
    pins >= -0.3 V                        BQ25180 7.1 (all other pins), nRF52840 PS 9 absolute maximum

Firmware policy used for the "capped" scenarios (docs/firmware.md 5.8, 6.3, 7.4, 12.4): LED average
150 mA sustained / 300 mA bursts when VBAT >= 3.65 V, 100 mA below 3.60 V and while the actuator moves,
LEDs off (2 mA red cue) below 3.53 V, SHIP below 3.48 V, actuator moves only with VSYS >= 3.40 V.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace

import numpy as np
import pytest

import spicelib
from spicelib import Deck, Design

# --------------------------------------------------------------------------------------------- models
LIB = {k: f"power_integrity__{k}.lib" for k in
       ("bq25180", "tps22917", "rt9080", "ws2812c", "tps61040", "drv8837", "nrf52840")}

# --------------------------------------------------------------------------------------------- limits
SRC_WS = "WS2812C-2020-V6 DS (Worldsemi) p.2 max ratings: VDD 3.3-5.3 V"
SRC_3V3 = ("W25Q128JV DS Rev F 9.2 VCC >= 2.7 V (binding); nRF52840 PS v1.1 8 VDD >= 1.7 V; "
           "TMAG5273 DS SLYS045C 5.3 VCC >= 1.7 V")
SRC_OCP = "BQ25180 DS SLUSE99C 7.5 IBAT_OCP 1.5 A (CHARGECTRL1 = 0x92)"
SRC_SYS = "BQ25180 DS SLUSE99C 7.1 SYS discharge current 1.5 A DC"
SRC_BUVLO = "BQ25180 DS SLUSE99C 7.5 VBUVLO 3.0 V (BUVLO = 010) with 7.6 tBUVLO 60 us deglitch"
SRC_IIN = "BQ25180 DS SLUSE99C 7.1 / 7.4 input current (IN to SYS) 1.1 A"
SRC_SH = "JST SH DS (eSH): current rating 1.0 A per contact, AWG #28"
SRC_BQ_VIL = "BQ25180 DS SLUSE99C 7.5 I2C VIL 0.4 V (SCL/SDA)"
SRC_NRF_VIL = "nRF52840 PS v1.1 6.9.3.1 VIL = 0.3 x VDD"
SRC_NEG = "BQ25180 DS 7.1 / nRF52840 PS v1.1 9: pins >= -0.3 V"
SRC_LSW = "TPS22917 DS SLVSDW8B 7.1 IPLS 2.5 A (pulse < 300 us)"

WS_VDD_MIN, WS_VDD_MAX = 3.3, 5.3
V3V3_MIN = 2.7
IBAT_OCP = 1.5
SYS_DC_MAX = 1.5
VBUVLO, TBUVLO = 3.0, 60e-6
IIN_MAX = 1.1
SH_CONTACT_A = 1.0
BQ_VIL = 0.4
NRF_VIL_FRAC = 0.3
PIN_ABS_MIN = -0.3
LSW_IPLS = 2.5

# ------------------------------------------------------------------- wiring and battery (not in netlists)
AWG28_OHM_PER_M = 0.2129   # 28 AWG copper, 0.0810 mm^2: 212.9 mOhm/m at 20 C (ASTM B258 AWG table)
AWG28_DIA = 0.321e-3       # m, 28 AWG bare conductor diameter (ASTM B258)
CU_TC = 0.00393            # 1/C, annealed copper (IEC 60028)
HARNESS_LEN = 0.100        # m, task brief "~100 mm" (docs/architecture.md 4.2 estimates 50-80 mm)
MU0 = 4e-7 * math.pi
# max resistance per mated contact (initial, after environmental tests), JST SH (eSH) and PH (ePH) datasheets
CONTACT_R = {"SH": (0.020, 0.040), "PH": (0.010, 0.020)}
BATT_RINT = (0.100, 0.200)  # Ohm, 1S LiPo pack (cell + PCM) range of the task brief

# ------------------------------------------------------------------------------- IC datasheet values
BQ_VSYSREG, BQ_VSYSREG_TOL = 4.5, 0.02              # SLUSE99C Table 8-3, 7.5 VSYS_REG_ACCURACY
BQ_ILIM500 = (0.450, 0.475, 0.498)                  # SLUSE99C 7.5 ILIM, 500 mA code (min, typ, max)
BQ_ILIM100 = (0.080, 0.090, 0.098)                  # SLUSE99C 7.5 ILIM, 100 mA code
BQ_RON_IN = (0.270, 0.470)                          # SLUSE99C 7.5 RON_IN typ / max
BQ_RON_BAT = (0.055, 0.090)                         # SLUSE99C 7.5 RON_BAT typ / max
BQ_ICHG = 0.400                                     # ICHG_CTRL = 0x43 (docs/firmware.md 13.1)
BQ_OD_R = 0.4 / 5e-3                                # SLUSE99C 7.5 VOL 0.4 V at 5 mA (/INT, SDA)
# TPS22917 RON at IOUT 200 mA (SLVSDW8B 7.5): VIN -> (typ 25 C, max 25 C, max -40..85 C)
LSW_RON = {1.8: (0.120, 0.150, 0.175), 3.6: (0.090, 0.110, 0.140), 5.0: (0.080, 0.100, 0.120)}
LDO_VSET, LDO_ACC = 3.3, 0.02                       # DS9080-09 14 VVOUT_ACC
LDO_RDROP = (0.31 / 0.6, 0.53 / 0.6)                # DS9080-09 14 VDROP at 600 mA, VOUT >= 3 V (typ, max)
LDO_GM = 0.6 / (0.01 * 3.3)                         # DS9080-09 14 VLOAD_REG <= 1 % over 1..600 mA
WS_ICH = 5e-3                                       # WS2812C-2020-V6 DS p.1/p.3: 5 mA per channel
WS_FPWM = 2e3                                       # WS2812C-2020-V6 DS p.1: 2 kHz PWM
WS_IIC = 0.2e-3                                     # per lit LED, docs/firmware.md 6.3 (TVP; not in the DS)
WSB_ICH = 12e-3                                     # WS2812B-2020-V6 pin-compatible alternate (SPEC 5.4)
NRF_ROL = 0.4 / 1e-3                                # nRF52840 PS 6.9.3.1 IOL,SD >= 1 mA at 0.4 V
QFET_RDS = 3.5                                      # BSS138DW DS30203 RDS(on) max (at VGS 10 V; tiny current here)
# +3V3 load (docs/architecture.md 7: about 50 mA peak): TX +8 dBm 14.8 mA (nRF52840 PS 6.20.15.2),
# CPU 3.3 mA (PS 5.2.1.3), W25Q128JV erase 25 mA max (DS Rev F 9.4), TMAG5273 2.3 mA, IMU/VCI/misc 0.5 mA
I3V3_TX = 14.8e-3
I3V3_BASE = 3.3e-3 + 25e-3 + 2.3e-3 + 0.5e-3
# OLED: NHD-1.5-128128G ICC at 100 % on 42 mA max (panel DS, display research), TPS61040 (SLVS413L)
OLED_ICC_MAX = 42e-3
OLED_ETA = 0.75
BOOST_ILIM = (0.350, 0.400, 0.450)                  # SLVS413L 5.5 ILIM
BOOST_VFB = 1.233                                   # SLVS413L 5.5 VFB typ
BOOST_VF = 0.45                                     # B5819W forward drop at ~0.4 A (assumed; only shapes the ripple)
# detent stepper (docs/firmware.md 5.3): coil + rDS(on) 20.3 Ohm, run current 160 mA, PWM 25 kHz
MOTOR_RCOIL, MOTOR_IRUN, MOTOR_FPWM = 20.3, 0.160, 25e3

# firmware policy (docs/firmware.md 6.3, 5.8, 7.4, 12.4)
FW_LED_BURST, FW_LED_SUST, FW_LED_LOW, FW_LED_MOVING, FW_LED_CUE = 0.300, 0.150, 0.100, 0.100, 0.002
FW_V_FULL, FW_V_DERATE, FW_V_OFF, FW_V_SHIP, FW_V_MOVE = 3.65, 3.60, 3.53, 3.48, 3.40


# =========================================================================================== corners
@dataclass(frozen=True)
class Corner:
    name: str
    temp: float = 25.0          # C
    rint: float = BATT_RINT[0]  # Ohm
    aged: bool = False          # contacts after environmental tests
    fet: str = "typ"            # RON / dropout: 'typ' (25 C typical) or 'max' (datasheet max at temp)
    spacing: float = 1.0e-3     # m, VSYS-to-GND wire spacing in the harness bundle
    caps: str = "nom"           # 'nom' or 'min' (every capacitor at -tolerance from its netlist value)
    length: float = HARNESS_LEN


NOMINAL = Corner("nominal")
# worst: weakest battery, aged contacts, hot FETs at datasheet max, wires spread across the 6 mm bore, caps low
WORST = Corner("worst", temp=60.0, rint=BATT_RINT[1], aged=True, fet="max", spacing=5.0e-3, caps="min")
COLD = Corner("cold", temp=-10.0, rint=BATT_RINT[1], aged=True, fet="max", spacing=5.0e-3, caps="min")


def lsw_ron(vin: float, c: Corner) -> float:
    """TPS22917 RON at VIN (interpolated in VIN) for the corner (SLVSDW8B 7.5)."""
    ks = sorted(LSW_RON)
    vin = min(max(vin, ks[0]), ks[-1])
    for a, b in zip(ks, ks[1:]):
        if a <= vin <= b:
            f = (vin - a) / (b - a)
            typ25, max25, max85 = (LSW_RON[a][i] + f * (LSW_RON[b][i] - LSW_RON[a][i]) for i in range(3))
            break
    if c.fet == "typ":
        return typ25
    t = min(max(c.temp, 25.0), 85.0)
    return max25 + (max85 - max25) * (t - 25.0) / 60.0


# =========================================================================================== loads
@dataclass
class Loads:
    led_idc: float = 0.0        # A per channel, steady
    led_ipk: float = 0.0        # A per channel, PWM amplitude (all channels of all LEDs switching together)
    led_duty: float = 0.5
    led_on: bool = True         # LED_PWR_EN high from t = 0
    led_on_at: float | None = None   # LED_PWR_EN rising edge time (inrush runs)
    oled_icc: float = 0.0       # panel VCC current at the boost output, A (0: U21 off)
    oled_ripple: bool = True
    motor: str = "off"          # off | full | pwm
    motor_icoil: float = 0.0    # A per coil (pwm)
    i3v3_base: float = I3V3_BASE
    i3v3_tx: float = I3V3_TX
    tx: bool = True             # TX bursts (else i3v3_tx added as DC)
    label: str = ""


def fw_led_total(cap: float, n: int) -> float:
    """Firmware cap (A, average) -> per-channel average current with every channel of n LEDs lit."""
    return cap / (3 * n)


# =========================================================================================== system
def _link_ref(d: Design) -> str:
    refs = [r for r, c in d.comps.items() if c["value"] == "LINK"]
    assert len(refs) == 1, f"{d.board}: link connector not found ({refs})"
    return refs[0]


def link_pins(d: Design, net: str) -> list:
    ref = _link_ref(d)
    return sorted((p for p, n in d.pins[ref].items() if n == net and p.isdigit()), key=int)


def batt_connector(base: Design):
    refs = [r for r, c in base.comps.items() if c["value"] == "BATT"]
    assert len(refs) == 1, refs
    ref = refs[0]
    fp = base.comps[ref]["fields"].get("Footprint", "") + " " + base.mpn(ref)
    series = "SH" if ("JST_SH" in fp or "SRSS" in fp) else "PH" if ("JST_PH" in fp or "-PH-" in fp) else None
    assert series, f"unknown battery connector series: {fp}"
    pos = [p for p, n in base.pins[ref].items() if n == "VBAT" and p.isdigit()]
    neg = [p for p, n in base.pins[ref].items() if n == "GND" and p.isdigit()]
    return ref, series, len(pos), len(neg)


class System:
    """Builds one ngspice deck of the whole VSYS path from the two netlists."""

    MAIN_NETS = {"VSYS", "GND", "VLED", "+3V3", "LSW_CT", "LSW_QOD", "OLED_LSW_CT", "OLED_VIN", "VSYS_SENSE",
                 "LED_PWR_EN", "OLED_VCC_EN", "I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N"}
    BASE_NETS = {"VSYS", "GND", "VBAT", "VBUS"}
    LOGIC = ("I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N")

    def __init__(self, main: Design, base: Design, corner: Corner = NOMINAL):
        self.main, self.base, self.c = main, base, corner
        self.n_vsys = len(link_pins(main, "VSYS"))
        self.n_gnd = len(link_pins(main, "GND"))
        assert link_pins(main, "VSYS") == link_pins(base, "VSYS") and \
            link_pins(main, "GND") == link_pins(base, "GND"), "link pinout differs between the boards"
        self.bat_ref, self.bat_series, self.n_bpos, self.n_bneg = batt_connector(base)
        self.n_led = len([r for r in main.on_net("VLED", "D") if main.fitted(r)
                          and main.pins[r].get("4") == "VLED"])

    # ------------------------------------------------------------------ node helpers
    def m(self, net: str) -> str:
        n = self.main.node(net)
        return "gm" if n == "0" else "m_" + n

    def b(self, net: str) -> str:
        n = self.base.node(net)
        return "0" if n == "0" else "b_" + n

    def mpin(self, ref, pin):
        n = self.main.pin(ref, pin)
        return "gm" if n == "0" else "m_" + n

    def bpin(self, ref, pin):
        n = self.base.pin(ref, pin)
        return "0" if n == "0" else "b_" + n

    @staticmethod
    def _remap(lines, prefix, gnd, tag):
        out = []
        for ln in lines:
            t = ln.split()
            t[0] = f"{t[0]}_{tag}"
            t[1:3] = [gnd if x == "0" else prefix + x for x in t[1:3]]
            out.append(" ".join(t))
        return out

    def _scale(self, d: Design, nets):
        if self.c.caps != "min":
            return None
        return {r: 1.0 - d.tol(r) for r in d.comps if r[0] == "C" and r[1:2].isdigit()}

    # ------------------------------------------------------------------ physical values
    def contact_r(self, series="SH"):
        return CONTACT_R[series][1 if self.c.aged else 0]

    def conductor_r(self):
        wire = AWG28_OHM_PER_M * self.c.length * (1 + CU_TC * (self.c.temp - 20.0))
        return 2 * self.contact_r("SH") + wire

    def loop_l(self):
        s = max(self.c.spacing, 1.01 * AWG28_DIA)
        return MU0 / math.pi * math.acosh(s / AWG28_DIA) * self.c.length

    def boost(self, vin: float, icc: float):
        """TPS61040 input model params at VIN for a panel current icc (netlist L20, R26/R27)."""
        L = self.main.value("L20")
        vout = BOOST_VFB * (1 + self.main.value("R26") / self.main.value("R27"))
        ilim = BOOST_ILIM[2]
        ipk = ilim + vin / L * 100e-9
        pin = min(vout * icc / OLED_ETA, vin * ipk / 2)
        ton = L * ipk / vin
        toff = L * ipk / (vout + BOOST_VF - vin)
        iavg = pin / vin
        tper = max(ipk * (ton + toff) / (2 * iavg), ton + toff + 1e-9) if iavg > 0 else 1e-3
        return dict(PIN=pin, KSHAPE=2 * tper / (ton + toff), TON=ton, TOFF=toff, TPER=tper, vout=vout, ipk=ipk)

    # ------------------------------------------------------------------ deck
    def deck(self, title: str, loads: Loads, vbat: float | None = 3.7, vbus: float | None = None,
             ilim=BQ_ILIM500[0], vsysreg=BQ_VSYSREG, logic: bool = False, bq_extra: dict | None = None):
        c, M, B = self.c, self.main, self.base
        typ = c.fet == "typ"
        d = Deck(title)
        for k in LIB.values():
            d.include(k)
        self.vnom = vsysreg if vbus else (vbat or 0.0)

        # ---- battery and its connector (contacts per rail from the netlist)
        rc_b = self.contact_r(self.bat_series)
        if vbat is not None:
            d += [f"Vocv bat_p bat_n DC {vbat}", f"Rint bat_p bat_i {c.rint}", "Vibat bat_i bat_c 0",
                  f"Rbcon_p bat_c {self.b('VBAT')} {rc_b / self.n_bpos:.6g}",
                  f"Rbcon_n bat_n 0 {rc_b / self.n_bneg:.6g}"]
        d += [f"Rvbat_leak {self.b('VBAT')} 0 10meg"]
        # ---- USB VBUS (stiff source at the corner value)
        if vbus is not None:
            d += [f"Vbus vbus_src 0 DC {vbus}", f"Viin vbus_src {self.b('VBUS')} 0"]
        d += [f"Rvbus_leak {self.b('VBUS')} 0 1meg"]
        # ---- BQ25180 power path
        bq = dict(VSYSREG=vsysreg, ILIM=ilim, RON_IN=BQ_RON_IN[0 if typ else 1],
                  RON_BAT=BQ_RON_BAT[0 if typ else 1], ICHG=BQ_ICHG)
        bq.update(bq_extra or {})
        ps = " ".join(f"{k}={v:.6g}" for k, v in bq.items())
        d += [f"Xbq {self.bpin('U1', 'IN')} bq_sys {self.bpin('U1', 'BAT')} {self.bpin('U1', 'GND')} "
              f"BQ25180_PP {ps}", f"Visys bq_sys {self.bpin('U1', 'SYS')} 0"]
        # ---- base passives
        d += self._remap(B.passives(nets=self.BASE_NETS, scale=self._scale(B, self.BASE_NETS)), "b_", "0", "b")
        # ---- harness: VSYS and GND bundles (conductor count from the netlist), L split evenly
        rcond, lh = self.conductor_r(), self.loop_l() / 2
        d += [f"Vilink {self.b('VSYS')} hv1 0", f"Rh_vsys hv1 hv2 {rcond / self.n_vsys:.6g}",
              f"Lh_vsys hv2 {self.m('VSYS')} {lh:.6g}",
              f"Rh_gnd gm hg1 {rcond / self.n_gnd:.6g}", f"Lh_gnd hg1 hg2 {lh:.6g}", "Vignd hg2 0 0"]
        # ---- main passives
        d += self._remap(M.passives(nets=self.MAIN_NETS, scale=self._scale(M, self.MAIN_NETS)), "m_", "gm", "m")

        # ---- LED rail: TPS22917 U2 + ring
        v_on = f"PULSE(0 3.3 {loads.led_on_at} 1u 1u 1 2)" if loads.led_on_at is not None else \
            f"DC {3.3 if loads.led_on else 0}"
        d += [f"Ven_led {self.mpin('U2', 'ON')} gm {v_on}", f"Rvled_leak {self.mpin('U2', 'VOUT')} gm 10meg",
              f"Rqod_leak {self.mpin('U2', 'QOD')} gm 10meg"]
        d += [f"Xu2 {self.mpin('U2', 'VIN')} {self.mpin('U2', 'ON')} {self.mpin('U2', 'CT')} "
              f"{self.mpin('U2', 'VOUT')} {self.mpin('U2', 'QOD')} {self.mpin('U2', 'GND')} TPS22917_PI "
              f"RON={lsw_ron(self.vnom, c):.6g}"]
        if loads.led_idc or loads.led_ipk:
            d += [f"Xring {self.m('VLED')} gm WS2812C_RING N={self.n_led} IDC={loads.led_idc:.6g} "
                  f"IPK={loads.led_ipk:.6g} DUTY={min(loads.led_duty, 1.0):.6g} FPWM={WS_FPWM:.6g} "
                  f"IIC={WS_IIC:.6g} TD=20u"]
        # ---- OLED boost input: TPS22917 U21 + TPS61040 U20
        try:
            qod21 = self.mpin("U21", "QOD")
        except KeyError:
            qod21 = "u21_qod_nc"
        if qod21.startswith("m_n_unconnected"):
            qod21 = "u21_qod_nc"
        d += ["Rqod21_nc u21_qod_nc gm 1g", f"Roledvin_leak {self.mpin('U21', 'VOUT')} gm 10meg",
              f"Ven_oled {self.mpin('U21', 'ON')} gm DC {3.3 if loads.oled_icc > 0 else 0}",
              f"Xu21 {self.mpin('U21', 'VIN')} {self.mpin('U21', 'ON')} {self.mpin('U21', 'CT')} "
              f"{self.mpin('U21', 'VOUT')} {qod21} {self.mpin('U21', 'GND')} TPS22917_PI "
              f"RON={lsw_ron(self.vnom, c):.6g}"]
        if loads.oled_icc > 0:
            bp = self.boost(max(self.vnom - 0.1, 2.5), loads.oled_icc)
            self.boost_params = bp
            d += [f"Xu20 {self.mpin('U20', 'VIN')} {self.mpin('U20', 'GND')} TPS61040_IN PIN={bp['PIN']:.6g} "
                  f"RIP={1 if loads.oled_ripple else 0} KSHAPE={bp['KSHAPE']:.6g} TON={bp['TON']:.6g} "
                  f"TOFF={bp['TOFF']:.6g} TPER={bp['TPER']:.6g}"]
        # ---- detent drivers
        if loads.motor != "off":
            for ref in ("U40", "U41"):
                if loads.motor == "full":
                    p = f"RCOIL={MOTOR_RCOIL} FULLON=1 ICOIL=0"
                else:
                    duty = min(1.0, loads.motor_icoil * MOTOR_RCOIL / max(self.vnom, 2.5))
                    p = f"RCOIL={MOTOR_RCOIL} FULLON=0 ICOIL={loads.motor_icoil:.6g} DUTY={duty:.6g} " \
                        f"FPWM={MOTOR_FPWM:.6g} TD=7u"
                d += [f"X{ref.lower()} {self.mpin(ref, 'VM')} {self.mpin(ref, 'GND')} DRV8837_VM {p}"]
        # ---- RT9080 + 3V3 load
        d += [f"Xu1 {self.mpin('U1', 'VIN')} {self.mpin('U1', 'EN')} {self.mpin('U1', 'VOUT')} "
              f"{self.mpin('U1', 'GND')} RT9080_PI VSET={LDO_VSET * (1 - LDO_ACC) if not typ else LDO_VSET:.6g} "
              f"RDROP={LDO_RDROP[0 if typ else 1]:.6g} GM={LDO_GM:.6g}"]
        tx = loads.i3v3_tx if loads.tx else 0.0
        base = loads.i3v3_base + (0.0 if loads.tx else loads.i3v3_tx)
        d += [f"Xnrf {self.mpin('U10', 'VDD')} gm NRF52840_3V3LOAD IBASE={base:.6g} ITX={tx:.6g} TSTART=150u"]

        # ---- logic lines across the link (static lows, worst-case drivers)
        if logic:
            rsig = self.conductor_r()
            for net in self.LOGIC:
                d += [f"Rlink_{net.lower()} {self.b(net)} {self.m(net)} {rsig:.6g}"]
            d += [f"Xol_scl {self.mpin('U10', 'P0.08')} gm NRF52840_OL ROL={NRF_ROL:.6g}",
                  f"Xod_sda {self.bpin('U1', 'SDA')} 0 BQ25180_OD_LOW RON_OD={BQ_OD_R:.6g}",
                  f"Xod_int {self.bpin('U1', '~{INT}')} 0 BQ25180_OD_LOW RON_OD={BQ_OD_R:.6g}",
                  f"Rq1b_on {self.bpin('Q1', '3')} {self.bpin('Q1', '4')} {QFET_RDS}"]

        # ---- initial guess for the operating point (the behavioural min/max sources need one)
        v = self.vnom
        led_up = loads.led_on and loads.led_on_at is None
        ns = {self.m("VSYS"): v, self.b("VSYS"): v, "hv1": v, "bq_sys": v, self.m("+3V3"): min(v, 3.3),
              self.m("VLED"): v if led_up else 0.0, self.mpin("U2", "CT"): 0.0 if led_up else v,
              self.m("OLED_VIN"): v if loads.oled_icc > 0 else 0.0,
              self.mpin("U21", "CT"): 0.0 if loads.oled_icc > 0 else v}
        if vbat is not None:
            ns[self.b("VBAT")] = vbat
        d += [".nodeset " + " ".join(f"v({k})={x:.4g}" for k, x in ns.items())]

        # ---- probes (differential voltages as B-source nodes)
        d += [f"Bp_vsys p_vsys 0 V = {{ v({self.m('VSYS')}) - v(gm) }}",
              f"Bp_vled p_vled 0 V = {{ v({self.m('VLED')}) - v(gm) }}",
              f"Bp_3v3 p_3v3 0 V = {{ v({self.m('+3V3')}) - v(gm) }}",
              f"Bp_bat p_bat 0 V = {{ v({self.b('VBAT')}) }}",
              "Bp_gnd p_gnd 0 V = { v(gm) }"]
        if logic:
            vdd = f"(v({self.m('+3V3')}) - v(gm))"
            d += [f"Bp_scl p_scl 0 V = {{ v({self.b('I2C_SCL')}) }}"]
            for net, key in (("I2C_SDA", "sda"), ("CHG_INT_N", "int"), ("BTN_N", "btn")):
                d += [f"Bp_{key} p_{key} 0 V = {{ v({self.m(net)}) - v(gm) }}",
                      f"Bm_{key} m_{key}_marg 0 V = {{ v({self.m(net)}) - v(gm) - {NRF_VIL_FRAC}*{vdd} }}"]
        return d


MEAS_BASE = [("vsys_min", "MIN v(p_vsys)"), ("vsys_max", "MAX v(p_vsys)"), ("vled_min", "MIN v(p_vled)"),
             ("vled_max", "MAX v(p_vled)"), ("v3v3_min", "MIN v(p_3v3)"), ("vbat_min", "MIN v(p_bat)"),
             ("gnd_max", "MAX v(p_gnd)"), ("gnd_min", "MIN v(p_gnd)"), ("ibat_max", "MAX i(vibat)"),
             ("ibat_avg", "AVG i(vibat)"), ("isys_max", "MAX i(visys)"), ("isys_avg", "AVG i(visys)"),
             ("ilink_max", "MAX i(vilink)"), ("ilink_avg", "AVG i(vilink)"), ("ignd_avg", "AVG i(vignd)")]
MEAS_LOGIC = [("scl_max", "MAX v(p_scl)"), ("scl_min", "MIN v(p_scl)"),
              ("sda_marg", "MAX v(m_sda_marg)"), ("int_marg", "MAX v(m_int_marg)"), ("btn_marg", "MAX v(m_btn_marg)"),
              ("sda_min", "MIN v(p_sda)"), ("int_min", "MIN v(p_int)"), ("btn_min", "MIN v(p_btn)")]


def _errors(res):
    """ngspice errors, ignoring gmin-stepping warnings when its source-stepping fallback converged."""
    errs = res["_errors"]
    if "Source stepping completed" in res["_log"] or "gmin stepping completed" in res["_log"].lower():
        errs = [e for e in errs if "gmin stepping failed" not in e and "singular matrix" not in e]
    return errs


def run_tran(d: Deck, stop=1.5e-3, start=0.0, tmax=0.2e-6, logic=False, vbus=False, waves=()):
    d.tran(f"{tmax:.3g}", f"{stop:.6g}", 0, f"{tmax:.3g}")
    meas = MEAS_BASE + (MEAS_LOGIC if logic else []) + ([("iin_max", "MAX i(viin)"), ("iin_avg", "AVG i(viin)")]
                                                         if vbus else [])
    for name, expr in meas:
        if "vibat" in expr and "Vibat" not in d.text():
            continue
        d.meas(f"tran {name} {expr} from={start:.6g} to={stop:.6g}")
    if waves:
        d.wave(*waves)
    res = d.run()
    assert not _errors(res), _errors(res)[:5]
    assert not res.get("_missing"), (res.get("_missing"), res["_log"][-3000:])
    return res


def run_op(d: Deck, logic=False):
    exprs = {"vsys": "v(p_vsys)", "vled": "v(p_vled)", "v3v3": "v(p_3v3)", "vbat": "v(p_bat)", "gnd": "v(p_gnd)",
             "ibat": "i(vibat)", "isys": "i(visys)", "ilink": "i(vilink)", "ignd": "i(vignd)"}
    if "Vibat" not in d.text():
        exprs.pop("ibat")
    if logic:
        exprs.update({"scl": "v(p_scl)", "sda_marg": "v(m_sda_marg)", "int_marg": "v(m_int_marg)",
                      "btn_marg": "v(m_btn_marg)"})
    d.op()
    d.print_op(*exprs.values())
    res = d.run()
    assert not _errors(res), _errors(res)[:5]
    out = {}
    for i, k in enumerate(exprs):
        assert f"op_{i}" in res, (k, res["_log"][-3000:])
        out[k] = res[f"op_{i}"]
    return out
