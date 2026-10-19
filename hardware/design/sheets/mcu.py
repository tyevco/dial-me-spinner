"""Main board: nRF52840 module, 32.768 kHz crystal, QSPI flash, SWD debug, spare test pads. See SPEC.md §4, §5.2.

Pinouts verified against primary datasheets:
* MDBT50Q-U1MV2: Raytac "MDBT50Q-1MV2 / -P1MV2" spec Ver.K, §2.1 (top-view pin indication),
  §2.2 (solder-pad layout) and §2.5 (pin assignment table, pads 1-61). The KiCad symbol
  RF_Module:MDBT50Q-U1MV2 and footprint RF_Module:Raytac_MDBT50Q agree pad for pad.
  §8.3 "Reg0 DC/DC and LDO mode disabled" is the reference circuit followed here.
* W25Q128JVSIQ: Winbond W25Q128JV datasheet Rev F, Fig. 1a / §3.3 (SOIC-8 208 mil):
  1 /CS, 2 DO(IO1), 3 /WP(IO2), 4 GND, 5 DI(IO0), 6 CLK, 7 /HOLD(IO3), 8 VCC.
* SC-20S: SII spec sheet §[7] (outline, recommended pad layout 0.7 x 1.4 mm, 0.8 mm gap).
* TC2030-IDC-NL: Tag-Connect TC2030-CTX: 1 VCC, 2 SWDIO, 3 nRESET, 4 SWCLK, 5 GND, 6 SWO.
"""

from nets import MCU_PINS

SHEET = ("mcu", "mcu.kicad_sch", "MCU, flash & debug")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

XTAL_FP = "Crystal_SII_SC-20S_2.0x1.2mm"

SYMBOLS = []


def footprints(fpgen, lib_dir):
    # SII SC-20S recommended pad layout (spec §[7]-4): two 0.7 x 1.4 mm pads, 0.8 mm gap
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


def build(d):
    d.sheet(*SHEET)

    d.group("nRF52840 module (Raytac MDBT50Q-U1MV2)",
            "Normal-voltage mode: VDD (28) + VDDH (30) on +3V3, DCCH (31) n/c, REG1 DC/DC (inductor in module).\n"
            "u.FL on the module -> Molex 146153-0050 flex antenna (mechanical item). Pin map = nets.MCU_PINS (SPEC §4).\n"
            "P0.10/NFC2 stays floating (never tie it): NFC pins as GPIO via UICR; P0.18 = pin reset via UICR.")
    d.add("U10", "RF_Module:MDBT50Q-U1MV2", "MDBT50Q-U1MV2", "RF_Module:Raytac_MDBT50Q",
          pins=dict(MCU_PINS),
          fields={"MPN": "MDBT50Q-U1MV2", "Manufacturer": "Raytac", "LCSC": "C2688382"})

    d.group("Module decoupling", "Place at pads 28/30 (+3V3) and 32 (VBUS), < 2 mm.\n"
            "VBUS 4.7 uF keeps the total VBUS capacitance (+ BQ25180 IN 2.2 uF) under 10 uF.")
    d.add("C10", "Device:C", "10u", C0603, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL10A106KP8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19702"})
    d.add("C11", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})
    d.add("C12", "Device:C", "4.7u/16V", C0603, pins={"1": "VBUS", "2": "GND"},
          fields={"MPN": "CL10A475KO8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19666"})

    d.group("32.768 kHz LFXO", "SC-20S CL 9 pF; Ccap = 2*CL - Cpin - Cpcb ~ 12 pF C0G.\n"
            "At pads 17/18, traces < 5 mm, symmetric, GND guard; no copper under Y1.")
    d.add("Y1", "Device:Crystal", "32.768k 9pF", "dial_spinner:" + XTAL_FP,
          pins={"1": "XL1", "2": "XL2"},
          datasheet="https://atta.szlcsc.com/upload/public/pdf/source/20240416/BFC04A78B0E1C9E9B6060A4EC5547171.pdf",
          description="32.768 kHz crystal, 20 ppm, CL 9 pF, 2.05x1.2 mm",
          fields={"MPN": "SC-20S 32.768kHz 20PPM 9pF", "Manufacturer": "Seiko Instruments", "LCSC": "C97603"})
    d.add("C13", "Device:C", "12p C0G", C0402, pins={"1": "XL1", "2": "GND"},
          fields={"MPN": "0402CG120J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C1547"})
    d.add("C14", "Device:C", "12p C0G", C0402, pins={"1": "XL2", "2": "GND"},
          fields={"MPN": "0402CG120J500NT", "Manufacturer": "FH (Guangdong Fenghua)", "LCSC": "C1547"})

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
            "Footprint only (no BOM part); bottom side, keep the 3 NPTH holes and cable-head area clear.\n"
            "No series parts on SWDIO/SWDCLK. NRESET has the internal pull-up; R11 is a DNP option.")
    d.add("J10", "Connector:Conn_ARM_SWD_TagConnect_TC2030-NL", "SWD",
          "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
          pins={"1": "+3V3", "2": "SWDIO", "3": "NRESET", "4": "SWDCLK", "5": "GND", "6": "SWO"},
          fields={"MPN": "TC2030-IDC-NL (footprint only)", "Manufacturer": "Tag-Connect"},
          in_bom=False)
    d.add("R11", "Device:R", "10k", R0402, pins={"1": "+3V3", "2": "NRESET"}, dnp=True,
          fields={"MPN": "0402WGF1002TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25744"})

    d.group("Spare GPIO test pads", "TP_SPARE1..4 = P0.03 (AIN1), P0.04 (AIN2), P1.11, P1.13")
    for i, net in enumerate(["TP_SPARE1", "TP_SPARE2", "TP_SPARE3", "TP_SPARE4"]):
        d.add(f"TP{10 + i}", "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
              pins={"1": net}, in_bom=False)
