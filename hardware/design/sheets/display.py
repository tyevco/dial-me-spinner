"""Main board: SSD1351 1.5in OLED (NHD-1.5-128128G) on a 30-pin ZIF + gated 13 V panel boost. See SPEC.md §5.3.

Panel pin functions are taken from the Newhaven NHD-1.5-128128G datasheet
(https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf, "Pin Description" and
"Interface Selection" p.4, "Wiring Diagram" p.5). The panel is modelled as the 30-way
ZIF connector J20 whose pin N is FPC contact N; the nets carry the panel functions.

ZIF land pattern from the JUSHUO AFC01-S**FCA-00 drawing (LCSC C262671 datasheet,
"Recommended P.C.B pattern layout"): 30x 0.30x1.30 mm pads at 0.50 mm pitch
(DIM A = 14.50 mm), fitting-nail pads 2.00x1.60 mm whose outer edge is 2.70 mm
outboard of the pin 1/30 centres and whose bottom edge is 4.13 mm below the top of
the signal pads.
"""

SHEET = ("display", "display.kicad_sch", "OLED display & 13 V boost")

R0402 = "Resistor_SMD:R_0402_1005Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"

ZIF_FP_NAME = "JUSHUO_AFC01-S30FCA-00_1x30-1MP_P0.50mm_Horizontal"
ZIF_FP = "dial_spinner:" + ZIF_FP_NAME

NHD_DS = "https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf"
ZIF_DS = "https://www.lcsc.com/datasheet/C262671.pdf"
TPS_DS = "https://www.ti.com/lit/ds/symlink/tps61040.pdf"

# B5819W: the stock Device:D_Schottky has horizontal pins, and the generator then puts its
# Reference/Value on the right-hand stub (over the +13V_OLED symbol).  This 2-pin symbol has
# vertical pins (A top, K bottom) so the generator lays it out horizontally with A on the left,
# K on the right and the fields above/below the body.  Pin numbers = SOD-123 pads (1 = K, cathode band).
SYMBOLS = [
    dict(
        name="B5819W_SOD123",
        ref="D",
        footprint="Diode_SMD:D_SOD-123",
        datasheet="https://www.lcsc.com/datasheet/C8598.pdf",
        description="40 V 1 A Schottky rectifier, SOD-123; pin 1 = K (cathode band), pin 2 = A",
        keywords="schottky diode rectifier",
        pins=[
            (2, "A", "passive", "T"),
            (1, "K", "passive", "B"),
        ],
    ),
]

# FPC contact -> net, per NHD-1.5-128128G pin table, 4-wire SPI column of the
# interface-selection table ("0" = VSS, "NC" = no connect).  None = no-connect flag.
PANEL_PINS = {
    1: "GND",          # NC (GND): may be tied to ground -> GND for ESD
    2: "+13V_OLED",    # VCC, OLED panel supply 12.5-13.5 V
    3: "OLED_VCOMH",   # VCOMH output -> 4.7 uF/25 V tantalum
    4: "+3V3",         # VDDIO, I/O supply (= nRF I/O rail, VIH = 0.8 VDDIO)
    5: "OLED_VSL",     # VSL output -> 50 ohm + ~1.4 V diode pair to VSS
    6: None,           # NC
    7: "GND",          # D7  : 4-wire SPI -> 0
    8: "GND",          # D6  : 0
    9: "GND",          # D5  : 0
    10: "GND",         # D4  : 0
    11: "GND",         # D3  : 0
    12: None,          # D2  : NC in serial mode (leave open)
    13: "OLED_MOSI",   # D1 = SDIN
    14: "OLED_SCK",    # D0 = SCLK
    15: "GND",         # E/RD# : 0
    16: "GND",         # R/W#  : 0
    17: "GND",         # BS0 = 0 \ BS1:BS0 = 00 selects 4-wire SPI
    18: "GND",         # BS1 = 0 /
    19: "OLED_CS_N",   # CS#
    20: "OLED_DC",     # D/C#
    21: "OLED_RES_N",  # RES#
    22: "OLED_IREF",   # IREF -> 560k to VSS
    23: None,          # GPIO1 (can be treated as NC)
    24: None,          # GPIO0 (can be treated as NC)
    25: None,          # NC
    26: "OLED_VDD",    # VDD, internal regulator output: 1 uF to GND only, never driven
    27: "+3V3",        # VCI, operating supply 2.4-3.5 V
    28: "GND",         # VSS
    29: None,          # NC
    30: "GND",         # NC (GND)
}

ZIF_NOTE = (
    "Pin map from Newhaven NHD-1.5-128128G datasheet, Pin Description + Interface Selection (p.4), Wiring Diagram (p.5):\n"
    "  " + NHD_DS + "   (Orient AOC128128A0-1.50W is pin-identical)\n"
    "1 NC(GND)=GND | 2 VCC=+13V_OLED | 3 VCOMH | 4 VDDIO=+3V3 | 5 VSL | 6 NC | 7-11 D7..D3=GND\n"
    "12 D2 open (SPI) | 13 D1=SDIN | 14 D0=SCLK | 15 E/RD#=GND | 16 R/W#=GND | 17 BS0=GND | 18 BS1=GND\n"
    "19 CS# | 20 D/C# | 21 RES# | 22 IREF | 23 GPIO1, 24 GPIO0, 25 NC: open | 26 VDD (int. reg.)\n"
    "27 VCI=+3V3 | 28 VSS | 29 NC | 30 NC(GND)=GND.   BS1:BS0 = 00 -> 4-wire SPI, write-only, mode 0, <= 20 MHz.\n"
    "Bottom-contact ZIF: FPC folds 180 deg behind the glass (NHD's top-contact advice is for unfolded entry).\n"
    "RES# 1M pull-down keeps the panel in reset while the MCU is in reset. Mates with the panel (not assembled).\n"
    "FPC fit: NHD W 15.5+/-0.2 / t 0.3+/-0.03 / stiffener 4+/-0.5 vs JUSHUO slot 15.60+/-0.05, recommended FPC\n"
    "  15.50+/-0.05 / t 0.30+/-0.01 / stiffener 6.0: check insertion, latch and retention with real panel samples\n"
    "  (with the 1:1 contact-side mock-up) before PCBA."
)


def footprints(fpgen, lib_dir):
    """JUSHUO AFC01-S30FCA-00: 30 pins, 0.5 mm, bottom contact, flip lid, 2.0 mm high.

    Origin = centre of the signal-pad row.  Pin 1 at -X, solder tails toward -Y, FPC
    enters from +Y (latch side).  Dimensions per the JUSHUO recommended PCB pattern.
    """
    pcbnew = fpgen.pcbnew
    fp = fpgen.Footprint(
        ZIF_FP_NAME,
        "JUSHUO AFC01-S30FCA-00 FFC/FPC connector, 30 pins, 0.5 mm pitch, bottom contact, flip lock, "
        "2.0 mm high, SMD right angle (" + ZIF_DS + ")",
        "FPC FFC ZIF 0.5mm 30pin bottom contact JUSHUO AFC01",
    )
    pitch, n = 0.5, 30
    x1 = -(n - 1) * pitch / 2  # pin 1 centre, -7.25
    for i in range(n):
        fp.smd(str(i + 1), round(x1 + i * pitch, 3), 0.0, 0.30, 1.30)
    # fitting nails: 2.00 x 1.60, outer edge 2.70 outboard of pin 1/30, bottom 4.13 below pad top
    mp_x = round(abs(x1) + 2.70 - 1.00, 3)   # 8.95
    mp_y = round(-0.65 + 4.13 - 0.80, 3)     # 2.68
    fp.smd("MP", -mp_x, mp_y, 2.00, 1.60)
    fp.smd("MP", mp_x, mp_y, 2.00, 1.60)
    # housing (DIM C = 19.40 wide, 5.35 deep)
    hx, ht, hb = 9.70, 0.35, 5.70
    fp.fab_rect(-hx, ht, hx, hb)
    fp.line(pcbnew.F_Fab, x1 - 0.4, ht, x1, ht + 0.6, 0.1)   # pin-1 chamfer mark on fab
    fp.line(pcbnew.F_Fab, x1, ht + 0.6, x1 + 0.4, ht, 0.1)
    # silkscreen, clear of pads
    s = 9.81
    for sx in (-1, 1):
        fp.line(pcbnew.F_SilkS, sx * s, ht - 0.11, sx * 7.75, ht - 0.11)   # top corner
        fp.line(pcbnew.F_SilkS, sx * s, ht - 0.11, sx * s, 1.65)          # side above nail
        fp.line(pcbnew.F_SilkS, sx * s, 3.72, sx * s, hb + 0.11)          # side below nail
    fp.line(pcbnew.F_SilkS, -s, hb + 0.11, s, hb + 0.11)                  # FPC entry edge
    fp.pin1_dot(x1, -1.15)
    fp.courtyard_rect(-10.25, -1.50, 10.25, 6.20)
    fp.save(lib_dir)


def _pad(note, width):
    """Pad the first note line with trailing spaces so the generator reserves `width` mm for the frame.

    The generator sizes a frame from the longest note line at ~1.0 mm/char; real italic text is
    ~1.13 mm/char, and power-symbol values / 2-pin field text at a row end overhang the part
    extents.  The invisible padding keeps both inside the frame.
    """
    first, _, rest = note.partition("\n")
    return first.ljust(width) + ("\n" + rest if rest else "")


def build(d):
    d.sheet(*SHEET)
    # Layout notes (generator-specific): 2-pin parts whose pins carry long power names
    # (+13V_OLED, OLED_VIN) are drawn vertical (rot=0) with the long name on the bottom pin;
    # vertical parts alternate with horizontal ones so their side fields never collide.

    # ------------------------------------------------------------------ panel
    d.group("OLED ZIF J20: NHD-1.5-128128G panel, 30-pin 0.5 mm FPC", _pad(ZIF_NOTE, 132))
    d.add("J20", "Connector_Generic_MountingPin:Conn_01x30_MountingPin", "OLED_ZIF30", ZIF_FP,
          pins={**{str(k): v for k, v in PANEL_PINS.items()}, "MP": "GND"},
          datasheet=ZIF_DS,
          description="30-pin 0.5 mm bottom-contact flip-lock FPC connector for the NHD-1.5-128128G OLED",
          fields={"MPN": "AFC01-S30FCA-00", "Manufacturer": "JUSHUO", "LCSC": "C262671",
                  "Mates_With": "NHD-1.5-128128G (Newhaven) / AOC128128A0-1.50W (Orient)",
                  "Panel_Datasheet": NHD_DS})
    d.add("R20", "Device:R", "1M", R0402, pins={"1": "OLED_RES_N", "2": "GND"},
          fields={"MPN": "0402WGF1004TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C26083"})
    d.add("#FLG21", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "+13V_OLED"}, in_bom=False, on_board=False)

    d.group("Panel supply capacitors (at the ZIF pins)", _pad(
            "NHD wiring diagram: VCC C5 0.1u + C6 10u (C31, C30), VCOMH C7 4.7u/25V tantalum (C32),\n"
            "VDDIO C3 1u (C33), VDD C4 1u (C34), VCI C1 0.1u + C2 4.7u (C36, C35).\n"
            "C39 = boost output cap on +13V_OLED: place it at D21 / U20 GND, not at the ZIF.\n"
            "No bleeders or QOD switches on +3V3 / +13V_OLED (VCC must float when off).", 182))
    d.add("C32", "Device:C_Polarized", "4.7u/25V Ta", "Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A",
          pins={"1": "OLED_VCOMH", "2": "GND"},
          description="VCOMH (FPC pin 3) tantalum, + to VCOMH",
          fields={"MPN": "TAJA475K025RNJ", "Manufacturer": "KYOCERA AVX", "LCSC": "C7189"})
    d.add("C30", "Device:C", "10u/25V", C0805, rot=0, pins={"1": "GND", "2": "+13V_OLED"},
          description="VCC (FPC pin 2) bulk",
          fields={"MPN": "CL21A106KAYNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C15850"})
    d.add("C33", "Device:C", "1u", C0402, pins={"1": "GND", "2": "+3V3"},
          description="VDDIO (FPC pin 4) decoupling",
          fields={"MPN": "CL05A105KA5NQNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C52923"})
    d.add("C31", "Device:C", "100n/50V", C0402, rot=0, pins={"1": "GND", "2": "+13V_OLED"},
          description="VCC (FPC pin 2) HF decoupling",
          fields={"MPN": "CL05B104KB54PNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C307331"})
    d.add("C34", "Device:C", "1u", C0402, pins={"1": "OLED_VDD", "2": "GND"},
          description="VDD (FPC pin 26, internal regulator output)",
          fields={"MPN": "CL05A105KA5NQNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C52923"})
    d.add("C39", "Device:C", "4.7u/25V", C0805, rot=0, pins={"1": "GND", "2": "+13V_OLED"},
          description="Boost output capacitor (place at D21 cathode / U20 GND)",
          fields={"MPN": "CL21A475KAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1779"})
    d.add("C35", "Device:C", "4.7u/25V", C0805, pins={"1": "GND", "2": "+3V3"},
          description="VCI (FPC pin 27) bulk",
          fields={"MPN": "CL21A475KAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1779"})
    d.add("C36", "Device:C", "100n", C0402, rot=0, pins={"1": "GND", "2": "+3V3"},
          description="VCI (FPC pin 27) HF decoupling",
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})

    d.group("IREF and VSL networks",
            "IREF: R = (VCC - 6 V) / 12.5 uA = 560k at 13 V (recompute if VCC changes).\n"
            "VSL: 50 ohm 1/4 W + ~1.4 V: BAV99 as 2 series diodes (pin 1 A1, pin 3 mid NC, pin 2 K2).")
    d.add("R21", "Device:R", "560k", R0402, pins={"1": "OLED_IREF", "2": "GND"},
          fields={"MPN": "0402WGF5603TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C132339"})
    d.add("R22", "Device:R", "51R 1/4W", R1206, pins={"1": "OLED_VSL", "2": "OLED_VSL_D"},
          fields={"MPN": "1206W4F510JT5E", "Manufacturer": "UNI-ROYAL", "LCSC": "C18019"})
    d.add("D20", "Diode:BAV99", "BAV99", SOT23,
          pins={"1": "OLED_VSL_D", "2": "GND", "3": None},
          fields={"MPN": "BAV99,215", "Manufacturer": "Nexperia", "LCSC": "C2500"})

    # ------------------------------------------------------------------ boost
    d.group("Boost input: load switch VSYS -> OLED_VIN, CIN, inductor", _pad(
            "OLED_VCC_EN low (also through MCU reset, R25) -> U21 off: VCC floats, boost draws 0 uA.\n"
            "Without it a disabled boost still passes VSYS - Vf to VCC through L20 and D21.\n"
            "U21 TPS22917: CT 1 nF from CT to VIN (C37) -> ~4 ms ramp, ~10 mA inrush into ~16 uF; QOD open.\n"
            "(Replaces the AO3401A/2N7002 disconnect, which had no real dV/dt control - review SCH-1.)\n"
            "LAYOUT: L20 and the SW node >= 10 mm from the TMAG5273 and the magnet track.", 180))
    d.add("U21", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "VSYS", "GND": "GND", "ON": "OLED_VCC_EN", "CT": "OLED_LSW_CT", "QOD": None, "VOUT": "OLED_VIN"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    d.add("C37", "Device:C", "1n/50V", C0402, pins={"1": "OLED_LSW_CT", "2": "VSYS"},
          fields={"MPN": "0402B102K500NT", "Manufacturer": "FH", "LCSC": "C1523"})
    d.add("C41", "Device:C", "10u", "Capacitor_SMD:C_0603_1608Metric", pins={"1": "VSYS", "2": "GND"},
          description="U21 VIN bypass",
          fields={"MPN": "CL10A106KP8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19702"})
    d.add("C38", "Device:C", "4.7u/25V", C0805, rot=0, pins={"1": "GND", "2": "OLED_VIN"},
          description="Boost input capacitor (place at U20 VIN/GND)",
          fields={"MPN": "CL21A475KAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1779"})
    d.add("R25", "Device:R", "100k", R0402, pins={"1": "OLED_VCC_EN", "2": "GND"},
          fields={"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"})
    d.add("L20", "Device:L", "10u", "Inductor_SMD:L_Sunlord_SWPA3015S",
          rot=0, pins={"1": "OLED_BST_SW", "2": "OLED_VIN"},
          fields={"MPN": "SWPA3015S100MT", "Manufacturer": "Sunlord", "LCSC": "C45403"})

    d.group("13 V boost: TPS61040, rectifier, FB divider", _pad(
            "VOUT = 1.233 V x (1 + 499k / 52.3k) = 13.00 V (0.5 % / 0.1 % divider); CFF C40 33 pF across R26 (tune 22-100 pF).\n"
            "EN tied to OLED_VIN: the input disconnect does the switching.  L 10 uH, Isat 0.92 A (peak need 0.49 A).\n"
            "LAYOUT: tight CIN-L-SW-GND and SW-D-COUT-GND loops; R26/R27/C40 at the FB pin, away from SW.", 150))
    d.add("R27", "Device:R", "52.3k 0.1%", R0402, pins={"1": "GND", "2": "OLED_BST_FB"},
          fields={"MPN": "RT0402BRD0752K3L", "Manufacturer": "YAGEO", "LCSC": "C852832"})
    d.add("R26", "Device:R", "499k 0.5%", R0402, rot=0, pins={"1": "OLED_BST_FB", "2": "+13V_OLED"},
          fields={"MPN": "RC0402DR-07499KL", "Manufacturer": "YAGEO", "LCSC": "C4167968"})
    d.add("U20", "Regulator_Switching:TPS61040DBV", "TPS61040DBVR", "Package_TO_SOT_SMD:SOT-23-5",
          pins={"VIN": "OLED_VIN", "EN": "OLED_VIN", "GND": "GND", "SW": "OLED_BST_SW", "FB": "OLED_BST_FB"},
          datasheet=TPS_DS,
          fields={"MPN": "TPS61040DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C7722"})
    d.add("C40", "Device:C", "33p C0G", C0402, rot=0, pins={"1": "OLED_BST_FB", "2": "+13V_OLED"},
          fields={"MPN": "0402CG330J500NT", "Manufacturer": "FH (Fenghua)", "LCSC": "C1562"})
    d.add("D21", "dial_spinner:B5819W_SOD123", "B5819W", "Diode_SMD:D_SOD-123",
          pins={"A": "OLED_BST_SW", "K": "+13V_OLED"},
          fields={"MPN": "B5819W SL", "Manufacturer": "Jiangsu Changjing (CJ)", "LCSC": "C8598"})
