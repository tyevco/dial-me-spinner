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
                    (also 15/35 °C, the band where the 3.48 V rule holds), AIN leakage sensitivity
  * aging           (verifier) calibrated reading and SHIP rule at 25 °C after R1/R2 datasheet drift (±0.5 %) and
                    C5 IR loss to its endurance bound
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
V_SHIP = 3.48          # firmware.md §12.4: SHIP entry below 3.48 V
VBATPOR_MAX = 3.46     # BQ25180 DS SLUSE99C §7.5 VBATPOR 3.08 / 3.21 / 3.46 V (min/typ/max)
FW_RATIO = 3.2         # firmware.md §3.1 DTS vsys-sense full-ohms 3200000 / output-ohms 1000000
T_FIRST_SAMPLE = 1.0   # firmware.md §2.2: power_thread runs on a 1 s tick -> first battery sample
T_FW_MIN_INTERVAL = 1.0  # firmware.md §12.4: "Sample at most about 1 Hz"
I_LED_MAX = 0.73       # architecture.md §8.4: LED ring hardware worst case, full white, C variant
R_SRC_BAT = 0.25       # firmware.md §12.4: VOCV ≈ Vmeas + I_est x 0.25 Ω (cell + BATFET + path)
F_LED_PWM = 2e3        # architecture.md §6.4 / WS2812C-2020-V6: 2 kHz PWM

TEMPS = (-10.0, 25.0, 60.0)
V_POINTS = (3.0, 3.3, 3.48, 3.7, 3.8, 4.2, 4.41, 4.5, 4.59, 5.0, 5.5)
# 3.0/3.7/4.2 battery corners; 4.41/4.5/4.59 = SYS_REG 4.5 V ±2 % on USB (BQ25180 DS SLUSE99C §7.5 VSYS_REG_ACCURACY);
# 4.5/5.0/5.5 = VBUS corners with SYS_REG_CTRL = 111 pass-through (VSYS = VIN, SLUSE99C §8.3)

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
    return "v" + f"{v:.2f}".replace(".", "p")


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
def _calibrated_errors(temp):
    """Error (V) of the one-point-calibrated reading at `temp` for every corner: {vsys: [err, ...]}.
    Calibration: 25 °C, 3.800 V, same part (R corner, ADC variant); the C5 IR may differ between the two times."""
    cal = {(r["si"], r["ir"]): r["res"] for r in _corners(25.0)}
    errs = {v: [] for v in V_POINTS}
    for row in _corners(temp):
        # The C5 IR at calibration is independent of the IR in use, also at 25 °C (verifier fix: the 25 °C case
        # used to force the same IR at both times, which hid the 2.4 mV IR term at the calibration temperature).
        ir_cals = [k[1] for k in cal if k[0] == row["si"]]
        for ir_cal in ir_cals:
            ccal = cal[(row["si"], ir_cal)][V_CAL]["codes"]
            for v in V_POINTS:
                for i, code in enumerate(row["res"][v]["codes"]):
                    errs[v].append(V_CAL * code / ccal[i] - v)
    return errs


DRIFT_R = 0.005   # UNI-ROYAL thick-film DS V.3 §11, ±0.5 %/1 % parts: Humidity (steady state, 240 h 40 °C 90-95 % RH)
                  # and Rapid change of temperature: ΔR ±(0.5 % + 0.05 Ω). Used as the post-calibration drift bound.
AGED_POINTS = (3.3, V_SHIP, 3.7, 4.2)


@functools.lru_cache(maxsize=None)
def _aged_errors():
    """Error (V) of the one-point-calibrated reading at 25 °C after the part has aged: calibration on the fresh board
    (every R1/R2 tolerance corner, ADC variant, C5 IR bound/open), then in use R1 and R2 drift by DRIFT_R in opposite
    directions (both signs) and the C5 IR is anywhere from open to the endurance bound (ir_eol, 250 MΩ)."""
    d = spicelib.Design("main")
    c5 = d.value("C5")
    cal = {(r["si"], r["ir"]): r["res"] for r in _corners(25.0)}
    errs = {v: [] for v in AGED_POINTS}
    for si, sc in enumerate(d.extremes(["R1", "R2"])):
        for s in (-1, 1):
            aged = dict(sc, R1=sc["R1"] * (1 + s * DRIFT_R), R2=sc["R2"] * (1 - s * DRIFT_R))
            for ir in (ir_eol(c5) if d.fitted("C5") else None, ir_min(c5), None):
                res = _dc(d, 25.0, aged, None, ir, points=AGED_POINTS + (V_CAL,))
                for ir_cal in [k[1] for k in cal if k[0] == si]:
                    ccal = cal[(si, ir_cal)][V_CAL]["codes"]
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
    res = _dc(main, 25.0, points=(3.7, 4.5), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])
    check("VSYS / VSENSE (nominal, unloaded)", 3.7 / res[3.7]["vs"], FW_RATIO * (1 - 1e-4), FW_RATIO * (1 + 1e-4),
          "", "firmware.md §3.1 DTS vsys-sense full-ohms 3.2 MΩ / output-ohms 1 MΩ")
    check("code at VSYS 3.70 V (ideal SAADC)", res[3.7]["codes"][0], 1316 - 0.5, 1316 + 0.5, "LSB",
          "firmware.md §12.4 example: 3.70 V gives code 1316")
    check("code at VSYS 4.50 V (ideal SAADC)", res[4.5]["codes"][0], 1600 - 0.5, 1600 + 0.5, "LSB",
          "firmware.md §12.4 example: 4.50 V gives code 1600")


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
@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: production test 8 raw-gain window ±3 % is narrower than "
                   "EG1/6 ±3 % plus the ±1 % divider and VOS; good boards can fail it")
def test_raw_gain_production_window(check):
    """firmware.md §16 test 8: raw gain (3.800 V / uncalibrated reading) within ±3 %."""
    dev = 0.0
    for row in _corners(25.0):
        for code in row["res"][V_CAL]["codes"]:
            dev = max(dev, abs(V_CAL / (code * LSB12 * FW_RATIO) - 1))
    check("raw gain deviation at 3.800 V, all corners (25 °C)", dev, None, 0.03, "",
          "firmware.md §16 test 8 'raw gain within ±3 %'")


@pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: bring-up B-8.5 uncalibrated ±2 % ignores the SAADC "
                   "EG1/6 ±3 % gain error")
def test_uncalibrated_error_bringup(check):
    """bringup.md B-8.5: uncalibrated reading vs DMM at 3.0 / 3.7 / 4.5 V within ±2 %."""
    worst = 0.0
    for row in _corners(25.0):
        for v in (3.0, 3.7, 4.5):
            for code in row["res"][v]["codes"]:
                worst = max(worst, abs(code * LSB12 * FW_RATIO / v - 1))
    check("uncalibrated |error| at 3.0 / 3.7 / 4.5 V, all corners (25 °C)", worst, None, 0.02, "",
          "bringup.md B-8.5 'within ±2 % (two 1 % resistors)'")


def test_calibrated_accuracy_25c(check):
    """After the one-point calibration at 3.800 V, at the calibration temperature."""
    errs = _calibrated_errors(25.0)
    worst = max(abs(e) for v in (3.3, 3.48, 3.7, 4.2, 4.5) for e in errs[v])
    check("calibrated |error| over 3.3 ... 4.5 V, 25 °C", worst, None, 0.020, "V",
          "bringup.md B-8.5 'within ±20 mV over 3.3–4.5 V' after calibration")
    check("calibrated |error| at 3.48 V (SHIP threshold), 25 °C", max(abs(e) for e in errs[V_SHIP]), None, 0.010,
          "V", "firmware.md §12.4 '±10 mV calibrated ADC error'")


_TEMP_XFAIL = pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: away from the 25 °C calibration the divider "
                                "TCR (±100 ppm/°C) and SAADC gain drift (CEG 0.02 %/°C) exceed the firmware's "
                                "±10 mV / 20 mV SHIP margin")


@pytest.mark.parametrize("temp", [pytest.param(-10.0, marks=_TEMP_XFAIL), pytest.param(60.0, marks=_TEMP_XFAIL)])
def test_calibrated_accuracy_over_temperature(temp, check):
    errs = _calibrated_errors(temp)[V_SHIP]
    check(f"calibrated |error| at 3.48 V, {temp:g} °C (TCR, CEG, VOS, C5 IR)", max(abs(e) for e in errs), None, 0.010,
          "V", "firmware.md §12.4 '±10 mV calibrated ADC error'")


@pytest.mark.parametrize("temp", [pytest.param(-10.0, marks=_TEMP_XFAIL), 15.0, 25.0, 35.0,
                                  pytest.param(60.0, marks=_TEMP_XFAIL)])
def test_ship_threshold_above_vbatpor(temp, check):
    """When the firmware reads 3.48 V and ships, the true VBAT must still be at or above VBATPOR max (3.46 V),
    so a button press can wake the charger. 15 / 35 °C bound the band in which the 3.48 V rule is safe."""
    over_read = max(_calibrated_errors(temp)[V_SHIP])
    check(f"true VBAT at a 3.48 V reading, {temp:g} °C", V_SHIP - over_read, VBATPOR_MAX, None, "V",
          "BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V (firmware.md §12.4 SHIP rule)")


_AGING_XFAIL = pytest.mark.xfail(strict=True, reason="DESIGN ISSUE: after the one-point calibration, the "
                                 "datasheet drift bound of the thick-film R1/R2 (±0.5 % humidity / temperature "
                                 "cycling) and the aged C5 IR (250 MΩ) exceed the ±10 mV / 20 mV SHIP margin even "
                                 "at 25 °C")


@_AGING_XFAIL
def test_calibrated_accuracy_after_aging(check):
    """Verifier addition (aging angle): calibrated fresh at 25 °C, read later at 25 °C after R1/R2 drift and C5 IR loss."""
    worst = max(abs(e) for e in _aged_errors()[V_SHIP])
    check("calibrated |error| at 3.48 V, 25 °C, after R1/R2 ±0.5 % drift and C5 IR 250 MΩ", worst, None, 0.010, "V",
          "firmware.md §12.4 '±10 mV calibrated ADC error'; drift: UNI-ROYAL DS V.3 §11 Humidity (steady state) "
          "±(0.5 %+0.05 Ω); IR: Samsung MLCC catalog 2015 endurance 25 MΩ·µF")


@_AGING_XFAIL
def test_ship_threshold_after_aging(check):
    """Verifier addition: true VBAT at a 3.48 V reading at 25 °C on an aged board (see test above)."""
    over_read = max(_aged_errors()[V_SHIP])
    check("true VBAT at a 3.48 V reading, 25 °C, aged R1/R2 and C5", V_SHIP - over_read, VBATPOR_MAX, None, "V",
          "BQ25180 DS SLUSE99C §7.5 VBATPOR max 3.46 V; drift: UNI-ROYAL DS V.3 §11 Humidity (steady state) "
          "±(0.5 %+0.05 Ω)")


def test_pin_leakage_sensitivity(main, check):
    """The PS gives no AIN leakage figure. Report how much leakage the 687 kΩ source tolerates."""
    base = _dc(main, 25.0, points=(V_SHIP,), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])[V_SHIP]["vs"]
    leak = _dc(main, 25.0, ileak=1e-9, points=(V_SHIP,), variants=[dict(EG=0.0, CEG=0.0, VOS=0.0)])[V_SHIP]["vs"]
    per_na = (base - leak) * FW_RATIO
    check("info: VSYS reading shift per nA of AIN0 leakage", per_na, None, None, "V",
          f"informational: {PS} has no AIN leakage spec")
    check("info: AIN0 leakage that alone uses the ±10 mV budget", 0.010 / per_na * 1e-9, None, None, "A",
          "informational (firmware.md §12.4 ±10 mV); measure at 60 °C on the first boards")


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
