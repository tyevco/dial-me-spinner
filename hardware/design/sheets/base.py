"""Base board: USB-C input + protection, BQ25180 charger / power path, battery + NTC,
centre press switch with ship-mode wake network, and the board-to-board link.
See SPEC.md §2, §3 and §6.

This board is its own KiCad project, so every non-power net here is a local label.
BTN_N, CHG_INT_N and the I2C lines have NO pull-ups on this board: they live on
the main board (SPEC §2, §5.5).

Pinouts were checked against the primary datasheets:
  * BQ25180YBGR (TI SLUSE99C, Fig. 6-1 / Table 6-1, YBG0008-C01 outline + land
    pattern + stencil, pages 52-54): A1 /INT, A2 IN, B1 SCL, B2 SYS, C1 SDA,
    C2 BAT, D1 TS/MR, D2 GND; 2x4 balls, 0.4 mm pitch, body 1.04 x 1.59 mm nom.
  * HRO TYPE-C-31-M-12 drawing (LCSC C165948): A5 CC1, B5 CC2, A6/B6 D+,
    A7/B7 D-, A8/B8 SBU, A4/A9/B4/B9 VBUS, A1/A12/B1/B12 GND; the stock KiCad
    footprint uses the same pad names in the same row order.
  * USBLC6-2SC6 (ST DS5934 / Doc ID 11265 Rev 5, Fig. 1): 1 I/O1, 2 GND, 3 I/O2,
    4 I/O2, 5 VBUS, 6 I/O1 (flow-through: 1-6 and 3-4 are the same line).
  * BSS138DW (Diodes DS30203): SOT363 S1 G1 D2 / S2 G2 D1 -> KiCad
    Q_Dual_NMOS_S1G1D2S2G2D1 (pins 1 S, 2 G, 6 D = FET A; 4 S, 5 G, 3 D = FET B).
  * SMF5.0A (Littelfuse SMF datasheet): SOD-123FL, colour band = cathode; the
    mounting pad layout (1.3 x 1.4 pads, 1.6 gap) equals KiCad Diode_SMD:D_SMF,
    pad 1 = cathode.
  * TS-1187A-B-A-B (XKB drawing, LCSC C318884): A-B and C-D are the common pairs;
    KiCad Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A numbers the A/B pads "1"
    and the C/D pads "2" with the same 7.0/5.0 x 4.5/3.0 mm layout.
"""

from nets import LINK_PINOUT

SHEET = ("base", "base.kicad_sch", "Base board")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

BQ_FP_NAME = "Texas_DSBGA-8_1.04x1.59mm_Layout2x4_P0.4mm_YBG0008"
BQ_FP = "dial_spinner:" + BQ_FP_NAME
BQ_DS = "https://www.ti.com/lit/ds/symlink/bq25180.pdf"

SYMBOLS = [
    dict(
        name="BQ25180YBGR",
        ref="U",
        footprint=BQ_FP,
        datasheet=BQ_DS,
        description="I2C 1-cell 1 A linear charger with power path and ship mode, DSBGA-8 (YBG), I2C addr 0x6A",
        keywords="charger li-ion lipo power-path ship-mode",
        pins=[
            ("A2", "IN", "power_in", "T"),
            ("B1", "SCL", "input", "L"),
            ("C1", "SDA", "bidirectional", "L"),
            ("A1", "~{INT}", "open_collector", "L"),
            ("D1", "TS/MR", "bidirectional", "L"),
            ("B2", "SYS", "power_out", "R"),
            ("C2", "BAT", "power_out", "R"),
            ("D2", "GND", "power_in", "B"),
        ],
    ),
]


def footprints(fpgen, lib_dir):
    """BQ25180 YBG0008 land pattern per TI SLUSE99C pages 52-54 (no matching stock footprint:
    Package_BGA:Texas_DSBGA-8_0.705x1.468mm_Layout2x4_P0.4mm is the smaller YBJ body with 0.2 mm pads)."""
    pcbnew = fpgen.pcbnew
    fp = fpgen.Footprint(
        BQ_FP_NAME,
        "Texas Instruments DSBGA-8 YBG0008-C01 (BQ25180YBGR), body 1.04x1.59 mm, 2x4 balls, 0.4 mm pitch, "
        "TI example land pattern: 0.23 mm NSMD copper, mask opening <= 0.05 mm larger (0.025 per side used), "
        "0.25 mm square R0.05 paste apertures for a 0.1 mm stencil. " + BQ_DS,
        "DSBGA YBG0008 BQ25180 BGA 0.4mm NSMD",
    )
    rows = (("A", -0.6), ("B", -0.2), ("C", 0.2), ("D", 0.6))   # top view: A1 top-left
    cols = (("1", -0.2), ("2", 0.2))
    for r, y in rows:
        for c, x in cols:
            p = fp.smd(r + c, x, y, 0.23, 0.23, shape="circle", paste=False)
            p.SetLocalSolderMaskMargin(pcbnew.FromMM(0.025))
            p.SetProperty(pcbnew.PAD_PROP_BGA)
            # separate stencil aperture (TI example stencil: 8x 0.25 mm square, R0.05)
            fp._pad("", x, y, 0.25, 0.25, "roundrect", pcbnew.PAD_ATTRIB_SMD, [pcbnew.F_Paste], rr=0.2)
    hw, hh = 0.52, 0.795                        # nominal body half sizes (E 1.04, D 1.59)
    fp.fab_rect(-hw, -hh, hw, hh)
    fp.line(pcbnew.F_Fab, -hw, -hh + 0.25, -hw + 0.25, -hh, 0.1)   # pin A1 bevel
    fp.silk_rect(-hw - 0.1, -hh - 0.1, hw + 0.1, hh + 0.1)
    fp.pin1_dot(-hw - 0.4, -hh - 0.25)
    fp.courtyard_rect(-1.02, -1.30, 1.02, 1.30)  # IPC-7351 nominal (0.5 mm) BGA courtyard excess
    fp.save(lib_dir)


def build(d):
    d.sheet(*SHEET)

    d.group("USB-C input and protection",
            "HRO TYPE-C-31-M-12 (sink, USB 2.0). Separate 5.1k Rd per CC pin; D+/D- pairs tied at the connector.\n"
            "USBLC6-2SC6 and SMF5.0A within 5 mm of J1; route D+/D- through the ESD pads (flow-through) as a 90R pair.\n"
            "J1 body (3.26 mm tall, 7.35 mm deep) reaches r ~27.6, under the FA lower plate (r <= 30): plate needs a relief there.")
    d.add("R1", "Device:R", "5.1k", R0402, pins={"1": "USB_CC1", "2": "GND"},
          fields={"MPN": "0402WGF5101TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25905"})
    d.add("R2", "Device:R", "5.1k", R0402, pins={"1": "USB_CC2", "2": "GND"},
          fields={"MPN": "0402WGF5101TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25905"})
    d.add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "TYPE-C-31-M-12",
          "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
          pins={"A4": "VBUS", "A1": "GND", "S1": "GND",
                "A5": "USB_CC1", "B5": "USB_CC2",
                "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
                "A8": None, "B8": None},
          fields={"MPN": "TYPE-C-31-M-12", "Manufacturer": "Korean Hroparts Elec", "LCSC": "C165948"})
    d.add("D1", "Diode:SMF5V0A", "SMF5.0A", "Diode_SMD:D_SMF",
          pins={"1": "VBUS", "2": "GND"}, rot=270,
          datasheet="https://www.littelfuse.com/assetdocs/tvs-diodes-smf-datasheet",
          description="200 W unidirectional TVS, 5.0 V VRWM, SOD-123FL (cathode = pin 1 to VBUS)",
          fields={"MPN": "SMF5.0A", "Manufacturer": "Littelfuse", "LCSC": "C151296"})
    d.add("U2", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS", "2": "GND"},
          fields={"MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics", "LCSC": "C7519"})

    d.group("Charger and power path (BQ25180, I2C 0x6A)",
            "IN 2.2u/25V, SYS 10u/25V, BAT 4.7u: each within 1 mm of its ball and of the D2 GND ball.\n"
            "SYS = VSYS (4.4 V on USB, SYS_REG set by firmware; VBAT on battery). /INT, SCL, SDA pull-ups are on the main board.")
    d.add("U1", "dial_spinner:BQ25180YBGR", "BQ25180YBGR", BQ_FP,
          pins={"A2": "VBUS", "B2": "VSYS", "C2": "VBAT", "D2": "GND",
                "B1": "I2C_SCL", "C1": "I2C_SDA", "A1": "CHG_INT_N", "D1": "CHG_TSMR"},
          fields={"MPN": "BQ25180YBGR", "Manufacturer": "Texas Instruments", "LCSC": "C3682423"})
    # 0805 X7R: an 0603 X5R loses too much to DC bias at 5.5 V + temperature to keep the BQ25180's >= 1 uF
    # effective CIN (hardware/sim test_usb_input, USB-3)
    d.add("C1", "Device:C", "2.2u/25V", "Capacitor_SMD:C_0805_2012Metric", pins={"1": "VBUS", "2": "GND"},
          fields={"MPN": "CC0805KKX7R8BB225", "Manufacturer": "YAGEO", "LCSC": "C277470"})
    d.add("C2", "Device:C", "10u/25V", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106MA8NRNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C96446"})
    d.add("C3", "Device:C", "4.7u", C0603, pins={"1": "VBAT", "2": "GND"},
          fields={"MPN": "CL10A475KO8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19666"})

    d.group("Battery connector J2 and NTC RT1 (TS/MR)",
            "J2 SM04B side-entry SH (2.95 mm): pins 1-2 = BAT+, 3-4 = GND (two 28 AWG leads\n"
            "per rail). Packs are re-terminated: check the polarity of every pack.\n"
            "RT1 on TS/MR: top side, at the board edge farthest from U1\n"
            "(>= 10 mm), no copper shared with U1. Bottom side has no parts,\n"
            "so RT1 reads board temperature, not the cell. GND Kelvin to D2.\n"
            "No cap on TS/MR (TS bias is pulsed 4 ms / 196 ms).")
    # Side-entry JST SH, 2.95 mm tall: a PH (4.8 mm + plug) hits the rotor web when the dial is pressed and its plug
    # runs into the spider ring. Two contacts per rail (SH: 1 A per contact) carry the ≤ 1.5 A pack current.
    d.add("J2", "Connector_Generic_MountingPin:Conn_01x04_MountingPin", "BATT",
          "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
          pins={"1": "VBAT", "2": "VBAT", "3": "GND", "4": "GND", "MP": "GND"},
          fields={"MPN": "SM04B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160404"})
    d.add("RT1", "Device:Thermistor_NTC", "10k B3435", R0402, pins={"1": "CHG_TSMR", "2": "GND"},
          datasheet="https://www.murata.com/en-us/products/productdetail?partno=NCP15XH103F03RC",
          fields={"MPN": "NCP15XH103F03RC", "Manufacturer": "Murata", "LCSC": "C77131"})

    d.group("Centre press switch and ship-mode wake",
            "SW1 at the board centre (top). Press: VBAT -> 1k -> SW1 -> SW_GATE (100k to GND, ~42 uA while held;\n"
            "the gates discharge within the BQ25180 deglitch on release).\n"
            "Q1A pulls TS/MR low (ship wake / 20 s HW reset); Q1B pulls BTN_N low (nRF SENSE wake). BTN_N pull-up is on main.")
    d.add("R3", "Device:R", "1k", R0402, pins={"1": "SW_HI", "2": "VBAT"},
          fields={"MPN": "0402WGF1001TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C11702"})
    d.add("SW1", "Switch:SW_Push", "TS-1187A", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
          pins={"1": "SW_HI", "2": "SW_GATE"}, rot=270,
          datasheet="https://www.lcsc.com/datasheet/C318884.pdf",
          description="Tactile switch SPST-NO 5.1x5.1x1.5 mm, 160 gf (1.6 N), 0.2 mm travel",
          fields={"MPN": "TS-1187A-B-A-B", "Manufacturer": "XKB Connection", "LCSC": "C318884"})
    # 100k, not 1M: the Q1 gates (~90-150 pF) must discharge within the BQ25180 deglitch after a release, or TS/MR
    # sits between the press threshold and the NTC voltage and reads a false temperature (hardware/sim test_charger_ts)
    d.add("R4", "Device:R", "100k", R0402, pins={"1": "SW_GATE", "2": "GND"},
          fields={"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"})
    q_fields = {"MPN": "BSS138DW-7-F", "Manufacturer": "Diodes Incorporated", "LCSC": "C154900"}
    q_ds = "https://www.diodes.com/assets/Datasheets/ds30203.pdf"
    d.add("Q1", "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1", "BSS138DW", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
          pins={"2": "SW_GATE", "6": "CHG_TSMR", "1": "GND"}, unit=1, datasheet=q_ds, fields=q_fields)
    d.add("Q1", "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1", "BSS138DW", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
          pins={"5": "SW_GATE", "3": "BTN_N", "4": "GND"}, unit=2, datasheet=q_ds, fields=q_fields)

    d.group("Board-to-board link (to main board through the spindle)",
            "JST SH 12-way SIDE-entry (SM12B, 2.95 mm) at r 15.5, θ 120°, entry facing the centre; identical pinout\n"
            "on the main board (SPEC §2). C4 sits next to J3. The harness runs into the spindle's side slot.")
    d.add("J3", "Connector_Generic_MountingPin:Conn_01x12_MountingPin", "LINK",
          "Connector_JST:JST_SH_SM12B-SRSS-TB_1x12-1MP_P1.00mm_Horizontal",
          pins={**{str(k): v for k, v in LINK_PINOUT.items()}, "MP": "GND"},
          fields={"MPN": "SM12B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160411"})
    d.add("C4", "Device:C", "10u/25V", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106MA8NRNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C96446"})

    d.group("Test points and power flags",
            "PWR_FLAGs mark VBUS (USB-C) and GND\nas externally driven for ERC.")
    d.add("#FLG01", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "VBUS"}, in_bom=False, on_board=False, rot=90)
    d.add("#FLG02", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "GND"}, in_bom=False, on_board=False, rot=90)
    for i, net in enumerate(["VBUS", "VBAT", "VSYS", "GND"], start=1):
        d.add(f"TP{i}", "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
              pins={"1": net}, in_bom=False)
