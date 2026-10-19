"""Main board: 48x WS2812C-2020-V6 RGB ring on VLED, data chain + per-LED decoupling. See SPEC.md §5.4.

Pinout check (WS2812C-2020-V6 datasheet p.2 pin table + p.5 application circuit, and the
WS2812B-2020-V6 drop-in datasheet p.2): 1 = DO, 2 = GND, 3 = DI, 4 = VDD.
KiCad stock symbol LED:WS2812B-2020: 1 DOUT, 2 VSS, 3 DIN, 4 VDD -> same numbering.
KiCad stock footprint LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm: pads 1 (-0.915,-0.55),
2 (-0.915,+0.55), 3 (+0.915,+0.55), 4 (+0.915,-0.55), 0.7x0.7 mm, 1.10 mm row pitch,
1.13 mm column gap. That is the datasheet land pattern rotated 180 deg (datasheet top view:
DI/VDD in one column, GND/DO in the other, DO-VDD and DI-GND on the same rows), and the fab
polarity bar sits next to the DO/GND column like the datasheet's back-side polarity strip.
=> stock symbol + stock footprint are correct; no custom symbol/footprint needed.

Reference designators: D101-D148 (LEDs), C101-C148 (one 100 nF per LED, same index),
R40-R42, TP40 (reserved block for this sheet).
Chain nets: LED_DIN -> D101.DIN; LED_Dk = DOUT of pixel k (D(100+k)) = DIN of D(101+k);
LED_D48 = D148.DOUT (chain end: TP40 + 100k pull-down).
"""

SHEET = ("leds", "leds.kicad_sch", "LED ring")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
LED_FP = "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm"
LED_DS = "https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf"
LED_DESC = ("Worldsemi WS2812C-2020-V6 addressable RGB LED, 5 mA/ch, VDD 3.3-5.3 V, "
            "SMD2020-4P (1 DO, 2 GND, 3 DI, 4 VDD)")

N_LEDS = 48
PER_GROUP = 12

LED_FIELDS = {"MPN": "WS2812C-2020-V6", "Manufacturer": "Worldsemi", "LCSC": "C55109522"}
CAP_100N = {"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"}
RES_220R = {"MPN": "0402WGF2200TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25091"}
RES_100K = {"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"}


def din_net(i):
    """Net on the DIN of LED number i (1-based)."""
    return "LED_DIN" if i == 1 else f"LED_D{i - 1}"


def dout_net(i):
    """Net on the DOUT of LED number i (1-based); LED_D48 is the chain end."""
    return f"LED_D{i}"


def build(d):
    s = d.sheet(*SHEET)
    s.notes.append(
        "48x WS2812C-2020-V6 (5 mA/ch) on VLED = TPS22917 load-switch output (main_power sheet, 2x 22 uF bulk there).\n"
        "Data: nRF P0.06 (I2S SDOUT) = LED_DIN_MCU -> R40 220R -> LED_DIN -> D101 -> LED_D1 -> D102 -> ... -> D148 -> LED_D48 (TP40).\n"
        "D101 = pixel 0 at the mechanical index; pixels run in chain order around the ring. 3.3 V logic; DNP SN74LV1T34 option (U43/R43) if the margin is short.\n"
        "WS2812B-2020-V6 (C52917434, 12 mA/ch) is a footprint/pinout drop-in; firmware must then cap peak current."
    )

    d.group("LED data input",
            "220R series (bounds DIN clamp current if P0.06 is high while VLED is off): place within 3 mm of the nRF pin (P0.06).\n"
            "100k pull-down at D101.DIN holds DIN low while P0.06 is\n"
            "high-Z (reset/DFU). FIRMWARE: send an all-zero frame and\n"
            "drive P0.06 low (pinctrl sleep) before deasserting\n"
            "LED_PWR_EN. Never drive LED_DIN_MCU high while VLED is off:\n"
            "QOD holds VLED at 0 V and VI max = VDD + 0.7 V, so DIN\n"
            "would back-power the ring through its ESD diode.")
    d.add("R40", "Device:R", "220", R0402, pins={"1": "LED_DIN_MCU", "2": "LED_DIN_R"}, fields=RES_220R)
    d.add("R41", "Device:R", "100k", R0402, pins={"1": "LED_DIN", "2": "GND"}, fields=RES_100K)

    d.group("Optional VLED-referenced level shifter (DNP)",
            "Default: R43 0R fitted, U43 not fitted (3.3 V drive; margin 0.1-0.2 V at VSYS 4.5 V on USB).\n"
            "If the bench test at VSYS = 4.6 V shows bit errors: remove R43, fit U43 (powered from VLED,\n"
            "so it is unpowered whenever the ring is off) and C43.")
    d.add("R43", "Device:R", "0", R0402, pins={"1": "LED_DIN_R", "2": "LED_DIN"},
          fields={"MPN": "0402WGF0000TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C17168"})
    d.add("U43", "74xGxx:74LVC1G34", "SN74LV1T34DBVR", "Package_TO_SOT_SMD:SOT-23-5",
          pins={"1": None, "2": "LED_DIN_R", "3": "GND", "4": "LED_DIN", "5": "VLED"}, dnp=True,
          fields={"MPN": "SN74LV1T34DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C100024"},
          datasheet="https://www.ti.com/lit/ds/symlink/sn74lv1t34.pdf",
          description="Single buffer, 1.8-5.5 V, TTL-level input (level-up translator), DNP option")
    d.add("C43", "Device:C", "100n", C0402, pins={"1": "VLED", "2": "GND"}, fields=CAP_100N, dnp=True)

    for g0 in range(1, N_LEDS + 1, PER_GROUP):
        g1 = g0 + PER_GROUP - 1
        d.group(f"LED ring D{100 + g0}-D{100 + g1} (pixels {g0 - 1}-{g1 - 1})",
                f"chain DOUT -> next DIN; C{100 + g0}-C{100 + g1}: one 100 nF 0402 per LED,\n"
                "<= 1 mm from its VDD pad, sharing the VDD/GND vias")
        for i in range(g0, g1 + 1):
            # Each LED's own decoupling cap sits just left of it, drawn vertical like the LED rails.
            d.add(f"C{100 + i}", "Device:C", "100n", C0402, pins={"1": "VLED", "2": "GND"},
                  fields=CAP_100N, rot=0)
            # Pin names map to verified numbers: DIN = 3, DOUT = 1, VDD = 4, VSS (GND) = 2.
            d.add(f"D{100 + i}", "LED:WS2812B-2020", "WS2812C-2020-V6", LED_FP,
                  pins={"DIN": din_net(i), "DOUT": dout_net(i), "VDD": "VLED", "VSS": "GND"},
                  fields=LED_FIELDS, datasheet=LED_DS, description=LED_DESC)

    d.group("Chain end: D148.DOUT = LED_D48",
            "Test pad + 100k pull-down. V6 DI/DO are\n"
            "swappable, so DOUT must not float.\n"
            "Never loop LED_D48 back to D101.")
    end = dout_net(N_LEDS)
    d.add("TP40", "Connector:TestPoint", end, "TestPoint:TestPoint_Pad_D1.0mm",
          pins={"1": end}, in_bom=False)
    d.add("R42", "Device:R", "100k", R0402, pins={"1": end, "2": "GND"}, fields=RES_100K)
