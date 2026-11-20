import io
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text, update

from . import batch, service
from .config import get_settings
from .db import engine, init_db, session_scope
from .models import Batch, Jurisdiction, Lookup, VprRule, utcnow
from .states import STATES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as s:  # lookups interrupted by a restart will never finish
        s.execute(update(Lookup).where(Lookup.status.in_(["pending", "running"]))
                  .values(status="error", error="Interrupted by a server restart - run it again.",
                          progress=None, finished_at=utcnow()))
    yield


app = FastAPI(title="VPR Lookup", lifespan=lifespan)


class LookupIn(BaseModel):
    address: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=2, max_length=100)
    state: str
    zip: str = Field(default="", max_length=10)
    county: str | None = Field(default=None, max_length=100)
    force_refresh: bool = False

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in STATES:
            raise ValueError("Unknown US state code")
        return v


TECH_ERROR = re.compile(r"^[A-Za-z_.]*(Error|Exception)\b")


def _client_error(err: str | None) -> str | None:
    """Technical exception text is replaced; plain messages (address not found...) are kept."""
    if err and TECH_ERROR.match(err):
        return "The lookup could not be completed. Please try again."
    return err


def _lookup_out(lk: Lookup, full: bool = True) -> dict:
    out = {
        "id": lk.id, "status": lk.status, "progress": lk.progress, "error": _client_error(lk.error),
        "created_at": lk.created_at.isoformat(), "finished_at": lk.finished_at and lk.finished_at.isoformat(),
        "input": {k: v for k, v in (lk.input or {}).items() if k != "source"},
    }
    res = service.client_result(lk.result)
    if full:
        out["geocode"] = lk.geocode
        out["result"] = res
    else:
        row = (res or {}).get("row") or {}
        out["summary"] = {k: row.get(k) for k in ("City Wise", "County Wise", "State Wise", "County")}
    return out


@app.get("/api/health")
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    return {"db": "ok"}


@app.get("/api/states")
def states():
    return [{"code": k, "name": v} for k, v in sorted(STATES.items(), key=lambda kv: kv[1])]


@app.post("/api/lookups", status_code=202)
def create_lookup(body: LookupIn, background: BackgroundTasks):
    data = body.model_dump()
    force = data.pop("force_refresh")
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    with session_scope() as s:
        lk = Lookup(input=data, force_refresh=force, status="pending")
        s.add(lk)
        s.flush()
        lookup_id = lk.id
    background.add_task(service.run_lookup, lookup_id)
    return {"id": lookup_id}


SINGLE_ONLY = ~Lookup.input.has_key("source")  # bulk-upload rows are listed under their batch instead


@app.get("/api/lookups")
def list_lookups(limit: int = 25):
    with session_scope() as s:
        rows = s.scalars(select(Lookup).where(SINGLE_ONLY).order_by(Lookup.created_at.desc())
                         .limit(min(limit, 200))).all()
        return [_lookup_out(r, full=False) for r in rows]


@app.get("/api/lookups/{lookup_id}")
def get_lookup(lookup_id: str):
    with session_scope() as s:
        lk = s.get(Lookup, lookup_id)
        if not lk:
            raise HTTPException(404, "Lookup not found")
        return _lookup_out(lk)


def _xlsx(results: list[dict], filename: str, headers: list[str] | None = None,
          rows: list[dict] | None = None) -> StreamingResponse:
    """Write result rows to a workbook. Pass `headers`/`rows` directly for exports with extra columns."""
    if rows is None:
        rows = [r["row"] for r in results]
        headers = (results[0].get("columns") or list(rows[0].keys())) if rows else []
    wb = Workbook()
    ws = wb.active
    ws.title = "VPR"
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2B2A27")
    wide = {"Notes": 70, "Documents Required": 60, "Other Requirements": 60, "Sources": 50,
            "Ordinance": 45, "Form Link": 45, "Lookup Status": 14, "Problem": 40}
    tone = {"Yes": "F6D9D4", "Yes (conditional)": "FBEACB", "No": "D9EEDF", "Error": "E7E5E0"}
    flag_cols = {i for i, h in enumerate(headers, start=1) if h in ("City Wise", "County Wise", "State Wise")}
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = wide.get(h, 18)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if cell.column in flag_cols and cell.value in tone:
                cell.fill = PatternFill("solid", fgColor=tone[cell.value])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/lookups/{lookup_id}/export.xlsx")
def export_lookup(lookup_id: str):
    with session_scope() as s:
        lk = s.get(Lookup, lookup_id)
        if not lk or not lk.result:
            raise HTTPException(404, "No finished result for this lookup")
        return _xlsx([service.client_result(lk.result)], f"VPR_{lk.input['address'][:30].replace(' ', '_')}.xlsx")


@app.get("/api/export.xlsx")
def export_all(limit: int = 500):
    with session_scope() as s:
        rows = s.scalars(select(Lookup).where(Lookup.status == "done", SINGLE_ONLY)
                         .order_by(Lookup.created_at.desc()).limit(limit)).all()
        return _xlsx([service.client_result(r.result) for r in rows if r.result], "VPR_lookups.xlsx")


# --------------------------------------------------------------------------- bulk upload

SUMMARY_KEYS = ("City Wise", "County Wise", "State Wise", "County")


def _row_states(s, ids: list[str]) -> dict[str, dict]:
    """Status and the few result fields the table needs, without loading whole results."""
    if not ids:
        return {}
    cols = [Lookup.id, Lookup.status, Lookup.error] + [Lookup.result[("row", k)].astext for k in SUMMARY_KEYS]
    out = {}
    for rec in s.execute(select(*cols).where(Lookup.id.in_(ids))).all():
        summary = dict(zip(SUMMARY_KEYS, rec[3:]))
        for k in ("City Wise", "County Wise", "State Wise"):
            summary[k] = service._client_flag(summary[k])
        out[rec[0]] = {"status": rec[1], "error": _client_error(rec[2]), "summary": summary}
    return out


def _batch_out(b: Batch, states: dict[str, dict], with_rows: bool = True) -> dict:
    counts = {"total": len(b.rows), "invalid": 0, "pending": 0, "done": 0, "error": 0,
              "required": 0, "not_required": 0, "review": 0}
    rows = []
    for r in b.rows:
        st = states.get(r["lookup_id"]) if r["lookup_id"] else None
        status = "invalid" if r["error"] else (st["status"] if st else "error")
        summary = (st or {}).get("summary") or {}
        if status == "invalid":
            counts["invalid"] += 1
        elif status in ("pending", "running"):
            counts["pending"] += 1
        elif status == "error":
            counts["error"] += 1
        else:
            counts["done"] += 1
            flags = [summary.get(k) for k in ("City Wise", "County Wise", "State Wise")]
            key = ("required" if any(service.is_required(f) for f in flags)
                   else "review" if "Error" in flags else "not_required")
            counts[key] += 1
        rows.append({"row": r["row"], "input": r["input"], "extra": r.get("extra") or {}, "lookup_id": r["lookup_id"],
                     "status": status, "error": r["error"] or (st or {}).get("error"), "summary": summary})
    out = {"id": b.id, "filename": b.filename, "created_at": b.created_at.isoformat(),
           "extra_columns": b.extra_columns or [], "counts": counts,
           "running": counts["pending"] > 0}
    if with_rows:
        out["rows"] = rows
    return out


@app.get("/api/batches/template.xlsx")
def batch_template():
    wb = Workbook()
    ws = wb.active
    ws.title = "Addresses"
    ws.append(["Address", "City", "State", "ZIP", "County"])
    ws.append(["44 E Downer Pl", "Aurora", "IL", "60505", ""])
    ws.append(["100 N Holliday St", "Baltimore", "MD", "21202", ""])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2B2A27")
    for col, w in zip("ABCDE", (34, 20, 10, 12, 20)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    info = wb.create_sheet("Instructions")
    for line in [
        ["How to fill this file"],
        ["Only the first sheet ('Addresses') is read. Replace the two example rows with your addresses."],
        ["Required columns: Address, City, State. Optional: ZIP, County (county is detected automatically)."],
        ["State can be a 2-letter code (IL) or the full name (Illinois)."],
        ["You can add other columns (for example Loan # or Reference); they are copied into the results export."],
        ["Up to 500 address rows per file. Blank rows are skipped."],
    ]:
        info.append(line)
    info["A1"].font = Font(bold=True, size=12)
    info.column_dimensions["A"].width = 100
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="VPR_bulk_template.xlsx"'})


@app.post("/api/batches", status_code=202)
async def create_batch(request: Request, filename: str = "upload.xlsx"):
    """Body = the raw file bytes; `filename` tells the format (.xlsx / .csv)."""
    content = await request.body()
    try:
        batch_id = await run_in_threadpool(batch.start, filename, content)
    except batch.FileProblem as exc:
        raise HTTPException(400, str(exc))
    with session_scope() as s:
        b = s.get(Batch, batch_id)
        return _batch_out(b, _row_states(s, [r["lookup_id"] for r in b.rows if r["lookup_id"]]), with_rows=False)


@app.get("/api/batches")
def list_batches(limit: int = 20):
    with session_scope() as s:
        bs = s.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(min(limit, 100))).all()
        ids = [r["lookup_id"] for b in bs for r in b.rows if r["lookup_id"]]
        states = _row_states(s, ids)
        return [_batch_out(b, states, with_rows=False) for b in bs]


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    with session_scope() as s:
        b = s.get(Batch, batch_id)
        if not b:
            raise HTTPException(404, "Upload not found")
        return _batch_out(b, _row_states(s, [r["lookup_id"] for r in b.rows if r["lookup_id"]]))


@app.post("/api/batches/{batch_id}/retry")
def retry_batch(batch_id: str):
    try:
        return {"restarted": batch.retry_failed(batch_id)}
    except KeyError:
        raise HTTPException(404, "Upload not found")


@app.get("/api/batches/{batch_id}/export.xlsx")
def export_batch(batch_id: str):
    with session_scope() as s:
        b = s.get(Batch, batch_id)
        if not b:
            raise HTTPException(404, "Upload not found")
        ids = [r["lookup_id"] for r in b.rows if r["lookup_id"]]
        lookups = {lk.id: lk for lk in s.scalars(select(Lookup).where(Lookup.id.in_(ids)))} if ids else {}
        results = {i: service.client_result(lk.result) for i, lk in lookups.items()}
        result_cols = next((res["columns"] for res in results.values() if res), None) or \
            ["Address", "City", "State", "ZIP", "County", "City Wise", "State Wise", "County Wise", "Notes"]
        taken = {"Row", "Lookup Status", "Problem", *result_cols}
        extra_name = {h: (f"{h} (your file)" if h in taken else h) for h in (b.extra_columns or [])}
        headers = ["Row", *extra_name.values(), "Lookup Status", "Problem", *result_cols]
        status_text = {"done": "Done", "error": "Failed", "pending": "Running", "running": "Running"}
        out_rows = []
        for r in b.rows:
            lk = lookups.get(r["lookup_id"]) if r["lookup_id"] else None
            row = {"Row": r["row"], **{extra_name.get(k, k): v for k, v in (r.get("extra") or {}).items()}}
            inp = r["input"] or {}
            row.update({"Address": inp.get("address"), "City": inp.get("city"), "State": inp.get("state"),
                        "ZIP": inp.get("zip"), "County": inp.get("county")})
            if r["error"]:
                row.update({"Lookup Status": "Invalid row", "Problem": r["error"]})
            elif lk is None:
                row.update({"Lookup Status": "Failed", "Problem": "Lookup record missing"})
            else:
                row["Lookup Status"] = status_text.get(lk.status, lk.status)
                row["Problem"] = _client_error(lk.error)
                if lk.status == "done" and results.get(lk.id):
                    row.update(results[lk.id]["row"])
            out_rows.append(row)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(b.filename).stem)[:40] or "upload"
        return _xlsx([], f"VPR_results_{stem}.xlsx", headers=headers, rows=out_rows)


@app.get("/api/jurisdictions")
def list_jurisdictions(state: str | None = None):
    """Saved knowledge base: every jurisdiction researched so far with its current rule."""
    with session_scope() as s:
        latest = (select(VprRule.jurisdiction_id, func.max(VprRule.researched_at).label("ts"))
                  .where(VprRule.status != "error").group_by(VprRule.jurisdiction_id).subquery())
        q = (select(Jurisdiction, VprRule)
             .join(latest, latest.c.jurisdiction_id == Jurisdiction.id)
             .join(VprRule, (VprRule.jurisdiction_id == Jurisdiction.id) & (VprRule.researched_at == latest.c.ts))
             .order_by(Jurisdiction.state_code, Jurisdiction.level, Jurisdiction.name))
        if state:
            q = q.where(Jurisdiction.state_code == state.upper())
        return [{
            "jurisdiction": j.display_name, "level": j.level, "state": j.state_code,
            "vacant_required": service._client_flag(r.vacant_required),
            "foreclosure_required": service._client_flag(r.foreclosure_required),
            "condition": (r.data or {}).get("requirement_conditions"),
            "registration_fee": r.registration_fee, "ordinance_url": r.ordinance_url, "form_url": r.form_url,
            "researched_at": r.researched_at.isoformat(),
        } for j, r in s.execute(q).all()]


# Serve the built React app (frontend/dist) from the same server in production.
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_relative_to(FRONTEND_DIST.resolve()) and file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
