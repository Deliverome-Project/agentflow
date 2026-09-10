"""Scaffold a conservative editable workflow from channels actually acquired."""

import copy
import csv
import json
import re
from pathlib import Path

import numpy as np

from ._vendor import flowkit as fk
from .compensation import load_matrix
from .engine import evaluate, prepare
from .recipes import save_recipe, validate

ROLES = ("live", "gfp", "mscarlet", "cy5")
TITLES = {"live": "Live / dead", "gfp": "GFP", "mscarlet": "mScarlet", "cy5": "Cy5"}


def inspect_sample(path):
    sample = fk.Sample(str(path))
    metadata = sample.get_metadata()
    spill = metadata.get("spillover") or metadata.get("spill")
    matrix_info = None
    if spill:
        from flowutils.compensate import get_spill

        values, detectors = get_spill(spill)
        matrix_info = {
            "detectors": detectors,
            "values": values.tolist(),
            "identity": bool(np.allclose(values, np.eye(len(detectors)))),
        }
    return {
        "events": sample.event_count,
        "channels": [{"detector": n, "marker": m} for n, m in zip(sample.pnn_labels, sample.pns_labels)],
        "instrument": metadata.get("cyt"),
        "spillover": matrix_info,
    }


def mark_unreviewed(recipe, name=None):
    affected = {name} if name else {g["name"] for g in recipe["gates"]}
    for gate in recipe["gates"]:
        if gate["parent"] in affected or set(gate.get("references", [])) & affected:
            affected.add(gate["name"])
        if gate["name"] in affected:
            gate["reviewed"] = False
    return affected


def add_reporter(recipe, sample_path, role, channel, confirmed=False):
    """Map a pending role explicitly; never manufacture an unacquired channel."""
    recipe = copy.deepcopy(recipe)
    sample = sample_path if isinstance(sample_path, fk.Sample) else fk.Sample(str(sample_path))
    if role not in ROLES or channel not in sample.pnn_labels:
        raise ValueError("Choose a listed role and an acquired detector")
    if channel not in [sample.pnn_labels[i] for i in sample.fluoro_indices]:
        raise ValueError("Choose a fluorescence detector for a reporter or viability gate")
    assigned = {k: v["detector"] for k, v in recipe.get("channel_roles", {}).items()}
    base = re.sub(r"-[AHW]$", "", channel)
    if base in [re.sub(r"-[AHW]$", "", v) for k, v in assigned.items() if k != role]:
        raise ValueError("A detector is already assigned to a different dye role")
    if any(g["name"] == role for g in recipe["gates"]):
        raise ValueError("Role already exists; edit its gate or create a new workflow to remap it")
    recipe["transforms"].setdefault(channel, {"kind": "asinh", "cofactor": 150})
    recipe.setdefault("channel_roles", {})[role] = {"detector": channel, "confirmed": confirmed}
    names = [g["name"] for g in recipe["gates"]]
    parent = (
        "live"
        if role != "live" and "live" in names
        else ("singlets" if "singlets" in names else "cells" if "cells" in names else "root")
    )
    prepared = prepare(sample, recipe)
    data = prepared.transformed.loc[evaluate(prepared, recipe)[parent], channel].to_numpy()
    if not len(data):
        raise ValueError("Parent has no events; adjust parent gates first")
    threshold = float(np.quantile(data, 0.8))
    gate = {
        "name": role,
        "parent": parent,
        "kind": "range",
        "channels": [channel],
        "bounds": [None, threshold] if role == "live" else [threshold, None],
        "reviewed": False,
        "label": TITLES[role] + ("" if confirmed else " candidate"),
        "note": "Draft 80th-percentile threshold; use biological controls to set the final boundary.",
    }
    if role == "live":
        position = next(
            (i for i, g in enumerate(recipe["gates"]) if g["name"] in ROLES), len(recipe["gates"])
        )
        recipe["gates"].insert(position, gate)
        for g in recipe["gates"]:
            if g["name"] in ROLES and g["name"] != "live":
                g["parent"] = "live"
                g["reviewed"] = False
    else:
        recipe["gates"].append(gate)
    recipe["pending_gates"] = [p for p in recipe.get("pending_gates", []) if p["name"] != role]
    validate(recipe)
    return recipe


def scaffold(sample_path, output, roles=None, example=False, compensation="fcs", matrix_path=None):
    out = Path(output)
    if out.exists():
        raise ValueError("Example/workflow folder already exists")
    sample_path = Path(sample_path).resolve()
    info = inspect_sample(sample_path)
    sample = fk.Sample(str(sample_path))
    labels = sample.pnn_labels
    spec = load_matrix(matrix_path) if matrix_path else {"mode": compensation}
    recipe = {
        "version": 1,
        "experiment": {
            "label": "DUMMY / EXAMPLE — NOT VALIDATED" if example else "Draft flow analysis",
            "is_example": example,
        },
        "compensation": spec,
        "transforms": {},
        "gates": [],
        "pending_gates": [],
        "channel_roles": {},
    }
    for name in ["FSC-A", "SSC-A", "FSC-H"]:
        if name in labels:
            recipe["transforms"][name] = {"kind": "linear"}
    if not {"FSC-A", "SSC-A"} <= set(labels):
        raise ValueError("Default workflow requires FSC-A and SSC-A; use explicit recipes for other labels")
    values = prepare(sample, recipe).transformed
    low, high = values[["FSC-A", "SSC-A"]].quantile([0.02, 0.98]).to_numpy()
    low = np.maximum(low, 0)
    if np.any(high <= low):
        raise ValueError("Insufficient scatter variation for a default gate")
    recipe["gates"].append(
        {
            "name": "cells",
            "parent": "root",
            "kind": "polygon",
            "channels": ["FSC-A", "SSC-A"],
            "vertices": [low.tolist(), [high[0], low[1]], high.tolist(), [low[0], high[1]]],
            "label": "FSC / SSC cells",
            "reviewed": False,
            "note": "Draft scatter envelope, not a cell-type classifier.",
        }
    )
    if "FSC-H" in labels:
        selected = values.loc[evaluate(prepare(sample, recipe), recipe)["cells"]]
        selected = selected[(selected["FSC-A"] > 0) & (selected["FSC-H"] > 0)]
        if len(selected) > 10:
            x0, x1 = selected["FSC-A"].quantile([0.02, 0.98])
            central_low, central_high = selected["FSC-A"].quantile([0.25, 0.75])
            central = selected[selected["FSC-A"].between(central_low, central_high)]
            ratio = float((central["FSC-H"] / central["FSC-A"]).median())
            r0, r1 = ratio * 0.75, ratio * 1.25
            if r1 > r0 and x1 > x0:
                recipe["gates"].append(
                    {
                        "name": "singlets",
                        "parent": "cells",
                        "kind": "polygon",
                        "channels": ["FSC-A", "FSC-H"],
                        "vertices": [[x0, x0 * r0], [x1, x1 * r0], [x1, x1 * r1], [x0, x0 * r1]],
                        "label": "Singlets (area / height)",
                        "reviewed": False,
                        "note": "Draft area/height ratio band; manually review doublet exclusion.",
                    }
                )
    if not any(g["name"] == "singlets" for g in recipe["gates"]):
        recipe["pending_gates"].append(
            {
                "name": "singlets",
                "label": "Singlets",
                "reason": "No usable FSC-H data; explicit alternative strategy needed.",
            }
        )
    for role in ROLES:
        recipe["pending_gates"].append(
            {
                "name": role,
                "label": TITLES[role],
                "reason": "Detector/dye identity not provided. A missing detector cannot be gated.",
            }
        )
    for role, channel in (roles or {}).items():
        if channel:
            recipe = add_reporter(recipe, sample, role, channel, confirmed=not example)
    out.mkdir(parents=True)
    save_recipe(out / "recipe.json", recipe)
    with (out / "samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample_id", "fcs_path", "experiment"])
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "DUMMY-example" if example else sample_path.stem,
                "fcs_path": str(sample_path),
                "experiment": recipe["experiment"]["label"],
            }
        )
    (out / "channels.json").write_text(json.dumps(info, indent=2) + "\n")
    (out / "README.md").write_text(
        f"# {recipe['experiment']['label']}\n\nSource: {sample_path.name}\n\n"
        "Default gates and fluorescence assignments are provisional. No biological claims should be drawn "
        "from these counts. Review scatter, singlets and controls before interpreting fluorescence.\n\n"
        "Open: `agentflow edit SAMPLE --recipe recipe.json`\n\n"
        "Rerun: `agentflow run samples.csv --recipe recipe.json --out NEW_RUN_DIRECTORY`\n"
    )
    return recipe
