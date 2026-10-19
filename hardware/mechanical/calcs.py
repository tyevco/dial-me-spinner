#!/usr/bin/env python3
"""dial-me-spinner rev A -- mechanical calculations.

Pure Python + numpy (+ matplotlib for the plots).  Run:

    python3 calcs.py            # print everything, write renders/calc_*.png
    python3 calcs.py --no-plots

Geometry follows hardware/design/SPEC.md section 8 and dial_spinner.scad.  Section 11 reads the
model directly: the analytic primitives echoed by `openscad -D view="prims"` and the board-part
envelopes in board_parts.json (generated from the KiCad boards by extract_board_parts.py), so the
clearance tables always match the model.  Numbers from the subsystem research are tagged
[research] / [verifier]; assumptions are tagged [assume] and are "to verify on prototype" items.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERS = os.path.join(HERE, "renders")
G = 9.81

# ---------------------------------------------------------------------------
# Geometry (mm) -- SPEC section 8 / dial_spinner.scad (same names)
# ---------------------------------------------------------------------------
RING_RO, RING_RI, RING_H = 35.0, 27.0, 10.0
RING_Z0, RING_Z1 = 15.6, 25.6
CH_TO, CH_BO, CH_IN = 1.0, 1.5, 0.5
MAG_N, MAG_D, MAG_H, RT = 48, 2.0, 2.0, 29.0
POCKET_D, POCKET_H = 2.10, 2.05
B_Z0, B_Z1 = 18.0, 25.0                  # 608
DET_D, DET_H, DET_GAP = 3.0, 2.0, 1.0
MB_Z0 = 29.1
TMAG_PKG_H, TMAG_ELEM_DEPTH = 1.1, 0.73   # SOT-23-6 body (nominal), element below pkg top [research]
GUIDE_A = (60.0, 180.0, 300.0)
GUIDE_RS = (29.0, 30.0, 29.0)             # theta-180 guide at r 30 (DEV, clears the pack end)
STOP_TRAVEL = 0.50
CUP_TOP, FA_Z0, FA_Z1 = 14.3, 12.8, 14.3
BB_Z1 = 11.1
HEAD_TOP = 14.8                           # stop-screw head top (base-fixed)
ROT_HUB_TOP = 26.0                        # wave washer + 316 cap ring on the collar

# Materials (g/mm^3)
RHO_316L = 7.98e-3
RHO_NDFEB = 7.5e-3
RHO_PA12GF = 1.25e-3     # [assume] SLS PA12-GF ~1.22, MJF PA12-GB ~1.30
RHO_STEEL = 7.85e-3
RHO_BRASS = 8.5e-3


def annulus(ro, ri, h):
    """volume (mm^3) and I/m factor (mm^2) of an annulus about z."""
    v = math.pi * (ro ** 2 - ri ** 2) * h
    return v, 0.5 * (ro ** 2 + ri ** 2)


def hr(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def table(rows, header):
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    print("  ".join(str(h).ljust(w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(x).ljust(w) for x, w in zip(r, widths)))


# ---------------------------------------------------------------------------
# 1. Rotor mass, inertia, CoG
# ---------------------------------------------------------------------------
def rotor_parts():
    parts = []  # (name, mass_g, I_kgm2, z_cg_mm)
    v, k = annulus(RING_RO, RING_RI, RING_H)
    ch = [(CH_TO ** 2 / 2, RING_RO - CH_TO / 3), (CH_BO ** 2 / 2, RING_RO - CH_BO / 3),
          (CH_IN ** 2 / 2, RING_RI + CH_IN / 3), (CH_IN ** 2 / 2, RING_RI + CH_IN / 3)]
    v_chamf = sum(2 * math.pi * r * a for a, r in ch)
    i_chamf = sum(2 * math.pi * r * a * r ** 2 for a, r in ch)
    v_knurl = 120 * (0.6 ** 2 / 2) * 7.0
    v_pock = MAG_N * math.pi * (POCKET_D / 2) ** 2 * POCKET_H
    v_bal = 4 * math.pi * 0.8 ** 2 * 3.0
    m_ring = (v - v_chamf - v_knurl - v_pock - v_bal) * RHO_316L
    i_ring = (v * RHO_316L * k - i_chamf * RHO_316L - v_knurl * RHO_316L * 34.8 ** 2
              - v_pock * RHO_316L * RT ** 2 - v_bal * RHO_316L * 31 ** 2) * 1e-9
    parts.append(("316L ring 70/54/10 (net)", m_ring, i_ring, 20.65))
    v_mag = math.pi * (MAG_D / 2) ** 2 * MAG_H
    m_mag = MAG_N * v_mag * RHO_NDFEB
    parts.append(("48x N52 Ø2x2 magnets", m_mag, m_mag * RT ** 2 * 1e-9, RING_Z1 - MAG_H / 2))
    # PA12-GF carrier (post-machined): web r 12.2-26.95 z 17-19, collar r 11-12.2 z 17-25.5, lip r 9.9-11 z 17-18
    segs = [annulus(26.95, 12.2, 2.0), annulus(12.2, 11.0, 8.5), annulus(11.0, 9.9, 1.0)]
    zc = [18.0, 21.25, 17.5]
    m_c = sum(s[0] for s in segs) * RHO_PA12GF
    i_c = sum(s[0] * s[1] for s in segs) * RHO_PA12GF
    z_c = sum(s[0] * z for s, z in zip(segs, zc)) * RHO_PA12GF / m_c
    parts.append(("PA12-GF carrier (no ribs)", m_c, i_c * 1e-9, z_c))
    m_or = 5.5 + 1.0 + 0.5 * (7 * (math.pi / 6 * 3.97 ** 3) * RHO_STEEL + 0.5)   # [assume] split of 13 g
    parts.append(("608-2Z rotating share", m_or, m_or * 10.3 ** 2 * 1e-9, 21.5))
    v_cap, k_cap = annulus(12.2, 9.95, 0.5)
    parts.append(("wave washer + 316 cap ring + ESD strap", 0.3 + v_cap * RHO_316L + 0.06,
                  (0.3 * 10.5 ** 2 + v_cap * RHO_316L * k_cap + 0.06 * 20 ** 2) * 1e-9, 25.5))
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
    return float(np.exp(np.interp(off, LUT_OFF, np.log(LUT_T))))


def ring_down(I, t1_mnm, m_bear_nmm_fn, m_shoe_mnm=0.0, theta0_deg=6.0, tmax=20.0, dt=2e-4, settle_deg=0.5):
    t1 = t1_mnm * 1e-3
    th = math.radians(theta0_deg)
    w = 0.0
    t = 0.0
    ts, ths = [], []
    peaks = 0
    t_settle = None
    while t < tmax:
        torque = -t1 * math.sin(N_DET * th)
        n_rpm = abs(w) * 60 / (2 * math.pi)
        fr = m_bear_nmm_fn(n_rpm) * 1e-3 + m_shoe_mnm * 1e-3
        if abs(w) < 1e-6:
            if abs(torque) <= fr:
                t_settle = t_settle or t
                break
            fr_dir = -math.copysign(fr, torque)
        else:
            fr_dir = -math.copysign(fr, w)
        a = (torque + fr_dir) / I
        w_new = w + a * dt
        if w != 0 and math.copysign(1, w_new) != math.copysign(1, w):
            peaks += 1
            w_new = 0.0
            if t_settle is None and math.degrees(abs(th)) < settle_deg:
                t_settle = t
        w = w_new
        th += w * dt
        t += dt
        if int(t / 0.002) != int((t - dt) / 0.002):
            ts.append(t)
            ths.append(math.degrees(th))
    return np.array(ts), np.array(ths), peaks, t_settle


# ---------------------------------------------------------------------------
# 4. Press-click model: 3 springs + 3 up-stops, centre TS-1187A
# ---------------------------------------------------------------------------
def click_force(r, theta_deg, P0, k, W, g_act, F_sw):
    """minimum force at (r, theta) that actuates the centre switch.  Rigid FA, delta = d0 + a*x + b*y
    (down positive); stops unilateral; springs push up with P0 + k*delta_i."""
    import itertools
    pts = [(rg * math.cos(math.radians(a)), rg * math.sin(math.radians(a))) for rg, a in zip(GUIDE_RS, GUIDE_A)]
    xf, yf = r * math.cos(math.radians(theta_deg)), r * math.sin(math.radians(theta_deg))
    best = None
    for na in (0, 1, 2):
        for act in itertools.combinations(range(3), na):
            nu = 3 + na
            A = np.zeros((nu, nu))
            rhs = np.zeros(nu)
            A[0, 0] = 1
            A[0, 1] = -k * sum(p[0] for p in pts)
            A[0, 2] = -k * sum(p[1] for p in pts)
            for j, _ in enumerate(act):
                A[0, 3 + j] = 1
            rhs[0] = 3 * P0 + 3 * k * g_act + F_sw - W
            for row, c in ((1, 1), (2, 0)):
                A[row, 0] = (yf if c == 1 else xf)
                A[row, 1] = -k * sum(p[0] * p[c] for p in pts)
                A[row, 2] = -k * sum(p[1] * p[c] for p in pts)
                for j, i in enumerate(act):
                    A[row, 3 + j] = pts[i][c]
                rhs[row] = (P0 + k * g_act) * sum(p[c] for p in pts)
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
            ok = all(s >= -1e-9 for s in S) and all(deltas[i] >= -1e-9 for i in range(3) if i not in act) and F > 0
            if ok and (best is None or F < best[0]):
                best = (F, deltas, act)
    return best


def tip_force(r_press, W_dev, edge_dist):
    if r_press <= edge_dist:
        return float("inf")
    return W_dev * edge_dist / (r_press - edge_dist)


# ---------------------------------------------------------------------------
# 11. Geometry helpers for the per-part clearance tables
# ---------------------------------------------------------------------------
def load_prims():
    """run OpenSCAD view="prims" and parse the echoed primitives."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "p.echo")
        subprocess.run(["openscad", "-o", out, "-D", 'view="prims"', os.path.join(HERE, "dial_spinner.scad")],
                       capture_output=True, text=True, check=True)
        prims, rc = [], None
        for ln in open(out):
            if ln.startswith("ECHO: PRIM = "):
                prims.append(json.loads(ln[len("ECHO: PRIM = "):]))
            elif ln.startswith("ECHO: ROTOR_CONST = "):
                rc = json.loads(ln[len("ECHO: ROTOR_CONST = "):])
    return prims, rc


def rotor_polys(rc, dz=0.0):
    (ri, ro, z0, z1, cto, cbo, cin, cw0, cw1, cri, cro, cz1, lri, bz0, bz1, capri, wsz0, capz1) = rc
    ring = [(ri + cin, z0), (ro - cbo, z0), (ro, z0 + cbo), (ro, z1 - cto), (ro - cto, z1), (ri + cin, z1),
            (ri, z1 - cin), (ri, z0 + cin)]

    def rect(a, b, za, zb):
        return [(a, za), (b, za), (b, zb), (a, zb)]
    polys = [ring, rect(cro, ri, cw0, cw1 + 0.11), rect(cri, cro + 0.11, cw0, cz1), rect(lri, cri, cw0, bz0),
             rect(9.55, 11.0, bz0, bz1), rect(6.2, 9.56, bz0 + 0.3, bz1 - 0.3), rect(capri, cro, wsz0, capz1)]
    return [[(r, z + dz) for r, z in p] for p in polys]


def sdf_poly2(P, poly):
    """signed distance of points P (N,2) to a convex CCW polygon (negative inside)."""
    poly = np.array(poly)
    n = len(poly)
    d = np.full(len(P), np.inf)
    inside = np.ones(len(P), bool)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = b - a
        w = P - a
        t = np.clip((w @ e) / (e @ e), 0, 1)
        q = w - np.outer(t, e)
        d = np.minimum(d, np.hypot(q[:, 0], q[:, 1]))
        inside &= (e[0] * w[:, 1] - e[1] * w[:, 0]) >= -1e-12
    return np.where(inside, -d, d)


def part_frame(p):
    a = math.radians(p["phi"])
    return np.array([p["x"], p["y"]]), np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])


def part_samples(p, step=0.12):
    """surface samples of a board-part box (world coordinates)."""
    o, U, V = part_frame(p)
    u0, u1, v0, v1 = p["box"]
    z0, z1 = p["z0"], p["z0"] + p["h"]
    us = np.linspace(u0, u1, max(2, int((u1 - u0) / step) + 1))
    vs = np.linspace(v0, v1, max(2, int((v1 - v0) / step) + 1))
    zs = np.linspace(z0, z1, max(2, int((z1 - z0) / step) + 1))
    pts = []
    for zz in (z0, z1):
        uu, vv = np.meshgrid(us, vs)
        pts.append(np.c_[uu.ravel(), vv.ravel(), np.full(uu.size, zz)])
    for uu_ in (u0, u1):
        vv, zz = np.meshgrid(vs, zs)
        pts.append(np.c_[np.full(vv.size, uu_), vv.ravel(), zz.ravel()])
    for vv_ in (v0, v1):
        uu, zz = np.meshgrid(us, zs)
        pts.append(np.c_[uu.ravel(), np.full(uu.size, vv_), zz.ravel()])
    L = np.vstack(pts)
    W = o + np.outer(L[:, 0], U) + np.outer(L[:, 1], V)
    return np.c_[W, L[:, 2]]


def part_rz(p):
    """(r_min, r_max, z0, z1) shadow of a part box in the (r, z) half-plane."""
    o, U, V = part_frame(p)
    u0, u1, v0, v1 = p["box"]
    # nearest point of the rectangle to the axis
    lo = np.array([-(o @ U), -(o @ V)])
    cu, cv = np.clip(lo[0], u0, u1), np.clip(lo[1], v0, v1)
    rmin = float(np.hypot(*(o + cu * U + cv * V)))
    corners = [o + a * U + b * V for a in (u0, u1) for b in (v0, v1)]
    rmax = max(float(np.hypot(*c)) for c in corners)
    return rmin, rmax, p["z0"], p["z0"] + p["h"]


def axisym_clearance(p, polys):
    rmin, rmax, z0, z1 = part_rz(p)
    rs = np.linspace(rmin, rmax, max(2, int((rmax - rmin) / 0.05) + 1))
    zs = np.linspace(z0, z1, max(2, int((z1 - z0) / 0.05) + 1))
    R, Z = np.meshgrid(rs, zs)
    P = np.c_[R.ravel(), Z.ravel()]
    return float(min(sdf_poly2(P, poly).min() for poly in polys))


def sdf_prim(X, pr):
    kind = pr[0]
    if kind == "box":
        c = np.array(pr[2]) + np.array(pr[3]) / 2
        h = np.array(pr[3]) / 2
        q = np.abs(X - c) - h
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
    if kind in ("cylx", "cylz"):
        p0, L, r = np.array(pr[2]), pr[3], pr[4]
        if kind == "cylx":
            ax, rad = X[:, 0] - p0[0], np.hypot(X[:, 1] - p0[1], X[:, 2] - p0[2])
        else:
            ax, rad = X[:, 2] - p0[2], np.hypot(X[:, 0] - p0[0], X[:, 1] - p0[1])
        q = np.c_[rad - r, np.maximum(-ax, ax - L)]
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
    if kind == "annz":
        ri, ro, z0, z1 = pr[2:6]
        r = np.hypot(X[:, 0], X[:, 1])
        q = np.c_[np.maximum(ri - r, r - ro), np.maximum(z0 - X[:, 2], X[:, 2] - z1)]
        return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
    if kind == "chain":
        pts, rxy, hz = np.array(pr[2], float), pr[3], pr[4]
        best = np.full(len(X), np.inf)
        for a, b in zip(pts[:-1], pts[1:]):
            if abs(rxy - hz) < 1e-9:          # 3D capsule
                e = b - a
                t = np.clip(((X - a) @ e) / max(e @ e, 1e-12), 0, 1)
                d = np.linalg.norm(X - a - np.outer(t, e), axis=1) - rxy
            else:                              # flat strip (horizontal segment)
                e = (b - a)[:2]
                t = np.clip(((X[:, :2] - a[:2]) @ e) / max(e @ e, 1e-12), 0, 1)
                dxy = np.linalg.norm(X[:, :2] - a[:2] - np.outer(t, e), axis=1) - rxy
                dz = np.abs(X[:, 2] - a[2]) - hz
                q = np.c_[dxy, dz]
                d = np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)
            best = np.minimum(best, d)
        return best
    raise ValueError(kind)


def chain_length(pr):
    pts = np.array(pr[2], float)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def under_spider(x, y):
    """True where the FA spider plate (hub, +-18 deg spokes, outer ring with USB notch, guide lobes) is."""
    r = math.hypot(x, y)
    th = math.degrees(math.atan2(y, x)) % 360
    if r <= 6.0:
        return True
    for a in GUIDE_A:
        if r <= 26.5 and abs((th - a + 180) % 360 - 180) <= 18:
            return True
    if 26.0 <= r <= 30.0 and not (x > 24 and abs(y) <= 5.6):
        return True
    for rg, a in zip(GUIDE_RS, GUIDE_A):
        gx, gy = rg * math.cos(math.radians(a)), rg * math.sin(math.radians(a))
        if math.hypot(x - gx, y - gy) <= 3.3:
            return True
    return False


# ---------------------------------------------------------------------------
def main(plots=True):
    print("dial-me-spinner rev A -- mechanical calculations (calcs.py)")
    print("Geometry: SPEC.md section 8 + dial_spinner.scad; assumptions [assume]; research values [research]/[verifier].")

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
          f"{parts[0][2] / I_r * 100:.0f} % of I.  The 1.5 mm bottom-outer chamfer (USB-C plug clearance) costs "
          f"{2 * math.pi * (RING_RO - CH_BO / 3) * (CH_BO ** 2 / 2 - 0.125) * RHO_316L:.1f} g vs a 0.5 chamfer.")

    # ---------------- 2. energy -------------------------------------------
    hr("2. Stored energy, angular momentum, rim speed")
    rows = []
    for n in (5, 10, 15, 30):
        w = 2 * math.pi * n
        m_one = math.pi * (MAG_D / 2) ** 2 * MAG_H * RHO_NDFEB * 1e-3
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
    print("Moment at 10 rev/s (N*mm):")
    rows = []
    for name, b in BEARINGS.items():
        for nu in (10, 20, 200):
            rows.append((name, nu, f"{skf_moment(600, nu, fa, 0.05, b):.3f}"))
    table(rows, ["bearing", "nu mm2/s", "M @600 rpm"])
    for chk, ref in (("608-2Z", 0.147), ("61808 (6808)", 1.60)):
        got = skf_moment(600, 20, 1.32, 0.05, BEARINGS[chk])
        print(f"  check vs research at Fa=1.32 N, nu=20: {chk} {got:.3f} N*mm (research {ref})")
    c_eddy = 1.3e-8   # N*m*s [research table, interpolated]
    k_air = 1.0e-9    # N*m*s^2 [assume]
    print(f"\nExtra drag terms: eddy c = {c_eddy:.1e} N*m*s, air k = {k_air:.1e} N*m*s^2 [assume]; at 10 rev/s "
          f"{c_eddy * 62.8 * 1e3:.4f} + {k_air * 62.8 ** 2 * 1e3:.4f} N*mm (small vs the bearing).")
    cases = [
        ("608-2Z oil nu10", "608-2Z", 10, 1.0), ("608-2Z oil nu20", "608-2Z", 20, 1.0),
        ("608-2Z nu20 x2.7 (pessimistic)", "608-2Z", 20, 2.7), ("608-2Z factory grease run-in nu200", "608-2Z", 200, 1.0),
        ("61808 oil nu10", "61808 (6808)", 10, 1.0), ("61808 oil nu20", "61808 (6808)", 20, 1.0),
        ("61808 nu20 x2.7", "61808 (6808)", 20, 2.7)]
    rows = []
    curves = {}
    spin10 = {}
    for label, bn, nu, fac in cases:
        b = BEARINGS[bn]
        res = []
        for n0 in (5, 10, 15):
            t, n = spin_down(I_r, n0, lambda rpm, b=b, nu=nu, fac=fac: fac * skf_moment(rpm, nu, fa, 0.05, b),
                             c_lin=c_eddy, k_air=k_air)
            revs = float(np.trapezoid(n, t)) if hasattr(np, "trapezoid") else float(np.trapz(n, t))
            res.append(f"{t[-1]:.0f} s / {revs:.0f} rev")
            if n0 == 10:
                curves[label] = (t, n)
                spin10[label] = t[-1]
        rows.append((label, *res))
    table(rows, ["case", "from 5 rev/s", "from 10 rev/s", "from 15 rev/s"])
    floor = spin10["608-2Z nu20 x2.7 (pessimistic)"]
    print("\nUncertainty: the SKF model runs below the bearing's minimum load and with drop lubrication; the one")
    print("measured comparison (verifier) suggests it under-predicts friction by up to ~2.7x.  Therefore:")
    print(f"  planning floor (x2.7)          {floor:.0f} s from 10 rev/s")
    print(f"  ACCEPTANCE GATE                >= 35 s  (just under the floor: a unit that meets the pessimistic")
    print("                                 model passes; below it the bearing prep failed -> re-clean / swap)")
    print("  TARGET (verifier 45-60 s)      >= 45 s  (record the value; it calibrates the friction model)")
    print(f"  model expectation              {spin10['608-2Z oil nu20']:.0f}-{spin10['608-2Z oil nu10']:.0f} s")
    print("The 608/61808 ratio (~10x) is robust because the same model error applies to both.")
    print("\nAxial-load sensitivity (608, nu20, 10 rev/s):")
    rows = []
    for fa_x in (fa, 2.0, 2.7, 3.5, 5.0):
        mm = skf_moment(600, 20, fa_x, 0.05, BEARINGS["608-2Z"])
        t, n = spin_down(I_r, 10, lambda rpm, f=fa_x: skf_moment(rpm, 20, f, 0.05, BEARINGS["608-2Z"]),
                         c_lin=c_eddy, k_air=k_air)
        rows.append((f"{fa_x:.2f}", f"{mm:.3f}", f"{fa_x * 15 / 2:.1f}", f"{t[-1]:.0f}"))
    table(rows, ["Fa N", "M N*mm", "Fa*dm/2 mN*m", "spin from 10 rev/s s"])

    # ---------------- 4. detent LUT ----------------------------------------
    hr("4. Detent torque vs in-plane radial offset (verified LUT, log-linear interpolation)")
    step_carr = 0.02 * 0.75
    print(f"Actuator resolution: 0.020 mm/full step x 0.75 (inclined slot) = {step_carr:.3f} mm carriage per full step "
          f"-> {7.5 / step_carr:.0f} full steps for 7.5 mm.")
    rows = []
    for off in np.arange(0, 7.51, 0.5):
        t1 = detent_torque(off)
        k = N_DET * t1 * 1e-3
        fn = math.sqrt(k / I_r) / (2 * math.pi)
        e_b = 2 * t1 * 1e-3 / N_DET
        n_cap = math.sqrt(2 * e_b / I_r) / (2 * math.pi)
        rows.append((f"{off:.1f}", f"{t1:.4g}", f"{t1 / 35:.3f}", f"{fn:.1f}", f"{n_cap:.2f}", int(round(off / step_carr))))
    table(rows, ["offset mm", "T1 mN*m", "rim force N (r35)", "f_n Hz", "capture rev/s", "full steps"])
    print("Note: LUT simulated for R_t = 30 mm (research); SPEC uses R_t = 29.0 -> expect ~2-5 % lower torque.")

    # ---------------- 5. ringing --------------------------------------------
    hr("5. Detent ringing / settling after release")
    mb = lambda rpm: skf_moment(max(rpm, 0.5), 20, fa, 0.05, BEARINGS["608-2Z"])
    print(f"Bearing friction at 1 rev/s: {mb(60):.3f} N*mm; at 0.1 rev/s: {mb(6):.3f} N*mm.")
    ring_rows = []
    ring_curves = {}
    T_SHOE = 1.6
    for off, label in ((0.0, "full click (16.5 mN*m)"), (1.5, "default 9.5 mN*m (1.5 mm)")):
        t1 = detent_torque(off)
        for shoe in (0.0, T_SHOE):
            ts, ths, peaks, tset = ring_down(I_r, t1, mb, m_shoe_mnm=shoe, theta0_deg=6.0)
            ring_rows.append((label, f"{shoe:.1f}", peaks // 2, f"{tset:.2f}" if tset else f">{ts[-1]:.0f}",
                              f"+/-{math.degrees(shoe * 1e-3 / (N_DET * t1 * 1e-3)):.2f}" if shoe else "-"))
            ring_curves[(off, shoe)] = (ts, ths)
    table(ring_rows, ["detent", "shoe mN*m", "cycles", "t to <0.5 deg (s)", "rest error deg (T_f/k)"])
    print(f"Click-spin with the shoe engaged, from 5 rev/s: ~{I_r * 2 * math.pi * 5 / (T_SHOE * 1e-3 + mb(150) * 1e-3):.1f} s.")
    print("Shoe: felt/UHMW (not PTFE), N = 0.20 N at r 32: mu 0.2-0.3 -> 1.3-1.9 mN*m.")

    # ---------------- 6. balance --------------------------------------------
    hr("6. Balance: ISO 1940 G2.5 at 15 rev/s")
    w15 = 2 * math.pi * 15
    e_per = 2.5 / w15 * 1e3
    U_per = m_r * e_per * 1e-3
    print(f"e_per = {e_per:.1f} um -> U_per = {U_per:.2f} g*mm for the {m_r:.0f} g rotor (aim <= 2 g*mm).")
    m_carrier = parts[2][1]
    m_ringc = parts[0][1] + parts[1][1]
    m_one = parts[1][1] / MAG_N
    common = [("ring OD/ID eccentricity 0.02 mm TIR (e = 0.01)", parts[0][1] * 0.010),
              ("48 magnets, mass sigma 3 % (random, RSS)", math.sqrt(MAG_N) * 0.03 * m_one * RT),
              ("glue blob 5 mg at r = 29", 0.005 * RT)]
    a = common + [("ring bonded freehand on the carrier (e ~ 0.035)", (m_ringc + m_carrier) * 0.035)]
    b = common + [("ring bonded on an arbor through the 608, OD TIR <= 0.02 (e = 0.01)", (m_ringc + m_carrier) * 0.010)]
    rows = []
    for tag, lst in (("A no jig", a), ("B arbor jig", b)):
        for n_, u in lst:
            rows.append((tag, n_, f"{u:.2f}"))
        rows.append((tag, "RSS before correction", f"{math.sqrt(sum(u * u for _, u in lst)):.2f}"))
    table(rows, ["build", "source", "U g*mm"])
    print(f"Rotating force at the G2.5 limit: {U_per * 1e-6 * w15 ** 2:.3f} N.")
    hole = (math.pi * 1 ** 2 * 1.0 + math.pi * 1 ** 2 * 0.6 / 3) * RHO_316L * 31
    tap = math.pi * 0.8 ** 2 * 3.0 * RHO_316L * 31
    grub_b = math.pi * 0.8 ** 2 * 3.0 * 0.85 * RHO_BRASS * 31
    grub_w = math.pi * 0.8 ** 2 * 3.0 * 0.85 * 17.0e-3 * 31
    print(f"Correction quanta at r = 31: Ø2x1 dimple -{hole:.2f}; empty M2x3 tapped hole -{tap:.2f}; brass grub "
          f"+{grub_b:.2f}; W-alloy grub +{grub_w:.2f} g*mm.")

    # ---------------- 6b. mass budget ----------------------------------------
    hr("6b. Device mass budget and centre of gravity")
    budget = [
        ("base", "3x micro-suction arc pads", 1.0, 0.5),
        ("base", "base cup PA12 + shelf, columns, rib, boss (~11.9 cm^3)", 12.0, 5.5),
        ("base", "LiPo 503450-class protected, ~1000 mAh", 19.0, 5.0),
        ("base", "flex antenna 146153-0100 + coax (share)", 1.0, 6.0),
        ("base", "base board Ø46 + tab + parts", 6.9, 10.8),
        ("base", "guide pins, cross pins, stop screws, springs", 2.3, 9.0),
        ("base", "battery leads", 0.5, 8.0),
        ("FA", "FA spider plate PA12-GF (~1.95 cm^3)", 2.4, 13.5),
        ("FA", "spindle, turned 316L", 3.6, 20.0),
        ("FA", "brass lower spacer / drop stop", 2.6, 16.2),
        ("FA", "brass hub + M4 nut", 4.7, 27.5),
        ("FA", "608 inner ring + share of balls", 13 - parts[3][1], 21.5),
        ("FA", "main board Ø64 4L + parts", 12.3, 29.9),
        ("FA", "OLED glass + bracket + foam", 5.0, 33.2),
        ("FA", "light box + diffuser + cover + 0.7 mm cover glass", 8.5, 34.0),
        ("FA", "stepper + carriage + magnet + rails + saddle + link", 3.9, 25.0),
        ("FA", "screws, harness, coax (share)", 2.0, 22.0),
        ("rotor", "rotor (section 1)", m_r, z_r),
    ]
    rows = [(g_, it, f"{m:.1f}", f"{z:.1f}") for g_, it, m, z in budget]
    m_tot = sum(b_[2] for b_ in budget)
    z_tot = sum(b_[2] * b_[3] for b_ in budget) / m_tot
    m_fa_static = sum(b_[2] for b_ in budget if b_[0] == "FA")
    m_base = sum(b_[2] for b_ in budget if b_[0] == "base")
    rows.append(("", "TOTAL", f"{m_tot:.1f}", f"{z_tot:.1f}"))
    table(rows, ["group", "item", "g", "z_cg mm"])
    m_FA = m_fa_static + m_r
    print(f"Floating assembly (moves on press) = {m_FA:.0f} g (rotor {m_r:.0f} + {m_fa_static:.0f}); base = {m_base:.0f} g. "
          f"Static tip angle on the arc pads (edge 28.1 mm) ~ {math.degrees(math.atan(28.1 / z_tot)):.0f} deg.")

    # ---------------- 7. press click ---------------------------------------
    hr("7. Press click: springs, press pad, per-unit pre-gap, force vs radius")
    d_w, D_m, na, n_tot = 0.32, 3.63, 3, 5
    k_s = 69000 * d_w ** 4 / (8 * D_m ** 3 * na)
    L_inst = 13.1 - 10.5
    P0 = 4.0 / 3
    L0 = L_inst + P0 / k_s
    L_solid = n_tot * d_w
    L_stop = L_inst - STOP_TRAVEL
    F_stop = P0 + k_s * STOP_TRAVEL
    C = D_m / d_w
    wahl = (4 * C - 1) / (4 * C - 4) + 0.615 / C
    tau = 8 * F_stop * D_m / (math.pi * d_w ** 3) * wahl
    print(f"Spring: 302 SS wire {d_w}, Dm {D_m} (OD {D_m + d_w:.2f}), {na} active + 2 closed/ground, k = {k_s:.3f} N/mm, "
          f"L0 = {L0:.2f}, installed {L_inst:.2f} (ear seat 10.5 -> plate pocket 13.1) -> P0 = {P0:.2f} N each.")
    print(f"  at the 0.50 stop: L = {L_stop:.2f}, F = {F_stop:.2f} N, tau = {tau:.0f} MPa (Wahl); solid {L_solid:.2f} -> "
          f"margin {L_stop - L_solid:.2f} nominal, {L_stop - L_solid - 0.05 - 0.10:.2f} worst (solid +0.05, seats -0.10).")
    P_hi = 4.6 / 3
    print(f"  higher-preload option (4.6 N total): L0 = {L_inst + P_hi / k_s:.2f} with the SAME installed length -> "
          f"solid margin unchanged; F at stop {P_hi + k_s * STOP_TRAVEL:.2f} N.")
    W_fa = m_FA * 1e-3 * G
    print(f"FA weight W = {W_fa:.2f} N; net preload on the stops at rest = {3 * P0 - W_fa:.2f} N.")
    F_sw = 1.6
    print("\nPress pad (Ø3 x 1.0 silicone 40A in the spindle bottom, k ~ 15-30 N/mm [assume]) + per-unit pre-gap:")
    print("  set g0 = (stop - 0.05) - t_u - F_sw/k so the click happens 0.05 mm before the 0.50 hard stop;")
    print("  after the switch bottoms, only the pad compresses: F_switch at the stop = F_sw + k * 0.05.")
    rows = []
    for k_pad in (15.0, 22.0, 30.0):
        for t_u in (0.15, 0.25, 0.30, 0.35):
            g0 = STOP_TRAVEL - 0.05 - t_u - F_sw / k_pad
            Fst = F_sw + k_pad * 0.05
            Fst_hi = F_sw + k_pad * 0.075
            rows.append((f"{k_pad:.0f}", f"{t_u:.2f}", f"{g0:.3f}" + ("  REJECT (<0.05)" if g0 < 0.05 else ""),
                         f"{Fst:.2f}", f"{Fst_hi:.2f}", f"{0.05 + F_sw / k_pad:.3f}"))
    table(rows, ["k_pad N/mm", "switch travel t_u", "pre-gap g0 mm", "F_sw at stop N", "(shim +0.025)", "pad compression mm"])
    print("  Old design check (0.5 mm TPU dot, ~70 N/mm, fixed 0.15 pre-gap, 0.60 stop): switch bottoms at 0.27-0.42,")
    print(f"  the dot then takes {0.60 - 0.42:.2f}-{0.60 - 0.27 + 0.02:.2f} mm -> {70 * 0.18 + 1.6:.0f}-{70 * 0.35 + 1.6:.0f} N through a 1.6 N switch (rejected).")
    g_act = STOP_TRAVEL - 0.05
    print(f"\nClick force vs press point (actuation at {g_act:.2f} mm by construction, F_sw = {F_sw} N; "
          f"guides at r {GUIDE_RS}):")
    radii = np.arange(0, 35.01, 0.5)
    press = {}
    for th, lab in ((60, "over a stop (θ=60°)"), (0, "between stops (θ=0°)"), (180, "over the r30 stop (θ=180°)")):
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
    i335 = int(round(33.5 / 0.5))
    print(f"\nDevice weight {W_dev:.2f} N.  Rim press at r = 33.5: 3 point feet at r 28 tip at "
          f"{tip_force(33.5, W_dev, edge3):.2f} N (< rim click {min(v_[i335] for v_ in press.values()):.2f}-"
          f"{max(v_[i335] for v_ in press.values()):.2f} N); 70 deg arc pads r 25-31 (edge {edge_arc:.1f}) tip at "
          f"{tip_force(33.5, W_dev, edge_arc):.1f} N.")

    # ---------------- 8. TMAG sampling ---------------------------------------
    hr("8. TMAG5273 sample rate / aliasing for the 24-pole-pair track")
    pp = MAG_N // 2
    for fs_nom, mode in ((3100, "XZX, 4x avg (research config)"), (4400, "ZX, 4x avg")):
        for tol, tl in ((1.0, "nom"), (0.9, "-10 %")):
            fs = fs_nom * tol
            fe = pp * 30
            print(f"  {mode:32s} fs={fs:6.0f} Hz ({tl:5s}): f_elec @30 rev/s = {fe} Hz, advance {360 * fe / fs:5.1f} "
                  f"deg/sample, Nyquist at {fs / 2 / pp:5.1f} rev/s, margin {fs / 2 / pp / 30:.2f}x")
    T = 1 / 3100
    dphi = 2 * math.pi * pp * 30 * (2 * T / 3)
    ax_ratio = math.cos(dphi / 2)
    err_e = math.degrees(math.asin((1 - ax_ratio) / (1 + ax_ratio)))
    print(f"  XZX skew at 30 rev/s: X/Z = {ax_ratio:.3f} -> max atan2 error {err_e:.1f} deg el. = {err_e / pp:.2f} deg mech.")
    zt = MB_Z0 - TMAG_PKG_H + TMAG_ELEM_DEPTH
    print(f"  Hall element z = {zt:.2f} -> {zt - RING_Z1:.2f} mm above the track face (window 2.2-4.0 [verifier]).")

    # ---------------- 9. drop & flick ---------------------------------------
    hr("9. Drop shock: 608, compliant seat, guide-pin rebound; flick reactions")
    lim = 0.25 * 1370
    print(f"608 pure-axial static limit = 0.25*C0 = {lim:.0f} N [verifier].  Rotor {m_r:.0f} g, rigid seat:")
    rows = []
    for h in (0.1, 0.3, 0.75):
        v = math.sqrt(2 * G * h)
        rows.append((h, *[f"{m_r * 1e-3 * v * v / (2 * s * 1e-3):.0f}" for s in (0.5, 1.0, 2.0)]))
    table(rows, ["drop m", "F @ 0.5 mm stop", "F @ 1 mm", "F @ 2 mm"])
    for P_ws, k_ws in ((30, 150), (50, 300)):
        print(f"  compliant seat: wave washer {P_ws} N preload, {k_ws} N/mm -> at the 0.15 mm drop stop the balls see "
              f"{P_ws + k_ws * 0.15:.0f} N (< {lim:.0f} N); the carrier lip then lands on the brass drop-stop flange.")
    m_fa_kg = m_FA * 1e-3
    print("Guide-pin rebound (pins in tension): after a flat drop the FA bounces off the column/ear stops and is")
    print("caught by the three stop screws.  F_total = v_rebound * sqrt(m * k_stop) [assume e, k_stop]:")
    rows = []
    for h in (0.1, 0.3):
        v = math.sqrt(2 * G * h)
        for e, kst in ((0.3, 3 * 5e6), (0.6, 3 * 15e6)):
            F = e * v * math.sqrt(m_fa_kg * kst)
            rows.append((h, e, f"{kst / 3e6:.0f}", f"{F / 3:.0f}"))
    table(rows, ["drop m", "restitution", "k_stop per pin kN/mm", "load per pin N"])
    tau_b = 3.0   # MPa knurl + Loctite 638 into PA12 [assume]
    xpin = min(2 * math.pi / 4 * 1.0 ** 2 * 150, 1.0 * 2 * 2.0 * 40)
    for name, L in (("theta 60 ear (z 6.5-10.5, above the antenna)", 4.0), ("theta 180/300 columns (z 2.5-10.5)", 8.0)):
        cap = tau_b * math.pi * 3.0 * L + xpin
        print(f"  pull-out {name}: knurl+bond {tau_b * math.pi * 3.0 * L:.0f} N + Ø1 cross pin {xpin:.0f} N = {cap:.0f} N")
    print("  -> >= 2x the 0.1 m rebound estimate; a 0.3 m drop can exceed the theta-60 ear (pull test, section 15).")
    J = I_r * 2 * math.pi * 10 / 0.035
    print(f"Flick to 10 rev/s: lateral impulse {J:.3f} N*s -> ~{J / 0.03:.1f} N average over 30 ms vs slide threshold "
          f"{0.6 * W_dev:.1f}-{1.0 * W_dev:.1f} N: the puck slides unless held or on micro-suction pads.")

    # ---------------- 10. actuator ------------------------------------------
    hr("10. Detent actuator force budget (inclined-slot cam 0.75) and stroke time")
    alpha = math.atan(0.75)
    F_MAG, N_V, N_T, N_SHOE, PIN_PRE = 0.29, 0.70, 0.55, 0.20, 0.50
    print(f"Loads at the carriage: magnetic radial {F_MAG} N (opposes retraction, aids engagement) [verifier];")
    print(f"normal (vertical) {N_V} N at rest in a well; tangential {N_T} N only while the rotor turns [verifier];")
    print(f"shoe normal {N_SHOE} N (reacted by the rails), shoe lift ramp 8 deg / flexure 0.2 N/mm over 0.5 mm in the")
    print(f"1.5-2.3 mm zone; spring-loaded drive pin {PIN_PRE} N against one slot flank (zero pin lash); cam lateral")
    print("reaction F_x = 0.75 F_y on the rail sides.  Anti-lash: preloaded slider nut (no axial spring) unless noted.")
    rows = []
    worst = {}
    for case, mu_r, mu_p, mu_s, turning, spring in (
            ("retract at rest, low mu", 0.10, 0.10, 0.2, False, 0.0),
            ("retract at rest, high mu", 0.15, 0.20, 0.3, False, 0.0),
            ("engage at rest, high mu", 0.15, 0.20, 0.3, False, 0.0),
            ("retract while turning, high mu", 0.15, 0.20, 0.3, True, 0.0),
            ("engage + 0.35-0.65 N anti-lash spring, high mu", 0.15, 0.20, 0.3, False, 0.65)):
        retract = case.startswith("retract")
        ramp = (N_SHOE + 0.2 * 0.5) * math.tan(math.radians(8) + math.atan(mu_s)) if retract else 0.0
        fmag = F_MAG if retract else 0.0
        fric = mu_r * (N_V + N_SHOE + (N_T if turning else 0.0)) + mu_s * N_SHOE
        base = fmag + ramp + fric + spring
        F_y = base / (1 - 0.75 * mu_r)
        F_sl = F_y * math.tan(alpha + math.atan(mu_p)) + mu_p * PIN_PRE
        worst[case] = F_sl
        rows.append((case, f"{fmag:.2f}", f"{ramp:.2f}", f"{fric:.2f}", f"{F_y - base:.2f}", f"{spring:.2f}",
                     f"{F_y:.2f}", f"{F_sl:.2f}", f"{0.78 / F_sl:.2f}"))
    table(rows, ["case", "magnetic", "ramp", "rail+shoe fric", "cam lateral", "spring", "carriage F_y",
                 "slider thrust", "margin on 0.78 N"])
    print("Rating: VSM08102 >= 80 gf (0.78 N) pull-out at 500 PPS, voltage not stated [research]; VM = VSYS 3.0-4.5 V.")
    print("-> at rest the 8 mm motor has ~1.0-1.5x margin; while turning or with a separate anti-lash spring it can")
    print("   fall below 1x.  The 10 mm sibling (Ø10 can) does NOT fit the 10.1 mm bowl (web 19.0 -> board 29.1).")
    print("   Gate: slider thrust >= 0.85 N at 3.0 V / 300 PPS against the real carriage (section 15).")
    steps_loaded, steps_free = 267, 233
    for pps in (500, 300, 200):
        print(f"  stroke time: loaded zone (0-4 mm, {steps_loaded} steps) at {pps} PPS + {steps_free} steps at 800 PPS = "
              f"{steps_loaded / pps + steps_free / 800:.2f} s")
    print("  Firmware: move the carriage only with the rotor at rest or slow (< 1 rev/s), never during a flick.")

    # ---------------- 11. clearances ----------------------------------------
    hr("11. Clearances (model-derived): stack, board parts vs rotor / hub / actuator / FA plate")
    prims, rc = load_prims()
    P = {p[1]: p for p in prims}
    rows = [
        ("ring bottom - cup wall top", RING_Z0 - CUP_TOP, RING_Z0 - CUP_TOP - STOP_TRAVEL),
        ("ring bottom - stop-screw head top", RING_Z0 - HEAD_TOP, RING_Z0 - HEAD_TOP - STOP_TRAVEL),
        ("detent magnet face - track face", DET_GAP, DET_GAP),
        ("TMAG element - track face", MB_Z0 - TMAG_PKG_H + TMAG_ELEM_DEPTH - RING_Z1, None),
        ("FA plate top - carrier web (wires run here)", 17.0 - FA_Z1, 17.0 - FA_Z1),
        ("carrier lip - brass drop-stop flange", 0.15, 0.15),
        ("stepper bracket bar - rotating web", (23.8 - 4) - 19.0, None),
        ("stepper front plate - collar (plan, r)", math.hypot(5.5, 11.5) - 12.2, None),
        ("rotor hub top (cap ring) - board bottom", MB_Z0 - ROT_HUB_TOP, None),
        ("press pad - switch actuator (pre-gap)", 0.15, "per unit 0.03-0.23"),
        ("base board bottom - LiPo top (6.0 envelope)", 9.5 - 8.5, None),
        ("FA plate / spokes - base board top", FA_Z0 - BB_Z1, FA_Z0 - BB_Z1 - STOP_TRAVEL),
        ("plate under-boss - cup stop face", STOP_TRAVEL, 0.0),
    ]
    table([(a, f"{b:+.2f}", c if isinstance(c, str) else ("-" if c is None else f"{c:+.2f}")) for a, b, c in rows],
          ["pair", "rest mm", "pressed (0.50) mm"])
    bp = json.load(open(os.path.join(HERE, "board_parts.json")))
    rot_rest = rotor_polys(rc)
    rot_press = rotor_polys(rc, -STOP_TRAVEL)
    hub_axi = [P["hub_flange"], P["hub_lower"], P["drop_stop_flange"]]
    act_click = [p for p in prims if p[1].endswith("@click")]
    act_free = [p for p in prims if p[1].endswith("@free")]
    wires = [P["harness"], P["coax"]]

    def nearest(X, plist, skip=()):
        best = (np.inf, "")
        for pr in plist:
            if any(s in pr[1] for s in skip):
                continue
            d = float(sdf_prim(X, pr).min())
            if d < best[0]:
                best = (d, pr[1].split("@")[0])
        return best

    print("\nMain-board BOTTOM parts (z from the PCB; rotor clearance is exact, the rest sampled at 0.12 mm).")
    print("Only parts with any clearance < 1.0 mm are listed; negative = interference.")
    rows = []
    flagged = []
    for p in bp["main"]["parts"]:
        if p["side"] != "B":
            continue
        X = part_samples(p)
        c_rot = axisym_clearance(p, rot_rest)
        c_hub = float(min(sdf_prim(X, pr).min() for pr in hub_axi))
        c_ac, n_ac = nearest(X, act_click)
        c_af, n_af = nearest(X, act_free)
        skip = ("harness",) if p["ref"].startswith("J1") else ()
        skip += ("coax",) if p["ref"].startswith("U10") else ()
        c_w, n_w = nearest(X, wires, skip)
        vals = [c_rot, c_hub, c_ac, c_af, c_w]
        if min(vals) < 1.0:
            rmin, rmax, z0, z1 = part_rz(p)
            rows.append((p["ref"], p["value"][:16], f"r {rmin:.1f}-{rmax:.1f}", f"z {z0:.2f}-{z1:.2f}",
                         f"{c_rot:+.2f}", f"{c_hub:+.2f}", f"{c_ac:+.2f} {n_ac}", f"{c_af:+.2f} {n_af}",
                         f"{c_w:+.2f} {n_w}"))
            if min(vals) < 0.3:
                flagged.append(p["ref"])
    table(rows, ["ref", "value", "r", "z", "rotor", "hub/spacer", "actuator@click", "actuator@free", "harness/coax"])
    print(f"Parts below 0.3 mm (action needed): {', '.join(flagged) if flagged else 'none'}")

    print("\nBase-board TOP parts: rotor at rest / pressed (exact), FA spider plate pressed (plan overlap -> z gap).")
    rows = []
    for p in bp["base"]["parts"]:
        if p["side"] != "T":
            continue
        X = part_samples(p, 0.25)
        c_rr = axisym_clearance(p, rot_rest)
        c_rp = axisym_clearance(p, rot_press)
        under = any(under_spider(x, y) for x, y, _ in X[::3])
        top = p["z0"] + p["h"]
        c_pl = (FA_Z0 - STOP_TRAVEL - top) if under else None
        c_pl0 = (FA_Z0 - top) if under else None
        rmin, rmax, z0, z1 = part_rz(p)
        if p["ref"] == "SW1":
            c_pl = c_pl0 = None
        if min(c_rp, c_pl if c_pl is not None else 9) < 1.5:
            rows.append((p["ref"], p["value"][:14], f"r {rmin:.1f}-{rmax:.1f}", f"top z {top:.2f}", f"{c_rr:+.2f}",
                         f"{c_rp:+.2f}", "-" if c_pl0 is None else f"{c_pl0:+.2f}", "-" if c_pl is None else f"{c_pl:+.2f}"))
    table(rows, ["ref", "value", "r", "height", "rotor rest", "rotor pressed", "plate rest", "plate pressed"])
    print("SW1 is handled by the pre-gap (section 7).  Rule from SPEC: parts under a spoke/hub <= 1.0 mm tall "
          f"(gap {FA_Z0 - BB_Z1:.1f} rest, {FA_Z0 - BB_Z1 - STOP_TRAVEL:.1f} pressed).")

    print("\nMain-board TOP parts under the OLED bracket rim/spokes (z 31.8-32.8) and the glass (z 33.0):")
    top_rows = []
    BRK_TOP = 32.8
    rim_o = (33.8 - 0.4) / 2, (34.0 - 0.4) / 2
    rim_i = (33.8 - 4.4) / 2, (34.0 - 4.4) / 2
    for p in bp["main"]["parts"]:
        if p["side"] != "T":
            continue
        X = part_samples(p, 0.2)
        top = p["z0"] + p["h"]
        xs, ys = X[:, 0], X[:, 1] + 1.47
        in_rim = np.any((np.abs(xs) <= rim_o[0]) & (np.abs(ys) <= rim_o[1]) &
                        ~((np.abs(xs) <= rim_i[0]) & (np.abs(ys) <= rim_i[1])))
        in_spoke = False
        for a in (90, 210, 330):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            along = X[:, 0] * ca + X[:, 1] * sa
            across = -X[:, 0] * sa + X[:, 1] * ca
            in_spoke |= bool(np.any((along >= 4.5) & (along <= 16.3) & (np.abs(across) <= 1.0)))
        under_glass = np.any((np.abs(xs) <= 16.9) & (np.abs(ys) <= 17.0))
        if in_rim or in_spoke:
            if p["h"] > 0.95:
                left = BRK_TOP - top - 0.2
                top_rows.append((p["ref"], p["value"][:14], f"top z {top:.2f}", "rim/spoke",
                                 f"pocketed: +0.20, rim left {left:.2f}" if left >= 0.4 else "pocket cut through"))
            elif 31.8 - top < 0.3:
                top_rows.append((p["ref"], p["value"][:14], f"top z {top:.2f}", "rim/spoke", f"{31.8 - top:+.2f}"))
        elif under_glass and 33.0 - top < 0.6:
            top_rows.append((p["ref"], p["value"][:14], f"top z {top:.2f}", "glass", f"{33.0 - top:+.2f}"))
        rmin, rmax, _, _ = part_rz(p)
        if rmax > 30.6 and top > 30.75:
            top_rows.append((p["ref"], p["value"][:14], f"r {rmin:.2f}-{rmax:.2f}", "cover skirt r>=30.6",
                             f"{30.6 - rmax:+.2f} (radial)"))
    table(top_rows or [("-", "none", "", "", "")], ["ref", "value", "height", "under", "clearance"])
    print("The bracket is pocketed (0.3 mm all round, 0.2 above) over every top part taller than 0.95 mm.")

    # ---------------- 12. wiring, window, USB, misc --------------------------
    hr("12. Harness, coax, cover glass, USB-C plug, carriage lash")
    wires_od = [0.75] * 5 + [0.55] * 7          # 28 AWG power (SPEC), 32 AWG signals [assume OD]
    a_w = sum(math.pi / 4 * d * d for d in wires_od)
    a_c = math.pi / 4 * 1.13 ** 2
    for name, w_, h_ in (("bottom slot / spacer window", 5.0, 1.9), ("top slot", 5.0, 2.45),
                         ("hub C-gap (5.0 x 3.0)", 5.0, 3.0), ("bore Ø6", None, None)):
        area = math.pi * 9 if w_ is None else w_ * h_
        print(f"  {name:30s} {area:5.1f} mm^2: 12 wires {a_w:.2f} + coax {a_c:.2f} -> fill {(a_w + a_c) / area * 100:.0f} %")
    print("  The 12 wires pass the 1.9-tall slot as a 2 x 6 ribbon (4.5 x 1.5).  SHR-12V-S housings (~14 x 3) cannot pass:")
    print("  route pre-crimped single wires (contacts only) and insert them into the housings afterwards.")
    L_h = chain_length(P["harness"])
    L_c = chain_length(P["coax"])
    print(f"  harness path (J3 plug -> J1 plug, as modelled) {L_h:.0f} mm -> cut 12 wires to {L_h + 15:.0f} mm (+15 slack)")
    print(f"  coax path (antenna feed -> u.FL) {L_c:.0f} mm; 146153-0100 has 100 mm -> {100 - L_c:.0f} mm to stow "
          "(one gentle loop in the base, theta 100-150, away from the antenna)")
    print(f"  battery leads path {chain_length(P['battery_leads']):.0f} mm")
    E_g, nu_g = 70000.0, 0.22
    for t_l, mat, E_, nu_ in ((0.7, "0.7 mm chem.-strengthened glass", E_g, nu_g), (1.0, "1.0 mm PC", 2400.0, 0.38),
                              (0.5, "0.5 mm PC (old optional lens)", 2400.0, 0.38)):
        D = E_ * t_l ** 3 / (12 * (1 - nu_ ** 2))
        for F in (4.4, 20.0):
            dss = F * 15.0 ** 2 * (3 + nu_) / (16 * math.pi * (1 + nu_) * D)
            print(f"  window {mat:32s} Ø30 simply supported, {F:4.1f} N centre: deflection {dss:.3f} mm "
                  f"(gap to OLED glass 0.6 mm)")
    z_cl = 11.1 + 3.26 / 2
    for h_om in (6.0, 6.5, 7.0):
        z_top = z_cl + h_om / 2
        for pr_ in (0.0, STOP_TRAVEL):
            zr = z_top + pr_ - RING_Z0           # ring-local height of the overmold top
            r_ring = RING_RO - CH_BO + min(max(zr, 0), CH_BO) if zr < CH_BO else RING_RO
            print(f"  USB-C overmold {h_om:.1f} mm tall (top z {z_top:.2f}){' pressed' if pr_ else ''}: ring radius at that "
                  f"height {r_ring:.2f} -> radial clearance to the plug face (r 35) {RING_RO - r_ring:.2f} mm")
    print("  Carriage lash budget: slider nut preloaded (anti-backlash, verify <= 0.02 mm), spring pin in slot 0,")
    print("  FR4 link 0.8 x 3: in-plane deflection at 0.4 N over 20 mm "
          f"{0.4 * 20 ** 3 / (3 * 20000 * 0.8 * 3 ** 3 / 12):.3f} mm (PA12 0.5 strip was "
          f"{0.4 * 20 ** 3 / (3 * 1700 * 0.5 * 3 ** 3 / 12):.2f} mm); plate capture <= 0.02 (shimmed rails).")

    if plots:
        make_plots(curves, ring_curves, press, radii, I_r, W_dev, edge3, edge_arc, floor)
    return 0


def make_plots(curves, ring_curves, press, radii, I_r, W_dev, edge3, edge_arc, floor):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(RENDERS, exist_ok=True)
    BLUE, ORANGE, AQUA, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=130)
    sty = {"608-2Z oil nu10": (BLUE, "-"), "608-2Z oil nu20": (BLUE, "--"),
           "608-2Z nu20 x2.7 (pessimistic)": (BLUE, ":"), "61808 oil nu20": (ORANGE, "-"),
           "61808 nu20 x2.7": (ORANGE, ":")}
    for lab, (c, ls) in sty.items():
        t, n = curves[lab]
        ax.plot(t, n, color=c, ls=ls, lw=2)
        ax.annotate(f"{lab}  ({t[-1]:.0f} s)", (t[-1], 0.0), xytext=(t[-1] * 0.55 + 2, 0.4 + 0.9 * list(sty).index(lab)),
                    color=INK, fontsize=8, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    for x, txt in ((35, "gate >= 35 s"), (45, "target >= 45 s")):
        ax.axvline(x, color=MUTED, lw=1, ls=(0, (2, 3)))
        ax.text(x + 1, 9.6 if x == 45 else 8.9, txt, color=MUTED, fontsize=8)
    ax.set_xlabel("time after a 10 rev/s flick (s)")
    ax.set_ylabel("speed (rev/s)")
    ax.set_title("Spin-down, SKF friction model + small eddy/air terms", loc="left", color=INK)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_ylim(0, 10.5)
    ax.set_xlim(0, None)
    fig.text(0.01, 0.01, f"blue = 608-2Z, orange = 61808; dotted = 2.7x friction (planning floor {floor:.0f} s). "
             f"Gate 35 s = bearing-prep check; target 45 s. I = {I_r:.2e} kg m^2.", color=MUTED, fontsize=7.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(os.path.join(RENDERS, "calc_spindown.png"))
    plt.close(fig)

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
    for (o, shoe), c in (((0.0, 0.0), BLUE), ((0.0, 1.6), ORANGE)):
        ts, ths = ring_curves[(o, shoe)]
        a2.plot(ts, ths, color=c, lw=1.2 if shoe == 0 else 2)
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

    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=130)
    for (lab, f), c in zip(press.items(), (BLUE, ORANGE, AQUA)):
        ax.plot(radii, f, color=c, lw=2)
        ax.annotate(lab, (radii[-1], f[-1]), xytext=(4, 0), textcoords="offset points", fontsize=8, color=INK, va="center")
    rr = np.linspace(15, 35, 100)
    ax.plot(rr, [tip_force(r, W_dev, edge3) for r in rr], color=MUTED, lw=1.2, ls="--")
    ax.text(15.5, 3.2, "tip limit, 3 point feet r28", color=MUTED, fontsize=8)
    ax.axvspan(32.5, 35, color=GRID, lw=0)
    ax.text(32.6, 0.25, "ring rim", color=MUTED, fontsize=8)
    ax.set_ylim(0, 6)
    ax.set_xlim(0, 44)
    ax.set_xlabel("press radius (mm)")
    ax.set_ylabel("force to click (N)")
    ax.set_title("Press-click force vs radius and azimuth (4.0 N preload, click at 0.45 mm)", loc="left", color=INK)
    ax.grid(True, color=GRID, lw=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(RENDERS, "calc_press.png"))
    plt.close(fig)
    print("\nplots: renders/calc_spindown.png, renders/calc_detent.png, renders/calc_press.png")


if __name__ == "__main__":
    sys.exit(main(plots="--no-plots" not in sys.argv))
