"""Orphan X — Model Scanner

NO AI. NO SERVER. NO OVERRIDES.
Just scans the Revit model and reports what's there.

1. Add a Python Script node in Dynamo
2. Right-click -> Engine -> CPython3
3. Paste this script
4. Run
5. Read the Watch node output
"""

import clr
import json
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, BuiltInParameter
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
lines = []

def log(msg):
    lines.append(str(msg))

log("=" * 60)
log("ORPHAN X — MODEL SCAN")
log("=" * 60)
log("")
log("Model: {}".format(doc.Title))
log("")

# ============================================
# 1. What Revit API classes are available?
# ============================================
log("--- AVAILABLE API CLASSES ---")

has_mech = False
has_pipe = False
has_elec = False

try:
    from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
    has_mech = True
    log("MechanicalSystem: YES")
    # List available DuctSystemType values
    duct_types = []
    for attr in dir(DuctSystemType):
        if not attr.startswith("_"):
            try:
                val = getattr(DuctSystemType, attr)
                if isinstance(val, DuctSystemType):
                    duct_types.append(attr)
            except Exception:
                pass
    log("  DuctSystemType values: {}".format(", ".join(duct_types)))
except Exception as ex:
    log("MechanicalSystem: NO ({})".format(str(ex)))

try:
    from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
    has_pipe = True
    log("PipingSystem: YES")
    pipe_types = []
    for attr in dir(PipeSystemType):
        if not attr.startswith("_"):
            try:
                val = getattr(PipeSystemType, attr)
                if isinstance(val, PipeSystemType):
                    pipe_types.append(attr)
            except Exception:
                pass
    log("  PipeSystemType values: {}".format(", ".join(pipe_types)))
except Exception as ex:
    log("PipingSystem: NO ({})".format(str(ex)))

try:
    from Autodesk.Revit.DB.Electrical import ElectricalSystem
    has_elec = True
    log("ElectricalSystem: YES")
except Exception as ex:
    log("ElectricalSystem: NO ({})".format(str(ex)))

log("")

# ============================================
# 2. Count MEP systems
# ============================================
log("--- MEP SYSTEMS ---")

if has_mech:
    from Autodesk.Revit.DB.Mechanical import MechanicalSystem, DuctSystemType
    try:
        mechs = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()
        log("Mechanical Systems: {}".format(len(mechs)))
        type_counts = {}
        for s in mechs:
            try:
                st = str(s.SystemType)
                type_counts[st] = type_counts.get(st, 0) + 1
            except Exception:
                type_counts["Unknown"] = type_counts.get("Unknown", 0) + 1
        for t, c in sorted(type_counts.items()):
            log("  {}: {}".format(t, c))
        if mechs:
            sample = mechs[0]
            log("  Sample: '{}' (ID: {})".format(sample.Name, sample.Id.IntegerValue))
    except Exception as ex:
        log("  Error: {}".format(str(ex)))

if has_pipe:
    from Autodesk.Revit.DB.Plumbing import PipingSystem, PipeSystemType
    try:
        pipes = FilteredElementCollector(doc).OfClass(PipingSystem).ToElements()
        log("Piping Systems: {}".format(len(pipes)))
        type_counts = {}
        for s in pipes:
            try:
                st = str(s.SystemType)
                type_counts[st] = type_counts.get(st, 0) + 1
            except Exception:
                type_counts["Unknown"] = type_counts.get("Unknown", 0) + 1
        for t, c in sorted(type_counts.items()):
            log("  {}: {}".format(t, c))
        if pipes:
            sample = pipes[0]
            log("  Sample: '{}' (ID: {})".format(sample.Name, sample.Id.IntegerValue))
    except Exception as ex:
        log("  Error: {}".format(str(ex)))

if has_elec:
    from Autodesk.Revit.DB.Electrical import ElectricalSystem
    try:
        elecs = FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements()
        log("Electrical Systems: {}".format(len(elecs)))
        type_counts = {}
        for s in elecs:
            try:
                st = str(s.SystemType)
                type_counts[st] = type_counts.get(st, 0) + 1
            except Exception:
                type_counts["Unknown"] = type_counts.get("Unknown", 0) + 1
        for t, c in sorted(type_counts.items()):
            log("  {}: {}".format(t, c))
        if elecs:
            sample = elecs[0]
            log("  Sample: '{}' (ID: {})".format(sample.Name, sample.Id.IntegerValue))
    except Exception as ex:
        log("  Error: {}".format(str(ex)))

log("")

# ============================================
# 3. Count MEP elements by category
# ============================================
log("--- MEP ELEMENT COUNTS BY CATEGORY ---")

categories_to_scan = [
    ("Air Terminals", BuiltInCategory.OST_DuctTerminal),
    ("Ducts", BuiltInCategory.OST_DuctCurves),
    ("Duct Fittings", BuiltInCategory.OST_DuctFitting),
    ("Flex Ducts", BuiltInCategory.OST_FlexDuctCurves),
    ("Pipes", BuiltInCategory.OST_PipeCurves),
    ("Pipe Fittings", BuiltInCategory.OST_PipeFitting),
    ("Pipe Segments", BuiltInCategory.OST_PipeSegments),
    ("Flex Pipes", BuiltInCategory.OST_FlexPipeCurves),
    ("Plumbing Fixtures", BuiltInCategory.OST_PlumbingFixtures),
    ("Mechanical Equipment", BuiltInCategory.OST_MechanicalEquipment),
    ("Sprinklers", BuiltInCategory.OST_Sprinklers),
    ("Electrical Equipment", BuiltInCategory.OST_ElectricalEquipment),
    ("Electrical Fixtures", BuiltInCategory.OST_ElectricalFixtures),
    ("Lighting Fixtures", BuiltInCategory.OST_LightingFixtures),
    ("Conduit", BuiltInCategory.OST_Conduit),
    ("Cable Tray", BuiltInCategory.OST_CableTray),
    ("Fire Alarm Devices", BuiltInCategory.OST_FireAlarmDevices),
]

total_elements = 0
for name, bic in categories_to_scan:
    try:
        elems = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        count = len(elems)
        if count > 0:
            log("  {}: {}".format(name, count))
            total_elements += count
    except Exception:
        pass

log("  TOTAL MEP ELEMENTS: {}".format(total_elements))
log("")

# ============================================
# 4. Sample elements — show what data we can extract
# ============================================
log("--- SAMPLE ELEMENTS (first 5 from largest category) ---")

best_cat = None
best_count = 0
best_elems = []
for name, bic in categories_to_scan:
    try:
        elems = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        if len(elems) > best_count:
            best_count = len(elems)
            best_cat = name
            best_elems = elems
    except Exception:
        pass

if best_elems:
    log("Showing from '{}' ({} total):".format(best_cat, best_count))
    log("")
    for elem in list(best_elems)[:5]:
        eid = elem.Id.IntegerValue
        cat = elem.Category.Name if elem.Category else "?"

        # Family name
        fam = "?"
        try:
            fam = elem.Symbol.Family.Name
        except Exception:
            try:
                etype = doc.GetElement(elem.GetTypeId())
                if etype and hasattr(etype, "FamilyName"):
                    fam = etype.FamilyName
            except Exception:
                pass

        # Type name
        typ = "?"
        try:
            etype = doc.GetElement(elem.GetTypeId())
            if etype:
                typ = etype.Name
        except Exception:
            pass

        # Level
        lvl = "?"
        try:
            level_id = elem.LevelId
            if level_id and level_id.IntegerValue > 0:
                lvl = doc.GetElement(level_id).Name
        except Exception:
            try:
                p = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
                if p and p.HasValue:
                    lvl = p.AsValueString()
            except Exception:
                pass

        # Connectors
        conn_count = 0
        connected_ids = []
        try:
            mgr = None
            try:
                mgr = elem.MEPModel.ConnectorManager
            except Exception:
                try:
                    mgr = elem.ConnectorManager
                except Exception:
                    pass
            if mgr:
                for conn in mgr.Connectors:
                    conn_count += 1
                    if conn.IsConnected:
                        for ref in conn.AllRefs:
                            if ref.Owner and ref.Owner.Id != elem.Id:
                                connected_ids.append(str(ref.Owner.Id.IntegerValue))
        except Exception:
            pass

        log("  ID: {}".format(eid))
        log("    Category: {}".format(cat))
        log("    Family: {}".format(fam))
        log("    Type: {}".format(typ))
        log("    Level: {}".format(lvl))
        log("    Connectors: {} total, connected to: [{}]".format(conn_count, ", ".join(connected_ids)))
        log("")

# ============================================
# 5. Check network access
# ============================================
log("--- NETWORK TEST ---")
try:
    import urllib.request
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("https://orphanx.chrisfrance.ai/sse")
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    data = resp.read(200).decode("utf-8")
    if "endpoint" in data:
        log("  orphanx.chrisfrance.ai: REACHABLE")
    else:
        log("  orphanx.chrisfrance.ai: GOT RESPONSE BUT UNEXPECTED: {}".format(data[:100]))
except Exception as ex:
    log("  orphanx.chrisfrance.ai: UNREACHABLE ({})".format(str(ex)))

log("")
log("=" * 60)
log("SCAN COMPLETE. Send this output to Chris.")
log("=" * 60)

output_text = "\n".join(lines)

# Save to desktop so they can send it to Chris
import os
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
outpath = os.path.join(desktop, "orphanx_scan.txt")
try:
    with open(outpath, "w") as f:
        f.write(output_text)
    output_text += "\n\nSaved to: " + outpath
except Exception as ex:
    output_text += "\n\nCould not save file: " + str(ex)

OUT = output_text
