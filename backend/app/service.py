"""Run an address lookup: geocode -> reuse or research each jurisdiction -> compose the sheet row."""

from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import geocode, linkcheck, research
from .config import get_settings
from .db import session_scope
from .models import Jurisdiction, Lookup, VprRule, utcnow
from .states import NO_COUNTY_GOVERNMENT

log = logging.getLogger(__name__)

LEVELS = ("city", "county", "state")
_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _key_locks_guard:
        return _key_locks.setdefault(key, threading.Lock())


def _set_progress(lookup_id: str, **fields) -> None:
    with session_scope() as s:
        lk = s.get(Lookup, lookup_id)
        for k, v in fields.items():
            setattr(lk, k, v)


# --------------------------------------------------------------------------- rules


def _upsert_jurisdiction(s, j: dict, state_code: str) -> Jurisdiction:
    row = s.scalar(select(Jurisdiction).where(Jurisdiction.key == j["key"]))
    if row is None:
        row = Jurisdiction(key=j["key"], level=j["level"], state_code=state_code, name=j["name"],
                           display_name=j["display_name"], geoid=j.get("geoid"))
        s.add(row)
        s.flush()
    return row


def _latest_rule(s, jurisdiction_id: int) -> VprRule | None:
    return s.scalar(
        select(VprRule)
        .where(VprRule.jurisdiction_id == jurisdiction_id, VprRule.status != "error")
        .order_by(VprRule.researched_at.desc())
        .limit(1)
    )


NON_EXPIRING = {"seed", "human_verified"}
URL_RE = re.compile(r"https?://[^\s;,|]+")
URL_FIELDS = {"ordinance_url": "Ordinance", "registration_form_url": "Registration form",
              "registration_portal_url": "Registration portal"}


def _normalize(d: dict | None) -> dict | None:
    """Make every *_url field a single URL; move any extra URLs into additional_links."""
    if not d:
        return d
    d = dict(d)
    extra = [l if isinstance(l, dict) else {"label": "Link", "url": str(l)} for l in (d.get("additional_links") or [])]
    for field, label in URL_FIELDS.items():
        urls = URL_RE.findall(d.get(field) or "")
        d[field] = urls[0] if urls else None
        extra += [{"label": f"{label} ({i})", "url": u} for i, u in enumerate(urls[1:], start=2)]
    seen, links = set(), []
    for link in extra:
        u = (URL_RE.findall(link.get("url") or "") or [None])[0]
        if u and u not in seen and u not in (d[f] for f in URL_FIELDS):
            seen.add(u)
            links.append({"label": link.get("label") or "Link", "url": u})
    d["additional_links"] = links
    return d


def _rule_dict(rule: VprRule, from_cache: bool) -> dict:
    return {
        "rule_id": rule.id,
        "status": rule.status,
        "researched_at": rule.researched_at.isoformat(),
        "model": rule.model,
        "data": _normalize(rule.data),
        "sources": rule.sources or [],
        "link_checks": rule.link_checks or {},
        "from_cache": from_cache,
        "error": rule.error,
    }


CODE_HOSTS = ("municode", "ecode360", "amlegal", "codepublishing", "municipal.codes", "generalcode", "gocodebook")


def _known_domains(jurisdiction_id: int) -> list[str]:
    """Sites already linked for this jurisdiction (e.g. the city's own .gov site) so filtered search can read them."""
    domains: list[str] = []
    with session_scope() as s:
        rules = s.scalars(select(VprRule).where(VprRule.jurisdiction_id == jurisdiction_id,
                                                 VprRule.status != "error")).all()
        for r in rules:
            d = r.data or {}
            urls = [d.get(f) for f in URL_FIELDS] + [l.get("url") for l in d.get("additional_links") or []]
            for u in urls:
                host = (URL_RE.findall(u or "") or [""])[0].split("/")[2:3]
                if host:
                    h = host[0].lower().removeprefix("www.")
                    if not any(c in h for c in CODE_HOSTS) and h not in domains:
                        domains.append(h)
    return domains[:10]


def get_or_research(j: dict, loc: dict, force: bool, on_state=lambda key, state: None) -> dict:
    """Return the current rule for a jurisdiction, researching it if missing or older than the TTL."""
    ttl = timedelta(days=get_settings().cache_ttl_days)
    with _lock_for(j["key"]):
        with session_scope() as s:
            jur = _upsert_jurisdiction(s, j, loc["state_code"])
            jur_id = jur.id
            rule = _latest_rule(s, jur_id)
            # "seed" = pre-built database rows and "human_verified" never expire; live AI results use the TTL.
            if rule and not force and (rule.status in NON_EXPIRING or utcnow() - rule.researched_at < ttl):
                on_state(j["key"], "cached")
                return _rule_dict(rule, from_cache=True)

        on_state(j["key"], "researching")
        try:
            out = research.research_jurisdiction(j["level"], j["display_name"], loc["state_name"], loc["state_code"],
                                                 extra_domains=_known_domains(jur_id))
            d = _normalize(out["data"])
            checks = linkcheck.check_urls([d.get(f) for f in URL_FIELDS]
                                          + [link["url"] for link in d["additional_links"]])
            new = VprRule(
                jurisdiction_id=jur_id, status="ai_researched", model=out["model"],
                vacant_required=d.get("vacant_registration_required"),
                foreclosure_required=d.get("foreclosure_registration_required"),
                ordinance_url=d.get("ordinance_url"), form_url=d.get("registration_form_url"),
                registration_fee=d.get("registration_fee"),
                data=d, sources=out["sources"], link_checks=checks,
            )
        except Exception as exc:  # keep the error visible, but never cache it as an answer
            log.exception("Research failed for %s", j["key"])
            new = VprRule(jurisdiction_id=jur_id, status="error", error=f"{type(exc).__name__}: {exc}")

        with session_scope() as s:
            s.add(new)
            s.flush()
            on_state(j["key"], "error" if new.status == "error" else "done")
            return _rule_dict(new, from_cache=False)


# --------------------------------------------------------------------------- applicability


def _base_flag(data: dict) -> str:
    vals = (data.get("vacant_registration_required"), data.get("foreclosure_registration_required"))
    if "Yes" in vals:
        return "Yes"
    if "Unclear" in vals:
        return "Unclear"
    return "No"


def _reg_type(data: dict) -> str:
    v = data.get("vacant_registration_required") == "Yes"
    f = data.get("foreclosure_registration_required") == "Yes"
    return {(True, True): "Vacant & Foreclosure", (True, False): "Vacant",
            (False, True): "Foreclosure", (False, False): "None"}[(v, f)]


def _level_entry(level: str, j: dict | None, rule: dict | None, loc: dict) -> dict:
    st = loc["state_code"]
    if j is None:
        if st == "DC":
            reason = "Washington, DC is an independent federal district; only the District level applies."
        elif level == "city":
            reason = f"The property is in an unincorporated area of {loc['county']['full_name']}; no city/town government applies."
        elif st in NO_COUNTY_GOVERNMENT:
            reason = f"{loc['state_name']} has no county government, so no county ordinance can apply."
        else:
            reason = "The property is in an independent city, which has no separate county government."
        return {"level": level, "jurisdiction": None, "flag": "No", "reason": reason, "rule": None}

    entry = {"level": level, "jurisdiction": j["display_name"], "rule": rule, "reason": None}
    if rule is None or rule["status"] == "error":
        entry["flag"] = "Error"
        entry["reason"] = (rule or {}).get("error") or "Research failed"
        return entry

    data = rule["data"]
    flag = _base_flag(data)
    in_municipality = bool(loc.get("municipality"))
    if level == "county" and flag != "No" and in_municipality:
        scope = data.get("applies_in_incorporated_areas")
        if scope == "No":
            flag = "No"
            entry["reason"] = (f"{j['display_name']} has a registration rule, but it applies only in unincorporated "
                               f"areas and this property is inside {loc['municipality']['label']} of "
                               f"{loc['municipality']['name']}.")
        elif scope == "Unclear":
            flag = "Unclear"
            entry["reason"] = "County rule exists; unclear whether it applies inside city limits."
    entry["flag"] = flag
    return entry


def _is_foreclosure_stop(entry: dict) -> bool:
    """A level that applies to the property and requires FORECLOSURE registration ends the review."""
    data = (entry.get("rule") or {}).get("data") or {}
    return entry.get("flag") == "Yes" and data.get("foreclosure_registration_required") == "Yes"


def _skipped_entry(level: str, j: dict, stop: dict) -> dict:
    return {"level": level, "jurisdiction": j["display_name"], "flag": "No", "rule": None, "skipped": True,
            "reason": (f"Not reviewed: foreclosure registration is required at the {stop['jurisdiction']} level, "
                       f"so further review was not done.")}


def _condition(data: dict) -> str | None:
    return data.get("requirement_conditions") or data.get("registration_trigger")


# --------------------------------------------------------------------------- output


def _join(required: list[dict], getter, multi_prefix=True) -> str:
    vals = []
    for e in required:
        v = getter(e["rule"]["data"])
        if not v:
            continue
        if isinstance(v, list):
            v = "\n".join(f"- {x}" for x in v)
        vals.append(f"{e['jurisdiction']}:\n{v}" if multi_prefix and len(required) > 1 else v)
    return "\n\n".join(vals) if vals else "N/A"


def _compose(lookup_input: dict, loc: dict, levels: dict[str, dict]) -> dict:
    ordered = [levels[l] for l in LEVELS]
    applicable = [e for e in ordered if e["jurisdiction"]]
    yes = [e for e in applicable if e["flag"] == "Yes"]
    unclear = [e for e in applicable if e["flag"] in ("Unclear", "Error")]
    no = [e for e in applicable if e["flag"] == "No"]
    primary = applicable[0] if applicable else None  # most local jurisdiction

    def names(es, conj="or"):
        ns = [e["jurisdiction"] for e in es]
        if len(ns) <= 1:
            return "".join(ns)
        return ", ".join(ns[:-1]) + f" {conj} " + ns[-1]

    stop = next((e for e in ordered if _is_foreclosure_stop(e)), None)
    skipped = [e for e in ordered if e.get("skipped")]

    lines: list[str] = []
    if stop:
        d = stop["rule"]["data"]
        s = f"Foreclosure registration is required at the {stop['jurisdiction']} level for the mentioned property"
        s += (f"; further VPR review was not done at the {names(skipped, 'and')} "
              f"level{'s' if len(skipped) > 1 else ''}.") if skipped else "."
        lines.append(s)
        lines.append(f"{stop['jurisdiction']} - registration type: {_reg_type(d)}.")
        if _condition(d):
            lines.append(f"{stop['jurisdiction']} - required when: {_condition(d)}")
        for e in yes:  # a more local level that required (vacant) registration before the stop
            if e is not stop:
                od = e["rule"]["data"]
                lines.append(f"VPR is also required at the {e['jurisdiction']} level - registration type: {_reg_type(od)}.")
                if _condition(od):
                    lines.append(f"{e['jurisdiction']} - required when: {_condition(od)}")
    elif yes:
        s = f"VPR is required at the {names(yes, 'and')} level{'s' if len(yes) > 1 else ''}"
        s += f" but is not required at the {names(no)} level" if no else ""
        lines.append(s + " for the mentioned property.")
        for e in yes:
            d = e["rule"]["data"]
            lines.append(f"{e['jurisdiction']} - registration type: {_reg_type(d)}.")
            if _condition(d):
                lines.append(f"{e['jurisdiction']} - required when: {_condition(d)}")
    elif not unclear:
        lines.append(f"VPR is not required at the {names(no)} level for the mentioned property.")
    for e in ([] if stop else unclear):
        lines.append(f"VPR requirement at the {e['jurisdiction']} level could not be confirmed - manual verification needed.")
    for e in ordered:  # explain why a level does not apply (unincorporated, no county govt, city-only rule...)
        if e["reason"] and e["flag"] == "No" and not e.get("skipped"):
            lines.append(e["reason"])
    lines = list(dict.fromkeys(lines))  # DC gives the same reason for county and state

    link_src = yes or ([primary] if primary and primary.get("rule") and primary["rule"]["status"] != "error" else [])
    ordinance_urls = [e["rule"]["data"].get("ordinance_url") for e in link_src if e["rule"]["data"].get("ordinance_url")]
    form_urls = [u for e in yes for u in (e["rule"]["data"].get("registration_form_url"),
                                          e["rule"]["data"].get("registration_portal_url")) if u]
    form_urls += [link["url"] for e in yes for link in e["rule"]["data"].get("additional_links") or []
                  if "form" in link["label"].lower()]
    if ordinance_urls:
        lines.append("Please find the link to the applicable ordinance below:")
        lines += [f"Ordinance: {u}" for u in ordinance_urls]
    for e in yes:
        d = e["rule"]["data"]
        if d.get("registration_form_url"):
            lines.append(f"Registration Form: {d['registration_form_url']}")
        if d.get("registration_portal_url"):
            lines.append(f"Registration Portal: {d['registration_portal_url']}")
        for link in d.get("additional_links") or []:
            if "form" in link["label"].lower():
                lines.append(f"{link['label']}: {link['url']}")
        if d.get("registration_fee"):
            lines.append(f"Registration Fee: {d['registration_fee']}")

    fee_renew = lambda d: " / ".join(x for x in (d.get("renewal_fee"), d.get("renewal_frequency")) if x)
    method = lambda d: (d.get("registration_method") or "") + (f" ({d['third_party_platform']})" if d.get("third_party_platform") else "")
    sources = sorted({u for e in applicable if e.get("rule") and e["rule"].get("data")
                      for u in (e["rule"]["data"].get("source_urls") or [])})
    researched = [e["rule"]["researched_at"] for e in applicable if e.get("rule") and e["rule"].get("data")]
    confidences = [e["rule"]["data"]["confidence"] for e in applicable if e.get("rule") and e["rule"].get("data")]
    conf_rank = {"Low": 0, "Medium": 1, "High": 2}

    county = loc.get("county") or {}
    row = {
        "Address": lookup_input["address"].upper(),
        "City": lookup_input["city"].upper(),
        "State": loc["state_code"],
        "ZIP": loc.get("zip") or lookup_input.get("zip"),
        "County": county.get("name") or "",
        "City Wise": levels["city"]["flag"],
        "State Wise": levels["state"]["flag"],
        "County Wise": levels["county"]["flag"],
        "Ordinance": "\n".join(ordinance_urls) or "N/A",
        "Notes": "\n".join(lines),
        "Form Link": "\n".join(form_urls) or "N/A",
        "Registration Type": "\n".join(f"{e['jurisdiction']}: {_reg_type(e['rule']['data'])}" for e in yes) or "N/A",
        "Registration Fee": _join(yes, lambda d: d.get("registration_fee")),
        "Renewal Fee / Frequency": _join(yes, fee_renew),
        "Documents Required": _join(yes, lambda d: d.get("documents_required")),
        "Registration Method": _join(yes, method),
        "Registration Deadline": _join(yes, lambda d: d.get("registration_deadline")),
        "Condition (when required)": _join(yes, _condition),
        "Other Requirements": _join(yes, lambda d: d.get("other_requirements")),
        "Penalties": _join(yes, lambda d: d.get("penalties")),
        "Contact": _join(yes, lambda d: d.get("contact_info")),
        "Confidence": min(confidences, key=lambda c: conf_rank.get(c, 0)) if confidences else "N/A",
        "Sources": "\n".join(sources) or "N/A",
        "Researched On": min(researched)[:10] if researched else "",
    }
    # JSONB does not keep key order, so store the sheet's column order explicitly.
    return {"columns": list(row.keys()), "row": row, "levels": levels}


# --------------------------------------------------------------------------- entry point


def run_lookup(lookup_id: str) -> None:
    # `progress` holds JSON the UI renders as a step list.
    steps = {"phase": "geocoding", "jurisdictions": []}
    steps_lock = threading.Lock()

    def push(**extra) -> None:
        _set_progress(lookup_id, progress=json.dumps(steps), **extra)

    def on_state(key: str, state: str) -> None:
        with steps_lock:
            for j in steps["jurisdictions"]:
                if j["key"] == key:
                    j["state"] = state
            push()

    try:
        with session_scope() as s:
            lk = s.get(Lookup, lookup_id)
            inp, force = dict(lk.input), lk.force_refresh
            lk.status = "running"
            lk.progress = json.dumps(steps)

        loc = geocode.resolve(inp["address"], inp["city"], inp["state"], inp.get("zip", ""), inp.get("county"))
        jurs = loc["jurisdictions"]
        steps["phase"] = "researching"
        steps["jurisdictions"] = [{"key": j["key"], "name": j["display_name"], "level": j["level"], "state": "waiting"}
                                  for j in jurs]
        push(geocode=loc)

        # Review the most local level first (city -> county -> state). If a level requires foreclosure
        # registration, the remaining levels are not reviewed (business rule).
        ordered_jurs = sorted(jurs, key=lambda j: LEVELS.index(j["level"]))
        first, rest = ordered_jurs[0], ordered_jurs[1:]
        rules: dict[str, dict] = {first["key"]: get_or_research(first, loc, force, on_state)}
        first_entry = _level_entry(first["level"], first, rules[first["key"]], loc)
        if not _is_foreclosure_stop(first_entry) and rest:
            with ThreadPoolExecutor(max_workers=get_settings().research_concurrency) as pool:
                for j, r in zip(rest, pool.map(lambda j: get_or_research(j, loc, force, on_state), rest)):
                    rules[j["key"]] = r

        by_level = {j["level"]: j for j in ordered_jurs}
        levels: dict[str, dict] = {}
        stop = None
        for lvl in LEVELS:
            j = by_level.get(lvl)
            if stop and j:
                levels[lvl] = _skipped_entry(lvl, j, stop)
                on_state(j["key"], "skipped")
                continue
            levels[lvl] = _level_entry(lvl, j, rules.get(j["key"]) if j else None, loc)
            if _is_foreclosure_stop(levels[lvl]):
                stop = levels[lvl]
        result = _compose(inp, loc, levels)
        _set_progress(lookup_id, result=result, status="done", progress=None,
                      finished_at=datetime.now(timezone.utc))
    except geocode.GeocodeError as exc:
        _set_progress(lookup_id, status="error", error=str(exc), progress=None, finished_at=utcnow())
    except Exception as exc:
        log.exception("Lookup %s failed", lookup_id)
        _set_progress(lookup_id, status="error", error=f"{type(exc).__name__}: {exc}", progress=None,
                      finished_at=utcnow())
