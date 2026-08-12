# Sari-Sari Store Management System

Sari is a local inventory and receipt-management application for a neighborhood store. It includes item catalog management, stock movements, pricing, dashboard metrics, consolidated receipt-PDF imports, receipt review, and confirmation into the inventory ledger.

The complete application now runs on one Windows computer through Docker Desktop:

- React frontend served by NGINX;
- FastAPI backend;
- private PaddleOCR service;
- PostgreSQL database;
- persistent local volumes for database records, receipt PDFs, and OCR models.

See [the architecture reference](docs/architecture.md) for the container and data flow.

## Start on Windows

### Requirements

1. Windows 10/11 with WSL 2 enabled.
2. Docker Desktop configured for Linux containers.
3. At least 4 GB of memory available to Docker Desktop; 6–8 GB is preferable during the first PaddleOCR build and model download.

### First startup

From PowerShell in the project directory:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace both password/token placeholders in `.env` with different long random values, then run:

```powershell
.\start-sari.cmd
```

The `.cmd` launcher invokes the checked-in PowerShell startup script with a process-scoped execution-policy bypass. You can also run `.\start-sari.ps1` directly when your PowerShell policy allows local scripts.

Alternatively:

```powershell
docker compose up -d --build --wait
```

Open [http://localhost:8080](http://localhost:8080). The first start can take several minutes because the OCR image and model files are large.

### Routine commands

```powershell
# Status
docker compose ps

# Logs
docker compose logs --tail=100 frontend backend ocr-gateway database

# Stop without deleting data
docker compose down

# Start again
docker compose up -d --wait
```

Do not add `--volumes` to `docker compose down` during routine use. That option deletes the local PostgreSQL database and the receipt/OCR volumes.

## Local ports and storage

Only the frontend is published to Windows, at `127.0.0.1:8080` by default. NGINX forwards `/api` to the private backend container. Backend port `8000`, OCR port `8090`, and PostgreSQL port `5432` are not exposed to the host.

Persistent Docker volumes:

- `sari-database-data` — all structured application data;
- `sari-receipt-images` — original consolidated receipt PDF files;
- `sari-ocr-models` — PaddleOCR model cache.

To permit access from another trusted device on the same LAN, set `APP_BIND_ADDRESS=0.0.0.0`, update `CORS_ORIGINS`, and create a narrowly scoped Windows Firewall rule for `APP_PORT`. Keep the PostgreSQL and OCR ports private.

## Development without the full stack

Backend tests use an isolated SQLite database explicitly; the Docker deployment uses PostgreSQL.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Frontend development:

```bash
cd frontend
npm ci
npm run dev
```

The Vite development server proxies `/api` to `http://localhost:8000`. For ordinary use on Windows, run the complete Compose stack instead.

## Receipt report imports

The receipt workflow accepts a PDF report, not receipt photos. Upload a text-based consolidated line-item PDF containing item description, quantity, unit price, and total amount columns. Each import stays in review until confirmed, so verify the purchase date and all line items before stock is posted. Scanned PDFs without selectable text are rejected.

## API surface

The backend exposes these routes through `http://localhost:8080/api/v1`:

- `GET /dashboard`
- `GET|POST /items`
- `GET|PATCH /items/{id}`
- `POST /items/{id}/archive`
- `GET /inventory`
- `GET /items/{id}/movements`
- `POST /stock-movements`
- `GET /ocr/health`
- `GET|POST /receipt-scans`
- `GET|PATCH /receipt-scans/{id}`
- `POST /receipt-scans/{id}/retry`
- `PATCH /receipt-scans/{id}/lines/{line_id}`
- `POST /receipt-scans/{id}/confirm`
