"""Rev B bench board: the main board's ground plane under the NFC coil, with the tuning network.

The study's coupling numbers come from the coil sitting 3.5 mm over the main board's In1
ground plane (docs/display-study.md §3.3).  This Ø64 2-layer board is that plane -- the TOP
is one unbroken GND pour, as In1 is -- with everything else on the bottom: the per-pin tuning
capacitors, a damping footprint, a U.FL for the NanoVNA and a header to the nRF52840-DK.
bench_nfc_plate stacks on it: a printed 3.0 mm spacer from this board's top to the plate's
bottom puts the coil 3.4 mm over the ground copper, as in the device.

Tuning, per pin, from the study: Ctune = 2 / ((2 pi 13.56 MHz)^2 L) - Cp - Cint, about
95-110 pF C0G with the IFL05K and about 190 pF without.  C1/C2 are fitted at 100 pF (the
with-ferrite case); C3/C4 are DNP pads in parallel for the no-ferrite runs (+82 pF = 182 pF)
or for trimming.  Keep the two pins matched.  Tune slightly high: a phone at contact pulls
the resonance down.

VNA (one port, L and Q of the coil as built): fit R4 and R5, remove the DK cable.  The VNA
then sees NFC1 against GND with NFC2 grounded, so C1 sets the resonance it reports.
DK: wire J2 to the DK's NFC antenna connector J5 (P0.09/P0.10 through its R44/R46 0R).  Check
the DK schematic for tuning capacitors on that path before fitting C1-C4: any that are fitted
there sit in parallel with these.
"""

SHEET = ("bench_nfc_base", "bench_nfc_base.kicad_sch", "NFC ground plane and tuning")
TITLE = "dial-me-spinner rev B bench: NFC ground plane and tuning"
REV = "1"
DATE = "2026-10-23"
POWER_NETS = ["GND"]

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

R0 = {"MPN": "0402WGF0000TCE", "Manufacturer": "UNI-ROYAL", "LCSC": "C17168"}
C100P = {"MPN": "0402CG101J500NT", "Manufacturer": "FH", "LCSC": "C1546"}
C82P = {"MPN": "0402CG820J500NT", "Manufacturer": "FH", "LCSC": "C45501"}


def build(d):
    d.sheet(*SHEET)
    d.group("Coil contacts (top, under the plate's pads A and B)",
            "W1 under pad A (theta 210), W2 under pad B (theta 190), both at r 23.  Wire or spring them up to the plate.\n"
            "The top is otherwise one GND pour: the stand-in for the main board's In1 plane.")
    d.add("W1", "Connector:TestPoint", "COIL A", "TestPoint:TestPoint_THTPad_2.0x2.0mm_Drill1.0mm",
          pins={"1": "COIL_A"}, in_bom=False)
    d.add("W2", "Connector:TestPoint", "COIL B", "TestPoint:TestPoint_THTPad_2.0x2.0mm_Drill1.0mm",
          pins={"1": "COIL_B"}, in_bom=False)

    d.group("Tuning network (bottom)",
            "R1/R2 0R in series: room for a small damping R per leg.  C1/C2 100p C0G fitted (with the IFL05K).\n"
            "C3/C4 DNP in parallel: +82p for the no-ferrite runs, or to trim.  R3 DNP across the coil (0603): parallel damping.")
    d.add("R1", "Device:R", "0R", R0402, pins={"1": "COIL_A", "2": "NFC1"}, fields=R0)
    d.add("R2", "Device:R", "0R", R0402, pins={"1": "COIL_B", "2": "NFC2"}, fields=R0)
    d.add("C1", "Device:C", "100p C0G", C0402, pins={"1": "NFC1", "2": "GND"}, fields=C100P)
    d.add("C2", "Device:C", "100p C0G", C0402, pins={"1": "NFC2", "2": "GND"}, fields=C100P)
    d.add("C3", "Device:C", "82p C0G", C0402, pins={"1": "NFC1", "2": "GND"}, dnp=True, fields=C82P)
    d.add("C4", "Device:C", "82p C0G", C0402, pins={"1": "NFC2", "2": "GND"}, dnp=True, fields=C82P)
    d.add("R3", "Device:R", "DNP", R0603, pins={"1": "NFC1", "2": "NFC2"}, dnp=True,
          description="Parallel damping across the coil: fit by hand if the Q is too high for the field detector")

    d.group("NanoVNA port and DK header (bottom)",
            "VNA: fit R4 + R5 (0R), unplug J2.  The VNA sees NFC1 to GND with NFC2 grounded.\n"
            "DK: J2 to the DK's NFC connector J5 with a short twisted pair; R4/R5 stay off.")
    d.add("J1", "Connector:Conn_Coaxial", "U.FL", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
          pins={"1": "VNA", "2": "GND"},
          fields={"MPN": "U.FL-R-SMT-1(10)", "Manufacturer": "HIROSE", "LCSC": "C88373"})
    d.add("R4", "Device:R", "0R", R0402, pins={"1": "VNA", "2": "NFC1"}, dnp=True, fields=R0)
    d.add("R5", "Device:R", "0R", R0402, pins={"1": "NFC2", "2": "GND"}, dnp=True, fields=R0)
    d.add("J2", "Connector_Generic:Conn_01x03", "TO DK J5",
          "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
          pins={"1": "NFC1", "2": "NFC2", "3": "GND"}, in_bom=False)

    d.group("ERC", "GND arrives from the DK through J2 or from the VNA through J1.")
    d.add("#FLG01", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "GND"}, in_bom=False, on_board=False)
