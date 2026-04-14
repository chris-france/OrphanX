# Orphan X — Build Plan

**Team:**
- **Chris France** — Mac, Claude Code, MCP server, all code generation
- **Ignacio Benito Soto** (Kirby Group) — Windows, Revit + Dynamo
- **Oskar Lindstrom** (Marioff) — Windows, Revit + Dynamo
- **Petra O'Sullivan** (Red Engineering) — Windows, Revit + Dynamo

**Time:** ~7 productive hours (8:30 AM – 5:00 PM minus setup, lunch, demo prep)

**Core principle:** Build in parallel, connect in the middle, polish at the end.

---

## Machine Setup: Oskar + Ignacio Have Admin

Oskar and Ignacio have admin access and can install software. This eliminates our biggest risk (network connectivity). Strategy:

**Ignacio's machine = the demo machine.** Runs Dynamo + Revit + the MCP server locally. Agentic node connects to `localhost:8620`. No WiFi dependency.

### Install on Ignacio's machine (first thing):
```powershell
# Python 3.12
winget install Python.Python.3.12

# Git (to pull from repo)
winget install Git.Git

# Then in a terminal:
git clone https://github.com/ibenitosoto/OrphanX.git
cd OrphanX/server
python -m venv venv
venv\Scripts\activate
pip install fastmcp anthropic fastapi uvicorn requests
```

### Install on Oskar's machine (backup):
Same setup. If Ignacio's machine has issues, Oskar's is ready to go.

### Chris builds on Mac, pushes to GitHub, they pull.
Chris writes all the code → pushes to repo → Ignacio/Oskar `git pull` → restart server. Fast iteration loop.

---

## Critical First Hour: Discovery (8:00 – 9:00)

Before writing a single line of production code, we need answers to questions that determine the entire architecture.

### Windows Team (all 3) — Explore the Alpha Tooling

Open Dynamo with the agentic nodes enabled. Answer these questions and report back to Chris:

**Agentic Node Discovery:**
1. Open a Revit model with MEP systems (Snowdon Towers or any MEP model)
2. Drop an `AgentProcess.GetAllAvailableTools` node — what tools does the Revit MCP expose?
3. Write down EVERY tool name and its parameters — we need the exact schema
4. Specifically look for:
   - Can it list all MEP systems? (MechanicalSystem, PipingSystem, ElectricalSystem)
   - Can it get elements within a system?
   - Can it get element connectivity (what connects to what)?
   - Can it get elements NOT in any system (orphans)?
   - Can it get element parameters (size, flow, level)?
   - Can it apply view overrides / color changes?
5. Try a `Send Request` node — what format does it expect? What does it return?
6. Can the agentic node connect to an external MCP server via SSE? (i.e., `http://<ip>:8620/sse`)
7. Save a sample .dyn file with one working agentic node and send it to Chris — he needs the JSON schema

**If the Revit MCP can't get system data:**
- Use a Python Script node in Dynamo to query Revit API directly:
  ```python
  # In Dynamo Python Script node
  import clr
  clr.AddReference('RevitAPI')
  from Autodesk.Revit.DB import *
  from Autodesk.Revit.DB.Mechanical import *
  from Autodesk.Revit.DB.Plumbing import *
  from Autodesk.Revit.DB.Electrical import *
  
  doc = __revit__.ActiveUIDocument.Document
  
  # Get all MEP systems
  mech_systems = FilteredElementCollector(doc).OfClass(MechanicalSystem).ToElements()
  pipe_systems = FilteredElementCollector(doc).OfClass(PipingSystem).ToElements()
  elec_systems = FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements()
  ```
- This is our **fallback** — extract data via Python Script node, pass to agentic node for AI analysis

**Document everything.** Take screenshots. Chris needs this info to build the right server.

### Chris (Mac) — Setup + Mock MCP Server

While the team explores, Chris sets up the development environment and builds a mock version of the MCP server that works with synthetic data:

```bash
# Project setup
cd /tmp/OrphanX
python3.12 -m venv venv && source venv/activate
pip install fastmcp anthropic fastapi uvicorn requests
```

Build the MCP server skeleton with hardcoded mock data so the AI analysis logic can be tested independently of Dynamo. When the Windows team reports back with real data shapes, swap mock data for real.

---

## Phase 1: Parallel Build (9:00 – 11:30)

### Chris (Mac) — Build the MCP Server

**Priority order:**

#### 1. `audit_systems` tool (core — spend the most time here)
- Receives: list of MEP systems with their elements, types, connectivity
- Claude system prompt with full MEP engineering knowledge:
  - System completeness chains by type (see README Section 3)
  - ASHRAE 188 dead leg rules (>6x pipe diameter = stagnation risk)
  - IPC code awareness (venting requirements)
  - Life safety rules (sprinkler coverage)
  - Hospital-specific severity escalation
- Returns: findings with severity, description, affected elements, recommendation
- **Patient Safety findings first** — dead legs in domestic water get highest severity
- Test with mock data: verify finding quality, false positive rate, recommendation specificity

#### 2. `classify_orphans` tool
- Receives: elements not in any system + their nearest neighbors
- Claude determines: likely intended system, confidence score, recommended action
- Hospital context: orphaned HVAC elements in patient areas = infection control concern

#### 3. `generate_report` tool
- Receives: all findings from audit_systems + classify_orphans
- Returns: formatted plain-English report organized by:
  1. Patient Safety findings
  2. Life Safety / Code findings
  3. Major findings
  4. Minor findings
- Each finding: what's wrong, why it matters, what to do, code reference if applicable

#### 4. Server configuration
- FastMCP with SSE transport on port 8620
- Also support stdio transport (if agentic nodes require it)
- CORS enabled for local network access
- Health check endpoint for testing connectivity

### Petra — Prepare the Demo Model

- Open Snowdon Towers MEP model (or rme_advanced_sample_project.rvt)
- Frame it as a "generic hospital" for the demo narrative
- **Seed the test cases** (all of these — we need findings in every discipline):

| # | What to Seed | Discipline | Expected Severity |
|---|---|---|---|
| 1 | 3-4 dead legs in domestic hot water (Level 3) | Plumbing | Critical - Patient Safety |
| 2 | 2 orphaned cold water branches (Level 2) | Plumbing | Critical - Patient Safety |
| 3 | 3 orphaned supply diffusers (Level 2) | Mechanical | Major |
| 4 | Disconnect a branch duct from main (Level 1) | Mechanical | Major |
| 5 | Remove vent from plumbing fixture group (Level 3) | Plumbing | Critical - Code |
| 6 | Delete branch line from 4 sprinkler heads (Level 2) | Fire Protection | Critical - Life Safety |
| 7 | Cross-connect: return grille in supply air system | Mechanical | Major |
| 8 | Empty circuit on electrical panel | Electrical | Major |

- Create a duplicate 3D view named **"Orphan X Audit"** — this is where color overrides go
- Create shared parameters if needed: `OX_Status`, `OX_Severity`, `OX_Note`
- **Document** the element IDs of seeded issues so we can verify the auditor finds them

### Ignacio — Dynamo Graph Foundation

Based on the discovery results from the first hour:

- Build the Dynamo graph skeleton:
  - Agentic Node #1: Revit MCP → query all MEP systems and elements
  - OR Python Script node fallback: query Revit API → serialize to JSON
  - Agentic Node #2: Orphan X MCP → send system data, receive findings
  - Standard nodes: parse findings JSON
  - View override nodes: map severity to color, apply to elements
- Test Agentic Node #2 connectivity to Chris's Mac (`http://<chris-mac-ip>:8620/sse`)
- If SSE doesn't work: try stdio transport, or HTTP POST fallback via Python Script node

### Oskar — Dynamo Graph: View Overrides

Build the downstream Dynamo nodes that apply visual results:

- **Input:** List of element IDs + severity levels from the MCP response
- **Color mapping:**
  - Green (0, 180, 0) = Healthy
  - Yellow (255, 200, 0) = Warning / Minor
  - Orange (255, 140, 0) = Major
  - Red (220, 0, 0) = Critical (patient safety + code)
  - Gray (180, 180, 180) = Orphaned
- **Nodes needed:**
  - `OverrideGraphicSettings.ByProperties` — set projection surface color
  - `Element.SetOverrides` — apply to specific elements in the "Orphan X Audit" view
  - Filter nodes to separate findings by severity
- Test with hardcoded element IDs first, then connect to live data from Agentic Node #2

---

## Phase 2: Integration (11:30 – 1:00, through lunch)

### Network Setup (SIMPLIFIED — server runs locally)
- MCP server runs on **Ignacio's machine** (same machine as Dynamo)
- Agentic node connects to `http://localhost:8620/sse` — no WiFi dependency
- Chris pushes code to GitHub → Ignacio runs `git pull` in the OrphanX folder → restarts server
- **Oskar's machine is the backup** — same setup, ready to go if Ignacio's has issues
- Only external network needed: Anthropic API (Claude) — standard HTTPS outbound

### Connect the Pipeline
1. Agentic Node #1 extracts real system data from seeded model
2. Verify data shape matches what Chris's MCP server expects — adjust server if needed
3. Agentic Node #2 sends data to Orphan X MCP server
4. Verify AI findings are correct — does it find all 8 seeded issues?
5. View overrides apply to correct elements with correct colors
6. End-to-end: one click in Dynamo → color-coded model + report

### Debug Priorities
1. **Data shape mismatch** (most likely issue) — the real Revit data won't match mock format perfectly. Chris adjusts the MCP server parser.
2. **Network connectivity** — firewall, wrong IP, transport mismatch. Try all fallbacks.
3. **False positives** — AI flags things that aren't problems. Tune the system prompt with MEP team input.
4. **False negatives** — AI misses seeded issues. Check if the data extraction captured enough info.
5. **View override errors** — wrong elements colored, or overrides not applying. Check element ID mapping.

---

## Phase 3: Polish + Stretch Goals (1:00 – 3:00)

Priority order — do as many as time allows:

1. **Tune AI findings quality** — iterate on system prompt with MEP team. They review every finding: is it accurate? Is the severity right? Is the recommendation actionable?
2. **Report formatting** — make the `generate_report` output clean, professional, printable
3. **Cross-connection detection** — verify the AI catches the return grille in supply air system
4. **Summary statistics** — total systems, health %, findings by discipline, findings by severity
5. **Export findings to CSV** — one-click export for coordination meetings
6. **Test with a second model** — proves it's not hardcoded for one project
7. **Dynamo Player button** — package the graph so it's one-click from Revit (no graph visible)

---

## Phase 4: Demo Prep (3:00 – 4:30)

### Demo Script (5 minutes)

| Time | What | Who |
|---|---|---|
| 0:00 – 0:45 | **The Story** — Legionella, dead legs, patients at risk. Why existing tools can't find this. | Petra |
| 0:45 – 1:15 | **The Model** — Show the hospital MEP model. "This passed review." | Petra |
| 1:15 – 1:45 | **Run Orphan X** — Open Dynamo, hit Run, show agentic nodes working | Ignacio |
| 1:45 – 2:45 | **The Kill Shot** — Zoom to red dead legs. "This is where patients get sick." Then show ALL disciplines: sprinklers, HVAC orphans, electrical. | Oskar |
| 2:45 – 3:30 | **The Report** — Show findings by severity. Plain English. ASHRAE 188 reference. | Oskar |
| 3:30 – 4:15 | **Architecture** — Quick slide: 2 agentic nodes + MCP server. How it works. | Chris |
| 4:15 – 5:00 | **Impact** — "2 days → 2 minutes. Works on any model. Saves patients." | Petra |

### Fallback Plan

If the live demo breaks (it's a hackathon — things break):

1. **Pre-screenshot** the color-coded model view before demo time
2. **Pre-generate** the report output as a text file
3. **Architecture walkthrough** — show the code, explain the MCP pattern, show the system prompt
4. "We had it running 30 minutes ago — here's the proof. Let us show you the architecture."

### Pre-Demo Checklist
- [ ] MCP server running on port 8620
- [ ] Dynamo graph opens without errors
- [ ] Run button executes full pipeline
- [ ] Color-coded view shows all 5 colors
- [ ] Report generates with all findings
- [ ] Revit zoomed to Level 3 patient wing (red dead legs visible)
- [ ] Backup screenshots saved
- [ ] Backup report text saved
- [ ] All team members know their demo role

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agentic nodes can't connect to external MCP | Medium | High | Fallback: Python Script node makes HTTP POST to localhost:8620 |
| Revit MCP doesn't expose system/connectivity data | Medium | High | Fallback: Python Script node queries Revit API directly |
| ~~Hackathon WiFi blocks inter-device traffic~~ | ~~High~~ | ~~Medium~~ | **ELIMINATED** — MCP server runs on same machine as Dynamo (localhost) |
| AI produces false positives | Medium | Medium | MEP team reviews and tunes system prompt during Phase 3 |
| Snowdon Towers lacks enough MEP data | Low | Medium | Use rme_advanced_sample_project.rvt instead, or seed more test cases |
| .dyn graph generated on Mac doesn't open in Dynamo | Low | Medium | Team builds graph manually on Windows using Chris's node specs |
| Claude API rate limit / downtime | Low | Critical | Pre-cache responses for demo, have offline mode with hardcoded results |

---

## File Structure

```
OrphanX/
├── README.md                      # Architecture brief (this repo)
├── BUILD_PLAN.md                  # This file
├── server/                        # MCP server (Chris builds on Mac)
│   ├── main.py                    # FastMCP server entry point
│   ├── tools/
│   │   ├── audit_systems.py       # System completeness analysis
│   │   ├── classify_orphans.py    # Orphan element classification
│   │   └── generate_report.py     # QA/QC report generator
│   ├── prompts/
│   │   └── system_prompt.py       # MEP engineering knowledge for Claude
│   ├── requirements.txt
│   └── .env.example               # ANTHROPIC_API_KEY=
├── dynamo/                        # Dynamo graph files
│   ├── OrphanX.dyn                # Main graph
│   └── python_scripts/            # Python Script node code (fallback)
│       ├── extract_mep_systems.py # Query Revit API for system data
│       ├── find_orphans.py        # Find elements not in any system
│       └── apply_overrides.py     # Color-code elements by severity
├── test_data/                     # Mock data for testing without Revit
│   ├── mock_systems.json          # Sample system extraction
│   ├── mock_orphans.json          # Sample orphaned elements
│   └── seeded_issues.md           # What we planted + expected findings
└── demo/                          # Demo materials
    ├── screenshots/               # Backup screenshots of results
    └── sample_report.txt          # Pre-generated report for fallback
```

---

## Network Diagram (Hackathon Setup)

```
   Chris's Mac                 Ignacio's Windows Machine (DEMO MACHINE)
┌──────────────┐            ┌──────────────────────────────────────┐
│              │  git push  │                                      │
│  Claude Code │───────────►│  Dynamo + Revit                      │
│  (writes all │  git pull  │  ├── Agentic Nodes                   │
│   the code)  │            │  ├── Python Scripts                   │
│              │            │  └── View Overrides                   │
└──────────────┘            │                                      │
                            │  MCP Server (localhost:8620)          │
                            │  ├── audit_systems                    │
                            │  ├── classify_orphans                 │
                            │  └── generate_report                  │
                            └──────────────┬───────────────────────┘
                                           │ HTTPS
                                           ▼
                            ┌──────────────────────────┐
                            │  Anthropic API (Claude)   │
                            └──────────────────────────┘

   Oskar's Windows Machine (BACKUP)
┌──────────────────────────────────────┐
│  Same setup — ready if Ignacio's     │
│  machine has issues                  │
└──────────────────────────────────────┘
```

**Code flow:** Chris writes code on Mac → pushes to GitHub → Ignacio/Oskar `git pull` → restart server. Fast iteration, no file transfers needed.

---

**When this plan is approved, Chris starts building `server/` immediately. Windows team starts discovery + model prep simultaneously.**
