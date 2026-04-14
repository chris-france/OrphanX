"""Orphan X — Extract MEP Data for Agentic Node

Extracts all MEP systems + orphaned elements from Revit model.
Outputs JSON string ready to feed into the Agentic Node → Orphan X MCP server.

1. Add a Python Script node
2. Right-click → Engine → CPython3
3. Paste this script
4. Connect output to the Agentic Node's input

No inputs needed.
"""

import clr
import json
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
)
from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
from Autodesk.Revit.DB.Electrical import ElectricalSystem
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

def eid_int(element_id):
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue

def _safe_name(obj, attr="Name"):
    try:
        val = getattr(obj, attr, None)
        if val:
            return str(val)
    except Exception:
        pass
    return "Unknown"

def _get_family_name(elem):
    try:
        return _safe_name(elem.Symbol.Family)
    except Exception:
        pass
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype and hasattr(etype, "FamilyName"):
            return str(etype.FamilyName)
        if etype:
            return _safe_name(etype)
    except Exception:
        pass
    return "Unknown"

def _get_type_name(elem):
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype:
            return _safe_name(etype)
    except Exception:
        pass
    return "Unknown"

def _get_level_name(elem):
    try:
        lid = elem.LevelId
        if lid and eid_int(lid) > 0:
            lvl = doc.GetElement(lid)
            if lvl:
                return lvl.Name
    except Exception:
        pass
    for bip in [BuiltInParameter.FAMILY_LEVEL_PARAM, BuiltInParameter.RBS_START_LEVEL_PARAM]:
        try:
            p = elem.get_Parameter(bip)
            if p and p.HasValue:
                return p.AsValueString()
        except Exception:
            pass
    return "Unknown"

def _param_value(param):
    if param is None or not param.HasValue:
        return None
    try:
        return param.AsValueString() or param.AsString() or str(param.AsDouble())
    except Exception:
        return None

def _get_params(elem):
    params = {}
    for bip in [
        BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
        BuiltInParameter.RBS_CALCULATED_SIZE,
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_PIPE_FLOW_PARAM,
        BuiltInParameter.RBS_DUCT_FLOW_PARAM,
    ]:
        try:
            v = _param_value(elem.get_Parameter(bip))
            if v:
                params[bip.ToString()] = v
        except Exception:
            pass
    for name in ["System Type", "Size", "Diameter", "Flow", "Length"]:
        try:
            v = _param_value(elem.LookupParameter(name))
            if v:
                params[name] = v
        except Exception:
            pass
    return params

def _get_connected_ids(elem):
    connected = []
    try:
        mgr = getattr(elem, "MEPModel", None) or elem
        connectors = mgr.ConnectorManager
        if connectors:
            for c in connectors.Connectors:
                if c.IsConnected:
                    for ref in c.AllRefs:
                        if ref.Owner and ref.Owner.Id != elem.Id:
                            eid = str(ref.Owner.Id.Value)
                            if eid not in connected:
                                connected.append(eid)
    except Exception:
        pass
    return connected

def _serialize(elem):
    return {
        "element_id": str(elem.Id.Value),
        "category": _safe_name(elem.Category) if elem.Category else "Unknown",
        "family": _get_family_name(elem),
        "type": _get_type_name(elem),
        "level": _get_level_name(elem),
        "connected_to": _get_connected_ids(elem),
        "parameters": _get_params(elem),
    }

def _get_location(elem):
    try:
        loc = elem.Location
        if hasattr(loc, "Point"):
            return (loc.Point.X, loc.Point.Y, loc.Point.Z)
        if hasattr(loc, "Curve"):
            mid = loc.Curve.Evaluate(0.5, True)
            return (mid.X, mid.Y, mid.Z)
    except Exception:
        pass
    try:
        bb = elem.get_BoundingBox(None)
        if bb:
            return ((bb.Min.X+bb.Max.X)/2, (bb.Min.Y+bb.Max.Y)/2, (bb.Min.Z+bb.Max.Z)/2)
    except Exception:
        pass
    return None

# --- System type mapping (safe for Revit 2026) ---
_DUCT_MAP = {}
for _a, _v in [("SupplyAir", "SupplyAir"), ("ReturnAir", "ReturnAir"), ("ExhaustAir", "Exhaust")]:
    try:
        e = getattr(DuctSystemType, _a)
        _DUCT_MAP[e] = _v
        _DUCT_MAP[int(e)] = _v
    except Exception:
        pass

_PIPE_MAP = {}
for _a, _v in [
    ("DomesticHotWater", "DomesticHotWater"), ("DomesticColdWater", "DomesticColdWater"),
    ("Sanitary", "SanitaryWaste"), ("Hydronic", "Hydronic"),
    ("HydronicReturn", "Hydronic"), ("HydronicSupply", "Hydronic"),
    ("FireProtectWet", "Sprinkler"), ("FireProtectDry", "Sprinkler"),
]:
    try:
        e = getattr(PipeSystemType, _a)
        _PIPE_MAP[e] = _v
        _PIPE_MAP[int(e)] = _v
    except Exception:
        pass

def _classify_mech(sys):
    try:
        st = sys.SystemType
        if st in _DUCT_MAP: return (_DUCT_MAP[st], "Mechanical")
        if int(st) in _DUCT_MAP: return (_DUCT_MAP[int(st)], "Mechanical")
    except Exception:
        pass
    name = _safe_name(sys).lower()
    if "supply" in name: return ("SupplyAir", "Mechanical")
    if "return" in name: return ("ReturnAir", "Mechanical")
    if "exhaust" in name: return ("Exhaust", "Mechanical")
    return ("Other", "Mechanical")

def _classify_pipe(sys):
    try:
        st = sys.SystemType
        if st in _PIPE_MAP: return (_PIPE_MAP[st], "Plumbing")
        if int(st) in _PIPE_MAP: return (_PIPE_MAP[int(st)], "Plumbing")
    except Exception:
        pass
    name = _safe_name(sys).lower()
    if "hot" in name or "hwr" in name or "hws" in name: return ("DomesticHotWater", "Plumbing")
    if "cold" in name or "cw" in name or "dcw" in name: return ("DomesticColdWater", "Plumbing")
    if "sanit" in name: return ("SanitaryWaste", "Plumbing")
    if "fire" in name or "sprink" in name: return ("Sprinkler", "FireProtection")
    if "hydron" in name or "chw" in name: return ("Hydronic", "Mechanical")
    return ("Other", "Plumbing")

def _get_network(sys):
    elements = []
    seen = set()
    net = None
    try:
        if isinstance(sys, MechanicalSystem): net = sys.DuctNetwork
        elif isinstance(sys, PipingSystem): net = sys.PipingNetwork
        elif isinstance(sys, ElectricalSystem): net = sys.Elements
    except Exception:
        pass
    if net:
        for elem in net:
            eid = elem.Id.Value
            if eid not in seen:
                seen.add(eid)
                elements.append(_serialize(elem))
    if not elements:
        try:
            for elem in sys.Elements:
                eid = elem.Id.Value
                if eid not in seen:
                    seen.add(eid)
                    elements.append(_serialize(elem))
        except Exception:
            pass
    return elements

# ===================== EXTRACT SYSTEMS =====================
systems = []

for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
    try:
        st, disc = _classify_mech(sys)
        systems.append({
            "system_id": str(sys.Id.Value), "system_name": _safe_name(sys),
            "system_type": st, "discipline": disc, "elements": _get_network(sys),
        })
    except Exception:
        pass

for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
    try:
        st, disc = _classify_pipe(sys)
        systems.append({
            "system_id": str(sys.Id.Value), "system_name": _safe_name(sys),
            "system_type": st, "discipline": disc, "elements": _get_network(sys),
        })
    except Exception:
        pass

for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
    try:
        systems.append({
            "system_id": str(sys.Id.Value), "system_name": _safe_name(sys),
            "system_type": "PowerCircuit", "discipline": "Electrical",
            "elements": _get_network(sys),
        })
    except Exception:
        pass

# ===================== FIND ORPHANS =====================
system_eids = set()
system_locs = []

for s in systems:
    for e in s["elements"]:
        system_eids.add(int(e["element_id"]))

for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
    try:
        net = sys.DuctNetwork or sys.Elements
        for elem in net:
            loc = _get_location(elem)
            if loc:
                system_locs.append((elem.Id.Value, _safe_name(sys), loc))
    except Exception:
        pass

for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
    try:
        net = sys.PipingNetwork or sys.Elements
        for elem in net:
            loc = _get_location(elem)
            if loc:
                system_locs.append((elem.Id.Value, _safe_name(sys), loc))
    except Exception:
        pass

def _nearest(xyz, count=3):
    if not xyz or not system_locs:
        return []
    dists = []
    for eid, sname, sloc in system_locs:
        d = math.sqrt(sum((a-b)**2 for a,b in zip(xyz, sloc)))
        dists.append((d, eid, sname))
    dists.sort()
    return [{"element_id": str(e), "system_name": s, "distance_ft": round(d,1)} for d,e,s in dists[:count]]

ORPHAN_CATS = [
    BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_MechanicalEquipment,
    BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_ElectricalFixtures, BuiltInCategory.OST_ElectricalEquipment,
    BuiltInCategory.OST_LightingFixtures, BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_FlexPipeCurves, BuiltInCategory.OST_FireAlarmDevices,
]

orphans = []
for bic in ORPHAN_CATS:
    try:
        for elem in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements():
            eid = elem.Id.Value
            if eid in system_eids:
                continue
            if isinstance(elem, (MechanicalSystem, PipingSystem, ElectricalSystem)):
                continue
            orphans.append({
                "element_id": str(eid),
                "category": _safe_name(elem.Category) if elem.Category else "Unknown",
                "family": _get_family_name(elem),
                "type": _get_type_name(elem),
                "level": _get_level_name(elem),
                "nearest_elements": _nearest(_get_location(elem)),
            })
    except Exception:
        pass

# ===================== OUTPUT =====================
output = {
    "building_type": "hospital",
    "systems": systems,
    "orphans": orphans,
    "_meta": {
        "model": doc.Title,
        "total_systems": len(systems),
        "total_elements": sum(len(s["elements"]) for s in systems),
        "total_orphans": len(orphans),
    }
}

OUT = json.dumps(output)
