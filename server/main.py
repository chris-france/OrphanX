"""Orphan X — MEP Systems Auditor MCP Server.

Exposes three tools via MCP (SSE transport) for Dynamo agentic nodes:
  - audit_systems: Analyze MEP systems for completeness and safety issues
  - classify_orphans: Classify elements not in any system
  - generate_report: Produce a formatted QA/QC report
"""

import json
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
import anthropic

from prompts import AUDIT_SYSTEM_PROMPT, CLASSIFY_ORPHANS_PROMPT, REPORT_PROMPT

load_dotenv()

mcp = FastMCP(
    "orphan-x",
    instructions="MEP Systems Auditor — analyzes Revit MEP models for orphaned elements, dead legs, incomplete systems, and patient safety hazards.",
    host="0.0.0.0",
    port=8620,
)

claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"


def _call_claude(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
    response = claude.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


@mcp.tool()
def audit_systems(systems_json: str) -> str:
    """Analyze MEP systems extracted from a Revit model for completeness, dead legs, orphaned connections, and safety issues.

    Args:
        systems_json: JSON string containing MEP system data. Expected format:
            {
                "building_type": "hospital" | "commercial" | "residential" | "laboratory",
                "systems": [
                    {
                        "system_id": "string",
                        "system_name": "string",
                        "system_type": "SupplyAir" | "ReturnAir" | "Exhaust" | "DomesticHotWater" | "DomesticColdWater" | "SanitaryWaste" | "Storm" | "Hydronic" | "Sprinkler" | "PowerCircuit" | "LightingCircuit" | "FireAlarm" | "Other",
                        "discipline": "Mechanical" | "Electrical" | "Plumbing" | "FireProtection",
                        "elements": [
                            {
                                "element_id": "string",
                                "category": "string (Revit category)",
                                "family": "string",
                                "type": "string",
                                "level": "string",
                                "connected_to": ["element_id", ...],
                                "parameters": {"key": "value", ...}
                            }
                        ]
                    }
                ]
            }

    Returns:
        JSON string with findings array.
    """
    user_msg = f"""Analyze the following MEP systems data for completeness and safety issues.
Return ONLY a valid JSON object with a "findings" array. No markdown, no explanation outside the JSON.

MEP Systems Data:
{systems_json}"""

    result = _call_claude(AUDIT_SYSTEM_PROMPT, user_msg, max_tokens=8192)

    # Try to parse to validate it's JSON, but return as string either way
    try:
        parsed = json.loads(result)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0].strip()
            try:
                parsed = json.loads(json_str)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        if "```" in result:
            json_str = result.split("```")[1].split("```")[0].strip()
            try:
                parsed = json.loads(json_str)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        return json.dumps({"raw_response": result, "parse_error": "Could not parse as JSON"})


@mcp.tool()
def classify_orphans(orphans_json: str) -> str:
    """Classify MEP elements that are not connected to any system.

    Args:
        orphans_json: JSON string containing orphaned elements. Expected format:
            {
                "building_type": "hospital" | "commercial" | "residential" | "laboratory",
                "orphans": [
                    {
                        "element_id": "string",
                        "category": "string (Revit category)",
                        "family": "string",
                        "type": "string",
                        "level": "string",
                        "nearest_elements": [
                            {"element_id": "string", "system_name": "string", "distance_ft": number}
                        ]
                    }
                ]
            }

    Returns:
        JSON string with classifications array.
    """
    user_msg = f"""Classify the following orphaned MEP elements. For each element, determine its likely intended system, severity, and recommended action.
Return ONLY a valid JSON object with a "classifications" array. No markdown, no explanation outside the JSON.

Orphaned Elements:
{orphans_json}"""

    result = _call_claude(CLASSIFY_ORPHANS_PROMPT, user_msg, max_tokens=4096)

    try:
        parsed = json.loads(result)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0].strip()
            try:
                parsed = json.loads(json_str)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        if "```" in result:
            json_str = result.split("```")[1].split("```")[0].strip()
            try:
                parsed = json.loads(json_str)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        return json.dumps({"raw_response": result, "parse_error": "Could not parse as JSON"})


@mcp.tool()
def generate_report(findings_json: str) -> str:
    """Generate a formatted QA/QC report from audit findings and orphan classifications.

    Args:
        findings_json: JSON string containing all findings. Expected format:
            {
                "model_name": "string",
                "building_type": "hospital" | "commercial" | ...,
                "audit_findings": [...],  (output from audit_systems)
                "orphan_classifications": [...],  (output from classify_orphans)
                "total_systems": number,
                "total_elements": number
            }

    Returns:
        Formatted plain-text QA/QC report.
    """
    user_msg = f"""Generate a professional MEP QA/QC audit report from the following findings.
Follow the report structure exactly. Write in plain English. Be direct and actionable.

Findings Data:
{findings_json}"""

    return _call_claude(REPORT_PROMPT, user_msg, max_tokens=8192)


if __name__ == "__main__":
    mcp.run(transport="sse")
