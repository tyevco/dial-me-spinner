"""Main board: nRF52840 module, 32.768 kHz crystal, QSPI flash, SWD debug, spare test pads. See SPEC.md §4, §5.2.

Pinouts verified against primary datasheets:
* MDBT50Q-U1MV2: Raytac "MDBT50Q-1MV2 / -P1MV2" spec Ver.K, §2.1 (top-view pin indication),
  §2.2 (solder-pad layout) and §2.5 (pin assignment table, pads 1-61). The KiCad symbol
  RF_Module:MDBT50Q-U1MV2 and footprint RF_Module:Raytac_MDBT50Q agree pad for pad; the sheet
  draws a by-port copy of that symbol (same numbers/names/types, see _mcu_symbol). The Raytac
  §8.3 "Reg0 DC/DC and LDO mode disabled" is the reference circuit followed here.
* W25Q128JVSIQ: Winbond W25Q128JV datasheet Rev F, Fig. 1a / §3.3 (SOIC-8 208 mil):
  1 /CS, 2 DO(IO1), 3 /WP(IO2), 4 GND, 5 DI(IO0), 6 CLK, 7 /HOLD(IO3), 8 VCC.
* SC-20S 9 pF (C97603): SII SC-20S standard specification (CL 9 pF, R1 <= 90 kOhm, DLmax 0.5 uW;
  pads 0.7 x 1.4 mm at 1.5 mm pitch, 0.8 mm gap; no copper under the part).
* TC2030-IDC-NL: Tag-Connect TC2030-CTX: 1 VCC, 2 SWDIO, 3 nRESET, 4 SWCLK, 5 GND, 6 SWO.
"""

import symlib
from nets import MCU_PINS

SHEET = ("mcu", "mcu.kicad_sch", "MCU, flash & debug")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

XTAL_FP = "Crystal_SII_SC-20S_2.0x1.2mm"
XTAL_SYM = "XTAL_SC-20S"

STOCK_MCU = "RF_Module:MDBT50Q-U1MV2"
MCU_SYM = "MDBT50Q-U1MV2_byport"
MCU_FP = "dial_spinner:Raytac_MDBT50Q_UFL"


def _mcu_symbol():
    """Box symbol for the module, cloned pin-for-pin from the stock KiCad symbol.

    Numbers, names and electrical types are copied from RF_Module:MDBT50Q-U1MV2 (checked against
    the Raytac pin table), only the pin sides change: the stock symbol puts VDD/VDDH/VBUS/DCCH
    2.54 mm apart on its top edge, where this generator's power-symbol texts overprint each other.
    Left: supply, USB, SWD, then P1.00-P1.15. Right: P0.00-P0.31. Bottom: GND (5 stacked pads).
    """
    stock = symlib.get(STOCK_MCU)
    by_name = {}
    for p in stock.pins:
        by_name.setdefault(p.name, []).append(p)

    def port_key(name):
        port, idx = name[1:].split(".")
        return int(port), int(idx)

    gpio = sorted((n for n in by_name if n.startswith("P") and "." in n), key=port_key)
    sides = (
        [(n, "L") for n in ["VDD", "VDDH", "VBUS", "DCCH", "D+", "D-", "SWDIO", "SWDCLK"]]
        + [(n, "L") for n in gpio if n.startswith("P1.")]
        + [(n, "R") for n in gpio if n.startswith("P0.")]
        + [("GND", "B")]
    )
    pins = []
    for name, side in sides:
        for p in sorted(by_name[name], key=lambda q: (q.hidden, int(q.number))):
            pins.append((int(p.number), p.name, "passive" if p.hidden else p.etype, side))
    assert sorted(n for n, *_ in pins) == sorted(int(p.number) for p in stock.pins) == list(range(1, 62))
    return dict(name=MCU_SYM, ref="U", footprint=MCU_FP, datasheet=stock.prop("Datasheet"),
                description="Raytac MDBT50Q-U1MV2 nRF52840 module, u.FL (pins = KiCad " + STOCK_MCU + ")",
                pins=pins)


SYMBOLS = [
    _mcu_symbol(),
    # Two-pin crystal drawn with its pins top/bottom: the generator lays such parts horizontally with
    # the reference above and the value below (like Device:C). Device:Crystal has horizontal pins, which
    # makes its reference collide with the XL2 label. Pin numbers = pads of the custom footprint below.
    dict(
        name=XTAL_SYM,
        ref="Y",
        footprint="dial_spinner:" + XTAL_FP,
        datasheet="https://www.lcsc.com/datasheet/C97603.pdf",
        description="SII SC-20S 32.768 kHz tuning-fork crystal, 2.05x1.2 mm, non-polarised",
        pins=[
            (1, "~", "passive", "T"),
            (2, "~", "passive", "B"),
        ],
    ),
]


NFC_FP = "NFC_Coil_Pads_1x02_P2.0mm"


def footprints(fpgen, lib_dir):
    # SII SC-20S recommended soldering pattern (standard spec, C97603): two 0.7 x 1.4 mm pads, 0.8 mm gap
    # (centres at +/-0.75 mm). KiCad's generic 2012 crystal footprint uses smaller
    # 0.6 x 1.1 mm pads, so the vendor pattern is used instead.
    fp = fpgen.Footprint(XTAL_FP,
                         "SII SC-20S 32.768 kHz crystal, 2.05x1.2 mm, vendor recommended land pattern "
                         "(no copper pattern under the part)",
                         "crystal 32.768kHz SC-20S")
    fp.smd("1", -0.75, 0, 0.7, 1.4)
    fp.smd("2", 0.75, 0, 0.7, 1.4)
    fp.courtyard_rect(-1.35, -0.95, 1.35, 0.95)
    fp.fab_rect(-1.025, -0.6, 1.025, 0.6)
    silk = fpgen.pcbnew.F_SilkS
    fp.line(silk, -0.25, -0.85, 0.25, -0.85)
    fp.line(silk, -0.25, 0.85, 0.25, 0.85)
    fp.save(lib_dir)

    # NFC coil solder pads: the coil flex lives in the top cover and its tail is soldered here. Flat pads, because a
    # side-entry header (2.95 mm) does not fit under the display glass (2.3 mm above the board top).
    fp = fpgen.Footprint(NFC_FP, "NFC coil flex-tail solder pads, 2 pads 1.2 x 2.0 mm at 2.0 mm pitch, no paste",
                         "NFC antenna coil pads")
    fp.smd("1", -1.0, 0, 1.2, 2.0, paste=False)
    fp.smd("2", 1.0, 0, 1.2, 2.0, paste=False)
    fp.courtyard_rect(-1.85, -1.25, 1.85, 1.25)
    fp.fab_rect(-1.6, -1.0, 1.6, 1.0)
    fp.save(lib_dir)

    # u.FL-only copy of the Raytac footprint: the stock one carries the all-layer keep-out for the
    # MDBT50Q-1MV2/-P1MV2 on-module antenna. The U1MV2 radiates through its u.FL cable, so that
    # keep-out would only block the ground plane and the LED ring above it. The small F.Cu
    # keep-out under the module's RF test area is kept.
    io = fpgen.pcbnew.PCB_IO_MGR.PluginFind(fpgen.pcbnew.PCB_IO_MGR.KICAD_SEXP)
    mod = io.FootprintLoad("/usr/share/kicad/footprints/RF_Module.pretty", "Raytac_MDBT50Q")
    for z in list(mod.Zones()):
        if z.GetIsRuleArea() and z.GetLayerSet().CuStack().size() > 1:
            mod.Remove(z)
    for item in list(mod.GraphicalItems()):
        if hasattr(item, "GetText") and "KEEP OUT" in item.GetText():
            mod.Remove(item)
    mod.SetFPIDAsString(MCU_FP.split(":")[1])
    mod.SetLibDescription("Raytac MDBT50Q-U1MV2 (u.FL) - stock Raytac_MDBT50Q pads without the on-module antenna keep-out")
    io.FootprintSave(lib_dir, mod)


def build(d):
    d.sheet(*SHEET)

    d.group("nRF52840 module MDBT50Q-U1MV2",
            "Normal-voltage mode: VDD + VDDH on +3V3, DCCH n/c,\n"
            "REG1 DC/DC on (its inductor is inside the module).\n"
            "u.FL on module -> Molex 146153-0100 flex antenna.\n"
            "Pin map = nets.MCU_PINS (SPEC §4).\n"
            "UICR: P0.18 = nRESET; NFCPINS stays in NFC mode\n"
            "(P0.09/P0.10 = NFC1/NFC2 antenna).\n"
            "Symbol: stock MDBT50Q-U1MV2 pins, regrouped by port.")
    d.add("U10", "dial_spinner:" + MCU_SYM, "MDBT50Q-U1MV2", MCU_FP,
          pins=dict(MCU_PINS),
          fields={"MPN": "MDBT50Q-U1MV2", "Manufacturer": "Raytac", "LCSC": "C2688382"})

    # Orientation only affects the drawing: C10 drawn GND|+3V3, C11 upright, so no power texts collide.
    d.group("Module VDD/VDDH decoupling", "At pads 28/30, < 2 mm\n(Raytac ref. circuit 8.3: 10 uF)")
    d.add("C10", "Device:C", "10u", C0603, pins={"1": "+3V3", "2": "GND"}, rot=270,
          fields={"MPN": "CL10A106KP8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19702"})
    d.add("C11", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"}, rot=0,
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})

    d.group("USB VBUS (module pad 32) and second-stage USB ESD",
            "R12 in series (nRF52840 PS 7.3 config 1): a legacy-cable hot plug rings the link VBUS to 6.5-8.4 V,\n"
            "above the 5.8 V VBUS abs max; with 4.7 R (Nordic's value) R12 x C12 filters the ring and the pin sees the settled\n"
            "VBUS, 4.49-5.49 V for a 4.5-5.5 V source (hardware/sim test_hotplug_nrf_vbus_abs_max).\n"
            "DC drop ~11 mV at the 2.4 mA VBUS current. C12 on the module side; total sink C < 10 uF.\n"
            "U12 USBLC6 at the module: IEC 8 kV on D+/D- otherwise drives 2.6-3.7 A into the nRF pads through the\n"
            "~145 nH link (HBM 2 kV class = 1.33 A). U12 as close as the module courtyard allows (3.5 mm pad to\n"
            "pad to D-); test_usb_input reads the placed distance.")
    d.add("R12", "Device:R", "4.7", R0402, pins={"1": "VBUS", "2": "VBUS_NRF"},
          fields={"MPN": "FRC0402F4R70TS", "Manufacturer": "FOJAN", "LCSC": "C2909356"})
    d.add("C12", "Device:C", "4.7u/16V", C0603, pins={"1": "VBUS_NRF", "2": "GND"}, rot=0,
          fields={"MPN": "CL10A475KO8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19666"})
    d.add("U12", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS_NRF", "2": "GND"},
          fields={"MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics", "LCSC": "C7519"})
    # VBUS_NRF is fed from the flagged VBUS through R12; ERC does not propagate a supply through a resistor.
    d.add("#FLG10", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "VBUS_NRF"}, in_bom=False, on_board=False)

    d.group("32.768 kHz LFXO", "SC-20S CL 9 pF; Ccap = 2*CL - Cpin - Cpcb ~ 12 pF C0G.\n"
            "R1 <= 90k (nRF RS_LFXO max 100k); DLmax 0.5 uW = nRF PD_LFXO.\n"
            "At pads 17/18, traces < 5 mm, symmetric, GND guard; no copper under Y1.")
    d.add("C13", "Device:C", "12p C0G", C0402, pins={"1": "XL1", "2": "GND"},
          fields={"MPN": "0402CG120J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C1547"})
    d.add("C14", "Device:C", "12p C0G", C0402, pins={"1": "XL2", "2": "GND"},
          fields={"MPN": "0402CG120J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C1547"})
    d.add("Y1", "dial_spinner:" + XTAL_SYM, "32.768k 9pF", "dial_spinner:" + XTAL_FP,
          pins={"1": "XL1", "2": "XL2"},
          fields={"MPN": "SC-20S 32.768kHz 20PPM 9pF", "Manufacturer": "Seiko Instruments", "LCSC": "C97603"})

    d.group("QSPI NOR flash (128 Mbit)",
            "nRF52840-DK QSPI pins (pads 41-46); traces < 20 mm, matched within 2 mm.\n"
            "-IQ suffix: QE=1 fixed, /WP and /HOLD disabled, so IO2/IO3 need no pull-ups.\n"
            "CS pulled up so the flash stays deselected in reset. Use deep power-down when idle.")
    d.add("U11", "Memory_Flash:W25Q128JVS", "W25Q128JVSIQ", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
          pins={"1": "QSPI_CS", "2": "QSPI_IO1", "3": "QSPI_IO2", "4": "GND",
                "5": "QSPI_IO0", "6": "QSPI_SCK", "7": "QSPI_IO3", "8": "+3V3"},
          datasheet="https://www.winbond.com/resource-files/w25q128jv%20revf%2003272018%20plus.pdf",
          fields={"MPN": "W25Q128JVSIQ", "Manufacturer": "Winbond", "LCSC": "C97521"})
    d.add("C15", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})
    d.add("R10", "Device:R", "10k", R0402, pins={"1": "+3V3", "2": "QSPI_CS"},
          fields={"MPN": "0402WGF1002TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25744"})

    d.group("SWD debug (Tag-Connect TC2030-NL)",
            "Footprint only (no BOM part), TOP side under the\n"
            "OLED glass (SPEC section 8).\n"
            "Keep the 3 NPTH holes + cable-head area clear.\n"
            "No series parts on SWD. NRESET: internal pull-up,\n"
            "R11 is a DNP option.")
    d.add("J10", "Connector:Conn_ARM_SWD_TagConnect_TC2030-NL", "SWD",
          "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
          pins={"1": "+3V3", "2": "SWDIO", "3": "NRESET", "4": "SWDCLK", "5": "GND", "6": "SWO"},
          fields={"MPN": "TC2030-IDC-NL (footprint only)", "Manufacturer": "Tag-Connect"},
          in_bom=False)
    d.add("R11", "Device:R", "10k", R0402, pins={"1": "+3V3", "2": "NRESET"}, dnp=True,
          fields={"MPN": "0402WGF1002TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25744"})

    d.group("NFC tag antenna (nRF52840 NFCT, NFC-A Type 2/4)",
            "Coil between NFC1 and NFC2: its flex tail solders to pads J11 (coil in the top cover).\n"
            "Tune: Ctune = 2/((2*pi*13.56 MHz)^2 * L_coil) - Cp - Cint (Cint ~ 4 pF, PS 6.13);\n"
            "180 pF C0G each suits L ~ 1.4-1.5 uH; retune on prototype.\n"
            "Route NFC1/NFC2 as a pair, away from the TMAG and the LED data line.")
    d.add("C16", "Device:C", "180p C0G", C0402, pins={"1": "NFC1", "2": "GND"},
          fields={"MPN": "0402CG181J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C78636"})
    d.add("C17", "Device:C", "180p C0G", C0402, pins={"1": "NFC2", "2": "GND"},
          fields={"MPN": "0402CG181J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C78636"})
    d.add("J11", "Connector_Generic:Conn_01x02", "NFC_COIL", "dial_spinner:" + NFC_FP,
          pins={"1": "NFC1", "2": "NFC2"}, in_bom=False,
          description="Solder pads for the NFC coil flex tail (no part fitted)")

    d.group("Spare GPIO test pads", "Value = module GPIO\n(P0.03/P0.04 = AIN1/AIN2)")
    spares = {"TP_SPARE1": "P0.03", "TP_SPARE2": "P0.04", "TP_SPARE3": "P1.11", "TP_SPARE4": "P1.13"}
    for i, (net, gpio) in enumerate(spares.items()):
        assert MCU_PINS[gpio] == net
        d.add(f"TP{10 + i}", "Connector:TestPoint", gpio, "TestPoint:TestPoint_Pad_D1.0mm",
              pins={"1": net}, in_bom=False)
