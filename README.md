# VPR Lookup

Enter a US property address → get whether **Vacant Property Registration (VPR)** or
**foreclosure registration** is required at the City / County / State level, with the
ordinance link, registration form, operator-style notes, registration fee, renewal,
full documents-required checklist, deadline, method, penalties and sources. Results can be
downloaded as Excel in the same layout as the operators' VPR tracking sheet (minus the work-order /
processing columns, plus the new requirement columns).

## How a lookup works

1. **Geocode** – the address goes to the free US Census geocoder, which returns the real
   county and whether the point is inside an incorporated city or an active town/township.
   (The mailing city is often wrong: an "Aurora, CO" address can be in unincorporated
   Arapahoe County.) If the address cannot be matched, the County you type is used instead.
2. **Reuse saved rules** – each jurisdiction (state, county, city/town) is stored in Postgres.
   If its rule was researched in the last `CACHE_TTL_DAYS` (default 3), it is reused instantly.
3. **Research** – missing or stale jurisdictions are researched in parallel with the OpenAI
   Responses API + `web_search`, returning strict JSON (see `backend/app/research.py`).
4. **Link check** – ordinance / form / portal URLs are requested to confirm they load.
5. **Compose** – flags, notes (operator template) and the sheet row are built
   (`backend/app/service.py`). County rules that only cover unincorporated areas are marked
   "No" for addresses inside a city.

## Run locally (Windows)

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm run dev
```

Open http://localhost:5173. (Or run `npm run build` once and open http://localhost:8000 –
the API serves the built frontend.)

First-time setup on a new machine:

```powershell
cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; copy .env.example .env
```

```powershell
cd frontend; npm install
```

## Deploy on your server (Docker)

1. Copy the `vpr-tool` folder to the server and create `backend/.env` (see `.env.example`).
2. `docker compose up -d --build`
3. The app listens on port 8000. Put it behind Nginx/Caddy with HTTPS, and add a login
   (e.g. basic auth in the proxy) – the app itself has no authentication yet.

## Database tables (created automatically)

| Table | Purpose |
|---|---|
| `vpr_jurisdictions` | One row per state / county / city-town researched (`key` like `city|CO|aurora`) |
| `vpr_rules` | Append-only research results per jurisdiction (full JSON + key columns, sources, link checks). Newest non-error row is the current rule; history is kept for change tracking. |
| `vpr_lookups` | Each address lookup: input, geocode result, final row |

## Pre-built jurisdiction database (`seed/`)

Jurisdictions from the reference workbook are researched by hand and loaded as `status = "seed"` rules,
which never expire and are used instantly by lookups (no OpenAI call).

- `seed/extract_jurisdictions.py <workbook>` – list every state/county/city in the workbook (`jurisdictions.json`)
- `seed/build_*.py` – one file per research batch; each writes `seed/research/*.json`
- `backend\.venv\Scripts\python seed\import_research.py` – load all research files (safe to re-run)
- `seed/check_seed_links.py` – fill in link checks for imported rules

Each entry carries a `confidence` (High / Medium / Low) and its sources. "Unclear" entries show
"manual verification needed" in the notes.

## Configuration (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | – | Postgres URL |
| `OPENAI_API_KEY` | – | Required for research |
| `OPENAI_MODEL` | `gpt-5.5` | Any model that supports `web_search` in the Responses API |
| `OPENAI_REASONING_EFFORT` | `medium` | Blank for non-reasoning models |
| `CACHE_TTL_DAYS` | `3` | Re-research saved rules older than this |

## Known limits / next steps

- AI research can be wrong – always check the Confidence, link checks and sources before
  relying on a result. Rules marked `human_verified` (future review screen) never expire.
- Connecticut: Census now uses planning regions instead of counties; CT has no county
  government, so County Wise is always "No".
- Next: bulk Excel upload, review/approve screen, scheduled 3-day refresh job for the whole
  saved database, user logins.
