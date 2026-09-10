"""Sequential batch execution with atomic output publication and provenance."""

import hashlib
import io
import json
import platform
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from .engine import digest, evaluate, prepare, save_recipe, summarize, validate
from .plots import save_qc, save_time_qc
from .quality import sample_quality
from .reporting import write_report
from .vendor_info import vendor_identity


def run_batch(samples, recipe_path, output):
    recipe_bytes = Path(recipe_path).read_bytes()
    recipe = json.loads(recipe_bytes)
    validate(recipe)
    manifest_bytes = Path(samples).read_bytes()
    manifest = pd.read_csv(io.BytesIO(manifest_bytes), dtype=str, keep_default_na=False)
    if not {"sample_id", "fcs_path"} <= set(manifest):
        raise ValueError("Sample CSV requires sample_id and fcs_path columns")
    if (
        manifest.empty
        or manifest.sample_id.duplicated().any()
        or (manifest.sample_id.str.strip() == "").any()
    ):
        raise ValueError("Sample IDs must be nonempty and unique; provide at least one sample")
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("Output already exists; choose a new run directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".agentflow-", dir=out.parent))
    rows, provenance = [], []
    try:
        for index, record in enumerate(manifest.to_dict("records")):
            path = Path(record["fcs_path"])
            if not path.is_absolute():
                path = Path(samples).resolve().parent / path
            before = digest(path)
            prepared = prepare(path, recipe)
            masks = evaluate(prepared, recipe)
            if digest(path) != before:
                raise ValueError(f"{path}: input changed during analysis")
            stats = summarize(prepared, recipe, masks)
            stats.insert(0, "sample_id", record["sample_id"])
            for key, value in record.items():
                if key not in ("sample_id", "fcs_path"):
                    stats[f"metadata:{key}"] = value
            rows.append(stats)
            matrix = prepared.matrix
            provenance.append(
                {
                    "sample_id": record["sample_id"],
                    "sha256": before,
                    "compensation": None
                    if matrix is None
                    else {"detectors": matrix.detectors, "values": matrix.matrix.tolist()},
                    "metadata": record,
                    "quality": sample_quality(prepared),
                }
            )
            save_qc(prepared, recipe, masks, staging / f"gates-{index + 1:04d}.png", record["sample_id"])
            save_time_qc(prepared, staging / f"time-{index + 1:04d}.png")
        if Path(recipe_path).read_bytes() != recipe_bytes or Path(samples).read_bytes() != manifest_bytes:
            raise ValueError("Recipe or sample sheet changed during analysis")
        save_recipe(staging / "recipe.json", recipe)
        (staging / "samples.csv").write_bytes(manifest_bytes)
        pd.concat(rows, ignore_index=True).to_csv(staging / "summary.csv", index=False)
        (staging / "run.json").write_text(
            json.dumps(
                {
                    "inputs": provenance,
                    "recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
                    "samples_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "python": platform.python_version(),
                    "experiment": recipe.get("experiment", {}),
                    "pending_gates": recipe.get("pending_gates", []),
                    "flowkit": vendor_identity(),
                    "versions": {
                        p: version(p)
                        for p in [
                            "agentflow-cytometry",
                            "flowio",
                            "flowutils",
                            "numpy",
                            "pandas",
                            "matplotlib",
                        ]
                    },
                    "signal_space": "raw" if recipe["compensation"]["mode"] == "none" else "compensated",
                    "summary": "Median signal before display transformations; counts use all events",
                },
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        write_report(staging, recipe, pd.concat(rows, ignore_index=True), provenance)
        if out.exists():
            raise ValueError("Output appeared during analysis; choose a new run directory")
        staging.rename(out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({"status": "complete", "samples": len(manifest), "output": str(out)}))
    return pd.concat(rows, ignore_index=True)
