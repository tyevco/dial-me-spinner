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
    res = deck.run(fallback=True)   # opt-in: retry with looser numerics on 'Timestep too small' or a hang

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

# Deck.run(): default timeout, and the opt-in numerical fallback (Deck.run(fallback=True)). The ladder is the one
# test_load_switches.run() uses: reltol 1e-3, then also Gear + rshunt 1e12, 90 s per attempt (normal decks finish in a
# few seconds), retried only on 'Timestep too small' or a hang.
DEFAULT_TIMEOUT = 300
FALLBACK_ATTEMPT_TIMEOUT = 90
NUMERIC_FALLBACKS = (("option reltol=1e-3",), ("option reltol=1e-3", "option method=gear", "option rshunt=1e12"))


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
        """Inline a model file. ngspice treats a node called 'gnd' as global ground even inside a .subckt, which
        would silently tie a subcircuit's ground PORT to node 0 whatever the caller connects it to. So in every
        subcircuit that has a 'gnd' port, that name is made local before the file goes into the deck."""
        path = lib if os.path.isabs(lib) else os.path.join(MODELS, lib)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.lines.insert(0, f"* ---- {os.path.basename(path)}\n" + localize_gnd_ports(open(path).read()))
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

    def run(self, timeout: int | None = None, keep: str | None = None, fallback: bool = False) -> dict:
        """Run the deck in ngspice batch mode and parse the measures / printed values / waves.

        timeout: seconds before subprocess.TimeoutExpired (default 300; with fallback, per attempt, default 90).
        fallback (opt-in, default off): numerical fallback for decks whose models can stall ngspice's step control at
            a switching instant. Only a 'Timestep too small' in the log or a hang (timeout) triggers a retry, first
            with reltol 1e-3, then with reltol 1e-3 + Gear integration + rshunt 1e12 (NUMERIC_FALLBACKS, the same
            ladder as test_load_switches.run()). Any other error, and anything the last attempt reports, is returned
            unchanged for the caller's checks (so a fallback never hides an error); a hang of every attempt raises the
            last TimeoutExpired. The result then carries '_fallback': the option lines added ([] = first attempt).
            self.options is left as it was.
        """
        if not fallback:
            return self._run_once(DEFAULT_TIMEOUT if timeout is None else timeout, keep)
        per_attempt = FALLBACK_ATTEMPT_TIMEOUT if timeout is None else timeout
        saved = list(self.options)
        res, hang = None, None
        try:
            for extra in ((),) + NUMERIC_FALLBACKS:
                keys = {_option_key(o) for o in extra}
                self.options = [o for o in saved if _option_key(o) not in keys] + list(extra)
                try:
                    res = self._run_once(per_attempt, keep)
                except subprocess.TimeoutExpired as exc:
                    res, hang = None, exc
                    continue
                res["_fallback"] = list(extra)
                if not any(re.search(r"(?i)timestep too small", e) for e in res["_errors"]):
                    break
        finally:
            self.options = saved
        if res is None:
            raise hang
        return res

    def _run_once(self, timeout: int, keep: str | None) -> dict:
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


def _option_key(line: str) -> str:
    """'option reltol=1e-4' -> 'reltol'; 'option noacct' -> 'noacct' (which option a Deck.options line sets)."""
    tok = line.split(None, 1)
    return (tok[1] if len(tok) > 1 else tok[0]).split("=")[0].strip().lower()


def localize_gnd_ports(text: str) -> str:
    """Rename a subcircuit's 'gnd' port (and its uses inside that subcircuit) to a local node name."""
    out, inside, rename = [], False, False
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith(".subckt"):
            head = re.split(r"\s+params:", line, maxsplit=1, flags=re.I)[0]
            inside, rename = True, bool(re.search(r"(?i)(?<![\w.])gnd(?![\w.])", " ".join(head.split()[2:])))
        if inside and rename and not low.startswith("*"):
            line = re.sub(r"(?i)(?<![\w.])gnd(?![\w.])", "gnd_port", line)
        if low.startswith(".ends"):
            inside, rename = False, False
        out.append(line)
    return "\n".join(out)


def eng(x: float, unit: str = "") -> str:
    if x == 0 or not math.isfinite(x):
        return f"{x}{unit}"
    e = int(math.floor(math.log10(abs(x)) / 3) * 3)
    e = max(-15, min(9, e))
    pre = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}[e]
    return f"{x / 10 ** e:.3g} {pre}{unit}"
