"""Sleep / ship-mode battery drain from the real netlists (DC operating point).

Both boards are merged at the link (VSYS, GND, I2C, CHG_INT_N, BTN_N, VBUS, USB) and every fitted R/C/L of both
netlists goes into one .op deck, so every resistive path from VBAT / VSYS / +3V3 to GND is found by the solver,
not by hand. Every IC is replaced by its sleep-state model (hardware/sim/models/sleep_current__*.lib, each citing
its datasheet). The nRF52840 pin states are read from the sleep column of docs/firmware.md §1.3, and the limits
from docs/architecture.md §8 (sleep budget, ship mode, battery-life claims), SPEC.md and the datasheets.

Each run measures the battery current and the current every element returns to GND; the latter sum must match
the former (KCL closure), and it is what the per-subsystem breakdown and the "top contributors" list come from.

Corners: VBAT 3.0 / 3.7 / 4.2 V; -10 / 25 / 60 C (nRF52840 leakage, B5819W leakage, NTC, diode junctions move);
typical vs datasheet-maximum IC currents; all 2^5 tolerance extremes of the resistors that carry sleep current.
"""

from __future__ import annotations

import math
import os
import re

import pytest

import spicelib

ROOT = os.path.dirname(spicelib.HW)
ARCH_MD = os.path.join(ROOT, "docs", "architecture.md")
FW_MD = os.path.join(ROOT, "docs", "firmware.md")

LIBS = ["rt9080", "tps22917", "tps61040", "b5819w", "ssd1351", "nrf52840", "bq25180", "drv8837", "drv5032",
        "tmag5273", "lis2dw12", "w25q128jv", "tpd4e05u06", "bss138dw"]

UA = 1e-6


# ======================================================================================= document parsing
def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def arch_sleep_budget() -> dict:
    """docs/architecture.md §8.2 sleep column -> {key: uA}, plus the OLED max claim and ship / battery numbers."""
    txt = open(ARCH_MD, encoding="utf-8").read()
    sec = _section(txt, "### 8.2 Per-subsystem currents", "### 8.3")
    keys = [("nRF52840", "nrf"), ("RT9080", "ldo"), ("VSYS_SENSE", "vsys_div"), ("BQ25180", "bq"), ("PCM", "pcm"),
            ("TMAG5273", "tmag"), ("LIS2DW12", "imu"), ("DRV5032", "hall"), ("DRV8837", "drv8837"),
            ("OLED", "oled"), ("W25Q128", "flash"), ("LED ring", "leds"), ("Piezo", "piezo"), ("Total", "total")]
    out = {}
    for line in sec.splitlines():
        if not line.startswith("| ") or line.startswith("| Subsystem") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for kw, key in keys:
            if kw in cells[0] and key not in out:
                m = re.search(r"([0-9]+(?:\.([0-9]+))?)", cells[1])
                out[key] = float(m.group(1))
                out.setdefault("_dec", {})[key] = len(m.group(2) or "")
                md = re.search(r"([0-9]+(?:\.([0-9]+))?)", cells[2])
                if md:
                    out[key + "_desk"] = float(md.group(1))
                    out["_dec"][key + "_desk"] = len(md.group(2) or "")
                if key == "oled":
                    mm = re.search(r"maximum\s+([0-9.]+)\s*[–-]\s*([0-9.]+)\s*µA", cells[-1])
                    out["oled_max"] = float(mm.group(2))
                break
    missing = {k for _, k in keys} - set(out)
    assert not missing, f"architecture.md §8.2 sleep rows not found: {missing}"
    m = re.search(r"\*\*Ship mode:\*\*.*?≈\s*\*\*([0-9.]+)\s*µA\*\*", sec, re.S)
    out["ship"] = float(m.group(1))
    s81 = _section(txt, "### 8.1 Assumptions", "### 8.2")
    out["cell_mAh"] = float(re.search(r"about\s+([0-9]+)\s*mAh nominal", s81).group(1))
    out["usable_mAh"] = float(re.search(r"\*\*([0-9]+)\s*mAh usable\*\*", s81).group(1))
    s83 = _section(txt, "### 8.3 Battery life", "**Levers")
    m = re.search(r"Desk, typical day:.*?([0-9]+) h asleep.*?\|\s*([0-9.]+)\s*mAh/day\s*\|.*?\(([0-9]+)[–-]([0-9]+) days\)",
                  s83)
    out["desk_sleep_h"], out["desk_mAh_day"], out["desk_days_min"] = float(m.group(1)), float(m.group(2)), float(m.group(3))
    out["desk_idle_h"] = float(re.search(r"Desk, typical day:.*?([0-9]+) h connected idle", s83).group(1))
    m = re.search(r"([0-9.]+)[–-]([0-9.]+)\s*%/month", s83)
    out["selfdis_pct"] = (float(m.group(1)), float(m.group(2)))
    return out


def _fw_rows():
    """docs/firmware.md §1.3 GPIO table -> [(doc pins, listed nets, sleep-config text)]."""
    txt = open(FW_MD, encoding="utf-8").read()
    sec = _section(txt, "### 1.3 GPIO configuration", "Rules the firmware has to respect")
    rows = []
    for line in sec.splitlines():
        if not re.match(r"\| P[01]\.[0-9]{2}", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        listed = re.sub(r"([A-Z_]+?)([0-9]+)[–-]([0-9]+)",
                        lambda mm: " ".join(f"{mm.group(1)}{k}" for k in range(int(mm.group(2)), int(mm.group(3)) + 1)),
                        cells[1])
        rows.append((re.findall(r"P[01]\.[0-9]{2}", cells[0]), re.findall(r"[A-Z][A-Z0-9_+]*", listed),
                     cells[-1].replace("*", "")))
    return txt, rows


def _u10_gpios_on(main, net) -> list:
    return sorted(f for f, n in main.funcs["U10"].items() if n == net and re.fullmatch(r"P[01]\.[0-9]{2}", f))


def fw_gpio_sleep_states(main, mismatches=None) -> dict:
    """nRF pin -> (net, state) from the 'Sleep config' column of docs/firmware.md §1.3.

    Keyed by NET (the firmware configures a function, wherever the netlist puts it), so a pin move in nets.py
    does not silently assign a state to the wrong net; doc-vs-netlist pin disagreements are appended to
    `mismatches` for test_gpio_sleep_states_from_firmware_doc (verifier change: was keyed by doc pin number)."""
    txt, rows = _fw_rows()
    states = {}
    for pins, nets, sleep in rows:
        s = sleep.lower()
        if "driven low" in s or "driven, low" in s or s.startswith("low"):
            st = "OUT_LOW"
        elif s.startswith("high"):
            st = "OUT_HIGH"
        elif any(k in s for k in ("disconnected", "sense", "input", "interrupt disabled", "analog", "same")):
            st = "HIGHZ"
        else:
            raise AssertionError(f"firmware.md §1.3: cannot classify sleep config {sleep!r}")
        for net in nets:
            for pin in _u10_gpios_on(main, net):
                states[pin] = (net, st)
                if pin not in pins and mismatches is not None:
                    mismatches.append(("pin", net, "/".join(pins), pin))
    # QSPI pins are set by the qspi_sleep pinctrl state (firmware.md §3.1 pinctrl): CSN keeps bias-pull-up.
    blk = re.search(r"qspi_sleep:\s*qspi_sleep\s*\{(.*?)\n\s*\};\s*\n", txt, re.S).group(1)
    csn = next(ln for ln in blk.splitlines() if "QSPI_CSN" in ln)
    for pin in ("P0.19", "P0.20", "P0.21", "P0.22", "P0.23"):
        states[pin] = (main.funcs["U10"][pin], "HIGHZ")
    states["P0.17"] = (main.funcs["U10"]["P0.17"], "PULLUP" if "bias-pull-up" in csn else "HIGHZ")
    return states


def fw_sense_wake_pins(main) -> dict:
    """nRF pin -> (net, 'low' | 'high') for every net whose firmware.md §1.3 sleep config is a SENSE wake source."""
    _, rows = _fw_rows()
    out = {}
    for pins, nets, sleep in rows:
        m = re.search(r"sense (low|high)", sleep.lower())
        if m:
            for net in nets:
                for pin in _u10_gpios_on(main, net):
                    out[pin] = (net, m.group(1))
    assert out, "firmware.md §1.3: no SENSE wake pins found"
    return out


# ======================================================================================= simulation
class SleepSim:
    """One DC operating point of both boards in SLEEP (System ON idle) or SHIP mode."""

    def __init__(self, main, base, vbat=3.7, temp=25.0, maxc=0, mode="sleep", scale=None, kgnd=0.0,
                 u20_en_net=None, tmag_tsleep=0.1, sw1_closed=False, pcm_ua=None, u21_qod_open=False):
        self.main, self.base = main, base
        self.vbat, self.temp, self.maxc, self.mode = vbat, temp, maxc, mode
        self.scale = scale or {}
        self.kgnd = kgnd
        self.u20_en_net = u20_en_net
        self.u21_qod_open = u21_qod_open     # what-if only: U21 QOD left unconnected (the pre-LSW-1 schematic)
        self.tmag_tsleep = tmag_tsleep
        self.sw1_closed = sw1_closed or "SW1" in base._shorted
        self.pcm_ua = arch_sleep_budget()["pcm"] if pcm_ua is None else pcm_ua
        self.res_to_gnd = {}     # element -> (node, ohms)
        self.res_all = {}        # element -> (n1, n2, ohms)
        self.ammeters = {}       # element -> (V source, sign) measuring its current into GND
        self.cat = {}            # element -> subsystem key

    # ------------------------------------------------------------------ deck
    def _passives(self, d, tag):
        lines = d.passives(nets=set(d.nets) | {"GND"}, scale=self.scale.get(tag))
        out = []
        for ln in lines:
            name, a, b, *val = ln.split()
            kind, rest = name[0], name[1:]
            new = f"{kind}{tag}_{rest}"
            out.append(" ".join([new, a, b, *val]))
            ref = rest.split("_")[0]
            if kind == "R":
                ohm = float(val[0])
                self.res_all[new] = (a, b, ohm)
                if "0" in (a, b):
                    self.res_to_gnd[new] = (b if a == "0" else a, ohm)
                    self.cat[new] = self._category(tag, ref)
            elif kind == "V" and "0" in (a, b):           # shorted passive to GND (fault injection)
                self.ammeters[new] = (new, 1 if b == "0" else -1)
                self.cat[new] = self._category(tag, ref)
        return out

    @staticmethod
    def _category(tag, ref):
        m = {"main": {"R2": "vsys_div", "R1": "vsys_div", "C5": "vsys_div",
                      "R20": "oled", "R21": "oled", "R22": "oled", "R25": "oled", "R26": "oled", "R27": "oled",
                      "R3": "leds", "R4": "leds", "R40": "leds", "R41": "leds", "R42": "leds", "R43": "leds",
                      "R70": "drv8837", "R10": "flash", "R57": "piezo", "R58": "piezo", "R59": "piezo"},
             "base": {"RT1": "bq", "R4": "button", "R3": "button", "R1": "usb", "R2": "usb"}}[tag]
        return m.get(ref, "other")

    def _ic(self, deck, name, cat, nodes, sub, params=""):
        """Instantiate an IC model with its GND port behind an ammeter ("__G__" marks a GND port that is not last)."""
        gnode = f"ng_{name.lower()}"
        nodes = [gnode if n == "__G__" else n for n in nodes] + ([] if "__G__" in nodes else [gnode])
        deck += f"X{name} {' '.join(nodes)} {sub} {params}".rstrip()
        deck += f"Vg_{name} {gnode} 0 0"
        self.ammeters[f"X{name}"] = (f"Vg_{name}", 1)
        self.cat[f"X{name}"] = cat

    def deck(self) -> spicelib.Deck:
        m, b = self.main, self.base
        T, MX = self.temp, self.maxc
        deck = spicelib.Deck(f"sleep current {self.mode} VBAT={self.vbat} T={T} maxc={MX}")
        for lib in LIBS:
            deck.include(f"sleep_current__{lib}.lib")
        deck.options += ["option rshunt=1e12", "option tnom=25", f"option temp={T}"]
        # battery: cell + protection PCM (outside the PCB: architecture.md §8.2 'Pack PCM' assumption) + ammeter
        deck += f"Vcell n_cell 0 DC {self.vbat}"
        deck += f"Vpack n_cell {b.node('VBAT')} 0"
        deck += f"Ipcm n_cell 0 DC {self.pcm_ua}u"
        # passives of both boards (same SPICE node names on the link nets merge the boards)
        deck += self._passives(m, "main")
        deck += self._passives(b, "base")
        # NTC RT1 (not emitted by passives(): ref 'RT'): R25 and B from its netlist value '10k B3435'
        if b.fitted("RT1"):
            r25 = b.value("RT1")
            beta = float(re.search(r"B\s*([0-9]+)", b.comps["RT1"]["value"]).group(1))
            r = r25 * math.exp(beta * (1 / (T + 273.15) - 1 / 298.15)) * self.scale.get("base", {}).get("RT1", 1.0)
            node = b.pin("RT1", "1")
            if "RT1" in b._shorted:
                deck += f"Vbase_RT1_short {node} 0 0"
                self.ammeters["Vbase_RT1_short"] = ("Vbase_RT1_short", 1)
                self.cat["Vbase_RT1_short"] = "bq"
            else:
                deck += f"Rbase_RT1 {node} 0 {r:.6g}"
                self.res_to_gnd["Rbase_RT1"] = (node, r)
                self.res_all["Rbase_RT1"] = (node, "0", r)
                self.cat["Rbase_RT1"] = "bq"
        # centre switch SW1 (open unless pressed / shorted by a fault)
        deck += f"Rbase_SW1 {b.pin('SW1', '1')} {b.pin('SW1', '2')} {0.05 if self.sw1_closed else 1e12}"
        p = m.pin
        # ---------------------------------------------------------------- base board ICs
        bq_nodes = [b.pin("U1", f) for f in ("IN", "SYS", "BAT", "TS/MR", "SCL", "SDA", "~{INT}")]
        bq_sub = "SC_BQ25180_SHIP" if self.mode == "ship" else "SC_BQ25180_BATT"
        self._ic(deck, "BQ_U1", "bq", bq_nodes, bq_sub, f"params: MAXC={MX}")
        self._ic(deck, "Q1A", "button", [b.pin("Q1", "6"), b.pin("Q1", "2")], "SC_BSS138", f"params: MAXC={MX}")
        self._ic(deck, "Q1B", "button", [b.pin("Q1", "3"), b.pin("Q1", "5")], "SC_BSS138", f"params: MAXC={MX}")
        # ---------------------------------------------------------------- main board ICs
        self._ic(deck, "U1", "ldo", [p("U1", "VIN"), p("U1", "EN"), "__G__", p("U1", "VOUT")], "SC_RT9080",
                 f"params: MAXC={MX} KGND={self.kgnd}")
        self._ic(deck, "U2", "leds", [p("U2", "VIN"), p("U2", "ON"), "__G__", p("U2", "VOUT"), p("U2", "QOD")],
                 "SC_TPS22917_OFF", f"params: MAXC={MX}")
        u21_qod = "n_u21_qod_open" if self.u21_qod_open else p("U21", "QOD")
        self._ic(deck, "U21", "oled", [p("U21", "VIN"), p("U21", "ON"), "__G__", p("U21", "VOUT"), u21_qod],
                 "SC_TPS22917_OFF", f"params: MAXC={MX}")
        en = m.node(self.u20_en_net) if self.u20_en_net else p("U20", "EN")
        self._ic(deck, "U20", "oled", [p("U20", "VIN"), en, p("U20", "SW"), p("U20", "FB")], "SC_TPS61040",
                 f"params: MAXC={MX}")
        deck += f"Vam_D21 {p('D21', 'K')} nd21_k 0"          # D21 reverse current (cathode -> anode) ammeter
        deck += f"XD21 {p('D21', 'A')} nd21_k SC_B5819W params: TEMP={T} MAXC={MX}"
        self._ic(deck, "J20", "oled", [p("J20", "Pin_27"), p("J20", "Pin_4"), p("J20", "Pin_2")], "SC_SSD1351_SLEEP",
                 f"params: MAXC={MX}")
        vdd = p("U10", "VDD")
        self._ic(deck, "U10", "nrf", [vdd], "SC_NRF52840_SYSON", f"params: TEMP={T} MAXC={MX}")
        sub = {"OUT_LOW": "SC_NRF_GPIO_OUT_LOW", "OUT_HIGH": "SC_NRF_GPIO_OUT_HIGH", "PULLUP": "SC_NRF_GPIO_PULLUP",
               "PULLDOWN": "SC_NRF_GPIO_PULLDOWN"}
        for pin, (net, st) in sorted(fw_gpio_sleep_states(m).items()):
            if st in sub:
                deck += f"XGPIO_{pin.replace('.', '_')} {m.node(net)} {vdd} ng_u10 {sub[st]}"
        self._ic(deck, "U11", "flash", [p("U11", "VCC"), p("U11", "~{CS}")], "SC_W25Q128JV_PD", f"params: MAXC={MX}")
        self._ic(deck, "U30", "tmag", [p("U30", "VCC"), p("U30", "SCL"), p("U30", "SDA"), p("U30", "INT")],
                 "SC_TMAG5273_WS", f"params: TSLEEP={self.tmag_tsleep} NCH=2 MAXC={MX}")
        self._ic(deck, "U32", "tmag", [p("U32", "D1+"), p("U32", "D1-"), p("U32", "D2+")], "SC_TPD4E05U06",
                 f"params: MAXC={MX}")
        self._ic(deck, "U31", "imu", [p("U31", f) for f in ("VDD", "VDD_IO", "SCL/SPC", "SDA/SDI/SDO", "INT1", "INT2")],
                 "SC_LIS2DW12_LP1", f"params: MAXC={MX}")
        for u in ("U40", "U41"):
            self._ic(deck, u, "drv8837", [p(u, f) for f in ("VM", "VCC", "IN1", "IN2", "nSLEEP", "OUT1", "OUT2")],
                     "SC_DRV8837_SLEEP", f"params: MAXC={MX}")
        self._ic(deck, "U42", "hall", [p("U42", "VCC"), p("U42", "OUT")], "SC_DRV5032FA", f"params: MAXC={MX}")
        return deck

    # ------------------------------------------------------------------ run
    WATCH = ["VSYS", "+3V3", "VBAT", "OLED_VIN", "OLED_BST_SW", "+13V_OLED", "OLED_BST_FB", "OLED_VCC_EN",
             "LED_PWR_EN", "VLED", "MOT_NSLEEP", "VSYS_SENSE", "OLED_RES_N", "BTN_N", "CHG_TSMR", "CHG_INT_N",
             "I2C_SCL", "I2C_SDA", "TMAG_INT_N", "TMAG_SCL", "TMAG_SDA", "QSPI_CS"]

    def run(self) -> dict:
        deck = self.deck()
        probes = [("ibat", "-i(Vcell)"), ("iboard", "i(Vpack)")]
        nodes = set()
        for n1, n2, _ in self.res_all.values():
            nodes.update(n for n in (n1, n2) if n != "0")
        for k, net in enumerate(self.WATCH):
            nd = self.main.node(net) if net in self.main.nets else self.base.node(net)
            nodes.add(nd)
            # keep every watched node in the circuit even if a fault removes its last element (else ngspice
            # rejects the probe): 1e15 ohm, i.e. 1000x above the rshunt every node already has (verifier fix)
            deck += f"Rwatch_{k} {nd} 0 1e15"
        for nd in sorted(nodes):
            probes.append((f"v:{nd}", f"v({nd})"))
        for el, (src, sign) in self.ammeters.items():
            probes.append((f"i:{el}", f"{'-' if sign < 0 else ''}i({src})"))
        probes.append(("id21", "i(Vam_D21)"))
        deck.op()
        deck.print_op(*(e for _, e in probes))
        res = deck.run()
        assert not res["_errors"], "ngspice: " + " | ".join(res["_errors"][:5]) + "\n" + res["_log"][-3000:]
        vals = {}
        for i, (k, _) in enumerate(probes):
            assert f"op_{i}" in res, f"probe {k} missing\n{res['_log'][-3000:]}"
            vals[k] = res[f"op_{i}"]
        # ground-return currents per element
        contrib = {}
        for name, (node, ohm) in self.res_to_gnd.items():
            contrib[name] = vals[f"v:{node}"] / ohm
        for el in self.ammeters:
            contrib[el] = vals[f"i:{el}"]
        contrib["Ipcm"] = self.pcm_ua * UA
        self.cat["Ipcm"] = "pcm"
        by_cat = {}
        for el, i in contrib.items():
            by_cat[self.cat.get(el, "other")] = by_cat.get(self.cat.get(el, "other"), 0.0) + i
        out = dict(ibat=vals["ibat"], iboard=vals["iboard"], id21=vals["id21"], contrib=contrib, by_cat=by_cat,
                   v={k[2:]: v for k, v in vals.items() if k.startswith("v:")}, deck=deck)
        out["sum"] = sum(contrib.values())
        return out

    def v(self, res, net):
        d = self.main if net in self.main.nets else self.base
        return res["v"][d.node(net)]

    def r_current(self, res, element):
        """Current through a resistor element (n1 -> n2)."""
        n1, n2, ohm = self.res_all[element]
        v1 = 0.0 if n1 == "0" else res["v"].get(n1)
        v2 = 0.0 if n2 == "0" else res["v"].get(n2)
        return (v1 - v2) / ohm


def simulate(main, base, **kw):
    sim = SleepSim(main, base, **kw)
    return sim, sim.run()


def ua(x):
    return x / UA


# ======================================================================================= fixtures
@pytest.fixture(scope="module")
def budget():
    return arch_sleep_budget()


@pytest.fixture(scope="module")
def nominal():
    m, b = spicelib.Design("main"), spicelib.Design("base")
    return simulate(m, b)


# ======================================================================================= tests: setup / sanity
# Known drift between docs/firmware.md §1.3 and the netlist (verifier, 2026-10-19 04:55 netlist): nets.py moved
# CHG_INT_N from P0.09 to P1.03 and put an NFC antenna (NFC1/NFC2 -> J11, C16/C17) on P0.09/P0.10.
FW_DOC_DRIFT = {("pin", "CHG_INT_N"), ("uncovered", "NFC1"), ("uncovered", "NFC2")}
FW_DOC_ISSUE = ("DESIGN ISSUE (documentation): docs/firmware.md §1.3 predates nets.py moving CHG_INT_N from P0.09 "
                "to P1.03 and adding the NFC antenna on P0.09/P0.10 (NFC1/NFC2): the table still lists P1.03 as "
                "'not connected / reset default' (followed literally, the charger /INT wake is lost in sleep), has no "
                "row for NFC1/NFC2, and §1.2/§2.x still apply nfct-pins-as-gpios for 'P0.09 = CHG_INT_N'. Fix: update "
                "the §1.3 rows (P1.03 CHG_INT_N SENSE low; P0.09/P0.10 NFC antenna), the UICR/DTS snippets and the "
                "bring-up table.")


def test_gpio_sleep_states_from_firmware_doc(main, check):
    """The firmware sleep pin table covers every connected nRF GPIO, and its pin numbers match the netlist.
    Only the exact known drift above is tolerated as an expected failure; any other mismatch fails."""
    mism = []
    st = fw_gpio_sleep_states(main, mism)
    gpios = {f: n for f, n in main.funcs["U10"].items() if re.fullmatch(r"P[01]\.[0-9]{2}", f)}
    skip = {"P0.00", "P0.01", "P0.18"}            # LFXO crystal pins and nRESET (no sleep-config row)
    uncovered = sorted(f for f, n in gpios.items() if f not in st and f not in skip and not n.startswith("unconnected"))
    issues = {("pin", m[1]) for m in mism} | {("uncovered", gpios[f]) for f in uncovered}
    failed = []
    for name, val, src in (
            ("connected nRF GPIOs without a firmware.md §1.3 sleep state", len(uncovered),
             f"docs/firmware.md §1.3 GPIO configuration vs netlist U10 {[(f, gpios[f]) for f in uncovered]}"),
            ("firmware.md §1.3 pin numbers that disagree with the netlist", len(mism),
             f"docs/firmware.md §1.3 vs hardware/design/nets.py {mism}")):
        try:
            check(name, val, hi=0, unit="pins", source=src)
        except AssertionError as e:
            failed.append(e)
    assert st["P1.01"][1] == "OUT_HIGH" and st["P1.02"][1] == "OUT_LOW" and st["P1.04"][1] == "OUT_LOW"
    if failed:
        if issues <= FW_DOC_DRIFT:
            pytest.xfail(FW_DOC_ISSUE)
        raise failed[0]


def test_sleep_operating_point_is_consistent(nominal, main, check):
    """KCL closure (ground returns = battery current) and the sleep preconditions the IC models rely on."""
    sim, r = nominal
    check("KCL: sum of ground returns vs battery current", abs(r["sum"] - r["ibat"]) / r["ibat"], hi=0.01,
          source="harness self-check (Kirchhoff)")
    check("+3V3 at VBAT 3.7 V", sim.v(r, "+3V3"), lo=3.3 * 0.98, hi=3.3 * 1.02, unit="V",
          source="RT9080 DS9080-09 EC table VOUT accuracy ±2 %")
    check("LED_PWR_EN (U2 ON) in sleep", sim.v(r, "LED_PWR_EN"), hi=0.35, unit="V",
          source="TPS22917 SLVSDW8B §7.3 Recommended Operating Conditions VIL(ON) 0.35 V max")
    check("OLED_VCC_EN (U21 ON) in sleep", sim.v(r, "OLED_VCC_EN"), hi=0.35, unit="V",
          source="TPS22917 SLVSDW8B §7.3 Recommended Operating Conditions VIL(ON) 0.35 V max")
    check("MOT_NSLEEP in sleep", sim.v(r, "MOT_NSLEEP"), hi=0.25 * sim.v(r, "+3V3"), unit="V",
          source="DRV8837 SLVSBA4F §6.5 VIL 0.25 x VCC min")
    check("VLED held off by U2 QOD", sim.v(r, "VLED"), hi=0.1, unit="V",
          source="SPEC §5.4 / architecture §7: LEDs unpowered in sleep (WS2812C not modelled above 0 V)")


# ======================================================================================= tests: budget
_BUDGET_KEYS = ("nrf", "ldo", "vsys_div", "bq", "pcm", "tmag", "imu", "hall", "drv8837", "oled", "flash", "leds",
                "piezo")


def _budget_total(budget):
    return sum(budget[k] for k in _BUDGET_KEYS)


def _record_breakdown(check, r, budget, tag):
    for key in sorted(r["by_cat"], key=lambda k: -r["by_cat"][k]):
        if abs(r["by_cat"][key]) < 0.05 * UA:
            continue
        lim = budget.get(key)
        check(f"[{tag}] {key}: sim vs architecture §8.2 line {lim if lim is not None else '-'} µA",
              ua(r["by_cat"][key]), unit="µA", source="informational breakdown (ground returns by subsystem)")


def test_sleep_breakdown_and_top_contributors(nominal, budget, check):
    """Per-subsystem breakdown at VBAT 3.7 V / 25 C / typical, and the top contributors (informational)."""
    sim, r = nominal
    _record_breakdown(check, r, budget, "nominal")
    top = sorted(r["contrib"].items(), key=lambda kv: -kv[1])[:8]
    for rank, (el, i) in enumerate(top, 1):
        check(f"top {rank}: {el} ({sim.cat.get(el, 'other')})", ua(i), unit="µA",
              source="informational (ground return per element)")
    print("\nSleep contributors (VBAT 3.7 V, 25 C, typ):")
    for el, i in top:
        print(f"  {el:16s} {sim.cat.get(el, 'other'):9s} {ua(i):7.3f} µA")
    print(f"  total battery current {ua(r['ibat']):.2f} µA vs budget {_budget_total(budget):.2f} µA")
    assert top[0][1] > 0


D21_ISSUE = ("DESIGN ISSUE (sleep budget; remains after the SLP-1/LSW-1 fix): the sleep total is 36.0 / 37.4 / "
             "37.5 uA at VBAT 3.0 / 3.7 / 4.2 V (typ, 25 C), above the architecture.md 8.2 sum of 32.41 uA. The "
             "panel's VCI->VCC ESD path holds +13V_OLED at about 2.7 V. U21 QOD, now tied to OLED_VIN, holds "
             "OLED_VIN at about 0 V, so the B5819W rectifier D21 sits at VR about 2.7 V. Its reverse leakage (CJ typ "
             "curve: 5.4 uA at 25 C, 30 uA at 60 C) flows all the time: +3V3 -> panel ESD -> D21 -> L -> U21 QOD -> "
             "GND. The boost itself is off (test_boost_is_really_off_in_sleep). Before the fix, OLED_VIN floated "
             "to the U20 UVLO (D21 VR about 1.2 V, 4.95 uA) and U20 burned that leakage while hiccuping (total "
             "36.9 uA). The 8.2 OLED line (12 uA: ICI, divider, RES# pull-down) "
             "does not include it; the sim gives 17.6 uA. Fix: either budget it in architecture 8.2 (OLED about "
             "17.6 uA, 60 C about 42 uA), or remove the leak in hardware: a low-IR rectifier, or U20 EN on its own "
             "GPIO with U21 QOD open (32.18 uA, test_boost_fix_whatif_en_held_low).")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=D21_ISSUE)
@pytest.mark.parametrize("vbat", [3.0, 3.7, 4.2])
def test_sleep_total_within_budget_vs_vbat(main, base, budget, vbat, check):
    """Total battery drain in SLEEP (typ, 25 C) against the itemised architecture.md §8.2 sleep budget."""
    sim, r = simulate(main, base, vbat=vbat)
    check(f"sleep battery current at VBAT {vbat} V (typ, 25 C)", ua(r["ibat"]), hi=_budget_total(budget), unit="µA",
          source="docs/architecture.md §8.2 sleep column (sum of lines)")


@pytest.mark.parametrize("temp", [-10.0, 25.0, 60.0])
def test_sleep_temperature_sweep(main, base, budget, temp, check):
    """Sleep drain at -10 / 25 / 60 C (typ, informational): nRF52840 leakage (PS Fig. 10), B5819W leakage,
    junction voltages and the NTC move; the 25 C budget has no temperature qualification, so no limit here."""
    sim, r = simulate(main, base, temp=temp)
    _record_breakdown(check, r, budget, f"{temp:+.0f} C")
    check(f"sleep battery current at {temp:+.0f} C (typ, VBAT 3.7 V; 25 C budget {_budget_total(budget):.2f} µA)",
          ua(r["ibat"]), unit="µA", source="informational")
    check(f"D21 reverse current at {temp:+.0f} C", ua(r["id21"]), unit="µA", source="informational")


@pytest.mark.parametrize("temp", [-10.0, 25.0, 60.0])
def test_boost_is_really_off_in_sleep(main, base, temp, check):
    """Guards fix SLP-1/LSW-1 (U21 QOD tied to OLED_VIN). With OLED_VCC_EN low, the boost must be in shutdown:
    U20 may draw only ISD + EN leakage (both max, 2.0 uA). QOD now holds OLED_VIN at 0.1 / 0.8 / 4.5 mV, and U20
    draws 0.100 / 0.101 / 0.105 uA at -10 / 25 / 60 C, so the margin is about 1.9 uA. With QOD open it drew 4.96 uA
    at 25 C and 27.3 uA at 60 C (UVLO hiccup)."""
    sim, r = simulate(main, base, temp=temp)
    check(f"OLED_VIN in sleep at {temp:+.0f} C", sim.v(r, "OLED_VIN"), unit="V", source="informational")
    check(f"U20 TPS61040 current in sleep at {temp:+.0f} C", ua(r["contrib"]["XU20"]), hi=1.0 + 1.0, unit="µA",
          source="TPS61040 SLVS413L §5.5 ISD 1 µA max + II 1 µA max; architecture §6.3 'boost input draws 0 µA'")


@pytest.mark.parametrize("temp", [-10.0, 25.0, 60.0])
def test_boost_enable_pin_in_shutdown_in_sleep(main, base, temp, check):
    """Guards fix SLP-1/LSW-1 (U21 QOD tied to OLED_VIN). This is the state check behind the current check above
    (verifier addition): TPS61040 shutdown needs EN <= VIL 0.4 V. EN = OLED_VIN is held at 0.1 / 0.8 / 4.5 mV at
    -10 / 25 / 60 C, a margin of at least 0.395 V. With QOD open it was 1.46-1.53 V. The current check alone passed
    at -10 C even though the boost was enabled there too (D21 leaks less when cold)."""
    sim, r = simulate(main, base, temp=temp)
    en = main.pin("U20", "EN")
    check(f"U20 EN in sleep at {temp:+.0f} C", 0.0 if en == "0" else r["v"][en], hi=0.4, unit="V",
          source="TPS61040 SLVS413L §5.5 VIL 0.4 V max (shutdown, ISD condition EN = GND); architecture §6.3 boost off")


def test_boost_fix_whatif_en_held_low(main, base, budget, check):
    """What-if (not the schematic): the EN-low alternative to the SLP-1 fix. U21 QOD is left open, as before the
    LSW-1 change, and U20 EN is held low (own GPIO + pull-down, SLP-1/SLP-V2 proposal) instead of tied to OLED_VIN.

    Re-targeted after the schematic fixed SLP-1 differently (U21 QOD tied to OLED_VIN). On that circuit EN low
    changes nothing: QOD already holds EN = OLED_VIN at about 0 V, and the totals are identical (37.37 uA at 25 C
    either way). The original deck had therefore become a copy of the real-design total, and it failed that
    total's budget. This deck keeps the alternative it was written for. OLED_VIN floats up to +13V_OLED, D21 sees
    VR of about 0 V, and its reverse leakage falls from 5.4 uA (QOD fix) to 0.19 uA. The result, 32.18 uA, is the
    same as on the pre-fix netlist. The test (a) records that this alternative meets the architecture 8.2 budget
    (32.41 uA), which the built fix misses by 5.0 uA (37.37 uA, 5.19 uA above this alternative), and (b) keeps the
    SLP-V3 role. It is the regression guard on every
    other sleep contributor while the real-design total (test_sleep_total_within_budget_vs_vbat) is xfailed for
    the D21 leak."""
    for temp in (-10.0, 25.0, 60.0):
        sim, r = simulate(main, base, temp=temp, u20_en_net="GND", u21_qod_open=True)
        check(f"[what-if EN low, QOD open] U20 current at {temp:+.0f} C", ua(r["contrib"]["XU20"]), hi=2.0,
              unit="µA", source="TPS61040 SLVS413L §5.5 ISD 1 µA max + II 1 µA max")
        check(f"[what-if EN low, QOD open] sleep battery current at {temp:+.0f} C", ua(r["ibat"]), unit="µA",
              source="informational")
    sim, r = simulate(main, base, u20_en_net="GND", u21_qod_open=True, maxc=1)
    check("[what-if EN low, QOD open] OLED + boost sleep current, datasheet max, 25 C", ua(r["by_cat"]["oled"]),
          unit="µA", source="informational (architecture §8.2 claims 35–40 µA max)")
    sim, r = simulate(main, base, u20_en_net="GND", u21_qod_open=True)
    sim0, r0 = simulate(main, base)
    check("[what-if EN low, QOD open] D21 reverse current (typ, 25 C)", ua(r["id21"]), unit="µA",
          source=f"informational (schematic, U21 QOD tied to OLED_VIN: {ua(r0['id21']):.2f} µA)")
    check("sleep current cost of the built SLP-1 fix (QOD tied) over the EN-low alternative (typ, 25 C)",
          ua(r0["ibat"] - r["ibat"]), unit="µA", source="informational (D21 reverse leakage sunk by U21 QOD)")
    check("[what-if EN low, QOD open] sleep battery current (typ, 25 C)", ua(r["ibat"]), hi=_budget_total(budget),
          unit="µA", source="docs/architecture.md §8.2 sleep column (sum of lines)")


OLED_MAX_ISSUE = ("DESIGN ISSUE: at datasheet maxima the OLED sleep current exceeds the architecture's '35-40 uA "
                  "maximum'. With the SLP-1/LSW-1 fix (U21 QOD tied to OLED_VIN) it is 45.4 uA at 25 C and 70.0 uA "
                  "at 60 C. The cause is the D21 back-feed (see D21_ISSUE): typical-curve reverse leakage of 5.4 / "
                  "29.9 uA, now sunk through U21 QOD (the diode has no low-VR max). 1.7 uA of the total is SSD1351 "
                  "ISLP_VCC, scaled linearly from its 16 V test point; without it the total is still 43.7 uA at "
                  "25 C. The excess therefore does not come from that scaling. The EN-low alternative with QOD open "
                  "gives 41.9 uA at 25 C.")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=OLED_MAX_ISSUE)
@pytest.mark.parametrize("temp", [25.0, 60.0])
def test_oled_sleep_within_architecture_max(main, base, budget, temp, check):
    """architecture.md §8.2 / §6.3: OLED sleep 'maximum 35-40 µA' -- datasheet-max IC currents."""
    sim, r = simulate(main, base, temp=temp, maxc=1)
    check(f"OLED + boost sleep current, datasheet max, {temp:+.0f} C", ua(r["by_cat"]["oled"]),
          hi=budget["oled_max"], unit="µA", source="docs/architecture.md §8.2 OLED row 'maximum 35–40 µA'")


def test_sleep_max_corner(main, base, budget, check):
    """All ICs at their datasheet maximum (where one exists), 25 C: informational total and breakdown."""
    sim, r = simulate(main, base, maxc=1)
    _record_breakdown(check, r, budget, "max")
    check("sleep battery current, datasheet-max corner, 25 C", ua(r["ibat"]), unit="µA",
          source="informational (no max budget in architecture.md)")


# ======================================================================================= tests: SPEC items
def test_vsys_sense_divider(nominal, budget, check):
    sim, r = nominal
    i = sim.r_current(r, "Rmain_R1")
    check("VSYS_SENSE divider current at VBAT 3.7 V", ua(i), hi=budget["vsys_div"], unit="µA",
          source="docs/architecture.md §8.2 'VSYS_SENSE divider' (3.7 V / 3.2 MΩ); SPEC §3 '~1.3 µA'")


def test_drv8837_pair_sleep_current(main, base, check):
    for mx in (0, 1):
        sim, r = simulate(main, base, maxc=mx)
        i = r["contrib"]["XU40"] + r["contrib"]["XU41"] + r["contrib"].get("Rmain_R70", 0.0)
        check(f"2x DRV8837 sleep current ({'max' if mx else 'typ'})", round(ua(i), 4), hi=0.24, unit="µA",
              source="SPEC §3 'DRV8837 ×2 ... sleep ≤ 0.24 µA' (SLVSBA4F IVMQ + IVCCQ)")


def test_drv5032_and_ldo_quiescent(nominal, check):
    sim, r = nominal
    check("DRV5032FA average supply current at +3V3", ua(r["contrib"]["XU42"]), hi=2.0, unit="µA",
          source="SPEC §5.6 'DRV5032FADBZR ... (≤ 2 µA avg)'")
    check("RT9080 ground current at the sleep load (IQ model)", round(ua(r["contrib"]["XU1"]), 4), hi=2.0, unit="µA",
          source="SPEC §3 'LDO ... Iq ≤ 2 µA'")


def test_tmag_wake_interval_corners(main, base, budget, check):
    """TMAG5273 W&S current at the firmware intervals: 100 ms (SLEEP), 10 ms (DESK_IDLE), 500 ms (low battery)."""
    for tsl, key, src in ((0.1, "tmag", "docs/architecture.md §8.2 TMAG5273 sleep line (100 ms, 'about 3 µA')"),
                          (0.01, "tmag_desk", "docs/architecture.md §8.2 TMAG5273 desk-idle line (10 ms)"),
                          (0.5, None, "informational: firmware.md §4.8 DEEP-LOWBAT 'about 1.5 µA'")):
        sim, r = simulate(main, base, tmag_tsleep=tsl)
        i = ua(r["contrib"]["XU30"])
        if key:
            check(f"TMAG5273 W&S average current at {tsl * 1e3:.0f} ms (at the budget's stated resolution)",
                  round(i, budget["_dec"][key]), hi=budget[key], unit="µA", source=src)
        else:
            check(f"TMAG5273 W&S average current at {tsl * 1e3:.0f} ms", i, unit="µA", source=src)


def test_ldo_light_load_ground_current_sensitivity(main, base, budget, check):
    """RT9080 IGND below 1 mA is not specified: chord from IQ to the 1 mA point of the DS9080-09 figure."""
    sim, r = simulate(main, base, kgnd=0.056)
    iload = ua(r["contrib"]["XU1"])
    check("RT9080 ground current with the 0-1 mA chord (KGND 0.056)", iload, unit="µA",
          source="informational: DS9080-09 'Ground Current vs. Load Current' (58 µA at 1 mA)")


# ======================================================================================= tests: tolerances
def test_resistor_tolerance_extremes(main, base, budget, check):
    """All 2^5 tolerance corners of the resistors that carry sleep current (R1, R2, R20, R26, R27)."""
    refs = ["R1", "R2", "R20", "R26", "R27"]
    totals, divs = [], []
    for sc in main.extremes(refs):
        sim, r = simulate(main, base, scale={"main": sc})
        totals.append(ua(r["ibat"]))
        divs.append(ua(sim.r_current(r, "Rmain_R1")))
    check("VSYS_SENSE divider current, worst tolerance corner (3.7 V)", max(divs), hi=budget["vsys_div"], unit="µA",
          source="docs/architecture.md §8.2 'VSYS_SENSE divider' line")
    check("sleep total, tolerance spread (max - min)", max(totals) - min(totals), unit="µA",
          source="informational (32 corners)")


# ======================================================================================= tests: ship mode
@pytest.mark.parametrize("vbat", [3.0, 3.7, 4.2])
def test_ship_mode_drain(main, base, budget, vbat, check):
    sim, r = simulate(main, base, vbat=vbat, mode="ship")
    check(f"ship-mode battery drain at VBAT {vbat} V (typ)", round(ua(r["ibat"]), 1), hi=budget["ship"], unit="µA",
          source="docs/architecture.md §8.2 'Ship mode ... ≈ 6.2 µA' (BQ25180 SLUSE99C IBAT_SHIP + PCM)")
    check(f"VSYS in ship mode at VBAT {vbat} V", sim.v(r, "VSYS"), hi=0.05, unit="V",
          source="BQ25180 SLUSE99C §8.3.4.1 Table 8-2: SYS pulled down in ship mode (main board unpowered)")


def test_ship_mode_max_vs_self_discharge(main, base, budget, check):
    """architecture §8.3: ship-mode life is 'limited by the cell's self-discharge' -- even at datasheet max."""
    sim, r = simulate(main, base, mode="ship", maxc=1)
    selfdis_ua = budget["selfdis_pct"][0] / 100 * budget["cell_mAh"] / (365.25 / 12 * 24) * 1e3
    check("ship-mode drain, datasheet max (BQ25180 4.5 µA)", ua(r["ibat"]), hi=selfdis_ua, unit="µA",
          source="docs/architecture.md §8.1/§8.3: 2 %/month self-discharge of the 1000 mAh cell")


# ======================================================================================= tests: battery-life claims
def test_desk_day_runtime_claim(nominal, budget, check):
    """architecture §8.3 'Desk, typical day ... ≈ 4 weeks (28-29 days)' recomputed with the simulated sleep floor."""
    sim, r = nominal
    # The simulated excess over the itemised floor (display off, +3V3 up) applies in the connected-idle hours
    # too: architecture §8.1 desk idle has the display and LEDs off, and its 57 µA column carries the same OLED,
    # LDO, divider, BQ and PCM lines as the sleep column (verifier fix: the sleep hours alone were adjusted).
    h = budget["desk_sleep_h"] + budget["desk_idle_h"]
    mah_day = budget["desk_mAh_day"] + h * (ua(r["ibat"]) - _budget_total(budget)) * 1e-3
    days = budget["usable_mAh"] / mah_day
    check("desk typical-day runtime with simulated sleep current", days, lo=budget["desk_days_min"], unit="days",
          source="docs/architecture.md §8.3 'Desk, typical day ... (28–29 days)'")
    lo, hi = budget["selfdis_pct"]
    sd = (lo + hi) / 2 / 100 * budget["cell_mAh"]
    months = budget["usable_mAh"] / (ua(r["ibat"]) * 1e-3 * 24 * 365.25 / 12 + sd)
    check("sleep-only time to cutoff (mid self-discharge)", months / 12, unit="years",
          source="informational: architecture §8.3 claims 'roughly 1.5 years'")


def test_wake_source_loads(main, base, check):
    """Button held during sleep (informational): R3/R4 on base, R56 pull-up through Q1B, TS/MR pulled low."""
    sim0, r0 = simulate(main, base)
    sim, r = simulate(main, base, sw1_closed=True)
    check("extra battery current while the dial is held down in sleep", ua(r["ibat"] - r0["ibat"]), unit="µA",
          source="informational (R56 100 kΩ + base R3/R4 path)")
    check("BTN_N while held", sim.v(r, "BTN_N"), hi=0.3 * sim.v(r, "+3V3"), unit="V",
          source="nRF52840 PS v1.1 §6.9.3.1 VIL 0.3 x VDD max")


def _wake_idle_checks(main, sim, r, check, tag=""):
    """Every SENSE wake input must idle at its inactive level, or the MCU never stays in System ON idle and the
    whole sleep figure is void (DETECT stays asserted). Returns {net: (V, ok)}."""
    vdd = sim.v(r, "+3V3")
    out = {}
    for pin, (net, pol) in sorted(fw_sense_wake_pins(main).items()):
        v = r["v"].get(main.node(net), 0.0)
        if pol == "low":     # wakes on low -> must idle >= VIH
            check(f"{tag}{net} ({pin}, SENSE low) idle level in sleep", v, lo=0.7 * vdd, unit="V",
                  source="nRF52840 PS v1.1 §6.9.3.1 VIH 0.7 x VDD min; firmware.md §1.3 sleep config")
            out[net] = (v, v >= 0.7 * vdd)
        else:                # wakes on high -> must idle <= VIL
            check(f"{tag}{net} ({pin}, SENSE high) idle level in sleep", v, hi=0.3 * vdd, unit="V",
                  source="nRF52840 PS v1.1 §6.9.3.1 VIL 0.3 x VDD max; firmware.md §1.3 sleep config")
            out[net] = (v, v <= 0.3 * vdd)
    return out


@pytest.mark.parametrize("maxc", [0, 1], ids=["typ", "max-leakage"])
def test_wake_inputs_idle_inactive(main, base, maxc, check):
    """Verifier addition: the sleep current is only valid if no wake source is asserted. Pull-ups (R52, R55, R56)
    against the datasheet-max pin leakage (TMAG IOZ, BQ25180 ILKG, BSS138 IDSS)."""
    sim, r = simulate(main, base, maxc=maxc)
    _wake_idle_checks(main, sim, r, check, f"[{'max' if maxc else 'typ'}] ")


# ======================================================================================= fault injection
@pytest.mark.fault
def test_fault_vsys_sense_bottom_resistor_wrong_value(main, base, budget, check):
    """BOM error: R2 fitted as 100 kΩ instead of 1 MΩ -> the divider check must fail."""
    main.override("R2", "100k")
    sim, r = simulate(main, base)
    i = ua(sim.r_current(r, "Rmain_R1"))
    check("FAULT R2=100k: divider current exceeds the budget line (detected)", i, lo=budget["vsys_div"], unit="µA",
          source="docs/architecture.md §8.2 'VSYS_SENSE divider' line")
    assert i > budget["vsys_div"]


@pytest.mark.fault
def test_fault_vsys_sense_cap_shorted(main, base, budget, check):
    """Assembly / footprint fault: C5 shorted (VSYS_SENSE to GND) -> the divider check must fail."""
    main.short("C5")
    sim, r = simulate(main, base)
    i = ua(sim.r_current(r, "Rmain_R1"))
    check("FAULT C5 short: divider current exceeds the budget line (detected)", i, lo=budget["vsys_div"], unit="µA",
          source="docs/architecture.md §8.2 'VSYS_SENSE divider' line")
    assert i > budget["vsys_div"]


@pytest.mark.fault
def test_fault_oled_res_pulldown_100k(main, base, budget, check):
    """Design error the display review caught: RES# pull-down R20 = 100 kΩ (33 µA while RES# is held high)."""
    main.override("R20", "100k")
    sim, r = simulate(main, base)
    i = ua(r["by_cat"]["oled"])
    check("FAULT R20=100k: OLED sleep current (typ) exceeds the architecture maximum (detected)", i,
          lo=budget["oled_max"], unit="µA", source="docs/architecture.md §8.2 OLED row 'maximum 35–40 µA'")
    assert i > budget["oled_max"]


@pytest.mark.fault
def test_fault_sw1_common_pair_swapped(main, base, budget, check):
    """Footprint error: SW1 pads wired to the same common pair (A-B) -> switch permanently closed in ship mode."""
    base.short("SW1")
    sim, r = simulate(main, base, mode="ship")
    i = ua(r["ibat"])
    check("FAULT SW1 always closed: ship-mode drain exceeds architecture §8.2 (detected)", round(i, 1),
          lo=budget["ship"] + 0.1, unit="µA", source="docs/architecture.md §8.2 'Ship mode ... ≈ 6.2 µA'")
    assert round(i, 1) > budget["ship"]


@pytest.mark.fault
@pytest.mark.parametrize("ref,net", [("R56", "BTN_N"), ("R52", "TMAG_INT_N"), ("R55", "CHG_INT_N")])
def test_fault_wake_pullup_left_off(main, base, ref, net, check):
    """Verifier addition (mutation run: these were NOT caught before): a wake-input pull-up left off leaves an
    open-drain / switch node floating on a SENSE-low pin -> spurious wake or a stuck DETECT, so the MCU never
    sleeps. The idle-level check must flag it (a floating node resolves to 0 V through rshunt in .op)."""
    main.remove(ref)
    sim, r = simulate(main, base)
    v = r["v"][main.node(net)]
    vih = 0.7 * sim.v(r, "+3V3")
    check(f"FAULT {ref} left off: {net} idles below VIH (detected)", v, hi=vih, unit="V",
          source="nRF52840 PS v1.1 §6.9.3.1 VIH 0.7 x VDD min")
    assert v < vih
