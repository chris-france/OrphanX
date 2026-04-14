"""Orphan X — ALL-IN-ONE MEP Audit Script

ONE SCRIPT. ONE PASTE. ONE RUN.

Instructions:
1. Open your Revit model (Hospital MEP or any MEP model)
2. Open Dynamo
3. Add a Python Script node
4. Right-click node -> Engine -> CPython3
5. Double-click the node, paste this ENTIRE script
6. Click Run
7. Switch to the "Orphan X - QA Audit" 3D view in Revit

The output will show: systems found, orphans found, AI findings, and color legend.
Elements in the model will be color-coded by severity:
  RED    = Critical Patient Safety / Life Safety (dead legs, missing sprinklers)
  ORANGE = Critical Code Violation (missing vents, etc.)
  YELLOW = Major (dead-end ducts, orphaned equipment)
  CYAN   = Minor (model hygiene)
  GRAY   = Unclassified orphan

No inputs needed. No other nodes needed. Just paste and run.
"""

import clr
import json
import math
import traceback
import ssl
import urllib.request

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ConnectorType,
    ElementId,
    OverrideGraphicSettings,
    Color,
    View3D,
    ViewDuplicateOption,
    ViewFamilyType,
    ViewFamily,
    FillPatternElement,
    XYZ,
)
from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
from Autodesk.Revit.DB.Electrical import ElectricalSystem

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ============================================================================
# CONFIG
# ============================================================================
MCP_URL = "https://orphanx.chrisfrance.ai"
BUILDING_TYPE = "hospital"
VIEW_NAME = "Orphan X - QA Audit"
MAX_NEAREST = 3

doc = DocumentManager.Instance.CurrentDBDocument

def eid_int(element_id):
    """Get integer value from ElementId — works on all Revit versions."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue

log_lines = []

def log(msg):
    log_lines.append(str(msg))

log("=" * 60)
log("ORPHAN X — MEP Systems Auditor")
log("=" * 60)
log("")

# ============================================================================
# HELPERS
# ============================================================================
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

def _param_value(param):
    if param is None or not param.HasValue:
        return None
    try:
        return param.AsValueString() or param.AsString() or str(param.AsDouble())
    except Exception:
        try:
            return param.AsString()
        except Exception:
            return None

def _get_element_params(elem):
    params = {}
    interesting = [
        BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
        BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
        BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
        BuiltInParameter.RBS_CALCULATED_SIZE,
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_DUCT_SIZE_PARAM,
        BuiltInParameter.RBS_PIPE_FLOW_PARAM,
        BuiltInParameter.RBS_DUCT_FLOW_PARAM,
    ]
    for bip in interesting:
        try:
            p = elem.get_Parameter(bip)
            v = _param_value(p)
            if v:
                params[bip.ToString()] = v
        except Exception:
            pass
    for name in ["System Type", "Size", "Diameter", "Flow", "Length", "Comments"]:
        try:
            p = elem.LookupParameter(name)
            v = _param_value(p)
            if v:
                params[name] = v
        except Exception:
            pass
    return params

def _get_connected_ids(elem):
    connected = []
    try:
        conn_mgr = elem.MEPModel
        if conn_mgr is None:
            conn_mgr = elem
        connectors = conn_mgr.ConnectorManager
        if connectors is None:
            return connected
        for connector in connectors.Connectors:
            if connector.IsConnected:
                for ref_conn in connector.AllRefs:
                    owner = ref_conn.Owner
                    if owner and owner.Id != elem.Id:
                        eid = str(owner.Id.Value)
                        if eid not in connected:
                            connected.append(eid)
    except Exception:
        pass
    return connected

def _get_location_xyz(elem):
    try:
        loc = elem.Location
        if loc is None:
            return None
        if hasattr(loc, "Point"):
            pt = loc.Point
            return (pt.X, pt.Y, pt.Z)
        if hasattr(loc, "Curve"):
            curve = loc.Curve
            mid = curve.Evaluate(0.5, True)
            return (mid.X, mid.Y, mid.Z)
    except Exception:
        pass
    try:
        bb = elem.get_BoundingBox(None)
        if bb:
            return ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)
    except Exception:
        pass
    return None

def _distance(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    dz = p1[2] - p2[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)

def _serialize_element(elem):
    return {
        "element_id": str(elem.Id.Value),
        "category": _safe_name(elem.Category) if elem.Category else "Unknown",
        "family": _get_family_name(elem),
        "type": _get_type_name(elem),
        "level": _get_level_name(elem),
        "connected_to": _get_connected_ids(elem),
        "parameters": _get_element_params(elem),
    }

# System type maps — keyed by both enum AND int value for Revit 2026 compat
_DUCT_TYPE_MAP = {}
for _attr, _val in [
    ("SupplyAir", ("SupplyAir", "Mechanical")),
    ("ReturnAir", ("ReturnAir", "Mechanical")),
    ("ExhaustAir", ("Exhaust", "Mechanical")),
    ("OtherAir", ("Other", "Mechanical")),
]:
    try:
        _enum = getattr(DuctSystemType, _attr)
        _DUCT_TYPE_MAP[_enum] = _val
        _DUCT_TYPE_MAP[int(_enum)] = _val
    except (AttributeError, TypeError, ValueError):
        pass
_PIPE_TYPE_MAP = {}
for _attr, _val in [
    ("DomesticHotWater", ("DomesticHotWater", "Plumbing")),
    ("DomesticColdWater", ("DomesticColdWater", "Plumbing")),
    ("Sanitary", ("SanitaryWaste", "Plumbing")),
    ("Storm", ("Storm", "Plumbing")),
    ("Hydronic", ("Hydronic", "Mechanical")),
    ("HydronicReturn", ("Hydronic", "Mechanical")),
    ("HydronicSupply", ("Hydronic", "Mechanical")),
    ("OtherPipe", ("Other", "Plumbing")),
    ("FireProtectWet", ("Sprinkler", "FireProtection")),
    ("FireProtectDry", ("Sprinkler", "FireProtection")),
    ("FireProtectPreaction", ("Sprinkler", "FireProtection")),
    ("FireProtectOther", ("Sprinkler", "FireProtection")),
]:
    try:
        _enum = getattr(PipeSystemType, _attr)
        _PIPE_TYPE_MAP[_enum] = _val
        _PIPE_TYPE_MAP[int(_enum)] = _val
    except (AttributeError, TypeError, ValueError):
        pass

def _get_duct_type(sys):
    """Get system type string from MechanicalSystem, handles enum or int."""
    try:
        st = sys.SystemType
        if st in _DUCT_TYPE_MAP:
            return _DUCT_TYPE_MAP[st]
        if int(st) in _DUCT_TYPE_MAP:
            return _DUCT_TYPE_MAP[int(st)]
        # Fallback: try the name
        name = _safe_name(sys).lower()
        if "supply" in name: return ("SupplyAir", "Mechanical")
        if "return" in name: return ("ReturnAir", "Mechanical")
        if "exhaust" in name: return ("Exhaust", "Mechanical")
    except Exception:
        pass
    return ("Other", "Mechanical")

def _get_pipe_type(sys):
    """Get system type string from PipingSystem, handles enum or int."""
    try:
        st = sys.SystemType
        if st in _PIPE_TYPE_MAP:
            return _PIPE_TYPE_MAP[st]
        if int(st) in _PIPE_TYPE_MAP:
            return _PIPE_TYPE_MAP[int(st)]
        # Fallback: try the name
        name = _safe_name(sys).lower()
        if "hot" in name or "hwr" in name or "hws" in name: return ("DomesticHotWater", "Plumbing")
        if "cold" in name or "cw" in name or "dcw" in name: return ("DomesticColdWater", "Plumbing")
        if "sanit" in name: return ("SanitaryWaste", "Plumbing")
        if "storm" in name: return ("Storm", "Plumbing")
        if "fire" in name or "sprink" in name: return ("Sprinkler", "FireProtection")
        if "hydron" in name or "chw" in name or "hw" in name: return ("Hydronic", "Mechanical")
    except Exception:
        pass
    return ("Other", "Plumbing")

def _get_system_elements(system):
    elements = []
    seen_ids = set()
    elem_set = None
    try:
        if isinstance(system, MechanicalSystem):
            elem_set = system.DuctNetwork
        elif isinstance(system, PipingSystem):
            elem_set = system.PipingNetwork
        elif isinstance(system, ElectricalSystem):
            elem_set = system.Elements
    except Exception:
        pass
    if elem_set:
        for elem in elem_set:
            eid = elem.Id.Value
            if eid not in seen_ids:
                seen_ids.add(eid)
                elements.append(_serialize_element(elem))
    if not elements:
        try:
            for elem in system.Elements:
                eid = elem.Id.Value
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    elements.append(_serialize_element(elem))
        except Exception:
            pass
    return elements

# ============================================================================
# PHASE 1: EXTRACT MEP SYSTEMS
# ============================================================================
log("PHASE 1: Extracting MEP systems from Revit model...")
errors = []
systems_out = []

try:
    for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
        try:
            sys_type, discipline = _get_duct_type(sys)
            systems_out.append({
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            })
        except Exception as ex:
            errors.append("MechSys {}: {}".format(sys.Id.Value, str(ex)))

    for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
        try:
            sys_type, discipline = _get_pipe_type(sys)
            systems_out.append({
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            })
        except Exception as ex:
            errors.append("PipeSys {}: {}".format(sys.Id.Value, str(ex)))

    for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
        try:
            st_name = str(sys.SystemType)
            if "Light" in st_name or "light" in st_name:
                sys_type, discipline = "LightingCircuit", "Electrical"
            elif "Fire" in st_name or "fire" in st_name:
                sys_type, discipline = "FireAlarm", "Electrical"
            else:
                sys_type, discipline = "PowerCircuit", "Electrical"
            systems_out.append({
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            })
        except Exception as ex:
            errors.append("ElecSys {}: {}".format(sys.Id.Value, str(ex)))
except Exception as ex:
    errors.append("System collection error: {}".format(str(ex)))

total_elements = sum(len(s["elements"]) for s in systems_out)
log("  Found {} systems with {} elements".format(len(systems_out), total_elements))
if errors:
    log("  {} extraction errors (non-fatal)".format(len(errors)))

systems_payload = json.dumps({"building_type": BUILDING_TYPE, "systems": systems_out})

# ============================================================================
# PHASE 2: FIND ORPHANED ELEMENTS
# ============================================================================
log("")
log("PHASE 2: Finding orphaned elements...")

ORPHAN_CATEGORIES = [
    BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_PipeSegments,
    BuiltInCategory.OST_MechanicalEquipment, BuiltInCategory.OST_PlumbingFixtures,
    BuiltInCategory.OST_Sprinklers, BuiltInCategory.OST_ElectricalFixtures,
    BuiltInCategory.OST_ElectricalEquipment, BuiltInCategory.OST_LightingFixtures,
    BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_FlexDuctCurves, BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_Conduit, BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_CableTray, BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_FireAlarmDevices,
]

system_element_ids = set()
system_element_info = {}

for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
    sys_name = _safe_name(sys)
    try:
        network = sys.DuctNetwork
        if network:
            for elem in network:
                eid = elem.Id.Value
                system_element_ids.add(eid)
                if eid not in system_element_info:
                    system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
    except Exception:
        try:
            for elem in sys.Elements:
                eid = elem.Id.Value
                system_element_ids.add(eid)
                if eid not in system_element_info:
                    system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
        except Exception:
            pass

for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
    sys_name = _safe_name(sys)
    try:
        network = sys.PipingNetwork
        if network:
            for elem in network:
                eid = elem.Id.Value
                system_element_ids.add(eid)
                if eid not in system_element_info:
                    system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
    except Exception:
        try:
            for elem in sys.Elements:
                eid = elem.Id.Value
                system_element_ids.add(eid)
                if eid not in system_element_info:
                    system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
        except Exception:
            pass

for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
    sys_name = _safe_name(sys)
    try:
        for elem in sys.Elements:
            eid = elem.Id.Value
            system_element_ids.add(eid)
            if eid not in system_element_info:
                system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
    except Exception:
        pass

system_points = []
for eid, info in system_element_info.items():
    if info["xyz"] is not None:
        system_points.append((eid, info["system_name"], info["xyz"]))

def _find_nearest(orphan_xyz, count):
    if orphan_xyz is None or not system_points:
        return []
    dists = []
    for eid, sname, sxyz in system_points:
        d = _distance(orphan_xyz, sxyz)
        dists.append((d, eid, sname))
    dists.sort(key=lambda t: t[0])
    return [{"element_id": str(eid), "system_name": sname, "distance_ft": round(d, 2)} for d, eid, sname in dists[:count]]

orphans_out = []
for bic in ORPHAN_CATEGORIES:
    try:
        elems = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        for elem in elems:
            eid = elem.Id.Value
            if eid in system_element_ids:
                continue
            try:
                if isinstance(elem, (MechanicalSystem, PipingSystem, ElectricalSystem)):
                    continue
            except Exception:
                pass
            orphan_xyz = _get_location_xyz(elem)
            orphans_out.append({
                "element_id": str(eid),
                "category": _safe_name(elem.Category) if elem.Category else "Unknown",
                "family": _get_family_name(elem),
                "type": _get_type_name(elem),
                "level": _get_level_name(elem),
                "nearest_elements": _find_nearest(orphan_xyz, MAX_NEAREST),
            })
    except Exception:
        pass

log("  Found {} orphaned elements".format(len(orphans_out)))

orphans_payload = json.dumps({"building_type": BUILDING_TYPE, "orphans": orphans_out})

# ============================================================================
# PHASE 3: SEND TO ORPHAN X MCP SERVER
# ============================================================================
log("")
log("PHASE 3: Sending data to Orphan X AI server...")
log("  Server: {}".format(MCP_URL))

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def call_mcp_tool(tool_name, arg_name, arg_value):
    """Call an MCP tool via SSE + JSON-RPC and return the result."""
    try:
        # Step 1: Get session from SSE endpoint
        # SSE is streaming — read line by line, not fixed byte count
        sse_req = urllib.request.Request(MCP_URL + "/sse", method="GET")
        sse_resp = urllib.request.urlopen(sse_req, timeout=30, context=ctx)

        endpoint = None
        for _ in range(10):
            line = sse_resp.readline().decode("utf-8").strip()
            if line.startswith("data:") and "session_id" in line:
                endpoint = line.split("data:")[1].strip()
                break
        sse_resp.close()

        if not endpoint:
            return None, "Could not get session from MCP server"

        # Step 2: Call the tool via JSON-RPC POST
        tool_call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {arg_name: arg_value}
            }
        }

        post_req = urllib.request.Request(
            MCP_URL + endpoint,
            data=json.dumps(tool_call).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        post_resp = urllib.request.urlopen(post_req, timeout=120, context=ctx)
        result = post_resp.read().decode("utf-8")
        return result, None

    except Exception as ex:
        return None, "MCP call failed: {}".format(str(ex))


# Call audit_systems
log("  Calling audit_systems...")
audit_result, audit_error = call_mcp_tool("audit_systems", "systems_json", systems_payload)

audit_findings = []
if audit_error:
    log("  ERROR: {}".format(audit_error))
else:
    try:
        audit_data = json.loads(audit_result)
        # Handle nested result structure from MCP
        if "result" in audit_data:
            inner = audit_data["result"]
            if isinstance(inner, str):
                inner = json.loads(inner)
            if "content" in inner:
                for c in inner["content"]:
                    if c.get("type") == "text":
                        inner = json.loads(c["text"])
                        break
            audit_findings = inner.get("findings", [])
        else:
            audit_findings = audit_data.get("findings", [])
        log("  Got {} audit findings".format(len(audit_findings)))
        for f in audit_findings:
            log("    [{}] {}: {}".format(
                f.get("severity", "?"),
                f.get("finding_type", "?"),
                f.get("description", "")[:80]
            ))
    except Exception as ex:
        log("  Could not parse audit response: {}".format(str(ex)))
        log("  Raw (first 300 chars): {}".format(str(audit_result)[:300]))

# Call classify_orphans (only if we have orphans)
orphan_classifications = []
if orphans_out:
    log("")
    log("  Calling classify_orphans...")
    orphan_result, orphan_error = call_mcp_tool("classify_orphans", "orphans_json", orphans_payload)

    if orphan_error:
        log("  ERROR: {}".format(orphan_error))
    else:
        try:
            orphan_data = json.loads(orphan_result)
            if "result" in orphan_data:
                inner = orphan_data["result"]
                if isinstance(inner, str):
                    inner = json.loads(inner)
                if "content" in inner:
                    for c in inner["content"]:
                        if c.get("type") == "text":
                            inner = json.loads(c["text"])
                            break
                orphan_classifications = inner.get("classifications", [])
            else:
                orphan_classifications = orphan_data.get("classifications", [])
            log("  Got {} orphan classifications".format(len(orphan_classifications)))
        except Exception as ex:
            log("  Could not parse orphan response: {}".format(str(ex)))
else:
    log("  No orphans to classify, skipping.")

# ============================================================================
# PHASE 4: APPLY VISUAL OVERRIDES
# ============================================================================
log("")
log("PHASE 4: Applying visual overrides to Revit model...")

SEVERITY_COLORS = {
    "Critical - Patient Safety": Color(255, 0, 0),
    "Critical - Life Safety":    Color(255, 0, 0),
    "Critical - Code Violation": Color(255, 165, 0),
    "Major":                     Color(255, 255, 0),
    "Minor":                     Color(0, 255, 255),
    "Orphan":                    Color(180, 180, 180),
}
SEVERITY_LINE_WEIGHTS = {
    "Critical - Patient Safety": 10,
    "Critical - Life Safety":    10,
    "Critical - Code Violation": 8,
    "Major":                     6,
    "Minor":                     4,
    "Orphan":                    4,
}
SEVERITY_PRIORITY = {
    "Critical - Patient Safety": 5,
    "Critical - Life Safety":    4,
    "Critical - Code Violation": 3,
    "Major":                     2,
    "Minor":                     1,
    "Orphan":                    0,
}

def _normalize_severity(raw):
    if not raw:
        return "Orphan"
    raw_lower = raw.lower().strip()
    if "patient" in raw_lower and "safety" in raw_lower:
        return "Critical - Patient Safety"
    if "life" in raw_lower and "safety" in raw_lower:
        return "Critical - Life Safety"
    if "code" in raw_lower and "violation" in raw_lower:
        return "Critical - Code Violation"
    if "critical" in raw_lower:
        return "Critical - Patient Safety"
    if "major" in raw_lower:
        return "Major"
    if "minor" in raw_lower:
        return "Minor"
    return "Orphan"

# Build element -> severity map
element_severity = {}

for finding in audit_findings:
    severity = _normalize_severity(finding.get("severity", ""))
    for eid_str in finding.get("affected_elements", []):
        eid_str = str(eid_str)
        existing = element_severity.get(eid_str)
        if existing is None or SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(existing, 0):
            element_severity[eid_str] = severity

for cls in orphan_classifications:
    eid_str = str(cls.get("element_id", ""))
    if not eid_str:
        continue
    severity = _normalize_severity(cls.get("severity", "Orphan"))
    existing = element_severity.get(eid_str)
    if existing is None or SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(existing, 0):
        element_severity[eid_str] = severity

log("  {} elements to color-code".format(len(element_severity)))

# Find or create the QA view and apply overrides
severity_counts = {}
overrides_applied = 0

try:
    TransactionManager.Instance.EnsureInTransaction(doc)

    # Find or create view
    qa_view = None
    all_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v in all_views:
        try:
            if v.Name == VIEW_NAME and not v.IsTemplate:
                qa_view = v
                break
        except Exception:
            pass

    if qa_view is None:
        source_view = None
        try:
            active = doc.ActiveView
            if isinstance(active, View3D) and not active.IsTemplate:
                source_view = active
        except Exception:
            pass
        if source_view is None:
            for v in all_views:
                try:
                    if not v.IsTemplate:
                        source_view = v
                        break
                except Exception:
                    pass
        if source_view is not None:
            try:
                new_id = source_view.Duplicate(ViewDuplicateOption.Duplicate)
                qa_view = doc.GetElement(new_id)
                qa_view.Name = VIEW_NAME
                log("  Created view: '{}'".format(VIEW_NAME))
            except Exception as ex:
                qa_view = source_view
                log("  Using existing view (could not duplicate: {})".format(str(ex)))
        else:
            try:
                vft_collector = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
                for vft in vft_collector:
                    if vft.ViewFamily == ViewFamily.ThreeDimensional:
                        qa_view = View3D.CreateIsometric(doc, vft.Id)
                        qa_view.Name = VIEW_NAME
                        log("  Created new 3D view: '{}'".format(VIEW_NAME))
                        break
            except Exception as ex:
                log("  ERROR: Could not create view: {}".format(str(ex)))

    if qa_view:
        # Get solid fill pattern
        solid_fill_id = None
        try:
            fills = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
            for fp in fills:
                pat = fp.GetFillPattern()
                if pat and pat.IsSolidFill:
                    solid_fill_id = fp.Id
                    break
        except Exception:
            pass

        for eid_str, severity in element_severity.items():
            try:
                elem_id = ElementId(int(eid_str))
                elem = doc.GetElement(elem_id)
                if elem is None:
                    continue

                color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["Orphan"])
                line_weight = SEVERITY_LINE_WEIGHTS.get(severity, 4)

                ogs = OverrideGraphicSettings()
                ogs.SetProjectionLineColor(color)
                ogs.SetSurfaceForegroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                ogs.SetCutLineColor(color)
                ogs.SetCutForegroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetCutForegroundPatternId(solid_fill_id)
                ogs.SetProjectionLineWeight(line_weight)
                ogs.SetCutLineWeight(line_weight)

                qa_view.SetElementOverrides(elem_id, ogs)
                overrides_applied += 1
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            except Exception:
                pass

    TransactionManager.Instance.TransactionTaskDone()

except Exception as ex:
    log("  Transaction error: {}".format(str(ex)))
    try:
        TransactionManager.Instance.TransactionTaskDone()
    except Exception:
        pass

log("  Applied {} color overrides".format(overrides_applied))

# ============================================================================
# SUMMARY
# ============================================================================
log("")
log("=" * 60)
log("SUMMARY")
log("=" * 60)
log("  Systems found: {}".format(len(systems_out)))
log("  Total elements in systems: {}".format(total_elements))
log("  Orphaned elements: {}".format(len(orphans_out)))
log("  AI findings: {}".format(len(audit_findings)))
log("  Orphan classifications: {}".format(len(orphan_classifications)))
log("  Color overrides applied: {}".format(overrides_applied))
log("")
log("  SEVERITY BREAKDOWN:")
for sev in ["Critical - Patient Safety", "Critical - Life Safety", "Critical - Code Violation", "Major", "Minor", "Orphan"]:
    count = severity_counts.get(sev, 0)
    if count > 0:
        log("    {} : {} elements".format(sev, count))
log("")
log("  COLOR LEGEND:")
log("    RED         = Critical Patient Safety / Life Safety")
log("    ORANGE      = Critical Code Violation")
log("    YELLOW      = Major")
log("    CYAN        = Minor")
log("    GRAY        = Orphan (unclassified)")
log("")
log("  Switch to view '{}' to see results.".format(VIEW_NAME))
log("=" * 60)

OUT = "\n".join(log_lines)
