# Hardware generator toolchain

The KiCad project in `hardware/kicad/` is **generated** from Python, so the
circuit is reviewable as code and can be regenerated after every change.
Open the generated project in KiCad 10 to inspect it, hand-tune the
layout, or continue the design by hand.

| Module | What it does |
|---|---|
| `sexpr.py` | Minimal S-expression reader/writer for KiCad files |
| `symlib.py` | Loads KiCad library symbols (flattening `extends`) and exposes pin geometry |
| `symgen.py` | Builds simple box symbols for parts missing from the KiCad libraries |
| `schgen.py` | Writes hierarchical `.kicad_sch` sheets. Every pin gets a short wire stub ending in a net label, global label or power symbol, and parts are auto-placed in titled groups |
| `pcbgen.py` | Builds a `.kicad_pcb` from the KiCad netlist through the `pcbnew` API: footprints linked to symbols, outline, zones, keepouts, fills, and Specctra DSN/SES I/O for Freerouting |
| `fab.py` | Gerbers, drill files, and the JLCPCB BOM |
| `jlc_cpl.py` | JLCPCB CPL: per-LCSC-part rotation/origin corrections fitted to the EasyEDA footprints, and a simulation of JLC's placement of every row that stops the release if a pad lands off copper (`tests/test_jlc_cpl.py`) |

## KiCad 10

The toolchain runs on **KiCad 10.0.8** (moved from 9.0.9 with no change to the design: the netlists, the routed
copper and the Gerbers are the same, see below). `schgen.py` still writes the KiCad 9 schematic format
(`(version 20250114)`), which KiCad 10 opens as it is; the boards, footprints and project files are written by
`pcbnew` and `kicad-cli` 10 themselves.

What changed for this toolchain:

* pcbnew API: `PCB_IO_MGR.PluginFind` -> `FindPlugin`; `FOOTPRINT.HasFieldByName` / `GetFieldByName` -> `HasField` /
  `GetField` (`None` for a missing field); `ZONE.Get/SetDoNotAllowCopperPour` -> `Get/SetDoNotAllowZoneFills`;
  `BOARD.GetBoardPolygonOutlines(outline)` needs the infer-outline flag (`True` keeps 9's behaviour).
* `PCB_TRACK.GetStart()` / `GetEnd()` return references to the track's own points: copy them
  (`pcbnew.VECTOR2I(t.GetEnd())`) before a `SetStart()` / `SetEnd()` on the same track. `finish_route.anchor_end`
  did not, so a track it split would have lost its far part (`tests/test_finish_route.py`).
* DRC: a zero-length track segment is a `tracks_crossing` error. `pcbgen.dedupe_tracks` (run by `layout.py --finish`)
  removes them. The main board had eight from its KiCad 9 routing, each inside other copper of its own net, so
  removing them changed no copper.
* Schematic parity compares every symbol field with the footprint's (`footprint_symbol_field_mismatch`), Datasheet
  and Description included: `pcbgen.sync_footprint_fields` copies them all onto the footprint, hidden (at placement,
  and in `release.py`'s field sync).
* Netlist: one token per line; a node's `pinfunction` is `<pin name>_<pin number>` (`"SDA_C1"`; 9 wrote `"SDA"`),
  so `sim/spicelib.py` takes pin names from the netlist's `(libparts)`; an empty Datasheet is `""` (9: `"~"`).
* Board file: no net table; pads and tracks name their net as `(net "NAME")`, so nothing may look nets up by number
  when it reads a `.kicad_pcb` as text (`sim/tests/test_led_data.py`).
* Libraries (10.0.8): the USB-C receptacle (`Connector:USB_C_Receptacle_USB2.0_16P`,
  `USB_C_Receptacle_HRO_TYPE-C-31-M-12`) calls its shield `SH` (9: `S1`), so the base board's J1 shield pads were
  renamed `SH` (same copper, same net). `SOT-363_SC-70-6`, the fiducial and the USB-C footprints changed in the
  library; a board keeps its own copy (a `lib_footprint_mismatch` warning) until someone updates it on purpose.
  `jlc_cpl.py` therefore checks the CPL against the board's own copy of each footprint, not the installed library,
  and notes where the two differ. `TPS22917DBV` moved its pins (U21's stubs moved; same connections).
* Stock paths are `${KICAD10_SYMBOL_DIR}`, `${KICAD10_FOOTPRINT_DIR}`, `${KICAD10_3DMODEL_DIR}`; the user library
  tables live in `~/.config/kicad/10.0/` (`cp /usr/share/kicad/template/{sym,fp}-lib-table`). Footprints placed
  under KiCad 9 still name `${KICAD9_3DMODEL_DIR}`, which KiCad 10 resolves.
* ERC lists the ignored checks at the end of `erc.rpt`. The results are unchanged: main one waived `pin_to_pin` on
  U21, base clean.

## Requirements

* KiCad 10.0.8 (`kicad-cli` and the `pcbnew` Python module), with the stock symbol and footprint libraries
* Java 21 + [Freerouting](https://github.com/freerouting/freerouting) 2.1.x (optional, for autorouting)
* Python 3.10+

## Flow

```
design/*.py  ──schgen──▶  kicad/*.kicad_sch  ──kicad-cli──▶  netlist
                                                           │
                       placement.py ──pcbgen──▶  kicad/*.kicad_pcb ──DSN──▶ Freerouting ──SES──▶ routed board
                                                                                                │
                                                                         kicad-cli ERC/DRC ◀────┘──▶ fab outputs
```

ERC and DRC run through `kicad-cli` on every build, and their reports are
written next to the outputs.
