"""Rev B bench board: the 1.75 in CO5300 AMOLED on an nRF52840-DK, as an Arduino R3 shield.

This is the "panel on an nRF52840-DK through an FH26 breakout" step of issue #5's bench
phase (docs/display-study.md §3, §7.1).  It answers the questions the rev B layout waits
on: bring-up sequence, 1-wire 0x02 framing at 32 MHz, colour modes, TE and partial windows,
current against content and a VBAT sweep from 3.0 to 4.5 V, and the touch I2C voltage.
It is not a rev B board and carries none of the rev B layout decisions.

Panel pinout from the Huaxin H0175Y003AMT003 V0 specification, §4 "Module Interface"
(https://www.displayamoled.com/photo/displayamoled/document/88489/ESHX0175Y003AMT003-SPEC.pdf):
the 31 FPC contacts are numbered there 1-31 with 1 = GND, 2 = TP_INT ... 31 = GND.  QSPI
lanes per its §5.3 application circuit: 16 SDI = D0, 17 DCX = D1, 20 D(0) = D2, 19 D(1) = D3.

CONNECTOR PIN = 32 - PANEL PIN.  Waveshare's ESP32-S3-Touch-AMOLED-1.75 schematic
(https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.75/ESP32-S3-Touch-AMOLED-1.75.pdf,
J3) mates the same tail with an FH26-31S-0.3SHW, and all 31 of its pins match the panel table
under that reversal: TP_INT on 30, TE on 11, the three unused MIPI pairs and MTP_PWR open.
FH26 is bottom-contact; FH26W is its halogen-free version with the same land pattern.

DK pins (Zephyr boards/nordic/nrf52840dk gpio-map) were chosen against SPEC §4's list of
low-frequency-only pins.  Only four of the header pins are full speed: P0.04 (A1), P1.08 (D7),
P0.26 (SDA) and P0.27 (SCL).  The two 32 MHz lines take P1.08 and P0.04 and touch I2C keeps
P0.26/P0.27.  Zephyr's default arduino_spi pins (P1.13-P1.15) are low-frequency pins and are
not used, so the firmware needs its own pinctrl overlay.  The rev B pins docs/display-study.md
§7.1 names are reused where they land on the header: TOUCH_INT P0.28, TOUCH_RST P0.29,
DISP_TE P0.31, DISP_VCI_EN P1.05; reset and the VBAT switch keep rev A's P1.01/P1.02.

The Arduino symbol names A4 and SDA alike (an Uno ties them), but on the DK they are
different GPIOs, P0.30 and P0.26.  Pins are therefore assigned by NUMBER here, never by name.
"""

SHEET = ("bench_display", "bench_display.kicad_sch", "AMOLED bench shield")
TITLE = "dial-me-spinner rev B bench: AMOLED shield for nRF52840-DK"
REV = "1"
DATE = "2026-10-23"
POWER_NETS = ["GND", "VDD_DK", "VBAT_EXT", "VBAT_IN", "DISP_VBAT", "VDD_PANEL", "VCI", "IOVCC",
              "TP_VDD", "TP_VIO"]

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
TP_FP = "TestPoint:TestPoint_Pad_D1.0mm"
FH26_FP = "Connector_FFC-FPC:Hirose_FH26-31S-0.3SHW_2Rows-31Pins-1MP_P0.60mm_Horizontal"

SPEC_DS = "https://www.displayamoled.com/photo/displayamoled/document/88489/ESHX0175Y003AMT003-SPEC.pdf"

R0 = {"MPN": "0402WGF0000TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C17168"}
R4K7 = {"MPN": "0402WGF4701TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25900"}
R10K = {"MPN": "0402WGF1002TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25744"}
R100K = {"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"}
R200K = {"MPN": "0402WGF2003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25764"}
R1M = {"MPN": "0402WGF1004TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C26083"}
C1N = {"MPN": "0402B102K500NT", "Manufacturer": "FH", "LCSC": "C1523"}
C100N = {"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"}
C1U = {"MPN": "CL05A105KA5NQNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C52923"}
C4U7 = {"MPN": "CL21A475KAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1779"}
C10U = {"MPN": "CL10A106MA8NRNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C96446"}

# Panel contact (vendor numbering) -> net.  None = left open.
PANEL_PINS = {
    1: "GND", 2: "TP_INT", 3: "TP_RST_N", 4: "TP_SDA", 5: "TP_SCL", 6: "TP_VDD", 7: "GND",
    8: "IOVCC", 9: "VCI", 10: "DISP_VBAT", 11: "DISP_VCI_EN", 12: "GND",
    13: None,              # MTP_PWR: "must be left open or connected to VSSD in normal condition"
    14: "DISP_RES_N", 15: "DISP_CS_N",
    16: "DISP_SIO0",       # SDI / D0: the only data line the Zephyr chipone,co5300 driver uses
    17: "DISP_SIO1",       # DCX / D1
    18: "DISP_SCK",
    19: "DISP_SIO3",       # D(1) / D3
    20: "DISP_SIO2",       # D(0) / D2
    21: "DISP_TE", 22: "GND",
    23: None, 24: None, 25: "GND", 26: None, 27: None, 28: "GND", 29: None, 30: None,  # MIPI-DSI, unused
    31: "GND",
}

# Arduino_UNO_R3 symbol pin NUMBER -> net.  Comments give the header name and the DK GPIO.
DK_PINS = {
    "15": "DISP_RES_N",    # D0   P1.01  (rev A OLED_RES_N)
    "16": "DISP_VBAT_EN",  # D1   P1.02  (rev A OLED_VCC_EN)
    "17": None,            # D2   P1.03
    "18": None,            # D3   P1.04
    "19": "DISP_VCI_EN",   # D4   P1.05  (rev B pin, study §7.1)
    "20": None,            # D5   P1.06
    "21": None,            # D6   P1.07
    "22": "DISP_SCK_DK",   # D7   P1.08  FULL SPEED
    "23": None,            # D8   P1.10
    "24": None,            # D9   P1.11
    "25": "DISP_CS_N",     # D10  P1.12  (toggles per transaction, not per bit)
    "26": None,            # D11  P1.13  Zephyr's default arduino_spi MOSI: low-frequency, unused
    "27": None,            # D12  P1.14
    "28": None,            # D13  P1.15
    "9": None,             # A0   P0.03
    "10": "DISP_SIO0_DK",  # A1   P0.04  FULL SPEED
    "11": "TP_INT",        # A2   P0.28  (rev B pin)
    "12": "TP_RST_N",      # A3   P0.29  (rev B pin)
    "13": "DISP_SIO1",     # A4   P0.30  read-back only (ID / status at a reduced clock)
    "14": "DISP_TE",       # A5   P0.31  (rev B pin)
    "31": "I2C_SDA",       # SDA  P0.26
    "32": "I2C_SCL",       # SCL  P0.27
    "2": "VDD_DK",         # IOREF = the DK's VDD (3.0 V as shipped)
    "4": "DK_3V3",         # 3V3: strapped to VDD_DK only through R41 (DNP)
    "5": None, "8": None, "1": None, "3": None, "30": None,
    "6": "GND", "7": "GND", "29": "GND",
}


def build(d):
    d.sheet(*SHEET)

    d.group("nRF52840-DK Arduino R3 headers",
            "Pins assigned by symbol pin NUMBER: A4/SDA and A5/SCL are separate GPIOs on the DK.\n"
            "32 MHz lines on the only full-speed header pins: SCK P1.08 (D7), SIO0 P0.04 (A1).\n"
            "Firmware: own pinctrl for SPIM3 (not arduino_spi), high drive (H0H1) on SCK and SIO0.\n"
            "Logic runs at the DK's VDD (3.0 V as shipped): inside CO5300 IOVCC 1.65-3.3 V and VCI 2.4-3.3 V.")
    d.add("J1", "MCU_Module:Arduino_UNO_R3", "nRF52840-DK", "Module:Arduino_UNO_R3",
          pins=DK_PINS, in_bom=False,
          description="Arduino Uno R3 shield headers (hand-fitted stacking headers), nRF52840-DK PCA10056")
    d.add("R41", "Device:R", "0R", R0402, pins={"1": "DK_3V3", "2": "VDD_DK"}, dnp=True, fields=R0,
          description="Fit only if the DK leaves IOREF unconnected")

    d.group("Panel connector (FH26W-31S, connector pin = 32 - panel pin)",
            "Silk marks PANEL PIN 1 at connector pin 31.  Bottom contact: FPC contacts face the board.\n"
            "MTP_PWR (panel 13) open; MIPI pairs (panel 23-24, 26-27, 29-30) open.\n"
            "Decoupling at the connector pins: VBAT 10u + 100n, VCI 4.7u + 100n, IOVCC 1u + 100n, TP_VDD 1u + 100n.")
    d.add("J2", "Connector_Generic_MountingPin:Conn_01x31_MountingPin", "FH26W-31S-0.3SHW(60)", FH26_FP,
          pins={**{str(32 - p): n for p, n in PANEL_PINS.items()}, "MP": "GND"},
          datasheet=SPEC_DS,
          fields={"MPN": "FH26W-31S-0.3SHW(60)", "Manufacturer": "HIROSE", "LCSC": "C2973806"})
    d.add("C1", "Device:C", "10u", C0603, pins={"1": "DISP_VBAT", "2": "GND"}, fields=C10U)
    d.add("C2", "Device:C", "100n", C0402, pins={"1": "DISP_VBAT", "2": "GND"}, fields=C100N)
    d.add("C3", "Device:C", "4.7u", C0805, pins={"1": "VCI", "2": "GND"}, fields=C4U7)
    d.add("C4", "Device:C", "100n", C0402, pins={"1": "VCI", "2": "GND"}, fields=C100N)
    d.add("C5", "Device:C", "1u", C0402, pins={"1": "IOVCC", "2": "GND"}, fields=C1U)
    d.add("C6", "Device:C", "100n", C0402, pins={"1": "IOVCC", "2": "GND"}, fields=C100N)
    d.add("C7", "Device:C", "1u", C0402, pins={"1": "TP_VDD", "2": "GND"}, fields=C1U)
    d.add("C8", "Device:C", "100n", C0402, pins={"1": "TP_VDD", "2": "GND"}, fields=C100N)

    d.group("Panel VBAT: external source or DK VDD, through the rev B load switch",
            "J3 takes a PPK2 in source-meter mode for the 3.0-4.5 V sweep and the current-vs-content runs.\n"
            "J4 selects VBAT_IN: 1-2 = J3 (external), 2-3 = DK VDD (3.0 V, below the pin table's 3.7 V minimum).\n"
            "U1 is the TPS22917 rev B keeps (U21, renamed DISP_VBAT_EN): same CT and QOD wiring as rev A.\n"
            "R1 (DNP) bypasses U1 to rule it out.")
    d.add("J3", "Connector_Generic:Conn_01x02", "VBAT EXT", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
          pins={"1": "VBAT_EXT", "2": "GND"}, in_bom=False)
    d.add("J4", "Connector_Generic:Conn_01x03", "VBAT SEL", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
          pins={"1": "VBAT_EXT", "2": "VBAT_IN", "3": "VDD_DK"}, in_bom=False)
    d.add("U1", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "VBAT_IN", "GND": "GND", "ON": "DISP_VBAT_EN", "CT": "DISP_LSW_CT",
                "QOD": "DISP_VBAT", "VOUT": "DISP_VBAT"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    d.add("C9", "Device:C", "1n", C0402, pins={"1": "DISP_LSW_CT", "2": "VBAT_IN"}, fields=C1N)
    d.add("C10", "Device:C", "10u", C0603, pins={"1": "VBAT_IN", "2": "GND"}, fields=C10U,
          description="U1 VIN bypass")
    d.add("R2", "Device:R", "100k", R0402, pins={"1": "DISP_VBAT_EN", "2": "GND"}, fields=R100K)
    d.add("R1", "Device:R", "0R", R0402, pins={"1": "VBAT_IN", "2": "DISP_VBAT"}, dnp=True, fields=R0)

    d.group("Panel logic rails from DK VDD, each separable",
            "J5 shunt carries VCI + IOVCC + TP_VDD: remove it and put a PPK2 (ammeter) across to log the logic current.\n"
            "R3-R5 split the three rails so any one can be fed or measured on its own.")
    d.add("J5", "Connector_Generic:Conn_01x02", "IDD LOGIC", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
          pins={"1": "VDD_DK", "2": "VDD_PANEL"}, in_bom=False)
    d.add("R3", "Device:R", "0R", R0402, pins={"1": "VDD_PANEL", "2": "VCI"}, fields=R0)
    d.add("R4", "Device:R", "0R", R0402, pins={"1": "VDD_PANEL", "2": "IOVCC"}, fields=R0)
    d.add("R5", "Device:R", "0R", R0402, pins={"1": "VDD_PANEL", "2": "TP_VDD"}, fields=R0)

    d.group("Display control and the 32 MHz lines",
            "R6/R7 0R at the header: swap for 22-33R if the SCK/SIO0 edges ring (CO5300 needs <= 3.5 ns 20-80 %).\n"
            "TP1-TP4 + TP5/TP6 GND beside the connector for the scope: probe at the panel end, with a spring ground.\n"
            "DISP_RES_N 1M pull-down and DISP_VCI_EN 100k pull-down hold the panel off while the DK resets.\n"
            "SIO1 (DCX) reads back on A4, a low-frequency pin: read ID/status at a reduced clock only.\n"
            "SIO2/SIO3 are unused by the single-lane driver: 10k pull-downs, TP7/TP8 for a later QSPI test.")
    d.add("R6", "Device:R", "0R", R0402, pins={"1": "DISP_SCK_DK", "2": "DISP_SCK"}, fields=R0)
    d.add("R7", "Device:R", "0R", R0402, pins={"1": "DISP_SIO0_DK", "2": "DISP_SIO0"}, fields=R0)
    d.add("R8", "Device:R", "1M", R0402, pins={"1": "DISP_RES_N", "2": "GND"}, fields=R1M)
    d.add("R9", "Device:R", "100k", R0402, pins={"1": "DISP_VCI_EN", "2": "GND"}, fields=R100K)
    d.add("R10", "Device:R", "100k", R0402, pins={"1": "IOVCC", "2": "DISP_CS_N"}, fields=R100K)
    d.add("R11", "Device:R", "100k", R0402, pins={"1": "DISP_SIO1", "2": "GND"}, fields=R100K)
    d.add("R12", "Device:R", "10k", R0402, pins={"1": "DISP_SIO2", "2": "GND"}, fields=R10K)
    d.add("R13", "Device:R", "10k", R0402, pins={"1": "DISP_SIO3", "2": "GND"}, fields=R10K)
    for ref, net in (("TP1", "DISP_SCK"), ("TP2", "DISP_SIO0"), ("TP3", "DISP_CS_N"), ("TP4", "DISP_TE"),
                     ("TP5", "GND"), ("TP6", "GND"), ("TP7", "DISP_SIO2"), ("TP8", "DISP_SIO3")):
        d.add(ref, "Connector:TestPoint", net, TP_FP, pins={"1": net}, in_bom=False)

    d.group("Touch I2C: direct at DK VDD, or level-shifted to 1.8 V",
            "Fitted: R14/R15 0R tie the touch bus straight to P0.26/P0.27 at 3.0 V (Waveshare runs it at 3.3 V).\n"
            "1.8 V option (the Huaxin/Viewe drawings): remove R14/R15/R16, fit U2, U3, C11, C12, R17, R18, R19.\n"
            "In 1.8 V mode TP_INT and TP_RST_N are NOT shifted: TP_INT at 1.8 V is below the nRF's 0.7 VDD = 2.1 V\n"
            "VIH, and the nRF would drive TP_RST_N to 3.0 V.  That mode answers 'does the bus work', not 'is it done'.")
    d.add("R14", "Device:R", "0R", R0402, pins={"1": "TP_SDA", "2": "I2C_SDA"}, fields=R0)
    d.add("R15", "Device:R", "0R", R0402, pins={"1": "TP_SCL", "2": "I2C_SCL"}, fields=R0)
    d.add("R16", "Device:R", "0R", R0402, pins={"1": "VDD_PANEL", "2": "TP_VIO"}, fields=R0)
    d.add("R20", "Device:R", "4.7k", R0402, pins={"1": "VDD_DK", "2": "I2C_SDA"}, fields=R4K7)
    d.add("R21", "Device:R", "4.7k", R0402, pins={"1": "VDD_DK", "2": "I2C_SCL"}, fields=R4K7)
    d.add("R22", "Device:R", "100k", R0402, pins={"1": "TP_VIO", "2": "TP_INT"}, fields=R100K)
    d.add("R23", "Device:R", "100k", R0402, pins={"1": "TP_VIO", "2": "TP_RST_N"}, fields=R100K)
    d.add("U2", "Interface:PCA9306DC", "PCA9306DCUR", "Package_SO:VSSOP-8_2.3x2mm_P0.5mm",
          pins={"VREF1": "TP_VIO", "VREF2": "PCA_EN", "EN": "PCA_EN", "GND": "GND",
                "SCL1": "TP_SCL", "SDA1": "TP_SDA", "SCL2": "I2C_SCL", "SDA2": "I2C_SDA"},
          dnp=True, fields={"MPN": "PCA9306DCUR", "Manufacturer": "Texas Instruments", "LCSC": "C33196"})
    d.add("R17", "Device:R", "200k", R0402, pins={"1": "VDD_DK", "2": "PCA_EN"}, dnp=True, fields=R200K,
          description="PCA9306 VREF2/EN bias (datasheet: 200k to the high-side supply)")
    d.add("R18", "Device:R", "4.7k", R0402, pins={"1": "TP_VIO", "2": "TP_SDA"}, dnp=True, fields=R4K7)
    d.add("R19", "Device:R", "4.7k", R0402, pins={"1": "TP_VIO", "2": "TP_SCL"}, dnp=True, fields=R4K7)
    d.add("U3", "Regulator_Linear:AP2112K-1.8", "AP2112K-1.8TRG1", "Package_TO_SOT_SMD:SOT-23-5",
          pins={"VIN": "VDD_PANEL", "EN": "VDD_PANEL", "GND": "GND", "NC": None, "VOUT": "TP_VIO"},
          dnp=True, fields={"MPN": "AP2112K-1.8TRG1", "Manufacturer": "Diodes Incorporated", "LCSC": "C176944"})
    d.add("C11", "Device:C", "1u", C0402, pins={"1": "VDD_PANEL", "2": "GND"}, dnp=True, fields=C1U)
    d.add("C12", "Device:C", "1u", C0402, pins={"1": "TP_VIO", "2": "GND"}, dnp=True, fields=C1U)

    d.group("ERC power flags",
            "Every rail here arrives from a header or through a jumper / 0R link, which ERC cannot see as a source.")
    # Not TP_VIO: U3 VOUT drives it, fitted or not.  VDD_DK is #FLG09, waived against J1 IOREF in build.py.
    for i, net in enumerate(("GND", "VBAT_EXT", "VBAT_IN", "VDD_PANEL", "VCI", "IOVCC", "TP_VDD", "PCA_EN",
                             "VDD_DK"), 1):
        d.add(f"#FLG{i:02d}", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": net}, in_bom=False, on_board=False)
