"""Pull every state / county / city that appears in the reference workbook (skips the Logins sheet).
Writes jurisdictions.json with the operators' answers kept only as research hints."""
import json, re, sys, collections
from pathlib import Path
import openpyxl

SRC = Path(sys.argv[1])
SHEETS = {  # sheet -> (state, city, county, city_wise, state_wise, county_wise, ordinance) header names
    "AK-AL-AR-AZ ": ("State", "City", "County", "City Wise", "State Wise", "County Wise", "Ordinance"),
    "CO-CT-DC-DE": ("State", "City", "County", "City Wise", "State Wise", "County Wise", "Ordinance"),
    "CA - California": ("State", "City", "County", "City Wise", "State Wise", "County Wise", "Ordinance"),
    "Audit Population One Time": ("State", "City", "County", None, None, None, None),
    "Prajwal": ("State", "City", "County", "City Wise", "State Wise", None, None),
}

def clean(v):
    if v is None: return ""
    return re.sub(r"\s+", " ", str(v)).strip()

wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
cities = collections.defaultdict(lambda: {"counties": collections.Counter(), "hints": collections.Counter(), "links": collections.Counter(), "rows": 0})
counties = collections.defaultdict(lambda: {"hints": collections.Counter(), "rows": 0})
states = collections.defaultdict(lambda: {"hints": collections.Counter(), "rows": 0})
for name, cols in SHEETS.items():
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    header = [clean(h) for h in next(it)]
    idx = {c: (header.index(c) if c and c in header else None) for c in cols}
    g = lambda r, c: clean(r[idx[c]]) if c and idx.get(c) is not None and idx[c] < len(r) else ""
    st_c, ci_c, co_c, cw, sw, kw, od = cols
    for r in it:
        st = g(r, st_c).upper()
        if len(st) != 2:
            continue
        city = g(r, ci_c).title()
        county = re.sub(r"\s+(County|Parish)$", "", g(r, co_c).title())
        states[st]["rows"] += 1
        if sw and g(r, sw): states[st]["hints"][g(r, sw).title()] += 1
        if county:
            counties[(st, county)]["rows"] += 1
            if kw and g(r, kw): counties[(st, county)]["hints"][g(r, kw).title()] += 1
        if city:
            c = cities[(st, city)]
            c["rows"] += 1
            if county: c["counties"][county] += 1
            if cw and g(r, cw): c["hints"][g(r, cw).title()] += 1
            if od and g(r, od).startswith("http"): c["links"][g(r, od)] += 1

out = {
    "states": [{"state": s, "rows": v["rows"], "operator_hint": dict(v["hints"])} for s, v in sorted(states.items())],
    "counties": [{"state": s, "county": c, "rows": v["rows"], "operator_hint": dict(v["hints"])} for (s, c), v in sorted(counties.items())],
    "cities": [{"state": s, "city": c, "rows": v["rows"], "counties": [k for k, _ in v["counties"].most_common(3)],
                "operator_hint": dict(v["hints"]), "operator_links": [k for k, _ in v["links"].most_common(3)]}
               for (s, c), v in sorted(cities.items())],
}
Path("jurisdictions.json").write_text(json.dumps(out, indent=1))
print("states", len(out["states"]), "counties", len(out["counties"]), "cities", len(out["cities"]))
print(collections.Counter(c["state"] for c in out["cities"]))
print(collections.Counter(c["state"] for c in out["counties"]))
