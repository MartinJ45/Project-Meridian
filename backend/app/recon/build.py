"""Build orbitable 3D reconstructions from dimensions read off a 2D drawing.

Each part has a spec in data/recon_specs/<DOC_ID>.json that records every dimension used
and where on the drawing it was read, so the 3D traces back to evidence. Geometry is an
extruded 2D profile (outline minus through-holes) with optional 3D features cut by boolean
subtraction. Coordinates are in the profile plane (x, y); z runs through the thickness,
z = 0 is the "bottom" face and z = thickness the "top" face.

  {"document_id": "D-0xx", "units": "mm", "thickness": t,
   "profile": {"rect": [w, h]} | {"polygon": [[x, y], ...]} | {"annulus": {"outer_d": D, "inner_d": d}},
   "holes": [{"x": .., "y": .., "d": ..},                                   # through-holes
             {"polar": {"count": n, "radius": r, "start_deg": a, "cx": 0, "cy": 0}, "d": ..}],
   "features": [
     {"type": "countersink", "at": <hole positions>, "d": D_outer, "face": "top"|"bottom"},   # 90 deg
     {"type": "counterbore", "at": <hole positions>, "d": D, "depth": h, "face": "top"|"bottom"},
     {"type": "side_hole", "axis": "x"|"y", "d": d, "pos": [p, z]}  # through the full part along axis;
                                                                     # pos = (other in-plane coord, z)
   ],
   "mass_check": {"density_g_cm3": 2.70, "drawing_weight_g": 117.3, "source": "title block"},
   "evidence": [{"dim": "...", "value": .., "page": 1, "view": "...", "note": "..."}],
   "assumptions": ["..."]}

<hole positions> is either a list of [x, y] or {"polar": {...}} as above.
Files starting with "_" are examples and are not registered.

    python -m app.recon.build             # build all specs -> data/models/*.glb, print checks
"""
import json
import math

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon, box

from ..config import MODELS_DIR, RECON_SPECS, ROOT

METHOD = "extruded-profile-v2 (+boolean features)"
EPS = 0.01  # mm; keeps cutting tools from sharing faces with the part


def _positions(at) -> list[tuple[float, float]]:
    if isinstance(at, dict) and "polar" in at:
        p = at["polar"]
        step = p.get("step_deg", 360.0 / p["count"])
        return [(p.get("cx", 0) + p["radius"] * math.cos(math.radians(p.get("start_deg", 0) + i * step)),
                 p.get("cy", 0) + p["radius"] * math.sin(math.radians(p.get("start_deg", 0) + i * step)))
                for i in range(p["count"])]
    return [tuple(xy) for xy in at]


def _hole_list(spec) -> list[tuple[float, float, float]]:
    out = []
    for h in spec.get("holes", []):
        pts = _positions(h) if "polar" in h else [(h["x"], h["y"])]
        out += [(x, y, h["d"]) for x, y in pts]
    return out


def profile(spec: dict) -> Polygon:
    p = spec.get("profile") or spec.get("outline")  # "outline" kept for the v1 example format
    if spec.get("shape") == "ring" and not p:
        p = {"annulus": {"outer_d": spec["outer_d"], "inner_d": spec["inner_d"]}}
    if "rect" in p:
        poly = box(0, 0, *p["rect"])
    elif "polygon" in p:
        poly = Polygon(p["polygon"])
    elif "annulus" in p:
        a = p["annulus"]
        poly = Point(0, 0).buffer(a["outer_d"] / 2, quad_segs=64).difference(
            Point(0, 0).buffer(a["inner_d"] / 2, quad_segs=64))
    else:
        raise ValueError(f"unsupported profile {p!r}")
    for x, y, d in _hole_list(spec):
        poly = poly.difference(Point(x, y).buffer(d / 2, quad_segs=24))
    return poly


def _cylinder(d, length, sections=48):
    return trimesh.creation.cylinder(radius=d / 2, height=length, sections=sections)


def _tools(spec: dict, bounds) -> list[trimesh.Trimesh]:
    t = spec["thickness"]
    (xmin, ymin, _), (xmax, ymax, _) = bounds
    tools = []
    for f in spec.get("features", []):
        kind = f["type"]
        if kind == "countersink":
            r = f["d"] / 2
            for x, y in _positions(f["at"]):
                cone = trimesh.creation.cone(radius=r + EPS, height=r + EPS, sections=48)  # 90 deg included angle
                if f.get("face", "top") == "top":
                    cone.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
                    cone.apply_translation([x, y, t + EPS])
                else:
                    cone.apply_translation([x, y, -EPS])
                tools.append(cone)
        elif kind == "counterbore":
            for x, y in _positions(f["at"]):
                cyl = _cylinder(f["d"], f["depth"] + 2 * EPS)
                z = t - f["depth"] / 2 + EPS if f.get("face", "top") == "top" else f["depth"] / 2 - EPS
                cyl.apply_translation([x, y, z])
                tools.append(cyl)
        elif kind == "side_hole":
            p, z = f["pos"]
            if f["axis"] == "x":
                length = xmax - xmin + 2
                cyl = _cylinder(f["d"], length)
                cyl.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
                cyl.apply_translation([(xmin + xmax) / 2, p, z])
            else:
                length = ymax - ymin + 2
                cyl = _cylinder(f["d"], length)
                cyl.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
                cyl.apply_translation([p, (ymin + ymax) / 2, z])
            tools.append(cyl)
        else:
            raise ValueError(f"unsupported feature {kind!r}")
    return tools


def build_mesh(spec: dict) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(profile(spec), height=spec["thickness"])
    tools = _tools(spec, mesh.bounds)
    if tools:
        mesh = trimesh.boolean.difference([mesh, *tools], engine="manifold")
    mesh.apply_translation(-mesh.bounds.mean(axis=0))  # centre for orbiting
    return mesh


def checks(spec: dict, mesh: trimesh.Trimesh) -> dict:
    """Measurements of the reconstruction compared with independent drawing evidence."""
    out = {"watertight": bool(mesh.is_watertight),
           "extents_mm": [round(float(v), 2) for v in mesh.extents],
           "volume_mm3": round(float(mesh.volume), 1)}
    mc = spec.get("mass_check")
    if mc:
        model_g = mesh.volume / 1000.0 * mc["density_g_cm3"]
        out["mass"] = {"model_g": round(model_g, 1), "drawing_g": mc["drawing_weight_g"],
                       "error_pct": round(100 * (model_g - mc["drawing_weight_g"]) / mc["drawing_weight_g"], 2),
                       "density_g_cm3": mc["density_g_cm3"], "source": mc.get("source", "")}
    return out


def _specs():
    if not RECON_SPECS.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECON_SPECS.glob("*.json"))
            if not p.name.startswith("_")]


def _build_one(spec: dict):
    mesh = build_mesh(spec)
    out = MODELS_DIR / f"{spec['document_id']}.glb"
    mesh.export(out)
    return out, {**spec, "checks": checks(spec, mesh)}


def _register(con, spec: dict, out) -> None:
    con.execute(
        "INSERT OR REPLACE INTO models3d (document_id, path, method, spec_json) VALUES (?,?,?,?)",
        (spec["document_id"], out.relative_to(ROOT).as_posix(), METHOD, json.dumps(spec)))


def build_all(con=None) -> list[dict]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in _specs():
        out, built = _build_one(spec)
        results.append({"document_id": spec["document_id"], **built["checks"]})
        if con is not None:
            _register(con, built, out)
    return results


def register_existing(con) -> int:
    """Called by ingest: (re)build every spec and register it. Cheap, and keeps checks current."""
    return len(build_all(con))


if __name__ == "__main__":
    for r in build_all():
        print(json.dumps(r))
