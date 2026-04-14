# Orphan X — Architecture & Build Plan

**Team:** Chris France (AI/MCP backend), Ignacio Benito Soto, Oskar Lindstrom, Petra O'Sullivan
**GitHub:** https://github.com/ibenitosoto/OrphanX
**Event:** Autodesk DevCon 2026 Dynamo Day Hackathon — April 14, Amsterdam

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  REVIT + DYNAMO                      │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │          Python Script Node (CPython3)        │   │
│  │                                               │   │
│  │  Phase 1: Extract MEP systems from Revit API  │   │
│  │  Phase 2: Find orphaned elements              │   │
│  │  Phase 3: Call MCP server (SSE + JSON-RPC)    │   │
│  │  Phase 4: Color-code elements by severity     │   │
│  └──────────────────┬───────────────────────────┘   │
│                     │                                │
│                     │ HTTPS (SSE + JSON-RPC)         │
└─────────────────────┼───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│           ORPHAN X MCP SERVER (Cloud VPS)            │
│           https://orphanx.chrisfrance.ai             │
│                                                      │
│  ┌───────────────┐  ┌────────────────────────────┐  │
│  │   FastMCP     │  │   LLM (Claude Sonnet 4.6)  │  │
│  │   SSE on 8620 │  │   via Anthropic API         │  │
│  │               │  │                             │  │
│  │ 3 MCP Tools:  │──│ System prompts with full    │  │
│  │ audit_systems │  │ MEP engineering knowledge:  │  │
│  │ classify_     │  │ • ASHRAE 188 (dead legs)    │  │
│  │   orphans     │  │ • NFPA 13 (sprinklers)      │  │
│  │ generate_     │  │ • IPC 901.2 (venting)       │  │
│  │   report      │  │ • NEC (electrical)          │  │
│  └───────────────┘  └────────────────────────────┘  │
│                                                      │
│  Ubuntu 24.04 | Python 3.12 | Cloudflare Tunnel     │
└─────────────────────────────────────────────────────┘
```

---

## MCP Server — How It Works

### Transport: SSE (Server-Sent Events)

The MCP server uses SSE transport over HTTPS. The client (our Dynamo script) follows this protocol:

1. **Connect:** `GET https://orphanx.chrisfrance.ai/sse` — opens persistent SSE stream
2. **Get endpoint:** Server sends `data: /messages/?session_id=xxx` on the SSE stream
3. **Initialize:** `POST /messages/?session_id=xxx` with JSON-RPC `initialize` request
4. **Read init response** from SSE stream (not from POST body — POST just returns "Accepted")
5. **Notify:** `POST` with `notifications/initialized`
6. **Call tool:** `POST` with `tools/call` — e.g., `audit_systems` with `systems_json` argument
7. **Read result** from SSE stream — JSON-RPC response with findings
8. **Close** SSE stream

**Key gotcha:** The POST response body is always "Accepted". The actual JSON-RPC result comes back on the SSE stream. You MUST keep the SSE stream open while making POST calls.

### Server Code (`server/main.py`)

```python
from mcp.server.fastmcp import FastMCP
import anthropic

mcp = FastMCP("orphan-x", host="0.0.0.0", port=8620)
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-6"

def _call_claude(system_prompt, user_content, max_tokens=4096):
    response = claude.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text

@mcp.tool()
def audit_systems(systems_json: str) -> str:
    result = _call_claude(AUDIT_SYSTEM_PROMPT, user_msg, max_tokens=8192)
    return json.dumps(parsed_result)
```

### Three MCP Tools

| Tool | Input | What it does | Output |
|------|-------|-------------|--------|
| `audit_systems` | JSON with systems + elements + connections | Claude traces network topology, finds dead legs, broken chains, code violations | JSON array of findings with severity, element IDs, code references |
| `classify_orphans` | JSON with orphaned elements + nearest neighbors | Claude determines likely system, assesses risk | JSON array of classifications with confidence, severity |
| `generate_report` | Combined findings from above | Claude writes plain-English QA/QC report | Formatted text report organized by severity |

### System Prompts (`server/prompts.py`)

The AI intelligence lives in three system prompts:

**AUDIT_SYSTEM_PROMPT** — Full MEP engineering knowledge:
- System completeness chains (AHU → duct → VAV → diffuser, etc.)
- Dead leg detection: pipe connected one end, dead-end other end, stagnant water
- ASHRAE 188: dead legs >6x pipe diameter = Legionella stagnation risk
- NFPA 13: sprinkler coverage requirements
- IPC 901.2: venting requirements for sanitary waste
- Severity tiers: Patient Safety > Life Safety > Code Violation > Major > Minor
- False positive management: capped stubs, backup circuits, test ports are OK

**CLASSIFY_ORPHANS_PROMPT** — Orphan element classification:
- Match orphans to likely systems by category, family, type, proximity
- Hospital context: orphaned HVAC in patient areas = infection control risk

**REPORT_PROMPT** — Report generation:
- Organize by severity, plain English, actionable recommendations

### Dead Leg Detection — How It Works

The `connected_to` field on every element is the key. When Claude receives the system data, it sees:

```json
{
  "system_type": "DomesticHotWater",
  "elements": [
    {"element_id": "100", "category": "Pipes", "connected_to": ["101", "102"]},
    {"element_id": "101", "category": "Pipe Fittings", "connected_to": ["100", "103"]},
    {"element_id": "102", "category": "Pipes", "connected_to": ["100"]},  // ← DEAD END
  ]
}
```

Element 102 connects to 100 but nothing on the other end. On a domestic hot water system in a hospital, that's a dead leg where water stagnates and Legionella grows. Claude flags it as Critical - Patient Safety with ASHRAE 188 reference.

---

## Replacing Claude with a Local LLM

The MCP server is designed so the LLM is a single swap point. Everything else stays the same.

### What to change

Only ONE function in `server/main.py`:

```python
# CURRENT: Claude API
def _call_claude(system_prompt, user_content, max_tokens=4096):
    response = claude.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text
```

### Option 1: Ollama (local, free)

```python
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.1:70b"  # or mistral, gemma2, etc.

def _call_llm(system_prompt, user_content, max_tokens=4096):
    response = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
    })
    return response.json()["message"]["content"]
```

Install: `curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.1:70b`

### Option 2: vLLM (local, faster for large models)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

def _call_llm(system_prompt, user_content, max_tokens=4096):
    response = client.chat.completions.create(
        model="meta-llama/Llama-3.1-70B-Instruct",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content
```

### Option 3: Any OpenAI-compatible API

```python
from openai import OpenAI

client = OpenAI(base_url="https://your-server/v1", api_key="your-key")

def _call_llm(system_prompt, user_content, max_tokens=4096):
    response = client.chat.completions.create(
        model="your-model",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content
```

### What stays the same

- FastMCP server (SSE transport, 3 tools, JSON-RPC protocol)
- System prompts (ASHRAE 188, NFPA 13, IPC knowledge)
- Dynamo script (extraction, MCP call, color overrides)
- Input/output JSON format
- The entire Revit integration

### LLM requirements for this use case

- **Must handle long context** — system data can be 50K+ tokens for large models
- **Must follow JSON output instructions** — the prompts say "return ONLY valid JSON"
- **Recommended minimum:** 70B parameter model for reliable MEP reasoning
- **Tested with:** Claude Sonnet 4.6 (cloud API)
- **Untested but should work:** Llama 3.1 70B, Mistral Large, Gemma 2 27B
- **Too small:** 7B/8B models will hallucinate findings and miss real issues

---

## VPS Deployment

- **VPS:** DigitalOcean 162.243.184.115, Ubuntu 24.04
- **Code:** `/opt/orphanx/` with Python 3.12 venv
- **Tunnel:** Cloudflare tunnel routes `orphanx.chrisfrance.ai` → `localhost:8620`
- **Env:** `.env` file with `ANTHROPIC_API_KEY`
- **Deploy:** `ssh root@162.243.184.115`, edit files, restart process

### Dependencies

```
fastmcp
anthropic
python-dotenv
```

---

## Dynamo Script — Client Side

One Python Script node in Dynamo (CPython3) does everything:

**File:** `dynamo/orphanx_all_in_one.py`

### Phase 1: Extract
- `FilteredElementCollector` gets MechanicalSystem, PipingSystem, ElectricalSystem
- For each system: get elements via `DuctNetwork`, `PipingNetwork`, or `.Elements`
- For each element: serialize ID, category, family, type, level, connections, parameters
- Revit 2026 compat: `eid_int()` helper (`.Value` vs `.IntegerValue`)

### Phase 2: Find Orphans
- Collect all element IDs that belong to any system
- Scan 14 MEP categories for elements NOT in the set
- For each orphan: find 3 nearest system elements by Euclidean distance

### Phase 3: Call MCP Server
- SSE + JSON-RPC protocol (see transport section above)
- Sends `systems_json` to `audit_systems`, `orphans_json` to `classify_orphans`
- SSL bypass for corporate networks
- 120-second timeout for AI analysis

### Phase 4: Apply Overrides
- Map severity → color (RED/ORANGE/YELLOW/CYAN/GRAY)
- Create or reuse "Orphan X - QA Audit" 3D view
- Apply `OverrideGraphicSettings` to each flagged element
- Solid fill pattern + line weight by severity

### Output Files (saved to Desktop)
- `orphanx_log.txt` — full run log
- `orphanx_results.json` — AI findings + errors
- `orphanx_extraction.json` — raw system/orphan data for manual analysis

---

## Presentation (3 minutes)

| Section | Time | Content |
|---------|------|---------|
| Intro | 15s | Team name, one-line pitch |
| Problem | 30s | Dead legs → Legionella → patients die. Engineer takes 3 days to audit. |
| Product | 60s | One script, one click, AI traces every pipe. Finds what humans miss. |
| Demo | 45s | Run script, show color-coded model, zoom to red dead leg |
| Wrap-up | 30s | 3 days → 60 seconds. Works on any model. Swappable AI. |
