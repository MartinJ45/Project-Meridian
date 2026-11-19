# Running Project Meridian

The challenge brief is in [README.md](README.md). This file covers the app.

## Requirements
- Python 3.11+ and Node 18+
- Optional: a Gemini API key. Without it, chat runs in **offline mode** (best matches and the
  drawing/3D still open, but no generated answer).

## Start

Windows (cmd, PowerShell, or double-click in Explorer):
```powershell
.\start.cmd
```
`start.cmd` runs `start.ps1` with `-ExecutionPolicy Bypass`. Calling `.\start.ps1` directly only
works inside PowerShell with script execution allowed; from cmd or a double-click Windows opens
`.ps1` files in Notepad instead.
macOS / Linux / Git Bash:
```bash
./start.sh
```
Then open http://127.0.0.1:8000. The first run creates `.venv`, builds the frontend, copies
`.env.example` to `.env` and builds `data/meridian.db`. Add `-Rebuild` (`.\start.cmd -Rebuild`) / `--rebuild` to redo
the database and frontend.

## Development (hot reload)

```powershell
cd backend; ..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
```powershell
cd frontend; npm run dev
```
Open http://127.0.0.1:5173 (Vite proxies `/api` and `/files` to the backend).

## Pipeline

| Step | Command (from `backend/`) | Output |
|---|---|---|
| Rebuild knowledge DB | `python -m app.ingest.run` | `data/meridian.db` (gitignored) |
| Re-extract PDF text | `python -m app.ingest.run --force` | `data/extracted/D-0xx.json` (committed) |
| Build 3D reconstructions | `python -m app.recon.build` | `data/models/D-0xx.glb` from `data/recon_specs/D-0xx.json` |

Corrections are journaled to `data/corrections.jsonl` and replayed on every rebuild.

## Layout

```
backend/app/
  main.py            FastAPI routes + serves frontend/dist
  schema.sql, db.py  SQLite schema (raw evidence tables + facts + corrections + audit)
  knowledge.py       queries, fuzzy search, correction propose/accept/reject
  ingest/            manifest, BOM, drawing text extraction, drawing<->BOM linking
  chat/              retrieve.py gathers evidence in Python; agent.py makes ONE Gemini call (JSON reply)
  recon/             dimension spec -> extruded .glb reconstruction
frontend/src/
  components/        ChatView, PartPanel (2D/3D/Evidence), PdfViewer, ModelViewer, DocumentsView, ReviewView
data/                extraction output, 3D specs/models, correction journal
```

## External services and data
- **Google Gemini API** (chat; planned: vision extraction of drawings). When enabled, chat
  messages and tool results (BOM rows, extracted drawing text) are sent to Google. The
  vision pass will send drawing page images.
- No other network services. All storage is local SQLite.
