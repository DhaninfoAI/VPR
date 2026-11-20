"""Apply "patch" research files (seed/research/35_resolve_*.json) on top of the current rules and save the result.

Each patch entry: {"key", "level", "state", "name", "display_name", "patch": {<fields to overwrite>}}.
Also settles county rules whose only open point was "applies inside cities" when the county requires nothing.

Output: seed/research/36_resolved.json (full entries, so a later import_research run keeps these answers)
and new "seed" rule rows for the changed jurisdictions.
Run from vpr-tool/:  backend\\.venv\\Scripts\\python seed\\apply_patches.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.geocode import jur_key  # noqa: E402
from app.models import Jurisdiction, VprRule  # noqa: E402
from import_research import SEED_MODEL, complete  # noqa: E402

OUT = ROOT / "research" / "36_resolved.json"


def latest_rules(s) -> dict[str, tuple[Jurisdiction, dict]]:
    jurs = {j.id: j for j in s.scalars(select(Jurisdiction))}
    out = {}
    for r in s.scalars(select(VprRule).where(VprRule.status != "error").order_by(VprRule.researched_at.asc())):
        if r.data and r.jurisdiction_id in jurs:  # ascending -> newest rule per jurisdiction wins
            j = jurs[r.jurisdiction_id]
            out[j.key] = (j, dict(r.data))
    return out


def main() -> None:
    patches = {}
    for f in sorted((ROOT / "research").glob("35_resolve_*.json")):
        for e in json.loads(f.read_text(encoding="utf-8")):
            patches[e["key"]] = e
    print("patches:", len(patches))

    with session_scope() as s:
        current = latest_rules(s)
    merged: dict[str, dict] = {}

    for key, e in patches.items():
        if key not in current:
            print("  skip (no such jurisdiction):", key)
            continue
        j, data = current[key]
        data.update({k: v for k, v in e["patch"].items() if v is not None or k == "requirement_conditions"})
        merged[key] = {"level": j.level, "state": j.state_code, "name": j.name, "display_name": j.display_name, "data": data}

    scope_fixes = 0
    for key, (j, data) in current.items():
        if key in merged:
            continue
        if j.level == "county" and data.get("applies_in_incorporated_areas") == "Unclear" and \
                "Yes" not in (data.get("vacant_registration_required"), data.get("foreclosure_registration_required")) and \
                "Unclear" not in (data.get("vacant_registration_required"), data.get("foreclosure_registration_required")):
            data["applies_in_incorporated_areas"] = "No"
            merged[key] = {"level": j.level, "state": j.state_code, "name": j.name, "display_name": j.display_name, "data": data}
            scope_fixes += 1
    print("scope-only fixes:", scope_fixes)

    entries = []
    for key, e in merged.items():
        if e["level"] != "county":
            e["data"]["applies_in_incorporated_areas"] = "Not applicable"
        if jur_key(e["level"], e["state"], e["name"]) != key:
            print("  key mismatch, skipped:", key)
            continue
        e["data"] = complete(e["data"])
        entries.append(e)
    OUT.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")

    with session_scope() as s:
        ids = {j.key: j.id for j in s.scalars(select(Jurisdiction).where(Jurisdiction.key.in_([jur_key(e["level"], e["state"], e["name"]) for e in entries])))}
        for e in entries:
            d = e["data"]
            s.add(VprRule(jurisdiction_id=ids[jur_key(e["level"], e["state"], e["name"])], status="seed", model=SEED_MODEL,
                          vacant_required=d["vacant_registration_required"], foreclosure_required=d["foreclosure_registration_required"],
                          ordinance_url=d["ordinance_url"], form_url=d["registration_form_url"], registration_fee=d["registration_fee"],
                          data=d, sources=[{"url": u, "title": None} for u in d["source_urls"]], link_checks={}))
    print("saved", len(entries), "rules ->", OUT.name)


if __name__ == "__main__":
    main()
