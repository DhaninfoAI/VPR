"""Bulk upload: read an Excel/CSV file of addresses, check its structure, and run one lookup per row.

File rules (also shown in the UI and the downloadable template):
  * .xlsx or .csv, first sheet only, up to `batch_max_rows` data rows.
  * A header row with Address, City and State columns (ZIP and County optional). Header names are
    matched without regard to case, spaces or punctuation, and common variants are accepted
    ("Street Address", "Zip Code", "ST" ...). Other columns are kept and copied into the export.
  * Structural problems reject the whole file with a message; problems in single rows only mark
    those rows "Invalid" and the other rows still run.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

from openpyxl import load_workbook

from . import service
from .config import get_settings
from .db import session_scope
from .models import Batch, Lookup
from .states import STATES

log = logging.getLogger(__name__)

FIELDS = ("address", "city", "state", "zip", "county")
REQUIRED = ("address", "city", "state")
LABEL = {"address": "Address", "city": "City", "state": "State", "zip": "ZIP", "county": "County"}
ALIASES = {
    "address": {"address", "streetaddress", "street", "propertyaddress", "address1", "addressline1", "propertystreet",
                "streetaddress1", "siteaddress"},
    "city": {"city", "town", "municipality", "propertycity", "citytown"},
    "state": {"state", "statecode", "st", "propertystate", "stateabbreviation"},
    "zip": {"zip", "zipcode", "postalcode", "zip5", "postcode", "propertyzip", "zippostalcode"},
    "county": {"county", "propertycounty", "countyname"},
}
STATE_BY_NAME = {v.lower(): k for k, v in STATES.items()}
MAX_BYTES = 5 * 1024 * 1024
HEADER_SCAN_ROWS = 10


class FileProblem(ValueError):
    """The file as a whole cannot be used; the message is shown to the user."""


def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # Excel stores ZIPs as numbers: 60505.0
    return str(v).strip()


def _read_rows(filename: str, content: bytes) -> list[list[str]]:
    name = filename.lower()
    if not content:
        raise FileProblem("The file is empty.")
    if len(content) > MAX_BYTES:
        raise FileProblem("The file is larger than 5 MB. Split it into smaller files.")
    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return [[_cell(c) for c in r] for r in csv.reader(io.StringIO(text))]
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        raise FileProblem("Old .xls files are not supported. In Excel use File > Save As > Excel Workbook (.xlsx).")
    if not name.endswith((".xlsx", ".xlsm")):
        raise FileProblem("Upload an Excel (.xlsx) or CSV (.csv) file.")
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError):
        raise FileProblem("The file could not be opened as an Excel workbook. Is it password protected or damaged?")
    ws = wb.worksheets[0]
    limit = get_settings().batch_max_rows + HEADER_SCAN_ROWS + 1000  # stop early on huge sheets
    rows = []
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i >= limit:
            break
        rows.append([_cell(c) for c in r])
    wb.close()
    return rows


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Header row = first row (within the first few) naming at least two of Address/City/State."""
    for i, r in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for col, h in enumerate(r):
            key = _norm_header(h)
            for field, names in ALIASES.items():
                if key in names:
                    if field in mapping:
                        raise FileProblem(f"Two columns both look like '{LABEL[field]}' "
                                          f"('{r[mapping[field]]}' and '{h}'). Keep only one.")
                    mapping[field] = col
        if sum(f in mapping for f in REQUIRED) >= 2:
            missing = [LABEL[f] for f in REQUIRED if f not in mapping]
            if missing:
                found = ", ".join(f"'{h}'" for h in r if h) or "none"
                raise FileProblem(f"Missing required column: {', '.join(missing)}. Columns found: {found}.")
            return i, mapping
    first = next((r for r in rows if any(r)), [])
    found = ", ".join(f"'{h}'" for h in first if h) or "none"
    raise FileProblem("Could not find the header row. The first row must have the column names Address, City and "
                      f"State (ZIP and County optional). First row found: {found}.")


def _clean_zip(z: str) -> tuple[str, str | None]:
    if not z:
        return "", None
    z = z.replace(" ", "")
    if re.fullmatch(r"\d{3,4}", z):
        z = z.zfill(5)  # Excel drops leading zeros (07102 -> 7102)
    if re.fullmatch(r"\d{5}(-?\d{4})?", z):
        return z[:5] + ("-" + z[-4:] if len(z) > 5 else ""), None
    return z, f"ZIP '{z}' is not a valid US ZIP code"


def _clean_state(s: str) -> tuple[str, str | None]:
    v = s.strip()
    if v.upper() in STATES:
        return v.upper(), None
    if v.lower() in STATE_BY_NAME:
        return STATE_BY_NAME[v.lower()], None
    return v, (f"State '{v}' is not a US state" if v else "State is empty")


def parse(filename: str, content: bytes) -> tuple[list[str], list[dict]]:
    """Return (extra column names, rows). Raises FileProblem when the file cannot be used at all."""
    rows = _read_rows(filename, content)
    if not any(any(r) for r in rows):
        raise FileProblem("The file has no data.")
    h_idx, mapping = _find_header(rows)
    header = rows[h_idx]
    used = set(mapping.values())
    extra_cols = [(c, h) for c, h in enumerate(header) if c not in used and h]

    out = []
    for offset, r in enumerate(rows[h_idx + 1:], start=h_idx + 2):  # sheet row numbers are 1-based
        if not any(r):
            continue  # blank line
        get = lambda f: r[mapping[f]] if f in mapping and mapping[f] < len(r) else ""
        inp = {f: get(f) for f in FIELDS}
        errors = []
        if len(inp["address"]) < 3:
            errors.append("Address is empty" if not inp["address"] else "Address is too short")
        elif len(inp["address"]) > 200:
            errors.append("Address is longer than 200 characters")
        if len(inp["city"]) < 2:
            errors.append("City is empty" if not inp["city"] else "City is too short")
        inp["state"], e = _clean_state(inp["state"])
        errors += [e] if e else []
        inp["zip"], e = _clean_zip(inp["zip"])
        errors += [e] if e else []
        inp["county"] = inp["county"] or None
        out.append({"row": offset, "input": inp, "extra": {h: (r[c] if c < len(r) else "") for c, h in extra_cols},
                    "lookup_id": None, "error": "; ".join(errors) or None})
    if not out:
        raise FileProblem("The header row was found but there are no address rows under it.")
    limit = get_settings().batch_max_rows
    if len(out) > limit:
        raise FileProblem(f"The file has {len(out)} address rows; the limit is {limit} per upload. Split it into smaller files.")
    if all(r["error"] for r in out):
        raise FileProblem("None of the rows can be looked up. First problem (row "
                          f"{out[0]['row']}): {out[0]['error']}.")
    return [h for _, h in extra_cols], out


# --------------------------------------------------------------------------- running


def _create_lookups(rows: list[dict]) -> list[str]:
    ids = []
    with session_scope() as s:
        for r in rows:
            if r["error"]:
                continue
            # "source" keeps bulk rows out of the single-lookup History page.
            lk = Lookup(input={**{k: r["input"][k] for k in FIELDS}, "source": "bulk"}, force_refresh=False,
                        status="pending")
            s.add(lk)
            s.flush()
            r["lookup_id"] = lk.id
            ids.append(lk.id)
    return ids


def _run_all(ids: list[str]) -> None:
    # Rows sharing a city wait on the same jurisdiction lock in service.get_or_research, so each
    # city/county/state is researched once and the other rows reuse the saved rule.
    with ThreadPoolExecutor(max_workers=get_settings().batch_concurrency) as pool:
        list(pool.map(service.run_lookup, ids))


def start(filename: str, content: bytes) -> str:
    extra_cols, rows = parse(filename, content)
    ids = _create_lookups(rows)
    with session_scope() as s:
        b = Batch(filename=filename[:255], extra_columns=extra_cols, rows=rows)
        s.add(b)
        s.flush()
        batch_id = b.id
    threading.Thread(target=_run_all, args=(ids,), daemon=True, name=f"batch-{batch_id[:8]}").start()
    return batch_id


def retry_failed(batch_id: str) -> int:
    """Run again every row whose lookup failed (for example after a server restart)."""
    with session_scope() as s:
        b = s.get(Batch, batch_id)
        if not b:
            raise KeyError(batch_id)
        ids = [r["lookup_id"] for r in b.rows if r["lookup_id"]]
        failed = {lk.id for lk in s.query(Lookup).filter(Lookup.id.in_(ids), Lookup.status == "error")}
        rows = [dict(r) for r in b.rows]
        redo = [r for r in rows if r["lookup_id"] in failed]
        for r in redo:
            r["lookup_id"] = None
    new_ids = _create_lookups(redo)
    with session_scope() as s:
        s.get(Batch, batch_id).rows = rows
    if new_ids:
        threading.Thread(target=_run_all, args=(new_ids,), daemon=True).start()
    return len(new_ids)
