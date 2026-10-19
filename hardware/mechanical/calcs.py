#!/usr/bin/env python3
"""dial-me-spinner rev A -- mechanical calculations.

Pure Python + numpy (+ matplotlib for the plots).  Run:

    python3 calcs.py            # print everything, write renders/calc_*.png
    python3 calcs.py --no-plots

Geometry follows hardware/design/SPEC.md section 8 and the constants in
dial_spinner.scad (kept in sync by hand -- the names match).  Every number that
comes from the subsystem research is tagged [research] / [verifier]; every
number that is an assumption is tagged [assume] and is a "to verify on
prototype" item.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERS = os.path.join(HERE, "renders")
G = 9.81

# ---------------------------------------------------------------------------
# Geometry (mm) -- SPEC section 8 / dial_spinner.scad
# ---------------------------------------------------------------------------
RING_RO, RING_RI, RING_H = 35.0, 27.0, 10.0
RING_Z0, RING_Z1 = 15.6, 25.6
MAG_N, MAG_D, MAG_H, RT = 48, 2.0, 2.0, 29.0
POCKET_D, POCKET_H = 2.10, 2.05
B_Z0, B_Z1 = 18.0, 25.0                  # 608
DET_D, DET_H, DET_GAP = 3.0, 2.0, 1.0
MB_Z0 = 29.1
TMAG_PKG_H, TMAG_ELEM_DEPTH = 1.1, 0.73   # SOT-23-6 body (nominal), element below pkg top [research]
GUIDE_R = 29.0
GUIDE_A = (60.0, 180.0, 300.0)

# Materials (g/mm^3)
RHO_316L = 7.98e-3
RHO_NDFEB = 7.5e-3
RHO_PA12GF = 1.25e-3     # [assume] SLS PA12-GF ~1.22, MJF PA12-GB ~1.30
RHO_STEEL = 7.85e-3
RHO_BRASS = 8.5e-3


def annulus(ro, ri, h):
    """volume (mm^3) and I/m factor (mm^2) of a thin-wall annulus about z."""
    v = math.pi * (ro ** 2 - ri ** 2) * h
    return v, 0.5 * (ro ** 2 + ri ** 2)


def hr(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def table(rows, header, fmt=None):
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(x).ljust(w) for x, w in zip(r, widths)))


# ---------------------------------------------------------------------------
# 1. Rotor mass, inertia, CoG
# ---------------------------------------------------------------------------
def rotor_parts():
    parts = []  # (name, mass_g, I_kgm2, z_cg_mm)

    # 316L ring, minus chamfers, knurl grooves, pockets, balance holes
    v, k = annulus(RING_RO, RING_RI, RING_H)
    v_chamf = (2 * math.pi * 34.67 * 0.5            # 1.0x45 top-outer
               + 2 * math.pi * 34.83 * 0.125        # 0.5x45 bottom-outer
               + 2 * 2 * math.pi * 27.17 * 0.125)   # 0.5x45 inner top + bottom
    v_knurl = 120 * (0.6 ** 2 / 2) * 7.0            # 120 straight V grooves (model)
    v_pock = MAG_N * math.pi * (POCKET_D / 2) ** 2 * POCKET_H
    v_bal = 4 * math.pi * 0.8 ** 2 * 3.0
    m_ring = (v - v_chamf - v_knurl - v_pock - v_bal) * RHO_316L
    i_ring = (v * RHO_316L * k
              - v_chamf * RHO_316L * 31.5 ** 2
              - v_knurl * RHO_316L * 34.8 ** 2
              - v_pock * RHO_316L * RT ** 2
              - v_bal * RHO_316L * 31 ** 2) * 1e-9  # g*mm^2 -> kg*m^2
    parts.append(("316L ring 70/54/10 (net)", m_ring, i_ring, 20.55))

    v_mag = math.pi * (MAG_D / 2) ** 2 * MAG_H
    m_mag = MAG_N * v_mag * RHO_NDFEB
    parts.append(("48x N52 Ø2x2 magnets", m_mag, m_mag * RT ** 2 * 1e-9, RING_Z1 - MAG_H / 2))

    # PA12-GF carrier: web, rim, collar, lip, ribs
    segs = [annulus(25.0, 12.2, 2.0), annulus(26.95, 25.0, 2.9), annulus(12.2, 11.0, 9.0),
            annulus(11.0, 9.9, 1.0)]
    zc = [18.0, 17.55, 21.5, 17.5]
    m_c = sum(s[0] for s in segs) * RHO_PA12GF
    i_c = sum(s[0] * s[1] for s in segs) * RHO_PA12GF
    zsum = sum(s[0] * z for s, z in zip(segs, zc)) * RHO_PA12GF
    v_ribs = 12 * 12.5 * 1.2 * 0.8
    m_c += v_ribs * RHO_PA12GF
    i_c += v_ribs * RHO_PA12GF * 19.25 ** 2
    zsum += v_ribs * RHO_PA12GF * 16.6
    parts.append(("PA12-GF carrier", m_c, i_c * 1e-9, zsum / m_c))

    # 608-2Z rotating share: outer ring + shields + half balls/cage [assume split of 13 g]
    m_or = 5.5 + 1.0 + 0.5 * (7 * (math.pi / 6 * 3.97 ** 3) * RHO_STEEL + 0.5)
    parts.append(("608-2Z rotating share", m_or, m_or * 10.3 ** 2 * 1e-9, 21.5))
    parts.append(("wave spring + retainer", 0.6, 0.6 * 10.5 ** 2 * 1e-9, 25.5))
    parts.append(("adhesive (bond line, magnets)", 0.4, 0.4 * 27 ** 2 * 1e-9, 20.0))
    return parts


def rotor_summary(parts):
    m = sum(p[1] for p in parts)
    i = sum(p[2] for p in parts)
    z = sum(p[1] * p[3] for p in parts) / m
    return m, i, z


# ---------------------------------------------------------------------------
# 2. SKF frictional-moment model (deep-groove ball bearings), N*mm
# ---------------------------------------------------------------------------
BEARINGS = {
    # d, D, C0 (N), R1, R2, S1, S2  -- SKF Table 2a [research, verifier re-implemented]
    "608-2Z": dict(d=8, D=22, C0=1370, R1=4.1e-7, R2=1.7, S1=3.73e-3, S2=14.6),
    "61808 (6808)": dict(d=40, D=52, C0=3750, R1=4.7e-7, R2=1.7, S1=6.5e-3, S2=0.78),
}


def skf_moment(n_rpm, nu, fa, fr, b, krs=3e-8, kz=3.1, mu_bl=0.12, mu_ehl=0.04):
    n = max(n_rpm, 1e-3)
    d, D = b["d"], b["D"]
    dm = 0.5 * (d + D)
    alpha = math.radians(24.6 * (fa / b["C0"]) ** 0.24)
    s = math.sin(alpha)
    grr = b["R1"] * dm ** 1.96 * (fr + b["R2"] / s * fa) ** 0.54
    gsl = b["S1"] * dm ** -0.145 * (fr ** 5 + b["S2"] * dm ** 1.5 / s * fa ** 4) ** (1 / 3)
    phi_ish = 1 / (1 + 1.84e-9 * (n * dm) ** 1.28 * nu ** 0.64)
    phi_rs = 1 / math.exp(krs * nu * n * (d + D) * math.sqrt(kz / (2 * (D - d))))
    mrr = phi_ish * phi_rs * grr * (nu * n) ** 0.6
    phi_bl = 1 / math.exp(2.6e-8 * (n * nu) ** 1.4 * dm)
    mu_sl = phi_bl * mu_bl + (1 - phi_bl) * mu_ehl
    return mrr + gsl * mu_sl


def spin_down(I, n0_rps, torque_nmm, c_lin=0.0, k_air=0.0, n_stop=0.05, dt=0.01, tmax=1200):
    """integrate I dw/dt = -M(n) - c*w - k*w^2.  returns t, n(rps) arrays."""
    w = 2 * math.pi * n0_rps
    t = 0.0
    ts, ns = [0.0], [n0_rps]
    while w / (2 * math.pi) > n_stop and t < tmax:
        n_rps = w / (2 * math.pi)
        m = torque_nmm(n_rps * 60) * 1e-3 + c_lin * w + k_air * w * w
        h = dt if w > 5 else dt / 4
        w -= m / I * h
        t += h
        if len(ts) < 40000 and (int(t / 0.1) != int((t - h) / 0.1)):
            ts.append(t)
            ns.append(max(w, 0) / (2 * math.pi))
    ts.append(t)
    ns.append(0.0)
    return np.array(ts), np.array(ns)


# ---------------------------------------------------------------------------
# 3. Detent model
# ---------------------------------------------------------------------------
LUT_OFF = np.array([0.0, 1.5, 3.0, 5.0, 7.5])          # mm, in-plane radial offset [verifier]
LUT_T = np.array([16.5, 9.5, 2.0, 0.14, 0.0027])        # mN*m peak detent torque [verifier]
N_DET = 24


def detent_torque(off):
    """log-linear interpolation of the verified LUT (mN*m)."""
    return float(np.exp(np.interp(off, LUT_OFF, np.log(LUT_T))))


def ring_down(I, t1_mnm, m_bear_nmm_fn, m_shoe_mnm=0.0, theta0_deg=6.0, tmax=20.0, dt=2e-4,
              settle_deg=0.5):
    """release in a detent well at theta0 (deg from the well bottom), Coulomb friction."""
    t1 = t1_mnm * 1e-3
    th = math.radians(theta0_deg)
    w = 0.0
    t = 0.0
    ts, ths = [], []
    peaks = 0
    last_sign = 0
    t_settle = None
    amp = abs(th)
    while t < tmax:
        torque = -t1 * math.sin(N_DET * th)
        n_rpm = abs(w) * 60 / (2 * math.pi)
        fr = m_bear_nmm_fn(n_rpm) * 1e-3 + m_shoe_mnm * 1e-3
        if abs(w) < 1e-6:
            if abs(torque) <= fr:          # stuck
                t_settle = t_settle or t
                break
            fr_dir = -math.copysign(fr, torque)
        else:
            fr_dir = -math.copysign(fr, w)
        a = (torque + fr_dir) / I
        w_new = w + a * dt
        if w != 0 and math.copysign(1, w_new) != math.copysign(1, w):   # velocity reversal -> peak
            peaks += 1
            amp = abs(th)
            w_new = 0.0
            if t_settle is None and math.degrees(amp) < settle_deg:
                t_settle = t
        w = w_new
        th += w * dt
        t += dt
        if int(t / 0.002) != int((t - dt) / 0.002):
            ts.append(t)
            ths.append(math.degrees(th))
    return np.array(ts), np.array(ths), peaks, t_settle


# ---------------------------------------------------------------------------
# 4. Press-click model: 3 springs + 3 up-stops at r = 29, centre switch
# ---------------------------------------------------------------------------
def click_force(r, theta_deg, P0, k, W, g_act, F_sw):
    """minimum applied force at (r, theta) that actuates the centre switch.

    FA is rigid: delta(x,y) = d0 + a*x + b*y (down positive).  Stops are unilateral
    (delta_i >= 0, reaction S_i >= 0 pushing down).  Springs push up with P0 + k*delta_i.
    Switch actuates when delta at the centre = g_act with reaction F_sw.
    """
    pts = [(GUIDE_R * math.cos(math.radians(a)), GUIDE_R * math.sin(math.radians(a))) for a in GUIDE_A]
    xf, yf = r * math.cos(math.radians(theta_deg)), r * math.sin(math.radians(theta_deg))
    best = None
    import itertools
    for na in (0, 1, 2):
        for act in itertools.combinations(range(3), na):
            # unknowns: F, a, b, S_act...
            nu = 3 + na
            A = np.zeros((nu, nu))
            rhs = np.zeros(nu)
            # vertical: F + W + sum S - sum(P0 + k(d0 + a x + b y)) - F_sw = 0
            A[0, 0] = 1
            A[0, 1] = -k * sum(p[0] for p in pts)
            A[0, 2] = -k * sum(p[1] for p in pts)
            for j, i in enumerate(act):
                A[0, 3 + j] = 1
            rhs[0] = 3 * P0 + 3 * k * g_act + F_sw - W
            # moment about x (y lever) and about y (x lever); W and switch at origin
            for row, c in ((1, 1), (2, 0)):
                A[row, 0] = (yf if c == 1 else xf)
                A[row, 1] = -k * sum(p[0] * p[c] for p in pts)
                A[row, 2] = -k * sum(p[1] * p[c] for p in pts)
                for j, i in enumerate(act):
                    A[row, 3 + j] = pts[i][c]
                rhs[row] = (P0 + k * g_act) * sum(p[c] for p in pts)
            # contact rows: d0 + a x_i + b y_i = 0
            for j, i in enumerate(act):
                A[3 + j, 1] = pts[i][0]
                A[3 + j, 2] = pts[i][1]
                rhs[3 + j] = -g_act
            try:
                sol = np.linalg.solve(A, rhs)
            except np.linalg.LinAlgError:
                continue
            F, a, b = sol[:3]
            S = sol[3:]
            deltas = [g_act + a * p[0] + b * p[1] for p in pts]
            ok = all(s >= -1e-9 for s in S) and all(
                deltas[i] >= -1e-9 for i in range(3) if i not in act) and F > 0
            if ok and (best is None or F < best[0]):
                best = (F, deltas, act)
    return best


def tip_force(r_press, W_dev, edge_dist):
    """force at r_press (beyond the support edge) that tips the device."""
    if r_press <= edge_dist:
        return float("inf")
    return W_dev * edge_dist / (r_press - edge_dist)


# ---------------------------------------------------------------------------
def main(plots=True):
    print("dial-me-spinner rev A -- mechanical calculations (calcs.py)")
    print("Geometry: SPEC.md section 8; assumptions tagged [assume]; research values [research]/[verifier].")

    # ---------------- 1. rotor -------------------------------------------
    hr("1. Rotor mass, moment of inertia, centre of gravity")
    parts = rotor_parts()
    rows = [(p[0], f"{p[1]:.2f}", f"{p[2]:.3e}", f"{p[3]:.2f}") for p in parts]
    m_r, I_r, z_r = rotor_summary(parts)
    rows.append(("TOTAL rotor", f"{m_r:.2f}", f"{I_r:.3e}", f"{z_r:.2f}"))
    table(rows, ["part", "mass g", "I kg*m^2", "z_cg mm"])
    print(f"\nBearing mid-plane z = {(B_Z0 + B_Z1) / 2:.2f} mm; rotor CoG offset = {z_r - (B_Z0 + B_Z1) / 2:+.2f} mm "
          "(negative = below the balls).")
    print(f"Radius of gyration = {math.sqrt(I_r / (m_r * 1e-3)) * 1e3:.1f} mm.  The ring alone is "
          f"{parts[0][2] / I_r * 100:.0f} % of I.")

    # ---------------- 2. energy -------------------------------------------
    hr("2. Stored energy, angular momentum, rim speed")
    rows = []
    for n in (5, 10, 15, 30):
        w = 2 * math.pi * n
        m_one = math.pi * (MAG_D / 2) ** 2 * MAG_H * RHO_NDFEB * 1e-3          # kg
        rows.append((n, f"{0.5 * I_r * w * w * 1e3:.0f}", f"{I_r * w * 1e3:.2f}", f"{w * RING_RO * 1e-3:.2f}",
                     f"{m_one * w * w * RT * 1e-3 * 1e3:.1f}"))
    table(rows, ["rev/s", "E mJ", "L mN*m*s", "rim m/s", "centrifugal force per magnet mN"])
    print("Flick impulse needed for 10 rev/s, applied at the rim r = 35: "
          f"{I_r * 2 * math.pi * 10 / 0.035:.3f} N*s (lateral reaction on the base, see section 9).")

    # ---------------- 3. spin-down -----------------------------------------
    hr("3. Spin-down: SKF frictional-moment model, 608-2Z (oiled) vs 61808")
    fa = m_r * 1e-3 * G
    print(f"Axial load Fa = rotor weight = {fa:.2f} N (vertical axis, gravity only), Fr = 0.05 N [assume].")
    print("Lubrication: degreased + 1-2 drops ISO VG 2-10 oil -> nu = 10 or 20 mm^2/s at room temp [research].")
    print("Krs = 3e-8, Kz = 3.1, mu_bl = 0.12, mu_EHL = 0.04 (same constants the verifier re-implemented).")
    print("Moment at 10 rev/s (N*mm):")
    rows = []
    for name, b in BEARINGS.items():
        for nu in (10, 20, 200):
            rows.append((name, nu, f"{skf_moment(600, nu, fa, 0.05, b):.3f}"))
    table(rows, ["bearing", "nu mm2/s", "M @600 rpm"])
    for chk, ref in (("608-2Z", 0.147), ("61808 (6808)", 1.60)):
        got = skf_moment(600, 20, 1.32, 0.05, BEARINGS[chk])
        print(f"  check vs research at Fa=1.32 N, nu=20: {chk} {got:.3f} N*mm (research {ref})")

    # eddy / air terms
    c_eddy = 1.3e-8   # N*m*s: In1/F.Cu pours 4.8-5.1 mm above the track [research table, interpolated]
    k_air = 1.0e-9    # N*m*s^2: skin friction on the knurled ring, Cf ~ 0.01 [assume]
    print(f"\nExtra drag terms: eddy c = {c_eddy:.1e} N*m*s (In1/F.Cu planes at 4.8-5.1 mm; B.Cu/In2 pour-free"
          f" r >= 26 per SPEC), air k = {k_air:.1e} N*m*s^2 [assume].")
    print(f"  at 10 rev/s: eddy {c_eddy * 62.8 * 1e3:.4f} N*mm, air {k_air * 62.8 ** 2 * 1e3:.4f} N*mm "
          "(both small vs. the bearing; knurl 'fan' drag is unmeasured)")

    cases = [
        ("608-2Z oil nu10", "608-2Z", 10, 1.0),
        ("608-2Z oil nu20", "608-2Z", 20, 1.0),
        ("608-2Z nu20 x2.7 (pessimistic)", "608-2Z", 20, 2.7),
        ("608-2Z factory grease run-in nu200", "608-2Z", 200, 1.0),
        ("61808 oil nu10", "61808 (6808)", 10, 1.0),
        ("61808 oil nu20", "61808 (6808)", 20, 1.0),
        ("61808 nu20 x2.7", "61808 (6808)", 20, 2.7),
    ]
    rows = []
    curves = {}
    for label, bn, nu, fac in cases:
        b = BEARINGS[bn]
        res = []
        for n0 in (5, 10, 15):
            t, n = spin_down(I_r, n0, lambda rpm, b=b, nu=nu, fac=fac: fac * skf_moment(rpm, nu, fa, 0.05, b),
                             c_lin=c_eddy, k_air=k_air)
            revs = float(np.trapz(n, t)) if hasattr(np, "trapz") else float(np.trapezoid(n, t))
            res.append(f"{t[-1]:.0f} s / {revs:.0f} rev")
            if n0 == 10:
                curves[label] = (t, n)
        rows.append((label, *res))
    table(rows, ["case", "from 5 rev/s", "from 10 rev/s", "from 15 rev/s"])
    print("\nUncertainty: the SKF model is used below the bearing's minimum load and with drop lubrication.")
    print("The one measured comparison (verifier) suggests it UNDER-predicts friction by up to ~2.7x, so the")
    print("608 row 'x2.7' is the planning floor: quote ~40-120 s from 10 rev/s, acceptance >= 45 s.")
    print("The 608/61808 ratio (~10x) is robust because the same model error applies to both.")

    # preload sensitivity
    print("\nAxial-load sensitivity (608, nu20, 10 rev/s): the click-mode detent moment (~0.7 N x 29 mm =")
    print("20 mN*m) exceeds the gravity-only moment capacity Fa*dm/2; a net preload of ~2.7 N stops the rocking:")
    rows = []
    for fa_x in (fa, 2.0, 2.7, 3.5, 5.0):
        mm = skf_moment(600, 20, fa_x, 0.05, BEARINGS["608-2Z"])
        t, n = spin_down(I_r, 10, lambda rpm, f=fa_x: skf_moment(rpm, 20, f, 0.05, BEARINGS["608-2Z"]),
                         c_lin=c_eddy, k_air=k_air)
        rows.append((f"{fa_x:.2f}", f"{mm:.3f}", f"{fa_x * 15 / 2:.1f}", f"{t[-1]:.0f}"))
    table(rows, ["Fa N", "M N*mm", "Fa*dm/2 mN*m", "spin from 10 rev/s s"])

    # ---------------- 4. detent LUT ----------------------------------------
    hr("4. Detent torque vs in-plane radial offset (verified LUT, log-linear interpolation)")
    step_carr = 0.02 * 0.75   # mm carriage per full step: M2x0.4 lead / 20 steps, x0.75 cam
    print(f"Actuator resolution: 0.020 mm/full step at the slider x 0.75 (inclined slot) = {step_carr:.3f} mm "
          f"carriage per full step -> {7.5 / step_carr:.0f} full steps for 7.5 mm.")
    rows = []
    for off in np.arange(0, 7.51, 0.5):
        t1 = detent_torque(off)
        k = N_DET * t1 * 1e-3
        fn = math.sqrt(k / I_r) / (2 * math.pi)
        e_b = 2 * t1 * 1e-3 / N_DET            # barrier energy (J) for T = T1 sin(N th)
        n_cap = math.sqrt(2 * e_b / I_r) / (2 * math.pi)
        rows.append((f"{off:.1f}", f"{t1:.4g}", f"{t1 / 35:.3f}", f"{fn:.1f}", f"{n_cap:.2f}",
                     int(round(off / step_carr))))
    table(rows, ["offset mm", "T1 mN*m", "rim force N (r35)", "f_n Hz", "capture rev/s", "full steps"])
    print("Note: LUT simulated for R_t = 30 mm (research); SPEC uses R_t = 29.0 (pitch 3.80 vs 3.93 mm) ->")
    print("expect ~2-5 % lower torque and slightly faster fall-off. To verify on prototype (f_n self-calibration).")

    # ---------------- 5. ringing --------------------------------------------
    hr("5. Detent ringing / settling after release (I, bearing friction from the SKF model at low speed)")
    mb = lambda rpm: skf_moment(max(rpm, 0.5), 20, fa, 0.05, BEARINGS["608-2Z"])
    print(f"Bearing friction at 1 rev/s: {mb(60):.3f} N*mm; at 0.1 rev/s: {mb(6):.3f} N*mm.")
    ring_rows = []
    ring_curves = {}
    for off, label in ((0.0, "full click (16.5 mN*m)"), (1.5, "default 9.5 mN*m (1.5 mm)")):
        t1 = detent_torque(off)
        for shoe in (0.0, 1.6):
            ts, ths, peaks, tset = ring_down(I_r, t1, mb, m_shoe_mnm=shoe, theta0_deg=6.0)
            ring_rows.append((label, f"{shoe:.1f}", peaks // 2, f"{tset:.2f}" if tset else f">{ts[-1]:.0f}"))
            ring_curves[(off, shoe)] = (ts, ths)
    table(ring_rows, ["detent", "shoe mN*m", "cycles", "t to <0.5 deg (s)"])
    t1 = detent_torque(0)
    print(f"Rest error with the shoe: +/-{math.degrees(1.6e-3 / (N_DET * t1 * 1e-3)):.2f} deg (T_f / k).")
    print(f"Click-spin with the shoe engaged, from 5 rev/s: ~{I_r * 2 * math.pi * 5 / (1.6e-3 + mb(150) * 1e-3):.1f} s "
          "(prize-wheel feel); without shoe it is nearly as long as a free spin.")
    print("Verifier: size the shoe for ~1.6 mN*m and make its engagement window cover the default strength")
    print("(offset <= 1.5 mm), else the default setting rings undamped.  Felt/UHMW, not PTFE (mu too low).")

    # ---------------- 6. balance --------------------------------------------
    hr("6. Balance: ISO 1940 G2.5 at 15 rev/s")
    w15 = 2 * math.pi * 15
    e_per = 2.5 / w15 * 1e3                        # um
    U_per = m_r * e_per * 1e-3                     # g*mm
    print(f"e_per = G/omega = {e_per:.1f} um  ->  U_per = m*e = {U_per:.2f} g*mm for the {m_r:.0f} g rotor "
          f"(aim <= 2 g*mm).")
    m_carrier = parts[2][1]
    m_ringc = parts[0][1] + parts[1][1]
    m_one = parts[1][1] / MAG_N
    common = [
        ("ring OD/ID eccentricity 0.02 mm TIR (e = 0.01)", parts[0][1] * 0.010),
        ("48 magnets, mass sigma 3 % (random, RSS)", math.sqrt(MAG_N) * 0.03 * m_one * RT),
        ("glue blob 5 mg at r = 29", 0.005 * RT),
    ]
    a = common + [("ring bonded on printed carrier, bore-to-register 0.05 TIR + bond gap 0.05 (e ~ 0.035)",
                   (m_ringc + m_carrier) * 0.035)]
    b = common + [("ring bonded on a turning arbor through the 608, ring OD TIR <= 0.02 (e = 0.01)",
                   (m_ringc + m_carrier) * 0.010)]
    rows = []
    for tag, lst in (("A no jig", a), ("B centring jig", b)):
        for n_, u in lst:
            rows.append((tag, n_, f"{u:.2f}"))
        rows.append((tag, "RSS before correction", f"{math.sqrt(sum(u * u for _, u in lst)):.2f}"))
    table(rows, ["build", "source", "U g*mm"])
    rss = math.sqrt(sum(u * u for _, u in b))
    print(f"=> build A needs 1-3 correction steps; build B lands inside the 2 g*mm aim but must still be measured.")
    print(f"Rotating force at the G2.5 limit: "
          f"{U_per * 1e-6 * w15 ** 2:.3f} N; free-body base acceleration ~ {U_per * 1e-6 * w15 ** 2 / 0.22 / G * 1e3:.0f} mg "
          "(220 g device; LIS2DW12 can see it -> on-device balancing assistant).")
    hole = (math.pi * 1 ** 2 * 1.0 + math.pi * 1 ** 2 * 0.6 / 3) * RHO_316L * 31
    tap = math.pi * 0.8 ** 2 * 3.0 * RHO_316L * 31
    grub_b = math.pi * 0.8 ** 2 * 3.0 * 0.85 * RHO_BRASS * 31
    grub_w = math.pi * 0.8 ** 2 * 3.0 * 0.85 * 17.0e-3 * 31
    print(f"Correction quanta at r = 31 (ring bottom face): Ø2x1 drill dimple -{hole:.2f} g*mm; empty M2x3 tapped hole "
          f"-{tap:.2f}; brass grub in it +{grub_b:.2f}; W-alloy grub +{grub_w:.2f} g*mm.")

    # ---------------- 6b. mass budget ----------------------------------------
    hr("6b. Device mass budget and centre of gravity")
    budget = [  # (group, item, g, z_cg)
        ("base", "3x micro-suction arc pads", 1.0, 0.5),
        ("base", "base cup PA12 (~10.3 cm^3)", 10.4, 6.0),
        ("base", "LiPo 603450 protected, ~1100 mAh", 21.0, 5.65),
        ("base", "flex antenna 146153-0100 + coax (share)", 1.0, 3.0),
        ("base", "base board + USB-C + SW1 + J2/J3", 5.7, 10.6),
        ("base", "guide pins, stop screws, springs", 1.2, 12.0),
        ("FA", "FA lower plate PA12-GF", 5.4, 13.4),
        ("FA", "spindle 316 Ø8x1 + POM spacer", 3.2, 20.0),
        ("FA", "608 inner ring + share of balls", 13 - parts[3][1], 21.5),
        ("FA", "spindle hub PA12-GF + 3 inserts", 1.1, 27.5),
        ("FA", "main board Ø64 4L + parts", 12.3, 29.9),
        ("FA", "OLED glass + bracket", 5.0, 33.2),
        ("FA", "light box + diffuser + cover + lens", 7.8, 34.0),
        ("FA", "stepper + carriage + magnet + rails", 3.7, 25.5),
        ("FA", "screws, harness, coax (share)", 2.4, 22.0),
        ("rotor", "rotor (section 1)", m_r, z_r),
    ]
    rows = [(g_, it, f"{m:.1f}", f"{z:.1f}") for g_, it, m, z in budget]
    m_tot = sum(b_[2] for b_ in budget)
    z_tot = sum(b_[2] * b_[3] for b_ in budget) / m_tot
    m_fa_static = sum(b_[2] for b_ in budget if b_[0] == "FA")
    m_base = sum(b_[2] for b_ in budget if b_[0] == "base")
    rows.append(("", "TOTAL", f"{m_tot:.1f}", f"{z_tot:.1f}"))
    table(rows, ["group", "item", "g", "z_cg mm"])
    print(f"Floating assembly (moves on press) = {m_fa_static + m_r:.0f} g; base = {m_base:.0f} g. "
          f"Static tip angle on arc pads (r_edge 28) ~ {math.degrees(math.atan(28 / z_tot)):.0f} deg.")

    # ---------------- 7. press click ---------------------------------------
    hr("7. Press-click force vs radius (3 springs + 3 stop screws at r = 29, centre TS-1187A)")
    d_w, D_m, na = 0.32, 3.63, 4                     # spring [design]
    k_s = 69000 * d_w ** 4 / (8 * D_m ** 3 * na)     # N/mm, G = 69 GPa (302 SS)
    L_inst, L0 = 2.7, None
    P0 = 4.0 / 3                                     # target preload each
    L0 = L_inst + P0 / k_s
    L_solid = (na + 2) * d_w
    F_stop = P0 + k_s * 0.60
    tau = 8 * F_stop * D_m / (math.pi * d_w ** 3) * (4 * (D_m / d_w) - 1) / (4 * (D_m / d_w) - 4) + 0.615 * d_w / D_m
    print(f"Spring: 302 SS wire {d_w} mm, Dm {D_m} (OD {D_m + d_w:.2f}), {na} active + 2 closed/ground, "
          f"k = {k_s:.3f} N/mm, L0 = {L0:.2f}, installed {L_inst} -> P0 = {P0:.2f} N each, "
          f"at stop (0.60) L = {L_inst - 0.6:.2f} vs solid {L_solid:.2f}, F = {F_stop:.2f} N, tau ~ {tau:.0f} MPa.")
    W_fa = (m_r + m_fa_static) * 1e-3 * G
    g0, t_sw, F_sw, k_dot = 0.15, 0.25, 1.6, 70.0
    g_act = g0 + t_sw + F_sw / k_dot
    print(f"FA weight W = {W_fa:.2f} N (rotor {m_r:.0f} g + non-rotating FA {m_fa_static:.0f} g, section 6b); "
          f"net preload on the stops at rest = {3 * P0 - W_fa:.2f} N.")
    print(f"Switch: pre-gap {g0} + travel {t_sw} (to verify) + dot compression {F_sw / k_dot:.3f} -> actuation at "
          f"{g_act:.3f} mm, F_sw = {F_sw} N; hard stop at 0.60 mm.")
    radii = np.arange(0, 35.01, 0.5)
    press = {}
    for th, lab in ((60, "over a stop (θ=60°)"), (0, "between stops (θ=0°)"), (30, "θ=30°")):
        fs = []
        for r in radii:
            res = click_force(r, th, P0, k_s, W_fa, g_act, F_sw)
            fs.append(res[0] if res else np.nan)
        press[lab] = np.array(fs)
    rows = []
    for r in (0, 10, 20, 25, 29, 32.5, 33.5, 35):
        i = int(round(r / 0.5))
        rows.append((r, *[f"{press[l][i]:.2f}" for l in press]))
    table(rows, ["r mm", *press.keys()])
    W_dev = m_tot * 1e-3 * G
    edge3 = 28 * math.cos(math.radians(60))
    edge_arc = 31 * math.cos(math.radians((120 - 70) / 2))
    print(f"\nDevice weight ~{W_dev:.2f} N.  Tip check for a press at the ring rim r = 33.5:")
    print(f"  3 point feet at r = 28 (support edge {edge3:.1f} mm from centre): tips at "
          f"{tip_force(33.5, W_dev, edge3):.2f} N  < rim click {min(v_[67] for v_ in press.values()):.2f}-"
          f"{max(v_[67] for v_ in press.values()):.2f} N"
          " -> the device tips before it clicks (unless micro-suction pads hold).")
    print(f"  3 arc pads 70° at r 25-31 (edge {edge_arc:.1f} mm): tips at {tip_force(33.5, W_dev, edge_arc):.1f} N -> OK.")

    # ---------------- 8. TMAG sampling ---------------------------------------
    hr("8. TMAG5273 sample rate / aliasing for the 24-pole-pair track")
    pp = MAG_N // 2
    for fs_nom, mode in ((3100, "XZX, 4x avg (research config)"), (4400, "ZX, 4x avg")):
        for tol, tl in ((1.0, "nom"), (0.9, "-10 %")):
            fs = fs_nom * tol
            fe = pp * 30
            adv = 360 * fe / fs
            n_nyq = fs / 2 / pp
            print(f"  {mode:32s} fs={fs:6.0f} Hz ({tl:5s}): f_elec @30 rev/s = {fe} Hz, advance {adv:5.1f} deg/sample, "
                  f"Nyquist at {n_nyq:5.1f} rev/s, margin {n_nyq / 30:.2f}x")
    T = 1 / 3100
    dphi = 2 * math.pi * pp * 30 * (2 * T / 3)
    ax_ratio = math.cos(dphi / 2)
    err_e = math.degrees(math.asin((1 - ax_ratio) / (1 + ax_ratio)))
    print(f"  XZX skew: X = mean of two conversions ~{2 * T / 3 * 1e6:.0f} us apart (time-centred on Z) -> X amplitude "
          f"x cos(dphi/2) = {ax_ratio:.3f} at 30 rev/s vs Z ~1.0 -> speed-dependent ellipse,")
    print(f"  max atan2 error {err_e:.1f} deg electrical = {err_e / pp:.2f} deg mechanical: correct in firmware as f(speed)"
          " or use ZX mode at high speed [estimate, verify on bench].")
    print(f"  16-pole-pair track (research) would reach {3100 / 2 / 16:.0f} rev/s; 24 pp trades that for detent = encoder period.")
    zt = MB_Z0 - TMAG_PKG_H + TMAG_ELEM_DEPTH
    print(f"  Hall element z = {zt:.2f} -> gap to track face (z {RING_Z1}) = {zt - RING_Z1:.2f} mm "
          "(target 3.0, allowed 2.2-4.0 [verifier]); constant under press because sensor and rotor both float.")

    # ---------------- 9. drop & flick ---------------------------------------
    hr("9. Drop shock on the 608 and flick reactions")
    lim = 0.25 * 1370
    print(f"608 pure-axial static limit = 0.25*C0 = {lim:.0f} N [verifier].  Rotor {m_r:.0f} g:")
    rows = []
    for h in (0.1, 0.3, 0.75):
        v = math.sqrt(2 * G * h)
        cells = []
        for s in (0.5, 1.0, 2.0):
            F = m_r * 1e-3 * v * v / (2 * s * 1e-3)
            cells.append(f"{F:.0f}")
        rows.append((h, *cells))
    table(rows, ["drop m", "F @ 0.5 mm stop", "F @ 1 mm", "F @ 2 mm"])
    print("-> rigid seating cannot protect the 608 beyond ~0.1 m.  Design: outer race held by a wave spring")
    print("   (30-50 N) under a printed retainer; above that the carrier lands on the POM spacer flange 0.15 mm")
    print("   below (crash stop), so balls see <= spring force.  Brinelling still possible on edge impacts.")
    J = I_r * 2 * math.pi * 10 / 0.035
    print(f"Flick to 10 rev/s: lateral impulse {J:.3f} N*s -> ~{J / 0.03:.1f} N average over 30 ms vs slide threshold "
          f"mu*W = {0.6 * W_dev:.1f}-{1.0 * W_dev:.1f} N: the puck slides unless held or on micro-suction pads.")

    # ---------------- 10. actuator ------------------------------------------
    hr("10. Detent actuator force budget (inclined-slot cam, slope 0.75)")
    F_mag = 0.29
    mu = 0.15
    N_v, N_t, pre = 0.70, 0.55, 0.45
    F_c = F_mag + mu * (N_v + N_t + pre)
    alpha = math.atan(0.75)
    for mu_pin in (0.10, 0.20):
        F_s = F_c * math.tan(alpha + math.atan(mu_pin))
        print(f"  carriage load {F_c:.2f} N (0.29 magnetic + mu {mu} x (0.70+0.55+0.45 preload)); slot mu {mu_pin}: "
              f"slider thrust {F_s:.2f} N vs VSM08102 >= 0.78 N @500 PPS -> margin {0.78 / F_s:.2f}x")
    print("  Cam ratio 0.75 uses the full 10 mm stroke for 7.5 mm and gives 1.33x force advantage.")

    # ---------------- 11. clearances ----------------------------------------
    hr("11. Stack-up clearances (nominal; FA = floating assembly moves with the rotor)")
    rows = [
        ("ring bottom - cup wall top", RING_Z0 - 14.3, 0.6, "rest; 0.70 at full stop travel"),
        ("ring bottom - stop-screw head", RING_Z0 - 14.6, 0.6, "rest; 0.40 at full stop (head is base-fixed)"),
        ("detent magnet face - track face", DET_GAP, 0.0, "constant (both on FA)"),
        ("TMAG element - track face", MB_Z0 - TMAG_PKG_H + TMAG_ELEM_DEPTH - RING_Z1, 0.0, "target 3.0"),
        ("carrier ribs - FA plate top", 16.2 - 14.3, 0.0, "FA-internal, constant"),
        ("carrier lip - POM drop stop", 0.15, 0.0, "intended crash stop"),
        ("stepper body - rotating web", (24.4 - 4) - 19.0, 0.0, "bowl floor"),
        ("stepper front plate - collar r", math.hypot(5.5, 11.5) - 12.2, 0.0, "plan view"),
        ("J1 (vertical SH, SPEC) - hub top", (MB_Z0 - 4.25) - 26.0, 0.0, "NEGATIVE = clash"),
        ("u.FL mated plug - 608 outer race", (MB_Z0 - 2.2 - 2.5) - B_Z1, 0.0, "NEGATIVE = clash"),
        ("boss - switch (pre-gap)", 0.15, 0.0, "set per unit"),
        ("base board bottom - LiPo top (6.3)", 9.5 - (2.5 + 6.3), 0.0, "swelling margin"),
        ("cup ear bottom - LiPo corner", 9.05 - (2.5 + 6.3), 0.0, "θ=60/300"),
    ]
    table([(a, f"{b:+.2f}", c) for a, b, _, c in rows], ["pair", "gap mm", "note"])

    # ---------------- plots ------------------------------------------------
    if plots:
        make_plots(curves, ring_curves, press, radii, I_r, W_dev, edge3, edge_arc)
    return 0


def make_plots(curves, ring_curves, press, radii, I_r, W_dev, edge3, edge_arc):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(RENDERS, exist_ok=True)
    BLUE, ORANGE, AQUA, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})

    # spin-down
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=130)
    sty = {"608-2Z oil nu10": (BLUE, "-"), "608-2Z oil nu20": (BLUE, "--"),
           "608-2Z nu20 x2.7 (pessimistic)": (BLUE, ":"), "61808 oil nu20": (ORANGE, "-"),
           "61808 nu20 x2.7": (ORANGE, ":")}
    for lab, (c, ls) in sty.items():
        t, n = curves[lab]
        ax.plot(t, n, color=c, ls=ls, lw=2)
        ax.annotate(f"{lab}  ({t[-1]:.0f} s)", (t[-1], 0.0), xytext=(t[-1] * 0.55 + 2, 0.4 + 0.9 * list(sty).index(lab)),
                    color=INK, fontsize=8, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    ax.axvline(45, color=MUTED, lw=1, ls=(0, (2, 3)))
    ax.text(46, 9.6, "acceptance test >= 45 s", color=MUTED, fontsize=8)
    ax.set_xlabel("time after a 10 rev/s flick (s)")
    ax.set_ylabel("speed (rev/s)")
    ax.set_title("Spin-down, SKF friction model + small eddy/air terms", loc="left", color=INK)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_ylim(0, 10.5)
    ax.set_xlim(0, None)
    fig.text(0.01, 0.01, "blue = 608-2Z, orange = 61808; solid nu10 / dashed nu20 / dotted nu20 with 2.7x friction "
             "(planning floor). Rotor I = %.2e kg m^2." % I_r, color=MUTED, fontsize=7.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(os.path.join(RENDERS, "calc_spindown.png"))
    plt.close(fig)

    # detent LUT + ringing
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2), dpi=130)
    off = np.linspace(0, 7.5, 200)
    a1.semilogy(off, [detent_torque(o) for o in off], color=BLUE, lw=2)
    a1.semilogy(LUT_OFF, LUT_T, "o", color=BLUE, ms=6, mec="#fcfcfb", mew=1.5)
    for o, t in zip(LUT_OFF, LUT_T):
        a1.annotate(f"{t:g}", (o, t), xytext=(5, 4), textcoords="offset points", fontsize=8, color=INK)
    a1.axhspan(0.05, 0.15, color=GRID, lw=0)
    a1.text(0.1, 0.062, "608 bearing friction band (0.05-0.15 mN·m)", fontsize=7.5, color=MUTED)
    a1.set_xlabel("carriage radial offset (mm)   0 = full click, 7.5 = free")
    a1.set_ylabel("peak detent torque (mN·m)")
    a1.set_title("Detent strength LUT (verified)", loc="left", color=INK)
    a1.grid(True, which="both", color=GRID, lw=0.5)
    for (o, shoe), c, ls in (((0.0, 0.0), BLUE, "-"), ((0.0, 1.6), ORANGE, "-")):
        ts, ths = ring_curves[(o, shoe)]
        a2.plot(ts, ths, color=c, lw=1.2 if shoe == 0 else 2, ls=ls)
    a2.set_xlim(0, 4)
    a2.set_xlabel("time after release (s)")
    a2.set_ylabel("angle from detent centre (deg)")
    a2.set_title("Ringing at full click: bearing only vs + 1.6 mN·m shoe", loc="left", color=INK, fontsize=10)
    a2.grid(True, color=GRID, lw=0.5)
    a2.plot([], [], color=BLUE, lw=1.2, label="bearing friction only")
    a2.plot([], [], color=ORANGE, lw=2, label="with 1.6 mN·m felt/UHMW shoe")
    a2.set_ylim(-7, 9.5)
    a2.legend(loc="upper right", fontsize=8, frameon=True, facecolor="#fcfcfb", edgecolor=GRID, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(RENDERS, "calc_detent.png"))
    plt.close(fig)

    # press force
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=130)
    cols = [BLUE, ORANGE, AQUA]
    for (lab, f), c in zip(press.items(), cols):
        ax.plot(radii, f, color=c, lw=2)
        i = len(radii) - 1
        ax.annotate(lab, (radii[i], f[i]), xytext=(4, 0), textcoords="offset points", fontsize=8, color=INK, va="center")
    rr = np.linspace(15, 35, 100)
    ax.plot(rr, [tip_force(r, W_dev, edge3) for r in rr], color=MUTED, lw=1.2, ls="--")
    ax.text(15.5, 3.2, "tip limit, 3 point feet r28", color=MUTED, fontsize=8)
    ax.axvspan(32.5, 35, color=GRID, lw=0)
    ax.text(32.6, 0.25, "ring rim", color=MUTED, fontsize=8)
    ax.set_ylim(0, 6)
    ax.set_xlim(0, 41)
    ax.set_xlabel("press radius (mm)")
    ax.set_ylabel("force to click (N)")
    ax.set_title("Press-click force vs radius and azimuth (TS-1187A, 4.0 N spring preload)", loc="left", color=INK)
    ax.grid(True, color=GRID, lw=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(RENDERS, "calc_press.png"))
    plt.close(fig)
    print("\nplots: renders/calc_spindown.png, renders/calc_detent.png, renders/calc_press.png")


if __name__ == "__main__":
    sys.exit(main(plots="--no-plots" not in sys.argv))
