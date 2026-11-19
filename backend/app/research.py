"""Research one jurisdiction's VPR rules with OpenAI web search + structured output."""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from openai import OpenAI

from .config import get_settings

log = logging.getLogger(__name__)

YES_NO = {"type": "string", "enum": ["Yes", "No", "Unclear"]}
NULLABLE_STR = {"type": ["string", "null"]}

RULE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "jurisdiction_name": {"type": "string"},
        "vacant_registration_required": YES_NO,
        "foreclosure_registration_required": YES_NO,
        "applies_in_incorporated_areas": {
            "type": "string",
            "enum": ["Yes", "No", "Unclear", "Not applicable"],
            "description": "Counties only: does the county rule also apply inside incorporated cities/towns?",
        },
        "registration_trigger": {
            **NULLABLE_STR,
            "description": "When registration becomes required (e.g. vacant 30+ days, notice of default filed, foreclosure sale).",
        },
        "who_must_register": NULLABLE_STR,
        "registration_deadline": NULLABLE_STR,
        "ordinance_name": {**NULLABLE_STR, "description": "Ordinance/statute title and section number."},
        "ordinance_url": NULLABLE_STR,
        "registration_form_url": NULLABLE_STR,
        "registration_portal_url": NULLABLE_STR,
        "registration_method": {
            "type": "string",
            "enum": ["Online portal", "Third-party platform", "Mail", "Email", "In person", "Multiple", "Not applicable", "Unknown"],
        },
        "third_party_platform": {**NULLABLE_STR, "description": "e.g. ProChamps, Federal Property Registration Corp, HERA."},
        "registration_fee": NULLABLE_STR,
        "renewal_fee": NULLABLE_STR,
        "renewal_frequency": NULLABLE_STR,
        "additional_links": {
            "type": "array",
            "description": "Other useful forms, fee schedules or guidance documents (one URL each).",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                "required": ["label", "url"],
            },
        },
        "documents_required": {"type": "array", "items": {"type": "string"}},
        "other_requirements": {"type": "array", "items": {"type": "string"}},
        "penalties": NULLABLE_STR,
        "contact_info": NULLABLE_STR,
        "summary": {"type": "string"},
        "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "confidence_reason": {"type": "string"},
        "source_urls": {"type": "array", "items": {"type": "string"}},
    },
}
RULE_SCHEMA["required"] = list(RULE_SCHEMA["properties"].keys())

INSTRUCTIONS = """You are a compliance researcher for a US mortgage field-services / property-preservation company.
For ONE government jurisdiction, determine whether it requires residential property registration of the kind servicers file:
  * Vacant property registration (VPR) - registering vacant/abandoned buildings, and
  * Foreclosure / default / abandoned-and-foreclosed property registration - registering properties in default or foreclosure.
Then collect everything an operator needs to actually complete the registration.

How to research:
- Search the web. Prefer primary sources: the jurisdiction's code of ordinances (Municode, eCode360/General Code, American Legal, Code Publishing, etc.), official .gov pages, state statutes. Third-party registry sites (ProChamps, Federal Property Registration Corp, HERA and similar) are acceptable for process, fee and form details.
- Only report rules enacted by THIS jurisdiction: the state legislature/agencies for a state, the county board for a county, the municipal council for a city/town. Never attribute a city ordinance to its county or vice versa.
- A state statute that merely authorises municipalities to adopt registration ordinances is NOT a state-level requirement; mention it in the summary instead.
- ordinance_url, registration_form_url and registration_portal_url must each contain exactly ONE URL. Put any other forms (e.g. a second registration form), fee schedules or guidance documents in additional_links.
- Never invent or guess URLs. Only output URLs you actually saw in search results. Use null when you could not find one.
- Look for the registration form/portal and the current fee schedule (fees are often in a separate fee resolution or on the registry site).
- If you searched the code and found no registration requirement, answer "No" and set ordinance_url to the jurisdiction's code of ordinances (or statutes) page so the operator can verify.
- Use "Unclear" when sources conflict or you cannot reach the code; explain why in confidence_reason.

Field guidance:
- registration_fee / renewal_fee: exact amounts and what they cover, e.g. "$250 per property (initial)". Mention late fees separately in penalties.
- documents_required: the FULL checklist of documents and information the registration requires, one item per entry, specific and taken from the ordinance or form (e.g. "Completed registration form", "Proof of liability insurance - minimum $300,000", "Name/phone of local property manager within 20 miles available 24/7", "Mortgagee name, address and contact", "Date property became vacant", "Exterior photos", "Copy of notice of default"). If nothing is required, return an empty list.
- other_requirements: ongoing obligations after registering (inspection frequency, posting signage, securing/maintenance standards, notifying changes, deregistration).
- summary: 2-4 plain sentences an operator can paste into notes.
- source_urls: every URL you relied on.
"""


def _level_hint(level: str, state_name: str) -> str:
    if level == "state":
        return (f"This is the STATE level. Look for statewide statutes in {state_name} that themselves require "
                "registration of vacant or foreclosed residential properties (for example with a state agency or a "
                "statewide registry). applies_in_incorporated_areas: \"Not applicable\".")
    if level == "county":
        return ("This is the COUNTY level. Look only at the county's own code. County ordinances often apply only "
                "in unincorporated areas - set applies_in_incorporated_areas accordingly.")
    return ("This is the CITY/TOWN level. Look at the municipality's own code of ordinances. "
            "applies_in_incorporated_areas: \"Not applicable\".")


def research_jurisdiction(level: str, display_name: str, state_name: str, state_code: str) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in backend/.env")

    client = OpenAI(api_key=settings.openai_api_key, timeout=600)
    prompt = (
        f"Jurisdiction: {display_name}, {state_name} ({state_code}) - level: {level}.\n"
        f"{_level_hint(level, state_name)}\n"
        f"Today's date: {date.today().isoformat()}. Report the rules currently in force."
    )
    kwargs: dict = dict(
        model=settings.openai_model,
        instructions=INSTRUCTIONS,
        input=prompt,
        tools=[{"type": "web_search", "search_context_size": settings.openai_search_context}],
        include=["web_search_call.action.sources"],
        text={"format": {"type": "json_schema", "name": "vpr_rule", "schema": RULE_SCHEMA, "strict": True}},
    )
    if settings.openai_reasoning_effort:
        kwargs["reasoning"] = {"effort": settings.openai_reasoning_effort}
    if settings.openai_max_tool_calls:
        kwargs["max_tool_calls"] = settings.openai_max_tool_calls  # caps web searches -> faster, cheaper

    started = time.monotonic()
    response = client.responses.create(**kwargs)
    data = json.loads(response.output_text)
    usage = getattr(response, "usage", None)
    stats = {
        "seconds": round(time.monotonic() - started, 1),
        "web_searches": sum(1 for i in response.output or [] if getattr(i, "type", None) == "web_search_call"),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    log.info("Researched %s with %s: %s", display_name, response.model, stats)
    return {"data": data, "sources": _collect_sources(response), "model": response.model, "stats": stats}


def _collect_sources(response) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in response.output or []:
        if getattr(item, "type", None) == "web_search_call":
            action = getattr(item, "action", None)
            for src in getattr(action, "sources", None) or []:
                url = getattr(src, "url", None)
                if url and url not in seen:
                    seen[url] = {"url": url, "title": None}
        elif getattr(item, "type", None) == "message":
            for part in getattr(item, "content", None) or []:
                for ann in getattr(part, "annotations", None) or []:
                    if getattr(ann, "type", None) == "url_citation":
                        seen[ann.url] = {"url": ann.url, "title": getattr(ann, "title", None)}
    return list(seen.values())
