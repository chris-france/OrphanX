"""Quick smoke test for the audit_systems Claude call."""
import json, anthropic, os, sys
from dotenv import load_dotenv
load_dotenv()
from prompts import AUDIT_SYSTEM_PROMPT

test_data = {
    "building_type": "hospital",
    "systems": [{
        "system_id": "SYS-001",
        "system_name": "Domestic Hot Water 1",
        "system_type": "DomesticHotWater",
        "discipline": "Plumbing",
        "elements": [
            {"element_id": "33100", "category": "Mechanical Equipment", "family": "Water Heater", "type": "Gas 100gal", "level": "Level B1", "connected_to": ["33101"], "parameters": {"Temperature": "140F"}},
            {"element_id": "33101", "category": "Pipe Segments", "family": "Copper", "type": "2 inch", "level": "Level B1", "connected_to": ["33100", "33102"], "parameters": {"System Type": "Domestic Hot Water", "Size": "2 in"}},
            {"element_id": "33102", "category": "Pipe Segments", "family": "Copper", "type": "3/4 inch", "level": "Level 3", "connected_to": ["33101"], "parameters": {"System Type": "Domestic Hot Water", "Size": "0.75 in", "Length": "12 ft"}}
        ]
    }]
}

print("Calling Claude with dead leg test data...")
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=AUDIT_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": "Analyze the following MEP systems data for completeness and safety issues.\nReturn ONLY a valid JSON object with a findings array. No markdown.\n\nMEP Systems Data:\n" + json.dumps(test_data, indent=2)}],
)
result = response.content[0].text
try:
    parsed = json.loads(result)
    findings = parsed.get("findings", [])
    print("SUCCESS: %d findings returned" % len(findings))
    for f in findings:
        print("  [%s] %s: %s" % (f.get("severity", "?"), f.get("finding_type", "?"), f.get("description", "")[:100]))
    print("\nFull JSON:")
    print(json.dumps(parsed, indent=2)[:2000])
except json.JSONDecodeError:
    print("JSON parse failed. Raw: " + result[:500])
