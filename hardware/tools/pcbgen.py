"""Build a KiCad 9 board from a KiCad netlist using the pcbnew Python API.

Footprints are linked to their schematic symbols (KIID paths), so
"Update PCB from Schematic" in KiCad keeps working on the generated board.
"""

from __future__ import annotations

import math
import os
import subprocess

import pcbnew

import sexpr
from sexpr import find, find_all

MM = pcbnew.FromMM
FP_DIR = os.environ.get("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")


def vec(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def load_netlist(path):
    n = sexpr.parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in find_all(find(n, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        fields = {}
        fl = find(c, "fields")
        if fl:
            for f in find_all(fl, "field"):
                name = str(find(f, "name")[1])
                fields[name] = str(f[2]) if len(f) > 2 else ""
        props = {}
        for p in find_all(c, "property"):
            v = find(p, "value")
            props[str(find(p, "name")[1])] = str(v[1]) if v else ""
        for k in ("MPN", "LCSC", "Manufacturer", "DNP"):
            if props.get(k) and not fields.get(k):
                fields[k] = props[k]
        sp = find(c, "sheetpath")
        comps[ref] = dict(
            ref=ref,
            value=str(find(c, "value")[1]),
            footprint=str(find(c, "footprint")[1]) if find(c, "footprint") else "",
            fields=fields,
            props=props,
            sheet_tstamps=str(find(sp, "tstamps")[1]),
            sheet_names=str(find(sp, "names")[1]),
            tstamp=str(find(c, "tstamps")[1]),
        )
    nets = {}
    for net in find_all(find(n, "nets"), "net"):
        name = str(find(net, "name")[1])
        nets[name] = [(str(find(nd, "ref")[1]), str(find(nd, "pin")[1])) for nd in find_all(net, "node")]
    return comps, nets


def export_netlist(sch_path, out_path):
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", out_path, sch_path],
                   check=True, capture_output=True)
    return out_path


class BoardBuilder:
    def __init__(self, copper_layers=4, extra_fp_libs: dict | None = None):
        self.board = pcbnew.BOARD()
        self.board.SetCopperLayerCount(copper_layers)
        self.fp_libs = dict(extra_fp_libs or {})
        self.footprints: dict[str, pcbnew.FOOTPRINT] = {}
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}

    # -- design rules ---------------------------------------------------------
    def rules(self, track=0.15, clearance=0.15, via=0.45, via_drill=0.25, edge=0.3, hole_clear=0.25):
        ds = self.board.GetDesignSettings()
        ds.m_TrackMinWidth = MM(0.1)
        ds.m_MinClearance = MM(0.1)
        ds.m_ViasMinSize = MM(0.4)
        ds.m_MinThroughDrill = MM(0.2)
        ds.m_CopperEdgeClearance = MM(edge)
        ds.m_HoleClearance = MM(hole_clear)
        ns = ds.m_NetSettings
        nc = ns.GetDefaultNetclass()
        nc.SetTrackWidth(MM(track))
        nc.SetClearance(MM(clearance))
        nc.SetViaDiameter(MM(via))
        nc.SetViaDrill(MM(via_drill))
        return ds

    def netclass(self, name, nets, track, clearance=0.15, via=0.6, via_drill=0.3):
        ns = self.board.GetDesignSettings().m_NetSettings
        nc = pcbnew.NETCLASS(name)
        nc.SetTrackWidth(MM(track))
        nc.SetClearance(MM(clearance))
        nc.SetViaDiameter(MM(via))
        nc.SetViaDrill(MM(via_drill))
        ns.SetNetclass(name, nc)
        for n in nets:
            ns.SetNetclassPatternAssignment(n, name)

    # -- geometry ---------------------------------------------------------------
    def circle(self, layer, cx, cy, r, width=0.1):
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(vec(cx, cy))
        s.SetEnd(vec(cx + r, cy))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.board.Add(s)
        return s

    def polyline(self, layer, pts, width=0.1, closed=True):
        seq = list(pts) + ([pts[0]] if closed else [])
        for (x0, y0), (x1, y1) in zip(seq, seq[1:]):
            s = pcbnew.PCB_SHAPE(self.board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(vec(x0, y0))
            s.SetEnd(vec(x1, y1))
            s.SetLayer(layer)
            s.SetWidth(MM(width))
            self.board.Add(s)

    def arc(self, layer, cx, cy, r, a0, a1, width=0.1):
        """Arc from angle a0 to a1 (degrees, CCW on screen with y down = clockwise math)."""
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        am = (a0 + a1) / 2
        p = lambda a: vec(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        s.SetArcGeometry(p(a0), p(am), p(a1))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.board.Add(s)
        return s

    def text(self, layer, s, x, y, size=1.0, thickness=0.15, angle=0, mirror=False):
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(s)
        t.SetPosition(vec(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(thickness))
        t.SetTextAngleDegrees(angle)
        t.SetMirrored(mirror)
        self.board.Add(t)
        return t

    @staticmethod
    def circle_pts(cx, cy, r, n=72, a0=0.0, a1=360.0):
        return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n)]

    def zone(self, net, layers, pts, priority=0, clearance=0.2, min_width=0.2, thermal_gap=0.3,
             spoke=0.3, name=""):
        z = pcbnew.ZONE(self.board)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        if net:
            z.SetNet(self.net(net))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(MM(clearance))
        z.SetMinThickness(MM(min_width))
        z.SetThermalReliefGap(MM(thermal_gap))
        z.SetThermalReliefSpokeWidth(MM(spoke))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        self.board.Add(z)
        return z

    def keepout(self, layers, pts, tracks=True, vias=True, pads=True, pours=True, footprints=False, name=""):
        z = pcbnew.ZONE(self.board)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowPads(pads)
        z.SetDoNotAllowCopperPour(pours)
        z.SetDoNotAllowFootprints(footprints)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        self.board.Add(z)
        return z

    # -- nets & footprints ------------------------------------------------------
    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def _lib_path(self, nick):
        if nick in self.fp_libs:
            return self.fp_libs[nick]
        return os.path.join(FP_DIR, nick + ".pretty")

    def load_footprint(self, fpid):
        nick, name = fpid.split(":", 1)
        fp = pcbnew.FootprintLoad(self._lib_path(nick), name)
        if fp is None:
            raise KeyError(f"footprint {fpid} not found")
        fp.SetFPIDAsString(fpid)
        return fp

    def place_from_netlist(self, comps, nets, placement, default=(0.0, 0.0, 0.0, "F")):
        pin_net = {}
        for name, nodes in nets.items():
            for ref, pin in nodes:
                pin_net[(ref, pin)] = name
        for ref, c in sorted(comps.items()):
            if not c["footprint"]:
                continue
            fp = self.load_footprint(c["footprint"])
            fp.SetReference(ref)
            fp.SetValue(c["value"])
            fp.SetPath(pcbnew.KIID_PATH(c["sheet_tstamps"] + c["tstamp"]))
            fp.SetSheetname(c["sheet_names"].strip("/").split("/")[-1] if c["sheet_names"] != "/" else "")
            for k in ("MPN", "LCSC", "Manufacturer"):
                if c["fields"].get(k):
                    fp.SetField(k, c["fields"][k])
                    fld = fp.GetFieldByName(k)
                    if fld:
                        fld.SetVisible(False)
            if c["props"].get("dnp") is not None or c["fields"].get("DNP"):
                fp.SetDNP(True)
            if "exclude_from_bom" in c["props"]:
                fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
            self.board.Add(fp)
            x, y, rot, side = placement.get(ref, default)
            if side == "B":
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            fp.SetPosition(vec(x, y))
            fp.SetOrientationDegrees(rot)
            for pad in fp.Pads():
                net = pin_net.get((ref, pad.GetNumber()))
                if net:
                    pad.SetNet(self.net(net))
            self.footprints[ref] = fp
        return self.footprints

    def mounting_hole(self, x, y, fpid="MountingHole:MountingHole_2.2mm_M2", ref="H"):
        fp = self.load_footprint(fpid)
        fp.SetReference(ref)
        fp.SetPosition(vec(x, y))
        self.board.Add(fp)
        return fp

    def set_origin(self, x, y):
        """Drill/place (aux) origin, used for gerber and pick-and-place coordinates."""
        ds = self.board.GetDesignSettings()
        ds.SetAuxOrigin(vec(x, y))
        ds.SetGridOrigin(vec(x, y))

    def save(self, path, fill=True):
        """Save; zone filling only works on a board loaded from disk, so reload first."""
        self.board.SetFileName(path)
        pcbnew.SaveBoard(path, self.board)
        if fill:
            refill(path)


def refill(path):
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    return b


def export_dsn(pcb_path, dsn_path):
    b = pcbnew.LoadBoard(pcb_path)
    if not pcbnew.ExportSpecctraDSN(b, dsn_path):
        raise RuntimeError("DSN export failed")


def import_ses(pcb_path, ses_path, out_path=None):
    b = pcbnew.LoadBoard(pcb_path)
    if not pcbnew.ImportSpecctraSES(b, ses_path):
        raise RuntimeError("SES import failed")
    out_path = out_path or pcb_path
    pcbnew.SaveBoard(out_path, b)
    refill(out_path)
