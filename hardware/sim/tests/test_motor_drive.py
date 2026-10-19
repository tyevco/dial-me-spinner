"""Detent actuator drive: 2x DRV8837 (U40/U41) + micro linear stepper on J40, and the DRV5032 home switch (U42).

Netlist-driven: every passive comes from hardware/kicad/{main,base} (main VSYS: C1 C2 C6 C41 C70 C72 C74,
+3V3: C71 C73 C75 and the rest of the rail, MOT_NSLEEP: R70; base VSYS: C2 C4, VBAT: C3). The DRV8837 /
U41 pins, J40 coil pairs and the nRF pins come from the netlist too, so a pin or value change in the
schematic shows up here.

Supply path, end to end:   cell (VBAT_ocv) + pack resistance -> BQ25180 power path (U1, base) -> base VSYS
caps -> 12-way link (2 VSYS + 3 GND wires, 28 AWG, 80 mm, JST SH contacts) -> main VSYS caps -> DRV8837 VM.

Models (hardware/sim/models): motor_drive__drv8837.lib, motor_drive__stepper.lib, motor_drive__bq25180.lib,
motor_drive__nrf52840_gpio.lib, motor_drive__drv5032.lib. Each one lists its datasheet and what it leaves out.

Drive patterns:
  * full step, two phases on (AB -> A'B -> A'B' -> AB'), 100 % duty: 80 / 313 / 446 PPS (firmware.md §5.3 speed
    plan) plus the stall (rotor blocked, no back-EMF) and hold (DC) cases;
  * the firmware's real drive (firmware.md §5.3): 8-µstep sine, 25 kHz PWM, slow decay, amplitude
    d = 160 mA x (20 Ohm x (1 + 0.00393 x (T - 25 C)) + 0.33 Ohm) / VSYS (MD-3). The pre-MD-3 fixed
    d = 160 mA x 20.3 Ohm / VSYS stays in the cases that pass with it (it is the higher duty below 25 C, so the
    conservative one for the coast peak) and in the 60 C strict xfail that is the evidence for MD-3.

Firmware rules guarded here (each strict xfail keeps the old value as evidence, a *_with_fw_rule test or the named
case applies the rule): MD-2 non-park moves only from >= 3.55 V measured idle VSYS (also with the calibrated reading
as far off as firmware.md §12.4 allows); MD-3 temperature-compensated duty; MD-1 brake (IN1 = IN2 = 1 >= 3 ms) before
IN = 00 + nSLEEP low (KICK_CASES 'usb-chargedone-worst-brake-then-sleep').

Assumptions that are not datasheet values (bounded, and listed in the model_limitations of the run):
  * cell + PCM resistance 0.20 Ohm at 25 C, 0.40 Ohm at -10 C, 0.15 Ohm at 60 C (architecture.md §8.4 gives
    "about 0.25 Ohm of pack plus path");
  * link inductance 80 nH loop for the 80 mm harness; MLCC ESR 10 mOhm; VSYS MLCC DC-bias derating from the Samsung
    curves of each netlist MPN (MLCC_DCBIAS, 25 C typical; worst = minus the MPN tolerance; X5R temperature drift
    and ageing not included);
  * stepper inductance 2-10 mH (4.3 nominal) and back-EMF constant 0.27-1.37 V per k step/s (stepper.lib).
"""

from __future__ import annotations

import functools
import math
import re

import numpy as np
import pytest

from spicelib import Deck

# ---------------------------------------------------------------- limits and parameters (with their sources)
DS_DRV = "DRV8837 DS SLVSBA4F"
DS_BQ = "BQ25180 DS SLUSE99C"
DS_HALL = "DRV5032 DS SLVSDC7H"
DS_NRF = "nRF52840 PS v1.6 §6.9.3.1"

RDS_TYP, RDS_MAX = 0.280, 0.330          # DRV8837 Table 6.5 rDS(on) HS+LS, 25 C, IO = 800 mA
IOUT_MAX = 1.8                           # DRV8837 Table 6.3 motor peak current
IOCP_MIN = 1.9                           # DRV8837 Table 6.5 / 7-4 IOCP min
TWAKE_MAX = 30e-6                        # DRV8837 Table 6.6 twake
VIH_K_MAX = 0.5                          # DRV8837 Table 6.5 VIH = 0.5 x VCC max
VM_ROC_MAX = 11.0                        # DRV8837 Table 6.3 VM
RTHJA_DRV = 60.9                         # DRV8837 Table 6.4 RthetaJA (DSG)
TSD_MIN = 150.0                          # DRV8837 Table 6.5 TTSD min

SYS_ABS_MAX = 5.5                        # BQ25180 Table 7.1 "all other pins" (SYS, BAT) abs max
SYS_I_DC = 1.5                           # BQ25180 Table 7.1 SYS discharge current DC
BATOCP = 1.5                             # BQ25180 Table 7.5 IBAT_OCP setting 10 (CHARGECTRL1 0x92, architecture.md)
VBUVLO = 3.0                             # BQ25180 Table 7.5 BUVLO setting b000 (deglitch 60 us, Table 7.6)
RON_BAT_TYP, RON_BAT_MAX = 0.055, 0.090  # BQ25180 Table 7.5 RON_BAT
RON_IN_TYP, RON_IN_MAX = 0.27, 0.47      # BQ25180 Table 7.5 RON_IN
ILIM_MIN = 0.450                         # BQ25180 Table 7.5 ILIM at the 500 mA setting: 450 / 475 / 498 mA
# BQ25180 SYS_REG 010 = 4.5 V, Table 7.5 accuracy +-2 %. firmware.md §13.1 row 8 sets 001 = 4.4 V (0x20); 4.5 V is the
# POR default (before the init, e.g. in MCUboot) and the only other value firmware.md allows, so it stays the USB VSYS
# here: the upper bound for the coil-current / coast-peak checks.
SYS_REG, SYS_REG_ACC = 4.5, 0.02

JST_I_CONTACT = 1.0                      # JST SH catalogue: 1 A per contact with AWG 28 (SPEC §2)
RC_INIT, RC_AGED = 0.020, 0.040          # JST SH catalogue contact resistance, initial / after env. tests
WIRE_R = 0.21 * 0.080                    # 28 AWG 0.21 Ohm/m x 80 mm harness (architecture.md §4.2)
L_LINK = 80e-9                           # harness loop inductance (assumption, ~1 nH/mm)
SHARE_WORST = (WIRE_R + 2 * RC_AGED) / (2 * WIRE_R + 2 * RC_AGED + 2 * RC_INIT)  # worst VSYS contact share

R_COIL = 20.0                            # VSM08102: 20 Ohm/phase (detent research)
V_RATED = 3.3                            # VSM08102 rated 3.3-5 V; thrust quoted at the 3.3 V end
V_RATED_MAX = 5.0
I_RATED = V_RATED / R_COIL               # 165 mA/phase at 25 C: the research's "about 165 mA/phase at 3.3 V"
F_RATED = 0.78                           # >= 80 gf pull-out at 500 PPS (vendor, detent research)
F_NEED = 0.50                            # detent research design rule: total actuator load <= 0.5 N (8 mm motor)
F_WORST = 1.15                           # detent verifier: realistic worst-case load 0.8-1.15 N (risk R4)
L_NOM, L_MAX = 4.3e-3, 10e-3            # phase inductance: nominal / upper bound (stepper.lib header, 2-10 mH)
KE_MAX = 1.37                            # back-EMF upper bound, V per k step/s (stepper.lib header; lower 0.27)
SRC_RES = "detent research (VSM08102 3.3 V / 20 Ohm, >= 80 gf at 500 PPS)"

FW = "firmware.md"
FW_VSYS_MOVE_OLD = 3.40                  # pre-MD-2 firmware.md §5.8 non-park minimum (evidence of the strict xfail)
FW_VSYS_MOVE = 3.55                      # firmware.md §5.8 minimum VSYS for non-park moves, measured idle (MD-2)
FW_VSYS_PARK = 3.30                      # firmware.md §5.8 minimum VSYS for a park move
# firmware.md §12.4 (VSENSE-1/4): the calibrated VSYS reading is 'about ±10 mV, but only at 25 ± 10 °C on a fresh unit'
# and 'can be up to 46 mV high away from 25 °C or after ageing'. MD-2 gates on the *measured* idle VSYS, so a reading
# that high lets a non-park move start from a true idle VSYS that much lower.
FW_ADC_FRESH, FW_ADC_HIGH = 0.010, 0.046
SRC_ADC = f"{FW} §12.4 (VSENSE-1/4) calibrated VSYS reading about ±10 mV at 25 ± 10 °C fresh, up to 46 mV high aged"
FW_LED_CAP = 0.100                       # firmware.md §5.8 LED cap while moving (100 mA average)
I_SYS = 0.050                            # nRF + QSPI peak, architecture.md §8.4
FW_WAKE_WAIT = 1e-3                      # firmware.md §5.2: nSLEEP high, wait 1 ms
FW_PRE_ENERGISE = 10e-3                  # firmware.md §5.2: energise the stored phase for 10 ms
FW_BRAKE = 3e-3                          # firmware.md §5.2 / §5.8 (MD-1): brake IN1 = IN2 = 1 >= 3 ms before sleep
FW_I_TARGET = 0.160                      # firmware.md §5.3 run current
FW_R_COIL_OLD = 20.3                     # pre-MD-3 firmware.md §5.3 fixed coil resistance in d = I x R / VSYS
FW_R25, FW_ALPHA, FW_R_DRV = 20.0, 0.00393, 0.33   # firmware.md §5.3 (MD-3): coil 20 Ohm at 25 C, copper tempco,
                                                   # RDS(on) HS+LS (DRV8837 max at 25 C)


def fw_r_eff(temp_c):
    """firmware.md §5.3 amplitude rule (MD-3): d_peak = I_target x R_eff / VSYS with
    R_eff = 20 Ohm x (1 + 0.00393 x (T - 25 C)) + 0.33 Ohm (20.33 Ohm at 25 C), T = nRF die temperature (taken equal
    to the coil / ambient temperature of the corner)."""
    return FW_R25 * (1 + FW_ALPHA * (temp_c - 25)) + FW_R_DRV


SRC_MD3 = f"{FW} §5.3 (MD-3) d = I x (20 Ohm x (1 + 0.00393 x (T - 25 C)) + 0.33 Ohm) / VSYS, clamp d <= 1"
FW_HOME_LAG = 0.075                      # firmware.md §5.4 edge-window lag allowance (0.075 s x v) ...
FW_HOME_M = 10                           # ... plus m = max(10 steps, learned spread)
FW_HOME_PPS = 446                        # fastest speed while crossing a HOME edge (approach/run-in, §5.3)
FW_HOME_WINDOW = FW_HOME_LAG + FW_HOME_M / FW_HOME_PPS   # 97.4 ms: the edge must land inside this

NRF_VIH_K, NRF_VIL_K = 0.7, 0.3          # nRF52840 PS VIH min / VIL max
NRF_ROUT = 800.0                         # VOH,SD >= VDD - 0.4 V at 0.5 mA (standard drive)

HALL = {  # DRV5032 SOT-23 omnipolar variants. Table 4-1: output type (od = open-drain); Table 6.5: tS (min, typ,
    # max); Table 6.6: BOP max / BRP min (the corners that assert last / release last). FC differs from the fitted FA
    # only in the output type, so it is the plausible substitution error (verifier addition: FC, AJ, ZE).
    "FA": dict(ts=(27e-3, 50e-3, 75e-3), od=0, bop=4.8, brp=0.5),
    "FB": dict(ts=(117e-3, 200e-3, 286e-3), od=0, bop=4.8, brp=0.5),
    "FC": dict(ts=(27e-3, 50e-3, 75e-3), od=1, bop=4.8, brp=0.5),
    "AJ": dict(ts=(27e-3, 50e-3, 75e-3), od=1, bop=9.5, brp=3.0),
    "ZE": dict(ts=(27e-3, 50e-3, 75e-3), od=1, bop=63.0, brp=30.0),
}
HALL_TACT = 40e-6
HALL_IOUT_MAX = 5e-3                     # DRV5032 Table 6.1 / 6.3 output current
HALL_ROH, HALL_ROL = 350.0, 300.0        # VOH >= VCC - 0.35 V at -1 mA, VOL <= 0.3 V at 1 mA
B_PARK = 32.9                            # mT at the home sensor with the carriage parked (detent research sim)

VSYS_MIN_3V3 = 2.7 + 0.3                 # W25Q128 VCC >= 2.7 V (architecture.md power table) + LDO dropout
SRC_3V3 = "SPEC §3 LDO dropout <= 300 mV + W25Q128 VCC >= 2.7 V (architecture.md §8 rails)"
R_PACK = {-10: 0.40, 25: 0.20, 60: 0.15}  # cell + PCM resistance (assumption, see module docstring)
TEMPS = (-10, 25, 60)

LIBS = ("motor_drive__drv8837.lib", "motor_drive__stepper.lib", "motor_drive__bq25180.lib",
        "motor_drive__nrf52840_gpio.lib", "motor_drive__drv5032.lib")

# MLCC DC-bias derating (verifier addition; replaces a flat x0.5 that was optimistic for the 0603 10 V parts).
# Samsung Electro-Mechanics characterization data, 25 C, Delta C in % at 0, 0.5, 1.0, ..., 6.0 V DC, read from the
# DC-bias graph of each part's product page (weblib.samsungsem.com/mlcc/mlcc-ec.do?partNumber=<MPN>, retrieved
# 2026-10-19). The MPN comes from the netlist (first 14 characters, without the packaging suffix), so a BOM change to
# an MPN that is not listed here fails loudly instead of being simulated with a guessed derating.
MLCC_DCBIAS = {
    "CL21A226MAQNNN": (0.0, 1.1, -1.1, -6.9, -13.5, -20.7, -28.1, -35.0, -41.0, -46.5, -51.3, -55.5, -59.2),
    "CL10A106KP8NNN": (0.0, -3.0, -10.9, -22.1, -33.0, -42.5, -51.2, -58.3, -63.5, -68.0, -71.7, -74.8, -77.5),
    "CL21A106KAYNNN": (0.0, -0.6, -2.7, -7.3, -12.7, -19.3, -26.4, -33.1, -39.5, -45.2, -50.3, -54.8, -58.8),
    "CL10A106MA8NRN": (0.0, -0.7, -3.6, -9.2, -15.5, -22.6, -29.9, -36.6, -42.6, -48.1, -52.8, -57.0, -60.7),
    "CL05B104KO5NNN": (0.0, 0.1, 0.2, -0.2, -0.8, -1.8, -3.1, -4.5, -6.1, -7.8, -9.5, -11.3, -13.1),
}
V_DCBIAS_KICK = 5.0       # turn-off kick: the middle of the 4.6 -> 5.5 V swing the SYS abs-max check covers
SRC_DCBIAS = "Samsung SEM DC-bias data (25 C) per netlist MPN; tolerance from the MPN code (K 10 %, M 20 %)"


class Supply:
    def __init__(self, name, vbat, usb=False, vbus=5.0, vsysreg=SYS_REG, ichg=0.0):
        self.name, self.vbat, self.usb, self.vbus, self.vsysreg, self.ichg = name, vbat, usb, vbus, vsysreg, ichg

    @property
    def vsys_idle(self):
        return min(self.vsysreg, self.vbus) if self.usb else self.vbat

    def __repr__(self):
        return self.name


SUP = {s.name: s for s in (
    Supply("VBAT3.0", 3.0), Supply("VBAT3.3", 3.3), Supply("VBAT3.4", 3.4), Supply("VBAT3.7", 3.7),
    Supply("VBAT4.2", 4.2),
    # USB: SYS regulated to 4.5 V +-2 % (POR default / allowed alternative, the upper bound; firmware sets 4.4 V, see
    # SYS_REG); VBUS 4.5 V cannot reach it through RON_IN; battery at 3.7 V supplements
    Supply("VBUS4.5", 3.7, usb=True, vbus=4.5, vsysreg=SYS_REG),
    Supply("VBUS5.0", 3.7, usb=True, vbus=5.0, vsysreg=SYS_REG),
    Supply("VBUS5.5", 3.7, usb=True, vbus=5.5, vsysreg=SYS_REG * (1 + SYS_REG_ACC)),   # 4.59 V
    # charge terminated: cell full (VBATREG 4.2 V), BATFET off (DS 8.1.1.4), only supplement can conduct
    Supply("VBUS5.5-done", 4.2, usb=True, vbus=5.5, vsysreg=SYS_REG * (1 + SYS_REG_ACC)),
    # charging at ICHG 400 mA (architecture.md §8.5): the charger sinks current from SYS into the cell
    Supply("VBUS5.5-charging", 3.7, usb=True, vbus=5.5, vsysreg=SYS_REG * (1 + SYS_REG_ACC), ichg=0.4),
)}


# ---------------------------------------------------------------- deck building blocks
def _base_lines(lines):
    """Base-board passives on their own nodes (nb_*), with the base GND (nb_gnd) behind the link GND wires."""
    out = []
    for ln in lines:
        t = ln.split()
        t[0] = t[0][0] + "B" + t[0][1:]
        for i in (1, 2):
            t[i] = "nb_gnd" if t[i] == "0" else ("nb_" + t[i][2:] if t[i].startswith("n_") else t[i])
        out.append(" ".join(t))
    return out


def vsys_caps(d):
    """Fitted VSYS-GND capacitors (a removed or DNP part is not in the deck, so it must not count in C_eff either)."""
    return [r for r in d.on_net("VSYS", "C") if d.fitted(r) and set(d.pins[r].values()) <= {"VSYS", "GND"}]


def mlcc_tol(d, ref):
    """Capacitance tolerance from the Samsung MPN code (9th character, after the 3-digit value: K = 10 %, M = 20 %;
    the 10th is the voltage code); the value string carries none, and the harness default (10 %) would understate the
    M-grade parts (main C1, C2, C6, C41; base C2, C4)."""
    mpn = d.mpn(ref)
    if mpn.startswith("CL") and len(mpn) >= 9 and mpn[8] in "KM":
        return {"K": 0.10, "M": 0.20}[mpn[8]]
    return d.tol(ref)


SAMSUNG_VRATED = {"R": 4.0, "Q": 6.3, "P": 10.0, "O": 16.0, "A": 25.0, "L": 35.0, "B": 50.0, "C": 100.0}


def cap_vrated(d, ref):
    """Rated voltage: from the value string ('10u/25V') if it carries one, else from the Samsung MPN voltage code
    (10th character, Samsung MLCC part-numbering guide). Unknown parts fail loudly."""
    v = d.comps[ref]["value"]
    if "/" in v and v.split("/")[1].strip().upper().endswith("V"):
        return float(v.split("/")[1].strip()[:-1])
    mpn = d.mpn(ref)
    if mpn.startswith("CL") and len(mpn) >= 10 and mpn[9] in SAMSUNG_VRATED:
        return SAMSUNG_VRATED[mpn[9]]
    raise KeyError(f"{d.board} {ref} {v!r} / MPN {mpn!r}: no voltage rating in the value or the MPN")


def cap_case_len_mm(d, ref):
    """Body length in mm from the KiCad footprint name (C_0805_2012Metric -> 2.0). Unknown footprints fail loudly."""
    fp = d.comps[ref]["fields"].get("Footprint", "")
    m = re.search(r"_(\d{2})(\d{2})Metric", fp)
    if not m:
        raise KeyError(f"{d.board} {ref}: no metric case size in footprint {fp!r}")
    return int(m.group(1)) / 10.0


def mlcc_dcbias(d, ref, v):
    key = d.mpn(ref)[:14]
    if key not in MLCC_DCBIAS:
        raise KeyError(f"{d.board} {ref} MPN {d.mpn(ref)!r}: no DC-bias data in MLCC_DCBIAS (add the vendor curve)")
    return 1.0 + float(np.interp(v, [0.5 * k for k in range(13)], MLCC_DCBIAS[key])) / 100.0


def vsys_cscale(main, base, v, worst=True):
    """Per-part scale for every VSYS MLCC on both boards: vendor DC-bias derating at v, times (1 - tolerance) if worst.
    Keys as power() expects them (main refs plain, base refs as 'base:<ref>')."""
    cs = {r: mlcc_dcbias(main, r, v) * ((1 - mlcc_tol(main, r)) if worst else 1.0) for r in vsys_caps(main)}
    cs.update({"base:" + r: mlcc_dcbias(base, r, v) * ((1 - mlcc_tol(base, r)) if worst else 1.0)
               for r in vsys_caps(base)})
    return cs


def vsys_ceff(main, base, cs):
    return (sum(main.value(r) * cs[r] for r in vsys_caps(main))
            + sum(base.value(r) * cs["base:" + r] for r in vsys_caps(base)))


def new_deck(title):
    deck = Deck(title)
    # 1 nA absolute current tolerance: the default 1 pA stalls the timestep on the near-idle cell branch in USB
    # mode (B-source rounding noise); every current checked here is >= 100 uA
    deck.options.append("option abstol=1e-9")
    # Gear integration: trapezoidal ringing on the stiff BAT node (0.2 Ohm pack + 4.7 uF) showed up as +-40 V
    # numerical spikes at timestep cut-backs; Gear damps them (physical LC ringing here has Q < 1 anyway)
    deck.options.append("option method=gear")
    for lib in LIBS:
        deck.include(lib)
    return deck


def power(deck, main, base, sup, temp, *, other=FW_LED_CAP + I_SYS, aged=True, ron_bat=RON_BAT_MAX,
          ron_in=RON_IN_MAX, ilim=ILIM_MIN, cscale=None, esr=0.01, v3=3.3, rpack=None):
    """Cell -> BQ25180 -> base caps -> link -> main VSYS caps, plus the other VSYS loads and the +3V3 rail."""
    rpack = R_PACK[temp] if rpack is None else rpack
    cscale = cscale or {}
    deck += f"Vcell nb_cell nb_gnd DC {sup.vbat}"
    deck += f"Rpack nb_cell nb_vbat {rpack}"
    deck += _base_lines(base.passives(nets={"VSYS", "GND"}, esr={"C": esr},
                                      scale={r: cscale.get("base:" + r, cscale.get("*", 1.0)) for r in vsys_caps(base)}))
    deck += _base_lines(base.passives(nets={"VBAT", "GND"}, esr={"C": esr}))
    deck += (f"XBQ nb_vsys nb_vbat nb_gnd BQ25180_PATH params: usb={int(sup.usb)} vbus={sup.vbus} "
             f"vsysreg={sup.vsysreg:.4f} ilim={ilim} ron_in={ron_in} ron_bat={ron_bat} ichg={sup.ichg}")
    rw = WIRE_R + 2 * (RC_AGED if aged else RC_INIT)
    vs = main.node("VSYS")
    # harness: R from wire + contacts; L with a 1 Ohm parallel damper (wire AC loss, keeps the solver out of
    # undamped ringing on the base ground; corner 4 MHz, no effect at the 25 kHz PWM or slower)
    deck += ["Vlink nb_vsys lk1 0", f"Rlink lk1 lk2 {rw / 2:.6g}", f"Llink lk2 {vs} {L_LINK / 2:.6g}",
             f"Rdlink lk2 {vs} 1", f"Rlgnd 0 lg1 {rw / 3:.6g}", f"Llgnd lg1 nb_gnd {L_LINK / 2:.6g}", "Rdlgnd lg1 nb_gnd 1"]
    deck += main.passives(nets={"VSYS", "GND"}, esr={"C": esr},
                          scale={r: cscale.get(r, cscale.get("*", 1.0)) for r in vsys_caps(main)})
    deck += f"Iother {vs} 0 DC {other}"
    p3 = main.node("+3V3")
    deck += [f"V3v3 n3v3src 0 DC {v3}", f"R3v3 n3v3src {p3} 0.05"]
    deck += main.passives(nets={"+3V3", "GND"}, esr={"C": esr})
    return deck


def drivers(deck, d, temp, *, rds=RDS_TYP, twake=TWAKE_MAX, iocp=IOCP_MIN, tol=0.0, lph=L_NOM, ke=0.0, pps=0.0,
            t0=0.0, tg=0.0, tstop=1e3, delta=math.pi / 2):
    for ref in ("U40", "U41"):
        p = functools.partial(d.pin, ref)
        deck += (f"X{ref} {p('VM')} {p('VCC')} {p('IN1')} {p('IN2')} {p('nSLEEP')} {p('OUT1')} {p('OUT2')} {p('GND')} "
                 f"DRV8837 params: rds={rds} temp_c={temp} twake={twake} iocp={iocp}")
    for name, (a, b), phb in (("A", ("1", "2"), 0), ("B", ("3", "4"), 1)):
        deck += (f"XCOIL{name} {d.pin('J40', a)} coil{name.lower()}_m PMSTEP_PHASE params: r25={R_COIL} tol={tol} "
                 f"temp_c={temp} lph={lph} ke={ke} pps={pps} t0={t0} tg={tg} tstop={tstop} delta={delta} phb={phb}")
        deck += f"VI{name} coil{name.lower()}_m {d.pin('J40', b)} 0"
    return deck


def gpio_out(deck, d, net, ctrl):
    """nRF pin (standard drive) on `net`; ctrl is a DC level (0/1) or a list of (t, level) points."""
    tag = net.lower()
    if isinstance(ctrl, (int, float)):
        deck += f"Vc_{tag} c_{tag} 0 DC {ctrl}"
    else:
        deck += f"Vc_{tag} c_{tag} 0 PWL({' '.join(f'{t:.9g} {v:g}' for t, v in ctrl)})"
    deck += f"XG_{tag} {d.node(net)} {d.node('+3V3')} 0 c_{tag} NRF_GPIO_OUT params: rout={NRF_ROUT}"
    return deck


def _pwl(transitions, edge=10e-9):
    """[(t, level)] sorted, starting level 0 -> PWL points."""
    pts, cur = [(0.0, 0)], 0
    for t, lv in transitions:
        if lv != cur:
            pts += [(t, cur), (t + edge, lv)]
            cur = lv
    return pts


def fullstep_plan(pps, nsteps, *, t_on=50e-6, t_wait=FW_WAKE_WAIT, t_pre=2e-3, t_hold=2e-3, end="hold",
                  t_brake=FW_BRAKE, t_tail=1e-3):
    """Two-phase-on full-step schedule. State k has field angle 45 + 90k degrees: A = sign(cos), B = sign(sin).

    Returns (ctrl dict net -> transitions, timing dict)."""
    ts = 1.0 / pps if pps else 0.0
    t_e = t_on + t_wait
    t0 = t_e + t_pre
    tr = {n: [] for n in ("MOT_A_IN1", "MOT_A_IN2", "MOT_B_IN1", "MOT_B_IN2", "MOT_NSLEEP")}
    tr["MOT_NSLEEP"].append((t_on, 1))

    def state(t, k):
        a = math.cos(math.radians(45 + 90 * k)) > 0
        b = math.sin(math.radians(45 + 90 * k)) > 0
        tr["MOT_A_IN1"].append((t, int(a)))
        tr["MOT_A_IN2"].append((t, int(not a)))
        tr["MOT_B_IN1"].append((t, int(b)))
        tr["MOT_B_IN2"].append((t, int(not b)))

    state(t_e, 0)
    for k in range(1, nsteps + 1):
        state(t0 + (k - 1) * ts, k)
    t_last = t0 + nsteps * ts if nsteps else t0
    t_x = t_last + t_hold
    if end == "hold":
        t_stop = t_x
    elif end == "coast":
        for n in tr:
            tr[n].append((t_x, 0))
        t_stop = t_x + t_tail
    elif end == "brake":
        for n in ("MOT_A_IN1", "MOT_A_IN2", "MOT_B_IN1", "MOT_B_IN2"):
            tr[n].append((t_x, 1))
        for n in tr:
            tr[n].append((t_x + t_brake, 0))
        t_stop = t_x + t_brake + t_tail
    else:
        raise ValueError(end)
    timing = dict(t_on=t_on, t_e=t_e, t0=t0, ts=ts, t_last=t_last, t_x=t_x, t_stop=t_stop)
    return {n: _pwl(v) for n, v in tr.items()}, timing


def check_ran(res):
    assert not res["_errors"], res["_errors"][:5]
    assert not res.get("_missing"), (res.get("_missing"), res["_log"][-3000:])


def window(w, key, t1, t2):
    t = w["time"]
    m = (t >= t1) & (t <= t2)
    return t[m], w[key][m]


def tavg(t, y):
    return float(np.trapezoid(y, t) / (t[-1] - t[0]))


# ---------------------------------------------------------------- hold / stall operating point
def hold_op(main, base, sup, temp, *, tol=0.0, rds=RDS_MAX, other=FW_LED_CAP + I_SYS, aged=True, ilim=ILIM_MIN,
            ron_bat=RON_BAT_MAX, ron_in=RON_IN_MAX, lph=L_NOM):
    """Both coils energised at 100 % (full-step hold, i.e. also the stalled rotor). Run as a short transient from
    the sleeping state (a robust start for the behavioural models) to steady state (> 10 L/R)."""
    deck = new_deck(f"motor hold {sup} {temp}C")
    power(deck, main, base, sup, temp, other=other, aged=aged, ilim=ilim, ron_bat=ron_bat, ron_in=ron_in)
    drivers(deck, main, temp, rds=rds, tol=tol, lph=lph)
    t_on, t_e = 10e-6, 60e-6
    for net, t in (("MOT_NSLEEP", t_on), ("MOT_A_IN1", t_e), ("MOT_B_IN1", t_e)):
        gpio_out(deck, main, net, _pwl([(t, 1)]))
    for net in ("MOT_A_IN2", "MOT_B_IN2"):
        gpio_out(deck, main, net, 0)
    t_end = t_e + 12 * lph / (R_COIL * 0.8)
    vs = main.node("VSYS")
    a1, a2 = main.pin("U40", "OUT1"), main.pin("U40", "OUT2")
    deck.tran("2u", f"{t_end:.6g}", 0, "5u")
    for name, expr in (("ia", "i(via)"), ("ib", "i(vib)"), ("vsys", f"v({vs})"), ("vbat", "v(nb_vbat)"),
                       ("ilink", "i(vlink)"), ("va1", f"v({a1})"), ("va2", f"v({a2})"), ("vsys_base", "v(nb_vsys)"),
                       ("vnsleep", f"v({main.node('MOT_NSLEEP')})")):
        deck.meas(f"tran {name} FIND {expr} AT={t_end:.6g}")
    res = deck.run(timeout=120)
    check_ran(res)
    out = {k: res[k] for k in ("ia", "ib", "vsys", "vbat", "ilink", "vsys_base", "vnsleep")}
    out["vcoil"] = res["va1"] - res["va2"]
    return out


# ================================================================ tests
def test_drv8837_model_matches_datasheet(check):
    """Model sanity against SLVSBA4F: rDS(on) at 800 mA, Table 7-1 truth table, sleep = Hi-Z, wake = twake."""
    out = {}
    for name, (n, i1, i2) in {"fwd": (1, 1, 0), "rev": (1, 0, 1), "coast": (1, 0, 0), "brake": (1, 1, 1),
                              "sleep": (0, 1, 0)}.items():
        deck = new_deck(f"truth {name}")
        deck += ["VVM vm 0 5", "VCC vcc 0 3", f"VN ns 0 {3 * n}", f"V1 in1 0 {3 * i1}", f"V2 in2 0 {3 * i2}",
                 "X1 vm vcc in1 in2 ns o1 o2 0 DRV8837 params: rds=0.28",
                 "Ro1 o1 vh 1k", "Ro2 o2 vh 1k", "Vh vh 0 2.5",       # weak midpoint bias shows Z as 2.5 V
                 "X2 vm vcc in1b 0 ns p1 p2 0 DRV8837 params: rds=0.28", "V3 in1b 0 3",
                 "Rl p1 pm 5.97", "Vil pm p2 0"]                       # 5 V / (5.97 + 0.28) = 0.8 A test load
        deck.op()
        deck.print_op("v(o1)", "v(o2)", "i(vil)", "v(p1,p2)")
        r = deck.run()
        check_ran(r)
        out[name] = (r["op_0"], r["op_1"], r["op_2"], r["op_3"])
    o = out["fwd"]
    rds = (5.0 - o[3]) / o[2]
    check("rDS(on) HS+LS at 0.8 A, 25 C", rds, RDS_TYP * 0.97, RDS_TYP * 1.03, "Ohm", f"{DS_DRV} Table 6.5 rDS(on)")
    lvl = {"H": (4.9, 5.01), "L": (-0.01, 0.1), "Z": (2.4, 2.6)}
    want = {"fwd": "HL", "rev": "LH", "coast": "ZZ", "brake": "LL", "sleep": "ZZ"}
    for name, (s1, s2) in want.items():
        for k, s in ((0, s1), (1, s2)):
            check(f"{name}: OUT{k + 1} = {s}", out[name][k], *lvl[s], "V", f"{DS_DRV} Table 7-1")


# ------------------------------------------------ coil current vs ratings (hold = stall, max current corner)
@pytest.mark.parametrize("supname", ["VBAT4.2", "VBUS5.5"])
def test_hold_current_vs_ratings(main, base, check, supname):
    """Highest coil current: hold/stall at the highest VSYS, coldest coil, coil -10 %, typical rDS(on).

    Checks the stepper terminal voltage against its 5 V rating, the DRV8837 output current against IOUT and
    the lowest OCP trip, the DRV8837 junction temperature, and the link / BQ25180 currents this draws."""
    sup = SUP[supname]
    temp = -10
    # ILIM at the 1050 mA setting's max (1.1 A) so that SYS really stays at 4.59 V on USB (max coil voltage).
    # TJ uses rDS(on) max x 1.2 (Figure 6-7 drift from 25 C to about 85 C).
    r = hold_op(main, base, sup, temp, tol=-0.10, rds=RDS_TYP, other=I_SYS, aged=False, ilim=1.1,
                ron_bat=RON_BAT_TYP, ron_in=RON_IN_TYP)
    imax = max(abs(r["ia"]), abs(r["ib"]))
    check("coil terminal voltage (hold)", abs(r["vcoil"]), None, V_RATED_MAX, "V", f"{SRC_RES}: rated 3.3-5 V")
    check("DRV8837 OUT current (hold)", imax, None, IOUT_MAX, "A", f"{DS_DRV} Table 6.3 IOUT")
    check("DRV8837 OUT current vs OCP trip", imax, None, IOCP_MIN, "A", f"{DS_DRV} Table 6.5 IOCP min")
    tj = 60.0 + imax ** 2 * RDS_MAX * 1.2 * RTHJA_DRV
    check("DRV8837 TJ at 60 C ambient (hold)", tj, None, TSD_MIN, "°C", f"{DS_DRV} Table 6.4 RθJA, 6.5 TTSD")
    ilink = r["ilink"]
    check("link current per VSYS contact", ilink * SHARE_WORST, None, JST_I_CONTACT, "A",
          "JST SH 1 A/contact (SPEC §2)")
    check("BQ25180 SYS current", ilink, None, SYS_I_DC, "A", f"{DS_BQ} Table 7.1 SYS DC")
    if not sup.usb:
        check("battery discharge current (= SYS current on battery)", ilink, None, BATOCP, "A",
              f"{DS_BQ} Table 7.5 IBAT_OCP 1.5 A setting")


# ------------------------------------------------ needed force vs VSYS and temperature (hold current)
MOVE_SUPPLIES = ["VBAT3.3", "VBAT3.4", "VBAT3.7", "VBAT4.2", "VBUS4.5", "VBUS5.0", "VBUS5.5"]


@pytest.mark.parametrize("temp", TEMPS)
@pytest.mark.parametrize("supname", MOVE_SUPPLIES)
def test_hold_force_and_brownout(main, base, check, supname, temp):
    """Coil current with the whole stroke load on VSYS (2 coils + LED cap 100 mA + nRF 50 mA), worst source
    resistance (RON max, aged contacts, cold pack), rDS(on) max. Force ~ current: F = 0.78 N x I / 165 mA.

    Every supply here is one where firmware.md §5.8 allows a move (park >= 3.30 V, others >= 3.55 V since MD-2;
    VBAT 3.3 / 3.4 V are park-only)."""
    sup = SUP[supname]
    assert sup.vsys_idle >= FW_VSYS_PARK
    r = hold_op(main, base, sup, temp)
    i = min(abs(r["ia"]), abs(r["ib"]))
    ratio = i / I_RATED
    check(f"I_coil / I_rated ({sup}, {temp} C)", ratio, None, None, "",
          f"info: I_rated = 3.3 V / 20 Ohm = 165 mA ({SRC_RES})")
    check(f"thrust estimate ({sup}, {temp} C)", F_RATED * ratio, F_NEED, None, "N",
          "detent research: load <= 0.5 N for the 8 mm motor; F = 0.78 N x I/I_rated")
    check(f"VSYS at the DRV under stroke load ({sup}, {temp} C)", r["vsys"], VSYS_MIN_3V3, None, "V", SRC_3V3)
    if not sup.usb:
        check(f"BAT pin under stroke load ({sup}, {temp} C)", r["vbat"], VBUVLO, None, "V",
              f"{DS_BQ} Table 7.5 VBUVLO (b000) - no brown-out")


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE (minor, thrust margin; old-rule evidence for MD-2): the pre-MD-2 firmware.md §5.8 'minimum VSYS for "
    "non-park moves 3.40 V (measured idle)' ignores the stroke-load sag (pack + BATFET + link) and rDS(on): at 3.40 V "
    "idle the phase voltage is below the motor's 3.3 V minimum rating (< 165 mA at 25 C); the 0.5 N load budget is "
    "still met. Rule now 3.55 V: test_required_current_at_firmware_move_threshold_with_fw_rule"))
def test_required_current_at_firmware_move_threshold(main, base, check):
    """VSM08102 rated phase voltage 3.3-5 V (vendor, via detent research): 165 mA/phase at 25 C is the lowest rated
    drive, where >= 80 gf is quoted. The pre-MD-2 firmware.md §5.8 let non-park moves start at VSYS = 3.40 V measured
    *idle*. With the stroke load (2 coils + LED cap + nRF) the coil current there is below 165 mA. The research's own
    rule is 'move only when VBAT >= 3.3 V under load'; the BAT-pin values under load are recorded (25 C and -10 C)."""
    assert SUP["VBAT3.4"].vbat == FW_VSYS_MOVE_OLD
    lo = hold_op(main, base, SUP["VBAT3.4"], 25)
    hi = hold_op(main, base, SUP["VBAT3.7"], 25)
    cold = hold_op(main, base, SUP["VBAT3.4"], -10)
    i_lo, i_hi = (min(abs(r["ia"]), abs(r["ib"])) for r in (lo, hi))
    need = 3.4 + (I_RATED - i_lo) * (3.7 - 3.4) / (i_hi - i_lo)       # idle VSYS that gives 165 mA (linear)
    check("idle VSYS needed for I_rated under stroke load, 25 C", need, None, None, "V",
          "info: interpolated from the simulated 3.4 / 3.7 V operating points")
    check("BAT pin under stroke load at VSYS idle 3.40 V, 25 C", lo["vbat"], None, None, "V",
          "info: detent research 'move only when VBAT >= 3.3 V under load'")
    check("BAT pin under stroke load at VSYS idle 3.40 V, -10 C (pack 0.4 Ohm)", cold["vbat"], None, None, "V",
          "info: detent research 'move only when VBAT >= 3.3 V under load' (the cold coil still gets > 165 mA)")
    check("I_coil at the old firmware non-park threshold (VSYS idle 3.40 V, 25 C)", i_lo, I_RATED, None, "A",
          f"VSM08102 rated phase voltage 3.3-5 V (vendor page via detent research): 3.3 V / 20 Ohm = 165 mA, "
          f"vs the pre-MD-2 {FW} §5.8 3.40 V idle")


def test_required_current_at_firmware_move_threshold_with_fw_rule(main, base, check):
    """Guard for MD-2 (firmware.md §5.8 / §12.4: non-park moves only from >= 3.55 V measured idle VSYS). Same deck and
    corners as test_required_current_at_firmware_move_threshold (stroke load = 2 coils + LED cap + nRF, worst source
    resistance, rDS(on) max) at the new threshold: the 25 C coil current must reach the rated 165 mA."""
    sup = Supply(f"VBAT{FW_VSYS_MOVE:.2f}", FW_VSYS_MOVE)
    r = hold_op(main, base, sup, 25)
    cold = hold_op(main, base, sup, -10)
    i = min(abs(r["ia"]), abs(r["ib"]))
    check(f"BAT pin under stroke load at VSYS idle {FW_VSYS_MOVE:.2f} V, 25 C", r["vbat"], None, None, "V",
          "info: detent research 'move only when VBAT >= 3.3 V under load'")
    check(f"BAT pin under stroke load at VSYS idle {FW_VSYS_MOVE:.2f} V, -10 C (pack 0.4 Ohm)", cold["vbat"], None,
          None, "V", "info: detent research 'move only when VBAT >= 3.3 V under load'")
    check(f"I_coil at VSYS idle {FW_VSYS_MOVE:.2f} V, -10 C", min(abs(cold["ia"]), abs(cold["ib"])), None, None, "A",
          "info: the cold coil (17.2 Ohm) gets more than the 25 C rated current")
    check(f"I_coil at the firmware non-park threshold (VSYS idle {FW_VSYS_MOVE:.2f} V, 25 C)", i, I_RATED, None, "A",
          f"VSM08102 rated phase voltage 3.3-5 V (vendor page via detent research): 3.3 V / 20 Ohm = 165 mA; "
          f"firmware rule {FW} §5.8 non-park moves only from >= {FW_VSYS_MOVE:.2f} V idle VSYS (MD-2)")


MD2_ADC_CASES = [  # id, over-read of the measured idle VSYS (firmware.md §12.4), strict-xfail reason
    ("fresh-unit-reads-10mV-high", FW_ADC_FRESH, None),
    ("aged-unit-reads-46mV-high", FW_ADC_HIGH,
     "DESIGN ISSUE (firmware rule insufficient): firmware.md §5.8 gates non-park moves on 3.55 V *measured* idle VSYS "
     "and §12.4 says the calibrated reading can be up to 46 mV high after ageing ('every threshold below is set with "
     "that drift in mind'), so a move can start from a true idle VSYS of 3.504 V: at 25 C the coil gets about 163.6 mA "
     "< the rated 165 mA (the rated point is 3.533 V; the vsys_sense model's own aged 25 C over-read, 29.6 mV, gives "
     "3.520 V and about 164.4 mA). The threshold would need about 3.58 V measured (3.533 V + 46 mV); the 0.5 N load "
     "budget is still met at 25 C"),
]


@pytest.mark.parametrize("cid,over_read,xf", [
    pytest.param(*c, marks=[pytest.mark.xfail(strict=True, reason=c[-1])] if c[-1] else [], id=c[0])
    for c in MD2_ADC_CASES])
def test_required_current_at_measured_move_threshold_with_fw_rule(main, base, check, cid, over_read, xf):
    """Worst corner of the MD-2 rule (reviewer extension of the guard above): firmware.md §5.8 gates on the *measured*
    idle VSYS ('3.55 V (measured idle)'), and firmware.md §12.4 gives the calibrated reading as about ±10 mV at
    25 ± 10 °C on a fresh unit and up to 46 mV high after ageing (VSENSE-1/4). A reading that high lets a non-park move
    start from a true idle VSYS of 3.55 V minus the over-read. Same deck, stroke load and 25 C rating corner as
    test_required_current_at_firmware_move_threshold_with_fw_rule."""
    v_true = FW_VSYS_MOVE - over_read
    r = hold_op(main, base, Supply(f"VBAT{v_true:.3f}", v_true), 25)
    i = min(abs(r["ia"]), abs(r["ib"]))
    check(f"true idle VSYS when it reads {FW_VSYS_MOVE:.2f} V ({over_read * 1e3:g} mV high)", v_true, None, None, "V",
          f"info: {SRC_ADC}")
    check(f"BAT pin under stroke load at true VSYS idle {v_true:.3f} V, 25 C", r["vbat"], None, None, "V",
          "info: detent research 'move only when VBAT >= 3.3 V under load'")
    check(f"I_coil at the firmware non-park threshold read {over_read * 1e3:g} mV high (true VSYS idle {v_true:.3f} V, "
          f"25 C)", i, I_RATED, None, "A",
          f"VSM08102 rated phase voltage 3.3-5 V (vendor page via detent research): 3.3 V / 20 Ohm = 165 mA; "
          f"firmware rule {FW} §5.8 non-park moves only from >= {FW_VSYS_MOVE:.2f} V measured idle VSYS (MD-2); "
          f"{SRC_ADC}")


@pytest.mark.parametrize("temp", TEMPS)
def test_ratio_vsys_3v0_vs_4v6(main, base, check, temp):
    """The explicit comparison: coil current / required (rated) current at VBAT 3.0 V (empty cell) and at VSYS
    4.59 V (USB, SYS_REG 4.5 V + 2 %), and whether the needed force is still there.

    On USB the BQ25180 input limit (500 mA setting: 450 mA min) is below a two-phase full-step stroke plus the
    other loads, so SYS falls into supplement mode (VBAT - 40 mV) during the stroke: the '4.6 V' case only exists
    when ILIM is set higher (1050 mA setting) or the load is lighter. Both are simulated."""
    lo = hold_op(main, base, SUP["VBAT3.0"], temp)
    reg = hold_op(main, base, SUP["VBUS5.5"], temp, other=I_SYS, ilim=0.995)      # SYS held at 4.59 V
    real = hold_op(main, base, SUP["VBUS5.5"], temp, ilim=ILIM_MIN)               # firmware ILIM, LED cap on
    rlo, rreg, rreal = (min(abs(r["ia"]), abs(r["ib"])) / I_RATED for r in (lo, reg, real))
    check(f"I/I_rated at VBAT 3.0 V, {temp} C", rlo, None, None, "", "info (research: torque about -20 % at 3.0 V)")
    check(f"thrust at VBAT 3.0 V, {temp} C", F_RATED * rlo, F_NEED, None, "N", "detent research load budget 0.5 N")
    check(f"BAT pin under stroke at VBAT 3.0 V, {temp} C", lo["vbat"], None, None, "V",
          f"info: below {VBUVLO} V BUVLO -> moves must stay locked out ({FW} §5.8 forbids < 3.30 V)")
    check(f"VSYS at the DRV with SYS regulated (ILIM 1050 mA), {temp} C", reg["vsys"], 4.4, None, "V",
          f"info/consistency: {DS_BQ} SYS_REG 4.5 V +-2 % minus link drop")
    check(f"I/I_rated at VSYS 4.59 V, {temp} C", rreg, 1.0, None, "", f"{SRC_RES}: rated current reached")
    check(f"VSYS on USB during a stroke, ILIM 500 mA setting, {temp} C", real["vsys"], None, None, "V",
          f"info: supplement mode ({DS_BQ} 8.3.3) when the load exceeds ILIM 450 mA min")
    check(f"I/I_rated on USB with ILIM 500 mA (supplement), {temp} C", rreal, None, None, "", "info")
    check(f"thrust on USB with ILIM 500 mA (supplement), {temp} C", F_RATED * rreal, F_NEED, None, "N",
          "detent research load budget 0.5 N")


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN ISSUE (MD-4, risk R4, accepted hardware risk): the verified worst-case actuator load 0.8-1.15 N exceeds "
    "what the 8 mm VSM08102 delivers at any battery VSYS; remedies are preloads cut to <= 0.5 N or the N20 / Ø6 "
    "gearmotor fallbacks (the 10 mm sibling's Ø10 can does not fit the 10.1 mm bowl, docs/mechanical.md §7)"))
def test_force_vs_verified_worst_load(main, base, check):
    """Best battery corner (VBAT 4.2 V, 25 C): thrust estimate vs the detent verifier's worst-case load."""
    r = hold_op(main, base, SUP["VBAT4.2"], 25)
    f = F_RATED * min(abs(r["ia"]), abs(r["ib"])) / I_RATED
    check("thrust at VBAT 4.2 V vs verified worst-case load", f, F_WORST, None, "N",
          "detent verifier: worst-case load 0.8-1.15 N (architecture.md R4)")


# ------------------------------------------------ full-step stepping transients
@functools.lru_cache(maxsize=None)
def rated_reference(pps, ke, lph, stall):
    """Average |i| of the same coil model driven at the vendor rating condition (ideal 3.3 V full step, 25 C,
    no driver drop) over the same window as the stepping tests: the 'required current' at this PPS."""
    deck = new_deck(f"rated reference {pps}")
    ts = 1.0 / pps
    nsteps, t0 = 8, 2e-3
    pts = [(0, 1)]
    for k in range(1, nsteps + 1):
        pts.append((t0 + (k - 1) * ts, 1 if math.cos(math.radians(45 + 90 * k)) > 0 else -1))
    pwl, cur = [(0.0, V_RATED)], 1
    for t, s in pts[1:]:
        if s != cur:
            pwl += [(t, V_RATED * cur), (t + 10e-9, V_RATED * s)]
            cur = s
    deck += f"Vdrv d 0 PWL({' '.join(f'{t:.9g} {v:g}' for t, v in pwl)})"
    kk = 0.0 if stall else ke
    deck += (f"XC d m PMSTEP_PHASE params: r25={R_COIL} temp_c=25 lph={lph} ke={kk} pps={pps} t0={t0 - ts} "
             f"tg={t0} tstop={t0 + nsteps * ts} phb=0")
    deck += "VI m 0 0"
    t1, t2 = t0 + (nsteps - 4) * ts, t0 + nsteps * ts
    deck.tran(f"{ts / 400:.3g}", f"{t2:.6g}", 0, f"{ts / 400:.3g}")
    deck.wave("i(vi)")
    r = deck.run()
    check_ran(r)
    t, i = window(r["waves"], "i(vi)", t1, t2)
    return tavg(t, np.abs(i))


def run_stepping(main, base, sup, temp, pps, *, nsteps=8, stall=False, tol=0.0, rds=RDS_MAX, lph=L_NOM, ke=KE_MAX,
                 other=FW_LED_CAP + I_SYS, end="hold", cscale=None, aged=True, t_pre=2e-3, t_hold=1e-3, extra=(),
                 ilim=ILIM_MIN, t_tail=1e-3, t_brake=FW_BRAKE):
    ctrl, tm = fullstep_plan(pps, nsteps, t_pre=t_pre, t_hold=t_hold, end=end, t_tail=t_tail, t_brake=t_brake)
    deck = new_deck(f"full step {pps} PPS {sup} {temp}C")
    if cscale is None:      # worst-case VSYS capacitance at the operating point (vendor DC bias, minus tolerance)
        cscale = vsys_cscale(main, base, sup.vsys_idle, worst=True)
    power(deck, main, base, sup, temp, other=other, cscale=cscale, aged=aged, ilim=ilim)
    ts = tm["ts"]
    drivers(deck, main, temp, rds=rds, tol=tol, lph=lph, ke=0.0 if stall else ke, pps=pps, t0=tm["t0"] - ts,
            tg=tm["t0"], tstop=tm["t_last"])
    for net, pts in ctrl.items():
        gpio_out(deck, main, net, pts)
    deck += list(extra)
    step = min(ts / 400, 5e-6)                         # L/R >= 0.1 ms; every step edge is a PWL breakpoint
    deck.tran(f"{step:.3g}", f"{tm['t_stop']:.6g}", 0, f"{step:.3g}")
    vs = main.node("VSYS")
    a1, a2 = main.pin("U40", "OUT1"), main.pin("U40", "OUT2")
    deck.wave("i(via)", "i(vib)", f"v({vs})", "v(nb_vbat)", "i(vlink)", f"v({a1})", f"v({a2})", "v(nb_vsys)")
    res = deck.run()
    check_ran(res)
    w = res["waves"]
    w["ia"], w["ib"], w["vsys"], w["vbat"], w["ilink"] = (w["i(via)"], w["i(vib)"], w[f"v({vs})"], w["v(nb_vbat)"],
                                                          w["i(vlink)"])
    w["oa1"], w["oa2"], w["vsys_base"] = w[f"v({a1})"], w[f"v({a2})"], w["v(nb_vsys)"]
    return w, tm


STEP_CASES = [  # (id, supply, temp, pps, stall)
    ("446pps-VBAT3.7-25C", "VBAT3.7", 25, 446, False),
    ("313pps-VBAT3.7-25C", "VBAT3.7", 25, 313, False),
    ("80pps-VBAT3.7-25C", "VBAT3.7", 25, 80, False),
    ("80pps-stall-VBAT3.7-25C", "VBAT3.7", 25, 80, True),
    ("446pps-VBAT3.4-60C", "VBAT3.4", 60, 446, False),
    ("446pps-VBAT3.3--10C", "VBAT3.3", -10, 446, False),
    ("446pps-VBAT4.2--10C", "VBAT4.2", -10, 446, False),
    ("446pps-VBUS5.5-25C", "VBUS5.5", 25, 446, False),
]


@pytest.mark.parametrize("cid,supname,temp,pps,stall", STEP_CASES, ids=[c[0] for c in STEP_CASES])
def test_fullstep_stepping(main, base, check, cid, supname, temp, pps, stall):
    """Full-step, two phases on, 8 steps (5 at 80 PPS): coil current (incl. back-EMF at the pull-out angle, upper ke bound),
    VM ripple at the DRV8837 VM pins (= main VSYS node with C70/C72/C74 and the rest of the netlist caps),
    the VSYS current pulses through the link (incl. the regenerated current at each phase reversal) and the
    BAT pin against BUVLO."""
    sup = SUP[supname]
    w, tm = run_stepping(main, base, sup, temp, pps, stall=stall, nsteps=8 if pps > 200 else 5)
    ts = tm["ts"]
    t1, t2 = tm["t_last"] - 4 * ts, tm["t_last"]      # last electrical cycle (4 full steps)
    t, ia = window(w, "ia", t1, t2)
    _, ib = window(w, "ib", t1, t2)
    iavg = 0.5 * (tavg(t, np.abs(ia)) + tavg(t, np.abs(ib)))
    iref = rated_reference(pps, KE_MAX, L_NOM, stall)
    ratio = iavg / iref
    check(f"avg |I_coil| / rated-drive current at {pps} PPS", ratio, None, None, "",
          "info: rated drive = ideal 3.3 V full step, same PPS/back-EMF, 25 C")
    check(f"thrust estimate at {pps} PPS", F_RATED * ratio, F_NEED, None, "N",
          "detent research: load <= 0.5 N; F = 0.78 N x I/I_rated-drive")
    ipk = float(max(np.max(np.abs(w["ia"])), np.max(np.abs(w["ib"]))))
    check("peak coil / OUT current", ipk, None, IOUT_MAX, "A", f"{DS_DRV} Table 6.3 IOUT 1.8 A")
    # the whole run (incl. the energise step) for the extremes, the stepping window for ripple / regen
    _, vs_all = window(w, "vsys", 0, tm["t_stop"])
    tw, vs = window(w, "vsys", tm["t0"] - 0.1 * ts, tm["t_last"])
    check("VM (VSYS) max, whole move", float(vs_all.max()), None, SYS_ABS_MAX, "V",
          f"{DS_BQ} Table 7.1 SYS abs max (lowest abs max on VSYS)")
    check("VM (VSYS) min, whole move", float(vs_all.min()), VSYS_MIN_3V3, None, "V", SRC_3V3)
    check("VM ripple pk-pk while stepping", float(vs.max() - vs.min()), None, None, "V", "info")
    _, il = window(w, "ilink", tm["t0"] - 0.1 * ts, tm["t_last"])
    check("link current per VSYS contact (peak)", float(il.max()) * SHARE_WORST, None, JST_I_CONTACT, "A",
          "JST SH 1 A/contact (SPEC §2)")
    check("link current min while stepping (dip at each phase reversal; < 0 = regen into base)", float(il.min()),
          None, None, "A", "info")
    if not sup.usb:
        _, vb = window(w, "vbat", 0, tm["t_stop"])
        check("BAT pin min, whole move", float(vb.min()), VBUVLO, None, "V", f"{DS_BQ} VBUVLO 3.0 V")


# ------------------------------------------------ turn-off kick through the body diodes
KICK_CASES = [  # id, supply, temp, tol, lph, VSYS caps ('worst' = vendor DC bias at 5 V - tolerance, 'typ'), end, xfail
    ("battery-4.2V-cold-coast", "VBAT4.2", -10, -0.10, L_MAX, "worst", "coast", None),
    ("usb-charging-coast", "VBUS5.5-charging", -10, -0.10, L_MAX, "worst", "coast", None),
    ("usb-chargedone-nominal-coast", "VBUS5.5-done", 25, 0.0, L_NOM, "typ", "coast", None),
    ("usb-chargedone-worst-coast", "VBUS5.5-done", -10, -0.10, L_MAX, "worst", "coast",
     "DESIGN ISSUE (conditional on a full-step drive; old-rule evidence for MD-1): coasting BOTH coils from a "
     "full-current two-phase-on hold on USB after charge termination (BATFET off, nothing sinks) dumps the coil energy "
     "into VSYS above the BQ25180 5.5 V abs max. The documented sine-microstep drive stays below it "
     "(test_firmware_drive_coast_kick); the MD-1 brake-before-sleep rule is guarded by the "
     "'usb-chargedone-worst-brake-then-sleep' case"),
    # MD-1 guard: same corner, firmware.md §5.2 stop path (IN1 = IN2 = 1 for FW_BRAKE = 3 ms, then IN = 00, nSLEEP low)
    ("usb-chargedone-worst-brake-then-sleep", "VBUS5.5-done", -10, -0.10, L_MAX, "worst", "brake", None),
]


@pytest.mark.parametrize("cid,supname,temp,tol,lph,cs,end,xf",
                         [pytest.param(*c, marks=[pytest.mark.xfail(strict=True, reason=c[-1])] if c[-1] else [],
                                       id=c[0]) for c in KICK_CASES])
def test_turnoff_kick(main, base, check, cid, supname, temp, tol, lph, cs, end, xf):
    """Hold both coils at full current (two-phase-on full step), then IDLE entry (all IN low + nSLEEP low -> coast):
    the coil current freewheels through the DRV8837 body diodes into VM. 'brake' = the firmware rule of
    firmware.md §5.2 / §5.8 and SPEC §5.6 (MD-1): IN1 = IN2 = 1 on U40/U41 for FW_BRAKE = 3 ms (the documented minimum;
    current decays in the low-side FETs), then IN = 00 and nSLEEP low; the 'usb-chargedone-worst-brake-then-sleep'
    case is the MD-1 guard for the 'usb-chargedone-worst-coast' strict xfail (same corner). Minimal other load (3 mA).
    VSYS MLCCs at the vendor DC-bias derating at 5 V (worst: minus the MPN tolerance)."""
    sup = SUP[supname]
    rule = (f"; firmware rule {FW} §5.2 (MD-1): brake IN1 = IN2 = 1 for {FW_BRAKE * 1e3:g} ms, then IN = 00 and "
            f"nSLEEP low" if end == "brake" else "")
    cscale = vsys_cscale(main, base, V_DCBIAS_KICK, worst=(cs == "worst"))
    check("effective VSYS capacitance at 5 V (both boards)", vsys_ceff(main, base, cscale), None, None, "F",
          f"info: {SRC_DCBIAS}")
    w, tm = run_stepping(main, base, sup, temp, 446, nsteps=0, stall=True, tol=tol, rds=RDS_TYP, lph=lph, other=3e-3,
                         end=end, cscale=cscale, aged=False, t_pre=6 * lph / 15, t_hold=0.5e-3)
    t_x = tm["t_x"]
    i0 = float(max(abs(np.interp(t_x - 1e-6, w["time"], w["ia"])), abs(np.interp(t_x - 1e-6, w["time"], w["ib"]))))
    check("coil current before turn-off", i0, None, IOUT_MAX, "A", f"{DS_DRV} Table 6.3 IOUT")
    _, vs = window(w, "vsys", t_x - 1e-4, tm["t_stop"])
    _, vsb = window(w, "vsys_base", t_x - 1e-4, tm["t_stop"])
    vmax = float(max(vs.max(), vsb.max()))
    check("VSYS peak after turn-off", vmax, None, SYS_ABS_MAX, "V", f"{DS_BQ} Table 7.1 SYS abs max 5.5 V{rule}")
    check("VM peak after turn-off", vmax, None, VM_ROC_MAX, "V", f"{DS_DRV} Table 6.3 VM max{rule}")
    _, il = window(w, "ilink", t_x, tm["t_stop"])
    check("link current after turn-off, most negative (back to base)", float(il.min()), None, None, "A", "info")
    _, o2 = window(w, "oa2", t_x, tm["t_stop"])
    check("OUT swing below GND during freewheel", float(o2.min()), None, None, "V", "info (body diode)")
    ta, ia = window(w, "ia", t_x, tm["t_stop"])
    below = np.nonzero(np.abs(ia) < 1e-3)[0]
    t_dec = float(ta[below[0]] - t_x) if len(below) else float("inf")
    check("coil current decay to < 1 mA", t_dec, None, None, "s", "info")


@pytest.mark.slow
def test_turnoff_kick_monte_carlo(main, base, check):
    """USB, charge done, nominal coil (25 C, 4.3 mH), coast from full-step hold: each VSYS MLCC (9 parts on both
    boards) at its vendor typical DC-bias derating at 5 V times a uniform draw within its MPN tolerance, 200 draws."""
    sup = SUP["VBUS5.5-done"]
    refs = vsys_caps(main) + ["base:" + r for r in vsys_caps(base)]
    tol_of = {r: (mlcc_tol(base, r[5:]) if r.startswith("base:") else mlcc_tol(main, r)) for r in refs}
    typ = vsys_cscale(main, base, V_DCBIAS_KICK, worst=False)
    rng = np.random.default_rng(7)
    vmax = []
    for _ in range(200):
        cs = {r: typ[r] * (1 + float(rng.uniform(-tol_of[r], tol_of[r]))) for r in refs}
        w, tm = run_stepping(main, base, sup, 25, 446, nsteps=0, stall=True, rds=RDS_TYP, lph=L_NOM, other=3e-3,
                             end="coast", cscale=cs, aged=False, t_pre=1.5e-3, t_hold=0.2e-3, t_tail=0.5e-3)
        _, vs = window(w, "vsys", tm["t_x"] - 1e-4, tm["t_stop"])
        _, vsb = window(w, "vsys_base", tm["t_x"] - 1e-4, tm["t_stop"])     # BQ25180 SYS pin is on the base board
        vmax.append(float(max(vs.max(), vsb.max())))
    vmax = np.array(vmax)
    check("VSYS peak after coast, MC mean (200 draws)", float(vmax.mean()), None, None, "V", "info")
    check("VSYS peak after coast, MC max (200 draws)", float(vmax.max()), None, SYS_ABS_MAX, "V",
          f"{DS_BQ} Table 7.1 SYS abs max")


def pwm_hold_ctrl(theta_deg, d_pk, t_start, t_hold, fpwm=25e3):
    """The firmware's slow-decay PWM (firmware.md §5.3) held at one field angle: coil A d_pk cos, coil B d_pk sin."""
    tpwm = 1.0 / fpwm
    n = int(round(t_hold / tpwm))
    tr = {k: [] for k in ("MOT_A_IN1", "MOT_A_IN2", "MOT_B_IN1", "MOT_B_IN2")}
    th = math.radians(theta_deg)
    for coil, val in (("A", d_pk * math.cos(th)), ("B", d_pk * math.sin(th))):
        hi, pw = (f"MOT_{coil}_IN1", f"MOT_{coil}_IN2") if val >= 0 else (f"MOT_{coil}_IN2", f"MOT_{coil}_IN1")
        on = abs(val)
        for p in range(n):
            tp = t_start + p * tpwm
            tr[hi].append((tp, 1))
            if on <= 0.001:
                tr[pw].append((tp, 1))
            elif on >= 0.999:
                tr[pw].append((tp, 0))
            else:
                tr[pw].append((tp, 0))
                tr[pw].append((tp + on * tpwm, 1))
    return tr, t_start + n * tpwm


def firmware_coast_peak(main, base, theta, *, sup=None, temp=-10, tol=-0.10, lph=L_MAX):
    """Firmware drive (firmware.md §5.3 slow-decay PWM) held at field angle theta, then all IN low + nSLEEP low (coast).
    Returns (coil current vector before the coast, VSYS peak on either board). The amplitude is the pre-MD-3
    d = 160 mA x 20.3 Ohm / VSYS_idle: at the -10 C corner that is 15 % more duty than the MD-3 rule (17.58 Ohm), i.e.
    a higher coil current and coast peak, so it is kept as the conservative bound (and the MD-5 numbers cite it)."""
    sup = sup or SUP["VBUS5.5-done"]
    d_pk = min(1.0, FW_I_TARGET * FW_R_COIL_OLD / sup.vsys_idle)
    t_on, t_e = 50e-6, 100e-6
    tr, t_x = pwm_hold_ctrl(theta, d_pk, t_e, max(3e-3, 6 * lph / 15))
    tr["MOT_NSLEEP"] = [(t_on, 1)]
    for k in tr:
        tr[k].append((t_x, 0))
    t_stop = t_x + 1e-3
    deck = new_deck(f"firmware drive coast {theta}")
    power(deck, main, base, sup, temp, other=3e-3, aged=False,
          cscale=vsys_cscale(main, base, V_DCBIAS_KICK, worst=True))
    drivers(deck, main, temp, rds=RDS_TYP, tol=tol, lph=lph)
    for net, pts in tr.items():
        gpio_out(deck, main, net, _pwl(pts, edge=20e-9))
    deck.tran("1u", f"{t_stop:.6g}", 0, "2u")
    vs = main.node("VSYS")
    deck.wave("i(via)", "i(vib)", f"v({vs})", "v(nb_vsys)")
    res = deck.run()
    check_ran(res)
    w = res["waves"]
    t = w["time"]
    i0 = math.hypot(float(np.interp(t_x - 1e-6, t, w["i(via)"])), float(np.interp(t_x - 1e-6, t, w["i(vib)"])))
    m = t >= t_x - 1e-4
    return i0, float(max(w[f"v({vs})"][m].max(), w["v(nb_vsys)"][m].max()))


@pytest.mark.parametrize("theta", [0, 45], ids=["full-step-position", "mid-step-45deg"])
def test_firmware_drive_coast_kick(main, base, check, theta):
    """Verifier addition. The drive firmware.md §5.3 actually uses (8-µstep sine, slow decay; amplitude at the
    conservative pre-MD-3 d = 160 mA x 20.3 Ohm / VSYS_idle, see firmware_coast_peak) held at one field angle, then
    coast: a stop at the full-step position that skips the MD-1 brake (θ = 0, one coil at the full-step position; MD-1
    makes every firmware stop path brake first, so this bounds a reset right after SETTLE) or an MCU reset /
    brown-out / HardFault mid-move (θ = 45°, both coils at 0.71 x), where the nRF pins
    float, the DRV8837 pulldowns give IN = 00 and nSLEEP = 0, and firmware cannot brake first. Worst corner: USB, charge
    done (BATFET off), -10 C, coil -10 %, L 10 mH, VSYS MLCCs at vendor DC bias minus tolerance, 3 mA other load.
    Guards fix MD-5 (main C2, C6, C41 and base C4 now 25 V CL10A106MA8NRNC): 5.31 V (θ = 0) / 5.36 V (θ = 45°), C_eff
    32.1 uF at 5 V, i.e. 140-190 mV below 5.5 V (was about 50 mV with the 10 V parts). X5R ageing (x0.93) and the -10 C
    bias-TCC (x0.97), not modelled, take θ = 45° to about 5.44 V."""
    i0, vmax = firmware_coast_peak(main, base, theta)
    check("firmware drive: coil current vector before coast", i0, None, IOUT_MAX, "A", f"{DS_DRV} Table 6.3 IOUT")
    check("VSYS peak after coast from the firmware drive (IDLE entry / MCU reset)", vmax, None, SYS_ABS_MAX, "V",
          f"{DS_BQ} Table 7.1 SYS abs max 5.5 V")


# ------------------------------------------------ VM decoupling structure (SPEC §5.6)
VM_BYPASS_MIN = 0.1e-6       # DRV8837 §5 Pin Functions (VM) / §9.1: 0.1 uF ceramic bypass rated for VM, per device
VM_BULK_MIN = 10e-6          # SPEC §5.6: "0.1 uF each + one 10 uF 0805 shared" on the DRV8837 VM pins
VM_BULK_CASE_MM = 2.0        # SPEC §5.6: the shared bulk is an 0805 (2012 metric, 2.0 mm long; an 0603 is 1.6 mm)
SRC_VM_CAPS = (f"SPEC §5.6 (VM <- VSYS: 0.1 uF each + one 10 uF 0805 shared); {DS_DRV} §5 Pin Functions / §9.1 "
               f"(0.1 uF VM bypass); {DS_DRV} §8.1 gives no bulk value (system-level)")
DRIVERS = ("U40", "U41")


def vm_caps(d):
    """The DRV8837 VM decoupling as the netlist has it: fitted capacitors from the drivers' VM net to GND on the
    drivers' own schematic sheet (netlist Sheetname of U40/U41), split into the shared bulk (>= 10 uF nominal) and the
    per-device bypass (0.1 uF class). Every main VSYS cap is on one SPICE node here (no PCB inductance between them),
    so only this sheet-local structure says whether the bulk sits at the drivers as SPEC §5.6 asks."""
    vm = {d.funcs[r]["VM"] for r in DRIVERS}
    assert len(vm) == 1, f"U40/U41 VM pins on different nets: {vm}"
    vm = vm.pop()
    sheets = {d.comps[r]["props"].get("Sheetname") for r in DRIVERS}
    caps = sorted((r for r in d.on_net(vm, "C") if d.fitted(r) and set(d.pins[r].values()) == {vm, "GND"}
                   and d.comps[r]["props"].get("Sheetname") in sheets), key=lambda r: -d.value(r))
    eps = 1 - 1e-9                      # '10u' parses to 10 x 1e-6 = 9.999999999999999e-06 (float rounding)
    bulk = [r for r in caps if d.value(r) >= VM_BULK_MIN * eps]
    bypass = [r for r in caps if VM_BYPASS_MIN * eps <= d.value(r) < VM_BULK_MIN * eps]
    return vm, caps, bulk, bypass


def test_vm_capacitors_per_spec(main, base, check):
    """Structural (netlist) check of the DRV8837 VM decoupling against SPEC §5.6 and the DRV8837 datasheet: one 0.1 uF
    bypass per device, one shared >= 10 uF 0805 bulk on the detent sheet, each rated above the highest VM (DS §8.1:
    'the voltage rating for bulk capacitors should be higher than the operating voltage, to provide margin for cases
    when the motor transfers energy to the supply'; VSYS may reach the 5.5 V BQ25180 abs max on a coast). The DS gives
    no numeric bulk value (§8.1: system-level testing), so the bulk's DC-bias-derated value is recorded as info; the
    electrical consequence of the total is the coast check (test_firmware_drive_coast_kick)."""
    vm, caps, bulk, bypass = vm_caps(main)
    check(f"VM bypass caps (0.1 uF class) on the driver sheet, one per DRV8837 ({' '.join(bypass)})", len(bypass),
          len(DRIVERS), None, "", SRC_VM_CAPS)
    check(f"shared VM bulk caps (>= 10 uF nominal) on the driver sheet ({' '.join(bulk)})", len(bulk), 1, None, "",
          SRC_VM_CAPS)
    for r in bulk:
        check(f"{r} case size, body length (SPEC §5.6: 0805 or larger)", cap_case_len_mm(main, r), VM_BULK_CASE_MM,
              None, "mm", "SPEC §5.6 (one 10 uF 0805 shared)")
    for r in caps:
        check(f"{r} voltage rating vs the highest VM (VSYS abs max)", cap_vrated(main, r), SYS_ABS_MAX, None, "V",
              f"{DS_DRV} §8.1 bulk rating above the operating voltage; {DS_BQ} Table 7.1 SYS 5.5 V")
    cs = vsys_cscale(main, base, V_DCBIAS_KICK, worst=True)
    c_bulk = sum(main.value(r) * cs[r] for r in bulk)
    check("shared VM bulk, effective at 5 V (vendor DC bias, minus MPN tolerance)", c_bulk, None, None, "F",
          f"info: {SRC_DCBIAS}")
    check("shared VM bulk share of the effective VSYS capacitance at 5 V", c_bulk / vsys_ceff(main, base, cs), None,
          None, "", "info")


@pytest.mark.fault
def test_fault_c74_left_off_is_detected(main, base, check):
    """Fault (verifier addition): C74, the shared 10 uF VM bulk cap (SPEC §5.6), left off. Before MD-5 the
    firmware-drive coast caught it (5.59 V > 5.5 V). With the 25 V VSYS caps (MD-5) the design no longer depends on
    C74 for that limit: at the worst corner the mid-step coast peaks at 5.48 V without C74 vs 5.36 V with it (C_eff
    27.6 vs 32.1 uF at 5 V), and no other electrical limit in this file separates the two (DRV8837 VM abs max 12 V,
    operating max 11 V; the DRV8837 has no VM UVLO, DS §7.3.4; BQ25180 SYS abs max 5.5 V; no VM ripple limit is
    documented; the closest full-step limit, VSYS min 3.013 V vs 3.0 V at VBAT 3.3 V / -10 C, moves 1 mV without C74;
    all main VSYS caps share one SPICE node, so C74's locality is not modelled). Only the unmodelled X5R
    ageing and -10 C bias-TCC would push it to about 5.57 V (5.44 V fitted). So the SPEC §5.6 structural check of
    test_vm_capacitors_per_spec must catch it; the coast peak is recorded as info."""
    main.remove("C74")
    _, _, bulk, _ = vm_caps(main)
    assert len(bulk) < 1, f"fault not detected: shared VM bulk caps {bulk}"
    check("FAULT C74 left off: shared VM bulk caps (>= 10 uF) on the driver sheet (must be < 1)", len(bulk), None, 0,
          "", f"{SRC_VM_CAPS} (fault detected when below 1)")
    i0, vmax = firmware_coast_peak(main, base, 45)
    check("FAULT C74 left off: VSYS peak after a mid-step coast (worst corner)", vmax, None, None, "V",
          f"info: below the {DS_BQ} 5.5 V abs max since MD-5 (25 V VSYS caps); 5.36 V with C74 fitted")


# ------------------------------------------------ firmware drive: 25 kHz slow-decay 8-µstep sine
def microstep_ctrl(pps, n_full, t_start, vsys_meas, i_target=FW_I_TARGET, fpwm=25e3, t_hold0=1e-3,
                   r_eff=FW_R_COIL_OLD):
    """PWM command lists for the four IN pins (firmware.md §5.3). Positive current: IN1 = 1, IN2 PWM with duty
    1 - |d| (IN2 high = brake/slow decay). Edge-aligned 'up' counter: the drive part comes first.
    µstep 0 is held for t_hold0 first (the firmware's pre-energise, shortened to > 5 L/R).
    Amplitude d_peak = min(1, i_target x r_eff / vsys_meas): r_eff = fw_r_eff(T) is the MD-3 rule, the default
    FW_R_COIL_OLD the pre-MD-3 fixed 20.3 Ohm."""
    d_pk = min(1.0, i_target * r_eff / vsys_meas)
    tpwm = 1.0 / fpwm
    t_ustep = 1.0 / (pps * 8)
    n_pwm = int(round(t_ustep / tpwm)) or 1
    tr = {n: [] for n in ("MOT_A_IN1", "MOT_A_IN2", "MOT_B_IN1", "MOT_B_IN2")}
    t = t_start
    seq = [0] * int(round(t_hold0 / (n_pwm * tpwm))) + list(range(n_full * 8 + 1))
    t_step0 = t_start + (len(seq) - n_full * 8 - 1) * n_pwm * tpwm
    for u in seq:
        th = math.radians(11.25 * u)
        for coil, val in (("A", d_pk * math.cos(th)), ("B", d_pk * math.sin(th))):
            hi, pw = (f"MOT_{coil}_IN1", f"MOT_{coil}_IN2") if val >= 0 else (f"MOT_{coil}_IN2", f"MOT_{coil}_IN1")
            on = abs(val)
            for p in range(n_pwm):
                tp = t + p * tpwm
                tr[hi].append((tp, 1))
                if on >= 0.999:
                    tr[pw].append((tp, 0))
                elif on <= 0.001:
                    tr[pw].append((tp, 1))
                else:
                    tr[pw].append((tp, 0))
                    tr[pw].append((tp + on * tpwm, 1))
        t += n_pwm * tpwm
    return {n: _pwl(v, edge=20e-9) for n, v in tr.items()}, t, d_pk, t_step0


MICRO_CASES = [("VBAT3.7-25C", "VBAT3.7", 25, None), ("VBUS5.0-25C", "VBUS5.0", 25, "slow"),
               # sensitivity: the detent sheet's own VM caps left off (C70, C72 100 nF, C74 10 uF)
               ("VBAT3.7-25C-without-C70-C72-C74", "VBAT3.7", 25, "slow"),
               ("VBAT3.7-60C", "VBAT3.7", 60,
                "DESIGN ISSUE (old-rule evidence for MD-3): the pre-MD-3 sine microstepping used a fixed 20.3 Ohm coil "
                "in d = I x R / VSYS and a 160 mA peak, so the hot coil (60 C, 22.8 Ohm) gets < 160 mA and the torque "
                "vector (1/sqrt2 of full step) falls below the 0.5 N load budget. The MD-3 duty is guarded by "
                "test_firmware_microstep_pwm_with_fw_rule")]


def _micro_marks(tag):
    if tag is None:
        return []
    if tag == "slow":
        return [pytest.mark.slow]
    return [pytest.mark.xfail(strict=True, reason=tag)]


def run_microstep(main, base, check, cid, sup, temp, *, r_eff=FW_R_COIL_OLD, duty_src=None, rule="", vsys_meas=None):
    """The real drive: 446 PPS, 8 µsteps, 25 kHz PWM, slow decay, d scaled by the idle VSYS (amplitude
    i_target x r_eff / VSYS_idle). Checks the VM ripple from the 25 kHz current pulses, VSYS peak, BAT pin, link
    current and the torque-vector magnitude. `rule` is appended to the sources of the limit checks. vsys_meas: the idle
    VSYS firmware measured and scales d with (default: the true idle VSYS of sup)."""
    pps, n_full = 446, 1
    t_on, t_e = 50e-6, 100e-6                         # the firmware's 1 ms wake wait adds nothing here (twake 30 us)
    vmeas = sup.vsys_idle if vsys_meas is None else vsys_meas
    ctrl, t_end, d_pk, t_s0 = microstep_ctrl(pps, n_full, t_e, vmeas, r_eff=r_eff)
    ctrl["MOT_NSLEEP"] = _pwl([(t_on, 1)])
    deck = new_deck(f"microstep {cid}")
    power(deck, main, base, sup, temp, cscale=vsys_cscale(main, base, sup.vsys_idle, worst=True))
    # rotor turns from the first µstep on, field angle 11.25 deg per µstep -> emf phase reference t_s0
    drivers(deck, main, temp, rds=RDS_MAX, ke=KE_MAX, pps=pps, t0=t_s0, tg=t_s0, tstop=t_end)
    for net, pts in ctrl.items():
        gpio_out(deck, main, net, pts)
    deck.tran("1u", f"{t_end:.6g}", 0, "2u")       # every PWM edge is a PWL breakpoint; 0.2 us steps give the same
    vs = main.node("VSYS")
    deck.wave("i(via)", "i(vib)", f"v({vs})", "v(nb_vbat)", "i(vlink)")
    res = deck.run()
    check_ran(res)
    w = res["waves"]
    t1 = t_s0                                           # the full step after the pre-energise
    t, ia = window(w, "i(via)", t1, t_end)
    _, ib = window(w, "i(vib)", t1, t_end)
    _, v = window(w, f"v({vs})", t1, t_end)
    _, il = window(w, "i(vlink)", t1, t_end)
    ivec = tavg(t, np.sqrt(ia ** 2 + ib ** 2))
    check("PWM duty amplitude d_peak", d_pk, None, 1.0, "",
          duty_src or f"pre-MD-3 {FW} §5.3 d = 160 mA x 20.3 Ohm / VSYS")
    check("µstep current-vector magnitude", ivec, None, None, "A", "info")
    # rating condition at the same speed: ideal 3.3 V two-phase-on full step (vector = sqrt2 x avg |i| per coil)
    iref = rated_reference(pps, KE_MAX, L_NOM, False)
    f_micro = F_RATED * ivec / (math.sqrt(2) * iref)
    check("VM ripple pk-pk, 25 kHz PWM", float(v.max() - v.min()), None, None, "V", "info")
    check("VM (VSYS) max, 25 kHz PWM", float(v.max()), None, SYS_ABS_MAX, "V", f"{DS_BQ} Table 7.1 SYS abs max{rule}")
    check("link current per VSYS contact, 25 kHz PWM", float(il.max()) * SHARE_WORST, None, JST_I_CONTACT, "A",
          "JST SH 1 A/contact (SPEC §2)" + rule)
    if not sup.usb:
        _, vb = window(w, "v(nb_vbat)", t1, t_end)
        check("BAT pin min, 25 kHz PWM", float(vb.min()), VBUVLO, None, "V", f"{DS_BQ} VBUVLO 3.0 V{rule}")
    # last, so a strict xfail on the thrust budget still records every datasheet check above
    check("µstep thrust estimate (vs 2-phase-on rating at 446 PPS)", f_micro, F_NEED, None, "N",
          "detent research load <= 0.5 N; rating assumed 2-2 phase full step at 3.3 V (sqrt2 x I vector)" + rule)
    return d_pk, ivec, f_micro


@pytest.mark.parametrize("cid,supname,temp,xf", [pytest.param(*c, marks=_micro_marks(c[-1]), id=c[0])
                                                 for c in MICRO_CASES])
def test_firmware_microstep_pwm(main, base, check, cid, supname, temp, xf):
    """The real drive (446 PPS, 8 µsteps, 25 kHz PWM, slow decay, d scaled by the idle VSYS) with the pre-MD-3 duty
    d = 160 mA x 20.3 Ohm / VSYS (see run_microstep). At 25 C the MD-3 duty is 0.15 % higher (20.33 Ohm); the 60 C
    case is the strict-xfail evidence for MD-3."""
    sup = SUP[supname]
    if "without" in cid:
        for ref in ("C70", "C72", "C74"):
            main.remove(ref)
    run_microstep(main, base, check, cid, sup, temp)


MD3_CASES = [  # id, true idle VSYS (battery), idle VSYS firmware measures (None = true), temp, strict-xfail reason
    # the strict xfail's own corner
    ("VBAT3.7-60C", 3.7, None, 60, None),
    # lowest idle VSYS a non-park move may start from (MD-2): d_peak clamps at 1 there (MD-3 needs >= 3.69 V at 60 C)
    ("VBAT3.55-60C", FW_VSYS_MOVE, None, 60, None),
    # the same at the calibration temperature (reviewer addition)
    ("VBAT3.55-25C", FW_VSYS_MOVE, None, 25, None),
    # reviewer addition: MD-2 gates on the measured VSYS, and at 60 C firmware.md §12.4 lets the reading be 46 mV high,
    # so a move can start from a true 3.504 V (d_peak is clamped at 1 either way)
    ("VBAT3.504-60C-reads-3.55", FW_VSYS_MOVE - FW_ADC_HIGH, FW_VSYS_MOVE, 60, None),
    # coldest corner at the lowest non-park VSYS: the worst corner of the MD-3 rule
    ("VBAT3.55--10C", FW_VSYS_MOVE, None, -10,
     "DESIGN ISSUE (firmware rule insufficient): at -10 C the MD-3 duty d = I x (20 Ohm x (1 + 0.00393 x (T - 25 C)) "
     "+ 0.33 Ohm) / VSYS lowers the drive to 160 mA x 17.58 Ohm = 2.81 V, but the back-EMF (upper ke) and the cold "
     "pack sag do not shrink with it, so at 446 PPS the current vector falls to about 121 mA and the thrust estimate "
     "to about 0.493 N < the 0.5 N load budget at VSYS idle 3.55 V (about 0.495 N at 3.7 V, 0.498 N at 4.2 V). The "
     "pre-MD-3 20.3 Ohm gave about 0.585 N; not reducing the duty below 25 C (T -> max(T, 25 C)) would keep it"),
]


@pytest.mark.parametrize("cid,vbat,vmeas,temp,xf", [
    pytest.param(*c, marks=[pytest.mark.xfail(strict=True, reason=c[-1])] if c[-1] else [], id=c[0])
    for c in MD3_CASES])
def test_firmware_microstep_pwm_with_fw_rule(main, base, check, cid, vbat, vmeas, temp, xf):
    """Guard for MD-3 (firmware.md §5.3: d_peak = I_target x (20 Ohm x (1 + 0.00393 x (T - 25 C)) + 0.33 Ohm) / VSYS,
    clamp d <= 1, T = nRF die temperature, here equal to the coil / ambient temperature). Same deck as the strict
    xfail test_firmware_microstep_pwm[VBAT3.7-60C] (446 PPS, rDS(on) max, upper back-EMF, worst VSYS caps): the
    torque vector must stay above the 0.5 N load budget and every other limit of that test must hold, at that corner,
    at the lowest non-park VSYS (MD-2, 3.55 V idle; also when it reads 46 mV high, firmware.md §12.4) and at the cold
    end."""
    sup = SUP["VBAT3.7"] if vbat == 3.7 else Supply(f"VBAT{vbat:.3f}", vbat)
    r_eff = fw_r_eff(temp)
    check(f"MD-3 R_eff at {temp} C (firmware.md §5.3 formula)", r_eff, None, None, "Ohm", f"info: {SRC_MD3}")
    rule = f"; firmware rule {SRC_MD3}"
    if vmeas is not None:
        check("idle VSYS firmware measures (true idle VSYS is the supply)", vmeas, None, None, "V", f"info: {SRC_ADC}")
        rule += f"; MD-2 threshold {FW_VSYS_MOVE:.2f} V measured, read {(vmeas - vbat) * 1e3:.0f} mV high ({SRC_ADC})"
    run_microstep(main, base, check, f"{cid}-MD-3", sup, temp, r_eff=r_eff, duty_src=SRC_MD3, rule=rule,
                  vsys_meas=vmeas)


# ------------------------------------------------ nSLEEP wake timing
def wake_run(main, base, v3, scale=None):
    deck = new_deck("nSLEEP wake")
    power(deck, main, base, SUP["VBAT3.7"], 25, v3=v3)
    deck += main.passives(nets={"MOT_NSLEEP", "GND"}, scale=scale)
    drivers(deck, main, 25, twake=TWAKE_MAX)
    t_on = 20e-6
    t_e = t_on + FW_WAKE_WAIT
    ctrl = {"MOT_NSLEEP": _pwl([(t_on, 1)]), "MOT_A_IN1": _pwl([(t_e, 1)]), "MOT_A_IN2": 0, "MOT_B_IN1": 0,
            "MOT_B_IN2": 0}
    for net, c in ctrl.items():
        gpio_out(deck, main, net, c)
    t_stop = t_e + FW_PRE_ENERGISE
    deck.tran("1u", f"{t_stop:.6g}", 0, "2u")
    ns = main.node("MOT_NSLEEP")
    deck.meas(f"tran vns FIND v({ns}) AT={t_on + 200e-6:.6g}")
    deck.meas(f"tran t_act WHEN v(xu40.en)=0.5 RISE=1")
    deck.meas(f"tran i_end FIND i(via) AT={t_stop:.6g}")
    deck.wave("i(via)")
    res = deck.run()
    errs = [e for e in res["_errors"] if not e.strip().startswith("meas")]   # t_act legitimately fails if no wake
    assert not errs, errs[:5]
    w = res["waves"]
    i_end = res.get("i_end", 0.0)
    above = np.nonzero(w["i(via)"] >= 0.9 * i_end)[0] if i_end > 1e-3 else []
    res["t90"] = float(w["time"][above[0]]) if len(above) else float("inf")
    return res, t_on, t_e, t_stop


@pytest.mark.parametrize("v3", [2.9, 3.3])
def test_nsleep_wake(main, base, check, v3):
    """MOT_NSLEEP driven by P1.15 (standard drive, VOH spec as 800 Ohm) into R70 || 2x RPD (100 kOhm each, inside
    U40/U41). R70 tolerance corners (extremes). The firmware waits 1 ms after nSLEEP and pre-energises 10 ms."""
    for sc in main.extremes(["R70"]):
        res, t_on, t_e, t_stop = wake_run(main, base, v3, scale=sc)
        tag = f"R70 x{sc['R70']:.2f}, +3V3 {v3} V"
        check(f"nSLEEP high level ({tag})", res.get("vns"), VIH_K_MAX * v3, None, "V", f"{DS_DRV} Table 6.5 VIH max")
        t_act = res.get("t_act", float("inf")) - t_on
        check(f"bridge active after nSLEEP edge ({tag})", t_act, None, FW_WAKE_WAIT, "s",
              f"{FW} §5.2 1 ms wait (>= {DS_DRV} Table 6.6 twake 30 us)")
        t90 = res.get("t90", float("inf")) - t_e
        check(f"coil current settles (90 %) within the pre-energise ({tag})", t90, None, FW_PRE_ENERGISE, "s",
              f"{FW} §5.2 energise 10 ms")
        check(f"coil A current reaches the run level ({tag})", res.get("i_end"), 0.5 * I_RATED, None, "A",
              f"{SRC_RES}: drive must actually energise")


@pytest.mark.fault
def test_fault_r70_wrong_value_is_detected(main, base, check):
    """Fault: R70 fitted as 100 Ohm instead of 100 kOhm (value typo). P1.15 cannot pull nSLEEP above VIH: the
    drivers never wake. The nSLEEP-level check must catch it."""
    main.override("R70", "100")
    res, t_on, t_e, t_stop = wake_run(main, base, 3.3)
    v = res.get("vns")
    assert v is not None and v < VIH_K_MAX * 3.3, f"fault not detected: nSLEEP = {v} V"
    i_end = res.get("i_end", 0.0)
    assert abs(i_end) < 0.5 * I_RATED, f"fault not detected: coil current {i_end} A"
    check("FAULT R70=100: nSLEEP high level (must violate VIH)", v, None, VIH_K_MAX * 3.3, "V",
          f"{DS_DRV} Table 6.5 VIH max (fault detected when below)")


@pytest.mark.fault
def test_fault_c70_solder_short_is_detected(main, base, check):
    """Fault: a solder bridge across C70 (VM bypass, 0402) shorts VSYS to GND. The link / SYS current checks used
    by the hold test must flag it."""
    main.short("C70")
    deck = new_deck("C70 short")
    power(deck, main, base, SUP["VBAT3.7"], 25)
    deck.op()
    deck.print_op("i(vlink)")
    res = deck.run()
    check_ran(res)
    ilink = res["op_0"]
    assert ilink * SHARE_WORST > JST_I_CONTACT and ilink > SYS_I_DC, f"fault not detected: {ilink} A"
    check("FAULT C70 short: SYS current (must exceed 1.5 A)", ilink, SYS_I_DC, None, "A",
          f"{DS_BQ} Table 7.1 SYS DC 1.5 A (fault detected when above)")


@pytest.mark.fault
def test_fault_motor_connector_bridge_trips_ocp(main, base, check):
    """Fault: J40 pins 1-2 (A+/A-, 1.0 mm pitch) solder-bridged. OUT1-OUT2 short: current must exceed IOUT, OCP must
    shut the bridge off within tDEG and retry after tRETRY (DS 7.3.5.2)."""
    deck = new_deck("J40 1-2 bridge")
    power(deck, main, base, SUP["VBAT4.2"], 25)
    drivers(deck, main, 25)
    deck += f"Rbridge {main.pin('J40', '1')} {main.pin('J40', '2')} 0.02"
    t_on = 20e-6
    for net, c in {"MOT_NSLEEP": _pwl([(t_on, 1)]), "MOT_A_IN1": _pwl([(100e-6, 1)]), "MOT_A_IN2": 0,
                   "MOT_B_IN1": 0, "MOT_B_IN2": 0}.items():
        gpio_out(deck, main, net, c)
    deck.tran("50n", "1.4m", 0, "0.5u")
    deck.meas("tran ipk MAX v(xu40.ih1)")
    deck.meas("tran t_off WHEN v(xu40.ok)=0.5 FALL=1")
    deck.meas("tran t_retry WHEN v(xu40.ok)=0.5 RISE=1")
    res = deck.run()
    assert not res["_errors"], res["_errors"][:5]
    ipk = res["ipk"]
    assert ipk > IOUT_MAX, f"fault not detected: {ipk} A"
    check("FAULT J40 bridge: peak OUT current (must exceed IOUT)", ipk, IOUT_MAX, None, "A",
          f"{DS_DRV} Table 6.3 IOUT 1.8 A (fault detected when above)")
    check("OCP retry interval", res["t_retry"] - res["t_off"], 0.8e-3, 1.3e-3, "s", f"{DS_DRV} Table 6.5 tRETRY 1 ms")


# ------------------------------------------------ DRV5032 HOME_N
def hall_variant(d):
    # Design has no public accessor for an overridden value string (harness request); read it the same way value() does
    v = d._override.get("U42", d.comps["U42"]["value"]).upper()
    for k in HALL:
        if f"DRV5032{k}" in v:
            return k
    raise KeyError(f"U42 = {v}: DRV5032 variant not in the HALL table (add its Table 4-1 / 6.5 / 6.6 data)")


def hall_run(d, *, ts, rpull=None, pullup=1, v3=3.3, bop=4.8, brp=0.5, od=0):
    """Field steps: 0 -> B_PARK just after a sample (worst-case latency), then back to 0 just after a sample."""
    deck = new_deck("DRV5032 HOME_N")
    p3 = d.node("+3V3")
    deck += [f"V3v3 n3v3src 0 DC {v3}", f"R3v3 n3v3src {p3} 0.05"]
    deck += d.passives(nets={"+3V3", "GND"}, esr={"C": 0.01})
    ton = 55e-6
    t_on_field = ton + 1e-6
    t_off_field = ton + 2 * ts + 1e-6
    t_stop = ton + 3.2 * ts
    deck += f"Vb bmt 0 PWL(0 0 {t_on_field:.9g} 0 {t_on_field + 1e-6:.9g} {B_PARK} {t_off_field:.9g} {B_PARK} " \
            f"{t_off_field + 1e-6:.9g} 0)"
    deck += (f"XU42 {d.pin('U42', 'VCC')} {d.pin('U42', 'OUT')} {d.pin('U42', 'GND')} bmt DRV5032 params: ts={ts} "
             f"ton={ton} bop={bop} brp={brp} roh={HALL_ROH} rol={HALL_ROL} od={od}")
    hn = d.node("HOME_N")
    deck += d.passives(refs=[r for r in d.on_net("HOME_N") if r[0] in "RC"])   # any pull / filter on HOME_N
    rp = f" rpull={rpull} pullup={pullup}" if rpull else ""
    deck += f"XIN {hn} {p3} 0 NRF_GPIO_IN params: cpad=3p{rp}"
    deck.tran("10u", f"{t_stop:.6g}", 0, "20u")
    deck.meas(f"tran t_low WHEN v({hn})={NRF_VIL_K * v3} FALL=1 from={t_on_field:.9g}")
    deck.meas(f"tran t_high WHEN v({hn})={NRF_VIH_K * v3} RISE=1 from={t_off_field:.9g}")
    deck.meas(f"tran voh FIND v({hn}) AT={t_on_field - 2e-6:.9g}")
    deck.meas(f"tran vol FIND v({hn}) AT={t_off_field - 1e-3:.9g}")
    deck.meas(f"tran vcc_min MIN v({d.pin('U42', 'VCC')})")
    res = deck.run()
    # a WHEN that never happens means HOME_N never crossed the threshold (e.g. an open-drain variant with no pull-up):
    # leave t_low / t_high out (latency = inf) and let the level / latency checks report it, not a simulator error
    errs = [e for e in res["_errors"] if not e.strip().startswith("meas")]
    assert not errs, errs[:5]
    for k in ("voh", "vol", "vcc_min"):
        assert k in res, (k, res["_log"][-2000:])
    return res, t_on_field, t_off_field


@pytest.mark.parametrize("load", ["netlist", "nrf-pullup-13k", "nrf-pulldown-13k"])
def test_home_n_levels_and_latency(main, check, load):
    """HOME_N: DRV5032FA push-pull into P1.14 (netlist: no external pull; firmware: input, no pull). Also with the
    nRF internal pull (13 kOhm typ) enabled by mistake. Levels against the nRF VIH/VIL, output current against the
    DRV5032 limit, and the worst-case latency (field change just after a sample, tS max) against the firmware's
    HOME edge-window lag allowance."""
    var = hall_variant(main)
    hv = HALL[var]
    ts_max = hv["ts"][2]
    rp = {"netlist": None, "nrf-pullup-13k": (13e3, 1), "nrf-pulldown-13k": (13e3, 0)}[load]
    res, t_on, t_off = hall_run(main, ts=ts_max, rpull=rp[0] if rp else None, pullup=rp[1] if rp else 1,
                                bop=hv["bop"], brp=hv["brp"], od=hv["od"])
    v3 = 3.3
    check("HOME_N high (no magnet)", res["voh"], NRF_VIH_K * v3, None, "V", f"{DS_NRF} VIH 0.7 VDD; {DS_HALL} VOH")
    check("HOME_N low (magnet parked)", res["vol"], None, NRF_VIL_K * v3, "V", f"{DS_NRF} VIL 0.3 VDD; {DS_HALL} VOL")
    iout = max(v3 - res["voh"], res["vol"]) / min(HALL_ROH, HALL_ROL)
    check("DRV5032 output current", iout, None, HALL_IOUT_MAX, "A", f"{DS_HALL} Table 6.3 IO")
    lat_on = res.get("t_low", float("inf")) - t_on
    lat_off = res.get("t_high", float("inf")) - t_off
    src = (f"{FW} §5.4 edge window: lag 0.075 s + m 10 steps at 446 PPS ({DS_HALL} tS max {ts_max * 1e3:.0f} ms "
           f"+ tACTIVE 40 us)")
    check("HOME_N assert latency (worst phase, tS max)", lat_on, None, FW_HOME_WINDOW, "s", src)
    check("HOME_N release latency (worst phase, tS max)", lat_off, None, FW_HOME_WINDOW, "s", src)
    check("DRV5032 worst-case latency vs the bare lag term (tS max + tACTIVE)", ts_max + HALL_TACT, None, None, "s",
          f"info: exceeds the 0.075 s lag term by tACTIVE; covered by the m >= 10 step margin ({FW} §5.4)")
    check("DRV5032 VCC min during the 2.7 mA sample pulse", res["vcc_min"], 1.65, None, "V",
          f"{DS_HALL} Table 6.3 VCC min")


@pytest.mark.fault
def test_fault_wrong_hall_variant_is_detected(main, check):
    """Fault: U42 populated as DRV5032FB (5 Hz, tS up to 286 ms) instead of FA. The latency check must catch it."""
    main.override("U42", "DRV5032FBDBZR")
    var = hall_variant(main)
    assert var == "FB"
    ts_max = HALL[var]["ts"][2]
    res, t_on, t_off = hall_run(main, ts=ts_max)
    lat = res.get("t_low", float("inf")) - t_on
    assert lat > FW_HOME_WINDOW, f"fault not detected: latency {lat} s"
    check("FAULT FB variant: HOME_N latency (must exceed the 97 ms window)", lat, FW_HOME_WINDOW, None, "s",
          f"{FW} §5.4 edge window (fault detected when above)")


@pytest.mark.fault
def test_fault_open_drain_hall_variant_is_detected(main, check):
    """Fault (verifier addition): U42 populated as DRV5032FC, which has the same SOT-23 footprint, 4.8 mT omnipolar
    thresholds and 20 Hz rate as the FA but an OPEN-DRAIN output. HOME_N has no pull-up in the netlist and P1.14 is
    'input, no pull' (firmware.md §1.3), so with no magnet HOME_N leaks to GND (IOZ) and reads as 'parked'. The
    HOME_N high-level check of test_home_n_levels_and_latency must catch it."""
    main.override("U42", "DRV5032FCDBZR")
    hv = HALL[hall_variant(main)]
    assert hv["od"] == 1
    res, t_on, t_off = hall_run(main, ts=hv["ts"][2], bop=hv["bop"], brp=hv["brp"], od=hv["od"])
    v = res["voh"]
    assert v < NRF_VIH_K * 3.3, f"fault not detected: HOME_N high level {v} V"
    check("FAULT FC (open-drain) variant: HOME_N with no magnet (must violate VIH)", v, None, NRF_VIH_K * 3.3, "V",
          f"{DS_NRF} VIH 0.7 VDD; {DS_HALL} Table 4-1 open-drain, Table 6.5 IOZ (fault detected when below)")
