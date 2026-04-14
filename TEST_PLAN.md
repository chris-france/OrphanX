# Orphan X — Test Plan

**MCP Server URL:** `https://orphanx.chrisfrance.ai/sse`

---

## What Works Right Now (Chris tested on VPS)

| Test | Status | Result |
|------|--------|--------|
| MCP server starts and accepts SSE connections | PASS | Server live on port 8620 |
| `audit_systems` with mock hospital data (5 systems, 38 elements) | PASS | Found dead legs, disconnected sprinklers, missing vents, empty circuits |
| Dead leg detection flagged as Critical - Patient Safety | PASS | ASHRAE 188 referenced, Legionella risk explained |
| Disconnected sprinkler heads flagged as Critical - Life Safety | PASS | NFPA 13 referenced |
| Missing vent on sanitary waste flagged as Critical - Code Violation | PASS | IPC 901.2 referenced |
| `classify_orphans` with mock orphan data (4 orphans) | PASS | Correct system type guesses, severity levels, fix recommendations |
| `generate_report` produces formatted QA/QC report | PASS | Organized by severity, plain English, actionable |
| JSON response parsing (handles markdown-wrapped JSON) | PASS | Extraction logic handles ```json blocks |
| Cloudflare tunnel routes HTTPS to VPS | PASS | `orphanx.chrisfrance.ai` resolves and connects |

---

## What the Dynamo Team Needs to Test

### Test 1: Can Dynamo reach the MCP server? (Ignacio — 5 min)

**Goal:** Confirm the agentic node can connect to `https://orphanx.chrisfrance.ai/sse`

1. Open Dynamo (any Revit project, doesn't matter which)
2. Drop an **AgentProcess.GetAllAvailableTools** node
3. Set the MCP Server URL to: `https://orphanx.chrisfrance.ai/sse`
4. Run the graph
5. **Expected result:** You should see 3 tools listed:
   - `audit_systems`
   - `classify_orphans`
   - `generate_report`

**If it fails:** Take a screenshot of the error. Try these:
- Make sure URL is exactly `https://orphanx.chrisfrance.ai/sse` (with `/sse` at the end)
- Check if your machine can reach the URL in a browser: open `https://orphanx.chrisfrance.ai/sse` — you should see `event: endpoint` text streaming
- If corporate firewall blocks it, try from your phone hotspot

**Report back to Chris:** "Tools visible: yes/no" + screenshot

---

### Test 2: Can Dynamo send data and get results? (Ignacio — 10 min)

**Goal:** Send hardcoded test data through the agentic node and get AI findings back

1. In Dynamo, add a **Code Block** node with this test JSON (copy-paste exactly):

```
"{\"building_type\":\"hospital\",\"systems\":[{\"system_id\":\"TEST-001\",\"system_name\":\"Domestic Hot Water Test\",\"system_type\":\"DomesticHotWater\",\"discipline\":\"Plumbing\",\"elements\":[{\"element_id\":\"1001\",\"category\":\"Mechanical Equipment\",\"family\":\"Water Heater\",\"type\":\"Gas\",\"level\":\"Level 1\",\"connected_to\":[\"1002\"],\"parameters\":{\"Temperature\":\"140F\"}},{\"element_id\":\"1002\",\"category\":\"Pipe Segments\",\"family\":\"Copper\",\"type\":\"2 inch\",\"level\":\"Level 1\",\"connected_to\":[\"1001\",\"1003\"],\"parameters\":{}},{\"element_id\":\"1003\",\"category\":\"Pipe Segments\",\"family\":\"Copper\",\"type\":\"1 inch\",\"level\":\"Level 2\",\"connected_to\":[\"1002\"],\"parameters\":{\"Length\":\"10 ft\"}}]}]}";
```

2. Connect the Code Block output to a **Send Request** agentic node
3. Set the tool name to `audit_systems`
4. Set the parameter name to `systems_json`
5. Run the graph
6. **Expected result:** JSON response with findings — should flag element 1003 as a dead leg (Critical - Patient Safety)

**Report back to Chris:** "Got findings: yes/no" + paste the response text

---

### Test 3: Extract real system data from Revit (Oskar or Petra — 15 min)

**Goal:** Run our extraction script on the Hospital Revit MEP model to get real data

1. Open the Hospital Revit MEP model (download from GitHub repo `test-models/Hospital Revit MEP.rar`, extract the .rvt)
2. In Dynamo, add a **Python Script** node
3. Set engine to **CPython3** (right-click node > select engine)
4. Paste the contents of `dynamo/extract_mep_systems.py` from the GitHub repo
5. Add an input: `IN[0]` = string `"hospital"` (use a Code Block node: `"hospital";`)
6. Run the graph
7. Connect output to a **Watch** node to see the JSON

**Expected result:** A big JSON string listing every MEP system in the model with all elements, connectivity, levels, and parameters.

**Report back to Chris:** 
- How many systems found? 
- Copy-paste the first 200 lines of output (or save to file and send)
- Any errors? Screenshot them.

---

### Test 4: Find orphaned elements (Oskar or Petra — 10 min)

**Goal:** Run orphan finder on the same model

1. Same Revit model, new **Python Script** node (CPython3)
2. Paste contents of `dynamo/find_orphans.py`
3. Add inputs: `IN[0]` = `"hospital";` and `IN[1]` = `3;` (number of nearest elements to report)
4. Run the graph
5. Connect output to **Watch** node

**Expected result:** JSON listing elements not in any system, with nearest system elements.

**Report back to Chris:** How many orphans found? Send output.

---

### Test 5: End-to-end pipeline (Everyone — 20 min)

**Goal:** Extract data from Revit, send to MCP server, get findings, color the model

**Option A — Agentic Nodes (preferred):**
1. Python Script node (extract_mep_systems.py) → outputs systems JSON
2. Send Request agentic node → sends JSON to `audit_systems` tool at `https://orphanx.chrisfrance.ai/sse` → receives findings JSON
3. Python Script node (find_orphans.py) → outputs orphans JSON
4. Send Request agentic node → sends JSON to `classify_orphans` tool → receives classifications JSON
5. Python Script node (apply_overrides.py) → takes combined findings → colors elements in Revit view

**Option B — HTTP fallback (if agentic nodes can't reach external MCP):**
Use this Python Script node instead of agentic nodes:

```python
import json
import urllib.request

systems_json = IN[0]  # output from extract_mep_systems.py

# Call the MCP server directly via HTTP
# First establish SSE connection to get session
req = urllib.request.Request(
    "https://orphanx.chrisfrance.ai/sse",
    method="GET"
)
# Read the session endpoint
response = urllib.request.urlopen(req, timeout=10)
first_lines = response.read(200).decode()
# Parse session ID from the SSE response
# endpoint line looks like: data: /messages/?session_id=xxx
session_line = [l for l in first_lines.split('\n') if 'session_id' in l][0]
endpoint = session_line.split('data: ')[1].strip()

# Send the tool call via the messages endpoint  
msg = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "audit_systems",
        "arguments": {"systems_json": systems_json}
    }
}
post_req = urllib.request.Request(
    "https://orphanx.chrisfrance.ai" + endpoint,
    data=json.dumps(msg).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
post_response = urllib.request.urlopen(post_req, timeout=120)
result = json.loads(post_response.read().decode())
OUT = json.dumps(result, indent=2)
```

---

## What Chris Tests Remotely (no Revit needed)

These are done/in-progress on the VPS:

- [x] MCP server starts on port 8620
- [x] SSE endpoint responds at `/sse`
- [x] `audit_systems` returns valid JSON findings for mock data
- [x] Dead legs detected with correct severity
- [x] Disconnected sprinklers detected
- [x] Missing sanitary vents detected
- [x] `classify_orphans` returns valid classifications
- [x] `generate_report` returns formatted report
- [x] JSON extraction handles markdown-wrapped responses
- [x] Cloudflare tunnel routes correctly
- [ ] Test with REAL Revit data (waiting on team)
- [ ] Tune prompts based on real findings quality
- [ ] Pre-generate demo report for fallback

---

## Quick Connectivity Test (anyone, 30 seconds)

Open this URL in any browser on your machine:

```
https://orphanx.chrisfrance.ai/sse
```

You should see streaming text that starts with:
```
event: endpoint
data: /messages/?session_id=...
```

If you see that, your machine can reach the server. If you get a timeout or error, your network is blocking it.

---

## Reporting Issues

Send Chris:
1. What test number failed
2. Screenshot of the error
3. What machine (whose laptop)
4. Did the browser test work? (the /sse URL)
