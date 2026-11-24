"""Knowledge graph assembled from the extracted, sourced knowledge (no new claims).

Nodes: subsystem (drawing folders), family (BOM part family), drawing, part (BOM row), material
(class), supplier (as recorded in the BOM). Every edge says where it comes from:

  drawing  -in_subsystem->  subsystem     manifest
  part     -in_family->     family        BOM 'Part family'
  family   -mostly_in->     subsystem     derived: subsystems of drawings linked to the family's parts
  drawing  -depicts->       part          reviewed link (confirmed/probable), consistency verdicts attached
  part     -interfaces->    part          BOM 'Interface with'
  drawing  -specifies->     material      title block MATERIAL/NOTE (vision pass)
  part     -records->       material      BOM 'Material' (active value, incl. accepted corrections)
  part     -supplied_by->   supplier      BOM 'Supplier' (pinned snapshot)
"""
from collections import Counter

from . import consistency


def _active(con, subject_type, predicate) -> dict:
    return {r["subject_id"]: r["value"] for r in con.execute(
        "SELECT subject_id, value FROM facts WHERE subject_type=? AND predicate=? AND status='active' AND value IS NOT NULL",
        (subject_type, predicate))}


def build(con) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, kind, label, **data):
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, **data})

    def edge(src, dst, rel, source, **data):
        edges.append({"id": f"{src}|{rel}|{dst}", "source": src, "target": dst, "rel": rel, "basis": source, **data})

    # drawings and subsystems
    sheet_title = _active(con, "document", "title")
    for d in con.execute("""SELECT d.id, d.title, d.subsystem, d.distribution,
                                   EXISTS(SELECT 1 FROM models3d m WHERE m.document_id=d.id) AS has_model,
                                   (SELECT status FROM link_decisions l WHERE l.document_id=d.id) AS link_status
                            FROM documents d"""):
        node(f"sub:{d['subsystem']}", "subsystem", d["subsystem"])
        node(f"doc:{d['id']}", "drawing", f"{d['id']} {sheet_title.get(d['id']) or d['title']}",
             doc_id=d["id"], degraded=d["distribution"] == "degraded-only", has_model=bool(d["has_model"]),
             link_status=d["link_status"] or "not reviewed")
        edge(f"doc:{d['id']}", f"sub:{d['subsystem']}", "in_subsystem", "manifest")

    # parts, families, suppliers, BOM materials
    family = _active(con, "bom_row", "part_family")
    supplier = _active(con, "bom_row", "supplier")
    material = _active(con, "bom_row", "material")
    ptype = _active(con, "bom_row", "type")
    linked_rows = {r[0] for r in con.execute(
        "SELECT row_index FROM doc_bom_links WHERE method IN ('curated','correction') AND status IN ('confirmed','probable')")}
    iface_rows = {r[0] for r in con.execute("SELECT from_row FROM interfaces UNION SELECT to_row FROM interfaces WHERE to_row IS NOT NULL")}
    for r in con.execute("SELECT row_index, name FROM bom_rows WHERE name IS NOT NULL"):
        rid = str(r["row_index"])
        node(f"row:{rid}", "part", r["name"], row=r["row_index"], type=ptype.get(rid), family=family.get(rid),
             has_drawing=r["row_index"] in linked_rows, has_interfaces=r["row_index"] in iface_rows)
        if family.get(rid):
            node(f"fam:{family[rid]}", "family", family[rid])
            edge(f"row:{rid}", f"fam:{family[rid]}", "in_family", f"BOM row {rid}")
        if supplier.get(rid):
            node(f"sup:{supplier[rid]}", "supplier", supplier[rid])
            edge(f"row:{rid}", f"sup:{supplier[rid]}", "supplied_by", f"BOM row {rid} (pinned snapshot)")
        for cls in sorted(consistency.material_classes(material.get(rid))):
            node(f"mat:{cls}", "material", cls)
            edge(f"row:{rid}", f"mat:{cls}", "records", f"BOM row {rid}: {material[rid]!r}")

    # drawing materials (title block, else note)
    for (doc_id,) in con.execute("SELECT id FROM documents"):
        text, ref = consistency.drawing_material(con, doc_id)
        for cls in sorted(consistency.material_classes(text)):
            node(f"mat:{cls}", "material", cls)
            edge(f"doc:{doc_id}", f"mat:{cls}", "specifies", ref)

    # reviewed drawing <-> part links, with consistency verdicts
    verdicts: dict[tuple, list] = {}
    for c in con.execute("SELECT document_id, row_index, field, verdict, detail FROM consistency_checks"):
        verdicts.setdefault((c["document_id"], c["row_index"]), []).append(
            {"field": c["field"], "verdict": c["verdict"], "detail": c["detail"]})
    fam_subs: dict[str, Counter] = {}
    for l in con.execute("""SELECT l.document_id, l.row_index, l.status, l.method, d.subsystem FROM doc_bom_links l
                            JOIN documents d ON d.id = l.document_id
                            WHERE l.method IN ('curated','correction') AND l.status IN ('confirmed','probable')"""):
        v = verdicts.get((l["document_id"], l["row_index"]), [])
        edge(f"doc:{l['document_id']}", f"row:{l['row_index']}", "depicts",
             f"reviewed link ({l['status']}{', via correction' if l['method'] == 'correction' else ''})",
             status=l["status"], conflict=any(x["verdict"] == "conflict" for x in v), checks=v)
        fam = family.get(str(l["row_index"]))
        if fam:
            fam_subs.setdefault(fam, Counter())[l["subsystem"]] += 1
    for fam, subs in fam_subs.items():
        sub, n = subs.most_common(1)[0]
        edge(f"fam:{fam}", f"sub:{sub}", "mostly_in",
             f"derived: {n} linked drawing(s) of this family are in {sub}", count=n)

    # interfaces
    for i in con.execute("SELECT from_row, to_row, to_name FROM interfaces WHERE to_row IS NOT NULL"):
        edge(f"row:{i['from_row']}", f"row:{i['to_row']}", "interfaces", f"BOM row {i['from_row']} 'Interface with': {i['to_name']}")

    # degree, for sizing and filtering
    deg = Counter()
    for e in edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    for n in nodes.values():
        n["degree"] = deg[n["id"]]
    return {"nodes": list(nodes.values()), "edges": edges,
            "counts": dict(Counter(n["kind"] for n in nodes.values())) | {"edges": len(edges)}}


def neighbourhood(graph: dict, focus: str, depth: int = 1) -> set[str]:
    adj: dict[str, set] = {}
    for e in graph["edges"]:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])
    seen, frontier = {focus}, {focus}
    for _ in range(depth):
        frontier = {m for n in frontier for m in adj.get(n, ())} - seen
        seen |= frontier
    return seen


def resolve(con, ref: str | None) -> str | None:
    """Turn a chat reference ('D-018', 'row 81', 'aluminium', 'Box') into a node id."""
    if not ref:
        return None
    ref = ref.strip()
    import re
    if re.fullmatch(r"(?i)d-\d{3}", ref):
        return f"doc:{ref.upper()}"
    m = re.fullmatch(r"(?i)(?:row[:\s]*|bom row\s*)?(\d{1,3})", ref)
    if m:
        return f"row:{int(m.group(1))}"
    if ":" in ref and ref.split(":")[0] in ("doc", "row", "sub", "fam", "mat", "sup"):
        return ref
    cls = consistency.material_classes(ref)
    if cls:
        return f"mat:{sorted(cls)[0]}"
    for prefix, sql in (("sub", "SELECT DISTINCT subsystem FROM documents"),):
        for (s,) in con.execute(sql):
            if s.lower() == ref.lower():
                return f"{prefix}:{s}"
    return None
