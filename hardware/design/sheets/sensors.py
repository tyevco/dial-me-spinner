"""Main board: TMAG5273 encoder, LIS2DW12 IMU, I2C/link pull-ups, piezo sounder. See SPEC.md §4, §5.5.

Pinouts checked against the primary datasheets:
  * TMAG5273 (TI SLYS045C, Apr 2026), Fig 4-1 / Table 4-1, DBV SOT-23-6 top view:
        1 SCL, 2 GND, 3 GND (TEST), 4 VCC, 5 INT, 6 SDA.
    KiCad Package_TO_SOT_SMD:SOT-23-6 pads 1-3 run down the left side and 4-6 up the right side.
    That is the same counter-clockwise order as the DBV package, so symbol pin n = pad n.
    Sensor location (SLYS045C section 6.3.2, Fig 6-2): the X/Y/Z Hall elements are 1.85 mm from the pin-1
    end of the 2.9 mm body, 0.68 mm from the pin 1-3 edge of the 1.6 mm body, and 0.73 mm below the top.
    In KiCad SOT-23-6 coordinates (top view, origin at the body centre, pin 1 at -x/-y) that is
    (-0.12, +0.40) mm. Fig 6-1 puts sensor X across the body and Y along the long axis.
    Layout: long axis radial, and the Hall element (not the footprint origin) on R_t = 29.0 mm. So the
    footprint origin goes at r = 28.6 mm if the pin-3/4 end faces outward, or r = 29.4 mm if it faces inward.
  * LIS2DW12 (ST DS11811 Rev 8), Table 1 + Fig 6 (top view):
        1 SCL/SPC, 2 CS, 3 SDO/SA0, 4 SDA/SDI/SDO, 5 NC, 6 GND, 7 RES, 8 GND, 9 VDD, 10 VDD_IO, 11 INT2, 12 INT1.
    Fig 6 (top view) has 1-4 down the left side, 5-6 along the bottom, 7-10 up the right side and 12, 11
    along the top. KiCad Package_LGA:LGA-12_2x2mm_P0.5mm has the same pad order, so symbol pin n = pad n.
  * Murata PKMCS0909E4000-R1 (flyer VPPT-BUZJ083-D): body 9.0 x 9.0 x 1.9 max. The recommended land
    pattern is 10.0 mm outer, 7.4 mm inner, 3.4 mm tall, i.e. two 1.3 x 3.4 pads at x = +/-4.35 mm.
    The part is a non-polar piezo element, so pad 1 = BZ+ and pad 2 = BZ- only follow the SPEC naming.
"""

SHEET = ("sensors", "sensors.kicad_sch", "Sensors & sounder")

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

PIEZO_FP = "Buzzer_Murata_PKMCS0909E4000-R1"

TMAG_DS = "https://www.ti.com/lit/ds/symlink/tmag5273.pdf"
LIS_DS = "https://www.st.com/resource/en/datasheet/lis2dw12.pdf"
PIEZO_DS = "https://www.murata.com/en-us/products/productdetail?partno=PKMCS0909E4000-R1"

SYMBOLS = [
    dict(
        name="TMAG5273",
        ref="U",
        footprint="Package_TO_SOT_SMD:SOT-23-6",
        datasheet=TMAG_DS,
        description="Low-power linear 3D Hall-effect sensor, I2C, 1.7-3.6 V, SOT-23-6 (DBV)",
        keywords="hall magnetic 3D sensor I2C TI",
        pins=[
            (4, "VCC", "power_in", "T"),
            (1, "SCL", "input", "L"),
            (6, "SDA", "bidirectional", "L"),
            (5, "INT", "open_collector", "L"),
            (2, "GND", "power_in", "B"),
            (3, "TEST", "input", "R"),     # datasheet name "GND (TEST)": connect to ground
        ],
    ),
    dict(
        name="LIS2DW12",
        ref="U",
        footprint="Package_LGA:LGA-12_2x2mm_P0.5mm",
        datasheet=LIS_DS,
        description="Ultra-low-power 3-axis accelerometer, I2C/SPI, 1.62-3.6 V, LGA-12 2x2x0.7 mm",
        keywords="accelerometer MEMS IMU I2C SPI ST",
        pins=[
            (9, "VDD", "power_in", "T"),
            (10, "VDD_IO", "power_in", "L"),
            (2, "CS", "input", "L"),
            (3, "SDO/SA0", "input", "L"),       # SA0 address strap in I2C mode (Table 12: input w/ pull-up)
            (7, "RES", "input", "L"),
            (1, "SCL/SPC", "input", "R"),
            (4, "SDA/SDI/SDO", "bidirectional", "R"),
            (12, "INT1", "output", "R"),
            (11, "INT2", "output", "R"),
            (5, "NC", "no_connect", "R"),
            (6, "GND", "power_in", "B"),
            (8, "GND", "power_in", "B"),   # stacked with pin 6 (hidden)
        ],
    ),
]


def footprints(fpgen, lib_dir):
    """Murata PKMCS0909E4000-R1 from the Murata 'Recommendable Land Pattern' (VPPT-BUZJ083-D).

    Pads: 1.3 x 3.4 mm at x = +/-4.35 mm (10.0 mm outer / 7.4 mm inner span). Body 9.0 x 9.0 mm, tol +/-0.2.
    The sound-emitting holes are 2.0 mm wide slots in the bottom face, at the middle of the two
    edges that have no terminals (y = +/-4.5). They are drawn on F.Fab so layout keeps them unobstructed.
    """
    pcbnew = fpgen.pcbnew
    fp = fpgen.Footprint(
        PIEZO_FP,
        "Murata PKMCS0909E4000-R1 magnet-free SMD piezo sounder 9.0x9.0x1.9 mm, Murata recommended land "
        "pattern (10.0/7.4 x 3.4 mm); sound-emitting slots on the bottom face at the non-terminal edges. "
        "https://www.murata.com/en-us/products/productdetail?partno=PKMCS0909E4000-R1",
        "Murata piezo sounder buzzer PKMCS0909E",
    )
    fp.smd("1", -4.35, 0, 1.3, 3.4, shape="rect")
    fp.smd("2", 4.35, 0, 1.3, 3.4, shape="rect")
    # body (fab) with a pin-1 chamfer, plus the two bottom sound slots (2.0 wide, 1.5 deep)
    F = pcbnew.F_Fab
    fp.line(F, -4.5, -3.5, -3.5, -4.5, 0.1)
    fp.line(F, -3.5, -4.5, 4.5, -4.5, 0.1)
    fp.line(F, 4.5, -4.5, 4.5, 4.5, 0.1)
    fp.line(F, 4.5, 4.5, -4.5, 4.5, 0.1)
    fp.line(F, -4.5, 4.5, -4.5, -3.5, 0.1)
    for s in (-1, 1):
        y0, y1 = s * 4.5, s * 3.0
        fp.line(F, -1.0, y0, -1.0, y1, 0.1)
        fp.line(F, -1.0, y1, 1.0, y1, 0.1)
        fp.line(F, 1.0, y1, 1.0, y0, 0.1)
    # silkscreen: body outline at +/-4.61, broken around the pads (pad edge |y| = 1.7)
    S = pcbnew.F_SilkS
    e, g = 4.61, 1.96
    fp.line(S, -e, -e, e, -e)
    fp.line(S, -e, e, e, e)
    for x in (-e, e):
        fp.line(S, x, -e, x, -g)
        fp.line(S, x, g, x, e)
    fp.line(S, -e, -g, -4.94, -g)        # pin-1 tick
    # courtyard: body + 0.25 mm, pads + 0.25 mm
    fp.courtyard_rect(-5.25, -4.75, 5.25, 4.75)
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = "${KICAD9_3DMODEL_DIR}/Buzzer_Beeper.3dshapes/Buzzer_Murata_PKMCS0909E.step"
    fp.fp.Models().push_back(m)
    fp.save(lib_dir)


def build(d):
    d.sheet(*SHEET)

    # Decoupling caps are listed before their IC and drawn GND-left: with schgen's auto-placement this
    # keeps the power-symbol texts of neighbouring caps and the group frames from touching.

    # ---------------------------------------------------------------- encoder
    d.group("Rotation encoder: TMAG5273A2 3D Hall (TWIM0, addr 0x35)",
            "BOTTOM side, theta = 270 deg, long axis radial (X tangential). Put the Hall element, not the\n"
            "package centre, on R_t = 29.0 mm: per TI Fig 6-2 it sits 0.40 mm from the body centre toward\n"
            "the pin-3/4 end and 0.12 mm toward the pin 1-3 side (footprint coords -0.12, +0.40 mm).\n"
            "Caps next to pin 4. No pours/inductors within the magnet-track keep-out.")
    d.add("C50", "Device:C", "100n", C0402, pins={"1": "GND", "2": "+3V3"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})
    d.add("C51", "Device:C", "1u", C0402, pins={"1": "GND", "2": "+3V3"},
          fields={"MPN": "CL05A105KA5NQNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C52923"})
    d.add("U30", "dial_spinner:TMAG5273", "TMAG5273A2QDBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"1": "TMAG_SCL", "6": "TMAG_SDA", "5": "TMAG_INT_N", "4": "+3V3", "2": "GND", "3": "GND"},
          fields={"MPN": "TMAG5273A2QDBVR", "Manufacturer": "Texas Instruments", "LCSC": "C3715882"})

    d.group("Encoder ESD (floating 316L ring 2.4 mm below)",
            "The flywheel is a touchable, electrically floating metal ring passing under U30.\n"
            "U32 clamps TMAG_SCL/SDA/INT_N right at U30 (short GND return via next to U30).")
    d.add("U32", "Power_Protection:TPD4E05U06DQA", "TPD4E05U06DQAR", "Package_SON:USON-10_2.5x1.0mm_P0.5mm",
          pins={"1": "TMAG_SCL", "2": "TMAG_SDA", "4": "TMAG_INT_N", "5": None, "3": "GND",
                "6": None, "7": None, "9": None, "10": None},
          fields={"MPN": "TPD4E05U06DQAR", "Manufacturer": "Texas Instruments", "LCSC": "C138714"},
          datasheet="https://www.ti.com/lit/ds/symlink/tpd4e05u06.pdf")

    d.group("Encoder bus pull-ups (dedicated TWIM0)",
            "4.7k SCL/SDA; 47k on open-drain INT (10 us pulses / latched)")
    d.add("R50", "Device:R", "4.7k", R0402, pins={"1": "+3V3", "2": "TMAG_SCL"},
          fields={"MPN": "0402WGF4701TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25900"})
    d.add("R51", "Device:R", "4.7k", R0402, pins={"1": "+3V3", "2": "TMAG_SDA"},
          fields={"MPN": "0402WGF4701TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25900"})
    d.add("R52", "Device:R", "47k", R0402, pins={"1": "+3V3", "2": "TMAG_INT_N"},
          fields={"MPN": "0402WGF4702TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25792"})

    # ---------------------------------------------------------------- IMU
    d.group("Accelerometer: LIS2DW12 (system I2C, addr 0x19)",
            "CS high = I2C mode. SA0 high = 0x19: never ground SA0 (its internal pull-up cannot be\n"
            "disabled). RES to GND. 100n + 10u at VDD (pin 9), 100n at VDD_IO (pin 10).")
    d.add("C52", "Device:C", "100n", C0402, pins={"1": "GND", "2": "+3V3"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})
    d.add("C53", "Device:C", "10u", C0603, pins={"1": "GND", "2": "+3V3"},
          fields={"MPN": "CL10A106KP8NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C19702"})
    d.add("C54", "Device:C", "100n", C0402, pins={"1": "GND", "2": "+3V3"},
          fields={"MPN": "CL05B104KO5NNNC", "Manufacturer": "Samsung Electro-Mechanics", "LCSC": "C1525"})
    d.add("U31", "dial_spinner:LIS2DW12", "LIS2DW12TR", "Package_LGA:LGA-12_2x2mm_P0.5mm",
          pins={"1": "I2C_SCL", "4": "I2C_SDA", "2": "+3V3", "3": "+3V3",
                "12": "IMU_INT1", "11": "IMU_INT2", "5": None,
                "9": "+3V3", "10": "+3V3", "6": "GND", "8": "GND", "7": "GND"},
          fields={"MPN": "LIS2DW12TR", "Manufacturer": "STMicroelectronics", "LCSC": "C189624"})

    # ---------------------------------------------------------------- pull-ups
    d.group("System I2C + link signal pull-ups (the only ones on the board)",
            "System I2C goes to IMU + BQ25180 (0x6A, via link). CHG_INT_N / BTN_N are open drain on the base board.")
    d.add("R53", "Device:R", "4.7k", R0402, pins={"1": "+3V3", "2": "I2C_SCL"},
          fields={"MPN": "0402WGF4701TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25900"})
    d.add("R54", "Device:R", "4.7k", R0402, pins={"1": "+3V3", "2": "I2C_SDA"},
          fields={"MPN": "0402WGF4701TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25900"})
    d.add("R55", "Device:R", "10k", R0402, pins={"1": "+3V3", "2": "CHG_INT_N"},
          fields={"MPN": "0402WGF1002TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25744"})
    d.add("R56", "Device:R", "100k", R0402, pins={"1": "+3V3", "2": "BTN_N"},
          fields={"MPN": "0402WGF1003TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25741"})

    # ---------------------------------------------------------------- piezo
    d.group("Piezo sounder: Murata PKMCS0909E4000-R1 (magnet-free, 4 kHz, external drive)",
            "Complementary PWM on BUZZ_A/BUZZ_B (one nRF PWM instance): +/-3.3 Vo-p (max +/-12.5).\n"
            "Murata land pattern: two 1.3 x 3.4 mm pads at x = +/-4.35 mm (custom footprint).\n"
            "Sound exits via 2 mm slots in the bottom face at the non-terminal edges: keep them clear.")
    d.add("R57", "Device:R", "470", R0402, pins={"1": "BUZZ_A", "2": "BZ_P"},
          fields={"MPN": "0402WGF4700TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25117"})
    d.add("R58", "Device:R", "470", R0402, pins={"1": "BUZZ_B", "2": "BZ_N"},
          fields={"MPN": "0402WGF4700TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C25117"})
    d.add("R59", "Device:R", "1M", R0402, pins={"1": "BZ_P", "2": "BZ_N"},
          description="Bleeds piezo charge from shock while the drive pins are disconnected in sleep",
          fields={"MPN": "0402WGF1004TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C26083"})
    d.add("BZ1", "Device:Speaker_Crystal", "PKMCS0909E4000-R1", "dial_spinner:" + PIEZO_FP,
          pins={"1": "BZ_P", "2": "BZ_N"},
          datasheet=PIEZO_DS, description="Murata 4 kHz SMD piezo sounder, external drive, 9x9x1.9 mm",
          fields={"MPN": "PKMCS0909E4000-R1", "Manufacturer": "Murata", "LCSC": "C910763"})
