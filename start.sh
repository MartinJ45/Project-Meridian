#!/usr/bin/env bash
# One-command local launch (macOS / Linux / Git Bash).
#   ./start.sh            build if needed, then serve on http://127.0.0.1:8000
#   ./start.sh --rebuild  force re-ingest and frontend rebuild
set -euo pipefail
cd "$(dirname "$0")"
REBUILD=0; [[ "${1:-}" == "--rebuild" ]] && REBUILD=1
PORT="${PORT:-8000}"

[[ -d .venv ]] || { echo "> Creating Python venv"; python3 -m venv .venv; }
PY=.venv/bin/python; [[ -x "$PY" ]] || PY=.venv/Scripts/python.exe
echo "> Installing Python requirements"
"$PY" -m pip install -q -r backend/requirements.txt

if [[ $REBUILD == 1 || ! -d frontend/dist ]]; then
  echo "> Building frontend"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

[[ -f .env ]] || { cp .env.example .env; echo "> Created .env - add GEMINI_API_KEY for chat answers (offline mode works without it)"; }

cd backend
if [[ $REBUILD == 1 || ! -f ../data/meridian.db ]]; then
  echo "> Building knowledge database"
  "../$PY" -m app.ingest.run
fi
echo "> Serving on http://127.0.0.1:$PORT"
exec "../$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
