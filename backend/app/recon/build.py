"""Build orbitable 3D reconstructions from dimensions read off a 2D drawing.

Each part has a spec in data/recon_specs/<DOC_ID>.json. The spec records every dimension
used and where on the drawing it came from, so the 3D can be traced back to evidence.
Supported shapes (enough for the simple plates/rings in this corpus):

  {"document_id": "D-0xx", "units": "mm",
   "shape": "plate",  "outline": {"rect": [w, h]} | {"polygon": [[x,y],...]}, "thickness": t,
   "holes": [{"x": .., "y": .., "d": ..}, ...],
   "evidence": [{"dim": "width", "value": 120, "page": 1, "note": "front view, overall"}]}

  {"shape": "ring", "outer_d": .., "inner_d": .., "thickness": .., "holes": [...]}

Files starting with "_" are examples and are not registered.

    python -m app.recon.build             # build all specs -> data/models/*.glb
"""
import json

import trimesh
from shapely.geometry import Point, Polygon, box

from ..config import MODELS_DIR, RECON_SPECS, ROOT

METHOD = "extruded-profile-v1"


def profile(spec: dict) -> Polygon:
    if spec["shape"] == "plate":
        o = spec["outline"]
        if "rect" in o:
            w, h = o["rect"]
            poly = box(0, 0, w, h)
        else:
            poly = Polygon(o["polygon"])
    elif spec["shape"] == "ring":
        poly = Point(0, 0).buffer(spec["outer_d"] / 2, quad_segs=32).difference(
            Point(0, 0).buffer(spec["inner_d"] / 2, quad_segs=32))
    else:
        raise ValueError(f"unsupported shape {spec['shape']!r}")
    for h in spec.get("holes", []):
        poly = poly.difference(Point(h["x"], h["y"]).buffer(h["d"] / 2, quad_segs=16))
    return poly


def build_mesh(spec: dict) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(profile(spec), height=spec["thickness"])
    mesh.apply_translation(-mesh.bounds.mean(axis=0))  # centre for orbiting
    return mesh


def build_all(con=None) -> list[str]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    built = []
    for path in sorted(RECON_SPECS.glob("*.json")):
        if path.name.startswith("_"):
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        out = MODELS_DIR / f"{spec['document_id']}.glb"
        build_mesh(spec).export(out)
        built.append(spec["document_id"])
        if con is not None:
            _register(con, spec, out)
    return built


def _register(con, spec: dict, out) -> None:
    con.execute(
        "INSERT OR REPLACE INTO models3d (document_id, path, method, spec_json) VALUES (?,?,?,?)",
        (spec["document_id"], out.relative_to(ROOT).as_posix(), METHOD, json.dumps(spec)))


def register_existing(con) -> int:
    """Called by ingest: register specs whose .glb is already built (committed)."""
    n = 0
    for path in sorted(RECON_SPECS.glob("*.json")) if RECON_SPECS.exists() else []:
        if path.name.startswith("_"):
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        out = MODELS_DIR / f"{spec['document_id']}.glb"
        if not out.exists():
            build_mesh(spec).export(out)
        _register(con, spec, out)
        n += 1
    return n


if __name__ == "__main__":
    print("built:", build_all())
