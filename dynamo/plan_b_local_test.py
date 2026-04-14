"""Orphan X — Plan B: Local test script (no MCP server needed).

Reads extraction JSON, calls Claude API directly, prints findings.

Usage:
    # Set your API key
    export ANTHROPIC_API_KEY=sk-ant-...

    # Run with extraction data
    python3 plan_b_local_test.py orphanx_extraction.json

    # Or run with the test data from the repo
    python3 plan_b_local_test.py ../test-models/orphanx_extraction.json
"""

import json
import os
import sys
import time

try:
    import anthropic
except ImportError:
    print("Installing anthropic SDK...")
    os.system(sys.executable + " -m pip install anthropic -q")
    import anthropic

AUDIT_SYSTEM_PROMPT = """You are an expert MEP (Mechanical, Electrical, Plumbing) systems integrity auditor for building BIM models, with specialized knowledge of healthcare facility requirements.

Your job: analyze MEP system data extracted from a Revit model and identify completeness failures, dead legs, orphaned elements, cross-connections, and missing components.

## DEAD LEG DETECTION (CRITICAL FOR HEALTHCARE)

A dead leg is a pipe segment connected on one end but terminating without reaching a fixture or device. In domestic water systems, dead legs create stagnant water zones.

ASHRAE Standard 188 requires water management plans that eliminate stagnation zones. Dead legs exceeding 6x the pipe diameter are considered stagnation risks.

In hospitals and healthcare facilities, stagnant water in domestic hot water systems creates ideal conditions for Legionella pneumophila colonization. Legionnaires' disease has a ~10% mortality rate.

**Any dead leg in a domestic water system in a healthcare facility is a CRITICAL PATIENT SAFETY finding.**

## SYSTEM COMPLETENESS RULES

Every MEP system must form a complete chain:
- Supply Air: AHU -> Main Duct -> Branch Ducts -> VAV/Terminal Units -> Supply Diffusers
- Domestic Water: Main -> Risers -> Branch Lines -> Fixtures
- Sanitary Waste: Fixtures -> Traps -> Waste Pipes -> Vents -> Stacks -> Building Drain
- Sprinkler: Riser -> Cross Mains -> Branch Lines -> Sprinkler Heads

## SEVERITY CLASSIFICATION

1. Critical - Patient Safety: Dead legs in domestic water, cross-contamination, stagnant water
2. Critical - Life Safety: Missing sprinkler coverage, missing fire alarm devices
3. Critical - Code Violation: Missing vents (IPC 901.2), missing traps
4. Major: Incomplete chains, orphaned elements, dead-end ducts
5. Minor: Model hygiene, unnamed systems

## FALSE POSITIVE MANAGEMENT

Do NOT flag: capped stubs, "FUTURE" provisions, standby/backup circuits, test ports, drain valves, pipe segments under 6 inches between fittings.

## OUTPUT FORMAT

Return ONLY a valid JSON object with a "findings" array. Each finding:
- system_id, system_name, finding_type (dead_leg/orphan/incomplete_chain/dead_end/cross_connection/missing_component)
- severity, description (2-3 sentences), affected_elements (list of element IDs)
- recommendation, code_reference (ASHRAE 188/IPC/NFPA/NEC or null)"""

CLASSIFY_ORPHANS_PROMPT = """You are an MEP systems expert classifying Revit elements NOT connected to any MEP system.

For each orphan: determine likely system, assess severity, recommend action.
- Sprinkler heads not in system -> Critical - Life Safety
- Plumbing fixtures not in domestic water -> Critical - Patient Safety (healthcare)
- HVAC terminals in patient rooms -> Major (infection control)
- All others -> Minor unless in patient care areas

Return ONLY a valid JSON object with a "classifications" array. Each:
- element_id, likely_system_type, confidence (0-100), reasoning, severity, action"""


def call_claude(system_prompt, user_content, max_tokens=8192):
    client = anthropic.Anthropic()
    print("  Calling Claude (this takes 10-30 seconds)...")
    start = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    elapsed = time.time() - start
    print("  Response received in {:.1f}s".format(elapsed))
    return response.content[0].text


def parse_json_response(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        if "```" in text:
            json_str = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)
        raise


def main():
    if len(sys.argv) < 2:
        # Try default locations
        candidates = [
            "orphanx_extraction.json",
            "../test-models/orphanx_extraction.json",
            "../logs-nacho/orphanx_extraction.json",
        ]
        extraction_path = None
        for c in candidates:
            if os.path.exists(c):
                extraction_path = c
                break
        if not extraction_path:
            print("Usage: python3 plan_b_local_test.py <extraction.json>")
            print("No extraction file found in default locations.")
            sys.exit(1)
    else:
        extraction_path = sys.argv[1]

    print("=" * 60)
    print("ORPHAN X — Plan B Local Test (Direct Claude API)")
    print("=" * 60)
    print()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print("Loading extraction data from: {}".format(extraction_path))
    with open(extraction_path) as f:
        data = json.load(f)

    systems = data.get("systems", [])
    orphans = data.get("orphans", [])
    meta = data.get("_meta", {})

    print("  Systems: {} (showing {})".format(
        meta.get("total_systems", len(systems)), len(systems)))
    print("  Elements: {}".format(
        sum(len(s.get("elements", [])) for s in systems)))
    print("  Orphans: {} (showing {})".format(
        meta.get("total_orphans", len(orphans)), len(orphans)))
    print()

    # --- Audit Systems ---
    print("PHASE 1: Auditing systems for dead legs and safety issues...")
    systems_with_elements = [s for s in systems if s.get("elements")]
    if systems_with_elements:
        systems_payload = json.dumps({
            "building_type": data.get("building_type", "hospital"),
            "systems": systems_with_elements
        })
        user_msg = "Analyze the following MEP systems data for completeness and safety issues.\nReturn ONLY a valid JSON object with a \"findings\" array.\n\nMEP Systems Data:\n" + systems_payload

        try:
            result_text = call_claude(AUDIT_SYSTEM_PROMPT, user_msg)
            audit_result = parse_json_response(result_text)
            findings = audit_result.get("findings", [])
            print("  Found {} audit findings".format(len(findings)))
            for f in findings:
                sev = f.get("severity", "Unknown")
                ftype = f.get("finding_type", "unknown")
                desc = f.get("description", "")[:100]
                print("    [{}] {}: {}".format(sev, ftype, desc))
        except Exception as ex:
            print("  ERROR: {}".format(ex))
            findings = []
            audit_result = {"error": str(ex)}
    else:
        print("  No systems with elements — skipping audit")
        print("  (This is the bug — extraction has 0 elements per system)")
        findings = []
        audit_result = {"findings": [], "note": "no elements in systems"}

    print()

    # --- Classify Orphans ---
    print("PHASE 2: Classifying orphaned elements...")
    if orphans:
        orphans_payload = json.dumps({
            "building_type": data.get("building_type", "hospital"),
            "orphans": orphans
        })
        user_msg = "Classify the following orphaned MEP elements.\nReturn ONLY a valid JSON object with a \"classifications\" array.\n\nOrphaned Elements:\n" + orphans_payload

        try:
            result_text = call_claude(CLASSIFY_ORPHANS_PROMPT, user_msg)
            orphan_result = parse_json_response(result_text)
            classifications = orphan_result.get("classifications", [])
            print("  Classified {} orphans".format(len(classifications)))
            for c in classifications[:10]:
                sev = c.get("severity", "Unknown")
                sys_type = c.get("likely_system_type", "unknown")
                print("    [{}] Element {} -> {}".format(
                    sev, c.get("element_id", "?"), sys_type))
            if len(classifications) > 10:
                print("    ... and {} more".format(len(classifications) - 10))
        except Exception as ex:
            print("  ERROR: {}".format(ex))
            classifications = []
            orphan_result = {"error": str(ex)}
    else:
        print("  No orphans to classify")
        classifications = []
        orphan_result = {"classifications": []}

    print()

    # --- Summary ---
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("  Systems analyzed: {}".format(len(systems_with_elements) if systems_with_elements else 0))
    print("  Audit findings: {}".format(len(findings)))
    print("  Orphan classifications: {}".format(len(classifications)))

    severity_counts = {}
    for f in findings:
        sev = f.get("severity", "Unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    for c in classifications:
        sev = c.get("severity", "Unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    if severity_counts:
        print()
        print("  SEVERITY BREAKDOWN:")
        for sev in ["Critical - Patient Safety", "Critical - Life Safety",
                     "Critical - Code Violation", "Major", "Minor"]:
            if sev in severity_counts:
                print("    {}: {}".format(sev, severity_counts[sev]))

    # Save results
    output_path = extraction_path.replace("extraction", "planb_results")
    if output_path == extraction_path:
        output_path = "orphanx_planb_results.json"
    try:
        with open(output_path, "w") as f:
            json.dump({
                "audit_findings": findings,
                "orphan_classifications": classifications,
                "summary": {
                    "systems_analyzed": len(systems_with_elements) if systems_with_elements else 0,
                    "findings_count": len(findings),
                    "classifications_count": len(classifications),
                    "severity_breakdown": severity_counts,
                }
            }, f, indent=2)
        print()
        print("  Results saved to: {}".format(output_path))
    except Exception as ex:
        print("  Could not save results: {}".format(ex))

    print("=" * 60)


if __name__ == "__main__":
    main()
