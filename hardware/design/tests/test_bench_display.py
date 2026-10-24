#!/usr/bin/env python3
"""The AMOLED bench shield's two pinouts, checked against sources the sheet did not write.

A wrong FPC pinout kills the board and possibly the panel, and the sheet module
derives its connector pins from one rule (connector pin = 32 - panel pin).  So the
committed netlist is held here against an independent transcription of Waveshare's
working J3 (ESP32-S3-Touch-AMOLED-1.75 schematic, same panel tail on an FH26-31S),
not against the rule itself.  The DK side is held to SPEC.md §4's low-frequency-only
list, so the two 32 MHz lines cannot drift onto a slow pin.

    python3 -m pytest hardware/design/tests -q

Reads the netlist only: needs no KiCad.
"""
import os
import sys

import pytest

HW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(HW, "tools"))
import sexpr  # noqa: E402
from sexpr import find, find_all  # noqa: E402

NET = os.path.join(HW, "kicad", "bench_display", "dial-me-spinner-bench_display.net")

#: Waveshare J3, read off the schematic image pin by pin.  "3V3" = their VCC3V3 rail.
WAVESHARE_J3 = {
    31: "GND", 30: "TP_INT", 29: "TP_RESET", 28: "TP_SDA", 27: "TP_SCL", 26: "3V3", 25: "GND",
    24: "3V3", 23: "3V3", 22: "3V3", 21: "3V3", 20: "GND", 19: "NC", 18: "LCD_RESET",
    17: "LCD_CS", 16: "QSPI_SIO0", 15: "QSPI_SI1", 14: "QSPI_SCL", 13: "QSPI_SI3", 12: "QSPI_SI2",
    11: "LCD_TE", 10: "GND", 9: "NC", 8: "NC", 7: "GND", 6: "NC", 5: "NC", 4: "GND", 3: "NC",
    2: "NC", 1: "GND",
}
#: Their signal names -> ours.  Their 3V3 pins are split into separate rails here on purpose.
SIGNALS = {
    "GND": "GND", "TP_INT": "TP_INT", "TP_RESET": "TP_RST_N", "TP_SDA": "TP_SDA", "TP_SCL": "TP_SCL",
    "LCD_RESET": "DISP_RES_N", "LCD_CS": "DISP_CS_N", "QSPI_SIO0": "DISP_SIO0", "QSPI_SI1": "DISP_SIO1",
    "QSPI_SCL": "DISP_SCK", "QSPI_SI3": "DISP_SIO3", "QSPI_SI2": "DISP_SIO2", "LCD_TE": "DISP_TE",
}
#: The rails behind Waveshare's 3V3 pins, by the Huaxin pin table (panel pin = 32 - connector pin).
RAILS = {26: "TP_VDD", 24: "IOVCC", 23: "VCI", 22: "DISP_VBAT", 21: "DISP_VCI_EN"}

#: Arduino_UNO_R3 symbol pin -> nRF52840-DK GPIO (Zephyr boards/nordic/nrf52840dk gpio-map).
DK_GPIO = {
    "15": "P1.01", "16": "P1.02", "17": "P1.03", "18": "P1.04", "19": "P1.05", "20": "P1.06",
    "21": "P1.07", "22": "P1.08", "23": "P1.10", "24": "P1.11", "25": "P1.12", "26": "P1.13",
    "27": "P1.14", "28": "P1.15", "9": "P0.03", "10": "P0.04", "11": "P0.28", "12": "P0.29",
    "13": "P0.30", "14": "P0.31", "31": "P0.26", "32": "P0.27",
}
#: SPEC.md §4.
LOW_FREQUENCY = {"P0.02", "P0.03", "P0.09", "P0.10", "P0.28", "P0.29", "P0.30", "P0.31",
                 *(f"P1.0{i}" for i in range(1, 8)), *(f"P1.{i}" for i in range(10, 16))}


def pin_nets(ref):
    n = sexpr.parse(open(NET, encoding="utf-8").read())
    out = {}
    for net in find_all(find(n, "nets"), "net"):
        name = str(find(net, "name")[1]).rsplit("/", 1)[-1]   # local labels carry their sheet path
        for nd in find_all(net, "node"):
            if str(find(nd, "ref")[1]) == ref:
                out[str(find(nd, "pin")[1])] = None if name.startswith("unconnected") else name
    return out


@pytest.mark.parametrize("pin", sorted(WAVESHARE_J3))
def test_fpc_pin_matches_waveshare(pin):
    net = pin_nets("J2").get(str(pin))
    theirs = WAVESHARE_J3[pin]
    if theirs == "NC":
        assert net is None, f"J2.{pin} is {net}; Waveshare leaves it open"
    elif theirs == "3V3":
        assert net == RAILS[pin], f"J2.{pin} is {net}; expected the {RAILS[pin]} rail"
    else:
        assert net == SIGNALS[theirs], f"J2.{pin} is {net}; Waveshare has {theirs}"


def test_fpc_shell_is_grounded():
    assert pin_nets("J2").get("MP") == "GND"


@pytest.mark.parametrize("net", ["DISP_SCK_DK", "DISP_SIO0_DK"])
def test_32mhz_lines_are_on_full_speed_pins(net):
    pins = [p for p, n in pin_nets("J1").items() if n == net]
    assert len(pins) == 1, f"{net} on J1 pins {pins}"
    gpio = DK_GPIO[pins[0]]
    assert gpio not in LOW_FREQUENCY, f"{net} is on {gpio}, a low-frequency-only pin (SPEC §4)"


def test_header_pins_are_each_used_once():
    """A4/SDA and A5/SCL share names in the symbol; a by-name assignment would short P0.30 to P0.26."""
    used = [n for n in pin_nets("J1").values() if n and n not in ("GND", "VDD_DK", "DK_3V3")]
    assert len(used) == len(set(used)), f"a header net appears twice: {sorted(used)}"
