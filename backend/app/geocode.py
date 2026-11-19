"""Resolve an address to its real governing jurisdictions using the free US Census geocoder.

The mailing city on an address is often not the government the property sits in
(e.g. an "Aurora, CO" address can be in unincorporated Arapahoe County). The Census
geographies tell us the actual county and whether the point is inside an incorporated
place or an active town/township (CT, NJ, PA, MI, ... towns are "county subdivisions").
"""

from __future__ import annotations

import logging
import re

import httpx

from .states import COUNTY_WORD, NO_COUNTY_GOVERNMENT, STATES

log = logging.getLogger(__name__)

CENSUS_BASE = "https://geocoding.geo.census.gov/geocoder/geographies"
COMMON = {
    "benchmark": "Public_AR_Current",
    "vintage": "Current_Current",
    "layers": "all",
    "format": "json",
}

PLACE_LABELS = {
    "city": "City",
    "town": "Town",
    "village": "Village",
    "borough": "Borough",
    "township": "Township",
    "charter township": "Charter Township",
    "municipality": "Municipality",
    "plantation": "Plantation",
    "city and borough": "City and Borough",
}


class GeocodeError(Exception):
    pass


def norm_name(name: str) -> str:
    """Normalize a place name for jurisdiction keys: 'Saint Petersburg' == 'St. Petersburg'."""
    n = re.sub(r"[.']", "", name.strip().lower())
    n = re.sub(r"^(saint|ste|st)\s+", "st ", n)
    n = re.sub(r"\s+(saint|st)\s+", " st ", n)
    return re.sub(r"\s+", " ", n)


def jur_key(level: str, state: str, name: str | None = None) -> str:
    state = state.upper()
    return f"state|{state}" if level == "state" else f"{level}|{state}|{norm_name(name or '')}"


def _first(geos: dict, key: str) -> dict | None:
    items = geos.get(key) or []
    return items[0] if items else None


def _label(entity: dict) -> str:
    name = entity.get("NAME", "")
    base = entity.get("BASENAME", "")
    suffix = name[len(base):].strip().lower() if name.startswith(base) else ""
    return PLACE_LABELS.get(suffix, "City")


def _census_match(street: str, city: str, state: str, zip_code: str) -> dict | None:
    with httpx.Client(timeout=30) as client:
        params = {**COMMON, "street": street, "city": city, "state": state, "zip": zip_code}
        r = client.get(f"{CENSUS_BASE}/address", params=params)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            return matches[0]
        one_line = ", ".join(p for p in (street, city, state, zip_code) if p)
        r = client.get(f"{CENSUS_BASE}/onelineaddress", params={**COMMON, "address": one_line})
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        return matches[0] if matches else None


def resolve(street: str, city: str, state: str, zip_code: str, county_hint: str | None) -> dict:
    """Return the location and the list of jurisdictions (state, county, city) to research."""
    state = state.upper().strip()
    if state not in STATES:
        raise GeocodeError(f"Unknown US state code: {state}")

    match = None
    try:
        match = _census_match(street, city, state, zip_code)
    except httpx.HTTPError as exc:
        log.warning("Census geocoder failed: %s", exc)

    if match:
        geos = match.get("geographies", {})
        county = _first(geos, "Counties")
        place = _first(geos, "Incorporated Places")
        subdivision = _first(geos, "County Subdivisions")
        comps = match.get("addressComponents", {})
        loc = {
            "source": "census",
            "matched_address": match.get("matchedAddress"),
            "zip": comps.get("zip") or zip_code,
            "lat": match.get("coordinates", {}).get("y"),
            "lon": match.get("coordinates", {}).get("x"),
            "county": county and {
                "name": county["BASENAME"], "full_name": county["NAME"], "geoid": county["GEOID"],
            },
        }
        if place:
            loc["municipality"] = {
                "name": place["BASENAME"], "label": _label(place), "geoid": place["GEOID"],
                "kind": "incorporated_place",
            }
        elif subdivision and subdivision.get("FUNCSTAT") == "A":
            # An active town/township government (New England, NJ, PA, NY, MI, WI, ...).
            loc["municipality"] = {
                "name": subdivision["BASENAME"], "label": _label(subdivision),
                "geoid": subdivision["GEOID"], "kind": "town_or_township",
            }
        else:
            loc["municipality"] = None  # unincorporated
    else:
        if not county_hint:
            raise GeocodeError(
                "The Census geocoder could not match this address. Check the street and ZIP, "
                "or enter the County so the lookup can continue without geocoding."
            )
        word = COUNTY_WORD.get(state, "County")
        loc = {
            "source": "user_input",
            "matched_address": None,
            "zip": zip_code,
            "lat": None,
            "lon": None,
            "county": {"name": county_hint.strip(), "full_name": f"{county_hint.strip()} {word}", "geoid": None},
            # Without geocoding we cannot tell city limits; assume the mailing city.
            "municipality": city.strip() and {
                "name": city.strip().title(), "label": "City", "geoid": None, "kind": "assumed_from_mailing_city",
            },
        }

    loc["state_code"] = state
    loc["state_name"] = STATES[state]
    loc["jurisdictions"] = _jurisdictions(loc)
    return loc


def _jurisdictions(loc: dict) -> list[dict]:
    st = loc["state_code"]
    if st == "DC":
        return [{
            "level": "city", "key": jur_key("city", "DC", "District of Columbia"), "name": "District of Columbia",
            "display_name": "District of Columbia", "geoid": "11",
        }]

    out = [{
        "level": "state", "key": jur_key("state", st), "name": loc["state_name"],
        "display_name": f"State of {loc['state_name']}", "geoid": None,
    }]

    county = loc.get("county")
    county_is_city = bool(county) and county["full_name"].lower().endswith(" city")  # VA/MD/MO/NV independent cities
    if county and st not in NO_COUNTY_GOVERNMENT and not county_is_city:
        out.append({
            "level": "county", "key": jur_key("county", st, county["name"]), "name": county["name"],
            "display_name": county["full_name"], "geoid": county.get("geoid"),
        })

    muni = loc.get("municipality")
    if muni:
        out.append({
            "level": "city", "key": jur_key("city", st, muni["name"]), "name": muni["name"],
            "display_name": f"{muni['label']} of {muni['name']}", "geoid": muni.get("geoid"),
        })
    return out
