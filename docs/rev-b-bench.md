# Rev B bench boards

Issue [#5](https://github.com/tyevco/dial-me-spinner/issues/5) puts a bench phase ahead of the rev B layout: put the
1.75" AMOLED on an nRF52840-DK, and measure the NFC coil over a copy of the main board's ground plane with the real
panel on top. These three boards are that phase. **None of them is a rev B board.** They exist to answer the
questions the rev B layout is waiting on, and they carry none of its layout decisions.

| Board | KiCad project | What it settles |
|---|---|---|
| **AMOLED shield**: Arduino R3 shield for the nRF52840-DK | `hardware/kicad/bench_display` | Bring-up sequence, 1-wire `0x02` framing at 32 MHz, colour modes, TE and partial windows, current against content, the VBAT sweep 3.0–4.5 V, and the touch I2C voltage |
| **NFC coil plate**: the display support plate with its coil | `hardware/kicad/bench_nfc_plate` | Coil L and Q with and without the IFL05K, with and without the notches, and with the real panel on top |
| **NFC base**: the main board's ground plane plus the tuning network | `hardware/kicad/bench_nfc_base` | The same, at the device's 3.4 mm coil-to-ground spacing, then read range with 2–3 phones on the DK |

All three are generated like the product boards (`build.py --board <name>`, `layout.py --board <name>`), and each
is its own single-sheet project with its own title, revision and power nets.

**Status: routed, DRC-clean and released, not ordered.** All three pass `release.py`'s gate (DRC, schematic parity,
and the JLC placement simulation). Gerbers, BOM, CPL and order notes are in `hardware/fab/<board>/`.

| Board | ERC | DRC errors | DRC warnings |
|---|---|---|---|
| AMOLED shield | clean; 2 waivers, recorded with reasons in `build.py` | none | 3 where the glass-outline silk crosses part outlines and header pads (cosmetic: JLC clips silk off pads); 1 library mismatch on J1, whose Uno outline was replaced by header-row courtyards on purpose |
| NFC coil plate | clean; 1 waiver (the coil's ends leave the board by wire) | none | none |
| NFC base | clean | none | none |

## 1. AMOLED shield

### The panel pinout, and why the connector is numbered backwards

The panel pinout comes from the Huaxin H0175Y003AMT003 V0 specification, §4 "Module Interface". The **31 FPC
contacts mate at connector pin = 32 − panel pin.** Waveshare's
[ESP32-S3-Touch-AMOLED-1.75 schematic](https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.75/ESP32-S3-Touch-AMOLED-1.75.pdf)
uses the same tail on an FH26-31S-0.3SHW, and all 31 of its J3 pins match the vendor table under that reversal.
`hardware/design/tests/test_bench_display.py` checks the shield's netlist against an independent transcription of
Waveshare's J3, not against the reversal rule, so a mistake in the rule cannot pass its own test.

| Panel pin | Function | J2 pin | Net | DK pin | GPIO |
|---|---|---|---|---|---|
| 2 | TP_INT | 30 | `TP_INT` | A2 | P0.28 |
| 3 | TP_RST | 29 | `TP_RST_N` | A3 | P0.29 |
| 4 / 5 | TP_SDA / TP_SCL | 28 / 27 | `TP_SDA` / `TP_SCL` → `I2C_SDA` / `I2C_SCL` | SDA / SCL | P0.26 / P0.27 |
| 6 | TP_3.3V (touch supply, 2.8–3.3 V) | 26 | `TP_VDD` | | |
| 8 | IOVCC (1.8–3.3 V) | 24 | `IOVCC` | | |
| 9 | VCI | 23 | `VCI` | | |
| 10 | VBAT (pin table 3.7–4.5 V; application circuit 3.3–5.5 V) | 22 | `DISP_VBAT` | | |
| 11 | VCI_EN ("Enable for VBAT") | 21 | `DISP_VCI_EN` | D4 | P1.05 |
| 13 | MTP_PWR: **left open** | 19 | | | |
| 14 | RESET | 18 | `DISP_RES_N` | D0 | P1.01 |
| 15 | CSX | 17 | `DISP_CS_N` | D10 | P1.12 |
| 16 | SDI / QSPI D0 | 16 | `DISP_SIO0` | A1 | **P0.04** |
| 17 | DCX / QSPI D1 | 15 | `DISP_SIO1` | A4 | P0.30 (read-back only) |
| 18 | SCL (SCK) | 14 | `DISP_SCK` | D7 | **P1.08** |
| 19 / 20 | D(1) / D(0) = QSPI D3 / D2 | 13 / 12 | `DISP_SIO3` / `DISP_SIO2` | | 10k pull-downs, TP7/TP8 |
| 21 | TE | 11 | `DISP_TE` | A5 | P0.31 |
| 23–24, 26–27, 29–30 | MIPI-DSI pairs, unused | 9–8, 6–5, 3–2 | open | | |
| 1, 7, 12, 22, 25, 28, 31 | GND | 31, 25, 20, 10, 7, 4, 1 | `GND` | | |

The DK pins were chosen against SPEC §4's list of low-frequency-only pins. Only four Arduino-header pins are full
speed, P0.04, P1.08, P0.26 and P0.27. The two 32 MHz lines take P1.08 and P0.04, and touch I2C keeps P0.26/P0.27.
A test fails if either 32 MHz line moves onto a slow pin. The pins `display-study.md` §7.1 names for rev B are
reused wherever they land on the header (P0.28, P0.29, P0.31, P1.05), and reset and the VBAT switch keep rev A's
P1.01/P1.02.

::: warning The Arduino symbol names A4 and SDA alike
An Uno ties A4 to SDA and A5 to SCL, so KiCad's `Arduino_UNO_R3` symbol gives them the same names. On the DK they
are different GPIOs: P0.30 and P0.26, P0.31 and P0.27. The shield assigns header pins by **number**, and a test
checks that no header net appears twice.
:::

### Power

- **VBAT** comes from **J3**, where a PPK2 in source-meter mode does the 3.0–4.5 V sweep and the current-vs-content
  runs. The alternative is the DK's VDD, selected on **J4**: 1–2 is external, 2–3 is the DK. The DK's 3.0 V is below
  the pin table's 3.7 V minimum, and Waveshare runs it at 3.3 V.
- From VBAT_IN it passes through **U1**, the TPS22917 rev B keeps, wired as rev A's U21 with CT 1 nF and QOD to VOUT.
  Its enable is `DISP_VBAT_EN` (P1.02, 100k pull-down). R1 (DNP) bypasses U1.
- **The logic rails** (VCI, IOVCC, TP_VDD) come from the DK's VDD through the **J5** shunt. Take the shunt off and put
  a PPK2 across it as an ammeter. R3–R5 split the three rails so any one of them can be fed or measured alone.
- **Hold-offs.** `DISP_RES_N` has a 1M pull-down and `DISP_VCI_EN` a 100k pull-down, so the panel stays off while the
  DK resets.

### Touch I2C: 3.0 V fitted, 1.8 V as an option

The Huaxin and Viewe drawings say the touch I2C runs at **1.8 V**. Waveshare drives it at 3.3 V. As fitted, R14/R15
tie the bus straight to P0.26/P0.27 at the DK's 3.0 V, with 4.7k pull-ups.

The 1.8 V option is a PCA9306 (U2) plus an AP2112K-1.8 (U3), all DNP. To use it, remove R14/R15/R16 and fit U2, U3,
C11, C12, R17, R18 and R19. **In 1.8 V mode TP_INT and TP_RST_N are not shifted.** At 1.8 V, TP_INT is below the
nRF's VIH (0.7 VDD = 2.1 V), and the nRF would drive TP_RST_N to 3.0 V. So that mode answers whether the bus works,
not whether the design is finished.

### The 32 MHz lines

- **Series links.** R6/R7 are 0R at the header. Swap them for 22–33R if SCK/SIO0 ring. The CO5300 needs edges of
  ≤ 3.5 ns (20–80 %).
- **Scope points.** TP1–TP4 (SCK, SIO0, CS, TE) sit in a column 6 mm from J2, with GND springs TP5/TP6 beside them.
  Probe at the panel end, with a spring ground rather than the lead.
- **Pin drive.** Use high drive (`NRF_DRIVE_H0H1`) on both lines.
- **The routed lines are long.** SCK is 49 mm and SIO0 is 80 mm from header to panel pin, two vias each. P0.04 to
  J2 is about 33 mm in a straight line, so the router detoured. The DK's own traces to its header come on top of
  that. This errs pessimistic: more capacitance than a rev B board would put on the lines. If the edges pass here
  they will pass on rev B. If they fail, the length is the first suspect, ahead of the nRF's drive.

### Assembly

1. **Headers.** Solder plain male headers from the bottom, plastic on top, pins down into the DK. Stacking headers
   would put the panel 8 mm higher.
2. **Panel.** It sits face-up over the shield in the printed **panel spacer**, `stl/bench_panel_spacer.stl` from
   `hardware/mechanical/bench.scad`. The spacer:
   - holds the glass edge on a ledge 4.0 mm above the board, in a Ø49.36 pocket. That fits the Ø48.96 Huaxin glass
     and the Ø48.16 Viewe glass with 0.4 mm of play. The silk circle is the outline to line it up on;
   - flies 2.8 mm up, over the 2.54 mm header plastic;
   - stands on three Ø4 feet at θ 25°/115°/215° about the glass centre. A scan of every courtyard and pad on the
     routed board found these clear by 7 mm or more, and `tests/test_bench.py` re-checks them against the board;
   - is open over θ 155–200°, where the tail folds under.

   Tape the feet down. Print it lip-down, as exported, and nothing bridges. Everything under the outline is ≤ 1.2 mm,
   and the tall jumpers are outside it.
3. **Tail.** Fold the tail behind the panel as the vendor's fold diagram shows, contacts down, into J2 from the left
   (the fold side). J2 is a **back-flip** FH26W: lift the actuator, which faces right, before inserting. Do not close it
   first, per Hirose.
4. **Tail landing point.** The silk marks connector pin 31 as PIN 1. The folded contact end lands near the middle of
   the panel's back, but its exact landing point needs a sample in hand (`display-study.md` §3.4). The tail has the
   slack for a bench fit.

### Firmware: a DK overlay

The shield needs its own SPIM3 pinctrl. Zephyr's `arduino_spi` pins are P1.13–P1.15, all low-frequency pins. The
`chipone,co5300` driver uses SCK, one data line and CS, with command and data framed in-band (`0x02`, then
`{0x00, CMD, 0x00}`), so there is no DC pin. Check the property names against the binding in your Zephyr tree.

```dts
&pinctrl {
	spi3_disp: spi3_disp {
		group1 {
			psels = <NRF_PSEL(SPIM_SCK, 1, 8)>, <NRF_PSEL(SPIM_MOSI, 0, 4)>,
				<NRF_PSEL(SPIM_MISO, 0, 30)>;		/* SIO1 read-back: a slow pin, reduced clock */
			nordic,drive-mode = <NRF_DRIVE_H0H1>;
		};
	};
	spi3_disp_sleep: spi3_disp_sleep {
		group1 {
			psels = <NRF_PSEL(SPIM_SCK, 1, 8)>, <NRF_PSEL(SPIM_MOSI, 0, 4)>,
				<NRF_PSEL(SPIM_MISO, 0, 30)>;
			low-power-enable;
		};
	};
};

&spi3 {
	pinctrl-0 = <&spi3_disp>;
	pinctrl-1 = <&spi3_disp_sleep>;
	cs-gpios = <&gpio1 12 GPIO_ACTIVE_LOW>;			/* D10 */
	display@0 {
		compatible = "chipone,co5300";
		reg = <0>;
		spi-max-frequency = <32000000>;
		width = <466>;
		height = <466>;
		pixel-format = <PANEL_PIXEL_FORMAT_RGB_565>;
		reset-gpios = <&gpio1 1 GPIO_ACTIVE_LOW>;		/* D0 */
		tear-effect-gpios = <&gpio0 31 GPIO_ACTIVE_HIGH>;	/* A5 */
	};
};
/* DISP_VBAT_EN P1.02 and DISP_VCI_EN P1.05 are plain GPIOs: VBAT switch on, then VCI_EN, then reset. */
/* Touch: &i2c0 (arduino_i2c) is already P0.26/P0.27 on the DK. */
```

## 2. NFC coil plate and base

### The stack

From the bottom up:

1. **NFC base**, Ø64 × 1.6 mm. Its top is one unbroken GND pour, standing in for the main board's In1 plane.
2. **The NFC spacer**, `stl/bench_nfc_spacer.stl`: a ring at r 16.5–21.5, 2.76 mm tall. With the 0.24 mm ferrite on
   top of it, the plate sits 3.0 mm above the base top. M2 × 4 screws come up through the base's Ø2.2 holes at r 19
   and self-tap into the spacer's Ø1.6 holes. The plate drops in between three tabs at its edge (θ 30°/150°/270°,
   clear of W1/W2 and J2), flush with the plate top, so the panel rests on the plate and not on them. The spacer
   prints flat with no supports. The screws stop 0.36 mm below the spacer's top, so the ferrite needs no holes.
3. **The IFL05K sheet**, 0.2 mm, cut to the plate's outline and notches and stuck to the plate's **bottom**.
4. **The coil plate**, 0.4 mm FR4, r 26.6.
5. **The panel**, on top.

That puts the coil 3.4 mm over ground copper, as in the device (`display-study.md` §3.2).

### The coil

| | |
|---|---|
| Turns | 4 concentric turns, each joined to the next by a 10° jog at θ 190–200° |
| Track / gap | 0.25 / 0.233 mm (0.483 mm pitch), copper r 24.6–26.3, 0.3 mm from the r 26.6 edge |
| Crossover | The outer end crosses inward on B.Cu at θ 210°. The inner three turns dip 0.3 mm over θ 200–220° to clear its via |
| Contacts | B.Cu pads A (θ 210°) and B (θ 190°) at r 23, where the study proposes moving J11. The base's W1/W2 sit directly under them |
| Ferrite notches | Drawn on the plate's bottom silk to cut against: **TMAG**, θ 253–287° (±17° of the TMAG5273 at θ 270°, an estimate), and **OPTIONAL**, θ 75–105° over the detent magnet's path. Build plates with and without it and compare |

The coil is a single footprint (L1), a net tie between its two pads. Drawn as tracks, a coil that joins NFC1 to
NFC2 would be a short as far as DRC is concerned. A true spiral was not used because fitting four turns into the
1.7 mm band would leave a 0.115 mm gap.

### Tuning

Each pin needs Ctune = 2 / ((2π·13.56 MHz)² L) − Cp − Cint (nRF52840 PS), with Cint ≈ 4 pF. That comes to about
95–110 pF C0G per pin with the ferrite and about 190 pF without (study §3.3).

- **Fitted:** C1/C2 at 100 pF, the with-ferrite case.
- **DNP:** C3/C4, +82 pF in parallel for the no-ferrite runs (182 pF) or for trimming; R3, parallel damping, 0603.
- R1/R2 are 0R series links per leg.

Keep the two pins matched, and tune slightly high, because a phone at contact pulls the resonance down.

### Procedure

1. **NanoVNA, one port.** Fit R4 and R5 (0R) and unplug J2. The VNA then sees NFC1 against GND with NFC2 grounded,
   so C1 sets the resonance it reports. Record L, Q and f₀ for each case:
   - bare coil;
   - with the IFL05K;
   - with the TMAG notch;
   - with the optional notch;
   - each of those with the real panel on top.
2. **Phones.** Remove R4/R5 and wire J2 to the DK's NFC connector **J5**. On the DK, P0.09/P0.10 reach J5 through
   R44/R46 (0R). **Check the DK schematic for tuning capacitors on that path** before fitting C1–C4: any that are
   fitted there sit in parallel with these. Read with an iPhone and an Android phone, contact to 4 cm.

## 3. What these boards do not settle

- **Which side of J2 the FPC enters.** It comes from Hirose's rule that a back-flip FH connector takes the FPC on the
  side opposite the actuator, and from KiCad's 3D model. Check it on the first board before fitting the panel.
- **Where the folded tail lands.** It needs a sample panel. So does the tail cutout in the support plate (option 1 in
  `display-study.md` §3.4). This plate is the full disc of option 2.
- **The panel's top operating temperature.** The Huaxin specification contradicts itself. Its §6 absolute maximum
  ratings give −20 to **+60 °C**, while the notes on its mechanical drawing give −20 to +70 °C, the figure in
  `display-study.md` §3.1. Ask the vendor, and design to +60 until they answer.
