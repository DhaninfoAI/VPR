"""Helpers for writing hand-researched seed entries."""
import json
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent / "research"

BLANK = {
    "applies_in_incorporated_areas": "Not applicable", "registration_trigger": None, "who_must_register": None,
    "registration_deadline": None, "ordinance_name": None, "ordinance_url": None, "registration_form_url": None,
    "registration_portal_url": None, "registration_method": "Unknown", "third_party_platform": None,
    "registration_fee": None, "renewal_fee": None, "renewal_frequency": None, "additional_links": [],
    "documents_required": [], "other_requirements": [], "penalties": None, "contact_info": None,
    "summary": "", "confidence": "Medium", "confidence_reason": "", "source_urls": [],
}


def rule(level: str, state: str, name: str, display: str, vacant: str, foreclosure: str, **fields) -> dict:
    data = {**BLANK, "jurisdiction_name": display, "vacant_registration_required": vacant,
            "foreclosure_registration_required": foreclosure, **fields}
    if level == "county" and "applies_in_incorporated_areas" not in fields:
        data["applies_in_incorporated_areas"] = "Unclear"
    if vacant == "No" and foreclosure == "No" and "registration_method" not in fields:
        data["registration_method"] = "Not applicable"
    return {"level": level, "state": state, "name": name, "display_name": display, "data": data}


def save(filename: str, entries: list[dict]) -> None:
    RESEARCH_DIR.mkdir(exist_ok=True)
    (RESEARCH_DIR / filename).write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(filename, len(entries), "entries")
