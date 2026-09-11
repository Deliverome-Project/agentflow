"""Recipe validation, stable JSON persistence and input fingerprints."""

import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
import yaml

from ._vendor import flowkit


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate(recipe):
    """Reject ambiguous recipes before opening data or saving edits."""
    if recipe.get("version") != 1:
        raise ValueError("Recipe version must be 1")
    if not isinstance(recipe.get("transforms"), dict) or not isinstance(recipe.get("gates"), list):
        raise TypeError("Recipe needs transforms and gates")
    comp = recipe["compensation"]
    from .compensation import validate_compensation

    validate_compensation(comp)
    for spec in recipe["transforms"].values():
        if spec["kind"] == "asinh":
            if not np.isfinite(spec["cofactor"]) or spec["cofactor"] <= 0:
                raise ValueError("Asinh cofactor must be finite and positive")
        elif spec["kind"] == "logicle":
            params = spec["parameters"]
            if set(params) != {"param_t", "param_w", "param_m", "param_a"} or not all(
                np.isfinite(v) for v in params.values()
            ):
                raise ValueError("Logicle requires four explicit finite parameters")
            t, w, m, a = (params[k] for k in ["param_t", "param_w", "param_m", "param_a"])
            if t <= 0 or m <= 0 or w < 0 or 2 * w > m or a < -w or a > m - 2 * w:
                raise ValueError("Invalid logicle parameter domain")
            flowkit.transforms.LogicleTransform(**params)
        elif spec["kind"] != "linear":
            raise ValueError("Transform must be linear, asinh, or logicle")
    seen = {"root"}
    for gate in recipe["gates"]:
        if not gate["name"] or gate["name"] in seen or gate["parent"] not in seen:
            raise ValueError("Gate names must be unique; parents must precede children")
        expected = 1 if gate["kind"] == "range" else 2
        if len(gate["channels"]) != expected or len(set(gate["channels"])) != expected:
            raise ValueError(f"Gate requires {expected} distinct channel(s)")
        if not set(gate["channels"]) <= recipe["transforms"].keys():
            raise ValueError("Every gate channel requires an explicit transform")
        if gate["kind"] == "boolean":
            refs = gate.get("references", [])
            if gate.get("operation") not in ("and", "or") or len(refs) < 2 or len(set(refs)) != len(refs):
                raise ValueError("Boolean gates need AND/OR and at least two distinct earlier populations")
            if not set(refs) <= (seen - {"root"}):
                raise ValueError("Boolean references must precede the gate")
        elif gate["kind"] == "polygon":
            points = np.asarray(gate["vertices"], dtype=float)
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
                raise ValueError("Polygon requires at least three 2D vertices")
            if not np.isfinite(points).all() or np.linalg.matrix_rank(points - points[0]) < 2:
                raise ValueError("Polygon must be finite and enclose an area")
        elif gate["kind"] in ("range", "ratio"):
            bounds = gate["bounds"]
            if gate["kind"] == "ratio":
                floor = gate.get("denominator_min")
                if floor is None or not np.isfinite(floor) or floor < 0:
                    raise ValueError("Ratio requires a finite nonnegative denominator minimum")
                if len(bounds) != 2 or any(v is None for v in bounds):
                    raise ValueError("Ratio requires two finite bounds")
            if len(bounds) != 2 or all(v is None for v in bounds):
                raise ValueError("Range requires a lower and/or upper bound")
            if any(v is not None and not np.isfinite(v) for v in bounds):
                raise ValueError("Range bounds must be finite or null")
            if all(v is not None for v in bounds) and bounds[0] >= bounds[1]:
                raise ValueError("Range minimum must be below maximum")
        elif gate["kind"] == "rectangle":
            bounds = np.asarray(gate["bounds"], dtype=float)
            if bounds.shape != (4,) or not np.isfinite(bounds).all():
                raise ValueError("Rectangle requires four finite bounds")
            if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
                raise ValueError("Rectangle minimum must be below maximum")
        else:
            raise ValueError("Gate kind must be polygon, rectangle, or range")
        seen.add(gate["name"])
    if "sample_overrides" in recipe:
        from .overrides import validate_overrides

        validate_overrides(recipe)


def save_recipe(path, recipe):
    validate(recipe)
    path = Path(path)
    # Atomic replacement prevents an interrupted save leaving half a recipe.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            if path.suffix.lower() in {".yaml", ".yml"}:
                yaml.safe_dump(json.loads(json.dumps(recipe, allow_nan=False)), handle, sort_keys=False)
            else:
                json.dump(recipe, handle, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_recipe(path):
    path = Path(path)
    recipe = (
        yaml.safe_load(path.read_text())
        if path.suffix.lower() in {".yaml", ".yml"}
        else json.loads(path.read_text())
    )
    if isinstance(recipe, dict) and recipe.get("snapshot_version") == 1:
        recipe = recipe["recipe"]
    validate(recipe)
    return recipe
