"""Compile signal ratios into standard Gating-ML dimensions and transformations."""

import numpy as np

from . import flowkit as fk


def compile_ratio(strategy, gate, matrix):
    identifier = "agentflow_ratio_" + gate["name"]
    while identifier in strategy.transformations:
        identifier += "_"
    strategy.add_transform(identifier, fk.transforms.RatioTransform(gate["channels"], 1.0, 0.0, 0.0))
    compensation = "compensation" if matrix is not None else "uncompensated"
    dims = [
        fk.RatioDimension(identifier, compensation, range_min=gate["bounds"][0], range_max=gate["bounds"][1]),
        fk.Dimension(
            gate["channels"][1],
            compensation_ref=compensation,
            range_min=float(np.nextafter(gate["denominator_min"], np.inf)),
        ),
    ]
    return fk.gates.RectangleGate(gate["name"], dims)
