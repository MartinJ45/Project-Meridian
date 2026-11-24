"""Knowledge-health metrics and their history, to show whether reviewed changes improve the system.

snapshot()  current state: link review status, drawing/BOM conflicts and gaps, extraction verification,
            corrections by status and type.
record()    appends a snapshot to data/metrics_history.jsonl (local) after every accepted correction and
            every ingested drawing, so the Review page can show the trend.
eval_runs() pass rate / latency of each saved evaluation run (data/eval/results/*.json).
"""
import json
import statistics
from datetime import datetime, timezone

from .config import DATA

HISTORY = DATA / "metrics_history.jsonl"
EVAL_RESULTS = DATA / "eval" / "results"


def snapshot(con) -> dict:
    q = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    links = dict(con.execute("SELECT status, COUNT(*) FROM link_decisions GROUP BY status").fetchall())
    verdicts = dict(con.execute("SELECT verdict, COUNT(*) FROM consistency_checks GROUP BY verdict").fetchall())
    corr = [dict(r) for r in con.execute(
        "SELECT status, predicate, proposed_via, COUNT(*) AS n FROM corrections GROUP BY 1, 2, 3")]
    drawing_facts = q("SELECT COUNT(*) FROM facts WHERE source_type='drawing' AND value IS NOT NULL")
    verified = q("""SELECT COUNT(*) FROM facts WHERE source_type='drawing' AND value IS NOT NULL
                    AND json_extract(evidence, '$.check') IN ('text_layer_match','repeat_read_agrees')""")
    return {
        "drawings": q("SELECT COUNT(*) FROM documents"),
        "uploaded_drawings": q("SELECT COUNT(*) FROM documents WHERE distribution='uploaded'"),
        "links": {"confirmed": links.get("confirmed", 0), "probable": links.get("probable", 0),
                  "none": links.get("none", 0),
                  "not_reviewed": q("SELECT COUNT(*) FROM documents WHERE id NOT IN (SELECT document_id FROM link_decisions)")},
        "consistency": {"conflicts": verdicts.get("conflict", 0),
                        "missing": verdicts.get("missing_on_drawing", 0) + verdicts.get("missing_in_bom", 0),
                        "agree": verdicts.get("agree", 0) + verdicts.get("drawing_more_specific", 0)},
        "extraction": {"drawing_fields": drawing_facts, "independently_verified": verified},
        "corrections": {
            "pending": sum(c["n"] for c in corr if c["status"] == "pending"),
            "accepted": sum(c["n"] for c in corr if c["status"] == "accepted"),
            "rejected": sum(c["n"] for c in corr if c["status"] == "rejected"),
            "accepted_by_type": _by(corr, "accepted"),
        },
    }


def _by(corr, status):
    out = {}
    for c in corr:
        if c["status"] == status:
            kind = "link" if c["predicate"] == "bom_link" else c["predicate"]
            out[kind] = out.get(kind, 0) + c["n"]
    return out


def record(con, event: str) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
                            **snapshot(con)}) + "\n")


def history(limit: int = 200) -> list[dict]:
    if not HISTORY.exists():
        return []
    lines = [l for l in HISTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines[-limit:]]


def eval_runs() -> list[dict]:
    out = []
    for f in sorted(EVAL_RESULTS.glob("*.json")) if EVAL_RESULTS.exists() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        runs = [x for c in r["cases"] for x in c["runs"]]
        if not runs:
            continue
        out.append({
            "started": r["started"], "cases": len(r["cases"]), "repeats": r["repeats"],
            "passed": sum(x["score"]["passed"] for x in runs), "total": len(runs),
            "median_latency_s": round(statistics.median(x["latency_ms"] for x in runs) / 1000, 1),
            "correction_demo_ok": all(r.get("correction_demo", {}).get("verdict", {}).values()) if r.get("correction_demo") else None,
        })
    return out
