"""Validated recipes and native FlowKit execution; no GUI required."""

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


def flowkit():
    import flowkit as fk

    return fk


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate(recipe):
    """Reject ambiguous recipes before opening data or saving edits."""
    if recipe.get("version") != 1:
        raise ValueError("Recipe version must be 1")
    comp = recipe["compensation"]
    if comp["mode"] not in ("none", "fcs", "matrix"):
        raise ValueError("Compensation mode must be none, fcs, or matrix")
    if comp["mode"] == "matrix":
        detectors = comp["detectors"]
        matrix = np.asarray(comp["values"], dtype=float)
        if (
            not detectors
            or len(set(detectors)) != len(detectors)
            or matrix.shape != (len(detectors), len(detectors))
            or not np.isfinite(matrix).all()
        ):
            raise ValueError("Matrix must be finite, square, and match unique detector names")
        if np.linalg.matrix_rank(matrix) != len(detectors):
            raise ValueError("Compensation matrix is singular")
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
            flowkit().transforms.LogicleTransform(**params)
        elif spec["kind"] != "linear":
            raise ValueError("Transform must be linear, asinh, or logicle")
    seen = {"root"}
    for gate in recipe["gates"]:
        if not gate["name"] or gate["name"] in seen or gate["parent"] not in seen:
            raise ValueError("Gate names must be unique; parents must precede children")
        if len(gate["channels"]) != 2 or len(set(gate["channels"])) != 2:
            raise ValueError("Each gate requires two different channels")
        if not set(gate["channels"]) <= recipe["transforms"].keys():
            raise ValueError("Every gate channel requires an explicit transform")
        if gate["kind"] == "polygon":
            points = np.asarray(gate["vertices"], dtype=float)
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
                raise ValueError("Polygon requires at least three 2D vertices")
            if not np.isfinite(points).all() or np.linalg.matrix_rank(points - points[0]) < 2:
                raise ValueError("Polygon must be finite and enclose an area")
        elif gate["kind"] == "rectangle":
            bounds = np.asarray(gate["bounds"], dtype=float)
            if bounds.shape != (4,) or not np.isfinite(bounds).all():
                raise ValueError("Rectangle requires four finite bounds")
            if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
                raise ValueError("Rectangle minimum must be below maximum")
        else:
            raise ValueError("Gate kind must be polygon or rectangle")
        seen.add(gate["name"])


def save_recipe(path, recipe):
    validate(recipe)
    path = Path(path)
    # Atomic replacement prevents an interrupted save leaving half a recipe.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(recipe, handle, indent=2, allow_nan=False)
        handle.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_recipe(path):
    recipe = json.loads(Path(path).read_text())
    validate(recipe)
    return recipe


def make_transform(spec):
    fk = flowkit()
    if spec["kind"] == "linear":
        return None
    if spec["kind"] == "asinh":
        # GatingML parametrization exactly equivalent to arcsinh(x / cofactor).
        return fk.transforms.AsinhTransform(
            param_t=spec["cofactor"] * np.sinh(1), param_m=1 / np.log(10), param_a=0
        )
    return fk.transforms.LogicleTransform(**spec["parameters"])


@dataclass
class PreparedSample:
    sample: object
    values: pd.DataFrame
    transformed: pd.DataFrame
    matrix: object


def prepare(path, recipe):
    validate(recipe)
    fk = flowkit()
    sample = path if isinstance(path, fk.Sample) else fk.Sample(str(path))
    channels = sample.pnn_labels
    required = set(recipe["transforms"])
    if not required <= set(channels):
        raise ValueError(f"Missing channels: {sorted(required - set(channels))}")
    if len(set(channels)) != len(channels):
        raise ValueError("Duplicate detector names")
    comp = recipe["compensation"]
    matrix = None
    # Explicitly clear pre-existing sample compensation; the recipe is authoritative.
    sample.apply_compensation(None)
    if comp["mode"] == "fcs":
        metadata = {k.lower(): v for k, v in sample.get_metadata().items()}
        spill = metadata.get("spillover") or metadata.get("spill")
        if not spill:
            raise ValueError("FCS has no spillover matrix; choose compensation explicitly")
        sample.apply_compensation(spill)
        matrix = sample.compensation
    elif comp["mode"] == "matrix":
        matrix = fk.Matrix(
            np.asarray(comp["values"], dtype=float),
            comp["detectors"],
            fluorochromes=comp.get("fluorochromes", comp["detectors"]),
        )
        sample.apply_compensation(matrix)
    if matrix is not None and (
        not np.isfinite(matrix.matrix).all() or np.linalg.matrix_rank(matrix.matrix) != len(matrix.detectors)
    ):
        raise ValueError("Spillover matrix must be finite and nonsingular")
    values = pd.DataFrame(sample.get_events(source="raw" if matrix is None else "comp"), columns=channels)
    transformed = values.copy()
    for channel, spec in recipe["transforms"].items():
        transform = make_transform(spec)
        if transform is not None:
            transformed[channel] = transform.apply(values[channel].to_numpy())
    if not np.isfinite(transformed[list(required)].to_numpy()).all():
        raise ValueError("Nonfinite values in selected channels")
    return PreparedSample(sample, values, transformed, matrix)


def build_strategy(recipe, matrix=None):
    """Compile the recipe into FlowKit's hierarchy, dimensions and transforms."""
    validate(recipe)
    fk = flowkit()
    strategy = fk.GatingStrategy()
    if matrix is not None:
        strategy.add_comp_matrix("compensation", matrix)
    for channel, spec in recipe["transforms"].items():
        transform = make_transform(spec)
        if transform is not None:
            strategy.add_transform(channel, transform)
    paths = {"root": ("root",)}
    for gate in recipe["gates"]:
        dims = []
        for i, channel in enumerate(gate["channels"]):
            bounds = gate["bounds"][i * 2 : i * 2 + 2] if gate["kind"] == "rectangle" else [None, None]
            dims.append(
                fk.Dimension(
                    channel,
                    compensation_ref="compensation"
                    if matrix is not None and channel in matrix.detectors
                    else "uncompensated",
                    transformation_ref=channel if channel in strategy.transformations else None,
                    range_min=bounds[0],
                    range_max=bounds[1],
                )
            )
        if gate["kind"] == "polygon":
            operation = fk.gates.PolygonGate(gate["name"], dims, gate["vertices"])
        else:
            operation = fk.gates.RectangleGate(gate["name"], dims)
        path = paths[gate["parent"]]
        strategy.add_gate(operation, path)
        paths[gate["name"]] = (*path, gate["name"])
    return strategy


def evaluate(prepared, recipe):
    strategy = build_strategy(recipe, prepared.matrix)
    masks = {"root": np.ones(prepared.sample.event_count, dtype=bool)}
    if recipe["gates"]:
        result = strategy.gate_sample(prepared.sample, cache_events=False)
        masks.update({g["name"]: result.get_gate_membership(g["name"]) for g in recipe["gates"]})
    return masks


def analyze_sample(path, recipe):
    """Return gate statistics; signal medians precede display transformation.

    ``path`` accepts an FCS path or a FlowKit Sample. Passing a Sample updates its
    compensation to match the recipe. The input event data remains unchanged.
    """
    prepared = prepare(path, recipe)
    return summarize(prepared, recipe, evaluate(prepared, recipe))


def summarize(prepared, recipe, masks):
    rows = []
    for gate in [{"name": "root", "parent": "root"}, *recipe["gates"]]:
        mask, parent = masks[gate["name"]], masks[gate["parent"]]
        row = {
            "gate": gate["name"],
            "parent": gate["parent"],
            "count": int(mask.sum()),
            "parent_count": int(parent.sum()),
            "percent_parent": 100 * mask.sum() / parent.sum() if parent.any() else None,
            "percent_total": 100 * mask.sum() / len(mask) if len(mask) else None,
        }
        for channel in recipe["transforms"]:
            row[f"median_signal:{channel}"] = (
                float(prepared.values.loc[mask, channel].median()) if mask.any() else None
            )
        rows.append(row)
    return pd.DataFrame(rows)
