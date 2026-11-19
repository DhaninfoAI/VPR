"""Fill in link checks for seed rules that were imported with --no-link-check."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import linkcheck
from app.db import session_scope
from app.models import VprRule
from app.service import URL_FIELDS

with session_scope() as s:
    rows = s.query(VprRule).filter(VprRule.status == "seed").all()
    todo = [r for r in rows if not r.link_checks]
    print(len(todo), "rules to check")
    for i, r in enumerate(todo, 1):
        d = r.data or {}
        urls = [d.get(f) for f in URL_FIELDS] + [l["url"] for l in d.get("additional_links") or []]
        r.link_checks = linkcheck.check_urls(urls) or {}
        if i % 25 == 0:
            s.flush(); print(i)
print("done")
