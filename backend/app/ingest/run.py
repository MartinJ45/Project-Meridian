"""Rebuild data/meridian.db from the dataset and committed extraction output.

    python -m app.ingest.run            # from backend/
    python -m app.ingest.run --force    # also re-run the PDF text pass

Accepted corrections are re-applied from data/corrections.jsonl so a rebuild never loses
reviewed knowledge.
"""
import argparse
import time

from ..config import DB_PATH
from ..db import connect, init_db
from . import bom, drawings, interfaces, link, manifest
from .. import consistency, knowledge
from ..recon import build as recon_build


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-extract PDF text even if JSON exists")
    args = ap.parse_args()

    if DB_PATH.exists():
        DB_PATH.unlink()
    con = connect()
    init_db(con)
    t = time.time()
    print(f"documents:        {manifest.load_documents(con)}")
    print(f"bom rows:         {bom.load_bom(con)}")
    print(f"drawings parsed:  {drawings.run(con, force=args.force)}")
    print(f"doc-bom links:    {link.run(con)}")
    print(f"interfaces:       {interfaces.run(con)}")
    print(f"3D models:        {recon_build.register_existing(con)}")
    print(f"corrections:      {knowledge.replay_corrections(con)}")
    # after corrections, so checks reflect the active (possibly corrected) values
    print(f"consistency:      {consistency.run(con)}")
    con.commit()
    print(f"done in {time.time() - t:.1f}s -> {DB_PATH}")


if __name__ == "__main__":
    main()
