"""Orphan X — PLAN C: Cap Detection + Visual Pop (No MCP Server)

ONE SCRIPT. ONE PASTE. ONE RUN. NO SERVER NEEDED.

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
    ViewDetailLevel,
)
try:
    from Autodesk.Revit.DB import DisplayStyle
except ImportError:
    DisplayStyle = None
from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
from Autodesk.Revit.DB.Electrical import ElectricalSystem

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ============================================================================
# CONFIG
# ============================================================================
ANTHROPIC_API_KEY = "PASTE_KEY_FROM_TEAMS_CHAT_HERE"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-6"
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
    # Try Symbol.Family.Name (loaded families)
    try:
        sym = elem.Symbol
        if sym and sym.Family:
            n = str(sym.Family.Name)
            if n:
                return n
    except Exception:
        pass
    # Try type's FamilyName property (system families like pipes/fittings)
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype and hasattr(etype, "FamilyName"):
            n = str(etype.FamilyName)
            if n:
                return n
    except Exception:
        pass
    # Try BuiltInParameter
    try:
        p = elem.get_Parameter(BuiltInParameter.ELEM_FAMILY_PARAM)
        if p:
            n = p.AsValueString()
            if n:
                return n
    except Exception:
        pass
    # Nuclear fallback: elem.Name often contains family:type info
    try:
        n = str(elem.Name)
        if n:
            return n
    except Exception:
        pass
    return "Unknown"

def _get_type_name(elem):
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype:
            n = str(etype.Name) if hasattr(etype, "Name") else None
            if n:
                return n
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
        if p:
            n = p.AsValueString()
            if n:
                return n
    except Exception:
        pass
    # Nuclear fallback
    try:
        n = str(elem.Name)
        if n:
            return n
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
            try:
                if connector.IsConnected:
                    for ref_conn in connector.AllRefs:
                        owner = ref_conn.Owner
                        if owner and eid_int(owner.Id) != eid_int(elem.Id):
                            eid = str(eid_int(owner.Id))
                            if eid not in connected:
                                connected.append(eid)
            except Exception:
                pass
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
        "element_id": str(eid_int(elem.Id)),
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
    """Get elements from system — tries network properties first, then .Elements."""
    elements = []
    seen_ids = set()

    sources = []
    try:
        if isinstance(system, MechanicalSystem):
            try: sources.append(system.DuctNetwork)
            except Exception: pass
        elif isinstance(system, PipingSystem):
            try: sources.append(system.PipingNetwork)
            except Exception: pass
    except Exception:
        pass
    try: sources.append(system.Elements)
    except Exception: pass

    for source in sources:
        if source is None:
            continue
        try:
            for elem in source:
                try:
                    eid = eid_int(elem.Id)
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        elements.append(_serialize_element(elem))
                except Exception:
                    pass
        except Exception:
            pass
        if elements:
            break

    return elements


# Pre-build a map of elements→system by scanning all MEP elements
# This is the REVERSE approach: instead of asking systems for elements,
# ask elements which system they belong to.
log("  Building element-to-system index...")
_elem_to_system = {}
_MEP_CATS = [
    BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting, BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory, BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_FlexPipeCurves, BuiltInCategory.OST_PipeSegments,
    BuiltInCategory.OST_MechanicalEquipment, BuiltInCategory.OST_PlumbingFixtures,
    BuiltInCategory.OST_Sprinklers, BuiltInCategory.OST_ElectricalEquipment,
    BuiltInCategory.OST_ElectricalFixtures, BuiltInCategory.OST_LightingFixtures,
    BuiltInCategory.OST_Conduit, BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_FireAlarmDevices,
]
for bic in _MEP_CATS:
    try:
        for elem in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements():
            try:
                sys_param = elem.get_Parameter(BuiltInParameter.RBS_SYSTEM_NAME_PARAM)
                if sys_param and sys_param.HasValue:
                    sys_name = sys_param.AsString()
                    if sys_name:
                        eid = eid_int(elem.Id)
                        for sn in sys_name.split(","):
                            sn = sn.strip()
                            if sn:
                                if sn not in _elem_to_system:
                                    _elem_to_system[sn] = []
                                _elem_to_system[sn].append((eid, elem))
            except Exception:
                pass
    except Exception:
        pass
log("  Indexed {} system names across {} elements".format(
    len(_elem_to_system), sum(len(v) for v in _elem_to_system.values())))

# ============================================================================
# PHASE 1: EXTRACT MEP SYSTEMS (index-first approach)
# ============================================================================
log("PHASE 1: Extracting MEP systems from Revit model...")
errors = []
systems_out = []

# Step 1: Collect metadata from system objects (name -> id, type, discipline)
_sys_meta = {}
try:
    for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
        try:
            sys_type, discipline = _get_duct_type(sys)
            _sys_meta[_safe_name(sys)] = (str(eid_int(sys.Id)), sys_type, discipline)
        except Exception as ex:
            errors.append("MechMeta: {}".format(str(ex)))
    for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
        try:
            sys_type, discipline = _get_pipe_type(sys)
            _sys_meta[_safe_name(sys)] = (str(eid_int(sys.Id)), sys_type, discipline)
        except Exception as ex:
            errors.append("PipeMeta: {}".format(str(ex)))
    for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
        try:
            st_name = str(sys.SystemType)
            if "Light" in st_name or "light" in st_name:
                sys_type, discipline = "LightingCircuit", "Electrical"
            elif "Fire" in st_name or "fire" in st_name:
                sys_type, discipline = "FireAlarm", "Electrical"
            else:
                sys_type, discipline = "PowerCircuit", "Electrical"
            _sys_meta[_safe_name(sys)] = (str(eid_int(sys.Id)), sys_type, discipline)
        except Exception as ex:
            errors.append("ElecMeta: {}".format(str(ex)))
except Exception as ex:
    errors.append("System metadata error: {}".format(str(ex)))

log("  Collected metadata for {} system objects".format(len(_sys_meta)))

# Step 2: Build systems from reverse index (guaranteed to have elements)
_used_sys_names = set()
for sys_name, elem_list in _elem_to_system.items():
    elems = []
    for eid, elem in elem_list:
        try:
            elems.append({
                "element_id": str(eid),
                "category": _safe_name(elem.Category) if elem.Category else "Unknown",
                "family": _get_family_name(elem),
                "type": _get_type_name(elem),
                "level": _get_level_name(elem),
                "connected_to": _get_connected_ids(elem),
                "parameters": _get_element_params(elem),
            })
        except Exception:
            try:
                elems.append({
                    "element_id": str(eid),
                    "category": str(elem.Category.Name) if elem.Category else "Unknown",
                    "family": "Unknown",
                    "type": "Unknown",
                    "level": "Unknown",
                    "connected_to": [],
                    "parameters": {},
                })
            except Exception:
                pass
    if sys_name in _sys_meta:
        sid, stype, disc = _sys_meta[sys_name]
        _used_sys_names.add(sys_name)
    else:
        sid = "idx-" + sys_name
        stype = "Other"
        disc = "Unknown"
        name_lower = sys_name.lower()
        if any(k in name_lower for k in ["supply", "return", "exhaust", "vav", "ahu", "fcu"]):
            stype, disc = "SupplyAir", "Mechanical"
        elif any(k in name_lower for k in ["hot", "hws", "hwr", "dhw"]):
            stype, disc = "DomesticHotWater", "Plumbing"
        elif any(k in name_lower for k in ["cold", "cw", "dcw"]):
            stype, disc = "DomesticColdWater", "Plumbing"
        elif any(k in name_lower for k in ["sanit", "waste", "sewer"]):
            stype, disc = "SanitaryWaste", "Plumbing"
        elif any(k in name_lower for k in ["fire", "sprink"]):
            stype, disc = "Sprinkler", "FireProtection"
        elif any(k in name_lower for k in ["storm", "rain"]):
            stype, disc = "Storm", "Plumbing"
    systems_out.append({
        "system_id": sid,
        "system_name": sys_name,
        "system_type": stype,
        "discipline": disc,
        "elements": elems,
    })

# Step 3: Add system objects that had no elements in the index (empty systems)
for sys_name, (sid, stype, disc) in _sys_meta.items():
    if sys_name not in _used_sys_names and sys_name not in _elem_to_system:
        systems_out.append({
            "system_id": sid,
            "system_name": sys_name,
            "system_type": stype,
            "discipline": disc,
            "elements": [],
        })

total_elements = sum(len(s["elements"]) for s in systems_out)
log("  Found {} systems with {} elements".format(len(systems_out), total_elements))
if errors:
    log("  {} extraction errors (non-fatal)".format(len(errors)))
    for e in errors[:5]:
        log("    ERROR: {}".format(e))

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

def _collect_system_members(sys_obj, sys_name):
    """Collect element IDs from a system using all available methods."""
    sources = []
    if isinstance(sys_obj, MechanicalSystem):
        try: sources.append(sys_obj.DuctNetwork)
        except Exception: pass
    elif isinstance(sys_obj, PipingSystem):
        try: sources.append(sys_obj.PipingNetwork)
        except Exception: pass
    try: sources.append(sys_obj.Elements)
    except Exception: pass
    for source in sources:
        if source is None:
            continue
        try:
            for elem in source:
                try:
                    eid = eid_int(elem.Id)
                    system_element_ids.add(eid)
                    if eid not in system_element_info:
                        system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
                except Exception:
                    pass
        except Exception:
            pass

for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements():
    _collect_system_members(sys, _safe_name(sys))

for sys in FilteredElementCollector(doc).OfClass(PipingSystem).ToElements():
    _collect_system_members(sys, _safe_name(sys))

for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements():
    sys_name = _safe_name(sys)
    try:
        for elem in sys.Elements:
            eid = eid_int(elem.Id)
            system_element_ids.add(eid)
            if eid not in system_element_info:
                system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}
    except Exception:
        pass

# Also add elements from reverse index (catches elements the network iteration missed)
for sys_name, elem_list in _elem_to_system.items():
    for eid, elem in elem_list:
        system_element_ids.add(eid)
        if eid not in system_element_info:
            system_element_info[eid] = {"system_name": sys_name, "xyz": _get_location_xyz(elem)}

log("  {} elements identified as belonging to systems".format(len(system_element_ids)))

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
            eid = eid_int(elem.Id)
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
# PHASE 3: CALL CLAUDE API DIRECTLY (no MCP server)
# ============================================================================
log("")
log("PHASE 3: Calling Claude AI directly...")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

AUDIT_PROMPT = """You are an expert MEP systems integrity auditor for a HOSPITAL BIM model.
You receive system SUMMARIES with category counts and cap/plug indicators.

## DEAD LEG DETECTION

Each system has "categories" (element counts by type) and optionally "caps_plugs" (count of pipe caps/plugs/blind flanges).

TWO ways to detect dead legs:
1. CAPPED PIPE: System has "caps_plugs" > 0. A cap on a water pipe = sealed dead-end = stagnant water. ASHRAE 188 violation.
2. NO FIXTURES: Domestic water system (HWS/HWR/CWS) with Pipes but 0 Plumbing Fixtures = water goes nowhere.

Both are Critical-Patient Safety in a hospital. Legionella kills immunocompromised patients.

## OTHER ISSUES
- MISSING COMPONENT: Sanitary without vents (IPC 901.2). Sprinkler without heads (NFPA 13).
- DEAD END: System with only 1-3 elements and no terminal equipment.
- INCOMPLETE CHAIN: Pipes/fittings but no terminal elements.

SEVERITY: Critical-Patient Safety, Critical-Life Safety, Critical-Code Violation, Major, Minor
Skip systems named FUTURE or with fewer than 2 elements.

Return at most 15 findings, prioritize Critical. Keep descriptions under 30 words.
Return ONLY valid JSON, no markdown, no code fences:
{"findings": [{"system_id":"...", "system_name":"...", "finding_type":"dead_leg|capped_dead_leg|incomplete_chain|dead_end|missing_component", "severity":"Critical-Patient Safety", "description":"short", "recommendation":"short", "code_reference":"ASHRAE 188"}]}"""

CLASSIFY_PROMPT = """You are an MEP expert classifying orphaned Revit elements not in any system.
For each: determine likely system, severity, action.
Sprinkler heads = Critical-Life Safety. Plumbing in hospital = Critical-Patient Safety. HVAC in patient rooms = Major.

Return at most 30 classifications, prioritize Critical severity. Keep reasoning under 20 words.
Return ONLY valid JSON (no markdown, no code fences): {"classifications": [{"element_id":"...", "likely_system_type":"...", "confidence":0-100, "reasoning":"short", "severity":"...", "action":"short"}]}"""

def call_claude(system_prompt, user_msg, max_tokens=16384):
    """Call Claude API directly via urllib — no SDK, no MCP, no server."""
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}],
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    resp = urllib.request.urlopen(req, timeout=180, context=ctx)
    data = json.loads(resp.read().decode("utf-8"))
    return data["content"][0]["text"]

def parse_json(text):
    """Extract JSON from Claude response — handles markdown, truncation, messy output."""
    import re
    # Strip markdown fences
    clean = text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()
    # Try parsing as-is
    try:
        return json.loads(clean)
    except Exception:
        pass
    # Try to find the largest valid JSON object
    m = re.search(r'\{[\s\S]*\}', clean)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    # Truncated JSON repair: close open brackets
    repaired = clean
    if repaired.count("[") > repaired.count("]"):
        # Find last complete item (ends with })
        last_brace = repaired.rfind("}")
        if last_brace > 0:
            repaired = repaired[:last_brace + 1]
            repaired += "]" * (repaired.count("[") - repaired.count("]"))
            repaired += "}" * (repaired.count("{") - repaired.count("}"))
            try:
                return json.loads(repaired)
            except Exception:
                pass
    return None

# Call audit_systems — pipes only (where dead legs live)
audit_findings = []
_PIPE_TYPES = {"DomesticHotWater", "DomesticColdWater", "SanitaryWaste", "Storm",
               "Hydronic", "Sprinkler", "Other"}
_PIPE_DISCIPLINES = {"Plumbing", "FireProtection"}
pipe_summaries = []
system_id_to_elements = {}
total_caps = 0
for s in systems_out:
    if not s.get("elements"):
        continue
    if s["system_type"] not in _PIPE_TYPES and s["discipline"] not in _PIPE_DISCIPLINES:
        continue
    elem_ids = [str(e["element_id"]) for e in s["elements"]]
    system_id_to_elements[str(s["system_id"])] = elem_ids
    cat_counts = {}
    cap_count = 0
    _CAP_KEYWORDS = ("cap", "plug", "blind", "dead end", "test tee", "stub", "capped", "endcap")
    for e in s["elements"]:
        cat = e.get("category", "Unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        fam_lower = e.get("family", "").lower()
        type_lower = e.get("type", "").lower()
        if any(kw in fam_lower or kw in type_lower for kw in _CAP_KEYWORDS):
            cap_count += 1
    total_caps += cap_count
    summary = {
        "system_id": s["system_id"], "system_name": s["system_name"],
        "system_type": s["system_type"], "element_count": len(elem_ids),
        "categories": cat_counts,
    }
    if cap_count > 0:
        summary["caps_plugs"] = cap_count
    pipe_summaries.append(summary)
# Debug: show unique families — especially pipe fittings (where caps live)
all_families = set()
fitting_families = set()
for s in systems_out:
    for e in s.get("elements", []):
        f = e.get("family", "Unknown")
        t = e.get("type", "Unknown")
        if f != "Unknown":
            all_families.add(f)
        if e.get("category", "") in ("Pipe Fittings", "Pipe Accessories"):
            fitting_families.add("{} : {}".format(f, t))
if all_families:
    sample = sorted(all_families)[:10]
    log("  Sample families: {}".format(", ".join(sample)))
else:
    log("  WARNING: All families are 'Unknown' — cap detection won't work")
if fitting_families:
    log("  Pipe fitting families: {}".format(", ".join(sorted(fitting_families)[:10])))
else:
    log("  No pipe fitting families found — caps may not be categorized as Pipe Fittings")
log("  {} piping systems, {} total caps/plugs detected".format(len(pipe_summaries), total_caps))
if pipe_summaries:
    log("  Auditing {} piping systems (summary mode)...".format(len(pipe_summaries)))
    try:
        audit_payload = json.dumps({"building_type": BUILDING_TYPE, "systems": pipe_summaries})
        log("  Payload size: {} bytes".format(len(audit_payload)))
        user_msg = "Analyze these MEP systems. Return ONLY JSON with findings array.\n\n" + audit_payload
        raw = call_claude(AUDIT_PROMPT, user_msg)
        log("  Claude response (first 500 chars): {}".format(raw[:500]))
        parsed = parse_json(raw)
        if parsed:
            audit_findings = parsed.get("findings", [])
        else:
            log("  WARNING: Could not parse Claude response as JSON")
        log("  Got {} audit findings".format(len(audit_findings)))
        for f in audit_findings:
            log("    [{}] {}: {}".format(
                f.get("severity", "?"), f.get("finding_type", "?"),
                f.get("description", "")[:80]))
    except Exception as ex:
        log("  ERROR calling Claude for audit: {}".format(str(ex)))
else:
    log("  No systems with elements to audit")

# Call classify_orphans
orphan_classifications = []
if orphans_out:
    log("  Classifying {} orphans...".format(len(orphans_out)))
    try:
        user_msg = "Classify these orphans. Return ONLY JSON with classifications array.\n\n" + orphans_payload
        raw = call_claude(CLASSIFY_PROMPT, user_msg)
        log("  Orphan response (first 500 chars): {}".format(raw[:500]))
        parsed = parse_json(raw)
        if parsed:
            orphan_classifications = parsed.get("classifications", [])
        else:
            log("  WARNING: Could not parse orphan response as JSON")
        log("  Got {} orphan classifications".format(len(orphan_classifications)))
    except Exception as ex:
        log("  ERROR calling Claude for orphans: {}".format(str(ex)))
else:
    log("  No orphans to classify")

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

# Build element -> severity map using system_id -> elements lookup
element_severity = {}

for finding in audit_findings:
    severity = _normalize_severity(finding.get("severity", ""))
    sid = str(finding.get("system_id", ""))
    elem_ids = system_id_to_elements.get(sid, [])
    if not elem_ids:
        elem_ids = [str(e) for e in finding.get("affected_elements", [])]
    log("    Coloring {} ({}) — {} elements".format(
        finding.get("system_name", "?"), severity, len(elem_ids)))
    for eid_str in elem_ids:
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
        # Disable section box and crop so we see the ENTIRE model
        try:
            qa_view.IsSectionBoxActive = False
        except Exception:
            pass
        try:
            qa_view.CropBoxActive = False
        except Exception:
            pass

        # Set view to Shaded + Fine detail so color overrides persist at ALL zoom levels
        try:
            if DisplayStyle is not None:
                qa_view.DisplayStyle = DisplayStyle.ShadingWithEdges
                log("  View set to ShadingWithEdges")
        except Exception as ex:
            log("  Set view to Shaded manually if colors don't show: {}".format(str(ex)))
        try:
            qa_view.DetailLevel = ViewDetailLevel.Fine
            log("  View detail level set to Fine")
        except Exception as ex:
            log("  Could not set detail level: {}".format(str(ex)))

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

        # Helper: build override settings that work at ALL zoom levels
        def _build_ogs(color, line_weight, halftone):
            ogs = OverrideGraphicSettings()
            # Lines (visible at all zoom levels)
            ogs.SetProjectionLineColor(color)
            ogs.SetCutLineColor(color)
            ogs.SetProjectionLineWeight(line_weight)
            ogs.SetCutLineWeight(line_weight)
            # Surface FOREGROUND pattern (the fill)
            ogs.SetSurfaceForegroundPatternColor(color)
            if solid_fill_id:
                ogs.SetSurfaceForegroundPatternId(solid_fill_id)
            # Surface BACKGROUND pattern (covers what foreground doesn't)
            try:
                ogs.SetSurfaceBackgroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
            except Exception:
                pass
            # Cut patterns (for section views)
            ogs.SetCutForegroundPatternColor(color)
            if solid_fill_id:
                ogs.SetCutForegroundPatternId(solid_fill_id)
            try:
                ogs.SetCutBackgroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetCutBackgroundPatternId(solid_fill_id)
            except Exception:
                pass
            # Transparency and halftone
            try:
                ogs.SetSurfaceTransparency(0)
            except Exception:
                pass
            ogs.SetHalftone(halftone)
            return ogs

        # STEP 1: Gray out ALL MEP elements so findings pop
        gray_color = Color(210, 210, 210)
        gray_ogs = _build_ogs(gray_color, 1, True)

        gray_count = 0
        mep_cats = [
            BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_PipeCurves,
            BuiltInCategory.OST_DuctFitting, BuiltInCategory.OST_PipeFitting,
            BuiltInCategory.OST_DuctAccessory, BuiltInCategory.OST_PipeAccessory,
            BuiltInCategory.OST_MechanicalEquipment, BuiltInCategory.OST_PlumbingFixtures,
            BuiltInCategory.OST_Sprinklers, BuiltInCategory.OST_DuctTerminal,
            BuiltInCategory.OST_FlexDuctCurves, BuiltInCategory.OST_FlexPipeCurves,
        ]
        for bic in mep_cats:
            try:
                for elem in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements():
                    try:
                        qa_view.SetElementOverrides(elem.Id, gray_ogs)
                        gray_count += 1
                    except Exception:
                        pass
            except Exception:
                pass
        log("  Grayed out {} MEP elements as background".format(gray_count))

        # STEP 2: Override flagged elements with bright severity colors
        # Pre-build an OGS per severity level (faster than building per element)
        severity_ogs_cache = {}
        for sev_name in SEVERITY_COLORS:
            color = SEVERITY_COLORS[sev_name]
            lw = SEVERITY_LINE_WEIGHTS.get(sev_name, 4)
            severity_ogs_cache[sev_name] = _build_ogs(color, lw, False)

        for eid_str, severity in element_severity.items():
            try:
                elem_id = ElementId(int(eid_str))
                elem = doc.GetElement(elem_id)
                if elem is None:
                    continue
                ogs = severity_ogs_cache.get(severity, severity_ogs_cache.get("Orphan"))
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

# ============================================================================
# SAVE FILES TO DESKTOP
# ============================================================================
import os
import tempfile

# Try Desktop, then Documents, then home, then temp
desktop = None
home = os.path.expanduser("~")
for folder in ["Desktop", "Documents", ""]:
    test_path = os.path.join(home, folder) if folder else home
    if os.path.isdir(test_path):
        try:
            test_file = os.path.join(test_path, "_orphanx_test.tmp")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            desktop = test_path
            break
        except Exception:
            continue
if desktop is None:
    desktop = tempfile.gettempdir()

# Save log file
log_text = "\n".join(log_lines)
try:
    log_path = os.path.join(desktop, "orphanx_log.txt")
    with open(log_path, "w") as f:
        f.write(log_text)
    log("Saved log to: {}".format(log_path))
except Exception as ex:
    log("Could not save log: {}".format(str(ex)))

# Save full results as JSON (for debugging and Chris to analyze)
results = {
    "summary": {
        "systems_found": len(systems_out),
        "total_elements": total_elements,
        "orphaned_elements": len(orphans_out),
        "ai_findings": len(audit_findings),
        "orphan_classifications": len(orphan_classifications),
        "overrides_applied": overrides_applied,
    },
    "audit_findings": audit_findings,
    "orphan_classifications": orphan_classifications,
    "extraction_errors": errors[:20],
}
try:
    results_path = os.path.join(desktop, "orphanx_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    log("Saved results to: {}".format(results_path))
except Exception as ex:
    log("Could not save results: {}".format(str(ex)))

# Save raw extraction data (so Chris can run it through AI manually if needed)
try:
    extract_path = os.path.join(desktop, "orphanx_extraction.json")
    with open(extract_path, "w") as f:
        json.dump({
            "building_type": BUILDING_TYPE,
            "systems": systems_out[:50],
            "orphans": orphans_out[:100],
            "_meta": {
                "total_systems": len(systems_out),
                "total_elements": total_elements,
                "total_orphans": len(orphans_out),
            }
        }, f, indent=2)
    log("Saved extraction to: {}".format(extract_path))
except Exception as ex:
    log("Could not save extraction: {}".format(str(ex)))

OUT = "\n".join(log_lines)
