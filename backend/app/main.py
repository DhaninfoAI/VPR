import io
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text, update

from . import service
from .config import get_settings
from .db import engine, init_db, session_scope
from .models import Jurisdiction, Lookup, VprRule, utcnow
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


def _lookup_out(lk: Lookup, full: bool = True) -> dict:
    out = {
        "id": lk.id, "status": lk.status, "progress": lk.progress, "error": lk.error,
        "created_at": lk.created_at.isoformat(), "finished_at": lk.finished_at and lk.finished_at.isoformat(),
        "input": lk.input,
    }
    if full:
        out["geocode"] = lk.geocode
        out["result"] = lk.result
    else:
        row = (lk.result or {}).get("row") or {}
        out["summary"] = {k: row.get(k) for k in ("City Wise", "County Wise", "State Wise", "County")}
    return out


@app.get("/api/health")
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    st = get_settings()
    return {"db": "ok", "openai_key_configured": bool(st.openai_api_key), "model": st.openai_model,
            "cache_ttl_days": st.cache_ttl_days}


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


@app.get("/api/lookups")
def list_lookups(limit: int = 25):
    with session_scope() as s:
        rows = s.scalars(select(Lookup).order_by(Lookup.created_at.desc()).limit(min(limit, 200))).all()
        return [_lookup_out(r, full=False) for r in rows]


@app.get("/api/lookups/{lookup_id}")
def get_lookup(lookup_id: str):
    with session_scope() as s:
        lk = s.get(Lookup, lookup_id)
        if not lk:
            raise HTTPException(404, "Lookup not found")
        return _lookup_out(lk)


def _xlsx(results: list[dict], filename: str) -> StreamingResponse:
    rows = [r["row"] for r in results]
    wb = Workbook()
    ws = wb.active
    ws.title = "VPR"
    headers = results[0].get("columns") or list(rows[0].keys()) if rows else []
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    wide = {"Notes": 70, "Documents Required": 60, "Other Requirements": 60, "Sources": 50,
            "Ordinance": 45, "Form Link": 45}
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = wide.get(h, 18)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
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
        return _xlsx([lk.result], f"VPR_{lk.input['address'][:30].replace(' ', '_')}.xlsx")


@app.get("/api/export.xlsx")
def export_all(limit: int = 500):
    with session_scope() as s:
        rows = s.scalars(select(Lookup).where(Lookup.status == "done")
                         .order_by(Lookup.created_at.desc()).limit(limit)).all()
        return _xlsx([r.result for r in rows if r.result], "VPR_lookups.xlsx")


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
            "vacant_required": r.vacant_required, "foreclosure_required": r.foreclosure_required,
            "registration_fee": r.registration_fee, "ordinance_url": r.ordinance_url, "form_url": r.form_url,
            "confidence": (r.data or {}).get("confidence"), "status": r.status,
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
