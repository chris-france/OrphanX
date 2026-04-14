"""Orphan X — Find Orphaned MEP Elements in Revit Model

Dynamo for Revit Python Script node.
Finds all MEP elements that are NOT connected to any system, then locates
the nearest system elements for each orphan to help the AI classify them.

IN[0]: building_type (string) — "hospital", "commercial", etc.
       Defaults to "hospital" if not provided.
IN[1]: max_nearest (int) — number of nearest system elements to return per orphan.
       Defaults to 3 if not provided.

OUT: JSON string ready to send to the Orphan X MCP classify_orphans tool.

Revit API: 2024/2025 compatible (CPython3 engine in Dynamo 2.x / 3.x).
"""

import clr
import json
import math
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    XYZ,
    ElementId,
)
from Autodesk.Revit.DB.Mechanical import MechanicalSystem
from Autodesk.Revit.DB.Plumbing import PipingSystem
from Autodesk.Revit.DB.Electrical import ElectricalSystem

from RevitServices.Persistence import DocumentManager

# ---------------------------------------------------------------------------
# Document handle
# ---------------------------------------------------------------------------
doc = DocumentManager.Instance.CurrentDBDocument

def eid_int(element_id):
    """Get integer value from ElementId — works on all Revit versions."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
building_type = "hospital"
try:
    if IN[0] and str(IN[0]).strip():
        building_type = str(IN[0]).strip().lower()
except Exception:
    pass

max_nearest = 3
try:
    if IN[1]:
        max_nearest = int(IN[1])
except Exception:
    pass

# ---------------------------------------------------------------------------
# MEP categories to check for orphans
# ---------------------------------------------------------------------------
ORPHAN_CATEGORIES = [
    BuiltInCategory.OST_DuctTerminal,          # Air Terminals
    BuiltInCategory.OST_DuctFitting,            # Duct Fittings
    BuiltInCategory.OST_PipeFitting,            # Pipe Fittings
    BuiltInCategory.OST_PipeSegments,           # Pipe Segments
    BuiltInCategory.OST_MechanicalEquipment,    # Mechanical Equipment
    BuiltInCategory.OST_PlumbingFixtures,       # Plumbing Fixtures
    BuiltInCategory.OST_Sprinklers,             # Sprinklers
    BuiltInCategory.OST_ElectricalFixtures,     # Electrical Fixtures
    BuiltInCategory.OST_ElectricalEquipment,    # Electrical Equipment
    BuiltInCategory.OST_LightingFixtures,       # Lighting Fixtures
    BuiltInCategory.OST_DuctCurves,             # Ducts
    BuiltInCategory.OST_PipeCurves,             # Pipes
    BuiltInCategory.OST_FlexDuctCurves,         # Flex Ducts
    BuiltInCategory.OST_FlexPipeCurves,         # Flex Pipes
    BuiltInCategory.OST_Conduit,                # Conduit
    BuiltInCategory.OST_ConduitFitting,         # Conduit Fittings
    BuiltInCategory.OST_CableTray,              # Cable Tray
    BuiltInCategory.OST_CableTrayFitting,       # Cable Tray Fittings
    BuiltInCategory.OST_FireAlarmDevices,        # Fire Alarm Devices
]


# ---------------------------------------------------------------------------
# Helper functions (shared logic with extract_mep_systems.py)
# ---------------------------------------------------------------------------
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
        fam = elem.Symbol
        if fam:
            return _safe_name(fam.Family)
    except Exception:
        pass
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype:
            return _safe_name(etype.FamilyName) if hasattr(etype, "FamilyName") else _safe_name(etype)
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
        level_id = elem.LevelId
        if level_id and eid_int(level_id) > 0:
            level = doc.GetElement(level_id)
            if level:
                return level.Name
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
        if p and p.HasValue:
            return p.AsValueString()
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
        if p and p.HasValue:
            return p.AsValueString()
    except Exception:
        pass
    return "Unknown"


def _get_location_xyz(elem):
    """Return (x, y, z) tuple for an element's location, or None."""
    try:
        loc = elem.Location
        if loc is None:
            return None
        # LocationPoint (equipment, fixtures, terminals)
        if hasattr(loc, "Point"):
            pt = loc.Point
            return (pt.X, pt.Y, pt.Z)
        # LocationCurve (pipes, ducts, conduit)
        if hasattr(loc, "Curve"):
            curve = loc.Curve
            mid = curve.Evaluate(0.5, True)
            return (mid.X, mid.Y, mid.Z)
    except Exception:
        pass
    # Fallback: try bounding box center
    try:
        bb = elem.get_BoundingBox(None)
        if bb:
            cx = (bb.Min.X + bb.Max.X) / 2.0
            cy = (bb.Min.Y + bb.Max.Y) / 2.0
            cz = (bb.Min.Z + bb.Max.Z) / 2.0
            return (cx, cy, cz)
    except Exception:
        pass
    return None


def _distance(p1, p2):
    """Euclidean distance between two (x,y,z) tuples, in feet."""
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    dz = p1[2] - p2[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# ---------------------------------------------------------------------------
# Step 1: Collect all element IDs that belong to a system
# ---------------------------------------------------------------------------
errors = []
system_element_ids = set()
system_element_info = {}  # element_id_int -> {"system_name": ..., "xyz": ...}

try:
    # -- Mechanical Systems --
    for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
        sys_name = _safe_name(sys)
        try:
            network = sys.DuctNetwork
            if network:
                for elem in network:
                    eid = elem.Id.Value
                    system_element_ids.add(eid)
                    if eid not in system_element_info:
                        system_element_info[eid] = {
                            "system_name": sys_name,
                            "xyz": _get_location_xyz(elem),
                        }
        except Exception:
            try:
                for elem in sys.Elements:
                    eid = elem.Id.Value
                    system_element_ids.add(eid)
                    if eid not in system_element_info:
                        system_element_info[eid] = {
                            "system_name": sys_name,
                            "xyz": _get_location_xyz(elem),
                        }
            except Exception:
                pass

    # -- Piping Systems --
    for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
        sys_name = _safe_name(sys)
        try:
            network = sys.PipingNetwork
            if network:
                for elem in network:
                    eid = elem.Id.Value
                    system_element_ids.add(eid)
                    if eid not in system_element_info:
                        system_element_info[eid] = {
                            "system_name": sys_name,
                            "xyz": _get_location_xyz(elem),
                        }
        except Exception:
            try:
                for elem in sys.Elements:
                    eid = elem.Id.Value
                    system_element_ids.add(eid)
                    if eid not in system_element_info:
                        system_element_info[eid] = {
                            "system_name": sys_name,
                            "xyz": _get_location_xyz(elem),
                        }
            except Exception:
                pass

    # -- Electrical Systems --
    for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
        sys_name = _safe_name(sys)
        try:
            for elem in sys.Elements:
                eid = elem.Id.Value
                system_element_ids.add(eid)
                if eid not in system_element_info:
                    system_element_info[eid] = {
                        "system_name": sys_name,
                        "xyz": _get_location_xyz(elem),
                    }
        except Exception:
            pass

except Exception as ex:
    errors.append("System collection error: {}".format(traceback.format_exc()))


# ---------------------------------------------------------------------------
# Step 2: Build spatial index of system elements for nearest-neighbor lookup
# ---------------------------------------------------------------------------
# Flat list of (element_id_int, system_name, xyz) for located system elements
system_points = []
for eid, info in system_element_info.items():
    if info["xyz"] is not None:
        system_points.append((eid, info["system_name"], info["xyz"]))


def _find_nearest(orphan_xyz, count):
    """Return list of {"element_id", "system_name", "distance_ft"} for the N
    nearest system elements to orphan_xyz."""
    if orphan_xyz is None or not system_points:
        return []
    dists = []
    for eid, sname, sxyz in system_points:
        d = _distance(orphan_xyz, sxyz)
        dists.append((d, eid, sname))
    dists.sort(key=lambda t: t[0])
    results = []
    for d, eid, sname in dists[:count]:
        results.append({
            "element_id": str(eid),
            "system_name": sname,
            "distance_ft": round(d, 2),
        })
    return results


# ---------------------------------------------------------------------------
# Step 3: Collect orphaned elements
# ---------------------------------------------------------------------------
orphans_out = []

try:
    for bic in ORPHAN_CATEGORIES:
        try:
            elems = (
                FilteredElementCollector(doc)
                .OfCategory(bic)
                .WhereElementIsNotElementType()
                .ToElements()
            )
            for elem in elems:
                eid = elem.Id.Value
                # Skip if this element is already in a system
                if eid in system_element_ids:
                    continue
                # Skip if this is the system element itself (system objects
                # show up as elements too)
                try:
                    if isinstance(elem, (MechanicalSystem, PipingSystem, ElectricalSystem)):
                        continue
                except Exception:
                    pass

                orphan_xyz = _get_location_xyz(elem)
                nearest = _find_nearest(orphan_xyz, max_nearest)

                orphan_data = {
                    "element_id": str(eid),
                    "category": _safe_name(elem.Category) if elem.Category else "Unknown",
                    "family": _get_family_name(elem),
                    "type": _get_type_name(elem),
                    "level": _get_level_name(elem),
                    "nearest_elements": nearest,
                }
                orphans_out.append(orphan_data)
        except Exception as ex:
            errors.append("Category {} error: {}".format(bic.ToString(), str(ex)))

except Exception as ex:
    errors.append("Orphan scan error: {}".format(traceback.format_exc()))

# ---------------------------------------------------------------------------
# Build output payload
# ---------------------------------------------------------------------------
output = {
    "building_type": building_type,
    "orphans": orphans_out,
}

output["_metadata"] = {
    "total_orphans": len(orphans_out),
    "total_system_elements": len(system_element_ids),
    "categories_scanned": len(ORPHAN_CATEGORIES),
    "errors": errors if errors else None,
}

OUT = json.dumps(output, indent=2)
