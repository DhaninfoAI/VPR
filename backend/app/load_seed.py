"""Load a VPR seed file (exported with `python -m app.load_seed --export`) into the database.

Usage
  Load (inside the container, file piped in):
      docker compose exec -T vpr python -m app.load_seed - < vpr_seed.json
  Load (local):
      python -m app.load_seed path/to/vpr_seed.json
  Export everything currently in the database:
      python -m app.load_seed --export path/to/vpr_seed.json

File format: a JSON list of
  {"key": "city|IL|aurora", "level": "city", "state": "IL", "name": "Aurora", "display_name": "City of Aurora",
   "data": {<rule fields>}, "researched_at": "2026-11-20T..."}

Loading is safe to repeat: a jurisdiction is created when missing, and a rule row is added only when its data
differs from the jurisdiction's newest rule. Rows are saved with status "seed", so they never expire.
"""

import json
import sys

from sqlalchemy import select

from .db import init_db, session_scope
from .geocode import jur_key
from .models import Jurisdiction, VprRule

SEED_MODEL = "seed file"
VALID = {"Yes", "No", "Unclear"}


def export(path: str) -> None:
    with session_scope() as s:
        jurs = {j.id: j for j in s.scalars(select(Jurisdiction))}
        latest: dict[int, VprRule] = {}
        for r in s.scalars(select(VprRule).where(VprRule.status != "error").order_by(VprRule.researched_at.asc())):
            if r.data:
                latest[r.jurisdiction_id] = r  # ascending -> newest wins
        out = [{"key": jurs[i].key, "level": jurs[i].level, "state": jurs[i].state_code, "name": jurs[i].name,
                "display_name": jurs[i].display_name, "data": r.data, "researched_at": r.researched_at.isoformat()}
               for i, r in latest.items() if i in jurs]
    out.sort(key=lambda e: (e["state"], {"state": 0, "county": 1, "city": 2}[e["level"]], e["name"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"exported {len(out)} jurisdictions -> {path}")


def load(entries: list[dict]) -> None:
    init_db()
    added = unchanged = created = 0
    with session_scope() as s:
        by_key = {j.key: j for j in s.scalars(select(Jurisdiction))}
        newest: dict[int, dict] = {}
        for r in s.scalars(select(VprRule).where(VprRule.status != "error").order_by(VprRule.researched_at.asc())):
            newest[r.jurisdiction_id] = r.data
        for e in entries:
            d = e["data"]
            for f in ("vacant_registration_required", "foreclosure_registration_required"):
                if d.get(f) not in VALID:
                    raise ValueError(f"{e.get('key')}: {f} must be Yes/No")
            key = e.get("key") or jur_key(e["level"], e["state"], e.get("name"))
            jur = by_key.get(key)
            if jur is None:
                jur = Jurisdiction(key=key, level=e["level"], state_code=e["state"].upper(), name=e["name"],
                                   display_name=e.get("display_name") or e["name"])
                s.add(jur)
                s.flush()
                by_key[key] = jur
                created += 1
            if newest.get(jur.id) == d:
                unchanged += 1
                continue
            # researched_at defaults to now, so the loaded rule becomes the jurisdiction's current rule.
            s.add(VprRule(jurisdiction_id=jur.id, status="seed", model=SEED_MODEL,
                          vacant_required=d.get("vacant_registration_required"),
                          foreclosure_required=d.get("foreclosure_registration_required"),
                          ordinance_url=d.get("ordinance_url"), form_url=d.get("registration_form_url"),
                          registration_fee=d.get("registration_fee"), data=d,
                          sources=[{"url": u, "title": None} for u in d.get("source_urls") or []], link_checks={}))
            newest[jur.id] = d
            added += 1
    print(f"jurisdictions created: {created} | rules added: {added} | already up to date: {unchanged}")


def main(argv: list[str]) -> None:
    if len(argv) == 2 and argv[0] == "--export":
        return export(argv[1])
    if len(argv) != 1:
        sys.exit(__doc__)
    # Always UTF-8 (the console code page on Windows would garble curly quotes and dashes).
    raw = (sys.stdin.buffer.read() if argv[0] == "-" else open(argv[0], "rb").read()).decode("utf-8-sig")
    load(json.loads(raw))


if __name__ == "__main__":
    main(sys.argv[1:])
