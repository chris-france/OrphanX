# Orphan X -- Dynamo Scripts

Python Script nodes for Dynamo for Revit that extract MEP system data,
find orphaned elements, and apply visual overrides based on AI audit findings.

These scripts run inside Dynamo's CPython3 (or IronPython) engine with full
access to the Revit API. They are designed for Revit 2024 and 2025.


## MCP Server

The Orphan X MCP server accepts the JSON output from these scripts and returns
AI-powered audit findings.

- **URL:** https://hackathon.chrisfrance.ai/
- **SSE endpoint:** https://hackathon.chrisfrance.ai/sse
- **Health check:** https://hackathon.chrisfrance.ai/health

MCP Tools:
- `audit_systems` -- receives system data, returns completeness findings
- `classify_orphans` -- receives orphan data, returns classifications
- `generate_report` -- receives all findings, returns formatted QA/QC report


## Scripts

### 1. extract_mep_systems.py

Extracts all MEP systems (Mechanical, Piping, Electrical) and their elements.

**Inputs:**
| Port | Type   | Description                         | Default    |
|------|--------|-------------------------------------|------------|
| IN[0]| string | Building type                       | "hospital" |

**Output:** JSON string matching the `audit_systems` MCP tool input schema.

**What it does:**
- Uses FilteredElementCollector to get MechanicalSystem, PipingSystem, and
  ElectricalSystem objects
- For each system: extracts system_id, system_name, system_type, discipline
- For each element in each system: extracts element_id, category, family, type,
  level, connected_to (via Revit Connectors), and key parameters
- Maps Revit system types (DuctSystemType, PipeSystemType) to the schema's
  string enum values

### 2. find_orphans.py

Finds all MEP elements that are NOT connected to any system.

**Inputs:**
| Port | Type   | Description                         | Default    |
|------|--------|-------------------------------------|------------|
| IN[0]| string | Building type                       | "hospital" |
| IN[1]| int    | Max nearest system elements         | 3          |

**Output:** JSON string matching the `classify_orphans` MCP tool input schema.

**What it does:**
- Collects all element IDs that belong to any MEP system
- Scans 19 MEP categories for elements NOT in the system set
- For each orphan, computes Euclidean distance to all system elements and
  returns the N nearest with their system names
- Categories scanned: Air Terminals, Duct Fittings, Pipe Fittings, Pipe
  Segments, Mechanical Equipment, Plumbing Fixtures, Sprinklers, Electrical
  Fixtures, Electrical Equipment, Lighting Fixtures, Ducts, Pipes, Flex Ducts,
  Flex Pipes, Conduit, Conduit Fittings, Cable Tray, Cable Tray Fittings,
  Fire Alarm Devices

### 3. apply_overrides.py

Applies color-coded visual overrides to elements based on audit severity.

**Inputs:**
| Port | Type   | Description                         | Default                  |
|------|--------|-------------------------------------|--------------------------|
| IN[0]| string | Combined audit findings JSON        | (required)               |
| IN[1]| string | View name for QA view               | "Orphan X - QA Audit"   |

**Output:** Summary text suitable for a Watch node.

**What it does:**
- Parses findings from both `audit_systems` and `classify_orphans` results
- Creates or reuses a 3D view named "Orphan X - QA Audit"
- Applies OverrideGraphicSettings to each affected element:

| Severity                     | Color              | RGB         | Line Weight |
|------------------------------|--------------------|-------------|-------------|
| Critical - Patient Safety    | RED                | 255,0,0     | 10          |
| Critical - Life Safety       | RED                | 255,0,0     | 10          |
| Critical - Code Violation    | ORANGE             | 255,165,0   | 8           |
| Major                        | YELLOW             | 255,255,0   | 6           |
| Minor                        | CYAN               | 0,255,255   | 4           |
| Orphan (unclassified)        | GRAY               | 180,180,180 | 4           |

- If an element appears in multiple findings, the highest severity wins
- Uses solid fill patterns for surface overrides (projection and cut)


## Dynamo Graph Setup

### Prerequisites
- Revit 2024 or 2025
- Dynamo 2.x or 3.x with CPython3 engine enabled
- An MEP model open in Revit

### Node Wiring (Manual Graph Build)

Create a Dynamo graph with these nodes connected in sequence:

```
[String Input: "hospital"] --> IN[0]
                                |
                         +------+------+
                         |             |
                 [Python Script]  [Python Script]
                 extract_mep_     find_orphans.py
                 systems.py             |
                         |              |
                    systems_json   orphans_json
                         |              |
                   [Agentic Node]  [Agentic Node]
                   audit_systems   classify_orphans
                   MCP Tool Call   MCP Tool Call
                         |              |
                    findings_json  classifications_json
                         |              |
                         +------+-------+
                                |
                        [Code Block]
                        Merge into single JSON
                                |
                        [Python Script]
                        apply_overrides.py
                                |
                         [Watch Node]
                         Summary output
```

### Agentic Node Configuration

For the agentic nodes that call the MCP server:

1. Set MCP Server URL to: `https://hackathon.chrisfrance.ai/sse`
2. Tool name: `audit_systems` or `classify_orphans`
3. Input: the JSON string output from the corresponding Python Script node

### Fallback: HTTP POST via Python Script

If the agentic nodes cannot connect to the external MCP server, use a Python
Script node to make a direct HTTP POST:

```python
import json
import urllib.request

# IN[0] = JSON payload from extract_mep_systems.py
payload = IN[0]

url = "https://hackathon.chrisfrance.ai/sse"
req = urllib.request.Request(
    url,
    data=json.dumps({"tool": "audit_systems", "input": payload}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req)
OUT = resp.read().decode("utf-8")
```

### Merging Results for apply_overrides.py

The apply_overrides script expects a single JSON object with both `findings`
and `classifications` arrays. Use a Code Block node to merge:

```
// Dynamo Code Block
import json;
audit = json.loads(IN[0]);
orphan = json.loads(IN[1]);
merged = {
    "findings": audit.get("findings", []),
    "classifications": orphan.get("classifications", [])
};
OUT = json.dumps(merged);
```

Or pass the combined JSON from the `generate_report` MCP tool, which accepts
both `audit_findings` and `orphan_classifications` keys.


## Troubleshooting

### "clr is not defined"
Switch the Python Script node engine to CPython3 (right-click the node,
select Engine > CPython3). IronPython 2 also supports clr but uses different
syntax for some .NET APIs.

### "RevitServices not found"
Make sure you are running inside Dynamo for Revit, not standalone Dynamo
Sandbox. The RevitServices assembly is only available when Dynamo is hosted
by Revit.

### Empty system elements
Some systems in Revit report zero elements via DuctNetwork/PipingNetwork if
they are malformed or newly created. The scripts fall back to the .Elements
property automatically.

### Performance on large models
The find_orphans.py script computes distances from every orphan to every
system element. On models with 10,000+ elements this can take 30-60 seconds.
Reduce max_nearest (IN[1]) to 1 if speed is critical.

### View already exists
If "Orphan X - QA Audit" already exists, the script reuses it and updates
overrides in place. It will not create duplicates.
