"""Load the pinned BOM snapshot. Raw rows are stored verbatim; facts are derived from them."""
import csv
import json
import re

from ..config import BOM_CSV

COLUMNS = {
    "Name": "name",
    "Part family": "part_family",
    "Type": "type",
    "Design": "design",
    "Order": "order_state",
    "V&V": "vv",
    "Notes": "notes",
    "Design Intend": "design_intent",  # sic, upstream spelling
    "Material": "material",
    "Product name": "product_name",
    "Supplier Order": "supplier_order",
    "Interface with": "interface_with",
    "Link": "link",
    "Supplier": "supplier",
    "Datasheet": "datasheet",
    "Amount": "amount",
    "Cost": "cost_raw",
    "Total cost": "total_cost_raw",
}

# BOM columns that become facts (predicate name -> column)
FACT_PREDICATES = {
    "part_family": "part_family",
    "type": "type",
    "material": "material",
    "supplier": "supplier",
    "supplier_order": "supplier_order",
    "supplier_link": "link",
    "amount": "amount",
    "cost_dkk": "cost_raw",
    "total_cost_dkk": "total_cost_raw",
    "design_state": "design",
    "order_state": "order_state",
    "vv_state": "vv",
    "interface_with": "interface_with",
    "design_intent": "design_intent",
    "notes": "notes",
}


def parse_dkk(raw: str | None) -> str | None:
    """'DKK1,234.50' -> '1234.50'. Returns None when unparseable so the raw value stays the evidence."""
    if not raw:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", raw)
    return m.group(0).replace(",", "") if m else None


def load_bom(con) -> int:
    n = 0
    with BOM_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for line_no, raw in enumerate(reader, start=2):  # header is line 1
            row = {col: (raw.get(src) or "").strip() or None for src, col in COLUMNS.items()}
            con.execute(
                f"INSERT OR REPLACE INTO bom_rows (row_index, {', '.join(row)}, raw_json) "
                f"VALUES (?, {', '.join('?' for _ in row)}, ?)",
                (line_no, *row.values(), json.dumps(raw, ensure_ascii=False)),
            )
            for pred, col in FACT_PREDICATES.items():
                value = row[col]
                if pred in ("cost_dkk", "total_cost_dkk"):
                    value = parse_dkk(value) if value else None
                if value:
                    con.execute(
                        """INSERT INTO facts (subject_type, subject_id, predicate, value, source_type, source_ref, confidence)
                           VALUES ('bom_row', ?, ?, ?, 'bom', ?, 1.0)""",
                        (str(line_no), pred, value, f"BOM row {line_no}"),
                    )
            n += 1
    return n
