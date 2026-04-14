"""Test the Orphan X MCP server with mock hospital MEP data."""

import json
import requests
import sys

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8620"

MOCK_SYSTEMS = {
    "building_type": "hospital",
    "systems": [
        {
            "system_id": "SYS-001",
            "system_name": "Domestic Hot Water 1",
            "system_type": "DomesticHotWater",
            "discipline": "Plumbing",
            "elements": [
                {"element_id": "33100", "category": "Mechanical Equipment", "family": "Water Heater", "type": "Gas 100gal", "level": "Level B1", "connected_to": ["33101"], "parameters": {"Temperature": "140F"}},
                {"element_id": "33101", "category": "Pipe Segments", "family": "Copper", "type": "2 inch", "level": "Level B1", "connected_to": ["33100", "33102", "33110"], "parameters": {"System Type": "Domestic Hot Water", "Size": "2\""}},
                {"element_id": "33102", "category": "Pipe Segments", "family": "Copper", "type": "1.5 inch", "level": "Level 1", "connected_to": ["33101", "33103", "33104"], "parameters": {"System Type": "Domestic Hot Water", "Size": "1.5\""}},
                {"element_id": "33103", "category": "Pipe Segments", "family": "Copper", "type": "1 inch", "level": "Level 2", "connected_to": ["33102", "33105", "33106"], "parameters": {"System Type": "Domestic Hot Water", "Size": "1\""}},
                {"element_id": "33104", "category": "Plumbing Fixtures", "family": "Sink", "type": "Lavatory", "level": "Level 1", "connected_to": ["33102"], "parameters": {}},
                {"element_id": "33105", "category": "Plumbing Fixtures", "family": "Sink", "type": "Lavatory", "level": "Level 2", "connected_to": ["33103"], "parameters": {}},
                {"element_id": "33106", "category": "Plumbing Fixtures", "family": "Shower", "type": "Patient Shower", "level": "Level 2", "connected_to": ["33103"], "parameters": {}},
                # DEAD LEG - branch pipe that goes nowhere (Patient Safety hazard)
                {"element_id": "33201", "category": "Pipe Segments", "family": "Copper", "type": "3/4 inch", "level": "Level 3", "connected_to": ["33103"], "parameters": {"System Type": "Domestic Hot Water", "Size": "0.75\"", "Length": "12 ft"}},
                # Another DEAD LEG
                {"element_id": "33202", "category": "Pipe Segments", "family": "Copper", "type": "3/4 inch", "level": "Level 3", "connected_to": ["33103"], "parameters": {"System Type": "Domestic Hot Water", "Size": "0.75\"", "Length": "8 ft"}},
                # Riser to Level 3 that connects to nothing
                {"element_id": "33110", "category": "Pipe Segments", "family": "Copper", "type": "1 inch", "level": "Level 3", "connected_to": ["33101"], "parameters": {"System Type": "Domestic Hot Water", "Size": "1\"", "Length": "14 ft"}},
            ]
        },
        {
            "system_id": "SYS-002",
            "system_name": "Supply Air 1 - Level 2 Patient Wing",
            "system_type": "SupplyAir",
            "discipline": "Mechanical",
            "elements": [
                {"element_id": "44100", "category": "Mechanical Equipment", "family": "AHU", "type": "AHU-2", "level": "Level R", "connected_to": ["44101"], "parameters": {"Flow": "15000 CFM"}},
                {"element_id": "44101", "category": "Duct Segments", "family": "Rectangular Duct", "type": "24x12", "level": "Level 2", "connected_to": ["44100", "44102", "44103", "44110"], "parameters": {"Size": "24x12"}},
                {"element_id": "44102", "category": "Duct Segments", "family": "Rectangular Duct", "type": "12x10", "level": "Level 2", "connected_to": ["44101", "44104"], "parameters": {"Size": "12x10"}},
                {"element_id": "44103", "category": "Duct Segments", "family": "Rectangular Duct", "type": "12x10", "level": "Level 2", "connected_to": ["44101", "44105"], "parameters": {"Size": "12x10"}},
                {"element_id": "44104", "category": "Air Terminals", "family": "Supply Diffuser", "type": "24x24 4-Way", "level": "Level 2", "connected_to": ["44102"], "parameters": {"Flow": "350 CFM"}},
                {"element_id": "44105", "category": "Air Terminals", "family": "Supply Diffuser", "type": "24x24 4-Way", "level": "Level 2", "connected_to": ["44103"], "parameters": {"Flow": "350 CFM"}},
                # DEAD END - branch duct goes nowhere (no diffuser at end)
                {"element_id": "44110", "category": "Duct Segments", "family": "Rectangular Duct", "type": "10x8", "level": "Level 2", "connected_to": ["44101"], "parameters": {"Size": "10x8"}},
            ]
        },
        {
            "system_id": "SYS-003",
            "system_name": "Fire Sprinkler - Level 3",
            "system_type": "Sprinkler",
            "discipline": "FireProtection",
            "elements": [
                {"element_id": "55001", "category": "Pipe Segments", "family": "Steel Pipe", "type": "4 inch", "level": "Level 3", "connected_to": ["55002", "55003"], "parameters": {"System Type": "Fire Protection Wet", "Size": "4\""}},
                {"element_id": "55002", "category": "Pipe Segments", "family": "Steel Pipe", "type": "2 inch", "level": "Level 3", "connected_to": ["55001", "55010", "55011"], "parameters": {"System Type": "Fire Protection Wet", "Size": "2\""}},
                {"element_id": "55003", "category": "Pipe Segments", "family": "Steel Pipe", "type": "2 inch", "level": "Level 3", "connected_to": ["55001", "55012", "55013"], "parameters": {"System Type": "Fire Protection Wet", "Size": "2\""}},
                {"element_id": "55010", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": ["55002"], "parameters": {}},
                {"element_id": "55011", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": ["55002"], "parameters": {}},
                # These sprinkler heads have NO branch line - disconnected
                {"element_id": "55020", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": [], "parameters": {}},
                {"element_id": "55021", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": [], "parameters": {}},
                {"element_id": "55022", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": [], "parameters": {}},
                {"element_id": "55023", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": [], "parameters": {}},
                {"element_id": "55012", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": ["55003"], "parameters": {}},
                {"element_id": "55013", "category": "Sprinklers", "family": "Pendant Sprinkler", "type": "Standard Response", "level": "Level 3", "connected_to": ["55003"], "parameters": {}},
            ]
        },
        {
            "system_id": "SYS-004",
            "system_name": "Electrical Panel LP-3A",
            "system_type": "PowerCircuit",
            "discipline": "Electrical",
            "elements": [
                {"element_id": "66001", "category": "Electrical Equipment", "family": "Panelboard", "type": "225A MLO", "level": "Level 3", "connected_to": ["66002", "66003", "66004", "66010"], "parameters": {"Voltage": "208/120V", "Panel Name": "LP-3A"}},
                {"element_id": "66002", "category": "Electrical Fixtures", "family": "Receptacle", "type": "Duplex", "level": "Level 3", "connected_to": ["66001"], "parameters": {"Circuit": "1"}},
                {"element_id": "66003", "category": "Electrical Fixtures", "family": "Receptacle", "type": "Duplex", "level": "Level 3", "connected_to": ["66001"], "parameters": {"Circuit": "3"}},
                {"element_id": "66004", "category": "Electrical Fixtures", "family": "Receptacle", "type": "Hospital Grade", "level": "Level 3", "connected_to": ["66001"], "parameters": {"Circuit": "5"}},
                # Empty circuit - connected to panel but no device
                {"element_id": "66010", "category": "Electrical Circuits", "family": "Circuit", "type": "20A 1P", "level": "Level 3", "connected_to": ["66001"], "parameters": {"Circuit Number": "7", "Load Name": "", "Connected Load": "0 VA"}},
            ]
        },
        {
            "system_id": "SYS-005",
            "system_name": "Sanitary Waste - Level 2",
            "system_type": "SanitaryWaste",
            "discipline": "Plumbing",
            "elements": [
                {"element_id": "77001", "category": "Plumbing Fixtures", "family": "Water Closet", "type": "Floor Mount", "level": "Level 2", "connected_to": ["77002"], "parameters": {}},
                {"element_id": "77002", "category": "Pipe Segments", "family": "Cast Iron", "type": "4 inch", "level": "Level 2", "connected_to": ["77001", "77003", "77010"], "parameters": {"System Type": "Sanitary"}},
                {"element_id": "77003", "category": "Plumbing Fixtures", "family": "Lavatory", "type": "Wall Mount", "level": "Level 2", "connected_to": ["77002"], "parameters": {}},
                {"element_id": "77010", "category": "Pipe Segments", "family": "Cast Iron", "type": "4 inch", "level": "Level 2", "connected_to": ["77002", "77011"], "parameters": {"System Type": "Sanitary"}},
                {"element_id": "77011", "category": "Pipe Segments", "family": "Cast Iron", "type": "4 inch", "level": "Level 2", "connected_to": ["77010"], "parameters": {"System Type": "Sanitary"}},
                # NO VENT on this group - IPC code violation
            ]
        }
    ]
}

MOCK_ORPHANS = {
    "building_type": "hospital",
    "orphans": [
        {"element_id": "88001", "category": "Air Terminals", "family": "Supply Diffuser", "type": "24x24 4-Way", "level": "Level 2", "nearest_elements": [{"element_id": "44102", "system_name": "Supply Air 1", "distance_ft": 6}]},
        {"element_id": "88002", "category": "Air Terminals", "family": "Supply Diffuser", "type": "24x24 4-Way", "level": "Level 2", "nearest_elements": [{"element_id": "44103", "system_name": "Supply Air 1", "distance_ft": 8}]},
        {"element_id": "88003", "category": "Air Terminals", "family": "Return Air Grille", "type": "20x20", "level": "Level 3", "nearest_elements": [{"element_id": "44110", "system_name": "Supply Air 1", "distance_ft": 12}]},
        {"element_id": "88010", "category": "Lighting Fixtures", "family": "Troffer", "type": "2x4 LED", "level": "Level 3", "nearest_elements": [{"element_id": "66001", "system_name": "Panel LP-3A", "distance_ft": 20}]},
    ]
}


def test_health():
    print("Testing /health...")
    r = requests.get(f"{BASE_URL}/health")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    print()


def test_audit():
    print("=" * 60)
    print("Testing audit_systems with mock hospital data...")
    print(f"  Sending {len(MOCK_SYSTEMS['systems'])} systems")
    print("=" * 60)

    # For direct HTTP testing (not MCP protocol)
    # The MCP server exposes tools via SSE, but for testing we can call Claude directly
    import anthropic
    import os
    from dotenv import load_dotenv

    load_dotenv()

    from prompts import AUDIT_SYSTEM_PROMPT

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=AUDIT_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Analyze the following MEP systems data for completeness and safety issues.\nReturn ONLY a valid JSON object with a \"findings\" array. No markdown, no explanation outside the JSON.\n\nMEP Systems Data:\n{json.dumps(MOCK_SYSTEMS, indent=2)}"
        }],
    )

    result = response.content[0].text
    print("\nAudit Results:")
    try:
        parsed = json.loads(result)
        print(json.dumps(parsed, indent=2))
        findings = parsed.get("findings", [])
        print(f"\n  Total findings: {len(findings)}")
        for f in findings:
            print(f"  [{f.get('severity', '?')}] {f.get('finding_type', '?')}: {f.get('description', '')[:100]}...")
    except json.JSONDecodeError:
        print(result[:2000])
    print()
    return result


def test_orphans():
    print("=" * 60)
    print("Testing classify_orphans with mock data...")
    print(f"  Sending {len(MOCK_ORPHANS['orphans'])} orphaned elements")
    print("=" * 60)

    import anthropic
    from dotenv import load_dotenv
    load_dotenv()

    from prompts import CLASSIFY_ORPHANS_PROMPT

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=CLASSIFY_ORPHANS_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Classify the following orphaned MEP elements.\nReturn ONLY a valid JSON object with a \"classifications\" array. No markdown, no explanation outside the JSON.\n\nOrphaned Elements:\n{json.dumps(MOCK_ORPHANS, indent=2)}"
        }],
    )

    result = response.content[0].text
    print("\nOrphan Classifications:")
    try:
        parsed = json.loads(result)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print(result[:2000])
    print()
    return result


if __name__ == "__main__":
    if "--health" in sys.argv:
        test_health()
    elif "--orphans" in sys.argv:
        test_orphans()
    elif "--audit" in sys.argv:
        test_audit()
    else:
        test_health()
        audit_result = test_audit()
        orphan_result = test_orphans()
        print("All tests complete.")
