"""Power integrity of VSYS, end to end (circuit key: power_integrity).

Path simulated (every passive from the two netlists, every connector contact count from the netlists):

    1S LiPo (OCV + R_int) -> battery connector J2 (series and contacts per rail from the base netlist)
      -> BQ25180 BAT/SYS power path (or USB VBUS -> IN: SYS regulation, ILIM, DPPM, supplement)
      -> base VSYS caps -> 12-way link harness (VSYS / GND conductors counted from J1 / J3 in the netlists;
         each = 2 JST SH contacts + 28 AWG wire; R and loop inductance)
      -> main VSYS caps -> loads:
           TPS22917 U2 -> VLED -> 48x WS2812C-2020-V6 (full white, and PWM edges of all LEDs together)
           TPS22917 U21 -> OLED_VIN -> TPS61040 U20 input (constant power + DCM ripple)
           DRV8837 U40/U41 VM (both coils: full-on, or 25 kHz PWM with aligned edges)
           RT9080 U1 -> +3V3 (nRF52840 incl. +8 dBm TX bursts, W25Q128JV erase, sensors)

Each board keeps its own ground: base GND is SPICE node 0, main GND is node `gm` (ngspice treats a node
called GND as node 0, so the models use VSS ports), joined only through the harness GND conductors. The
ground offset between the boards (I*R + L*di/dt) is simulated and checked against the logic thresholds of
the lines that cross the link (I2C_SCL/SDA, CHG_INT_N, BTN_N).

Limits (every one from a datasheet, quoted in each check's source string):
    VLED >= 3.3 V and <= 5.3 V           WS2812C-2020-V6 DS p.2 (VDD 3.3-5.3 V)
    +3V3 >= 2.7 V                         W25Q128JV DS Rev F 9.2 (binding; nRF52840 PS 8 and TMAG5273 5.3: 1.7 V)
    I(BAT) <= 1.5 A                       BQ25180 SLUSE99C 7.5 IBAT_OCP (CHARGECTRL1 = 0x92 -> 1.5 A)
    I(SYS) <= 1.5 A DC                    BQ25180 SLUSE99C 7.1 SYS discharge current
    V(BAT) < 3.0 V for <= 60 us           BQ25180 SLUSE99C 7.5 VBUVLO (BUVLO 010) and 7.6 tBUVLO
    I(IN) <= 1.1 A                        BQ25180 SLUSE99C 7.1 / 7.4 input current
    link / battery contact <= 1.0 A avg   JST SH datasheet, 1.0 A per contact with AWG #28
    BQ25180 SCL low <= 0.4 V              BQ25180 SLUSE99C 7.5 VIL
    nRF input low <= 0.3 x VDD            nRF52840 PS v1.1 6.9.3.1 VIL
    pins >= -0.3 V                        BQ25180 7.1 (all other pins), nRF52840 PS v1.1 9
    VSYS <= 5.5 V                         TPS22917 SLVSDW8B 7.3 VIN, RT9080 DS9080-09 12 VIN

The "capped" scenarios apply the firmware power policy of docs/firmware.md (5.8, 6.3, 7.4, 12.4): LED average
150 mA sustained / 300 mA bursts at VBAT >= 3.65 V, 100 mA below 3.60 V and while the actuator moves, only a
2 mA red cue below 3.53 V, SHIP below 3.48 V, actuator moves only at VSYS >= 3.40 V (park >= 3.30 V).

Corners: nominal (pack 100 mOhm, contacts as new, 25 C typical RON), worst (200 mOhm pack, contacts after
environmental tests, 60 C datasheet-max RON / dropout, VSYS-GND wires 5 mm apart, every capacitor at -tol),
cold (-10 C, same but copper colder). VBAT 3.0 / 3.7 / 4.2 V plus the firmware policy thresholds; VBUS
4.5 / 5.0 / 5.5 V with SYS_REG -2 % / nominal / +2 %.

What the simulation shows (rev A netlists; xfail tests carry the evidence):
  * Uncapped (no firmware limit) the system draws ~1.33 A: VLED 3.05 V at VBAT 3.7 V worst corner, and at the
    end of discharge (3.0 V) +3V3 falls below the flash minimum -> the firmware limiter is a protection function.
  * With the firmware AVERAGE caps every steady-state point passes (VLED >= 3.33 V worst corner).
  * But the cap limits the average only: with all LEDs lit and their PWM aligned the ring pulls 0.72 A for
    70-210 us, VLED falls to 3.08-3.25 V at VBAT <= 3.70 V; a peak (lit-channel) budget is derived per VBAT
    (test_led_peak_budget_vs_vbat) and verified (test_proposed_peak_cap_fix).
  * USB with no usable pack: the firmware USB budgets exceed ILIM min (SYS collapses).
  * Ground offset between the boards <= ~47 mV; the I2C low level seen by the BQ25180 is 0.30 V (VIL 0.4 V).
  * Decoupling: BQ25180 SYS 20 uF local, 93.6 uF on both boards at +tol (Table 9-2 max 100 uF: little room to
    add VSYS bulk); a hard VLED short is stopped only by BATOCP / the pack PCM (U2 has no current limit).

Independent verification (verifier pass, see the 'verifier:' comments): TPS22917 hot-corner RON set to the DS
band maximum; capacitor tolerances from the MPN letter (M = 20 %); per-board scale dicts (refs overlap between
the boards); explicit tolerance factors replace the corner -tol instead of multiplying onto it; main-ground
nodeset (the DC op no longer depends on source stepping); the 3.0 V uncapped corner judged on +3V3 instead of
two physically impossible checks; VLED checked at the low-battery cue point; base caps in the Monte Carlo;
datasheet decoupling check; fault tests for base SYS caps 10x low, main VSYS bulk left off, a single battery
contact and a shorted LED.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

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
SRC_BUVLO = "BQ25180 DS SLUSE99C 7.5 VBUVLO 3.0 V (BUVLO = 010), 7.6 tBUVLO 60 us deglitch"
SRC_IIN = "BQ25180 DS SLUSE99C 7.1 / 7.4 input current (IN to SYS) 1.1 A"
SRC_SH = "JST SH DS (eSH): current rating 1.0 A per contact, AWG #28"
SRC_BQ_VIL = "BQ25180 DS SLUSE99C 7.5 I2C VIL 0.4 V (SCL/SDA)"
SRC_NRF_VIL = "nRF52840 PS v1.1 6.9.3.1 VIL = 0.3 x VDD"
SRC_NEG = "BQ25180 DS SLUSE99C 7.1 / nRF52840 PS v1.1 9: pins >= -0.3 V"
SRC_LSW = "TPS22917 DS SLVSDW8B 7.1 IPLS 2.5 A (pulse < 300 us, 2 % duty)"
SRC_VIN55 = "TPS22917 DS SLVSDW8B 7.3 VIN <= 5.5 V; RT9080 DS9080-09 12 VIN <= 5.5 V"
SRC_CSYS_MIN = "BQ25180 DS SLUSE99C 6 Pin Functions SYS: connect at least 10 uF ceramic; 9.2.2.3 Table 9-2 CSYS nom 10 uF"
SRC_CSYS_MAX = "BQ25180 DS SLUSE99C 9.2.2.3 Table 9-2 CSYS max 100 uF"
SRC_CBAT = "BQ25180 DS SLUSE99C 9.2.2.3 Table 9-2 CBAT min 1 uF"
SRC_CIN = "BQ25180 DS SLUSE99C 9.2.2.3 Table 9-2 CIN 1-10 uF"
SRC_MAIN_BYPASS = ("RT9080 DS9080-09 8 Functional Pin Description VIN 1 uF; TPS22917 SLVSDW8B 11 Power Supply "
                   "Recommendations CIN 1 uF; DRV8837 SLVSBA4F 5 Pin Functions VM 0.1 uF")

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
VIN_MAX = 5.5

# ------------------------------------------------------------------- wiring and battery (not in netlists)
AWG28_OHM_PER_M = 0.2129   # 28 AWG copper, 0.0810 mm^2: 212.9 mOhm/m at 20 C (ASTM B258 AWG table)
AWG28_DIA = 0.321e-3       # m, 28 AWG bare conductor diameter (ASTM B258)
CU_TC = 0.00393            # 1/C, annealed copper (IEC 60028)
HARNESS_LEN = 0.100        # m, task brief "~100 mm" (docs/architecture.md 4.2 estimates 50-80 mm)
MU0 = 4e-7 * math.pi
# max resistance per mated contact (initial, after environmental tests): JST SH (eSH) 20 / 40 mOhm,
# JST PH (ePH) 10 / 20 mOhm
CONTACT_R = {"SH": (0.020, 0.040), "PH": (0.010, 0.020)}
CONTACT_A = {"SH": 1.0, "PH": 2.0}   # A per contact (JST SH: 1.0 A with AWG #28; JST PH: 2.0 A)
BATT_RINT = (0.100, 0.200)           # Ohm, 1S LiPo pack (cell + PCM) range of the task brief

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
WSB_ICH = 12e-3                                     # WS2812B-2020-V6, pin-compatible alternate (SPEC 5.4)
WS_FPWM = 2e3                                       # WS2812C-2020-V6 DS p.1: 2 kHz PWM
WS_IIC = 0.2e-3                                     # per lit LED, docs/firmware.md 6.3 (TVP; not in the DS)
NRF_ROL = 0.4 / 1e-3                                # nRF52840 PS 6.9.3.1 IOL,SD >= 1 mA at 0.4 V
QFET_RDS = 3.5                                      # BSS138DW DS30203 RDS(on) max (at VGS 10 V; uA here)
# +3V3 load (docs/architecture.md 7: about 50 mA peak): TX +8 dBm 14.8 mA (nRF52840 PS 6.20.15.2),
# CPU 3.3 mA (PS 5.2.1.3), W25Q128JV erase 25 mA max (DS Rev F 9.4), TMAG5273 2.3 mA, IMU/VCI/misc 0.5 mA
I3V3_TX = 14.8e-3
I3V3_BASE = 3.3e-3 + 25e-3 + 2.3e-3 + 0.5e-3
# OLED: NHD-1.5-128128G ICC at 100 % on 42 mA max (panel DS, verified in the display research);
# C7 master current 08h = 9/16 of full scale (docs/firmware.md 7.4 low-battery limit)
OLED_ICC_MAX = 42e-3
OLED_ICC_DIM = OLED_ICC_MAX * 9 / 16
OLED_ETA = 0.75                                     # TPS61040 efficiency (conservative read of SLVS413L Fig. 5-x)
BOOST_ILIM = (0.350, 0.400, 0.450)                  # SLVS413L 5.5 ILIM
BOOST_VFB = 1.233                                   # SLVS413L 5.5 VFB typ
BOOST_VF = 0.45                                     # B5819W drop at ~0.4 A (assumed; only shapes the ripple)
# detent stepper (docs/firmware.md 5.3): coil + rDS(on) 20.3 Ohm, run current 160 mA, PWM 25 kHz;
# microstep at 45 deg drives both coils at 160 mA x cos 45
MOTOR_RCOIL, MOTOR_IRUN, MOTOR_FPWM = 20.3, 0.160, 25e3
MOTOR_I45 = MOTOR_IRUN * math.cos(math.pi / 4)

# firmware policy (docs/firmware.md 5.8, 6.3, 7.4, 12.4)
FW_LED_BURST, FW_LED_SUST, FW_LED_LOW, FW_LED_MOVING, FW_LED_CUE = 0.300, 0.150, 0.100, 0.100, 0.002
FW_V_FULL, FW_V_DERATE, FW_V_OFF, FW_V_SHIP = 3.65, 3.60, 3.53, 3.48


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
# worst: weakest pack, aged contacts, hot FETs at datasheet max, wires spread across the 6 mm bore, caps low
WORST = Corner("worst", temp=60.0, rint=BATT_RINT[1], aged=True, fet="max", spacing=5.0e-3, caps="min")
COLD = Corner("cold", temp=-10.0, rint=BATT_RINT[1], aged=True, fet="max", spacing=5.0e-3, caps="min")
CORNERS = {c.name: c for c in (NOMINAL, WORST, COLD)}


def lsw_ron(vin: float, c: Corner) -> float:
    """TPS22917 RON at VIN (interpolated in VIN), typ at 25 C or DS max at the corner temperature.

    The DS gives max RON only at 25 C and as one band maximum for -40..+85 C, so above 25 C the band maximum is
    the only guaranteed value (verifier: the earlier linear interpolation to 60 C, 127.5 mOhm at 3.6 V, was not
    datasheet-backed; the band max is 140 mOhm). At or below 25 C RON falls with temperature, so max25 is a
    conservative bound."""
    ks = sorted(LSW_RON)
    vin = min(max(vin, ks[0]), ks[-1])
    for a, b in zip(ks, ks[1:]):
        if a <= vin <= b:
            f = (vin - a) / (b - a)
            typ25, max25, max85 = (LSW_RON[a][i] + f * (LSW_RON[b][i] - LSW_RON[a][i]) for i in range(3))
            break
    if c.fet == "typ":
        return typ25
    return max85 if c.temp > 25.0 else max25


def cap_tol(d: Design, ref: str) -> float:
    """Capacitor tolerance: from the value string when it carries one ('10u 5%'), else from the tolerance letter
    of the MPN (Samsung CL.., Yageo CC.., Fenghua 0402..: K = 10 %, M = 20 %, J = 5 %), else the harness default.
    (Verifier: Design.tol() falls back to 10 % for every capacitor, but C1/C8/C9 on main and C2 on base are
    M-grade, +/-20 %.)"""
    import re
    if "%" in d.comps[ref]["value"]:
        return d.tol(ref)
    mpn = d.mpn(ref).upper()
    pats = (r"^CL\d\d[A-Z]\d{3}([FGJKMZ])", r"^CC\d{4}([FGJKMZ])", r"^\d{4}[A-Z]{1,2}\d{3}([FGJKMZ])\d{3}",
            r"^TAJ[A-Z]\d{3}([JKM])")
    for p in pats:
        mm = re.match(p, mpn)
        if mm:
            return {"F": 0.01, "G": 0.02, "J": 0.05, "K": 0.10, "M": 0.20, "Z": 0.20}[mm.group(1)]
    return d.tol(ref)


def is_cap(ref: str) -> bool:
    return ref[0] == "C" and ref[1:2].isdigit()


def part_tol(d: Design, ref: str) -> float:
    return cap_tol(d, ref) if is_cap(ref) else d.tol(ref)


def tol_extremes(d: Design, refs):
    """All 2^n tolerance corners {ref: 1 +/- tol} (like Design.extremes, with MPN capacitor tolerances)."""
    import itertools
    refs = list(refs)
    for signs in itertools.product((-1, 1), repeat=len(refs)):
        yield {r: 1.0 + sgn * part_tol(d, r) for r, sgn in zip(refs, signs)}


def tol_draws(d: Design, refs, n: int, seed: int):
    """n uniform tolerance draws {ref: factor} (like Design.monte_carlo, with MPN capacitor tolerances)."""
    import random
    rng = random.Random(seed)
    refs = list(refs)
    for _ in range(n):
        yield {r: 1.0 + rng.uniform(-part_tol(d, r), part_tol(d, r)) for r in refs}


def pi_caps(d: Design, nets) -> list:
    """Fitted capacitors with every pin on the PI-path nets of this board."""
    return sorted(r for r in d.comps if is_cap(r) and d.fitted(r) and d.pins.get(r)
                  and all(n in nets for n in d.pins[r].values()))


# =========================================================================================== loads
@dataclass
class Loads:
    led_idc: float = 0.0        # A per channel, steady
    led_ipk: float = 0.0        # A per channel, PWM amplitude (all channels of all LEDs switching together)
    led_duty: float = 0.5
    led_on_at: float | None = None   # LED_PWR_EN rising edge (inrush runs); None: rail already on
    oled_icc: float = 0.0       # panel VCC current at the boost output, A (0: U21 off)
    oled_ripple: bool = True
    oled_ten: float | None = None   # boost load switches on at this time (None: on from t = 0)
    motor: str = "off"          # off | full (both coils static, d = 1) | pwm | avg
    motor_icoil: float = 0.0    # A per coil (pwm / avg)
    i3v3_base: float = I3V3_BASE
    i3v3_tx: float = I3V3_TX
    tx: bool = True             # TX bursts (else the TX current is steady)


def led_sync(cap: float, n: int, ich: float = WS_ICH) -> dict:
    """Firmware average cap reached by dimming every channel of every LED: PWM peaks of ich per channel
    with duty = cap / (3 n ich), all LEDs switching together (the brief's worst case)."""
    return dict(led_ipk=ich, led_duty=min(1.0, cap / (3 * n * ich)))


def led_avg(cap: float, n: int, ich: float = WS_ICH) -> dict:
    return dict(led_idc=min(ich, cap / (3 * n)))


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
    """One ngspice deck of the whole VSYS path, built from the two netlists."""

    MAIN_NETS = {"VSYS", "GND", "VLED", "+3V3", "LSW_CT", "LSW_QOD", "OLED_LSW_CT", "OLED_VIN", "VSYS_SENSE",
                 "LED_PWR_EN", "OLED_VCC_EN", "I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N"}
    BASE_NETS = {"VSYS", "GND", "VBAT", "VBUS"}
    LOGIC = ("I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N")

    def __init__(self, main: Design, base: Design, corner: Corner = NOMINAL):
        self.main, self.base, self.c = main, base, corner
        self.n_vsys = len(link_pins(main, "VSYS"))
        self.n_gnd = len(link_pins(main, "GND"))
        assert self.n_vsys and self.n_gnd
        assert link_pins(main, "VSYS") == link_pins(base, "VSYS") and \
            link_pins(main, "GND") == link_pins(base, "GND"), "link pinout differs between the boards"
        self.bat_ref, self.bat_series, self.n_bpos, self.n_bneg = batt_connector(base)
        self.n_led = len([r for r in main.on_net("VLED", "D") if main.fitted(r)
                          and main.pins[r].get("4") == "VLED"])
        self.vnom = 3.7

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

    def _scale(self, d: Design, extra: dict | None):
        """Per-board scale. `extra` belongs to THIS board only (verifier: the references overlap between the
        boards, C1-C4 and R1-R4 exist on both, so one shared dict scaled base parts with main-board draws)."""
        sc = {}
        if self.c.caps == "min":
            sc = {r: 1.0 - cap_tol(d, r) for r in d.comps if is_cap(r)}
        # verifier: an explicit factor is relative to the NETLIST value and replaces the corner's -tol (it used to
        # multiply onto it, so the 'extremes' of C7/C8/C9 at the worst corner spanned 0.81..0.99 instead of
        # 1 -/+ tol and never reached the high end of C8/C9)
        for r, f in (extra or {}).items():
            if r in d.comps:
                sc[r] = f
        return sc or None

    # ------------------------------------------------------------------ physical values
    def contact_r(self, series="SH"):
        return CONTACT_R[series][1 if self.c.aged else 0]

    def conductor_r(self):
        wire = AWG28_OHM_PER_M * self.c.length * (1 + CU_TC * (self.c.temp - 20.0))
        return 2 * self.contact_r("SH") + wire

    def loop_l(self):
        """Loop inductance of the VSYS / GND pair: (mu0/pi) acosh(s/d) per metre (two parallel round wires)."""
        s = max(self.c.spacing, 1.01 * AWG28_DIA)
        return MU0 / math.pi * math.acosh(s / AWG28_DIA) * self.c.length

    def boost(self, vin: float, icc: float):
        """TPS61040 input-model params at VIN for a panel current icc (L20 and R26/R27 from the netlist)."""
        L = self.main.value("L20")
        vout = BOOST_VFB * (1 + self.main.value("R26") / self.main.value("R27"))
        ipk = BOOST_ILIM[2] + vin / L * 100e-9
        pin = min(vout * icc / OLED_ETA, vin * ipk / 2)
        ton, toff = L * ipk / vin, L * ipk / (vout + BOOST_VF - vin)
        tper = max(ipk * (ton + toff) / (2 * pin / vin), ton + toff + 5e-9)
        return dict(PIN=pin, KSHAPE=2 * tper / (ton + toff), TON=ton, TOFF=toff, TPER=tper, vout=vout, ipk=ipk)

    # ------------------------------------------------------------------ deck
    def deck(self, title: str, loads: Loads, vbat: float | None = 3.7, vbus: float | None = None,
             ilim=BQ_ILIM500[0], vsysreg=BQ_VSYSREG, logic: bool = False, scale: dict | None = None,
             led_ich_scale: float = 1.0, scale_base: dict | None = None, bq_extra: dict | None = None,
             vguess: float | None = None):
        """scale: {ref: factor} for MAIN-board parts, scale_base: the same for BASE-board parts.
        bq_extra: BQ25180_PP parameter overrides (e.g. a deeply discharged pack: no supplement, precharge).
        vguess: initial guess for VSYS in the .nodeset only (e.g. VBAT + VDPPM when USB runs in DPPM)."""
        c, M, B = self.c, self.main, self.base
        typ = c.fet == "typ"
        d = Deck(title)
        # Gear integration: the trapezoidal rule rings numerically on the floating main-ground node
        d.options.append("option method=gear")
        for k in LIB.values():
            d.include(k)
        # operating-point guess: just inside the SYS regulation loop on USB (the ILIM branch has no slope)
        self.vnom = v = min(vsysreg - 0.4 * ilim / 50.0, vbus - 0.2) if vbus else (vbat or 3.7)   # GREG = 50 A/V

        # ---- battery and its connector (series and contacts per rail from the netlist)
        rc_b = self.contact_r(self.bat_series)
        if vbat is not None:
            d += [f"Vocv bat_p bat_n DC {vbat}", f"Rint bat_p bat_i {c.rint}", "Vibat bat_i bat_c 0",
                  f"Rbcon_p bat_c {self.b('VBAT')} {rc_b / self.n_bpos:.6g}",
                  f"Rbcon_n bat_n 0 {rc_b / self.n_bneg:.6g}"]
        else:   # no pack (or a pack below BUVLO): BAT only holds C3 near VBATREG, nothing can supplement SYS
            d += ["Vnopack nopack 0 DC 4.2", f"Rnopack nopack {self.b('VBAT')} 10k"]
        d += [f"Rvbat_leak {self.b('VBAT')} 0 10meg"]
        # ---- USB VBUS (stiff source at the corner value)
        if vbus is not None:
            d += [f"Vbus vbus_src 0 DC {vbus}", f"Viin vbus_src {self.b('VBUS')} 0"]
        d += [f"Rvbus_leak {self.b('VBUS')} 0 1meg"]
        # ---- BQ25180 power path
        # no pack: BAT holds only C3, the charger terminates once C3 sits at VBATREG -> no charge current
        bq = dict(VSYSREG=vsysreg, ILIM=ilim, RON_IN=BQ_RON_IN[0 if typ else 1],
                  RON_BAT=BQ_RON_BAT[0 if typ else 1] if vbat is not None else 1e6,
                  ICHG=BQ_ICHG if vbat is not None else 0.0)
        bq.update(bq_extra or {})
        ps = " ".join(f"{k}={x:.6g}" for k, x in bq.items())
        d += [f"Xbq {self.bpin('U1', 'IN')} bq_sys {self.bpin('U1', 'BAT')} {self.bpin('U1', 'GND')} "
              f"BQ25180_PP {ps}", f"Visys bq_sys {self.bpin('U1', 'SYS')} 0"]
        # ---- base passives
        d += self._remap(B.passives(nets=self.BASE_NETS, scale=self._scale(B, scale_base)), "b_", "0", "b")
        # ---- harness: VSYS and GND bundles (conductor count from the netlist), loop L split evenly
        rcond, lh = self.conductor_r(), self.loop_l() / 2
        d += [f"Vilink {self.b('VSYS')} hv1 0", f"Rh_vsys hv1 hv2 {rcond / self.n_vsys:.6g}",
              f"Lh_vsys hv2 {self.m('VSYS')} {lh:.6g}",
              f"Rh_gnd gm hg1 {rcond / self.n_gnd:.6g}", f"Lh_gnd hg1 hg2 {lh:.6g}", "Vignd hg2 0 0"]
        # ---- main passives
        d += self._remap(M.passives(nets=self.MAIN_NETS, scale=self._scale(M, scale)), "m_", "gm", "m")

        # ---- LED rail: TPS22917 U2 + ring
        v_on = f"PULSE(0 3.3 {loads.led_on_at} 1u 1u 1 2)" if loads.led_on_at is not None else "DC 3.3"
        d += [f"Ven_led {self.mpin('U2', 'ON')} gm {v_on}", f"Vilsw {self.mpin('U2', 'VIN')} lsw_in 0",
              f"Rvled_leak {self.mpin('U2', 'VOUT')} gm 10meg", f"Rqod_leak {self.mpin('U2', 'QOD')} gm 10meg",
              f"Xu2 lsw_in {self.mpin('U2', 'ON')} {self.mpin('U2', 'CT')} {self.mpin('U2', 'VOUT')} "
              f"{self.mpin('U2', 'QOD')} {self.mpin('U2', 'GND')} TPS22917_PI RON={lsw_ron(v, c):.6g}"]
        if loads.led_idc or loads.led_ipk:
            d += [f"Xring {self.m('VLED')} gm WS2812C_RING N={self.n_led} IDC={loads.led_idc * led_ich_scale:.6g} "
                  f"IPK={loads.led_ipk * led_ich_scale:.6g} DUTY={min(loads.led_duty, 1.0):.6g} "
                  f"FPWM={WS_FPWM:.6g} IIC={WS_IIC:.6g} TD=20u"]
        # ---- OLED boost input: TPS22917 U21 + TPS61040 U20
        qod21 = self.mpin("U21", "QOD")
        if "unconnected" in qod21:
            qod21 = "u21_qod_nc"
        d += ["Rqod21_nc u21_qod_nc gm 1g", f"Roledvin_leak {self.mpin('U21', 'VOUT')} gm 10meg",
              f"Ven_oled {self.mpin('U21', 'ON')} gm DC {3.3 if loads.oled_icc > 0 else 0}",
              f"Xu21 {self.mpin('U21', 'VIN')} {self.mpin('U21', 'ON')} {self.mpin('U21', 'CT')} "
              f"{self.mpin('U21', 'VOUT')} {qod21} {self.mpin('U21', 'GND')} TPS22917_PI RON={lsw_ron(v, c):.6g}"]
        if loads.oled_icc > 0:
            bp = self.boost(max(v - 0.1, 2.5), loads.oled_icc)
            d += [f"Xu20 {self.mpin('U20', 'VIN')} {self.mpin('U20', 'GND')} TPS61040_IN PIN={bp['PIN']:.6g} "
                  f"RIP={1 if loads.oled_ripple else 0} KSHAPE={bp['KSHAPE']:.6g} TON={bp['TON']:.6g} "
                  f"TOFF={bp['TOFF']:.6g} TPER={bp['TPER']:.6g}"
                  + (f" V0=0 TEN={loads.oled_ten:.6g}" if loads.oled_ten is not None else "")]
        # ---- detent drivers (both share one PWM instance: aligned edges)
        if loads.motor != "off":
            for ref in ("U40", "U41"):
                duty = min(1.0, loads.motor_icoil * MOTOR_RCOIL / max(v, 2.5))
                if loads.motor == "full":
                    p = f"RCOIL={MOTOR_RCOIL} FULLON=1"
                elif loads.motor == "avg":
                    p = f"RCOIL={MOTOR_RCOIL} IDC={loads.motor_icoil * duty:.6g}"
                else:
                    p = f"RCOIL={MOTOR_RCOIL} ICOIL={loads.motor_icoil:.6g} DUTY={duty:.6g} " \
                        f"FPWM={MOTOR_FPWM:.6g} TD=7u"
                d += [f"X{ref.lower()} {self.mpin(ref, 'VM')} {self.mpin(ref, 'GND')} DRV8837_VM {p}"]
        # ---- RT9080 + 3V3 load
        vset = LDO_VSET if typ else LDO_VSET * (1 - LDO_ACC)
        d += [f"Xu1 {self.mpin('U1', 'VIN')} {self.mpin('U1', 'EN')} {self.mpin('U1', 'VOUT')} "
              f"{self.mpin('U1', 'GND')} RT9080_PI VSET={vset:.6g} RDROP={LDO_RDROP[0 if typ else 1]:.6g} "
              f"GM={LDO_GM:.6g}"]
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
                  f"Xod_int {self.bpin('U1', '~{INT}')} 0 BQ25180_OD_LOW RON_OD={BQ_OD_R:.6g}"]
            q = [p for p, n in B.pins["Q1"].items() if n == "BTN_N"][0]
            d += [f"Rq1b_on {self.bpin('Q1', q)} 0 {QFET_RDS}"]

        # ---- initial guess for the operating point (the behavioural min/max sources need one)
        led_up = loads.led_on_at is None
        v = vguess if vguess is not None else v
        ns = {self.m("VSYS"): v, self.b("VSYS"): v, "hv1": v, "bq_sys": v, self.m("+3V3"): min(v, vset) - 0.01,
              self.m("VLED"): v if led_up else 0.0, self.mpin("U2", "CT"): 0.0 if led_up else v,
              self.m("OLED_VIN"): v if loads.oled_icc > 0 else 0.0,
              self.mpin("U21", "CT"): 0.0 if loads.oled_icc > 0 else v}
        ns[self.b("VBAT")] = vbat if vbat is not None else 4.2   # no pack: the charger holds BAT at VBATREG
        # verifier: the floating main-board ground had no initial guess; Newton then needed source stepping on
        # every DC run and failed outright (garbage op, e.g. I(BAT) 9.8 A) after harmless netlist changes such as
        # R53 = 1k on an otherwise unconnected I2C node. A small positive guess (main GND sits above base GND by
        # I_load x R_gnd) makes the op converge directly; nodesets are only initial guesses, results are unchanged.
        ns["gm"] = 0.02
        ns[self.m("VSYS_SENSE")] = v * M.value("R2") / (M.value("R1") + M.value("R2"))
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
             ("gnd_max", "MAX v(p_gnd)"), ("gnd_min", "MIN v(p_gnd)"), ("isys_max", "MAX i(visys)"),
             ("isys_avg", "AVG i(visys)"), ("ilink_max", "MAX i(vilink)"), ("ilink_avg", "AVG i(vilink)"),
             ("ignd_avg", "AVG i(vignd)"), ("ilsw_max", "MAX i(vilsw)")]
MEAS_BAT = [("ibat_max", "MAX i(vibat)"), ("ibat_avg", "AVG i(vibat)")]
MEAS_USB = [("iin_max", "MAX i(viin)"), ("iin_avg", "AVG i(viin)")]
MEAS_LOGIC = [("scl_max", "MAX v(p_scl)"), ("scl_min", "MIN v(p_scl)"),
              ("sda_marg", "MAX v(m_sda_marg)"), ("int_marg", "MAX v(m_int_marg)"), ("btn_marg", "MAX v(m_btn_marg)"),
              ("sda_min", "MIN v(p_sda)"), ("int_min", "MIN v(p_int)"), ("btn_min", "MIN v(p_btn)")]


def _errors(res):
    """ngspice errors, ignoring gmin-stepping warnings when the source-stepping fallback converged."""
    errs = res["_errors"]
    if "Source stepping completed" in res["_log"]:
        errs = [e for e in errs if "gmin stepping failed" not in e and "singular matrix" not in e]
    return errs


def run_tran(d: Deck, stop=1.5e-3, start=0.0, tmax=0.2e-6, logic=False, waves=()):
    d.tran(f"{tmax:.3g}", f"{stop:.6g}", 0, f"{tmax:.3g}")
    text = d.text()
    meas = list(MEAS_BASE)
    meas += MEAS_BAT if "Vibat " in text else []
    meas += MEAS_USB if "Viin " in text else []
    meas += MEAS_LOGIC if logic else []
    for name, expr in meas:
        d.meas(f"tran {name} {expr} from={start:.6g} to={stop:.6g}")
    if waves:
        d.wave(*waves)
    res = d.run()
    assert not _errors(res), _errors(res)[:5]
    assert not res.get("_missing"), (res.get("_missing"), res["_log"][-3000:])
    return res


def run_op(d: Deck, logic=False):
    text = d.text()
    exprs = {"vsys": "v(p_vsys)", "vled": "v(p_vled)", "v3v3": "v(p_3v3)", "vbat": "v(p_bat)", "gnd": "v(p_gnd)",
             "isys": "i(visys)", "ilink": "i(vilink)", "ignd": "i(vignd)", "ilsw": "i(vilsw)"}
    if "Vibat " in text:
        exprs["ibat"] = "i(vibat)"
    if "Viin " in text:
        exprs["iin"] = "i(viin)"
    if logic:
        exprs.update({"scl": "v(p_scl)", "sda_marg": "v(m_sda_marg)", "int_marg": "v(m_int_marg)",
                      "btn_marg": "v(m_btn_marg)", "sda": "v(p_sda)", "int": "v(p_int)", "btn": "v(p_btn)"})
    d.op()
    d.print_op(*exprs.values())
    res = d.run()
    assert not _errors(res), _errors(res)[:5]
    out = {}
    for i, k in enumerate(exprs):
        assert f"op_{i}" in res, (k, res["_log"][-3000:])
        out[k] = res[f"op_{i}"]
    return out


def longest_below(res, vec: str, thr: float) -> float:
    """Longest continuous time (s) the waveform `vec` stays below thr."""
    w = res["waves"]
    t = w.get("time", next(iter(w.values())))
    y = w[vec]
    below = y < thr
    best = run = 0.0
    for i in range(1, len(t)):
        if below[i] and below[i - 1]:
            run += t[i] - t[i - 1]
            best = max(best, run)
        elif not below[i]:
            run = 0.0
    return best


# ================================================================================ scenario definitions
def fw_scenarios(n_led: int) -> dict:
    """Firmware power policy points (docs/firmware.md): name -> (VBAT rested, LED cap A, OLED ICC A, motor)."""
    return {
        "full@3.65": (FW_V_FULL, FW_LED_BURST, OLED_ICC_MAX, "off"),
        "full@3.70": (3.70, FW_LED_BURST, OLED_ICC_MAX, "off"),
        "full@4.20": (4.20, FW_LED_BURST, OLED_ICC_MAX, "off"),
        "moving@3.65": (FW_V_FULL, FW_LED_MOVING, OLED_ICC_MAX, "run"),
        "moving@4.20": (4.20, FW_LED_MOVING, OLED_ICC_MAX, "run"),
        "derated@3.53": (FW_V_OFF, FW_LED_LOW, OLED_ICC_DIM, "run"),
        "lowbat@3.48": (FW_V_SHIP, FW_LED_CUE, OLED_ICC_DIM, "run"),
    }


def fw_loads(n_led, cap, icc, motor, sync: bool) -> Loads:
    if cap <= FW_LED_CUE:          # the red cue is one channel of one LED: tiny, use its average
        led = led_avg(cap, n_led)
    else:
        led = led_sync(cap, n_led) if sync else led_avg(cap, n_led)
    if motor == "run":
        mot = dict(motor="pwm" if sync else "avg", motor_icoil=MOTOR_I45)
    else:
        mot = dict(motor="off")
    return Loads(oled_icc=icc, tx=sync, oled_ripple=sync, **led, **mot)


def hw_loads(sync: bool, ich=WS_ICH) -> Loads:
    """No firmware limits: every LED full white (sync: 50 % PWM with all edges together), OLED 100 % white,
    both coils fully on (d = 1), +3V3 at its peak."""
    led = dict(led_ipk=ich, led_duty=0.5) if sync else dict(led_idc=ich)
    return Loads(oled_icc=OLED_ICC_MAX, motor="full", tx=sync, oled_ripple=sync, **led)


def check_all(check, items):
    """check() every (name, value, lo, hi, unit, source); passing ones first so that the report records every
    value up to the first violation (check() asserts on the first one that fails)."""
    def ok(it):
        _, v, lo, hi, _, _ = it
        return (lo is None or v >= lo) and (hi is None or v <= hi)
    for name, v, lo, hi, unit, src in sorted(items, key=lambda it: not ok(it)):
        check(name, v, lo=lo, hi=hi, unit=unit, source=src)


def supply_items(s: System, r: dict, tag: str, led_on=True, dc=False) -> list:
    """Common limits on a run result (op keys or tran meas keys)."""
    g = (lambda k: r[k]) if dc else (lambda k: r[k + "_min"])
    items = []
    if led_on:
        items.append((f"{tag}: VLED min", g("vled"), WS_VDD_MIN, None, "V", SRC_WS))
    items.append((f"{tag}: +3V3 min", g("v3v3"), V3V3_MIN, None, "V", SRC_3V3))
    if "ibat" in r or "ibat_max" in r:
        items.append((f"{tag}: I(BAT) peak", r["ibat"] if dc else r["ibat_max"], None, IBAT_OCP, "A", SRC_OCP))
    items.append((f"{tag}: I(SYS) DC", r["isys"] if dc else r["isys_avg"], None, SYS_DC_MAX, "A", SRC_SYS))
    return items


def check_supply(check, s: System, r: dict, tag: str, led_on=True, dc=False, extra=()):
    check_all(check, list(extra) + supply_items(s, r, tag, led_on, dc))


# ======================================================================================== the tests
def test_harness_model_inputs_from_netlist(main, base, check):
    """The link and battery-connector contact counts the PI model uses come from the netlists."""
    s = System(main, base)
    assert s.n_led == len(main.find("WS2812C")) - sum(not main.fitted(r) for r in main.find("WS2812C"))
    # SPEC 2: VSYS on pins 1-2, GND on 3, 4, 8 -> per-rail conductor counts used for the harness
    check("link VSYS conductors (J1/J3, netlist)", s.n_vsys, lo=2, source="SPEC.md 2 link pinout (pins 1, 2)")
    check("link GND conductors (J1/J3, netlist)", s.n_gnd, lo=3, source="SPEC.md 2 link pinout (pins 3, 4, 8)")
    r = s.conductor_r()
    assert 0.03 < r < 0.15, r
    assert s.bat_series in CONTACT_R and s.n_bpos >= 1 and s.n_bneg >= 1


@pytest.mark.parametrize("cname,vbat", [
    ("nominal", 4.2), ("worst", 4.2), ("nominal", 3.7),
    pytest.param("worst", 3.7, marks=pytest.mark.xfail(strict=True, reason=(
        "DESIGN ISSUE: with no firmware limit (48 LEDs full white + OLED 100 % + both coils on + +3V3 peak, "
        "~1.33 A) a 200 mOhm pack at 3.7 V pulls VLED to ~3.05 V < 3.3 V (WS2812C VDD min): the firmware LED "
        "limiter is a hardware protection function"))),
    pytest.param("nominal", 3.0, marks=pytest.mark.xfail(strict=True, reason=(
        "DESIGN ISSUE: uncapped full load at the end of discharge (VBAT 3.0 V) pulls +3V3 to ~2.68 V < 2.7 V "
        "(W25Q128JV VCC min) while the BQ25180 BUVLO deglitch (60 us) runs; only the firmware (SHIP at 3.48 V, "
        "loads capped) prevents it"))),
    pytest.param("worst", 3.0, marks=pytest.mark.xfail(strict=True, reason=(
        "DESIGN ISSUE: uncapped full load at VBAT 3.0 V worst corner: +3V3 ~2.41 V < 2.7 V (W25Q128JV VCC min)"))),
])
def test_hw_worst_case_uncapped_dc(main, base, check, cname, vbat):
    """Hardware worst case with NO firmware limits, steady state: is the firmware LED cap needed?

    Verifier: at an OCV of 3.0 V the V(BAT) >= VBUVLO check is impossible for any load (OCV = VBUVLO, every mA
    of discharge puts the terminal below it) and VLED >= 3.3 V is impossible for any VSYS-fed rail (OCV < 3.3 V),
    so those two checks only apply where the OCV is above the respective limit; the 3.0 V corner is judged on
    +3V3 (flash), the currents and the contact ratings, which a better design could pass."""
    s = System(main, base, CORNERS[cname])
    r = run_op(s.deck(f"uncapped DC {cname} {vbat}", hw_loads(sync=False), vbat=vbat))
    tag = f"uncapped DC VBAT {vbat} {cname}"
    extra = [
        (f"{tag}: link VSYS current per contact", r["ilink"] / s.n_vsys, None, SH_CONTACT_A, "A", SRC_SH),
        (f"{tag}: link GND current per contact", r["ignd"] / s.n_gnd, None, SH_CONTACT_A, "A", SRC_SH),
        (f"{tag}: battery connector current per contact", r["ibat"] / min(s.n_bpos, s.n_bneg), None,
         CONTACT_A[s.bat_series], "A", f"JST {s.bat_series} DS current rating per contact")]
    if vbat > VBUVLO:
        extra.append((f"{tag}: V(BAT) (BUVLO)", r["vbat"], VBUVLO, None, "V", SRC_BUVLO))
    check_supply(check, s, r, tag, dc=True, led_on=vbat > WS_VDD_MIN, extra=extra)


@pytest.mark.parametrize("cname", ["nominal", "worst", "cold"])
@pytest.mark.parametrize("point", ["full@3.65", "full@3.70", "full@4.20", "moving@3.65", "moving@4.20",
                                   "derated@3.53", "lowbat@3.48"])
def test_firmware_capped_dc(main, base, check, point, cname):
    """Firmware policy applied as average (steady) currents: all limits hold at every policy point."""
    s = System(main, base, CORNERS[cname])
    vbat, cap, icc, motor = fw_scenarios(s.n_led)[point]
    r = run_op(s.deck(f"capped DC {point}", fw_loads(s.n_led, cap, icc, motor, sync=False), vbat=vbat))
    tag = f"capped DC {point} {cname}"
    check_supply(check, s, r, tag, dc=True, extra=[(f"{tag}: V(BAT) (BUVLO)", r["vbat"], VBUVLO, None, "V", SRC_BUVLO)])


SYNC_XFAIL = pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE: the firmware limiter caps the AVERAGE ring current, but with all 48 LEDs lit (any brightness) "
    "and their 2 kHz PWM phases aligned the ring draws the full 48 x 3 x 5 mA = 0.72 A for 70-210 us per period, "
    "about as long as the battery-path settling (~150 us), so VLED sags almost as at DC: 3.08-3.25 V < 3.3 V "
    "(WS2812C VDD min) at VBAT <= 3.70 V (worst corner) and at 3.53 V even at the nominal corner"))


@pytest.mark.parametrize("cname,point", [
    ("nominal", "full@4.20"), ("worst", "full@4.20"), ("nominal", "full@3.70"), ("nominal", "full@3.65"),
    ("nominal", "moving@4.20"), ("worst", "moving@4.20"),
    pytest.param("worst", "full@3.70", marks=SYNC_XFAIL),
    pytest.param("worst", "full@3.65", marks=SYNC_XFAIL),
    ("nominal", "moving@3.65"),
    pytest.param("worst", "moving@3.65", marks=SYNC_XFAIL),
    pytest.param("nominal", "derated@3.53", marks=SYNC_XFAIL),
    pytest.param("worst", "derated@3.53", marks=SYNC_XFAIL),
    ("nominal", "lowbat@3.48"), ("worst", "lowbat@3.48"),
])
def test_firmware_capped_sync_pwm_transient(main, base, check, cname, point):
    """Firmware caps with the brief's worst case: PWM edges of all LEDs together, motor PWM edges aligned,
    TX bursts and boost ripple. Checks the instantaneous minimums, BUVLO deglitch and the BATOCP peak."""
    s = System(main, base, CORNERS[cname])
    vbat, cap, icc, motor = fw_scenarios(s.n_led)[point]
    loads = fw_loads(s.n_led, cap, icc, motor, sync=True)
    r = run_tran(s.deck(f"capped sync {point}", loads, vbat=vbat), stop=1.2e-3, waves=("v(p_bat)",))
    tag = f"capped sync-PWM {point} {cname}"
    # verifier: VLED is checked at the low-battery cue point too: LED_PWR_EN stays on for the red cue, so all 48
    # WS2812C ICs on the rail still need VDD >= 3.3 V (the author skipped it for cap <= FW_LED_CUE)
    check_supply(check, s, r, tag, led_on=True, extra=[
        (f"{tag}: V(BAT) below BUVLO, longest", longest_below(r, "v(p_bat)", VBUVLO), None, TBUVLO, "s", SRC_BUVLO),
        (f"{tag}: GND offset main-base, peak", max(r["gnd_max"], -r["gnd_min"]), None, BQ_VIL, "V",
         SRC_BQ_VIL + " (offset alone)")])


@pytest.mark.parametrize("temp", [-10.0, 25.0, 60.0])
def test_temperature_capped_full_budget(main, base, check, temp):
    """Temperature: RON (TPS22917 / BQ25180 at DS max for the temperature), copper resistance of the harness,
    weakest pack, at the lowest VBAT where the full firmware LED budget is allowed (3.65 V), steady state."""
    c = Corner(f"T{temp:+.0f}", temp=temp, rint=BATT_RINT[1], aged=True, fet="max", spacing=5e-3, caps="min")
    s = System(main, base, c)
    vbat, cap, icc, motor = fw_scenarios(s.n_led)["full@3.65"]
    r = run_op(s.deck(f"temp {temp}", fw_loads(s.n_led, cap, icc, motor, sync=False), vbat=vbat))
    tag = f"capped DC full@3.65 at {temp:+.0f} C"
    check_supply(check, s, r, tag, dc=True, extra=[(f"{tag}: V(BAT) (BUVLO)", r["vbat"], VBUVLO, None, "V", SRC_BUVLO)])


@pytest.mark.parametrize("cname", ["nominal", "worst"])
def test_vbat_3v0_end_of_discharge(main, base, check, cname):
    """VBAT 3.0 V (BUVLO): with the LEDs, OLED and actuator off (firmware ships at 3.48 V), +3V3 must still be
    valid for the flash right up to the BUVLO disconnect."""
    s = System(main, base, CORNERS[cname])
    r = run_tran(s.deck(f"3.0 V {cname}", Loads(), vbat=3.0), stop=1.2e-3)
    check(f"VBAT 3.0 V, LEDs/OLED/motor off, {cname}: +3V3 min", r["v3v3_min"], lo=V3V3_MIN, unit="V",
          source=SRC_3V3)


USB_NOBAT_XFAIL = pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE: with the battery absent or below BUVLO the BQ25180 cannot supplement SYS, and the firmware "
    "'on USB' budget (LED 150 mA + OLED + actuator + +3V3) exceeds ILIM min 450 mA -> SYS collapses"))


@pytest.mark.parametrize("vbus", [4.5, 5.0, 5.5])
def test_usb_vbus_corners(main, base, check, vbus):
    """USB 4.5 / 5.0 / 5.5 V with a 3.7 V pack charging: SYS regulation (4.5 V +/-2 %, dropout at 4.5 V),
    ILIM 450 mA min, DPPM and supplement under the firmware 'on USB' load with aligned PWM edges."""
    s = System(main, base, WORST if vbus != 5.5 else NOMINAL)
    vsysreg = {4.5: BQ_VSYSREG * (1 - BQ_VSYSREG_TOL), 5.0: BQ_VSYSREG,
               5.5: BQ_VSYSREG * (1 + BQ_VSYSREG_TOL)}[vbus]
    ilim = BQ_ILIM500[0] if vbus != 5.5 else BQ_ILIM500[2]
    loads = Loads(oled_icc=OLED_ICC_MAX, motor="pwm", motor_icoil=MOTOR_I45, **led_sync(FW_LED_SUST, s.n_led))
    r = run_tran(s.deck(f"usb {vbus}", loads, vbat=3.7, vbus=vbus, vsysreg=vsysreg, ilim=ilim), stop=1.2e-3)
    tag = f"USB VBUS {vbus} V, pack 3.7 V, on-USB caps"
    check_supply(check, s, r, tag, extra=[
        (f"{tag}: VLED max", r["vled_max"], None, WS_VDD_MAX, "V", SRC_WS),
        (f"{tag}: VSYS max", r["vsys_max"], None, VIN_MAX, "V", SRC_VIN55),
        (f"{tag}: I(IN) peak", r["iin_max"], None, IIN_MAX, "A", SRC_IIN)])


@pytest.mark.parametrize("ilim_code,led_cap,icc,motor", [
    pytest.param(500, FW_LED_SUST, OLED_ICC_MAX, "run", marks=USB_NOBAT_XFAIL),
    pytest.param(100, 0.020, OLED_ICC_MAX * 5 / 16, "off", marks=pytest.mark.xfail(strict=True, reason=(
        "DESIGN ISSUE: the firmware's ILIM = 100 mA phase budget (LEDs <= 20 mA, OLED C7 <= 04h, no actuator) "
        "does not bound the OLED panel (white content) or +3V3 (TX + flash erase): demand ~0.13 A > ILIM min "
        "80 mA, so without a pack able to supplement SYS collapses (brown-out loop)"))),
], ids=["ILIM500-on-USB-budget", "ILIM100-boot-budget"])
def test_usb_without_battery(main, base, check, ilim_code, led_cap, icc, motor):
    """USB only, pack absent or below BUVLO (BQ25180 cannot supplement, SLUSE99C 8.3.3): the firmware budget's
    average demand must fit under ILIM min, otherwise SYS has no regulated operating point."""
    s = System(main, base, NOMINAL)
    ilim = (BQ_ILIM500 if ilim_code == 500 else BQ_ILIM100)[0]
    mot = dict(motor="avg", motor_icoil=MOTOR_I45) if motor == "run" else {}
    loads = Loads(oled_icc=icc, oled_ripple=False, tx=False, **led_avg(led_cap, s.n_led), **mot)
    r = run_op(s.deck(f"usb only {ilim_code}", loads, vbat=None, vbus=5.0, ilim=ilim))
    tag = f"USB only (no pack), ILIM {ilim_code} mA code at min ({ilim * 1e3:.0f} mA), firmware budget"
    check_all(check, [(f"{tag}: I(IN) (pinned at ILIM = no regulation)", r["iin"], None, 0.98 * ilim, "A",
                       "BQ25180 DS SLUSE99C 7.5 ILIM min (load must stay below it without supplement)"),
                      (f"{tag}: VLED", r["vled"], WS_VDD_MIN, None, "V", SRC_WS),
                      (f"{tag}: +3V3", r["v3v3"], V3V3_MIN, None, "V", SRC_3V3)])


@pytest.mark.parametrize("vbat", [4.2, 3.7])
def test_ground_bounce_logic_levels(main, base, check, vbat):
    """Ground offset between the boards during the uncapped worst case (all LED PWM edges together, both coils,
    TX, boost ripple) against the logic levels that cross the link."""
    s = System(main, base, WORST)
    r = run_tran(s.deck(f"bounce {vbat}", hw_loads(sync=True), vbat=vbat, logic=True), stop=1.2e-3, logic=True)
    tag = f"uncapped sync-PWM, VBAT {vbat} worst"
    check(f"{tag}: GND offset main-base, peak", max(r["gnd_max"], -r["gnd_min"]), hi=BQ_VIL, unit="V",
          source=SRC_BQ_VIL + " (offset alone)")
    check(f"{tag}: I2C_SCL low (nRF) seen at BQ25180", r["scl_max"], hi=BQ_VIL, unit="V", source=SRC_BQ_VIL)
    check(f"{tag}: I2C_SCL min at BQ25180", r["scl_min"], lo=PIN_ABS_MIN, unit="V", source=SRC_NEG)
    for k, name in (("sda", "I2C_SDA (BQ ACK)"), ("int", "CHG_INT_N"), ("btn", "BTN_N")):
        check(f"{tag}: {name} low at nRF minus 0.3 VDD", r[f"{k}_marg"], hi=0.0, unit="V", source=SRC_NRF_VIL)
        check(f"{tag}: {name} min at nRF", r[f"{k}_min"], lo=PIN_ABS_MIN, unit="V", source=SRC_NEG)


def test_logic_levels_pullup_extremes(main, base, check):
    """Pull-up tolerance extremes (4 parts, 16 corners) at the uncapped DC worst case, VBAT 3.7 V worst corner."""
    s = System(main, base, WORST)
    refs = [r for r in ("R53", "R54", "R55", "R56") if r in main.comps]
    worst = {"scl": -9.0, "sda_marg": -9.0, "int_marg": -9.0, "btn_marg": -9.0}
    for sc in main.extremes(refs):
        r = run_op(s.deck("pull-up extremes", hw_loads(sync=False), vbat=3.7, logic=True, scale=sc), logic=True)
        for k in worst:
            worst[k] = max(worst[k], r[k])
    check("pull-up extremes: I2C_SCL low seen at BQ25180", worst["scl"], hi=BQ_VIL, unit="V", source=SRC_BQ_VIL)
    for k in ("sda_marg", "int_marg", "btn_marg"):
        check(f"pull-up extremes: {k} (low minus 0.3 VDD at nRF)", worst[k], hi=0.0, unit="V", source=SRC_NRF_VIL)


@pytest.mark.parametrize("cname", ["nominal", "worst"])
def test_led_rail_inrush(main, base, check, cname):
    """LED_PWR_EN rising with the OLED boost running and +3V3 at peak: CT (C7) slew limits the inrush into
    VLED (C8, C9, C101-C148). Worst corner: extremes of C7/C8/C9 (8 corners)."""
    s = System(main, base, CORNERS[cname])
    loads = Loads(led_on_at=100e-6, oled_icc=OLED_ICC_MAX, oled_ripple=False)
    worst = dict(ibat=0.0, ilsw=0.0, v3v3=9.0, vsys=9.0)
    refs = [r for r in ("C7", "C8", "C9") if r in main.comps]
    for sc in (tol_extremes(main, refs) if cname == "worst" else [None]):
        r = run_tran(s.deck("inrush", loads, vbat=3.7, scale=sc), stop=2.8e-3, tmax=2e-6)
        worst = dict(ibat=max(worst["ibat"], r["ibat_max"]), ilsw=max(worst["ilsw"], r["ilsw_max"]),
                     v3v3=min(worst["v3v3"], r["v3v3_min"]), vsys=min(worst["vsys"], r["vsys_min"]))
    tag = f"LED rail turn-on, VBAT 3.7 {cname}" + (", C7/C8/C9 extremes" if cname == "worst" else "")
    check(f"{tag}: I(BAT) peak", worst["ibat"], hi=IBAT_OCP, unit="A", source=SRC_OCP)
    check(f"{tag}: TPS22917 switch current peak", worst["ilsw"], hi=LSW_IPLS, unit="A", source=SRC_LSW)
    check(f"{tag}: +3V3 min", worst["v3v3"], lo=V3V3_MIN, unit="V", source=SRC_3V3)


def test_mlcc_dc_bias_stress(main, base, check):
    """Stress angle: every capacitor on both boards at 50 % of its netlist value (an assumed X5R DC-bias loss at
    3.7-4.5 V, not a datasheet figure), firmware full budget with aligned LED PWM and TX bursts at 3.70 V: the
    droop is set by the battery path, so the minimums must not move materially."""
    s = System(main, base, NOMINAL)
    vbat, cap, icc, motor = fw_scenarios(s.n_led)["full@3.70"]
    half_m = {r: 0.5 for r in main.comps if is_cap(r)}
    half_b = {r: 0.5 for r in base.comps if is_cap(r)}
    r = run_tran(s.deck("dc-bias stress", fw_loads(s.n_led, cap, icc, motor, sync=True), vbat=vbat, scale=half_m,
                        scale_base=half_b), stop=1.2e-3)
    tag = "all MLCC x0.5, full@3.70 nominal, aligned PWM"
    check_supply(check, s, r, tag, extra=[(f"{tag}: GND offset main-base, peak", max(r["gnd_max"], -r["gnd_min"]),
                                           None, BQ_VIL, "V", SRC_BQ_VIL + " (offset alone)")])


@pytest.mark.fault
def test_fault_ct_cap_missing_detected(main, base, check):
    """FAULT: C7 (TPS22917 CT) left off -> CT-open slew 44 mV/us charges ~49 uF of VLED at ~2 A: the battery
    current must exceed BATOCP (the BQ25180 would drop SYS) -- proves the inrush check catches it."""
    main.remove("C7")
    s = System(main, base, NOMINAL)
    r = run_tran(s.deck("inrush, C7 missing", Loads(led_on_at=100e-6, oled_icc=OLED_ICC_MAX), vbat=3.7),
                 stop=1.0e-3, tmax=0.2e-6)
    check("FAULT C7 off: I(BAT) peak exceeds IBAT_OCP (detected)", r["ibat_max"], lo=IBAT_OCP, unit="A",
          source=SRC_OCP)


@pytest.mark.fault
def test_fault_stiff_i2c_pullup_detected(main, base, check):
    """FAULT: R53 (I2C_SCL pull-up) fitted as 1k instead of 4.7k -> the nRF's standard-drive low (IOL >= 1 mA at
    0.4 V) cannot pull SCL below the BQ25180 VIL across the link: the logic-level check must flag it."""
    main.override("R53", "1k")
    s = System(main, base, WORST)
    r = run_op(s.deck("R53 1k", hw_loads(sync=False), vbat=3.7, logic=True), logic=True)
    check("FAULT R53 = 1k: SCL low seen at BQ25180 exceeds VIL (detected)", r["scl"], lo=BQ_VIL, unit="V",
          source=SRC_BQ_VIL)


# ------------------------------------------------------------------ decoupling vs datasheet minimums / maximums
def net_cap(d: Design, net: str, sign: int = 0) -> float:
    """Sum of fitted capacitors between `net` and GND on one board, at nominal (sign 0) or +/- tolerance."""
    tot = 0.0
    for r in d.on_net(net, "C"):
        if is_cap(r) and d.fitted(r) and set(d.pins[r].values()) == {net, "GND"}:
            tot += d.value(r) * (1 + sign * cap_tol(d, r))
    return tot


def decoupling_items(main: Design, base: Design) -> list:
    n_drv = len(main.find("DRV8837"))
    n_lsw = len(main.find("TPS22917"))
    need_main = 1e-6 + n_lsw * 1e-6 + n_drv * 0.1e-6
    vbus = net_cap(base, "VBUS", +1) + (net_cap(main, "VBUS", +1) if "VBUS" in main.nets else 0.0)
    return [
        ("BQ25180 SYS, base-board VSYS caps (nominal)", net_cap(base, "VSYS"), 10e-6, None, "F", SRC_CSYS_MIN),
        ("BQ25180 SYS, all VSYS caps on both boards at +tol (behind-switch VLED/OLED_VIN caps excluded)",
         net_cap(base, "VSYS", +1) + net_cap(main, "VSYS", +1), None, 100e-6, "F", SRC_CSYS_MAX),
        ("BQ25180 BAT, base-board VBAT caps at -tol", net_cap(base, "VBAT", -1), 1e-6, None, "F", SRC_CBAT),
        ("BQ25180 IN, base-board VBUS caps at -tol", net_cap(base, "VBUS", -1), 1e-6, None, "F", SRC_CIN),
        ("BQ25180 IN, VBUS caps on both boards at +tol", vbus, None, 10e-6, "F", SRC_CIN),
        (f"main VSYS caps at -tol vs local-bypass minimums (RT9080 1 uF + {n_lsw} x TPS22917 1 uF + "
         f"{n_drv} x DRV8837 0.1 uF = {need_main * 1e6:.1f} uF)", net_cap(main, "VSYS", -1), need_main, None, "F",
         SRC_MAIN_BYPASS),
    ]


def test_vsys_decoupling_vs_datasheets(main, base, check):
    """Netlist capacitance on the power path against the datasheet minimums and the BQ25180 CSYS maximum
    (verifier addition: the PI transients barely move when bulk caps are left off, because the droop is set by
    the battery path, so missing or excessive decoupling needs its own datasheet check)."""
    check_all(check, decoupling_items(main, base))


def rewire(d: Design, ref: str, pin: str, net: str):
    """Fault injection for a wrong connection: move one pin of `ref` to `net` (in-memory netlist only)."""
    old = d.pins[ref][pin]
    d.nets[old] = [x for x in d.nets[old] if not (x[0] == ref and x[1] == pin)]
    d.pins[ref][pin] = net
    d.nets.setdefault(net, []).append((ref, pin, ""))
    return d


@pytest.mark.fault
def test_fault_base_sys_caps_low_detected(main, base, check):
    """FAULT (value off by 10x): base C2/C4 fitted as 1 uF instead of 10 uF -> the BQ25180 SYS pin has 2 uF:
    the decoupling check must flag it (the transient PI checks do not, the droop is battery-path limited)."""
    for r in base.on_net("VSYS", "C"):
        base.override(r, "1u")
    items = decoupling_items(main, base)
    name, v, lo, hi, unit, src = items[0]
    check(f"FAULT base SYS caps 1 uF: {name} below the DS minimum (detected)", v, hi=0.999 * lo, unit=unit,
          source=src)


@pytest.mark.fault
def test_fault_main_vsys_bulk_missing_detected(main, base, check):
    """FAULT (parts left off): the main-board VSYS bulk MLCCs (every VSYS cap of 1 uF or more) are not fitted ->
    only the 100 nF bypass caps remain at the RT9080 / TPS22917 / DRV8837 inputs: the decoupling check must
    flag it."""
    for r in main.on_net("VSYS", "C"):
        if set(main.pins[r].values()) == {"VSYS", "GND"} and main.value(r) >= 1e-6:
            main.remove(r)
    name, v, lo, hi, unit, src = decoupling_items(main, base)[-1]
    check(f"FAULT main VSYS bulk off: {name} (detected)", v, hi=0.999 * lo, unit=unit, source=src)


@pytest.mark.fault
def test_fault_battery_connector_single_contact_detected(main, base, check):
    """FAULT (wrong connection): the battery connector's second VBAT contact left unconnected, so the whole pack
    current runs through one JST SH contact: the per-contact current check of the uncapped case must flag it."""
    s0 = System(main, base)
    rewire(base, s0.bat_ref, [p for p, n in base.pins[s0.bat_ref].items() if n == "VBAT"][-1], "BATT_NC")
    s = System(main, base, NOMINAL)
    assert s.n_bpos == s0.n_bpos - 1
    r = run_op(s.deck("J2 single contact", hw_loads(sync=False), vbat=4.2))
    check("FAULT battery connector, one VBAT contact: current per contact exceeds the rating (detected)",
          r["ibat"] / min(s.n_bpos, s.n_bneg), lo=CONTACT_A[s.bat_series], unit="A",
          source=f"JST {s.bat_series} DS current rating per contact")


@pytest.mark.fault
def test_fault_shorted_led_detected(main, base, check):
    """FAULT (shorted LED): one WS2812C fails VDD-GND short (20 mOhm) while the rail runs the firmware full budget
    at 3.70 V: the I(BAT) <= IBAT_OCP check must flag it (the BQ25180 BATOCP hiccup is then the only protection:
    U2 has no current limit, so the VSYS bulk discharges through it far above IPLS before BATOCP acts)."""
    s = System(main, base, NOMINAL)
    vbat, cap, icc, motor = fw_scenarios(s.n_led)["full@3.70"]
    d = s.deck("shorted LED", fw_loads(s.n_led, cap, icc, motor, sync=False), vbat=vbat)
    d += ["Vsh shc 0 PULSE(0 1 200u 100n 100n 1 2)",
          f"Bshort {s.m('VLED')} gm I = {{ v(shc) * (v({s.m('VLED')}) - v(gm)) / 0.02 }}"]
    r = run_tran(d, stop=0.5e-3, tmax=0.05e-6)
    check("FAULT shorted LED: I(BAT) peak exceeds IBAT_OCP (detected)", r["ibat_max"], lo=IBAT_OCP, unit="A",
          source=SRC_OCP)
    check("FAULT shorted LED: TPS22917 U2 current peak exceeds IPLS (no current limit; detected)", r["ilsw_max"],
          lo=LSW_IPLS, unit="A", source=SRC_LSW)


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE: with the SPEC 5.4 WS2812B-2020-V6 drop-in (12 mA/ch) the aligned PWM peak is 1.73 A even at the "
    "300 mA average cap: I(BAT) ~1.85 A > IBAT_OCP 1.5 A -> BATFET hiccup / brown-out; a peak (lit-channel) "
    "limit is mandatory with that part"))
def test_ws2812b_dropin_peak(main, base, check):
    """SPEC 5.4 allows the WS2812B-2020-V6 (12 mA/ch) as a pin-compatible drop-in. Even at the firmware's
    300 mA average cap its aligned PWM peak is 48 x 3 x 12 mA = 1.73 A."""
    s = System(main, base, NOMINAL)
    loads = Loads(oled_icc=OLED_ICC_MAX, **led_sync(FW_LED_BURST, s.n_led, ich=WSB_ICH))
    r = run_tran(s.deck("WS2812B", loads, vbat=4.2), stop=1.2e-3)
    check("WS2812B drop-in, 300 mA cap, aligned PWM: I(BAT) peak", r["ibat_max"], hi=IBAT_OCP, unit="A",
          source=SRC_OCP)


def led_peak_budget(s: System, vbat: float, icc: float, motor_avg: float = 0.0, iters: int = 10) -> float:
    """Largest steady ring current (= aligned PWM peak: lit channels x 5 mA) keeping VLED >= 3.3 V (bisection
    on the operating point; the 70-210 us PWM pulses settle like DC, see the sync-PWM test)."""
    mot = dict(motor="avg", motor_icoil=MOTOR_I45) if motor_avg else {}

    def vled(i_ring):
        return run_op(s.deck("budget", Loads(oled_icc=icc, tx=False, oled_ripple=False,
                                             led_idc=max(i_ring, 1e-9) / (3 * s.n_led), **mot), vbat=vbat))["vled"]
    full = 3 * s.n_led * WS_ICH
    if vled(0.0) < WS_VDD_MIN:
        return 0.0
    if vled(full) >= WS_VDD_MIN:
        return full
    lo, hi = 0.0, full
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if vled(mid) >= WS_VDD_MIN else (lo, mid)
    return lo


BUDGET_VBAT = (3.48, 3.53, 3.60, 3.65, 3.70, 3.80, 3.90, 4.00, 4.20)


def test_led_peak_budget_vs_vbat(main, base, check):
    """Derived firmware limit (answers 'is a firmware LED limit needed'): the largest INSTANTANEOUS ring current
    (lit channels x 5 mA, all PWM phases aligned) that keeps VLED >= 3.3 V at the worst corner, per rested VBAT,
    with the OLED at its policy level and +3V3 at its peak, actuator idle. Where it is below the full-ring
    0.72 A, the limiter must cap the lit-channel count, not only the average current."""
    s = System(main, base, WORST)
    full = 3 * s.n_led * WS_ICH
    for vbat in BUDGET_VBAT:
        icc = OLED_ICC_MAX if vbat >= FW_V_DERATE else OLED_ICC_DIM
        best = led_peak_budget(s, vbat, icc)
        check(f"max aligned ring peak for VLED >= 3.3 V, VBAT {vbat:.2f} (worst corner, actuator idle)", best,
              lo=0.0, unit="A", source=SRC_WS + f" (derived budget; full ring = {full:.2f} A)")
    check("full-ring aligned peak allowed at VBAT 4.20 V (worst corner)", led_peak_budget(s, 4.2, OLED_ICC_MAX),
          lo=full, unit="A", source=SRC_WS + " (derived budget)")


@pytest.mark.parametrize("vbat", [3.53, 3.65, 3.70])
def test_proposed_peak_cap_fix(main, base, check, vbat):
    """Fix check: with the ring's aligned peak limited to 95 % of the derived budget (fewer lit channels instead of
    lower PWM duty) the worst-corner sync-PWM transient keeps VLED >= 3.3 V at the low-VBAT policy points."""
    s = System(main, base, WORST)
    icc = OLED_ICC_MAX if vbat >= FW_V_DERATE else OLED_ICC_DIM
    peak = 0.95 * led_peak_budget(s, vbat, icc)
    cap = FW_LED_BURST if vbat >= FW_V_FULL else FW_LED_LOW
    loads = Loads(oled_icc=icc, led_ipk=peak / (3 * s.n_led), led_duty=min(1.0, cap / max(peak, 1e-6)))
    r = run_tran(s.deck(f"peak-capped {vbat}", loads, vbat=vbat), stop=1.2e-3)
    tag = f"peak-capped ring ({peak:.2f} A aligned), VBAT {vbat} worst"
    check_supply(check, s, r, tag)


@pytest.mark.slow
def test_monte_carlo_capacitors_sync_pwm(main, base, check):
    """Monte Carlo (200 draws) over every capacitor on the PI path of BOTH boards (tolerances from the value
    string or the MPN tolerance letter), firmware full budget with aligned LED/motor PWM edges, VBAT 3.7 V nominal
    corner: VLED and +3V3 minimums and ground offset.
    (Verifier: the base-board SYS/BAT/VBUS caps were missing, and the main-board draws leaked onto the base parts
    with the same references C1-C4.)"""
    s = System(main, base, NOMINAL)
    caps_m = pi_caps(main, System.MAIN_NETS)
    caps_b = pi_caps(base, System.BASE_NETS)
    vbat, cap, icc, motor = fw_scenarios(s.n_led)["full@3.70"]
    loads = fw_loads(s.n_led, cap, icc, motor, sync=True)
    vled, v3, gnd = [], [], []
    for sm, sb in zip(tol_draws(main, caps_m, 200, seed=7), tol_draws(base, caps_b, 200, seed=8)):
        r = run_tran(s.deck("mc", loads, vbat=vbat, scale=sm, scale_base=sb), stop=0.6e-3)
        vled.append(r["vled_min"]), v3.append(r["v3v3_min"]), gnd.append(max(r["gnd_max"], -r["gnd_min"]))
    check("MC 200: VLED min (worst draw)", min(vled), lo=WS_VDD_MIN, unit="V", source=SRC_WS)
    check("MC 200: +3V3 min (worst draw)", min(v3), lo=V3V3_MIN, unit="V", source=SRC_3V3)
    check("MC 200: GND offset (worst draw)", max(gnd), hi=BQ_VIL, unit="V", source=SRC_BQ_VIL + " (offset alone)")
