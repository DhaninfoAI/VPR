"""Load hand-researched jurisdiction rules from seed/research/*.json into the database.

Each file is a JSON list of entries:
  {"level": "state"|"county"|"city", "state": "CO", "name": "Aurora",
   "display_name": "City of Aurora", "data": {<fields of research.RULE_SCHEMA>}}

Rows are saved with status "seed" (never auto-expired; see service.get_or_research).
Re-running is safe: an entry is skipped when an identical seed rule already exists.

Run from vpr-tool/:  backend\\.venv\\Scripts\\python seed\\import_research.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app import linkcheck  # noqa: E402
from app.geocode import jur_key  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.models import Jurisdiction, VprRule  # noqa: E402
from app.research import RULE_SCHEMA  # noqa: E402
from app.service import URL_FIELDS, _normalize  # noqa: E402
from app.states import STATES  # noqa: E402

SEED_MODEL = "claude-opus-5-5 (manual research)"
LIST_FIELDS = {"documents_required", "other_requirements", "source_urls", "additional_links"}


def key_for(e: dict) -> str:
    return jur_key(e["level"], e["state"], e.get("name"))


def complete(data: dict) -> dict:
    out = {}
    for f in RULE_SCHEMA["properties"]:
        out[f] = data.get(f, [] if f in LIST_FIELDS else None)
    out["applies_in_incorporated_areas"] = out["applies_in_incorporated_areas"] or "Not applicable"
    out["registration_method"] = out["registration_method"] or "Unknown"
    for f in ("vacant_registration_required", "foreclosure_registration_required"):
        if out[f] not in ("Yes", "No", "Unclear"):
            raise ValueError(f"{f} must be Yes/No/Unclear")
    return _normalize(out)


def main(check_links: bool = True) -> None:
    init_db()
    files = sorted((ROOT / "research").glob("*.json"))
    added = skipped = 0
    latest: dict[str, dict] = {}  # later files override earlier ones for the same jurisdiction
    for path in files:
        entries = json.loads(path.read_text(encoding="utf-8"))
        print(f"{path.name}: {len(entries)} entries")
        for e in entries:
            latest[key_for(e)] = e
    for path in [None]:
        for e in latest.values():
            st = e["state"].upper()
            assert st in STATES, f"{path.name}: bad state {st}"
            data = complete(e["data"])
            k = key_for(e)
            with session_scope() as s:
                jur = s.scalar(select(Jurisdiction).where(Jurisdiction.key == k))
                if jur is None:
                    name = STATES[st] if e["level"] == "state" else e["name"].strip()
                    jur = Jurisdiction(key=k, level=e["level"], state_code=st, name=name,
                                       display_name=e.get("display_name") or name)
                    s.add(jur)
                    s.flush()
                last = s.scalar(select(VprRule).where(VprRule.jurisdiction_id == jur.id, VprRule.status == "seed")
                                .order_by(VprRule.researched_at.desc()).limit(1))
                if last and last.data == data:
                    skipped += 1
                    continue
                urls = [data.get(f) for f in URL_FIELDS] + [l["url"] for l in data["additional_links"]]
                checks = linkcheck.check_urls(urls) if check_links else {}
                s.add(VprRule(
                    jurisdiction_id=jur.id, status="seed", model=SEED_MODEL,
                    vacant_required=data["vacant_registration_required"],
                    foreclosure_required=data["foreclosure_registration_required"],
                    ordinance_url=data["ordinance_url"], form_url=data["registration_form_url"],
                    registration_fee=data["registration_fee"], data=data,
                    sources=[{"url": u, "title": None} for u in data["source_urls"]], link_checks=checks,
                ))
                added += 1
    print(f"added {added}, unchanged {skipped}")


if __name__ == "__main__":
    main(check_links="--no-link-check" not in sys.argv)
