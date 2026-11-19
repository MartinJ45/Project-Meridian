"""Propose drawing <-> BOM row links. These are candidates with a score, not facts."""
import re

from rapidfuzz import fuzz, process

# Upstream filename noise that is not part of the part name
NOISE = re.compile(r"\b(x\d+|v\d+|version\s*\d+|loop\s*\d+)\b", re.I)


def normalise(s: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s or "")
    s = NOISE.sub(" ", s.replace("_", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


def run(con, min_score: float = 70, top_k: int = 3) -> int:
    con.execute("DELETE FROM doc_bom_links WHERE method = 'filename-fuzzy'")
    bom = [dict(r) for r in con.execute("SELECT row_index, name, part_family FROM bom_rows WHERE name IS NOT NULL")]
    choices = {b["row_index"]: normalise(b["name"]) for b in bom}
    family = {b["row_index"]: (b["part_family"] or "").lower() for b in bom}
    n = 0
    for d in con.execute("SELECT id, title, subsystem FROM documents").fetchall():
        hits = process.extract(normalise(d["title"]), choices, scorer=fuzz.token_set_ratio, limit=top_k * 3)
        ranked = []
        for _, score, row_index in hits:
            # small bonus when the BOM family matches the drawing's subsystem
            if family[row_index] and family[row_index] == (d["subsystem"] or "").lower():
                score += 5
            if score >= min_score:
                ranked.append((score, row_index))
        for score, row_index in sorted(ranked, reverse=True)[:top_k]:
            con.execute(
                "INSERT OR REPLACE INTO doc_bom_links (document_id, row_index, score, method, status) VALUES (?,?,?,?, 'candidate')",
                (d["id"], row_index, min(score, 100), "filename-fuzzy"),
            )
            n += 1
    return n
