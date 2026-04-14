# Orphan X — Dynamo Scripts (DynamoMCP Alpha)

MEP Systems Auditor using DynamoMCP alpha features.

## Architecture

```
[Python Script]          [Agentic Node]           [Python Script]
 Extract MEP    ──→    Orphan X MCP Server   ──→   Apply Color
 data from Revit       (AI analysis)               Overrides
```

1. **Extract** — Python Script node reads Revit model via API, outputs JSON
2. **Analyze** — Agentic Node sends JSON to our MCP server, AI returns findings
3. **Visualize** — Python Script node colors elements by severity in a 3D view


## MCP Server

- **SSE URL:** `https://orphanx.chrisfrance.ai/sse`
- **Tools:**
  - `audit_systems` — analyzes system topology, finds dead legs / code violations
  - `classify_orphans` — classifies disconnected elements, suggests correct systems
  - `generate_report` — produces formatted QA/QC report


## Quick Start (3 nodes)

### Node 1: Extract (Python Script)

1. Add Python Script node → right-click → Engine → **CPython3**
2. Paste `extract_for_agentic.py`
3. No inputs needed

### Node 2: Agentic Node

1. Add Agentic Node to graph
2. Set MCP Server URL: `https://orphanx.chrisfrance.ai/sse`
3. Use tool: `audit_systems`
4. Connect Node 1 output → Agentic Node input (`systems_json` argument)

### Node 3: Apply Overrides (Python Script)

1. Add Python Script node → right-click → Engine → **CPython3**
2. Paste `apply_overrides.py`
3. Connect Agentic Node output → IN[0]

### Run

Click Run. Switch to "Orphan X - QA Audit" view in Revit.


## Color Legend

| Severity | Color | Meaning |
|----------|-------|---------|
| Critical - Patient Safety | RED | Dead legs (Legionella), ASHRAE 188 |
| Critical - Life Safety | RED | Disconnected sprinklers, NFPA 13 |
| Critical - Code Violation | ORANGE | Missing vents, IPC 901.2 |
| Major | YELLOW | Dead-end ducts, orphaned equipment |
| Minor | CYAN | Model hygiene issues |
| Orphan | GRAY | Unclassified disconnected element |


## Scripts

| File | Purpose | Inputs | Output |
|------|---------|--------|--------|
| `extract_for_agentic.py` | Extract MEP systems + orphans | None | JSON string |
| `apply_overrides.py` | Color model by severity | IN[0]: findings JSON | Summary text |
| `scan_model.py` | Debug: report what's in model | None | Text report |
| `orphanx_all_in_one.py` | Fallback: does everything without Agentic Node | None | Text report |


## Troubleshooting

| Problem | Fix |
|---------|-----|
| "clr is not defined" | Right-click Python node → Engine → CPython3 |
| Empty output from extraction | Model may not have MEP systems |
| Agentic Node can't connect | Check browser can reach `https://orphanx.chrisfrance.ai/sse` |
| SSL error | Ask Autodesk engineers — Agentic Node should handle SSL |
| Slow on large models | Normal for 18K+ elements, wait 30-60 seconds |
