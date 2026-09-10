"""Generate synthetic two-color screen inputs; never uses experimental data."""

import csv
from pathlib import Path

import flowio
import numpy as np

from agentflow import save_recipe

out = Path("demo")
out.mkdir(exist_ok=True)
rng = np.random.default_rng(42)
spill = np.array([[1.0, 0.12], [0.04, 1.0]])
rows = []
for i, fraction in enumerate([0.15, 0.4, 0.7]):
    n = 5000
    positive = rng.random(n) < fraction
    signal = (
        np.column_stack([rng.normal(100, 20, n) + 1500 * positive, rng.normal(100, 20, n) + 900 * positive])
        @ spill
    )
    data = np.column_stack([rng.normal(50000, 8000, n), rng.normal(30000, 5000, n), signal])
    filename = f"sample-{i + 1}.fcs"
    with (out / filename).open("wb") as handle:
        flowio.create_fcs(handle, data.ravel().tolist(), ["FSC-A", "SSC-A", "FITC-A", "PE-A"])
    rows.append(
        {
            "sample_id": f"sample-{i + 1}",
            "fcs_path": filename,
            "well": f"A0{i + 1}",
            "condition": ["control", "low", "high"][i],
        }
    )
with (out / "samples.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
save_recipe(
    out / "recipe.json",
    {
        "version": 1,
        "compensation": {"mode": "matrix", "detectors": ["FITC-A", "PE-A"], "values": spill.tolist()},
        "transforms": {
            "FSC-A": {"kind": "linear"},
            "SSC-A": {"kind": "linear"},
            "FITC-A": {"kind": "asinh", "cofactor": 150},
            "PE-A": {"kind": "asinh", "cofactor": 150},
        },
        "gates": [
            {
                "name": "cells",
                "parent": "root",
                "kind": "polygon",
                "channels": ["FSC-A", "SSC-A"],
                "vertices": [[25000, 15000], [75000, 15000], [75000, 45000], [25000, 45000]],
            },
            {
                "name": "positive",
                "parent": "cells",
                "kind": "rectangle",
                "channels": ["FITC-A", "PE-A"],
                "bounds": [2, 5, 2, 5],
            },
        ],
    },
)
print("Created demo/samples.csv and demo/recipe.json (synthetic data).")
