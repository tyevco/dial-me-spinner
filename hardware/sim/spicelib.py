"""SPICE test harness: builds ngspice decks from the real KiCad netlists.

Every simulation starts from hardware/kicad/<board>/dial-me-spinner-<board>.net, so a schematic change is
picked up by the next test run. Passives (R/C/L) come straight from the netlist with their values. ICs are
replaced by behavioural models from hardware/sim/models/ (each model file cites the datasheet it follows).

    d = Design("main")
    deck = Deck("LED data line")
    deck.include("ws2812c.lib")
    deck += d.passives(nets={"LED_DIN_MCU", "LED_DIN_R", "LED_DIN"})
    deck += f"XLED {d.node('LED_DIN')} {d.node('VLED')} 0 WS2812C_DIN"
    deck.tran("10n", "5u")
    deck.meas("tran vmax MAX v(n_led_din)")
    res = deck.run()            # {"vmax": 3.29}

Fault injection (to prove that a test really detects the failure it guards against):
    d.override("R40", "22")     # change a value
    d.remove("C7")              # leave a part off
    d.short("R43")              # replace a part by a short (0 Ω)
"""

from __future__ import annotations

import itertools
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
MODELS = os.path.join(HERE, "models")
sys.path.insert(0, os.path.join(HW, "tools"))

import sexpr  # noqa: E402
from sexpr import find, find_all  # noqa: E402

NGSPICE = shutil.which("ngspice")

_SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6,
       "G": 1e9, "R": 1.0, "r": 1.0, "": 1.0}

# default tolerances when the value string does not give one
DEFAULT_TOL = {"R": 0.01, "C": 0.10, "L": 0.20}


def parse_value(s: str) -> float:
    """'4.7u/25V' -> 4.7e-6, '499k 0.5%' -> 499e3, '4R7' -> 4.7, '220' -> 220, '0' -> 0, '12p C0G' -> 12e-12."""
    tok = s.strip().split()[0].split("/")[0] if s.strip() else ""
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([fpnuµmkKMGRr]?)([0-9]*)(?:[FHΩ]|Ohm|ohm)?", tok)
    if not m:
        raise ValueError(f"cannot parse component value {s!r}")
    num, unit, frac = m.groups()
    if frac:  # 4k7 / 4R7 style
        num = f"{num}.{frac}"
    return float(num) * _SI[unit]


def parse_tol(s: str, kind: str) -> float:
    m = re.search(r"([0-9]*\.?[0-9]+)\s*%", s)
    return float(m.group(1)) / 100 if m else DEFAULT_TOL.get(kind, 0.05)


def node_name(net: str) -> str:
    if net in ("GND", "/GND", "0"):
        return "0"
    n = net.split("/")[-1] if net.startswith("/") else net
    n = re.sub(r"[^A-Za-z0-9_]", "_", n.replace("+", "p"))
    return "n_" + n.lower()


class Design:
    """One board's netlist, with value overrides / removals / shorts for fault injection."""

    def __init__(self, board: str, path: str | None = None):
        self.board = board
        path = path or os.path.join(HW, "kicad", board, f"dial-me-spinner-{board}.net")
        tree = sexpr.parse(open(path, encoding="utf-8").read())
        self.comps = {}
        for c in find_all(find(tree, "components"), "comp"):
            ref = str(find(c, "ref")[1])
            fields = {}
            fl = find(c, "fields")
            if fl:
                for f in find_all(fl, "field"):
                    fields[str(find(f, "name")[1])] = str(f[2]) if len(f) > 2 else ""
            props = {str(find(p, "name")[1]): (str(find(p, "value")[1]) if find(p, "value") else "")
                     for p in find_all(c, "property")}
            self.comps[ref] = dict(ref=ref, value=str(find(c, "value")[1]), fields=fields, props=props,
                                   dnp="dnp" in props or bool(fields.get("DNP")))
        self.nets = {}      # net -> [(ref, pin, pinfunction)]
        self.pins = {}      # ref -> {pin: net}
        self.funcs = {}     # ref -> {pinfunction: net}
        for net in find_all(find(tree, "nets"), "net"):
            name = str(find(net, "name")[1])
            short = name.split("/")[-1] if name.startswith("/") else name
            lst = []
            for nd in find_all(net, "node"):
                ref, pin = str(find(nd, "ref")[1]), str(find(nd, "pin")[1])
                pf = find(nd, "pinfunction")
                func = str(pf[1]) if pf else ""
                lst.append((ref, pin, func))
                self.pins.setdefault(ref, {})[pin] = short
                if func:
                    self.funcs.setdefault(ref, {})[func] = short
            self.nets[short] = lst
        self._override, self._removed, self._shorted = {}, set(), set()

    # ------------------------------------------------------------------ queries
    def value(self, ref: str) -> float:
        return parse_value(self._override.get(ref, self.comps[ref]["value"]))

    def tol(self, ref: str) -> float:
        return parse_tol(self.comps[ref]["value"], ref[0])

    def mpn(self, ref: str) -> str:
        return self.comps[ref]["fields"].get("MPN", "")

    def node(self, net: str) -> str:
        if net not in self.nets and net not in ("GND", "0"):
            raise KeyError(f"net {net!r} is not in the {self.board} netlist")
        return node_name(net)

    def pin(self, ref: str, pin_or_func: str) -> str:
        """SPICE node on a part's pin, by pin number or pin name (pinfunction)."""
        if pin_or_func in self.pins.get(ref, {}):
            return node_name(self.pins[ref][pin_or_func])
        if pin_or_func in self.funcs.get(ref, {}):
            return node_name(self.funcs[ref][pin_or_func])
        raise KeyError(f"{ref} has no pin {pin_or_func!r} (pins {self.pins.get(ref)}, funcs {self.funcs.get(ref)})")

    def on_net(self, net: str, prefix: str = "") -> list:
        return sorted({r for r, _, _ in self.nets.get(net, []) if r.startswith(prefix)}, key=_refkey)

    def find(self, mpn_part: str) -> list:
        return sorted((r for r, c in self.comps.items() if mpn_part.upper() in self.mpn(r).upper()), key=_refkey)

    def fitted(self, ref: str) -> bool:
        return not self.comps[ref]["dnp"] and ref not in self._removed

    # ------------------------------------------------------------------ fault injection
    def override(self, ref: str, value: str):
        self._override[ref] = value
        return self

    def remove(self, ref: str):
        self._removed.add(ref)
        return self

    def fit(self, ref: str, value: str | None = None):
        """Fit a DNP part (e.g. the LED level-shifter option)."""
        self.comps[ref]["dnp"] = False
        if value:
            self._override[ref] = value
        return self

    def short(self, ref: str):
        self._shorted.add(ref)
        return self

    def reset(self):
        self._override, self._removed, self._shorted = {}, set(), set()
        return self

    # ------------------------------------------------------------------ deck lines
    def passives(self, nets=None, refs=None, exclude=(), scale=None, esr=None, include_dnp=False) -> list:
        """SPICE lines for every fitted R/C/L whose pins all sit on `nets` (or that is listed in `refs`).

        scale: {ref: multiplier} (Monte Carlo / corners); esr: {ref or 'C': ohms} adds a series R to capacitors.
        """
        nets = set(nets or ())
        out = []
        for ref in sorted(self.comps, key=_refkey):
            kind = ref[0]
            if kind not in "RCL" or not ref[1:2].isdigit() or ref in exclude:
                continue
            if self.comps[ref]["dnp"] and not include_dnp or ref in self._removed:
                continue
            pins = self.pins.get(ref, {})
            if len(pins) != 2:
                continue
            ns = [pins[p] for p in sorted(pins)]
            if refs is not None and ref not in refs:
                if not nets or not all(n in nets for n in ns):
                    continue
            elif refs is None and not all(n in nets for n in ns):
                continue
            a, b = (node_name(n) for n in ns)
            if ref in self._shorted:
                out.append(f"V{ref}_short {a} {b} 0")
                continue
            v = self.value(ref) * (scale or {}).get(ref, 1.0)
            if kind == "R":
                out.append(f"R{ref} {a} {b} {max(v, 1e-6):.6g}")
            elif kind == "C":
                r_esr = (esr or {}).get(ref, (esr or {}).get("C"))
                if r_esr:
                    mid = f"{a}_{ref.lower()}_esr"
                    out.append(f"R{ref}_esr {a} {mid} {r_esr:.6g}")
                    a = mid
                out.append(f"C{ref} {a} {b} {v:.6g}")
            else:
                out.append(f"L{ref} {a} {b} {v:.6g}")
        return out

    def monte_carlo(self, refs, n: int, seed: int = 1):
        """n tolerance draws {ref: multiplier}, uniform within each part's tolerance (worst-case-ish)."""
        rng = random.Random(seed)
        for _ in range(n):
            yield {r: 1.0 + rng.uniform(-self.tol(r), self.tol(r)) for r in refs}

    def extremes(self, refs):
        """All 2^n tolerance corners for a few parts (keep n small)."""
        refs = list(refs)
        for signs in itertools.product((-1, 1), repeat=len(refs)):
            yield {r: 1.0 + s * self.tol(r) for r, s in zip(refs, signs)}


def _refkey(ref):
    m = re.match(r"([A-Za-z#]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


class Deck:
    def __init__(self, title: str):
        self.title = title
        self.lines = []
        self.analyses = []
        self.measures = []
        self.control = []
        self.options = ["option noacct", "option reltol=1e-4"]
        self.waves = []

    def __iadd__(self, other):
        if isinstance(other, str):
            self.lines.append(other)
        else:
            self.lines.extend(other)
        return self

    def include(self, lib: str):
        path = lib if os.path.isabs(lib) else os.path.join(MODELS, lib)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.lines.insert(0, f".include {path}")
        return self

    def param(self, **kw):
        for k, v in kw.items():
            self.lines.append(f".param {k}={v}")
        return self

    def tran(self, step, stop, start=0, extra=""):
        self.analyses.append(f"tran {step} {stop} {start} {extra}".strip())
        return self

    def dc(self, src, start, stop, step):
        self.analyses.append(f"dc {src} {start} {stop} {step}")
        return self

    def op(self):
        self.analyses.append("op")
        return self

    def ac(self, kind, n, f0, f1):
        self.analyses.append(f"ac {kind} {n} {f0} {f1}")
        return self

    def meas(self, spec: str):
        """'tran name WHEN/FIND/MAX/MIN/AVG ...' (ngspice .meas syntax without the leading dot)."""
        self.measures.append(spec)
        return self

    def print_op(self, *exprs):
        """For .op: values printed as name = value (use ngspice expressions such as v(n_x) or i(vsrc))."""
        for i, e in enumerate(exprs):
            self.control.append(f"let _p{i} = {e}")
            self.control.append(f'echo "op_{i} = $&_p{i}"')
        return self

    def wave(self, *vectors):
        """Return these vectors (from the last analysis) as numpy arrays in the result under 'waves'."""
        self.waves.extend(vectors)
        return self

    def text(self) -> str:
        out = [f"* {self.title}"] + self.lines
        out += ["." + o for o in self.options]
        out += [".control", "set filetype=ascii", "set wr_singlescale", "set wr_vecnames"]
        for a in self.analyses:
            out.append(a)
        for m in self.measures:
            out.append("meas " + m)
        out += self.control
        if self.waves:
            out.append("wrdata __WAVES__ " + " ".join(self.waves))
        out += ["quit", ".endc", ".end"]
        return "\n".join(out) + "\n"

    def run(self, timeout: int = 300, keep: str | None = None) -> dict:
        if NGSPICE is None:
            raise RuntimeError("ngspice not found (apt install ngspice)")
        work = tempfile.mkdtemp(prefix="spice_")
        try:
            deck = os.path.join(work, "deck.cir")
            wav = os.path.join(work, "waves.txt")
            txt = self.text().replace("__WAVES__", wav)
            with open(deck, "w") as f:
                f.write(txt)
            if keep:
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copyfile(deck, keep)
            r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, timeout=timeout, cwd=work)
            log = r.stdout + r.stderr
            res = {"_log": log}
            for line in log.splitlines():
                m = re.match(r"^\s*([A-Za-z_][\w]*)\s*=\s*([-+0-9.eE]+)", line)
                if m:
                    try:
                        res[m.group(1).lower()] = float(m.group(2))
                    except ValueError:
                        pass
            fails = [ln for ln in log.splitlines() if re.search(r"(?i)\berror\b|failed|singular|timestep too small", ln)
                     and "measure" not in ln.lower()]
            res["_errors"] = fails
            if self.waves and os.path.exists(wav):
                import numpy as np
                with open(wav) as f:
                    head = f.readline().split()
                data = np.loadtxt(wav, skiprows=1, ndmin=2)
                res["waves"] = {h: data[:, i] for i, h in enumerate(head)}
            for m in self.measures:
                name = m.split()[1].lower()
                if name not in res:
                    res.setdefault("_missing", []).append(name)
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)


def eng(x: float, unit: str = "") -> str:
    if x == 0 or not math.isfinite(x):
        return f"{x}{unit}"
    e = int(math.floor(math.log10(abs(x)) / 3) * 3)
    e = max(-15, min(9, e))
    pre = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}[e]
    return f"{x / 10 ** e:.3g} {pre}{unit}"
