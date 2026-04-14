"""Orphan X — Extract MEP Systems from Revit Model

Dynamo for Revit Python Script node.
Extracts all MEP systems (Mechanical, Piping, Electrical) and their elements,
serializes to JSON matching the audit_systems MCP tool schema.

IN[0]: building_type (string) — "hospital", "commercial", "residential", "laboratory"
       Defaults to "hospital" if not provided.

OUT: JSON string ready to send to the Orphan X MCP audit_systems tool.

Revit API: 2024/2025 compatible (CPython3 engine in Dynamo 2.x / 3.x).
"""

import clr
import json
import sys
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ConnectorType,
    XYZ,
)
from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
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
# Input — building type
# ---------------------------------------------------------------------------
building_type = "hospital"
try:
    if IN[0] and str(IN[0]).strip():
        building_type = str(IN[0]).strip().lower()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Helper: map Revit system types to our schema strings
# ---------------------------------------------------------------------------

_DUCT_TYPE_MAP = {}
for _attr, _val in [
    ("SupplyAir", ("SupplyAir", "Mechanical")),
    ("ReturnAir", ("ReturnAir", "Mechanical")),
    ("ExhaustAir", ("Exhaust", "Mechanical")),
    ("OtherAir", ("Other", "Mechanical")),
]:
    try:
        _DUCT_TYPE_MAP[getattr(DuctSystemType, _attr)] = _val
    except AttributeError:
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
        _PIPE_TYPE_MAP[getattr(PipeSystemType, _attr)] = _val
    except AttributeError:
        pass


def _get_system_type_and_discipline_mech(system):
    """Return (system_type_str, discipline_str) for a MechanicalSystem."""
    try:
        dst = system.SystemType
        return _DUCT_TYPE_MAP.get(dst, ("Other", "Mechanical"))
    except Exception:
        return ("Other", "Mechanical")


def _get_system_type_and_discipline_pipe(system):
    """Return (system_type_str, discipline_str) for a PipingSystem."""
    try:
        pst = system.SystemType
        return _PIPE_TYPE_MAP.get(pst, ("Other", "Plumbing"))
    except Exception:
        return ("Other", "Plumbing")


def _get_system_type_and_discipline_elec(system):
    """Return (system_type_str, discipline_str) for an ElectricalSystem."""
    try:
        st = system.SystemType
        st_name = str(st)
        if "Power" in st_name or "power" in st_name:
            return ("PowerCircuit", "Electrical")
        if "Light" in st_name or "light" in st_name:
            return ("LightingCircuit", "Electrical")
        if "Fire" in st_name or "fire" in st_name:
            return ("FireAlarm", "Electrical")
        return ("PowerCircuit", "Electrical")
    except Exception:
        return ("PowerCircuit", "Electrical")


# ---------------------------------------------------------------------------
# Helper: safe parameter value extraction
# ---------------------------------------------------------------------------
def _param_value(param):
    """Return the display string or storage value of a Parameter, or None."""
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
    """Return a dict of useful parameters for an element."""
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
    # Also grab a few common named parameters
    for name in ["System Type", "Size", "Diameter", "Flow", "Pressure Drop", "Comments"]:
        try:
            p = elem.LookupParameter(name)
            v = _param_value(p)
            if v:
                params[name] = v
        except Exception:
            pass
    return params


# ---------------------------------------------------------------------------
# Helper: get connected element IDs via Revit Connectors
# ---------------------------------------------------------------------------
def _get_connected_ids(elem):
    """Return a list of element id strings that this element connects to."""
    connected = []
    try:
        conn_mgr = elem.MEPModel
        if conn_mgr is None:
            # For pipes/ducts/conduit, connectors are on the element directly
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
        # Some elements don't have ConnectorManager — that's fine
        pass
    return connected


# ---------------------------------------------------------------------------
# Helper: get element level name
# ---------------------------------------------------------------------------
def _get_level_name(elem):
    """Return the level name for an element, or 'Unknown'."""
    try:
        level_id = elem.LevelId
        if level_id and eid_int(level_id) > 0:
            level = doc.GetElement(level_id)
            if level:
                return level.Name
    except Exception:
        pass
    # Fallback: try the Level parameter
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


# ---------------------------------------------------------------------------
# Helper: get element category, family, type names safely
# ---------------------------------------------------------------------------
def _safe_name(obj, attr="Name"):
    """Safely get a .Name or other attribute as a string."""
    try:
        val = getattr(obj, attr, None)
        if val:
            return str(val)
    except Exception:
        pass
    return "Unknown"


def _get_family_name(elem):
    """Return the family name for an element."""
    try:
        # For FamilyInstance
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
    """Return the type name for an element."""
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype:
            return _safe_name(etype)
    except Exception:
        pass
    return "Unknown"


# ---------------------------------------------------------------------------
# Helper: serialize a single element
# ---------------------------------------------------------------------------
def _serialize_element(elem):
    """Convert a Revit element to the schema dict."""
    return {
        "element_id": str(elem.Id.Value),
        "category": _safe_name(elem.Category) if elem.Category else "Unknown",
        "family": _get_family_name(elem),
        "type": _get_type_name(elem),
        "level": _get_level_name(elem),
        "connected_to": _get_connected_ids(elem),
        "parameters": _get_element_params(elem),
    }


# ---------------------------------------------------------------------------
# Helper: get elements from a system's PipingNetwork / DuctNetwork
# ---------------------------------------------------------------------------
def _get_system_elements(system):
    """Return a list of element dicts for all elements in a system."""
    elements = []
    seen_ids = set()
    try:
        # MechanicalSystem.DuctNetwork, PipingSystem.PipingNetwork,
        # ElectricalSystem.Elements — all return ElementSets or similar
        elem_set = None
        if isinstance(system, MechanicalSystem):
            try:
                elem_set = system.DuctNetwork
            except Exception:
                pass
        elif isinstance(system, PipingSystem):
            try:
                elem_set = system.PipingNetwork
            except Exception:
                pass
        elif isinstance(system, ElectricalSystem):
            try:
                elem_set = system.Elements
            except Exception:
                pass

        if elem_set:
            for elem in elem_set:
                eid = elem.Id.Value
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    elements.append(_serialize_element(elem))
    except Exception:
        pass

    # Also try the generic GetElements() / Elements property if nothing yet
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


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
errors = []
systems_out = []

try:
    # -- Mechanical Systems (HVAC) --
    mech_systems = (
        FilteredElementCollector(doc)
        .OfClass(MechanicalSystem)
        .ToElements()
    )
    for sys in mech_systems:
        try:
            sys_type, discipline = _get_system_type_and_discipline_mech(sys)
            system_data = {
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            }
            systems_out.append(system_data)
        except Exception as ex:
            errors.append("MechSystem {}: {}".format(sys.Id.Value, str(ex)))

    # -- Piping Systems --
    pipe_systems = (
        FilteredElementCollector(doc)
        .OfClass(PipingSystem)
        .ToElements()
    )
    for sys in pipe_systems:
        try:
            sys_type, discipline = _get_system_type_and_discipline_pipe(sys)
            system_data = {
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            }
            systems_out.append(system_data)
        except Exception as ex:
            errors.append("PipeSystem {}: {}".format(sys.Id.Value, str(ex)))

    # -- Electrical Systems --
    elec_systems = (
        FilteredElementCollector(doc)
        .OfClass(ElectricalSystem)
        .ToElements()
    )
    for sys in elec_systems:
        try:
            sys_type, discipline = _get_system_type_and_discipline_elec(sys)
            system_data = {
                "system_id": str(sys.Id.Value),
                "system_name": _safe_name(sys),
                "system_type": sys_type,
                "discipline": discipline,
                "elements": _get_system_elements(sys),
            }
            systems_out.append(system_data)
        except Exception as ex:
            errors.append("ElecSystem {}: {}".format(sys.Id.Value, str(ex)))

except Exception as ex:
    errors.append("Collection error: {}".format(traceback.format_exc()))

# ---------------------------------------------------------------------------
# Build output payload
# ---------------------------------------------------------------------------
output = {
    "building_type": building_type,
    "systems": systems_out,
}

# Add extraction metadata for debugging
output["_metadata"] = {
    "total_systems": len(systems_out),
    "total_elements": sum(len(s["elements"]) for s in systems_out),
    "errors": errors if errors else None,
}

OUT = json.dumps(output, indent=2)
