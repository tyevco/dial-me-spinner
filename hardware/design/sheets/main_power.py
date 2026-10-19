"""Main board: board-to-board link, 3V3 LDO, LED rail load switch, VSYS sense. See SPEC.md §3, §5.1."""

from nets import LINK_PINOUT

SHEET = ("main_power", "main_power.kicad_sch", "Power & link")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"

SYMBOLS = [
    dict(
        name="RT9080-33GJ5",
        ref="U",
        footprint="Package_TO_SOT_SMD:SOT-23-5",
        datasheet="https://www.richtek.com/assets/product_file/RT9080/DS9080-07.pdf",
        description="600 mA, 2 uA Iq low-dropout regulator, 3.3 V fixed",
        pins=[
            (1, "VIN", "power_in", "L"),
            (3, "EN", "input", "L"),
            (2, "GND", "power_in", "B"),
            (5, "VOUT", "power_out", "R"),
            (4, "NC", "no_connect", "R"),
        ],
    ),
]


def build(d):
    d.sheet(*SHEET)

    d.group("Board-to-board link (to base board through the spindle)",
            "JST SH 12-way vertical; identical pinout on the base board (SPEC §2)")
    d.add("J1", "Connector_Generic_MountingPin:Conn_01x12_MountingPin", "LINK",
          "Connector_JST:JST_SH_BM12B-SRSS-TB_1x12-1MP_P1.00mm_Vertical",
          pins={**{str(k): v for k, v in LINK_PINOUT.items()}, "MP": "GND"},
          fields={"MPN": "BM12B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160413"})
    d.add("C1", "Device:C", "22u", C0805, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "LCSC": "C45783"})

    d.group("3V3 always-on LDO", "nRF VDD+VDDH, flash, sensors, OLED logic; Iq 2 uA")
    d.add("U1", "dial_spinner:RT9080-33GJ5", "RT9080-33GJ5", "Package_TO_SOT_SMD:SOT-23-5",
          pins={"VIN": "VSYS", "EN": "VSYS", "GND": "GND", "VOUT": "+3V3", "NC": None},
          fields={"MPN": "RT9080-33GJ5", "Manufacturer": "Richtek", "LCSC": "C841192"})
    d.add("C2", "Device:C", "10u", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106KP8NNNC", "LCSC": "C19702"})
    d.add("C3", "Device:C", "10u", C0603, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL10A106KP8NNNC", "LCSC": "C19702"})
    d.add("C4", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "LCSC": "C1525"})

    d.group("VSYS sense", "2.2M/1M always-on divider (~1.3 uA) into AIN0; 100 nF holds the sample")
    d.add("R1", "Device:R", "2.2M", R0402, pins={"1": "VSYS", "2": "VSYS_SENSE"},
          fields={"MPN": "0402WGF2204TCE", "LCSC": "C22935"})
    d.add("R2", "Device:R", "1M", R0402, pins={"1": "VSYS_SENSE", "2": "GND"},
          fields={"MPN": "0402WGF1004TCE", "LCSC": "C26083"})
    d.add("C5", "Device:C", "100n", C0402, pins={"1": "VSYS_SENSE", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "LCSC": "C1525"})

    d.group("LED rail load switch", "VSYS -> VLED, ~2 ms soft start (CT 1 nF), QOD discharge")
    d.add("U2", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "VSYS", "GND": "GND", "ON": "LED_PWR_EN", "CT": "LSW_CT", "QOD": "VLED", "VOUT": "VLED"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    d.add("C6", "Device:C", "10u", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106KP8NNNC", "LCSC": "C19702"})
    d.add("C7", "Device:C", "1n/50V", C0402, pins={"1": "LSW_CT", "2": "GND"},
          fields={"MPN": "0402B102K500NT", "LCSC": "C1523"})
    d.add("R3", "Device:R", "100k", R0402, pins={"1": "LED_PWR_EN", "2": "GND"},
          fields={"MPN": "0402WGF1003TCE", "LCSC": "C25741"})
    d.add("C8", "Device:C", "22u", C0805, pins={"1": "VLED", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "LCSC": "C45783"})
    d.add("C9", "Device:C", "22u", C0805, pins={"1": "VLED", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "LCSC": "C45783"})

    d.group("Test points")
    for i, net in enumerate(["VSYS", "+3V3", "VLED", "GND"], start=1):
        d.add(f"TP{i}", "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
              pins={"1": net}, in_bom=False)
