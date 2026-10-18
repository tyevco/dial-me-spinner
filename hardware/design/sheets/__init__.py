"""Schematic sheet modules, in page order.

Each module defines:
    SHEET = (name, filename, title)
    SYMBOLS = [dict(name=..., pins=[(number, name, etype, side), ...], ref="U",
                    footprint="lib:fp", datasheet="url", description="...")]   # optional custom symbols
    def footprints(fpgen, lib_dir): ...                                         # optional custom footprints
    def build(d): ...                                                           # adds the sheet's parts
"""

SHEETS: list[str] = []
