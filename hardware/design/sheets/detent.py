"""Main board: detent actuator driver (2x DRV8837), motor connector, home Hall switch. See SPEC.md §5.6.

Pinouts verified against the TI datasheets (pin number = footprint pad number):
  DRV8837DSGR  (SLVSBA4F Apr 2021, Fig. 5-1 + Pin Functions table, DSG0008A package drawing):
      1 VM, 2 OUT1, 3 OUT2, 4 GND, 5 IN2, 6 IN1, 7 nSLEEP, 8 VCC, 9 = exposed thermal pad (to GND).
      Same numbering as the stock Driver_Motor:DRV8837 symbol; a custom box symbol is used only so
      that the VM and VCC rails do not sit 2.54 mm apart on the same edge (their labels overlapped).
      Footprint Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm: pads 1-4 left column
      top->bottom, 5-8 right column bottom->top, pad 9 = EP 0.9x1.6 mm (matches DSG0008A).
  DRV5032FADBZR (SLVSDC7H Dec 2024, Fig. 5-1 + Table 5-1, DBZ0003A package drawing):
      SOT-23 (FA/FB/FC/AJ/ZE): 1 VCC, 2 OUT, 3 GND. Package_TO_SOT_SMD:SOT-23 (TO-236) has pads 1/2
      on one side, 3 opposite, as DBZ0003A. Push-pull output, LOW when |B| > BOP (magnet present).
"""

SHEET = ("detent", "detent.kicad_sch", "Detent actuator & home sensor")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
WSON8 = "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
JST_SH4 = "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal"

DRV8837 = {"MPN": "DRV8837DSGR", "Manufacturer": "Texas Instruments", "LCSC": "C39159"}
C100N = {"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"}
C10U = {"MPN": "CL21A106KAYNNNE", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C15850"}
R100K = {"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"}

SYMBOLS = [
    dict(
        name="DRV8837DSGR",
        ref="U",
        footprint=WSON8,
        datasheet="https://www.ti.com/lit/ds/symlink/drv8837.pdf",
        description="1.8 A low-voltage brushed DC / stepper-coil H-bridge, IN/IN interface, nSLEEP, WSON-8 2x2 (DSG)",
        keywords="H-bridge motor driver",
        pins=[
            (1, "VM", "power_in", "T"),
            (8, "VCC", "power_in", "L"),
            (6, "IN1", "input", "L"),
            (5, "IN2", "input", "L"),
            (7, "nSLEEP", "input", "L"),
            (2, "OUT1", "output", "R"),
            (3, "OUT2", "output", "R"),
            (4, "GND", "power_in", "B"),
            (9, "GND", "passive", "B"),   # exposed thermal pad, stacked hidden on GND
        ],
    ),
    dict(
        name="DRV5032FADBZR",
        ref="U",
        footprint=SOT23,
        datasheet="https://www.ti.com/lit/ds/symlink/drv5032.pdf",
        description="Ultra-low-power omnipolar Hall switch, push-pull, BOP 4.8 mT max, 20 Hz, SOT-23 (DBZ)",
        keywords="hall switch omnipolar magnetic",
        pins=[
            (1, "VCC", "power_in", "L"),
            (3, "GND", "power_in", "L"),
            (2, "OUT", "output", "R"),
        ],
    ),
]


def _driver(d, ref, coil, c_vm, c_vcc):
    """One DRV8837 H-bridge per stepper coil, with its local VM and VCC bypass caps."""
    d.add(ref, "dial_spinner:DRV8837DSGR", "DRV8837DSGR", WSON8,
          pins={"1": "VSYS", "8": "+3V3", "7": "MOT_NSLEEP",
                "6": f"MOT_{coil}_IN1", "5": f"MOT_{coil}_IN2",
                "2": f"MOT_{coil}_OUT1", "3": f"MOT_{coil}_OUT2",
                "4": "GND", "9": "GND"},
          fields=DRV8837)
    # VCC cap laid horizontally, VM cap upright at the row end: keeps rail texts and ref/value apart
    d.add(c_vcc, "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"}, fields=C100N)
    d.add(c_vm, "Device:C", "100n", C0402, pins={"1": "VSYS", "2": "GND"}, fields=C100N, rot=0)


def build(d):
    d.sheet(*SHEET)

    d.group("Coil A driver - DRV8837 #1",
            "IN1/IN2: 00 coast, 10 fwd, 01 rev, 11 brake\n"
            "VM = VSYS (3.0-4.5 V), VCC = +3V3\n"
            "Pin 4 + EP (pad 9) to the GND plane\n"
            "100 nF at the VM pin and at the VCC pin\n"
            "U40/U41 + caps: TOP side in theta 60-120, or\n"
            "BOTTOM only outside theta 60-120 (keep-out)")
    _driver(d, "U40", "A", "C70", "C71")

    d.group("Coil B driver - DRV8837 #2",
            "Same as #1. A 2-wire DC gearmotor uses\n"
            "coil A only (U40, J40 pins 1-2); U41 then\n"
            "idles with IN1/IN2 low")
    _driver(d, "U41", "B", "C72", "C73")

    d.group("Shared VM bulk + nSLEEP pull-down",
            "10 uF/25 V 0805 placed between the two VM pins\n"
            "nSLEEP: 100k ext. pull-down (SPEC §4) in\n"
            "parallel with the 100k internal one in each DRV\n"
            "Sleep: IVM+IVCC <= 2x(95+25) nA = 0.24 uA max")
    d.add("R70", "Device:R", "100k", R0402, pins={"1": "MOT_NSLEEP", "2": "GND"}, fields=R100K)
    d.add("C74", "Device:C", "10u/25V", C0805, pins={"1": "VSYS", "2": "GND"}, fields=C10U, rot=0)

    d.group("Motor connector (JST SH 4-way)",
            "Side entry SM04B, ~2.9 mm tall: the lead\n"
            "runs in-plane to the radial actuator\n"
            "Bottom side: just outside the theta 60-120\n"
            "keep-out, r < 27, entry facing the actuator\n"
            "1 A+, 2 A-, 3 B+, 4 B-\n"
            "2-wire DC gearmotor: pins 1-2 only\n"
            "MP solder tabs to GND")
    d.add("J40", "Connector_Generic_MountingPin:Conn_01x04_MountingPin", "MOTOR", JST_SH4,
          pins={"1": "MOT_A_OUT1", "2": "MOT_A_OUT2", "3": "MOT_B_OUT1", "4": "MOT_B_OUT2", "MP": "GND"},
          fields={"MPN": "SM04B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160404"})

    d.group("Home (park) Hall switch",
            "DRV5032FA omnipolar push-pull, always on\n"
            "(+3V3, 1.6 uA typ avg). HOME_N low = detent\n"
            "magnet parked (free mode); no pull-up needed\n"
            "TOP side only, above park pos. r 21.5, theta 90\n"
            "(bottom = keep-out, 0.5 mm to the magnet)")
    d.add("C75", "Device:C", "100n", C0402, pins={"1": "+3V3", "2": "GND"}, fields=C100N, rot=0)
    d.add("U42", "dial_spinner:DRV5032FADBZR", "DRV5032FADBZR", SOT23,
          pins={"VCC": "+3V3", "OUT": "HOME_N", "GND": "GND"},
          fields={"MPN": "DRV5032FADBZR", "Manufacturer": "Texas Instruments", "LCSC": "C140921"})
