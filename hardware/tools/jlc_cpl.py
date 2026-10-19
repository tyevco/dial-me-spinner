"""JLCPCB pick-and-place: per-part rotation/origin corrections and the CPL writer.

JLC places every part with its own (EasyEDA/LCSC) footprint. Where that footprint's
zero orientation or origin differs from the KiCad one, a CPL that copies KiCad's
angle places the part rotated (often by 180°, which still fits the pads) or
offset. For each LCSC code this module fetches the EasyEDA footprint and fits its
pads to the KiCad library footprint by pad number. It then caches
{rotation α, origin (dx, dy) in KiCad footprint coordinates} in
hardware/design/jlc_offsets.json and writes the CPL with
  top:    angle = (θ + α) mod 360
  bottom: angle = (180 − θ + α) mod 360          (same convention as kicad-jlcpcb-tools)
and the JLC origin transformed onto the board.
"""

from __future__ import annotations

import csv
import json
import math
import os
import urllib.error
import urllib.request

import pcbnew

EE_URL = "https://easyeda.com/api/products/{code}/components?version=6.4.19.5"
EE_UNIT = 0.254  # EasyEDA canvas unit (10 mil) in mm
HERE = os.path.dirname(os.path.abspath(__file__))
OFFSETS = os.path.join(os.path.dirname(HERE), "design", "jlc_offsets.json")


def _ee_pads(code):
    import time
    req = urllib.request.Request(EE_URL.format(code=code), headers={"User-Agent": "Mozilla/5.0 (dial-me-spinner jlc_cpl)"})
    for attempt in range(6):  # the EasyEDA API rate-limits with HTTP 403; back off and retry
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)["result"]
            break
        except urllib.error.HTTPError as e:
            if e.code != 403 or attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))
    time.sleep(0.7)
    ds = d["packageDetail"]["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    pads = {}
    for s in ds["shape"]:
        if s.startswith("PAD~"):
            f = s.split("~")
            pads.setdefault(f[8], []).append(((float(f[2]) - ox) * EE_UNIT, (float(f[3]) - oy) * EE_UNIT))
    return d["packageDetail"].get("title", ""), pads


def _rot(p, a):
    a = math.radians(a)
    x, y = p
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def _centroid(pts):
    return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))


def _lib_footprint(fp, lib_dirs):
    nick = str(fp.GetFPID().GetLibNickname())
    name = str(fp.GetFPID().GetLibItemName())
    path = lib_dirs.get(nick, f"/usr/share/kicad/footprints/{nick}.pretty")
    return pcbnew.FootprintLoad(path, name)


def fit(code, lib_fp):
    """Best rotation (0/90/180/270) and EE origin in KiCad-local mm, by pad-number fitting."""
    title, ep = _ee_pads(code)
    kp = {}
    for p in lib_fp.Pads():
        if p.GetNumber():
            v = p.GetPosition()
            kp.setdefault(p.GetNumber(), []).append((pcbnew.ToMM(v.x), pcbnew.ToMM(v.y)))
    common = [n for n in kp if n in ep]
    if len(common) < 2:
        return None
    K = {n: _centroid(kp[n]) for n in common}
    E = {n: _centroid(ep[n]) for n in common}
    best = None
    for a in (0, 90, 180, 270):
        Er = {n: _rot(E[n], a) for n in common}
        tx = sum(K[n][0] - Er[n][0] for n in common) / len(common)
        ty = sum(K[n][1] - Er[n][1] for n in common) / len(common)
        rms = math.sqrt(sum((K[n][0] - Er[n][0] - tx) ** 2 + (K[n][1] - Er[n][1] - ty) ** 2 for n in common) / len(common))
        if best is None or rms < best["rms"]:
            best = {"rot": a, "dx": round(tx, 3), "dy": round(ty, 3), "rms": round(rms, 3)}
    best.update(title=title, matched=len(common), kicad_pads=len(kp), ee_pads=len(ep),
                footprint=str(lib_fp.GetFPID().GetLibItemName()))
    return best


def update_offsets(board_paths, lib_dirs, refresh=False):
    table = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    for path in board_paths:
        b = pcbnew.LoadBoard(path)
        for fp in b.GetFootprints():
            code = fp.GetFieldText("LCSC") if fp.HasFieldByName("LCSC") else ""
            if not code or fp.IsDNP() or (code in table and "rot" in table[code] and not refresh):
                continue
            try:
                r = fit(code, _lib_footprint(fp, lib_dirs))
            except Exception as e:  # noqa: BLE001 — network or parse problem: record it
                r = {"error": str(e)}
            table[code] = r or {"error": "no common pads"}
    with open(OFFSETS, "w") as f:
        json.dump(dict(sorted(table.items())), f, indent=1)
        f.write("\n")
    return table


def _local_to_board(fp, lib_fp, lx, ly):
    """Map a library-local point onto the board via the pads (handles rotation and bottom flip)."""
    import numpy as np
    loc = {p.GetNumber(): p.GetPosition() for p in lib_fp.Pads() if p.GetNumber()}
    src, dst = [], []
    for p in fp.Pads():
        q = loc.get(p.GetNumber())
        if q is not None:
            src.append((pcbnew.ToMM(q.x), pcbnew.ToMM(q.y), 1.0))
            dst.append((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)))
    if len(src) < 3:  # 2-pad parts: fall back to the footprint position + rotated offset
        th = fp.GetOrientationDegrees()
        sx = -1 if fp.IsFlipped() else 1
        rx, ry = _rot((lx * sx, ly), th)
        pos = fp.GetPosition()
        return pcbnew.ToMM(pos.x) + rx, pcbnew.ToMM(pos.y) + ry
    sol, *_ = np.linalg.lstsq(np.array(src), np.array(dst), rcond=None)
    x, y = np.array([lx, ly, 1.0]) @ sol
    return float(x), float(y)


def write_cpl(pcb_path, out_csv, lib_dirs, strict=True):
    table = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    b = pcbnew.LoadBoard(pcb_path)
    org = b.GetDesignSettings().GetAuxOrigin()
    ox, oy = pcbnew.ToMM(org.x), pcbnew.ToMM(org.y)
    rows, missing = [], []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        attrs = fp.GetAttributes()
        if fp.IsDNP() or attrs & pcbnew.FP_EXCLUDE_FROM_POS_FILES or attrs & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        code = fp.GetFieldText("LCSC") if fp.HasFieldByName("LCSC") else ""
        corr = table.get(code, {})
        if "rot" not in corr:
            missing.append(f"{fp.GetReference()} ({code or 'no LCSC'})")
            corr = {"rot": 0, "dx": 0.0, "dy": 0.0}
        th = fp.GetOrientationDegrees()
        bottom = fp.IsFlipped()
        ang = ((180 - th) if bottom else th) + corr["rot"]
        ang = round(ang % 360, 2)
        lib_fp = _lib_footprint(fp, lib_dirs)
        x, y = _local_to_board(fp, lib_fp, corr.get("dx", 0.0), corr.get("dy", 0.0))
        rows.append([fp.GetReference(), f"{x - ox:.4f}mm", f"{-(y - oy):.4f}mm", "Bottom" if bottom else "Top", f"{ang:g}"])
    if missing and strict:
        raise RuntimeError("no JLC rotation/origin correction for: " + ", ".join(missing))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(rows)
    return out_csv, missing
