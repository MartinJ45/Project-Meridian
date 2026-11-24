"""Turn the BOM's free-text 'Interface with' column into followable edges.

Each comma-separated name is resolved to a BOM row by exact (case-insensitive) name, then by
fuzzy match within the same part family, then anywhere. Unresolved names are kept with
to_row = NULL so nothing in the source text is lost.
"""
from rapidfuzz import fuzz, process

MIN_SCORE = 85


def run(con) -> int:
    con.execute("DELETE FROM interfaces")
    rows = [dict(r) for r in con.execute("SELECT row_index, name, part_family, interface_with FROM bom_rows")]
    by_name = {}
    for r in rows:
        by_name.setdefault((r["name"] or "").strip().lower(), []).append(r["row_index"])
    names = {r["row_index"]: r["name"] or "" for r in rows}
    family = {r["row_index"]: r["part_family"] for r in rows}
    n = 0
    for r in rows:
        if not r["interface_with"]:
            continue
        for raw in r["interface_with"].split(","):
            name = raw.strip()
            if not name:
                continue
            target, score = None, None
            exact = by_name.get(name.lower())
            if exact:
                target, score = exact[0], 100.0
            else:
                same_family = {k: v for k, v in names.items() if family[k] == r["part_family"]}
                for pool in (same_family, names):
                    hit = process.extractOne(name, pool, scorer=fuzz.WRatio)
                    if hit and hit[1] >= MIN_SCORE:
                        target, score = hit[2], round(hit[1], 1)
                        break
            con.execute("INSERT OR REPLACE INTO interfaces (from_row, to_row, to_name, match_score) VALUES (?,?,?,?)",
                        (r["row_index"], target, name, score))
            n += 1
    return n


def for_row(con, row_index: int) -> dict:
    out = [dict(x) for x in con.execute(
        """SELECT i.to_row AS row_index, i.to_name AS name_in_bom, i.match_score, b.part_family
           FROM interfaces i LEFT JOIN bom_rows b ON b.row_index = i.to_row WHERE i.from_row = ?""", (row_index,))]
    inc = [dict(x) for x in con.execute(
        """SELECT i.from_row AS row_index, b.name, b.part_family FROM interfaces i
           JOIN bom_rows b ON b.row_index = i.from_row WHERE i.to_row = ?""", (row_index,))]
    return {"interfaces_with": out, "referenced_by": inc}
