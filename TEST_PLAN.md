# Orphan X — Test Plan

**MCP Server:** `https://orphanx.chrisfrance.ai/sse`
**GitHub Repo:** `https://github.com/ibenitosoto/OrphanX`

---

## Server Test Results (Chris — VPS verified)

| Test | Status | Result |
|------|--------|--------|
| MCP server starts and accepts SSE connections | PASS | Server live on port 8620 |
| `audit_systems` with mock hospital data (5 systems, 38 elements) | PASS | 12 findings across all disciplines |
| Dead leg detection flagged as Critical - Patient Safety | PASS | ASHRAE 188 referenced, Legionella risk explained |
| Disconnected sprinkler heads flagged as Critical - Life Safety | PASS | NFPA 13 referenced |
| Missing vent on sanitary waste flagged as Critical - Code Violation | PASS | IPC 901.2 referenced |
| `classify_orphans` with mock orphan data (4 orphans) | PASS | Correct system type guesses, 85-95% confidence |
| `generate_report` produces formatted QA/QC report | PASS | Organized by severity, plain English, actionable |
| JSON response parsing (handles markdown-wrapped JSON) | PASS | Extraction logic handles ```json blocks |
| Cloudflare tunnel routes HTTPS to VPS | PASS | `orphanx.chrisfrance.ai` resolves and connects |

---

## What the DynamoMCP Package Actually Is

**DynamoMCP v0.0.18 is a graph-building AI**, NOT a Revit data tool. It has 28 tools that create nodes, connect wires, and run graphs. It does NOT query Revit models or connect to external servers.

Our Revit data extraction is done by **Python Script nodes** running Revit API code. DynamoMCP can help assemble the graph, but the Python scripts do the real work.

---

## Team Tests — In Order

### Test 0: Can your browser reach the server? (30 seconds)

Open this URL in any browser: `https://orphanx.chrisfrance.ai/sse`

**Expected:** Streaming text starting with `event: endpoint`

**If it fails:** Your network blocks it. Try phone hotspot.

**Every team member should do this first.** If you can't reach the URL, you can't run the pipeline.

---

### Test 1: Run the All-In-One Script (THE MAIN TEST — 5 min)

This is the one that matters. One script does everything.

1. Open your Revit model (Hospital MEP or any MEP model)
2. Open Dynamo
3. Add a **Python Script** node (search "Python" in node library)
4. Right-click the node → **Engine → CPython3** (IMPORTANT)
5. Double-click the node to open the code editor
6. Go to GitHub: `https://github.com/ibenitosoto/OrphanX`
7. Open `dynamo/orphanx_all_in_one.py`
8. Click "Raw", select all, copy
9. Paste the ENTIRE script into the Python Script node
10. Close the editor
11. Click **Run** in Dynamo
12. Wait 30-60 seconds (AI is analyzing)
13. Connect a **Watch** node to the output to see the log
14. In Revit, switch to the **"Orphan X - QA Audit"** 3D view

**Expected output in Watch node:**
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

**Expected in Revit "Orphan X - QA Audit" view:**
- RED elements = Critical Patient Safety / Life Safety
- ORANGE elements = Critical Code Violation
- YELLOW elements = Major findings
- CYAN elements = Minor findings

**Report to Chris:**
- "X systems found, Y elements, Z orphans, N findings, M overrides applied"
- Screenshot of the color-coded 3D view
- Screenshot of the Watch node output
- Any errors

---

### Test 2: Quick Connectivity Test from Dynamo (2 min)

If Test 1 fails on the MCP call, first verify Dynamo can reach the server.

1. Add a new **Python Script** node (CPython3)
2. Paste this:

```python
import urllib.request
import ssl
ctx = ssl.create_default_context()
req = urllib.request.Request("https://orphanx.chrisfrance.ai/sse")
resp = urllib.request.urlopen(req, timeout=5, context=ctx)
OUT = resp.read(200).decode("utf-8")
```

3. Run the graph
4. Check the Watch node output

**Expected:** `event: endpoint\ndata: /messages/?session_id=...`

**If it fails with SSL error**, try this version instead:

```python
import urllib.request
import ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request("https://orphanx.chrisfrance.ai/sse")
resp = urllib.request.urlopen(req, timeout=5, context=ctx)
OUT = resp.read(200).decode("utf-8")
```

**If that also fails:** Your corporate network blocks outbound HTTPS to non-standard domains. Use phone hotspot or a different machine.

---

### Test 3: Extraction Only — No Server Needed (5 min)

If the server can't be reached, test that the Revit extraction works locally.

1. Add a **Python Script** node (CPython3)
2. Paste the contents of `dynamo/extract_mep_systems.py` from GitHub
3. Add a **String** input node with value `hospital`, connect to the Python Script input
4. Run the graph
5. Connect a **Watch** node to the output

**Expected:** A large JSON string listing every MEP system and its elements.

**Report to Chris:**
- How many systems found? (look for `_metadata.total_systems`)
- How many elements? (look for `_metadata.total_elements`)
- Any errors? (look for `_metadata.errors`)
- Copy the first 200 lines or save to file

This data is valuable even without the server — Chris can run it through the AI manually.

---

### Test 4: Use DynamoMCP AI to Build the Graph (optional, 10 min)

If the DynamoMCP extension is installed and the AI chat panel is visible:

1. Open the MCP AI chat in Dynamo
2. Paste this prompt:

```
Search for Python Script node using get_nodes_info with searchTerms ["PythonScript"]. Then create one Python Script node at position (0, 0) with the custom name "Orphan X - All In One". After creating it, tell me the node ID so I can paste code into it.
```

3. The AI will create the node for you
4. Double-click the node, paste `dynamo/orphanx_all_in_one.py`
5. Tell the AI: `Run the workspace`

---

## DynamoMCP Installation (if not already done)

1. Extract `DynamoMCP-v0.0.18.zip`
2. Copy the `DynamoMCP/` folder to: `%AppData%\Dynamo\Dynamo Revit\3.6\packages\`
3. Copy `DynamoMCP/extra/MCP_ViewExtensionDefinition.xml` to: `%AppData%\Dynamo\Dynamo Revit\3.6\viewExtensions\`
4. **Restart Dynamo completely** (close and reopen)
5. You should see an MCP chat panel in Dynamo

---

## Troubleshooting Quick Reference

| Problem | Fix |
|---------|-----|
| "No module named RevitAPI" | Right-click Python node → Engine → **CPython3** |
| SSL errors | Add `ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE` |
| Timeout on MCP call | AI analysis takes 10-30 sec. Set timeout to 120. |
| Empty extraction output | Model might not have MEP systems. Check Revit Systems tab. |
| Can't reach orphanx.chrisfrance.ai | Try phone hotspot. Corporate firewalls may block it. |
| DynamoMCP nodes not showing | Restart Dynamo after installing the package |
| Python node has no Engine option | Dynamo version too old. Need Dynamo 2.13+ for CPython3. |
| "Element has no Location" | Non-fatal. Script handles this with fallbacks. |
| Corporate blocks external URLs from Revit | Use phone hotspot or different machine |

---

## Reporting Issues to Chris

Send:
1. Which test failed (Test 0, 1, 2, 3, or 4)
2. Screenshot of the error or Watch node output
3. Whose machine
4. Did the browser test (Test 0) work?
5. Did extraction-only (Test 3) work?

This helps isolate: is it a network issue, a Revit API issue, or a server issue.
