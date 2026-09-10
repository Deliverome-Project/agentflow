"""Sequential batch execution with atomic output publication and provenance."""

import hashlib
import json
import platform
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from .engine import digest, evaluate, load_recipe, prepare, save_recipe, summarize
from .vendor_info import vendor_identity


def run_batch(samples, recipe_path, output):
    recipe_bytes = Path(recipe_path).read_bytes()
    recipe = load_recipe(recipe_path)
    manifest_bytes = Path(samples).read_bytes()
    manifest = pd.read_csv(samples, dtype=str, keep_default_na=False)
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
                }
            )
            save_qc(prepared, recipe, masks, staging / f"gates-{index + 1:04d}.png", record["sample_id"])
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
        if out.exists():
            raise ValueError("Output appeared during analysis; choose a new run directory")
        staging.rename(out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({"status": "complete", "samples": len(manifest), "output": str(out)}))
    return pd.concat(rows, ignore_index=True)


def save_qc(prepared, recipe, masks, path, sample_id):
    # Use an independent Agg canvas: never opens a window or changes GUI backends.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Polygon, Rectangle

    gates = recipe["gates"]
    fig = Figure(figsize=(5 * max(1, min(3, len(gates))), 4 * max(1, (len(gates) + 2) // 3)))
    FigureCanvasAgg(fig)
    fig.suptitle(sample_id)
    if not gates:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, f"{prepared.sample.event_count:,} events; no gates", ha="center")
        ax.set_axis_off()
    for i, gate in enumerate(gates):
        ax = fig.add_subplot((len(gates) + 2) // 3, min(3, len(gates)), i + 1)
        x, y = gate["channels"]
        data = prepared.transformed.loc[masks[gate["parent"]], [x, y]]
        if len(data):
            ax.hexbin(data[x], data[y], gridsize=70, mincnt=1, bins="log", cmap="viridis")
        if gate["kind"] == "polygon":
            patch = Polygon(gate["vertices"], fill=False, edgecolor="red", linewidth=1.5)
        else:
            x0, x1, y0, y1 = gate["bounds"]
            patch = Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="red", linewidth=1.5)
        ax.add_patch(patch)
        ax.autoscale_view()
        ax.set(
            xlabel=f"{x} ({recipe['transforms'][x]['kind']})",
            ylabel=f"{y} ({recipe['transforms'][y]['kind']})",
            title=f"{gate['name']}: {masks[gate['name']].sum():,} / {len(data):,}",
        )
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
