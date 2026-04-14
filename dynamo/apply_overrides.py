"""Orphan X — Apply Visual Overrides to Revit Elements by Severity

Dynamo for Revit Python Script node.
Takes audit findings JSON (from audit_systems + classify_orphans MCP tools),
maps severity levels to colors, and applies OverrideGraphicSettings to elements
in a dedicated QA audit view.

IN[0]: audit_json (string) — JSON containing audit findings. Expected format:
       {
           "findings": [
               {
                   "severity": "Critical - Patient Safety" | "Critical - Life Safety" |
                               "Critical - Code Violation" | "Major" | "Minor",
                   "affected_elements": ["12345", "12346", ...]
               }
           ],
           "classifications": [
               {
                   "element_id": "99999",
                   "severity": "Major"
               }
           ]
       }
       Accepts either separate "findings" and "classifications" keys, or a
       combined list. The script is tolerant of both shapes.

IN[1]: view_name (string) — Name for the QA view. Defaults to "Orphan X - QA Audit".

OUT: Summary string describing what overrides were applied.

Revit API: 2024/2025 compatible (CPython3 engine in Dynamo 2.x / 3.x).
"""

import clr
import json
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    OverrideGraphicSettings,
    Color,
    Transaction,
    View3D,
    ViewDuplicateOption,
    ViewFamilyType,
    ViewFamily,
    FillPatternElement,
    LinePatternElement,
)

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ---------------------------------------------------------------------------
# Document handle
# ---------------------------------------------------------------------------
doc = DocumentManager.Instance.CurrentDBDocument

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
audit_json = ""
try:
    audit_json = str(IN[0]) if IN[0] else ""
except Exception:
    pass

view_name = "Orphan X - QA Audit"
try:
    if IN[1] and str(IN[1]).strip():
        view_name = str(IN[1]).strip()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Color map — severity to RGB
# ---------------------------------------------------------------------------
SEVERITY_COLORS = {
    "Critical - Patient Safety": Color(255, 0, 0),       # RED
    "Critical - Life Safety":    Color(255, 0, 0),        # RED (same priority)
    "Critical - Code Violation": Color(255, 165, 0),      # ORANGE
    "Major":                     Color(255, 255, 0),      # YELLOW
    "Minor":                     Color(0, 255, 255),      # CYAN
    "Orphan":                    Color(180, 180, 180),    # GRAY (unclassified orphans)
}

# Line weight overrides by severity (heavier = more critical)
SEVERITY_LINE_WEIGHTS = {
    "Critical - Patient Safety": 10,
    "Critical - Life Safety":    10,
    "Critical - Code Violation": 8,
    "Major":                     6,
    "Minor":                     4,
    "Orphan":                    4,
}

# Priority: if an element appears in multiple findings, highest severity wins
SEVERITY_PRIORITY = {
    "Critical - Patient Safety": 5,
    "Critical - Life Safety":    4,
    "Critical - Code Violation": 3,
    "Major":                     2,
    "Minor":                     1,
    "Orphan":                    0,
}


# ---------------------------------------------------------------------------
# Helper: normalize severity string (fuzzy matching)
# ---------------------------------------------------------------------------
def _normalize_severity(raw):
    """Map raw severity string to a canonical key in SEVERITY_COLORS."""
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
        # Generic critical — default to Patient Safety level
        return "Critical - Patient Safety"
    if "major" in raw_lower:
        return "Major"
    if "minor" in raw_lower:
        return "Minor"
    if "warning" in raw_lower:
        return "Minor"
    return "Orphan"


# ---------------------------------------------------------------------------
# Step 1: Parse input JSON and build element -> severity map
# ---------------------------------------------------------------------------
errors = []
element_severity = {}  # element_id_str -> canonical severity string
stats = {"elements_processed": 0, "overrides_applied": 0, "view_created": False}

try:
    data = json.loads(audit_json)
except Exception as ex:
    errors.append("Failed to parse input JSON: {}".format(str(ex)))
    data = {}

# Process "findings" array (from audit_systems tool)
findings = data.get("findings", [])
if isinstance(data.get("audit_findings"), list):
    findings = data["audit_findings"]

for finding in findings:
    severity = _normalize_severity(finding.get("severity", ""))
    affected = finding.get("affected_elements", [])
    for eid_str in affected:
        eid_str = str(eid_str)
        existing = element_severity.get(eid_str)
        if existing is None or SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(existing, 0):
            element_severity[eid_str] = severity

# Process "classifications" array (from classify_orphans tool)
classifications = data.get("classifications", [])
if isinstance(data.get("orphan_classifications"), list):
    classifications = data["orphan_classifications"]

for cls in classifications:
    eid_str = str(cls.get("element_id", ""))
    if not eid_str:
        continue
    severity = _normalize_severity(cls.get("severity", "Orphan"))
    existing = element_severity.get(eid_str)
    if existing is None or SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(existing, 0):
        element_severity[eid_str] = severity

stats["elements_processed"] = len(element_severity)

if not element_severity:
    errors.append("No elements found in input data to apply overrides to.")


# ---------------------------------------------------------------------------
# Step 2: Find or create the QA audit view
# ---------------------------------------------------------------------------
def _get_solid_fill_pattern():
    """Return the solid fill pattern element, or None."""
    try:
        fills = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
        for fp in fills:
            pat = fp.GetFillPattern()
            if pat and pat.IsSolidFill:
                return fp.Id
    except Exception:
        pass
    return None


def _find_or_create_view():
    """Find an existing view with the target name, or duplicate the active 3D view."""
    # Look for existing view by name
    all_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v in all_views:
        try:
            if v.Name == view_name and not v.IsTemplate:
                return v
        except Exception:
            pass

    # No existing view — duplicate the active 3D view or find any 3D view
    source_view = None

    # Try the active view first
    try:
        active = doc.ActiveView
        if isinstance(active, View3D) and not active.IsTemplate:
            source_view = active
    except Exception:
        pass

    # Fallback: find any non-template 3D view
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
            new_view = doc.GetElement(new_id)
            new_view.Name = view_name
            return new_view
        except Exception as ex:
            errors.append("Could not duplicate view: {}".format(str(ex)))
            # Return the source view as fallback
            return source_view

    # Last resort: create a new 3D view from a ViewFamilyType
    try:
        vft_collector = (
            FilteredElementCollector(doc)
            .OfClass(ViewFamilyType)
            .ToElements()
        )
        vft_3d = None
        for vft in vft_collector:
            if vft.ViewFamily == ViewFamily.ThreeDimensional:
                vft_3d = vft
                break
        if vft_3d:
            new_view = View3D.CreateIsometric(doc, vft_3d.Id)
            new_view.Name = view_name
            return new_view
    except Exception as ex:
        errors.append("Could not create 3D view: {}".format(str(ex)))

    return None


# ---------------------------------------------------------------------------
# Step 3: Apply overrides inside a transaction
# ---------------------------------------------------------------------------
try:
    TransactionManager.Instance.EnsureInTransaction(doc)

    # Find or create the audit view
    qa_view = _find_or_create_view()
    if qa_view is None:
        errors.append("Could not find or create the '{}' view. Overrides not applied.".format(view_name))
    else:
        stats["view_created"] = True
        solid_fill_id = _get_solid_fill_pattern()

        # Build severity counts for summary
        severity_counts = {}

        for eid_str, severity in element_severity.items():
            try:
                eid_int = int(eid_str)
                elem_id = ElementId(eid_int)
                elem = doc.GetElement(elem_id)
                if elem is None:
                    errors.append("Element {} not found in model.".format(eid_str))
                    continue

                color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["Orphan"])
                line_weight = SEVERITY_LINE_WEIGHTS.get(severity, 4)

                ogs = OverrideGraphicSettings()

                # Surface/face overrides (projection)
                ogs.SetProjectionLineColor(color)
                ogs.SetSurfaceForegroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetSurfaceForegroundPatternId(solid_fill_id)

                # Cut overrides (for section/plan views)
                ogs.SetCutLineColor(color)
                ogs.SetCutForegroundPatternColor(color)
                if solid_fill_id:
                    ogs.SetCutForegroundPatternId(solid_fill_id)

                # Line weight — use heavier lines for critical elements
                ogs.SetProjectionLineWeight(line_weight)
                ogs.SetCutLineWeight(line_weight)

                # Apply the override to this element in the QA view
                qa_view.SetElementOverrides(elem_id, ogs)

                stats["overrides_applied"] += 1
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            except Exception as ex:
                errors.append("Override failed for {}: {}".format(eid_str, str(ex)))

    TransactionManager.Instance.TransactionTaskDone()

except Exception as ex:
    errors.append("Transaction error: {}".format(traceback.format_exc()))
    try:
        TransactionManager.Instance.TransactionTaskDone()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Build output summary
# ---------------------------------------------------------------------------
summary_lines = [
    "=== Orphan X — Visual Override Summary ===",
    "",
    "View: '{}'".format(view_name),
    "Elements processed: {}".format(stats["elements_processed"]),
    "Overrides applied: {}".format(stats["overrides_applied"]),
    "",
    "--- Severity Breakdown ---",
]

# Severity counts in priority order
for sev_name in [
    "Critical - Patient Safety",
    "Critical - Life Safety",
    "Critical - Code Violation",
    "Major",
    "Minor",
    "Orphan",
]:
    count = severity_counts.get(sev_name, 0) if "severity_counts" in dir() else 0
    if count > 0:
        r, g, b = 0, 0, 0
        c = SEVERITY_COLORS.get(sev_name)
        if c:
            r, g, b = c.Red, c.Green, c.Blue
        summary_lines.append(
            "  {} : {} elements  (RGB {},{},{})".format(sev_name, count, r, g, b)
        )

summary_lines.append("")
summary_lines.append("--- Color Legend ---")
summary_lines.append("  RED (255,0,0)       = Critical - Patient Safety / Life Safety")
summary_lines.append("  ORANGE (255,165,0)  = Critical - Code Violation")
summary_lines.append("  YELLOW (255,255,0)  = Major")
summary_lines.append("  CYAN (0,255,255)    = Minor")
summary_lines.append("  GRAY (180,180,180)  = Orphan (unclassified)")

if errors:
    summary_lines.append("")
    summary_lines.append("--- Errors ({}) ---".format(len(errors)))
    for e in errors[:20]:  # Cap at 20 to avoid flooding Watch node
        summary_lines.append("  ! {}".format(e))
    if len(errors) > 20:
        summary_lines.append("  ... and {} more errors".format(len(errors) - 20))

OUT = "\n".join(summary_lines)
