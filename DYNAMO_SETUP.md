# Orphan X — Dynamo Setup Guide

**MCP Server:** `https://orphanx.chrisfrance.ai/sse`

---

## What You Need to Know

**DynamoMCP v0.0.18 is a graph-building AI** — it creates, connects, and runs Dynamo nodes via chat. It does NOT query Revit data directly. Our Revit data extraction happens via Python Script nodes that run inside the graph.

**The workflow:**
1. Python Script node extracts MEP data from Revit (our code)
2. Python Script node sends that data to `orphanx.chrisfrance.ai` (HTTP call)
3. Python Script node receives AI findings back
4. Python Script node applies color overrides to the Revit model

---

## Option A: Quick Manual Setup (10 min, no MCP needed)

Just create the graph by hand in Dynamo. Four Python Script nodes, wired in sequence.

### Step 1: Create the extraction node

1. Open Dynamo (with a Revit MEP model loaded)
2. Add a **Python Script** node (search "Python" in node library)
3. Right-click the node → **Engine** → **CPython3**
4. Double-click to edit, paste the ENTIRE contents of `dynamo/extract_mep_systems.py` from the GitHub repo
5. Add an input: connect a **String** node with value `hospital`
6. Run the graph — the output should be a large JSON string with all MEP systems

### Step 2: Create the MCP caller node

1. Add a second **Python Script** node (CPython3)
2. Paste this code:

```python
"""Send extracted MEP data to Orphan X MCP server and get audit findings."""
import json
import urllib.request
import ssl

systems_json = IN[0]  # JSON string from extract_mep_systems.py

MCP_URL = "https://orphanx.chrisfrance.ai"

# Create SSL context that works in Dynamo's Python environment
ctx = ssl.create_default_context()

try:
    # Step 1: Connect to SSE endpoint to get session
    sse_req = urllib.request.Request(MCP_URL + "/sse", method="GET")
    sse_resp = urllib.request.urlopen(sse_req, timeout=10, context=ctx)
    sse_data = sse_resp.read(500).decode("utf-8")
    
    # Parse session endpoint from SSE response
    # Format: "event: endpoint\ndata: /messages/?session_id=xxx\n"
    endpoint = None
    for line in sse_data.split("\n"):
        if line.startswith("data: ") and "session_id" in line:
            endpoint = line[6:].strip()
            break
    
    if not endpoint:
        OUT = json.dumps({"error": "Could not get session from MCP server", "raw": sse_data[:200]})
    else:
        # Step 2: Call audit_systems tool via JSON-RPC
        tool_call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "audit_systems",
                "arguments": {"systems_json": systems_json}
            }
        }
        
        post_req = urllib.request.Request(
            MCP_URL + endpoint,
            data=json.dumps(tool_call).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        post_resp = urllib.request.urlopen(post_req, timeout=120, context=ctx)
        result = post_resp.read().decode("utf-8")
        
        OUT = result

except Exception as e:
    import traceback
    OUT = json.dumps({"error": str(e), "traceback": traceback.format_exc()})
```

3. Connect the output of Step 1's Python Script node to this node's `IN[0]`

### Step 3: Create the orphan finder + classifier

1. Add a third **Python Script** node (CPython3) for orphan finding
2. Paste the contents of `dynamo/find_orphans.py` from the repo
3. Its output can be sent to a fourth Python Script node that calls `classify_orphans` tool (same HTTP pattern as Step 2, just change the tool name)

### Step 4: Apply visual overrides

1. Add another **Python Script** node (CPython3)
2. Paste the contents of `dynamo/apply_overrides.py` from the repo  
3. Connect the audit findings JSON to `IN[0]`
4. This creates an "Orphan X - QA Audit" 3D view and colors elements:
   - **RED** = Critical Patient Safety / Life Safety
   - **ORANGE** = Critical Code Violation
   - **YELLOW** = Major
   - **CYAN** = Minor

### Step 5: Run

1. Run the full graph
2. Switch to the "Orphan X - QA Audit" 3D view in Revit
3. You should see color-coded elements highlighting all issues

---

## Option B: Use DynamoMCP AI to Build the Graph (if MCP chat is working)

Paste this prompt into the DynamoMCP AI chat. It will build the graph for you using the `create_nodes`, `set_node_value`, and `connect_nodes` tools.

### Prompt to paste:

```
Build an Orphan X MEP audit graph with these steps:

1. Search for Python Script node type using get_nodes_info with searchTerms ["PythonScript", "Python"]

2. Create 4 Python Script nodes arranged left to right:
   - Node 1 at (0, 0): "Extract MEP Systems" 
   - Node 2 at (600, 0): "Send to Orphan X" 
   - Node 3 at (0, 400): "Find Orphans"
   - Node 4 at (1200, 0): "Apply Overrides"

3. Also create a String input node at (-400, 0) with value "hospital"

4. Connect:
   - String node output → Node 1 input port 0
   - Node 1 output → Node 2 input port 0
   - Node 2 output → Node 4 input port 0

5. Group all nodes with title "Orphan X - MEP Audit Pipeline"

6. Run auto_layout_workspace

Do NOT run the graph yet. I need to paste code into each Python Script node first.
```

After the AI creates the graph, double-click each Python Script node and paste the code:
- Node 1: paste `dynamo/extract_mep_systems.py`
- Node 2: paste the MCP caller code from Option A Step 2 above
- Node 3: paste `dynamo/find_orphans.py`  
- Node 4: paste `dynamo/apply_overrides.py`

---

## Connectivity Test (30 seconds)

Before doing anything else, test if your machine can reach the server.

**In a browser:** Go to `https://orphanx.chrisfrance.ai/sse`

You should see:
```
event: endpoint
data: /messages/?session_id=...
```

If you see that, you're good. If not, your network is blocking it — try phone hotspot.

**In Dynamo Python Script node** (quick test):
```python
import urllib.request
import ssl
ctx = ssl.create_default_context()
req = urllib.request.Request("https://orphanx.chrisfrance.ai/sse")
resp = urllib.request.urlopen(req, timeout=5, context=ctx)
OUT = resp.read(200).decode("utf-8")
```

Expected output: `event: endpoint\ndata: /messages/?session_id=...`

---

## DynamoMCP Installation

The `DynamoMCP-v0.0.18.zip` package installs as a Dynamo view extension:

1. Extract the zip — you'll get a `DynamoMCP/` folder
2. Copy the entire `DynamoMCP/` folder to your Dynamo packages directory:
   - `%AppData%\Dynamo\Dynamo Revit\3.6\packages\`
3. Copy `DynamoMCP/extra/MCP_ViewExtensionDefinition.xml` to:
   - `%AppData%\Dynamo\Dynamo Revit\3.6\viewExtensions\`
   - OR `%ProgramData%\Dynamo\Dynamo Revit\3.6\viewExtensions\`
4. Restart Dynamo completely (close and reopen)
5. You should see an MCP chat panel or agent interface in Dynamo

**Package structure:**
```
DynamoMCP/
├── pkg.json                              # Package metadata (engine: dynamo 3.6)
├── bin/
│   ├── MCPExtension.dll                  # Dynamo view extension (loads the MCP server)
│   ├── MCPExtension.pdb                  # Debug symbols
│   ├── MCPExtension.deps.json            # .NET 8.0 dependencies
│   ├── instructions.md                   # AI system prompt for graph building
│   └── mcp_server/                       # MCP server binaries
│       ├── MCPServer.dll                 # The actual MCP server (28 tools)
│       ├── ModelContextProtocol.dll      # MCP protocol library
│       ├── DynamoPlayer.*.dll            # Dynamo player integration
│       └── Microsoft.Extensions.*.dll    # .NET hosting dependencies
└── extra/
    └── MCP_ViewExtensionDefinition.xml   # Extension registration file
```

## Available DynamoMCP Tools (28 total)

These are the tools the AI uses to build graphs. You don't call them directly — the AI chat does.

| Tool | What it does |
|------|-------------|
| `get_workspace_info` | Read current graph state |
| `get_nodes_info` | Search for node types by name |
| `create_nodes` | Add nodes to the graph |
| `set_node_value` | Set a node's input value |
| `connect_nodes` | Wire nodes together |
| `disconnect_nodes` | Remove connections |
| `delete_node` | Remove a node |
| `run_workspace` | Execute the graph |
| `get_node_output_values` | Read results after execution |
| `auto_layout_workspace` | Auto-arrange the graph |
| `create_group` | Group nodes visually |
| `create_notes` | Add annotations |
| `run_graph_from_path` | Run a saved .dyn file |
| ... and 15 more for graph management |

---

## Troubleshooting

**"No module named RevitAPI"** → Make sure the Python Script node engine is set to **CPython3** (right-click → Engine → CPython3)

**SSL errors calling orphanx.chrisfrance.ai** → The `ssl.create_default_context()` should handle this. If not, try adding `ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE` (not ideal but works for hackathon)

**Timeout calling MCP server** → The AI analysis takes 10-30 seconds. Make sure timeout is set to 120 seconds.

**Empty output from extraction** → The model might not have MEP systems. Check in Revit: Systems tab → see if any systems exist.

**"Element has no Location"** → Some Revit elements don't have geometry. The scripts handle this with fallbacks (LocationPoint → LocationCurve → BoundingBox center).

**Corporate firewall blocks orphanx.chrisfrance.ai** → Try phone hotspot. Or use a different team member's machine.
