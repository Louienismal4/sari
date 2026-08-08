# Sari-Sari Store Management System

Phase 1 is a small, dependable inventory foundation for a neighborhood store. It currently includes:

- item catalog CRUD with categories, purchase/selling units, pack-size conversion, suppliers, archive state, and per-selling-unit pricing;
- suggested-price calculation with PHP rounding and separate actual selling price;
- stock-in, stock-out, physical-count adjustment, and movement history;
- dashboard totals and low-stock attention list;
- receipt camera preview/capture with compressed-image upload fallback;
- a private OCR gateway contract with mock mode, local PaddleOCR PP-OCRv4 inference, normalized errors, durable scan attempts, and bounded retry handling;
- a responsive desktop/mobile UI that keeps manual inventory usable when OCR is offline.

The local default remains mock OCR. Set the application to `OCR_PROVIDER=gateway` to call the private service in `services/ocr-gateway`; set that service to `OCR_GATEWAY_PROVIDER=paddleocr` on the Windows OCR host. The gateway defaults to CPU-only `PP-OCRv4_mobile_det` plus `en_PP-OCRv4_mobile_rec`; provider credentials never enter the React bundle.

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API loads the project-root `.env`, starts with the local SQLite database at `backend/sari.db`, and seeds a few sample items on the first run. Set `DATABASE_URL` to a PostgreSQL connection string when moving to Supabase. Standard `postgresql://` and `postgres://` URLs are normalized to the installed `psycopg` driver, Supabase connections require SSL, and the SQLAlchemy pool is configurable with the `DB_POOL_*` variables in `.env.example`.

Do not use `https://PROJECT_REF.supabase.co` as `DATABASE_URL`; that is the Data API URL, not a PostgreSQL connection string.

### Move the local database to Supabase

The repository includes a one-time, non-destructive SQLite-to-Postgres transfer. Stop the backend before starting so it cannot seed or write to the target while the copy is running.

1. In Supabase, open the project's **Connect** panel. Prefer the direct connection for the one-time migration when the machine has IPv6; otherwise use the shared session pooler on port `5432`. For the persistent FastAPI backend, use the direct connection on an IPv6-capable host or the session pooler on IPv4-only hosts. Transaction-pooler URLs on port `6543` are supported, but are intended for temporary/serverless clients.
2. Put the migration URL in the uncommitted project-root `.env` as `SUPABASE_MIGRATION_DATABASE_URL`. Put the backend runtime URL in `DATABASE_URL`; they may be the same session-pooler URL. Keep the database password out of source control.
3. Check connectivity and source row counts without writing:

   ```bash
   cd backend
   .venv/bin/python -m scripts.migrate_sqlite_to_supabase --check-only
   ```

4. Stop the backend, then run the copy:

   ```bash
   .venv/bin/python -m scripts.migrate_sqlite_to_supabase
   ```

   The script validates the SQLite schema without altering it, creates native PostgreSQL UUID/timestamp/numeric columns and required indexes, refuses a non-empty target, copies rows in foreign-key order, and verifies every target row count inside the same transaction. If you have deliberately confirmed that existing Sari rows should be replaced, rerun with `--replace-target`; the script first saves those rows under `backend/backups/`, then replaces only the eight application tables atomically. It also enables RLS and removes direct `anon`/`authenticated` table grants because this app accesses the database only through FastAPI. Use `--skip-rls-hardening` only if you intentionally plan to expose these tables through Supabase's Data API and will immediately add reviewed policies.
5. Start the backend with the runtime `DATABASE_URL`, then verify `GET /api/v1/health/ready` and the dashboard. Do not allow the app to write to Supabase until the copy has completed.

This migration moves database rows only. Receipt image files remain under `backend/storage/receipts`; move them to shared storage separately before deploying the backend away from this machine.

Connection modes: [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres). Import guidance: [Import data into Supabase](https://supabase.com/docs/guides/database/import-data). RLS guidance: [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security).

### OCR gateway

The gateway is optional for local mock work. To run its contract locally:

```bash
export OCR_PROVIDER=mock
export OCR_GATEWAY_PROVIDER=mock
export OCR_SERVICE_TOKEN=replace-with-a-long-random-token
PYTHONPATH=services/ocr-gateway uvicorn app.main:app --app-dir services/ocr-gateway --host 127.0.0.1 --port 8090
```

For the Windows PC topology and the hardened Compose service, see [docs/ocr-gateway.md](docs/ocr-gateway.md) and [services/ocr-gateway/README.md](services/ocr-gateway/README.md).

### Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite dev server proxies `/api` to the FastAPI server at `http://localhost:8000`.

Useful checks:

```bash
cd frontend
npm run build

cd ../backend
pytest
```

## API surface

The FastAPI OpenAPI document is available at [http://localhost:8000/docs](http://localhost:8000/docs).

Core endpoints:

- `GET /api/v1/dashboard`
- `GET|POST /api/v1/items`
- `GET|PATCH /api/v1/items/{id}`
- `POST /api/v1/items/{id}/archive`
- `GET /api/v1/inventory`
- `GET /api/v1/items/{id}/movements`
- `POST /api/v1/stock-movements`
- `GET /api/v1/ocr/health`
- `POST /api/v1/receipt-scans`
- `GET /api/v1/receipt-scans/{id}`
- `POST /api/v1/receipt-scans/{id}/retry`
- `PATCH /api/v1/receipt-scans/{id}/lines/{line_id}`
- `POST /api/v1/receipt-scans/{id}/confirm`

## Phase 1 decisions in this slice

- Currency: PHP, rounded half-up to two decimal places.
- Stock quantities: decimal-safe; the UI uses step `0.001` so weight-based units remain possible.
- Item codes: generated as `ITM-000001` when not supplied.
- Negative stock: rejected for normal stock-out actions.
- Archive: items are soft-archived and retain their ledger/history.
- App-to-gateway authentication: rotated service token; user authentication remains deferred to the Phase 1 hardening milestone.

## Design reference

The dashboard visual reference used for the implementation is [docs/design/phase-1-dashboard-concept.png](docs/design/phase-1-dashboard-concept.png).
