"""Validated recipes and native FlowKit execution; no GUI required."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .compensation import resolve_compensation
from .recipes import digest, load_recipe, save_recipe, validate

__all__ = [
    "analyze_sample",
    "build_strategy",
    "digest",
    "evaluate",
    "load_recipe",
    "prepare",
    "save_recipe",
    "validate",
]


def flowkit():
    from ._vendor import flowkit as fk

    return fk


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
    matrix = resolve_compensation(sample, recipe["compensation"])
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
            bounds = (
                gate["bounds"][i * 2 : i * 2 + 2] if gate["kind"] in ("rectangle", "range") else [None, None]
            )
            dims.append(
                fk.Dimension(
                    channel,
                    compensation_ref="compensation"
                    if matrix is not None and channel in matrix.detectors
                    else "uncompensated",
                    transformation_ref=channel
                    if channel in strategy.transformations and gate["kind"] != "ratio"
                    else None,
                    range_min=bounds[0],
                    range_max=bounds[1],
                )
            )
        if gate["kind"] == "ratio":
            from .ratio import SignalRatioGate

            operation = SignalRatioGate(gate["name"], dims, gate["bounds"], gate["denominator_min"])
        elif gate["kind"] == "boolean":
            operation = fk.gates.BooleanGate(
                gate["name"],
                gate["operation"],
                [{"ref": ref, "path": paths[ref][:-1], "complement": False} for ref in gate["references"]],
            )
        elif gate["kind"] == "polygon":
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
            "experiment_label": recipe.get("experiment", {}).get("label", "analysis"),
            "is_example": recipe.get("experiment", {}).get("is_example", False),
            "reviewed": gate.get("reviewed", False) if gate["name"] != "root" else True,
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
