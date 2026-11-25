"""Schematic sheet modules, grouped per board (KiCad project), in page order.

Each module defines:
    SHEET = (name, filename, title)
    SYMBOLS = [dict(name=..., pins=[(number, name, etype, side), ...], ref="U",
                    footprint="lib:fp", datasheet="url", description="...")]   # optional custom symbols
    def footprints(fpgen, lib_dir): ...                                         # optional custom footprints
    def build(d): ...                                                           # adds the sheet's parts
"""

PROJECTS: dict[str, list[str]] = {
    "main": ["main_power", "mcu", "display", "leds", "sensors", "detent"],
    "base": ["base"],
    # rev B bench boards (issue #5's bench phase): not product boards, each a single sheet
    "bench_display": ["bench_display"],
    "bench_nfc_plate": ["bench_nfc_plate"],
    "bench_nfc_base": ["bench_nfc_base"],
}
SHEETS = [s for v in PROJECTS.values() for s in v]
