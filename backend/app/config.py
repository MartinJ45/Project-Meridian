"""Paths and settings. Everything is resolved relative to the repository root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATASET = ROOT / "dataset"
MANIFEST = DATASET / "manifest.json"
BOM_CSV = DATASET / "context" / "openlpbf-bom.csv"

DATA = ROOT / "data"
DB_PATH = DATA / "meridian.db"          # generated, gitignored; rebuilt by ingest
EXTRACTED = DATA / "extracted"          # committed: per-drawing extraction output
RECON_SPECS = DATA / "recon_specs"      # committed: hand/LLM-read dimensions per part
MODELS_DIR = DATA / "models"            # committed: generated .glb reconstructions

FRONTEND_DIST = ROOT / "frontend" / "dist"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
# Tried in order when the primary model is overloaded (503/429) or times out.
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
# Per-request timeout. A chat turn makes several requests (one per tool round).
GEMINI_TIMEOUT_S = float(os.getenv("GEMINI_TIMEOUT_S", "60"))
# Thinking effort for chat replies: minimal | low | medium | high, or empty for the model default.
# Lower is faster; answers come from retrieved evidence, so heavy reasoning is rarely needed.
GEMINI_THINKING = os.getenv("GEMINI_THINKING", "low").strip()
# Whole chat turn: no further fallback model is tried once this much time has passed.
GEMINI_TURN_BUDGET_S = float(os.getenv("GEMINI_TURN_BUDGET_S", "60"))
