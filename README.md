# Orphan X

**AI-Powered MEP System Completeness & Integrity Checker**

*Finding the orphaned elements that put patients at risk.*

> Autodesk DevCon Hackathon — April 14, 2026 — Amsterdam
> Team Orphan X — Dynamo Day Hackathon Entry

---

## 1. The Problem

### When Orphaned Pipes Kill

Dead legs in hospital water systems — pipe segments where water sits stagnant — breed Legionella bacteria. Patients die from this. It has happened multiple times at healthcare facilities. These dead legs pass every visual review and every clash detection tool. They look like normal pipes. But the water inside them is going nowhere — and becoming a breeding ground for deadly bacteria.

### The Broader Problem

Dead legs are the most dangerous example of a systemic issue in MEP modeling: orphaned and incomplete systems that pass every visual and geometric check but fail at the logical level. MEP models in hospitals, data centers, labs, and commercial buildings have thousands of mechanical, electrical, and plumbing elements — all of which must be connected into complete, logical systems.

**What goes wrong:**

- **Orphaned elements** — Diffusers, sprinkler heads, receptacles, or fixtures that exist in the model but aren't connected to any system. They look correct in plan view but have no functional relationship to the building systems.
- **Dead ends** — Pipe/duct/conduit segments that connect on one end but terminate without reaching a device. In domestic water systems, these create stagnant water zones where Legionella colonizes.
- **Incomplete systems** — A supply air system that traces from the AHU through main ducts but has branches that terminate without diffusers. A panel with 20 circuits but only 14 connected to devices.
- **Missing components** — A hydronic system without a pump. A sanitary system with fixtures but no vent. A sprinkler branch without a flow switch.
- **Cross-connected systems** — Elements accidentally assigned to the wrong system — a return air grille in the supply air system, a hot water pipe in the chilled water system.

### Why It Matters

- Dead legs in hospital water systems breed Legionella — ~10% mortality rate in immunocompromised patients
- Orphaned sprinkler heads mean no fire protection coverage — a life safety failure
- Incomplete exhaust systems in labs can expose staff to hazardous fumes
- Manual QA/QC takes 20-40 hours per discipline on a complex project
- Navisworks checks geometry, not systems — two ducts can pass clash detection but still be logically disconnected

> *The core insight: MEP model quality is not just geometric — it's logical. And in healthcare facilities, logical failures don't just cost money — they cost lives.*

---

## 2. The Solution: Orphan X

An agentic Dynamo graph that queries every MEP system in a Revit model, analyzes each system for completeness and integrity using AI, and produces a color-coded model view plus a prioritized findings report — all in a single graph execution. In a hospital context, it hunts the dead legs, orphaned pipes, and incomplete systems that create conditions for waterborne pathogen growth.

### One-Line Pitch

> *"Finds the MEP errors that kill patients and that clash detection can't see — dead legs, orphans, incomplete systems — in minutes instead of days."*

### Capabilities

| Capability | Description |
|---|---|
| **Extract all MEP systems** | Queries the Revit model via Dynamo MCP — every MechanicalSystem, PipingSystem, ElectricalSystem, and their connected elements. Also finds elements NOT in any system. |
| **Classify system type** | Identifies system types: supply air, return air, exhaust, domestic hot/cold water, chilled water, sanitary waste, power, lighting, fire protection, etc. |
| **AI completeness analysis** | For each system, AI evaluates whether the system is logically complete based on MEP engineering rules. |
| **Orphan detection** | Finds every MEP element that belongs to no system. Categorizes by discipline, level, and severity. |
| **Dead-end detection** | Identifies pipe/duct/conduit segments that terminate without reaching a device — the Legionella risk in water systems. |
| **Cross-connection detection** | Flags elements in the wrong system based on category, type, and connected elements. |
| **Severity scoring** | Critical (patient safety/code), Major (field issue), Minor (model hygiene). |
| **Visual output** | Color-coded Revit view: green = healthy, yellow = warning, orange = major, red = critical, gray = orphaned. |

---

## 3. MEP System Completeness Rules

### Mechanical (HVAC)

| System Type | Required Chain | Common Failures |
|---|---|---|
| Supply Air | AHU → Main Duct → Branch Ducts → VAV/Terminal Units → Diffusers | Orphaned diffusers, branches without terminals |
| Return Air | Return Grilles → Branch Ducts → Main Return → AHU | Missing return path, grilles not in system |
| Exhaust | Exhaust Grilles → Ductwork → Exhaust Fan → Exterior Termination | Grilles without fan, missing exterior termination |
| Hydronic | Chiller/Boiler → Pumps → Main Pipes → Branch Pipes → Coils/FCUs | Missing pump, open loops, wrong pipe system |

### Electrical

| System Type | Required Chain | Common Failures |
|---|---|---|
| Power Distribution | Transformer → Switchgear → Panels → Circuits → Devices/Equipment | Devices without circuits, panels over capacity |
| Lighting | Panel → Circuits → Light Fixtures + Switches | Fixtures without circuits, orphaned fixtures |
| Low Voltage | Panels → Devices (FA, Data, Security) | Fire alarm devices not on FA panel |

### Plumbing

| System Type | Required Chain | Common Failures |
|---|---|---|
| **Domestic Water (CRITICAL in healthcare)** | Main → Risers → Branch Lines → Fixtures (+ shut-off valves) | **DEAD LEGS (Legionella risk)**, fixtures without supply, dead-end branches creating stagnant water |
| Sanitary Waste | Fixtures → Traps → Waste Pipes → Vents → Stacks → Building Drain | Fixtures without traps, missing vents (code violation) |
| Storm Drainage | Roof Drains → Leaders → Storm Main → Building Storm Drain | Drains without leaders, missing overflow drains |

### Fire Protection

| System Type | Required Chain | Common Failures |
|---|---|---|
| Sprinkler | Riser → Cross Mains → Branch Lines → Sprinkler Heads | Heads without branch lines, coverage gaps |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DYNAMO GRAPH (.dyn)                       │
│                                                             │
│  ┌────────────────────┐      ┌────────────────────────┐    │
│  │  Agentic Node #1   │      │  Agentic Node #2       │    │
│  │  Revit MCP         │      │  Orphan X MCP          │    │
│  │                    │      │  (Custom - AI Engine)   │    │
│  │  • Get MEP systems │      │                        │    │
│  │  • Get elements    │      │  • Completeness audit  │    │
│  │  • Get orphans     │      │  • Orphan classify     │    │
│  │  • Get connectivity│      │  • Severity scoring    │    │
│  └────────┬───────────┘      │  • Report generation   │    │
│           │                  └───────────┬────────────┘    │
│           └──────────┬───────────────────┘                  │
│                      ▼                                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             Standard Dynamo Nodes                     │  │
│  │  Filter by severity → Map to colors → View overrides │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              ORPHAN X MCP SERVER (port 8620)                 │
│              Runs on Mac / any machine                       │
│                                                             │
│  FastAPI + FastMCP (SSE transport)                          │
│  ┌────────────────────────────────────────────────────┐    │
│  │  audit_systems(systems_data)                        │    │
│  │    → Completeness analysis via Claude               │    │
│  │  classify_orphans(orphan_elements)                  │    │
│  │    → Likely system + corrective action              │    │
│  │  generate_report(all_findings)                      │    │
│  │    → Plain-English QA/QC report by discipline       │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Runs On | Built By |
|---|---|---|---|
| Dynamo Graph (.dyn) | Agentic nodes + Python Script nodes + standard nodes | Windows (Revit + Dynamo) | Claude Code (JSON on Mac) |
| Revit MCP Connection | Agentic Node → Revit MCP | Within Dynamo | Configured in graph |
| Orphan X MCP Server | Python FastAPI + Claude API + FastMCP | Mac / any machine (port 8620) | Claude Code |
| Visual Output | Dynamo view overrides by severity | Within Dynamo/Revit | Standard nodes |

---

## 5. MCP Server — Tool Definitions

### Tool 1: `audit_systems`

```json
{
  "input": {
    "systems": [
      {
        "system_id": "12345",
        "system_name": "Domestic Hot Water 1",
        "system_type": "DomesticHotWater",
        "discipline": "Plumbing",
        "elements": [
          {
            "element_id": "67890",
            "category": "Pipe Segments",
            "family": "Copper",
            "type": "1 inch",
            "level": "Level 3",
            "connected_to": ["45678"],
            "parameters": {"System Type": "Domestic Hot Water", "Size": "1\""}
          }
        ]
      }
    ]
  },
  "output": {
    "findings": [
      {
        "system_id": "12345",
        "system_name": "Domestic Hot Water 1",
        "finding_type": "dead_leg",
        "severity": "Critical - Patient Safety",
        "description": "4 dead legs in DHW system on Level 3 Patient Wing. Branch pipes terminate 8-14 ft from nearest fixture. Stagnant hot water at Legionella colonization temperature.",
        "affected_elements": ["33201", "33202", "33205", "33208"],
        "recommendation": "Remove dead legs or install recirculation loops per ASHRAE 188.",
        "code_reference": "ASHRAE Standard 188 - Legionellosis: Risk Management for Building Water Systems"
      }
    ]
  }
}
```

### Tool 2: `classify_orphans`

```json
{
  "input": {
    "orphans": [
      {
        "element_id": "99999",
        "category": "Air Terminals",
        "family": "Return Air Grille",
        "type": "20x20",
        "level": "Level 3",
        "nearest_elements": ["88888", "88889"]
      }
    ]
  },
  "output": {
    "classifications": [
      {
        "element_id": "99999",
        "likely_system_type": "ReturnAir",
        "confidence": 92,
        "reasoning": "Return Air Grille on Level 3, nearest elements are return duct segments.",
        "severity": "Major",
        "action": "Connect to nearest return duct segment and add to Return Air 1 system."
      }
    ]
  }
}
```

### Tool 3: `generate_report`

Produces a plain-English QA/QC report organized by discipline and severity, with patient safety findings prioritized.

---

## 6. Visual Output — Color-Coded QA/QC View

| Color | Meaning | Example |
|---|---|---|
| **GREEN** | Healthy — element in complete system | Diffuser connected to VAV connected to AHU |
| **YELLOW** | Warning — minor issue | Element in system but missing optional parameter |
| **ORANGE** | Major — incomplete chain or dead end | Duct branch terminating without terminal unit |
| **RED** | Critical — patient safety or code violation | Dead leg in hospital water system, orphaned sprinkler head |
| **GRAY** | Orphaned — not in any system | Diffuser placed but never connected to ductwork |

---

## 7. Why This Wins

| Judge Criteria | How Orphan X Delivers |
|---|---|
| **Humanitarian impact** | Dead legs in hospital water systems kill people. This tool finds patient safety hazards no other BIM tool checks for. |
| **All-discipline coverage** | Audits HVAC, electrical, plumbing, and fire protection. Hospital angle leads the story, but works on any building. |
| **Meaningful AI** | Evaluates logical system completeness — not geometry, not parameter values, but whether systems actually work. |
| **MEP engineers built it** | Real MEP domain expertise defines the completeness rules. Not a software team guessing. |
| **Clean Dynamo MCP usage** | Two agentic nodes, clear purposes. Architecture matches exactly what the alpha tooling was designed for. |
| **Visual demo** | Hospital model goes from neutral gray to color-coded health map in 2 minutes. |
| **Scalable** | Works on any Revit MEP model. Healthcare rules layer on top of universal MEP rules. |

---

## Tech Stack

| Component | Technology |
|---|---|
| MCP Server Framework | FastMCP (Python) — SSE transport |
| AI Engine | Claude API (Anthropic SDK) |
| HTTP Framework | FastAPI + Uvicorn |
| Dynamo Graph | .dyn JSON |
| Revit Integration | Dynamo for Revit + Agentic Nodes (Alpha) |
| Visual Output | Revit view overrides via Dynamo |

---

---

## Team Orphan X

| Name | Company | Role |
|---|---|---|
| **Chris France** | AECOM | AI / Backend — MCP server, Claude integration, code generation |
| **Ignacio Benito Soto** | Kirby Group | Dynamo graph, agentic node wiring |
| **Oskar Lindstrom** | Marioff | Dynamo view overrides, MEP domain |
| **Petra O'Sullivan** | Red Engineering | Revit model prep, MEP domain, demo lead |

*Built with Claude Code*
