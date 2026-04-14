# Orphan X — Test Plan

**MCP Server:** `https://orphanx.chrisfrance.ai/sse`
**GitHub:** `https://github.com/ibenitosoto/OrphanX`

---

## How This Works (Read This First)

One Python Script node in Dynamo does everything:

1. Reads every pipe, duct, and fitting from the Revit model
2. Finds orphaned elements not connected to any system
3. Sends data to our AI server (Claude analyzes for dead legs, code violations, patient safety)
4. Colors elements in the model by severity

```
[Python Script Node]
  ↓ Reads Revit model
  ↓ Sends to AI server
  ↓ Colors elements
[Done — switch to 3D view]
```

---

## Test 0: Can Your Browser Reach the Server? (30 seconds)

Open in any browser: `https://orphanx.chrisfrance.ai/sse`

**Expected:** Streaming text starting with `event: endpoint`

**If it fails:** Try phone hotspot. Your network blocks it.

**Do this first.** If the browser can't reach it, the script won't either.

---

## Test 1: Run the All-In-One Script (THE MAIN TEST — 5 min)

1. Open the Hospital MEP model in Revit
2. Open Dynamo
3. Search for **Python Script** in the node library, drag it onto the canvas
4. Right-click the node → **Engine → CPython3** (IMPORTANT)
5. Double-click the node to open the code editor
6. Go to GitHub: `https://github.com/ibenitosoto/OrphanX`
7. Open `dynamo/orphanx_all_in_one.py`
8. Click **Raw**, select all, copy
9. Paste the ENTIRE script into the Python Script node
10. Close the editor
11. Click **Run** in Dynamo
12. Wait 30-60 seconds (extraction + AI analysis takes time)
13. Connect a **Watch** node to the output to see the log
14. In Revit, switch to the **"Orphan X - QA Audit"** 3D view

### Expected Output in Watch Node

```
============================================================
ORPHAN X — MEP Systems Auditor
============================================================

PHASE 1: Extracting MEP systems from Revit model...
  Found X systems with Y elements

PHASE 2: Finding orphaned elements...
  Found Z orphaned elements

PHASE 3: Sending data to Orphan X AI server...
  Server: https://orphanx.chrisfrance.ai
  Calling audit_systems...
  Got N audit findings
    [Critical - Patient Safety] dead_leg: ...
    ...

PHASE 4: Applying visual overrides to Revit model...
  Applied M color overrides

SUMMARY
  Systems found: X
  ...
```

### Expected in Revit

Switch to the "Orphan X - QA Audit" 3D view:
- **RED** = Critical Patient Safety / Life Safety (dead legs, disconnected sprinklers)
- **ORANGE** = Critical Code Violation (missing vents)
- **YELLOW** = Major
- **CYAN** = Minor
- **GRAY** = Unclassified orphan

### Report to Chris

- "X systems, Y elements, Z orphans, N findings, M overrides"
- Screenshot of the color-coded 3D view
- Screenshot of the Watch node output
- Any errors

---

## Test 2: Extraction Only — No Server Needed (3 min)

If Test 1 fails on the server call, test that extraction works locally:

1. Add Python Script node → CPython3
2. Paste `dynamo/extract_for_agentic.py` from GitHub
3. Run
4. Connect a Watch node

**Expected:** Large JSON blob with all MEP systems and orphans.

Look for `total_systems`, `total_elements`, `total_orphans` near the end.

This data is valuable even without the server — Chris can run it through the AI manually.

---

## Test 3: Model Scanner — Debug Tool (2 min)

If you need to see what's in the model:

1. Add Python Script node → CPython3
2. Paste `dynamo/scan_model.py` from GitHub
3. Run

Shows: system counts, element counts, sample data. No server needed.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "No module named RevitAPI" | Right-click Python node → Engine → **CPython3** |
| SSL errors | Script already handles this. If still failing, try phone hotspot. |
| Timeout on server call | AI takes 10-30 sec. Script has 120 sec timeout. Be patient. |
| Empty extraction output | Model may not have MEP systems. Run Test 3. |
| Can't reach orphanx.chrisfrance.ai | Try phone hotspot. Check Test 0 first. |
| Python node has no Engine option | Dynamo too old. Need Dynamo 2.13+ for CPython3. |

---

## Reporting Issues to Chris

Send:
1. Which test failed (0, 1, 2, or 3)
2. Screenshot of the error or Watch node output
3. Did the browser test (Test 0) work?
