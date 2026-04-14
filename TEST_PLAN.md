# Orphan X — Test Plan

**MCP Server:** `https://orphanx.chrisfrance.ai/sse`
**GitHub:** `https://github.com/ibenitosoto/OrphanX`

---

## How This Works (Read This First)

Three boxes in Dynamo, wired together:

```
[Extract from Revit]  →  [Agentic Node → our AI]  →  [Color the model]
     Python Script          DynamoMCP alpha             Python Script
     (reads Revit)          (calls our server)          (paints Revit)
```

- **Box 1** reads every pipe, duct, and fitting from Revit. Pure local, no internet.
- **Box 2** is the Agentic Node (DynamoMCP alpha feature). It sends that data to our AI server. Claude analyzes it and returns findings — dead legs, code violations, patient safety risks.
- **Box 3** reads the AI findings and paints elements in the Revit model by severity (red = critical, orange = code violation, yellow = major, cyan = minor).

---

## Test 0: Can Your Browser Reach the Server? (30 seconds)

Open in any browser: `https://orphanx.chrisfrance.ai/sse`

**Expected:** Streaming text starting with `event: endpoint`

**If it fails:** Try phone hotspot. Your network blocks it.

---

## Test 1: The Full Demo (THE MAIN TEST)

### Step 1: Open model + Dynamo

1. Open the Hospital MEP model in Revit
2. Open Dynamo

### Step 2: Create the Extract node

1. Search for **Python Script** in the Dynamo node library
2. Drag it onto the canvas
3. Right-click the node → **Engine → CPython3** (IMPORTANT)
4. Double-click the node to open the code editor
5. Go to GitHub: `https://github.com/ibenitosoto/OrphanX`
6. Open `dynamo/extract_for_agentic.py`
7. Click "Raw", select all, copy
8. Paste into the Python Script node
9. Close the editor

### Step 3: Create the Agentic Node

**⚠️ This is the DynamoMCP alpha feature. Ask the Autodesk engineers if you can't find it.**

We need an Agentic Node that:
- Connects to MCP server URL: `https://orphanx.chrisfrance.ai/sse`
- Calls tool: `audit_systems`
- Takes one input argument: `systems_json` (the output from Step 2)

How to find it — try these in order:
1. Search the node library for **"Agentic"** or **"Agent"** or **"MCP"** or **"Send Request"**
2. Look for a panel or menu added by the DynamoMCP extension
3. If you see `AgentProcess.GetAllAvailableTools` or `Send Request` — those are it
4. **If you can't find it, ask the Autodesk engineers at the hackathon.** They built it. They know where it is.

Once you have the Agentic Node:
- Set the MCP server URL to: `https://orphanx.chrisfrance.ai/sse`
- It should discover our tools automatically (`audit_systems`, `classify_orphans`, `generate_report`)
- Select `audit_systems`
- Wire the **output** of the Extract Python Script → **input** of the Agentic Node

### Step 4: Create the Override node

1. Add another **Python Script** node (search "Python" in library)
2. Right-click → **Engine → CPython3**
3. Double-click to open editor
4. Go to GitHub: `dynamo/apply_overrides.py`
5. Click "Raw", select all, copy, paste
6. Close the editor
7. Wire the **output** of the Agentic Node → **IN[0]** of this Python Script

### Step 5: Run

1. Click **Run** in Dynamo
2. Wait 30-60 seconds (extraction + AI analysis)
3. In Revit, switch to the **"Orphan X - QA Audit"** 3D view

### Expected Result

**Watch node on Extract script:**
- Large JSON blob with systems and elements

**Watch node on Agentic Node output:**
- AI findings with severities, element IDs, code references (ASHRAE 188, NFPA 13, IPC)

**In Revit "Orphan X - QA Audit" view:**
- RED = Critical Patient Safety / Life Safety (dead legs, disconnected sprinklers)
- ORANGE = Critical Code Violation (missing vents)
- YELLOW = Major
- CYAN = Minor

### Report to Chris

- "X systems found, Y elements, N findings, M overrides applied"
- Screenshot of the color-coded 3D view
- Screenshot of Watch node outputs
- Any errors

---

## Test 2: Fallback — If the Agentic Node Doesn't Work

If you can't get the Agentic Node working (it IS alpha software), use the all-in-one fallback:

1. Add ONE Python Script node → CPython3
2. Paste `dynamo/orphanx_all_in_one.py` from GitHub
3. Run
4. This does everything in one script — extract, call server via HTTP, color model

Less impressive for judges but proves the system works end-to-end.

---

## Test 3: Extraction Only — No Server Needed

If the server can't be reached, test that extraction works:

1. Add Python Script node → CPython3
2. Paste `dynamo/extract_for_agentic.py`
3. Run
4. Connect a Watch node — you should see a big JSON blob

**Report to Chris:**
- How many systems? (search for `total_systems` in output)
- How many elements? (search for `total_elements`)
- How many orphans? (search for `total_orphans`)

This data is valuable even without the server — Chris can run it through the AI manually.

---

## Test 4: Model Scanner — Debug Tool

If everything is broken and you need to see what Revit exposes:

1. Add Python Script node → CPython3
2. Paste `dynamo/scan_model.py`
3. Run
4. Output shows: API classes available, system counts, element counts, sample data

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't find Agentic Node | Ask Autodesk engineers. Search "Agent" or "MCP" in node library. |
| "No module named RevitAPI" | Right-click Python node → Engine → **CPython3** |
| Agentic Node can't connect to server | Check Test 0 first. Try Test 2 fallback. |
| SSL errors | Ask Autodesk engineers — Agentic Node should handle SSL |
| Timeout on AI analysis | AI takes 10-30 sec. Be patient. If >60 sec, retry. |
| Empty extraction output | Model may not have MEP systems. Run Test 4 to check. |
| Python node has no Engine option | Dynamo too old. Need Dynamo 2.13+ for CPython3. |

---

## Reporting Issues to Chris

Send:
1. Which test failed (0, 1, 2, 3, or 4)
2. Screenshot of the error or Watch node output
3. Did the browser test (Test 0) work?
4. Could you find the Agentic Node?
