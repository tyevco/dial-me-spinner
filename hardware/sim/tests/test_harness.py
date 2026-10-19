"""Harness self-test: value parsing, netlist extraction and an RC step against the closed form."""

import math

import pytest

import spicelib


@pytest.mark.parametrize("s,v", [("4.7u/25V", 4.7e-6), ("499k 0.5%", 499e3), ("4R7", 4.7), ("220", 220.0),
                                 ("0", 0.0), ("12p C0G", 12e-12), ("51R 1/4W", 51.0), ("4.7u/25V Ta", 4.7e-6),
                                 ("10k B3435", 10e3), ("2.2M", 2.2e6), ("4k7", 4700.0)])
def test_parse_value(s, v):
    assert spicelib.parse_value(s) == pytest.approx(v)


def test_netlist_has_link_nets(main, base):
    for d in (main, base):
        for net in ("VSYS", "VBUS", "USB_DP", "USB_DM", "I2C_SCL", "I2C_SDA", "CHG_INT_N", "BTN_N"):
            assert net in d.nets, (d.board, net)


def test_rc_step_matches_closed_form(check):
    deck = spicelib.Deck("RC step")
    deck += ["V1 in 0 PULSE(0 1 0 1n 1n 1 2)", "R1 in out 1k", "C1 out 0 1u"]
    deck.tran("1u", "5m")
    deck.meas("tran v1tau FIND v(out) AT=1m")
    res = deck.run()
    check("v(out) at t = RC", res["v1tau"], 1 - math.exp(-1) - 0.002, 1 - math.exp(-1) + 0.002, "V", "closed form")
