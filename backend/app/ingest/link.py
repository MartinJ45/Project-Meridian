"""Drawing <-> BOM links.

1. Reviewed decisions from data/links_curated.json (one per drawing: confirmed / probable / none,
   each with the evidence behind it). These replace fuzzy matching for the drawings they cover.
2. Fuzzy filename matching, only for drawings without a reviewed decision; stored as
   'candidate' with a score, never presented as fact.
"""
import json
import re

from rapidfuzz import fuzz, process

from ..config import DATA

CURATED = DATA / "links_curated.json"
STATUS_SCORE = {"confirmed": 100.0, "probable": 70.0}

# Upstream filename noise that is not part of the part name
NOISE = re.compile(r"\b(x\d+|v\d+|version\s*\d+|loop\s*\d+)\b", re.I)


def normalise(s: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s or "")
    s = NOISE.sub(" ", s.replace("_", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


def load_curated(con) -> set[str]:
    if not CURATED.exists():
        return set()
    data = json.loads(CURATED.read_text(encoding="utf-8"))["links"]
    for doc_id, d in data.items():
        con.execute("INSERT OR REPLACE INTO link_decisions (document_id, status, rationale) VALUES (?,?,?)",
                    (doc_id, d["status"], d["rationale"]))
        for row in d["rows"]:
            con.execute(
                """INSERT OR REPLACE INTO doc_bom_links (document_id, row_index, score, method, status, rationale)
                   VALUES (?,?,?, 'curated', ?, ?)""",
                (doc_id, row, STATUS_SCORE.get(d["status"], 50.0), d["status"], d["rationale"]))
    return set(data)


def fuzzy(con, skip: set[str], min_score: float = 70, top_k: int = 3) -> int:
    bom = [dict(r) for r in con.execute("SELECT row_index, name, part_family FROM bom_rows WHERE name IS NOT NULL")]
    choices = {b["row_index"]: normalise(b["name"]) for b in bom}
    family = {b["row_index"]: (b["part_family"] or "").lower() for b in bom}
    n = 0
    for d in con.execute("SELECT id, title, subsystem FROM documents").fetchall():
        if d["id"] in skip:
            continue
        hits = process.extract(normalise(d["title"]), choices, scorer=fuzz.token_set_ratio, limit=top_k * 3)
        ranked = []
        for _, score, row_index in hits:
            if family[row_index] and family[row_index] == (d["subsystem"] or "").lower():
                score += 5
            if score >= min_score:
                ranked.append((score, row_index))
        for score, row_index in sorted(ranked, reverse=True)[:top_k]:
            con.execute(
                "INSERT OR REPLACE INTO doc_bom_links (document_id, row_index, score, method, status) VALUES (?,?,?,?, 'candidate')",
                (d["id"], row_index, min(score, 100), "filename-fuzzy"))
            n += 1
    return n


def run(con) -> int:
    con.execute("DELETE FROM doc_bom_links")
    con.execute("DELETE FROM link_decisions")
    covered = load_curated(con)
    fuzzy(con, skip=covered)
    return con.execute("SELECT COUNT(*) FROM doc_bom_links").fetchone()[0]
