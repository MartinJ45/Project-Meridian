"""Evaluate chat quality, latency, cost and reproducibility; run the correction before/after demo.

    python -m app.evaluate                    # all cases, 2 repeats, + correction demo
    python -m app.evaluate --repeats 1 --only mat-shared dims
    python -m app.evaluate --no-correction

Runs against a fresh knowledge base built in a temp folder from the committed dataset and
extraction output, with an empty correction journal, so results do not depend on local edits.
Writes data/eval/results/<timestamp>.json and data/eval/REPORT.md.
"""
import argparse
import json
import re
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, consistency, metrics
from . import knowledge as kb
from .chat.agent import run_turn
from .db import connect, init_db
from .ingest import bom, drawings, interfaces, link, manifest
from .recon import build as recon_build

EVAL_DIR = config.DATA / "eval"
QUESTIONS = EVAL_DIR / "questions.json"


# ------------------------------------------------------------------ fresh knowledge base

def build_fresh_db(path: Path):
    con = connect(path)
    init_db(con)
    manifest.load_documents(con)
    bom.load_bom(con)
    drawings.run(con)
    link.run(con)
    interfaces.run(con)
    recon_build.register_existing(con)
    consistency.run(con)
    con.commit()
    return con


# ------------------------------------------------------------------ scoring

def _match(text: str, alt: str) -> bool:
    if alt.startswith("re:"):
        return re.search(alt[3:], text, re.I) is not None
    return alt.lower() in text.lower()


def score(case: dict, result: dict) -> dict:
    text = result["reply"]
    opened = {a["document_id"] for a in result["attachments"] if a["type"] == "drawing"}
    opened3d = {a["document_id"] for a in result["attachments"] if a["type"] == "model3d"}
    checks = []
    for group in case.get("all_of", []):
        checks.append({"check": f"mentions {' | '.join(group)}", "ok": any(_match(text, a) for a in group)})
    for bad in case.get("none_of", []):
        checks.append({"check": f"does not mention {bad}", "ok": not _match(text, bad)})
    for d in case.get("open", []):
        checks.append({"check": f"opens {d}", "ok": d in opened})
    for d in case.get("open_3d", []):
        checks.append({"check": f"opens 3D {d}", "ok": d in opened3d})
    if case.get("open_none"):
        checks.append({"check": "opens no drawing", "ok": not opened})
    if case.get("open_graph"):
        checks.append({"check": "offers the knowledge graph", "ok": any(a["type"] == "graph" for a in result["attachments"])})
    exp = case.get("expect_correction")
    if exp:
        filed = [c for c in result.get("_corrections", []) if c["predicate"] == exp["predicate"]
                 and str(c["subject_id"]) == exp["subject_id"] and str(c["new_value"]).replace(" ", "") == exp["new_value"]]
        checks.append({"check": f"files {exp['predicate']} correction {exp['subject_id']} -> {exp['new_value']}", "ok": bool(filed)})
    if result["mode"] != "online":
        checks.append({"check": "answered online (not fallback)", "ok": False})
    return {"passed": all(c["ok"] for c in checks), "checks": checks,
            "opened": sorted(opened), "opened_3d": sorted(opened3d)}


def run_case(con, case: dict) -> dict:
    messages = []
    result = None
    before = {c["id"] for c in kb.list_corrections(con)}
    for turn in case["turns"]:
        messages.append({"role": "user", "content": turn})
        result = run_turn(con, messages)
        messages.append({"role": "assistant", "content": result["reply"]})
    result["_corrections"] = [c for c in kb.list_corrections(con) if c["id"] not in before]
    for c in result["_corrections"]:  # keep cases independent: discard anything a case proposed
        kb.review_correction(con, c["id"], False, "eval cleanup", journal=False)
    attempts = result["_internal"]["attempts"]
    ok = next((a for a in attempts if a.get("ok")), {})
    return {
        "reply": result["reply"], "mode": result["mode"], "latency_ms": result["latency_ms"],
        "attachments": result["attachments"], "model": ok.get("model"),
        "fallbacks": sum(1 for a in attempts if not a.get("ok")),
        "tokens": {k: ok.get(k) for k in ("prompt_tokens", "thinking_tokens", "output_tokens")},
        "score": score(case, result),
    }


# ------------------------------------------------------------------ correction before/after

CORRECTION_SCENARIO = {
    "question": "How many Galvo box brackets does the BOM record for BOM row 81?",
    "proposal": "The amount for BOM row 81 (Galvo box bracket) is wrong: drawing D-018 says x2, so it should be 2.",
}


def correction_demo(con, journal: Path) -> dict:
    kb.JOURNAL = journal  # keep the demo out of the real journal
    steps = {}
    q = [{"role": "user", "content": CORRECTION_SCENARIO["question"]}]
    steps["before"] = run_turn(con, q)
    steps["consistency_before"] = consistency.for_row(con, 81)
    steps["proposal"] = run_turn(con, [{"role": "user", "content": CORRECTION_SCENARIO["proposal"]}])
    pending = kb.list_corrections(con, "pending")
    steps["correction"] = pending[0] if pending else None
    if pending:
        steps["review"] = kb.review_correction(con, pending[0]["id"], True, "Checked against D-018 (x2).")
    steps["after"] = run_turn(con, q)
    steps["consistency_after"] = consistency.for_row(con, 81)
    steps["facts_after"] = [f for f in kb.facts_for(con, "bom_row", "81") if f["predicate"] == "amount"]
    steps["audit"] = kb.audit_log(con)[:5]
    before, after = steps["before"]["reply"], steps["after"]["reply"]
    steps["verdict"] = {
        "correction_filed": bool(pending),
        "drawing_check_ran": bool(pending) and any(c["name"] == "drawing evidence"
                                                   for c in pending[0]["check_report"]["checks"]),
        "answer_changed": before != after and bool(re.search(r"\b2\b", after)),
        "original_kept": any(f["status"] == "superseded" and f["value"] == "1" for f in steps["facts_after"]),
        "quantity_conflict_resolved": any(c["field"] == "quantity" and c["verdict"] == "conflict" for c in steps["consistency_before"])
        and not any(c["field"] == "quantity" and c["verdict"] == "conflict" for c in steps["consistency_after"]),
    }
    for k in ("before", "proposal", "after"):
        steps[k] = {"reply": steps[k]["reply"], "latency_ms": steps[k]["latency_ms"], "mode": steps[k]["mode"]}
    return steps


# ------------------------------------------------------------------ report

def write_report(run: dict) -> Path:
    cases = run["cases"]
    lat = [r["latency_ms"] for c in cases for r in c["runs"]]
    tok_in = [r["tokens"]["prompt_tokens"] or 0 for c in cases for r in c["runs"]]
    tok_out = [(r["tokens"]["output_tokens"] or 0) + (r["tokens"]["thinking_tokens"] or 0) for c in cases for r in c["runs"]]
    passes = [r["score"]["passed"] for c in cases for r in c["runs"]]
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).extend(r["score"]["passed"] for r in c["runs"])
    stable = [len({r["score"]["passed"] for r in c["runs"]}) == 1 and len({tuple(r["score"]["opened"]) for r in c["runs"]}) == 1
              for c in cases if len(c["runs"]) > 1]
    models = sorted({r["model"] for c in cases for r in c["runs"] if r["model"]})
    lines = [
        "# Evaluation report", "",
        f"Run {run['started']} · {len(cases)} cases × {run['repeats']} repeat(s) · models answering: {', '.join(models) or '-'}",
        "Fresh knowledge base built from the committed dataset and extraction output; empty correction journal.", "",
        "## Summary", "",
        "| Metric | Value |", "|---|---|",
        f"| Pass rate (all checks in a case) | {sum(passes)}/{len(passes)} ({100 * sum(passes) / max(1, len(passes)):.0f}%) |",
        f"| Reproducibility (same pass/fail and same drawings opened across repeats) | {sum(stable)}/{len(stable)} cases |" if stable else "| Reproducibility | n/a (1 repeat) |",
        f"| Latency median / p90 / max | {statistics.median(lat) / 1000:.1f} s / {sorted(lat)[int(0.9 * (len(lat) - 1))] / 1000:.1f} s / {max(lat) / 1000:.1f} s |",
        f"| Tokens per turn (median) | {statistics.median(tok_in):.0f} in / {statistics.median(tok_out):.0f} out incl. thinking |",
        f"| Turns needing a fallback model | {sum(1 for c in cases for r in c['runs'] if r['fallbacks'])} |", "",
        "## By category", "", "| Category | Passed |", "|---|---|",
        *[f"| {k} | {sum(v)}/{len(v)} |" for k, v in sorted(by_cat.items())], "",
        "## Cases", "",
    ]
    for c in cases:
        r = c["runs"][0]
        status = "PASS" if all(x["score"]["passed"] for x in c["runs"]) else (
            "FAIL" if not any(x["score"]["passed"] for x in c["runs"]) else "FLAKY")
        lines += [f"### {c['id']} ({c['category']}) - {status}", "",
                  *[f"> {t}" for t in c["turns"]], "",
                  f"Opened: {', '.join(r['score']['opened']) or '-'}; 3D: {', '.join(r['score']['opened_3d']) or '-'}; "
                  f"{r['latency_ms'] / 1000:.1f} s", ""]
        failed = [x["check"] for x in r["score"]["checks"] if not x["ok"]]
        if failed:
            lines += ["Failed checks (first run): " + "; ".join(failed), ""]
        lines += ["<details><summary>Answer (first run)</summary>", "", r["reply"], "", "</details>", ""]
    demo = run.get("correction_demo")
    if demo:
        lines += ["## Correction before/after", "",
                  f"Question: *{CORRECTION_SCENARIO['question']}*", "",
                  "**Before**", "", demo["before"]["reply"], "",
                  f"**Proposal in chat:** *{CORRECTION_SCENARIO['proposal']}*", "", demo["proposal"]["reply"], ""]
        if demo.get("correction"):
            lines += ["**Automated checks shown to the reviewer**", ""]
            lines += [f"- {'✓' if k['ok'] else '!'} {k['name']}: {k['detail']}" for k in demo["correction"]["check_report"]["checks"]]
            lines += ["", f"**Reviewer accepted** correction #{demo['correction']['id']}.", ""]
        lines += ["**After**", "", demo["after"]["reply"], "", "**Outcome**", ""]
        lines += [f"- {k.replace('_', ' ')}: {'yes' if v else 'NO'}" for k, v in demo["verdict"].items()]
        lines += ["", "Facts for BOM row 81 `amount` after acceptance:", ""]
        lines += [f"- {f['value']} [{f['source_ref']}] {f['status']}" for f in demo["facts_after"]]
    out = EVAL_DIR / "REPORT.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-correction", action="store_true")
    args = ap.parse_args()
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set; the evaluation measures the online assistant.")

    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    tmp = Path(tempfile.mkdtemp(prefix="meridian-eval-"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kb.JOURNAL = tmp / "journal.jsonl"  # any correction proposed during the eval stays out of the real journal
    metrics.HISTORY = tmp / "metrics_history.jsonl"  # ...and out of the real knowledge-health history
    try:
        con = build_fresh_db(tmp / "eval.db")
        results = []
        for c in cases:
            runs = []
            for i in range(args.repeats):
                r = run_case(con, c)
                runs.append(r)
                print(f"{c['id']:<16} run {i + 1}: {'PASS' if r['score']['passed'] else 'FAIL'} "
                      f"{r['latency_ms'] / 1000:5.1f}s  opened={r['score']['opened']}"
                      + ("" if r["score"]["passed"] else
                         "  failed: " + "; ".join(x["check"] for x in r["score"]["checks"] if not x["ok"])), flush=True)
            results.append({**c, "runs": runs})
        run = {"started": started, "repeats": args.repeats, "cases": results}
        if not args.no_correction:
            print("correction demo ...", flush=True)
            run["correction_demo"] = correction_demo(con, tmp / "journal.jsonl")
            print("  ", run["correction_demo"]["verdict"], flush=True)
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (EVAL_DIR / "results").mkdir(parents=True, exist_ok=True)
    stamp = started.replace(":", "").replace("-", "")[:15]
    (EVAL_DIR / "results" / f"{stamp}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("report:", write_report(run))


if __name__ == "__main__":
    main()
