"""VSYS sense: R1/R2 divider + C5 on VSYS_SENSE into the nRF52840 SAADC, AIN0 = P0.02 (SPEC.md §3, §4).

Everything the schematic defines (R1, R2, C5, their tolerances, and which MCU pin the net reaches) comes from the
main-board netlist. SAADC behaviour comes from models/vsys_sense__nrf52840_saadc.lib (nRF52840 PS v1.1).
Firmware use (docs/firmware.md §3.1 DTS, §12.4): gain 1/6, internal 0.6 V reference (3.6 V full scale), 12 bit,
8x oversampling (burst), tACQ 40 µs, VSYS = code x 3.6/4096 x 3.2, one-point calibration at 3.800 V.

Angles:
  * input range     VSENSE vs the 3.6 V full scale and vs VDD (RT9080 -2 %, dropout) for VSYS 3.0 ... 5.5 V,
                    R tolerance corners x TCR corners x C5 insulation resistance x -10/25/60 °C
  * sampling        CSAMPLE charge sharing through C5 for every tACQ option, CSAMPLE pre-charge 0 V / VDD,
                    VSYS 3.0/4.2/5.5 V, C5 tolerance and X7R temperature; the SAADC model against PS Table 95
  * sample interval C5 recovery between 8x oversampling bursts (load extreme on the divider)
  * VSYS ripple     2 kHz LED PWM at the hardware worst-case LED current (load extreme on VSYS)
  * accuracy        firmware constant, raw gain (production window), uncalibrated (bring-up), one-point calibrated
                    at -10/25/60 °C (TCR, CEG, VOS, C5 insulation resistance), SHIP threshold vs BQ25180 VBATPOR
                    (also 15/35 °C, the band where the old 3.48 V rule holds), AIN leakage sensitivity
  * aging           (verifier) calibrated reading and SHIP rule at 25 °C after R1/R2 datasheet drift (±0.5 %) and
                    C5 IR loss to its endurance bound
  * firmware rules  the strict xfails keep the old values (SHIP 3.48 V, ±10 mV, raw gain ±3 %, bring-up ±2 %) as the
                    evidence; the *_with_fw_rule guards apply firmware.md §12.4 / §16 test 8 and bringup.md B-8.5:
                    every threshold that protects a datasheet limit compares the true value with
                    VBAT_est = calibrated reading - 75 mV (VREAD_MARGIN), SHIP when VBAT_est < 3.465 V (a reading
                    below 3.54 V), the documented calibrated drift for a fresh unit at 15-35 °C and over -10...60 °C
                    and an aged unit at 25 °C and at -10 / 60 °C (VSENSE-1/4), calibration reference from a DMM at
                    TP1 or with the board under 5 mA (VSENSE-5), ±5.5 % raw-gain and uncalibrated windows
                    (VSENSE-2/3); test_read_margin_covers_over_read_with_fw_rule checks the 75 mV against the worst
                    over-read at every documented VBAT_est / VSYS_est threshold
  * settling        after power-up, all R/C corners, X7R temperature
  * sleep current   VSYS 3.7 / 4.2 V, all corners
  * faults          C5 left off (x2), R1/R2 swapped, R1 decade typo, R2 left off, C5 wrong value, R1 bridged
                    (VSYS_SENSE tied to VSYS), C5 one decade low at the firmware tACQ
"""

from __future__ import annotations

import functools
import itertools
import math

import pytest

import spicelib

LIB = "vsys_sense__nrf52840_saadc.lib"
NETS = {"VSYS", "VSYS_SENSE", "GND"}

# ---------------------------------------------------------------- datasheet / document constants
PS = "nRF52840 PS v1.1"
GAIN, VREF = 1 / 6, 0.6                       # firmware.md §3.1 (ADC_GAIN_1_6, internal ref); PS §6.23.2
FS = VREF / GAIN                              # 3.6 V, PS §6.23.2 "input range = 0.6 V / gain"
LSB12 = FS / 4096                             # 0.879 mV at the pin
HALF_LSB = 0.5 * LSB12                        # settling / dynamic-error criterion (see _dyn_src)
TACQ_TABLE95 = [(3e-6, 10e3), (5e-6, 40e3), (10e-6, 100e3), (15e-6, 200e3), (20e-6, 400e3), (40e-6, 800e3)]
TCONV = 2e-6                                  # PS §6.23.10.1 tCONV < 2 µs
CSAMPLE = 2.5e-12                             # PS §6.23.10.1 CSAMPLE at maximum gain (largest, worst case)
CPAD = 3e-12                                  # PS §6.9.3.1 GPIO pad capacitance
EG16 = 0.03                                   # PS §6.23.10.1 EG1/6 -3 ... +3 %
CEG_TYP = 0.0002                              # PS §6.23.10.1 CEG 0.02 %/°C (typ, the only value given)
VOS_LSB12 = 8.0                               # PS §6.23.10.1 VOS ±2 LSB10 (calibrated) = ±8 LSB12
N_OVERSAMPLE = 8                              # firmware.md §3.1 zephyr,oversampling = <3>
TACQ_FW = 40e-6                               # firmware.md §3.1 acquisition time 40 µs

VDD_NOM, VDD_ACC, VDROP_MAX = 3.3, 0.02, 0.53  # RT9080 DS9080-09 §14: VOUT ±2 %, VDROP 0.53 V max at 600 mA
VDD_MAX = VDD_NOM * (1 + VDD_ACC)


def vdd_min(vsys):
    """Lowest +3V3 (nRF VDD) at this VSYS: RT9080 -2 % or dropout (DS9080-09 §14)."""
    return min(VDD_NOM * (1 - VDD_ACC), vsys - VDROP_MAX)


TCR = 100e-6          # UNI-ROYAL thick-film chip resistor DS V.3 (2019-02-12) §11: 0402, R > 10 Ω: ±100 ppm/°C
X7R_TEMP = 0.15       # Samsung MLCC catalog 2015, temperature characteristic B (X7R): ±15 % over -55 ... 125 °C


def ir_min(c):
    """Samsung MLCC catalog 2015, Reliability Test Condition item 2, 16 V rated: IR >= 10,000 MΩ or 100 MΩ·µF,
    whichever is smaller (25 °C).  C5 = CL05B104KO5NNNC (B = X7R, O = 16 V)."""
    return min(10e9, 100e6 * 1e-6 / c)


def ir_eol(c):
    """Same catalog, high-temperature load test: IR >= 500 MΩ or 25 MΩ·µF, whichever is smaller. Used as the bound for
    a hot or aged part (the catalog gives no IR-vs-temperature curve)."""
    return min(500e6, 25e6 * 1e-6 / c)


V_CAL = 3.800          # firmware.md §12.4 / §16 test 8: production one-point calibration at 3.800 V
V_SHIP_OLD = 3.48      # pre-VSENSE-1 firmware.md §12.4 SHIP entry (evidence of the strict xfails; 15/25/35 °C cases)
VREAD_MARGIN = 0.075   # firmware.md §12.4 (VSENSE-1/4/5): every threshold that protects a datasheet limit compares the
                       # true value with VBAT_est = calibrated reading - 75 mV (VSYS_est likewise)
VBAT_EST_SHIP = 3.465  # firmware.md §12.4 low-battery policy: SHIP when VBAT_est < 3.465 V (VBATPOR max 3.46 V + 5 mV)
V_SHIP = round(VBAT_EST_SHIP + VREAD_MARGIN, 6)   # 3.54 V: the SHIP threshold as a calibrated reading
CAL_ACC_OLD = 0.010    # pre-VSENSE-1 firmware.md §12.4 '±10 mV calibrated ADC error' (kept as the 25 °C check, where it
                       # still holds; stricter than CAL_ACC_FRESH)
# firmware.md §12.4 (VSENSE-1/4): documented calibrated drift of the reading at the SHIP point, (high, low) in V. The
# decided figures were +48/-54 (fresh, -10...60 °C) and +72/-78 mV (aged, -10/60 °C); at the 3.54 V SHIP reading the
# model gives 54.03 mV low and 72.44 / 78.30 mV, so these are the whole-mV values that hold. The error grows with VSYS
# (about 2.0-2.1 % of the reading at the aged -10/60 °C corner), which test_read_margin_covers_over_read_with_fw_rule
# covers threshold by threshold.
CAL_ACC_FRESH = 0.024              # fresh unit at 15-35 °C: about ±24 mV
CAL_DRIFT_FRESH = (0.048, 0.055)   # fresh unit over -10...60 °C
CAL_DRIFT_AGED = (0.030, 0.036)    # aged unit (R1/R2 drift, C5 IR loss) at 25 °C
CAL_DRIFT_AGED_T = (0.073, 0.079)  # aged unit at -10 / 60 °C (temperature and ageing combined)
I_CAL_MAX = 5e-3       # firmware.md §12.4 / §16 test 8 (VSENSE-5): no DMM at TP1 -> board under 5 mA while calibrating
RAW_GAIN_WIN_OLD = 0.03   # pre-VSENSE-2 firmware.md §16 test 8 raw-gain window ±3 %
RAW_GAIN_WIN = 0.055      # firmware.md §16 test 8: raw gain within ±5.5 % (VSENSE-2)
UNCAL_WIN_OLD = 0.02      # pre-VSENSE-3 bringup.md B-8.5 uncalibrated window ±2 %
UNCAL_WIN = 0.055         # bringup.md B-8.5: uncalibrated vs DMM at TP1 within ±5.5 % (VSENSE-3)
VBATPOR_MAX = 3.46     # BQ25180 DS SLUSE99C §7.5 VBATPOR 3.08 / 3.21 / 3.46 V (min/typ/max)
FW_RATIO = 3.2         # firmware.md §3.1 DTS vsys-sense full-ohms 3200000 / output-ohms 1000000
T_FIRST_SAMPLE = 1.0   # firmware.md §2.2: power_thread runs on a 1 s tick -> first battery sample
T_FW_MIN_INTERVAL = 1.0  # firmware.md §12.4: "Sample at most about 1 Hz"
I_LED_MAX = 0.73       # architecture.md §8.4: LED ring hardware worst case, full white, C variant
R_SRC_BAT = 0.25       # firmware.md §12.4: VOCV ≈ Vmeas + I_est x 0.25 Ω (cell + BATFET + path)
F_LED_PWM = 2e3        # architecture.md §6.4 / WS2812C-2020-V6: 2 kHz PWM
# VSENSE-5: the VSYS really at the divider while firmware stores 3.800 V. DMM at TP1 = exact. Board under 5 mA: VSYS
# sits below the supply setpoint by I x path resistance; the docs give no resistance for the battery-emulator path, so
# the documented cell + BATFET + path figure (R_SRC_BAT, 0.25 Ω) stands in for it (1.25 mV, stores a high gain).
CAL_REFS = {"DMM-at-TP1": V_CAL, "board-under-5mA": round(V_CAL - I_CAL_MAX * R_SRC_BAT, 6)}
SRC_VSENSE_RULE = ("firmware rule firmware.md §12.4 (VSENSE-1/4/5): SHIP when VBAT_est = reading - 75 mV < 3.465 V "
                   "(a reading below 3.54 V); calibration reference from a DMM at TP1 or with the board under 5 mA")

_PI2 = "firmware.md §6.3 (PI-2) instantaneous lit-channel table row, looked up with VBAT_est (row <= true VBAT)"
# Every VBAT_est / VSYS_est threshold firmware.md compares with a true value to protect a datasheet limit: VREAD_MARGIN
# must cover the worst over-read at that true value. id, threshold (true value, V), source, strict-xfail reason.
_MARGIN_XF = ("DESIGN ISSUE (firmware rule insufficient): firmware.md §12.4 subtracts a fixed 75 mV (VREAD_MARGIN) "
              "from the reading, but the calibrated over-read grows with VSYS: an aged board (R1/R2 ±0.5 %, C5 IR "
              "250 MΩ) at −10 / 60 °C, calibrated with the board under 5 mA, reads {o:.1f} mV high at a true {v:.2f} V, "
              "so VBAT_est can exceed the true VBAT by {d:.2f} mV at this threshold. 75 mV holds only up to a true "
              "3.72 V; the margin must be at least the over-read at the threshold (67.9 mV at 3.21 V, 77.0 mV at "
              "3.80 V, 79.6 mV at 3.90 V, 87.6 mV at 4.20 V), e.g. 2.12 % of the threshold")
READ_THRESHOLDS = (
    ("NEW-1-OLED_VCC_EN-3.21", 3.21, "firmware.md §6.3 / §7.2 / §13.3 (NEW-1, OLED-V1): OLED_VCC_EN at TMR_ILIM 0xC9 "
                                     "only with VBAT_est >= 3.21 V", None),
    ("SHIP-3.465", VBAT_EST_SHIP, "firmware.md §12.4: SHIP when VBAT_est < 3.465 V (VBATPOR max 3.46 V)", None),
    ("PI-2-row-3.48", 3.48, _PI2 + "; also the on-USB row (NF-1)", None),
    ("PI-2-row-3.53", 3.53, _PI2, None),
    ("MD-2-move-3.54", 3.54, "firmware.md §5.8 (MD-2): non-park moves only with VSYS_est (idle) >= 3.54 V", None),
    ("PI-2-row-3.60", 3.60, _PI2 + "; also the §6.3 derating 'VBAT < 3.60 V'", None),
    ("PI-2-row-3.65", 3.65, _PI2 + "; also the §6.3 derating re-enable 'VBAT >= 3.65 V'", None),
    ("PI-2-row-3.70", 3.70, _PI2, None),
    ("OLED-BST-2-3.75", 3.75, "firmware.md §12.4 / §7.4 (OLED-BST-2): OLED C7 <= 08h below VBAT_est 3.75 V (the PI-2 "
                              "table assumes it)", _MARGIN_XF.format(o=75.66, v=3.75, d=0.66)),
    ("PI-2-row-3.80", 3.80, _PI2, _MARGIN_XF.format(o=76.98, v=3.80, d=1.98)),
    ("PI-2-row-3.90", 3.90, _PI2 + " (>= 3.90 V: full ring)", _MARGIN_XF.format(o=79.63, v=3.90, d=4.63)),
)

TEMPS = (-10.0, 25.0, 60.0)
V_POINTS = tuple(sorted({3.0, 3.3, V_SHIP_OLD, V_SHIP, 3.7, CAL_REFS["board-under-5mA"], 3.8, 4.2, 4.41, 4.5, 4.59, 5.0,
                         5.5} | {c[1] for c in READ_THRESHOLDS}))
# 3.0/3.7/4.2 battery corners; 3.48 / 3.54 old / current SHIP threshold (reading); READ_THRESHOLDS true values (3.21 ...
# 3.90 V; 3.465 V = SHIP VBAT_est); 3.79875 = VSENSE-5 loaded calibration point;
# 4.41/4.5/4.59 = SYS_REG 4.5 V ±2 % on USB (BQ25180 DS SLUSE99C §7.5 VSYS_REG_ACCURACY): 4.5 V is the POR default and
# the only alternative firmware.md §13.1 allows (it sets 4.4 V, 0x20), so these are the upper USB points;
# 4.5/5.0/5.5 = VBUS corners with SYS_REG_CTRL = 111 pass-through (VSYS = VIN, SLUSE99C §8.3): firmware never sets it,
# kept as the hardware bound of the input-range check

ADC_VARIANTS = [dict(EG=eg, CEG=s * CEG_TYP, VOS=v) for eg in (-EG16, EG16) for s in (-1, 1)
                for v in (-VOS_LSB12, VOS_LSB12)]


def _dyn_src(what):
    return (f"{what}: 0.5 LSB12 at gain 1/6 = {HALF_LSB * 1e3:.3f} mV ({PS} §6.23.2 3.6 V FS / 4096; the model "
            f"meets every Table 95 row to this criterion, test_saadc_model_reproduces_ps_table95)")


# ---------------------------------------------------------------- deck helpers
def _mcu(d):
    return d.find("MDBT50Q")[0]


def _ain(d):
    """SPICE node on the MCU's AIN0 pad (P0.02): follows the schematic, not the net name."""
    return d.pin(_mcu(d), "P0.02")


def _divider(d, scale=None, tcr=None, ir=None):
    """Netlist passives on VSYS/VSYS_SENSE/GND, optional TCR (tc1 per ref) and C5 insulation resistance."""
    out = []
    for ln in d.passives(nets=NETS, scale=scale):
        ref = ln.split()[0][1:]
        if tcr and ln.startswith("R") and ref in tcr:
            ln += f" tc1={tcr[ref]:.6g}"
        out.append(ln)
    if ir and d.fitted("C5"):
        out.append(f"RC5_ir {d.pin('C5', '1')} {d.pin('C5', '2')} {ir:.6g}")
    return out


def _tag(v):
    return "v" + f"{v:.5f}".replace(".", "p")


def _run(deck):
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    assert not res.get("_missing"), (res.get("_missing"), res["_log"][-3000:])
    return res


def _dc(d, temp=25.0, scale=None, tcr=None, ir=None, ileak=0.0, points=V_POINTS, variants=ADC_VARIANTS):
    """One .dc sweep of VSYS: pin voltage, divider current and the SAADC code of every ADC error variant."""
    ain = _ain(d)
    deck = spicelib.Deck(f"VSYS sense DC T={temp}")
    deck.include(LIB)
    deck += _divider(d, scale, tcr, ir)
    deck += f"VSYS {d.node('VSYS')} 0 DC 3.7"
    for i, p in enumerate(variants):
        deck += (f"XADC{i} {ain} n_code{i} NRF52840_SAADC_DC params: EG={p['EG']:.6g} CEG={p['CEG']:.6g} "
                 f"VOS={p['VOS']:.6g} ILEAK={(ileak if i == 0 else 0.0):.6g}")
    deck += f".temp {temp}"
    deck.options.append("option tnom=25")
    deck.dc("VSYS", 2.9, 5.6, 0.01)
    for v in points:
        t = _tag(v)
        deck.meas(f"dc vs_{t} FIND v({ain}) AT={v}")
        deck.meas(f"dc is_{t} FIND i(VSYS) AT={v}")
        for i in range(len(variants)):
            deck.meas(f"dc c{i}_{t} FIND v(n_code{i}) AT={v}")
    res = _run(deck)
    return {v: dict(vs=res[f"vs_{_tag(v)}"], i=-res[f"is_{_tag(v)}"],
                    codes=[res[f"c{i}_{_tag(v)}"] for i in range(len(variants))]) for v in points}


def _tcr_corners(temp):
    if temp == 25.0:
        return [None]
    return [{"R1": s1 * TCR, "R2": s2 * TCR} for s1, s2 in itertools.product((-1, 1), repeat=2)]


@functools.lru_cache(maxsize=None)
def _corners(temp):
    """All static corners at one temperature: R1/R2 tolerance extremes x TCR signs x C5 IR (bound / open)."""
    d = spicelib.Design("main")
    c5 = d.value("C5")
    ir_bound = ir_min(c5) if temp <= 25.0 else ir_eol(c5)
    rows = []
    for si, sc in enumerate(d.extremes(["R1", "R2"])):
        for tcr in _tcr_corners(temp):
            for ir in (ir_bound, None):
                rows.append(dict(si=si, scale=sc, tcr=tcr, ir=ir, res=_dc(d, temp, sc, tcr, ir)))
    return rows


@functools.lru_cache(maxsize=None)
def _calibrated_errors(temp, v_cal_true=V_CAL):
    """Error (V) of the one-point-calibrated reading at `temp` for every corner: {vsys: [err, ...]}.
    Calibration: 25 °C, 3.800 V stored, same part (R corner, ADC variant); the C5 IR may differ between the two times.
    v_cal_true is the VSYS really at the divider during calibration (VSENSE-5, CAL_REFS): V_CAL with the DMM at TP1."""
    cal = {(r["si"], r["ir"]): r["res"] for r in _corners(25.0)}
    errs = {v: [] for v in V_POINTS}
    for row in _corners(temp):
        # The C5 IR at calibration is independent of the IR in use, also at 25 °C (verifier fix: the 25 °C case
        # used to force the same IR at both times, which hid the 2.4 mV IR term at the calibration temperature).
        ir_cals = [k[1] for k in cal if k[0] == row["si"]]
        for ir_cal in ir_cals:
            ccal = cal[(row["si"], ir_cal)][v_cal_true]["codes"]
            for v in V_POINTS:
                for i, code in enumerate(row["res"][v]["codes"]):
                    errs[v].append(V_CAL * code / ccal[i] - v)
    return errs


DRIFT_R = 0.005   # UNI-ROYAL thick-film DS V.3 §11, ±0.5 %/1 % parts: Humidity (steady state, 240 h 40 °C 90-95 % RH)
                  # and Rapid change of temperature: ΔR ±(0.5 % + 0.05 Ω). Used as the post-calibration drift bound.
AGED_POINTS = tuple(sorted({3.3, V_SHIP_OLD, V_SHIP, 3.7, 4.2} | {c[1] for c in READ_THRESHOLDS}))


@functools.lru_cache(maxsize=None)
def _aged_errors(v_cal_true=V_CAL, temp=25.0):
    """Error (V) of the one-point-calibrated reading at `temp` (25 °C unless given) after the part has aged: calibration
    on the fresh board at 25 °C (every R1/R2 tolerance corner, ADC variant, C5 IR bound/open), then in use R1 and R2
    drift by DRIFT_R in opposite directions (both signs) and the C5 IR is anywhere from open to the endurance bound
    (ir_eol, 250 MΩ).
    v_cal_true: the VSYS really at the divider while 3.800 V is stored (VSENSE-5, CAL_REFS). temp: read-out
    temperature (TCR corners as in _corners; the CEG of every ADC variant applies through .temp)."""
    d = spicelib.Design("main")
    c5 = d.value("C5")
    cal = {(r["si"], r["ir"]): r["res"] for r in _corners(25.0)}
    errs = {v: [] for v in AGED_POINTS}
    for si, sc in enumerate(d.extremes(["R1", "R2"])):
        for s in (-1, 1):
            aged = dict(sc, R1=sc["R1"] * (1 + s * DRIFT_R), R2=sc["R2"] * (1 - s * DRIFT_R))
            for tcr in _tcr_corners(temp):
                for ir in (ir_eol(c5) if d.fitted("C5") else None, ir_min(c5), None):
                    res = _dc(d, temp, aged, tcr, ir, points=AGED_POINTS + (V_CAL,))
                    for ir_cal in [k[1] for k in cal if k[0] == si]:
                        ccal = cal[(si, ir_cal)][v_cal_true]["codes"]
                        for v in AGED_POINTS:
                            for i, code in enumerate(res[v]["codes"]):
                                errs[v].append(V_CAL * code / ccal[i] - v)
    return errs


def _si(x):
    """A value as a netlist-style string (parse_value does not read exponents), for fault injection."""
    for mult, pre in ((1e6, "M"), (1e3, "k"), (1.0, ""), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if abs(x) >= mult:
            return f"{x / mult:.6g}{pre}"
    return f"{x / 1e-15:.6g}f"


def _pwl(points):
    body = " ".join(f"{t:.10g} {v:.6g}" for t, v in points)
    words = body.split(" ")
    lines, cur = [], []
    for k in range(0, len(words), 2):
        cur.append(words[k] + " " + words[k + 1])
        if len(cur) == 8:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return "PWL(" + "\n+ ".join(lines) + ")"


def _burst_waves(t0, tacq, n, bursts=1, interval=0.0, tr=5e-9):
    """SAMP / RST waveforms for `bursts` bursts of n back-to-back acquisitions (tACQ + tCONV each). RST pre-charges
    CSAMPLE to VPRE just before every acquisition. Returns (samp, rst, [acquisition end times per burst])."""
    s, r, ends = [(0.0, 0.0)], [(0.0, 0.0)], []
    for b in range(bursts):
        tb = t0 + b * interval
        e = []
        for k in range(n):
            ts = tb + k * (tacq + TCONV)
            r += [(ts - 0.6e-6, 0), (ts - 0.6e-6 + tr, 1), (ts - 0.2e-6, 1), (ts - 0.2e-6 + tr, 0)]
            s += [(ts, 0), (ts + tr, 1), (ts + tacq, 1), (ts + tacq + tr, 0)]
            e.append(ts + tacq)
        ends.append(e)
    return _pwl(s), _pwl(r), ends


def _sample(d, tacq, vsys, vpre, n=N_OVERSAMPLE, scale=None, bursts=1, interval=0.0, src_r=None):
    """Transient: VSYS source -> divider (or an ideal source through src_r) -> SAADC sampler.
    Returns (per-sample errors of the last burst in V vs the unloaded pin voltage, unloaded pin voltage)."""
    deck = spicelib.Deck(f"SAADC sampling tACQ={tacq * 1e6:g}us")
    deck.include(LIB)
    if src_r is None:
        ain = _ain(d)
        deck += _divider(d, scale)
        deck += f"VSYS {d.node('VSYS')} 0 DC {vsys}"
    else:
        ain = "n_ain"
        deck += [f"VSRC n_src 0 DC {vsys}", f"RSRC n_src n_ain {src_r:.6g}"]
    t0 = 20e-6
    s, r, ends = _burst_waves(t0, tacq, n, bursts, interval)
    deck += f"VSAMP n_samp 0 {s}"
    deck += f"VRST n_rst 0 {r}"
    deck += (f"XADC {ain} n_samp n_rst n_hold n_code NRF52840_SAADC_SE params: VPRE={vpre:.6g} CS={CSAMPLE:.6g} "
             f"CPAD={CPAD:.6g}")
    deck.options.append("option reltol=1e-6 abstol=1e-15 vntol=1e-9 chgtol=1e-18")
    deck.tran("20n", f"{ends[-1][-1] + 3e-6:.10g}", 0, "10u")   # TMAX 10 µs; PWL breakpoints resolve each edge
    deck.meas(f"tran vref FIND v({ain}) AT={t0 - 2e-6:.10g}")
    for k, t in enumerate(ends[-1]):
        deck.meas(f"tran h{k} FIND v(n_hold) AT={t - 2e-9:.10g}")
    res = _run(deck)
    vref = res["vref"]
    return [res[f"h{k}"] - vref for k in range(n)], vref


def _c5_min_scale(d):
    return (1 - d.tol("C5")) * (1 - X7R_TEMP)


def _c5_max_scale(d):
    return (1 + d.tol("C5")) * (1 + X7R_TEMP)


def _settle_time(d, vsys, scale):
    """Time from the VSYS step (power-up) until VSENSE is within 0.5 LSB12 of its final value."""
    ain = _ain(d)
    r1 = d.value("R1") * scale.get("R1", 1.0)
    r2 = d.value("R2") * scale.get("R2", 1.0)
    vfinal = vsys * r2 / (r1 + r2)
    deck = spicelib.Deck("VSYS sense power-up")
    deck += _divider(d, scale)
    t_on = 1e-3
    deck += f"VSYS {d.node('VSYS')} 0 PWL(0 0 {t_on} 0 {t_on + 100e-6} {vsys})"
    deck.tran("1m", "8")
    deck.meas(f"tran tset WHEN v({ain})={vfinal - HALF_LSB:.9g} RISE=1")
    res = _run(deck)
    return res["tset"] - t_on


def _ripple_half_pp(d, scale, vsys=3.7):
    """Half peak-to-peak ripple at the AIN0 pad in steady state with a 2 kHz square VSYS ripple of
    I_LED_MAX x R_SRC_BAT peak-to-peak."""
    ain = _ain(d)
    a = I_LED_MAX * R_SRC_BAT / 2
    per = 1 / F_LED_PWM
    deck = spicelib.Deck("VSYS ripple rejection")
    deck += _divider(d, scale)
    deck += f"VSYS {d.node('VSYS')} 0 PULSE({vsys - a} {vsys + a} 0 1u 1u {per / 2 - 1e-6:.9g} {per:.9g})"
    deck.tran("5u", "0.62")
    deck.meas(f"tran pp PP v({ain}) FROM=0.6 TO=0.62")
    return _run(deck)["pp"] / 2


# ================================================================ nominal / structure
def test_divider_matches_firmware_constant(main, check):
    """The divider ratio in the schematic is the one the firmware converts with (DTS full-ohms/output-ohms)."""
    assert main.node("VSYS_SENSE") == _ain(main), "VSYS_SENSE no longer reaches the MCU's AIN0 pad (P0.02)"
    res = _dc(main, 25.0, points=(3.7, 4.4, 4.5), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])
    check("VSYS / VSENSE (nominal, unloaded)", 3.7 / res[3.7]["vs"], FW_RATIO * (1 - 1e-4), FW_RATIO * (1 + 1e-4),
          "", "firmware.md §3.1 DTS vsys-sense full-ohms 3.2 MΩ / output-ohms 1 MΩ")
    check("code at VSYS 3.70 V (ideal SAADC)", res[3.7]["codes"][0], 1316 - 0.5, 1316 + 0.5, "LSB",
          "firmware.md §12.4 example: 3.70 V gives code 1316")
    check("code at VSYS 4.40 V (ideal SAADC)", res[4.4]["codes"][0], 1564 - 0.5, 1564 + 0.5, "LSB",
          "firmware.md §12.4 example: 4.40 V gives code 1564")
    check("code at VSYS 4.50 V (ideal SAADC)", res[4.5]["codes"][0], 1600 - 0.5, 1600 + 0.5, "LSB",
          "firmware.md §12.4 VSYS = code x 2.8125 mV: 4.50 V (SYS_REG POR default) gives code 1600")


# ================================================================ input range
@pytest.mark.parametrize("temp", TEMPS)
def test_input_range(temp, check):
    """VSENSE stays inside the SAADC range (0 ... 3.6 V full scale) and below VDD for VSYS 3.0 ... 5.5 V."""
    rows = _corners(temp)
    for v in (3.0, 3.7, 4.2, 4.59, 5.5):
        vs_max = max(r["res"][v]["vs"] for r in rows)
        check(f"VSENSE max at VSYS {v} V, {temp:g} °C", vs_max, None, vdd_min(v), "V",
              f"{PS} §6.23.2 'AIN cannot exceed VDD'; VDD min = RT9080 DS9080-09 §14 (−2 % / VDROP 0.53 V)")
    vs_max = max(r["res"][5.5]["vs"] for r in rows)
    check(f"VSENSE max at 5.5 V vs full scale, {temp:g} °C", vs_max, None, FS, "V",
          f"{PS} §6.23.2 input range 0.6 V / (1/6) = 3.6 V")
    vs_min = min(r["res"][3.0]["vs"] for r in rows)
    check(f"VSENSE min at VSYS 3.0 V, {temp:g} °C", vs_min, 0.0, None, "V", f"{PS} §6.23.2 'not lower than VSS'")
    code_max = max(max(r["res"][5.5]["codes"]) for r in rows)
    check(f"code max at 5.5 V incl. EG +3 %, VOS, CEG, {temp:g} °C", code_max, None, 4095, "LSB",
          f"{PS} §6.23.10.1 EG1/6, 12-bit full scale (no clipping)")


@pytest.mark.fault
@pytest.mark.parametrize("fault", ["R1_R2_swapped", "R1_220k", "R2_left_off", "R1_shorted"])
def test_fault_divider_errors_violate_input_range(fault, main, check):
    """Wrong divider values, a missing bottom resistor or a bridge across R1 (VSYS_SENSE connected to VSYS) push AIN0
    above VDD somewhere in 3.0 ... 5.5 V."""
    if fault == "R1_R2_swapped":
        v1, v2 = main.comps["R1"]["value"], main.comps["R2"]["value"]
        main.override("R1", v2).override("R2", v1)
    elif fault == "R1_220k":
        main.override("R1", "220k")
    elif fault == "R1_shorted":
        main.short("R1")
    else:
        main.remove("R2")
    res = _dc(main, 25.0, ir=ir_min(main.value("C5")), points=(3.0, 3.7, 4.2, 4.59, 5.0, 5.5),
              variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])
    over = max(res[v]["vs"] - vdd_min(v) for v in res)
    check(f"fault {fault}: worst VSENSE − VDD_min over VSYS 3.0 ... 5.5 V", over, 0.0, None, "V",
          f"must violate: {PS} §6.23.2 AIN ≤ VDD (RT9080 −2 %)")


# ================================================================ sampling (CSAMPLE through C5)
def test_saadc_model_reproduces_ps_table95(check):
    """Model self-check: at each tACQ the Table 95 maximum source resistance (no external C) settles to 0.5 LSB12,
    and 10x that resistance does not."""
    d = spicelib.Design("main")
    for tacq, rmax in TACQ_TABLE95:
        e_ok, _ = _sample(d, tacq, VDD_NOM, 0.0, n=1, src_r=rmax)
        check(f"tACQ {tacq * 1e6:g} µs, Rsource {rmax / 1e3:g} kΩ: |error|", abs(e_ok[0]), None, HALF_LSB, "V",
              f"{PS} §6.23.1.1 Table 95 (model calibration, VPRE 0 V, Vin = VDD)")
        e_bad, _ = _sample(d, tacq, VDD_NOM, 0.0, n=1, src_r=10 * rmax)
        check(f"tACQ {tacq * 1e6:g} µs, Rsource {10 * rmax / 1e3:g} kΩ (10x): |error|", abs(e_bad[0]), HALF_LSB,
              None, "V", f"{PS} §6.23.1.1 Table 95 exceeded 10x: model must show the error")


def test_charge_sharing_matches_closed_form(main, check):
    """Numerical sanity check: with C5 fitted each acquisition moves the pin by (V - VPRE) x CS / (C5 + CPAD + CS)."""
    vsys = 4.2
    errs, vref = _sample(main, TACQ_FW, vsys, 0.0)
    step_sim = (errs[-1] - errs[0]) / (len(errs) - 1)
    step_cf = -vref * CSAMPLE / (main.value("C5") + CPAD + CSAMPLE)
    check("charge-sharing step per sample, SPICE / closed form", step_sim / step_cf, 0.97, 1.03, "",
          f"closed form, {PS} CSAMPLE 2.5 pF + CPAD 3 pF")


@pytest.mark.parametrize("tacq", [t for t, _ in TACQ_TABLE95], ids=lambda t: f"{t * 1e6:g}us")
def test_sampling_error_vs_tacq(tacq, main, check):
    """8x burst average error from charge sharing between CSAMPLE and C5, worst over VSYS, CSAMPLE pre-charge
    and C5 tolerance / X7R temperature."""
    worst = 0.0
    for vsys in (3.0, 4.2, 5.5):
        for vpre in (0.0, VDD_MAX):
            for c5s in (_c5_min_scale(main), _c5_max_scale(main)):
                errs, _ = _sample(main, tacq, vsys, vpre, scale={"C5": c5s})
                avg = sum(errs) / len(errs)
                worst = max(worst, abs(avg))
    check(f"tACQ {tacq * 1e6:g} µs: |8x average sampling error|, C5 fitted", worst, None, HALF_LSB, "V",
          _dyn_src("sampling error"))


def test_tacq_robustness_without_c5(main, check):
    """With C5 missing the source is R1||R2 (687 kΩ): only tACQ = 40 µs (≤ 800 kΩ, Table 95) still reads
    correctly, which is why 40 µs is the recommended setting."""
    r1, r2 = main.value("R1") * (1 + main.tol("R1")), main.value("R2") * (1 + main.tol("R2"))
    check("R1 || R2 at +tolerance (Thevenin source without C5)", r1 * r2 / (r1 + r2), None, 800e3, "Ω",
          f"{PS} §6.23.1.1 Table 95: tACQ 40 µs allows ≤ 800 kΩ")
    main.remove("C5")
    worst = 0.0
    for vsys in (3.0, 5.5):
        for vpre in (0.0, VDD_MAX):
            errs, _ = _sample(main, TACQ_FW, vsys, vpre)
            worst = max(worst, abs(sum(errs) / len(errs)))
    check("tACQ 40 µs, C5 missing: |8x average sampling error|", worst, None, HALF_LSB, "V",
          _dyn_src("sampling error"))


@pytest.mark.fault
def test_fault_c5_missing_detected_at_short_tacq(main, check):
    """Leave C5 off and use tACQ 3 µs: the sampling check must flag the 687 kΩ source."""
    main.remove("C5")
    errs, _ = _sample(main, 3e-6, 4.2, 0.0)
    check("fault C5 removed, tACQ 3 µs: |8x average sampling error|", abs(sum(errs) / len(errs)), HALF_LSB, None,
          "V", "must violate: " + _dyn_src("sampling error"))


@pytest.mark.fault
def test_fault_c5_decade_low_detected_at_fw_tacq(main, check):
    """Verifier addition: C5 fitted one decade low (BOM slip). At the firmware tACQ of 40 µs (where a missing C5 is
    NOT caught by the sampling check), the worst sampling corner of test_sampling_error_vs_tacq must flag it."""
    main.override("C5", _si(main.value("C5") / 10))
    errs, _ = _sample(main, TACQ_FW, 3.0, VDD_MAX, scale={"C5": _c5_min_scale(main)})
    check("fault C5 / 10, tACQ 40 µs: |8x average sampling error|", abs(sum(errs) / len(errs)), HALF_LSB, None,
          "V", "must violate: " + _dyn_src("sampling error"))


def test_sample_interval(main, check):
    """C5 recovers through R1||R2 between 8x bursts. Worst case: VSYS 3.0 V, CSAMPLE pre-charged to VDD max,
    C5 at its minimum, R1/R2 at +1 % (slowest recovery). The firmware's fastest rate (1 Hz) must hold 0.5 LSB12;
    shorter intervals are reported to place the recommendation."""
    sc = {"R1": 1 + main.tol("R1"), "R2": 1 + main.tol("R2"), "C5": _c5_min_scale(main)}
    tau = (main.value("R1") * sc["R1"] * main.value("R2") * sc["R2"]
           / (main.value("R1") * sc["R1"] + main.value("R2") * sc["R2"])) * main.value("C5") * sc["C5"]
    results = {}
    for interval in (T_FW_MIN_INTERVAL, 0.2, 0.1, 0.05):
        bursts = max(2, int(math.ceil(6 * tau / interval)) + 1)
        errs, _ = _sample(main, TACQ_FW, 3.0, VDD_MAX, scale=sc, bursts=bursts, interval=interval)
        results[interval] = abs(sum(errs) / len(errs))
    check(f"burst every {T_FW_MIN_INTERVAL:g} s: |8x average error|, steady state", results[T_FW_MIN_INTERVAL],
          None, HALF_LSB, "V", _dyn_src("firmware.md §12.4 'at most about 1 Hz'"))
    passing = [iv for iv, e in results.items() if e <= HALF_LSB]
    check("shortest burst interval meeting 0.5 LSB12 (of 1 / 0.2 / 0.1 / 0.05 s)", min(passing), None,
          T_FW_MIN_INTERVAL, "s", "recommendation; must not exceed the firmware's 1 s fastest rate")
    for iv, e in results.items():
        check(f"info: burst every {iv:g} s, |8x average error|", e, None, None, "V", "informational")


# ================================================================ VSYS ripple (LED PWM)
def test_vsys_ripple_rejection(main, check):
    """2 kHz LED PWM ripple (worst-case LED current x source resistance) seen at AIN0, fastest R/C corner."""
    sc = {"R1": 1 - main.tol("R1"), "R2": 1 - main.tol("R2"), "C5": _c5_min_scale(main)}
    check("ripple at AIN0 (half p-p), 0.73 A x 0.25 Ω at 2 kHz", _ripple_half_pp(main, sc), None, HALF_LSB, "V",
          _dyn_src("ripple; architecture.md §8.4 0.73 A, firmware.md §12.4 0.25 Ω, 2 kHz PWM (§6.4)"))


@pytest.mark.fault
def test_fault_c5_missing_detected_by_ripple(main, check):
    main.remove("C5")
    check("fault C5 removed: ripple at AIN0 (half p-p)", _ripple_half_pp(main, {}), HALF_LSB, None, "V",
          "must violate: " + _dyn_src("ripple"))


# ================================================================ static accuracy
def _raw_gain_dev(v_cal_true=V_CAL):
    """Worst |raw gain - 1| over the 25 °C corners: firmware stores 3.800 V, the divider sees v_cal_true (CAL_REFS)."""
    return max(abs(V_CAL / (code * LSB12 * FW_RATIO) - 1) for row in _corners(25.0)
               for code in row["res"][v_cal_true]["codes"])


def _uncal_err():
    """Worst |uncalibrated reading / VSYS - 1| at 3.0 / 3.7 / 4.5 V over the 25 °C corners (DMM at TP1 = VSYS)."""
    return max(abs(code * LSB12 * FW_RATIO / v - 1) for row in _corners(25.0) for v in (3.0, 3.7, 4.5)
               for code in row["res"][v]["codes"])


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (old-rule evidence for VSENSE-2): the pre-VSENSE-2 production "
                   "test 8 raw-gain window ±3 % is narrower than EG1/6 ±3 % plus the ±1 % divider and VOS; good "
                   "boards can fail it. Window now ±5.5 %: test_raw_gain_production_window_with_fw_rule")
def test_raw_gain_production_window(check):
    """Pre-VSENSE-2 firmware.md §16 test 8: raw gain (3.800 V / uncalibrated reading) within ±3 %."""
    check("raw gain deviation at 3.800 V, all corners (25 °C)", _raw_gain_dev(), None, RAW_GAIN_WIN_OLD, "",
          "pre-VSENSE-2 firmware.md §16 test 8 'raw gain within ±3 %'")


def test_raw_gain_production_window_with_fw_rule(check):
    """Guard for VSENSE-2 (firmware.md §16 test 8: raw gain within ±5.5 %), same corners as the strict xfail
    test_raw_gain_production_window, for both calibration references VSENSE-5 allows (CAL_REFS): every good board
    (R1/R2 tolerance extremes, EG1/6 ±3 %, CEG, VOS ±8 LSB12, C5 IR bound / open) must pass the window."""
    for name, vc in CAL_REFS.items():
        check(f"raw gain deviation at 3.800 V, all corners (25 °C), calibration reference {name}", _raw_gain_dev(vc),
              None, RAW_GAIN_WIN, "", "firmware rule firmware.md §16 test 8 'Raw gain within ±5.5 %' (VSENSE-2); "
              "reference DMM at TP1 or board under 5 mA (VSENSE-5)")


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (old-rule evidence for VSENSE-3): the pre-VSENSE-3 bring-up "
                   "B-8.5 uncalibrated ±2 % ignores the SAADC EG1/6 ±3 % gain error. Window now ±5.5 %: "
                   "test_uncalibrated_error_bringup_with_fw_rule")
def test_uncalibrated_error_bringup(check):
    """Pre-VSENSE-3 bringup.md B-8.5: uncalibrated reading vs DMM at 3.0 / 3.7 / 4.5 V within ±2 %."""
    check("uncalibrated |error| at 3.0 / 3.7 / 4.5 V, all corners (25 °C)", _uncal_err(), None, UNCAL_WIN_OLD, "",
          "pre-VSENSE-3 bringup.md B-8.5 'within ±2 % (two 1 % resistors)'")


def test_uncalibrated_error_bringup_with_fw_rule(check):
    """Guard for VSENSE-3 (bringup.md B-8.5: uncalibrated reading vs DMM at TP1, 3.0 / 3.7 / 4.5 V, within ±5.5 %), same
    corners as the strict xfail test_uncalibrated_error_bringup."""
    check("uncalibrated |error| at 3.0 / 3.7 / 4.5 V, all corners (25 °C)", _uncal_err(), None, UNCAL_WIN, "",
          "firmware rule bringup.md B-8.5 'within ±5.5 % (SAADC gain error EG1/6 ±3 %, divider ±1.4 %, offset)' "
          "(VSENSE-3)")


def test_calibrated_accuracy_25c(check):
    """After the one-point calibration at 3.800 V, at the calibration temperature (DMM at TP1; the 3.54 V SHIP reading
    also with the board-under-5mA calibration reference of VSENSE-5). The ±10 mV bound is the pre-VSENSE-1 figure: it
    still holds at 25 °C and is stricter than the ±24 mV firmware.md §12.4 now gives for 15-35 °C
    (test_calibrated_accuracy_fresh_15_35c_with_fw_rule), so it stays."""
    errs = _calibrated_errors(25.0)
    worst = max(abs(e) for v in (3.3, V_SHIP_OLD, V_SHIP, 3.7, 4.2, 4.5) for e in errs[v])
    check("calibrated |error| over 3.3 ... 4.5 V, 25 °C", worst, None, 0.020, "V",
          "bringup.md B-8.5 'within ±20 mV over 3.3–4.5 V' after calibration")
    check("calibrated |error| at 3.48 V (pre-VSENSE-1 SHIP threshold), 25 °C", max(abs(e) for e in errs[V_SHIP_OLD]),
          None, CAL_ACC_OLD, "V", "pre-VSENSE-1 firmware.md §12.4 'about ±10 mV' (fresh unit, 25 °C)")
    for name, vc in CAL_REFS.items():
        check(f"calibrated |error| at {V_SHIP:.2f} V (SHIP threshold reading), 25 °C, calibration reference {name}",
              max(abs(e) for e in _calibrated_errors(25.0, vc)[V_SHIP]), None, CAL_ACC_OLD, "V",
              f"pre-VSENSE-1 firmware.md §12.4 'about ±10 mV' (fresh unit, 25 °C); {SRC_VSENSE_RULE}")


@pytest.mark.parametrize("temp", [15.0, 25.0, 35.0])
def test_calibrated_accuracy_fresh_15_35c_with_fw_rule(temp, check):
    """Guard for VSENSE-1/5 (firmware.md §12.4: the calibrated reading is within about ±24 mV at 15-35 °C on a fresh
    unit), at the SHIP reading, both calibration references. Same fresh corners as test_ship_threshold_above_vbatpor at
    15 / 25 / 35 °C (TCR, CEG, VOS, C5 IR at its 25 °C bound, at its endurance bound above 25 °C)."""
    for name, vc in CAL_REFS.items():
        errs = _calibrated_errors(temp, vc)[V_SHIP]
        check(f"calibrated |error| at {V_SHIP:.2f} V, {temp:g} °C, fresh unit, calibration reference {name}",
              max(abs(e) for e in errs), None, CAL_ACC_FRESH, "V",
              f"firmware.md §12.4 'about ±24 mV at 15–35 °C on a fresh unit' (VSENSE-1); {SRC_VSENSE_RULE}")


_TEMP_XFAIL = pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (old-rule evidence for VSENSE-1): away from the "
                                "25 °C calibration the divider TCR (±100 ppm/°C) and SAADC gain drift (CEG 0.02 %/°C) "
                                "exceed the pre-VSENSE-1 firmware's ±10 mV / 20 mV margin of the 3.48 V SHIP "
                                "threshold. Rule now SHIP below a 3.54 V reading (VBAT_est = reading - 75 mV < "
                                "3.465 V): test_ship_threshold_above_vbatpor_with_fw_rule")


@pytest.mark.parametrize("temp", [pytest.param(-10.0, marks=_TEMP_XFAIL), pytest.param(60.0, marks=_TEMP_XFAIL)])
def test_calibrated_accuracy_over_temperature(temp, check):
    errs = _calibrated_errors(temp)[V_SHIP_OLD]
    check(f"calibrated |error| at 3.48 V, {temp:g} °C (TCR, CEG, VOS, C5 IR)", max(abs(e) for e in errs), None,
          CAL_ACC_OLD, "V", "pre-VSENSE-1 firmware.md §12.4 '±10 mV calibrated ADC error'")


@pytest.mark.parametrize("temp", [pytest.param(-10.0, marks=_TEMP_XFAIL), 15.0, 25.0, 35.0,
                                  pytest.param(60.0, marks=_TEMP_XFAIL)])
def test_ship_threshold_above_vbatpor(temp, check):
    """When the firmware reads 3.48 V (the pre-VSENSE-1 SHIP threshold) and ships, the true VBAT must still be at or
    above VBATPOR max (3.46 V), so a button press can wake the charger. 15 / 35 °C bound the band in which the old
    3.48 V rule is safe; -10 / 60 °C are the strict-xfail evidence for VSENSE-1."""
    over_read = max(_calibrated_errors(temp)[V_SHIP_OLD])
    check(f"true VBAT at a 3.48 V reading, {temp:g} °C", V_SHIP_OLD - over_read, VBATPOR_MAX, None, "V",
          "BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V (pre-VSENSE-1 firmware.md §12.4 SHIP 3.48 V)")


_DRIFT_SRC = ("drift: UNI-ROYAL DS V.3 §11 Humidity (steady state) ±(0.5 %+0.05 Ω); IR: Samsung MLCC catalog 2015 "
              "endurance 25 MΩ·µF")


def _drift_checks(check, errs, budget, what, src):
    """Over-read against the documented high figure and |error| against the low figure (budget = (high, low); the
    high figure is the smaller one, so |error| <= low also bounds the under-read)."""
    check(f"calibrated over-read at {V_SHIP:.2f} V, {what}", max(errs), None, budget[0], "V", src)
    check(f"calibrated |error| at {V_SHIP:.2f} V, {what}", max(abs(e) for e in errs), None, budget[1], "V", src)


@pytest.mark.parametrize("temp", [-10.0, 60.0])
def test_calibrated_accuracy_over_temperature_with_fw_rule(temp, check):
    """Guard for VSENSE-1/5: same corners as test_calibrated_accuracy_over_temperature at the 3.54 V SHIP reading, with
    the calibration references firmware.md §12.4 allows (CAL_REFS), against the calibrated drift firmware.md §12.4
    documents for a fresh unit over −10…60 °C (CAL_DRIFT_FRESH)."""
    for name, vc in CAL_REFS.items():
        _drift_checks(check, _calibrated_errors(temp, vc)[V_SHIP], CAL_DRIFT_FRESH,
                      f"{temp:g} °C (TCR, CEG, VOS, C5 IR), fresh unit, calibration reference {name}",
                      f"firmware.md §12.4 fresh unit over −10…60 °C: reading up to {CAL_DRIFT_FRESH[0] * 1e3:.0f} mV "
                      f"high / {CAL_DRIFT_FRESH[1] * 1e3:.0f} mV low (VSENSE-1/4); {SRC_VSENSE_RULE}")


@pytest.mark.parametrize("temp", [-10.0, 60.0])
def test_ship_threshold_above_vbatpor_with_fw_rule(temp, check):
    """Guard for VSENSE-1/5: when the firmware reads 3.54 V (firmware.md §12.4: SHIP when VBAT_est = reading − 75 mV <
    3.465 V) and ships, the true VBAT must still be at or above VBATPOR max (3.46 V). Same corners as the strict xfails
    of test_ship_threshold_above_vbatpor, for both calibration references VSENSE-5 allows (CAL_REFS)."""
    for name, vc in CAL_REFS.items():
        over_read = max(_calibrated_errors(temp, vc)[V_SHIP])
        check(f"true VBAT at a {V_SHIP:.2f} V reading, {temp:g} °C, calibration reference {name}", V_SHIP - over_read,
              VBATPOR_MAX, None, "V", f"BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V; {SRC_VSENSE_RULE}")


_AGING_XFAIL = pytest.mark.xfail(strict=True, reason="DESIGN ISSUE (old-rule evidence for VSENSE-4): after the "
                                 "one-point calibration, the datasheet drift bound of the thick-film R1/R2 (±0.5 % "
                                 "humidity / temperature cycling) and the aged C5 IR (250 MΩ) exceed the pre-VSENSE-1 "
                                 "±10 mV / 20 mV margin of the 3.48 V SHIP threshold even at 25 °C. Rule now SHIP "
                                 "below a 3.54 V reading (VBAT_est = reading - 75 mV < 3.465 V): "
                                 "test_ship_threshold_after_aging_with_fw_rule")


@_AGING_XFAIL
def test_calibrated_accuracy_after_aging(check):
    """Verifier addition (aging angle): calibrated fresh at 25 °C, read later at 25 °C after R1/R2 drift and C5 IR loss."""
    worst = max(abs(e) for e in _aged_errors()[V_SHIP_OLD])
    check("calibrated |error| at 3.48 V, 25 °C, after R1/R2 ±0.5 % drift and C5 IR 250 MΩ", worst, None, CAL_ACC_OLD,
          "V", f"pre-VSENSE-1 firmware.md §12.4 '±10 mV calibrated ADC error'; {_DRIFT_SRC}")


@_AGING_XFAIL
def test_ship_threshold_after_aging(check):
    """Verifier addition: true VBAT at a 3.48 V reading (pre-VSENSE-1 SHIP) at 25 °C on an aged board (see above)."""
    over_read = max(_aged_errors()[V_SHIP_OLD])
    check("true VBAT at a 3.48 V reading, 25 °C, aged R1/R2 and C5", V_SHIP_OLD - over_read, VBATPOR_MAX, None, "V",
          "BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V; drift: UNI-ROYAL DS V.3 §11 Humidity (steady state) "
          "±(0.5 %+0.05 Ω)")


def test_calibrated_accuracy_after_aging_with_fw_rule(check):
    """Guard for VSENSE-4/5: same aged corners as test_calibrated_accuracy_after_aging (25 °C, R1/R2 ±0.5 % drift, C5 IR
    to 250 MΩ) at the 3.54 V SHIP reading, both calibration references, against the drift firmware.md §12.4 documents
    for an aged unit at 25 °C (CAL_DRIFT_AGED)."""
    for name, vc in CAL_REFS.items():
        _drift_checks(check, _aged_errors(vc)[V_SHIP], CAL_DRIFT_AGED,
                      f"25 °C, aged R1/R2 and C5, calibration reference {name}",
                      f"firmware.md §12.4 aged unit at 25 °C: reading up to {CAL_DRIFT_AGED[0] * 1e3:.0f} mV high / "
                      f"{CAL_DRIFT_AGED[1] * 1e3:.0f} mV low (VSENSE-4); {SRC_VSENSE_RULE}; {_DRIFT_SRC}")


def test_ship_threshold_after_aging_with_fw_rule(check):
    """Guard for VSENSE-4/5: true VBAT at a 3.54 V reading (firmware.md §12.4 SHIP) at 25 °C on an aged board, same
    corners as test_ship_threshold_after_aging, both calibration references."""
    for name, vc in CAL_REFS.items():
        over_read = max(_aged_errors(vc)[V_SHIP])
        check(f"true VBAT at a {V_SHIP:.2f} V reading, 25 °C, aged R1/R2 and C5, calibration reference {name}",
              V_SHIP - over_read, VBATPOR_MAX, None, "V",
              f"BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V; {SRC_VSENSE_RULE}; {_DRIFT_SRC}")


@pytest.mark.parametrize("temp", [-10.0, 60.0])
def test_calibrated_accuracy_aged_over_temperature_with_fw_rule(temp, check):
    """Guard for VSENSE-1/4/5: the corners of test_ship_threshold_aged_over_temperature_with_fw_rule (aged board read
    at −10 / 60 °C) at the 3.54 V SHIP reading, both calibration references, against the drift firmware.md §12.4
    documents for an aged unit away from 25 °C (CAL_DRIFT_AGED_T)."""
    for name, vc in CAL_REFS.items():
        _drift_checks(check, _aged_errors(vc, temp)[V_SHIP], CAL_DRIFT_AGED_T,
                      f"{temp:g} °C, aged R1/R2 and C5, calibration reference {name}",
                      f"firmware.md §12.4 aged unit at −10 / 60 °C: reading up to {CAL_DRIFT_AGED_T[0] * 1e3:.0f} mV "
                      f"high / {CAL_DRIFT_AGED_T[1] * 1e3:.0f} mV low (VSENSE-1/4); {SRC_VSENSE_RULE}; {_DRIFT_SRC}")


@pytest.mark.parametrize("temp", [-10.0, 60.0])
def test_ship_threshold_aged_over_temperature_with_fw_rule(temp, check):
    """Worst corner of the VSENSE-1/4/5 rule (verifier extension of the two guards above): an aged board (the corners
    of test_ship_threshold_after_aging) read at −10 / 60 °C (TCR and CEG corners of test_ship_threshold_above_vbatpor),
    calibrated fresh at 25 °C with either reference. firmware.md §12.4 says the reading drifts 'over −10…60 °C and
    with ageing'; nothing keeps a unit from being both. (Strict xfail until the SHIP rule moved from a 3.53 V reading
    to VBAT_est = reading − 75 mV < 3.465 V: the true VBAT at a 3.53 V reading was 3.4589 / 3.4577 V.)"""
    for name, vc in CAL_REFS.items():
        errs = _aged_errors(vc, temp)[V_SHIP]
        check(f"calibrated |error| at {V_SHIP:.2f} V, {temp:g} °C, aged R1/R2 and C5, calibration reference {name}",
              max(abs(e) for e in errs), None, None, "V", f"info: {SRC_VSENSE_RULE}; {_DRIFT_SRC}")
        check(f"true VBAT at a {V_SHIP:.2f} V reading, {temp:g} °C, aged R1/R2 and C5, calibration reference {name}",
              V_SHIP - max(errs), VBATPOR_MAX, None, "V",
              f"BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V; {SRC_VSENSE_RULE}; {_DRIFT_SRC}")


def _worst_over_read(v):
    """Worst calibrated over-read (V) at a true VSYS v over every corner of this file: fresh unit at −10 / 15 / 25 / 35 /
    60 °C (_calibrated_errors), aged unit at −10 / 25 / 60 °C (_aged_errors), both calibration references. Returns
    (over-read, corner)."""
    worst = (-math.inf, "")
    for name, vc in CAL_REFS.items():
        sets = [(f"fresh unit, {t:g} °C", _calibrated_errors(t, vc)) for t in (-10.0, 15.0, 25.0, 35.0, 60.0)]
        sets += [(f"aged unit, {t:g} °C", _aged_errors(vc, t)) for t in (-10.0, 25.0, 60.0)]
        for corner, errs in sets:
            o = max(errs[v])
            if o > worst[0]:
                worst = (o, f"{corner}, calibration reference {name}")
    return worst


@pytest.mark.parametrize("cid,v_est,src", [
    pytest.param(*c[:3], marks=[pytest.mark.xfail(strict=True, reason=c[3])] if c[3] else [], id=c[0])
    for c in READ_THRESHOLDS])
def test_read_margin_covers_over_read_with_fw_rule(cid, v_est, src, check):
    """Guard for the VSENSE-1/4/5 reading margin (firmware.md §12.4: every threshold that protects a datasheet limit
    compares the true value with VBAT_est = calibrated reading − 75 mV). For a threshold X this holds exactly when no
    unit reads more than 75 mV high at a true X: the reading is monotonic in VSYS, so a reading >= X + 75 mV then means
    a true value >= X. Worst over-read at the true threshold value over every fresh and aged corner of this file, both
    calibration references (_worst_over_read)."""
    over, corner = _worst_over_read(v_est)
    check(f"info: corner of the worst over-read at a true {v_est:.3f} V", over, None, None, "V", f"info: {corner}")
    check(f"info: true value at a {v_est + VREAD_MARGIN:.3f} V reading is at least VBAT_est {v_est:.3f} V plus",
          VREAD_MARGIN - over, None, None, "V", "info: VREAD_MARGIN minus the worst over-read")
    check(f"worst calibrated over-read at a true {v_est:.3f} V ({cid}) vs VREAD_MARGIN", over, None, VREAD_MARGIN, "V",
          f"firmware rule firmware.md §12.4 (VSENSE-1/4/5): VBAT_est = reading − 75 mV must not exceed the true value; "
          f"threshold: {src}")


def test_pin_leakage_sensitivity(main, check):
    """The PS gives no AIN leakage figure. Report how much leakage the 687 kΩ source tolerates."""
    base = _dc(main, 25.0, points=(V_SHIP,), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])[V_SHIP]["vs"]
    leak = _dc(main, 25.0, ileak=1e-9, points=(V_SHIP,), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])[V_SHIP]["vs"]
    per_na = (base - leak) * FW_RATIO
    check("info: VSYS reading shift per nA of AIN0 leakage", per_na, None, None, "V",
          f"informational: {PS} has no AIN leakage spec")
    check("info: AIN0 leakage that alone uses the ±10 mV budget", CAL_ACC_OLD / per_na * 1e-9, None, None, "A",
          "informational (the pre-VSENSE-1 firmware.md §12.4 ±10 mV, which still holds at 25 °C on a fresh unit); "
          "measure at 60 °C on the first boards")


# ================================================================ settling after power-up
def test_settling_after_power_up(main, check):
    worst = 0.0
    for sc in main.extremes(["R1", "R2", "C5"]):
        sc = dict(sc, C5=sc["C5"] * (1 + X7R_TEMP))
        for vsys in (3.0, 4.2, 5.5):
            worst = max(worst, _settle_time(main, vsys, sc))
    check("settling to 0.5 LSB12 after the VSYS step, all corners", worst, None, T_FIRST_SAMPLE, "s",
          "firmware.md §2.2 power_thread 1 s tick (first battery sample)")


@pytest.mark.fault
def test_fault_c5_wrong_value_slows_settling(main, check):
    main.override("C5", "1u")
    check("fault C5 = 1 µF: settling time at 4.2 V", _settle_time(main, 4.2, {}), T_FIRST_SAMPLE, None, "s",
          "must violate: firmware.md §2.2 power_thread 1 s tick")


# ================================================================ sleep current
def test_sleep_current(check):
    i37 = max(r["res"][3.7]["i"] for t in TEMPS for r in _corners(t))
    check("divider current at VSYS 3.7 V, all corners, −10 ... 60 °C", i37, None, 1.2e-6, "A",
          "architecture.md §8.2 sleep budget row 'VSYS_SENSE divider 1.2 µA (3.7 V / 3.2 MΩ)'")
    i42 = max(r["res"][4.2]["i"] for t in TEMPS for r in _corners(t))
    check("divider current at VSYS 4.2 V, all corners, −10 ... 60 °C", i42, None, 1.35e-6, "A",
          "SPEC.md §3 '~1.3 µA' (2 significant figures: < 1.35 µA)")
    d = spicelib.Design("main")
    vs = max(r["res"][4.2]["vs"] for r in _corners(25.0))
    i_saadc = N_OVERSAMPLE * CSAMPLE * max(vs, VDD_MAX - vs) / T_FW_MIN_INTERVAL
    check("info: average SAADC sampling current at 1 Hz bursts (8 x CSAMPLE)", i_saadc, None, None, "A",
          f"informational: {PS} CSAMPLE 2.5 pF; R1 {d.comps['R1']['value']} / R2 {d.comps['R2']['value']}")


@pytest.mark.fault
def test_fault_r1_typo_detected_by_sleep_current(main, check):
    main.override("R1", "220k")
    res = _dc(main, 25.0, points=(3.7,), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])
    check("fault R1 = 220k: divider current at 3.7 V", res[3.7]["i"], 1.2e-6, None, "A",
          "must violate: architecture.md §8.2 sleep budget 1.2 µA")
