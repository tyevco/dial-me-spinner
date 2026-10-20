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
        datasheet="https://www.richtek.com/assets/product_file/RT9080/DS9080-09.pdf",
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
            "JST SH 12-way SIDE-entry on the bottom at r = 19.5, θ 330° (a vertical header would hit the rotor hub);\n"
            "the harness lies flat under the board into the spindle bore. Identical pinout on the base board (SPEC §2)")
    d.add("J1", "Connector_Generic_MountingPin:Conn_01x12_MountingPin", "LINK",
          "Connector_JST:JST_SH_SM12B-SRSS-TB_1x12-1MP_P1.00mm_Horizontal",
          pins={**{str(k): v for k, v in LINK_PINOUT.items()}, "MP": "GND"},
          fields={"MPN": "SM12B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160411"})
    d.add("C1", "Device:C", "22u", C0805, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C45783"})

    d.group("3V3 always-on LDO", "nRF VDD+VDDH, flash, sensors, OLED logic; Iq 2 uA")
    d.add("U1", "dial_spinner:RT9080-33GJ5", "RT9080-33GJ5", "Package_TO_SOT_SMD:SOT-23-5",
          pins={"VIN": "VSYS", "EN": "VSYS", "GND": "GND", "VOUT": "+3V3", "NC": None},
          fields={"MPN": "RT9080-33GJ5", "Manufacturer": "Richtek", "LCSC": "C841192"})
    # VSYS caps are 25 V parts: a 10 V 0603 keeps only ~28 % at 5 V, and VSYS must absorb the stepper's coast energy
    # on USB with the BATFET off (hardware/sim test_motor_drive, MD-5)
    d.add("C2", "Device:C", "10u/25V", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106MA8NRNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C96446"})
    d.add("C3", "Device:C", "10u", C0603, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL10A106KP8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19702"})
    d.add("C4", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})

    d.group("VSYS sense", "2.2M/1M always-on divider (~1.3 uA) into AIN0; 100 nF holds the sample")
    d.add("R1", "Device:R", "2.2M", R0402, pins={"1": "VSYS", "2": "VSYS_SENSE"},
          fields={"MPN": "0402WGF2204TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C11490"})
    d.add("R2", "Device:R", "1M", R0402, pins={"1": "VSYS_SENSE", "2": "GND"},
          fields={"MPN": "0402WGF1004TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C26083"})
    d.add("C5", "Device:C", "100n", C0402, pins={"1": "VSYS_SENSE", "2": "GND"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})

    d.group("LED rail load switch", "VSYS -> VLED; CT 1 nF to VIN (TPS22917 pin table) ~4 ms rise; QOD discharge through R4")
    d.add("U2", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "VSYS", "GND": "GND", "ON": "LED_PWR_EN", "CT": "LSW_CT", "QOD": "LSW_QOD", "VOUT": "VLED"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    d.add("C6", "Device:C", "10u/25V", C0603, pins={"1": "VSYS", "2": "GND"},
          fields={"MPN": "CL10A106MA8NRNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C96446"})
    d.add("C7", "Device:C", "1n/50V", C0402, pins={"1": "LSW_CT", "2": "VSYS"},
          fields={"MPN": "0402B102K500NT", "Manufacturer": "FH", "LCSC": "C1523"})
    d.add("R3", "Device:R", "100k", R0402, pins={"1": "LED_PWR_EN", "2": "GND"},
          fields={"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"})
    d.add("R4", "Device:R", "68", R0402, pins={"1": "VLED", "2": "LSW_QOD"},
          fields={"MPN": "RC0402FR-0768RL", "Manufacturer": "YAGEO", "LCSC": "C163455"},
          description="QOD discharge resistor (TPS22917 option 1: external R between VOUT and QOD); VLED to 10 % "
                      "in about 24 ms (26.6 ms worst corner, C8/C9 +20 %, DC bias), inside the firmware's 30 ms "
                      "(hardware/sim test_u2_qod_discharge_tolerance_extremes)")
    d.add("C8", "Device:C", "22u", C0805, pins={"1": "VLED", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C45783"})
    d.add("C9", "Device:C", "22u", C0805, pins={"1": "VLED", "2": "GND"},
          fields={"MPN": "CL21A226MAQNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C45783"})

    d.group("Spindle clamp holes (GND)",
            "Plated M2 holes for the stainless spindle flange: grounds spindle -> 608 races -> ring, giving the\n"
            "touchable 316L flywheel an ESD bleed path instead of arcing to the encoder (review SCH-2).\n"
            "Bond the ring to the bearing outer race with conductive epoxy (docs/mechanical.md).")
    for i in range(1, 4):
        d.add(f"H{i}", "Mechanical:MountingHole_Pad", "SPINDLE_M2", "MountingHole:MountingHole_2.2mm_M2_Pad_Via",
              pins={"1": "GND"}, in_bom=False)

    d.group("Power flags", "VSYS, VBUS and GND enter this board only through the passive link connector J1")
    for i, net in enumerate(["VSYS", "VBUS", "GND"], start=1):
        d.add(f"#FLG0{i}", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": net}, in_bom=False, on_board=False)

    d.group("Test points")
    for i, net in enumerate(["VSYS", "+3V3", "VLED", "GND"], start=1):
        d.add(f"TP{i}", "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
              pins={"1": net}, in_bom=False)
