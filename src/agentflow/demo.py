"""Deterministic synthetic screen with known spillover and single-stain controls."""

import csv
import json
from pathlib import Path

import flowio
import numpy as np

from .compensation import control_diagnostics, estimate_controls, matrix_diagnostic, save_matrix
from .engine import make_transform
from .workflow import scaffold


def make_demo(output):
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("Demo folder already exists")
    out.mkdir(parents=True)
    rng = np.random.default_rng(42)
    detectors = ["BV1-A", "BL1-A", "YL2-A", "RL1-A"]
    channels = ["Time", "FSC-A", "SSC-A", "FSC-H", *detectors]
    matrix = np.array(
        [[1, 0.02, 0.01, 0.01], [0.005, 1, 0.08, 0.015], [0.01, 0.05, 1, 0.09], [0.01, 0.01, 0.03, 1]]
    )

    def write(path, truth, scatter=True):
        n = len(truth)
        area = rng.lognormal(np.log(60000), 0.25, n)
        height = area * rng.normal(0.85, 0.05, n)
        if scatter:
            height[rng.random(n) < 0.1] *= 0.45
        data = np.column_stack(
            [np.arange(n) * 0.01, area, rng.lognormal(np.log(30000), 0.3, n), height, truth @ matrix]
        )
        with path.open("wb") as handle:
            flowio.create_fcs(handle, data.ravel().tolist(), channels)

    controls = []
    for j, detector in enumerate(detectors):
        n = 2000
        truth = rng.normal(100, 10, (n, 4))
        truth[n // 2 :, j] += 20000
        filename = f"control-{j + 1}.fcs"
        write(out / filename, truth, False)
        controls.append(
            {"detector": detector, "fcs_path": filename, "negative_max": 500, "positive_min": 10000}
        )
    (out / "controls.json").write_text(
        json.dumps({"detectors": detectors, "controls": controls}, indent=2) + "\n"
    )
    estimated = estimate_controls(out / "controls.json")
    save_matrix(estimated, out / "compensation.json")
    matrix_diagnostic(estimated, out / "compensation.png")
    control_diagnostics(out / "controls.json", estimated, out / "control-diagnostics")
    (out / "expected-spillover.json").write_text(
        json.dumps({"mode": "matrix", "detectors": detectors, "values": matrix.tolist()}, indent=2) + "\n"
    )
    rows = []
    for i, fraction in enumerate([0.05, 0.25, 0.6]):
        n = 5000
        truth = rng.normal(100, 30, (n, 4))
        truth[:, 0] += 15000 * (rng.random(n) < 0.2)
        for j in range(1, 4):
            truth[:, j] += 20000 * (rng.random(n) < fraction)
        filename = f"sample-{i + 1}.fcs"
        write(out / filename, truth)
        rows.append(
            {
                "sample_id": f"DUMMY-{i + 1}",
                "fcs_path": str(out / filename),
                "well": f"A0{i + 1}",
                "condition": ["control", "low", "high"][i],
                "group": ["Negative control", "Low positive fraction", "High positive fraction"][i],
                "color": ["#3d6b60", "#5848a8", "#922038"][i],
                "plate": "DUMMY-PLATE-1",
                "replicate": "1",
                "control_role": ["negative", "sample", "positive"][i],
                "experiment": "DUMMY / SYNTHETIC EXAMPLE",
            }
        )
    scaffold(
        out / "sample-1.fcs",
        out / "workflow",
        dict(zip(["live", "gfp", "mscarlet", "cy5"], detectors)),
        True,
        matrix_path=out / "compensation.json",
    )
    # Deliberate demo boundaries separate the simulated populations. Never reuse
    # them as biological thresholds. All remain visibly draft/example.
    recipe_path = out / "workflow/recipe.json"
    recipe = json.loads(recipe_path.read_text())
    for gate in recipe["gates"]:
        if gate["name"] in ("live", "gfp", "mscarlet", "cy5"):
            transform = make_transform(recipe["transforms"][gate["channels"][0]])
            low, threshold, high = transform.apply(np.array([-1000.0, 5000.0, 100000.0])).tolist()
            gate["bounds"] = [low, threshold] if gate["name"] == "live" else [threshold, high]
            gate["note"] = (
                "DUMMY synthetic dye / detector assignment and threshold; for interaction practice only."
            )
            if gate["name"] == "live":
                gate["label"] = "Live / dead — DUMMY BV1-A"
    for mapping in recipe["channel_roles"].values():
        mapping["confirmed"] = True
        mapping["is_example"] = True
    recipe_path.write_text(json.dumps(recipe, indent=2) + "\n")
    with (out / "workflow/samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "README.md").write_text(
        "# DUMMY / SYNTHETIC EXAMPLE\n\nGenerated with seed 42; no experimental data.\n\n"
        "Four single-stain controls estimate compensation. All workflow gates remain draft drawing aids.\n"
        "Compare compensation.json with expected-spillover.json; inspect the control evidence.\n\n"
        "Group labels are generator inputs, not inferred classifications: reporter-positive probabilities "
        "are 5%, 25%, and 60% per reporter, sampled independently. Positive events receive the same "
        "20,000-unit signal increment in every group. The demo negative control has 5% positives; "
        "it is not an unstained control. Real groups come from the sample sheet.\n"
    )
    return out
