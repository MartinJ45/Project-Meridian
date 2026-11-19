"""Load the drawing inventory from dataset/manifest.json."""
import json
import re
from pathlib import PurePosixPath

from ..config import MANIFEST


def title_from_source(source_path: str) -> str:
    """'CAD/Technical Drawings/Box/Door_x2.PDF' -> 'Door x2'. Keeps the upstream name recognisable."""
    stem = PurePosixPath(source_path).stem
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)  # camelCase -> words
    return stem.replace("_", " ").strip()


def load_documents(con) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n = 0
    for a in manifest["assets"]:
        if not a["id"].startswith("D-"):
            continue
        con.execute(
            """INSERT OR REPLACE INTO documents
               (id, path, subsystem, distribution, role, source_path, source_url, title, pages, sha256, derivation)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                a["id"], a["path"], a.get("subsystem"), a.get("distribution"), a.get("role"),
                a.get("source_path"), a.get("source_url"), title_from_source(a.get("source_path", a["id"])),
                a.get("pages"), a.get("sha256"),
                json.dumps(a["derivation"]) if a.get("derivation") else None,
            ),
        )
        n += 1
    return n
