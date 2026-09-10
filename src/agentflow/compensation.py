"""Labelled spillover matrices and explicit single-stain control estimation.

Independent median-difference implementation, not copied from Cytoflow.
Matrix orientation: measured = true @ spillover. No intensity transforms here.
"""

import csv
import json
from pathlib import Path

import numpy as np

from ._vendor import flowkit as fk


def validate_compensation(spec):
    if spec["mode"] not in ("none", "fcs", "matrix"):
        raise ValueError("Compensation mode must be none, fcs, or matrix")
    if spec["mode"] != "matrix":
        return
    detectors = spec["detectors"]
    matrix = np.asarray(spec["values"], dtype=float)
    if (
        not detectors
        or any(not isinstance(d, str) or not d for d in detectors)
        or len(set(detectors)) != len(detectors)
        or matrix.shape != (len(detectors), len(detectors))
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("Matrix must be finite, square, and match unique detector names")
    if np.linalg.matrix_rank(matrix) != len(detectors):
        raise ValueError("Compensation matrix is singular")
    if np.linalg.cond(matrix) > 1e8:
        raise ValueError("Compensation matrix is ill-conditioned")
    if not np.allclose(np.diag(matrix), 1, atol=1e-8):
        raise ValueError("Spillover diagonal must be 1; supply fractions, not percentages or an inverse")
    if "fluorochromes" in spec and (
        len(spec["fluorochromes"]) != len(detectors)
        or any(not isinstance(x, str) or not x for x in spec["fluorochromes"])
    ):
        raise ValueError("Provide one nonempty fluorochrome label per detector")


def resolve_compensation(sample, spec):
    validate_compensation(spec)
    sample.apply_compensation(None)
    if spec["mode"] == "none":
        return None
    if spec["mode"] == "fcs":
        metadata = {k.lower(): v for k, v in sample.get_metadata().items()}
        spill = metadata.get("spillover") or metadata.get("spill")
        if not spill:
            raise ValueError("FCS has no spillover matrix; choose compensation explicitly")
        # Parse labels and values before applying, so singular matrices get a clear error.
        from flowutils.compensate import get_spill

        values, detectors = get_spill(spill)
        spec = {"mode": "matrix", "detectors": detectors, "values": values.tolist()}
        validate_compensation(spec)
    matrix = fk.Matrix(
        np.asarray(spec["values"], dtype=float),
        spec["detectors"],
        fluorochromes=spec.get("fluorochromes", spec["detectors"]),
    )
    sample.apply_compensation(matrix)
    return matrix


def load_matrix(path):
    """Read matrix JSON or labelled square CSV/TSV (first column = source detector)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        spec = json.loads(path.read_text())
    else:
        with path.open(newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ","))
        if len(rows) < 2 or len(rows[0]) < 2:
            raise ValueError("Matrix table requires column and row detector labels")
        columns = [v.strip() for v in rows[0][1:]]
        row_labels = [row[0].strip() for row in rows[1:] if row]
        if row_labels != columns or len(rows) - 1 != len(columns):
            raise ValueError("Matrix row labels must equal column labels in the same order")
        spec = {
            "mode": "matrix",
            "detectors": columns,
            "values": [[float(v) for v in row[1:]] for row in rows[1:]],
        }
    if spec.get("mode") != "matrix":
        raise ValueError("Expected an explicit matrix object")
    validate_compensation(spec)
    return spec


def save_matrix(spec, path):
    validate_compensation(spec)
    path = Path(path)
    serialized = json.dumps(spec, indent=2, allow_nan=False) + "\n"
    with path.open("x") as handle:
        handle.write(serialized)


def estimate_controls(config_path):
    """Estimate rows from positive/negative populations in each single-stain FCS.

    The user supplies raw-signal thresholds, not automatically inferred gates.
    Both populations must be the same particle type/background. At least 50
    events in each are required by default. Optional cleanup uses an uncompensated
    recipe and a named gate. Results require inspection of the diagnostic report.
    """
    from .engine import evaluate, prepare
    from .recipes import digest, load_recipe

    path = Path(config_path).resolve()
    config_fingerprint = digest(path)
    config = json.loads(path.read_text())
    cleanup = None
    cleanup_fingerprint = None
    if config.get("cleanup_recipe"):
        cleanup_path = path.parent / config["cleanup_recipe"]
        cleanup_fingerprint = digest(cleanup_path)
        cleanup = load_recipe(cleanup_path)
        if cleanup["compensation"]["mode"] != "none":
            raise ValueError("Control cleanup recipe must be uncompensated")
    detectors = config["detectors"]
    if not detectors or len(set(detectors)) != len(detectors):
        raise ValueError("Control detectors must be nonempty and unique")
    controls = config["controls"]
    if len(controls) != len(detectors) or {c["detector"] for c in controls} != set(detectors):
        raise ValueError("Provide exactly one single-stain control per detector")
    minimum = config.get("min_events", 50)
    if not isinstance(minimum, int) or minimum < 2:
        raise ValueError("min_events must be an integer of at least 2")
    matrix = np.eye(len(detectors))
    evidence = []
    for control in controls:
        source = control["detector"]
        fcs = path.parent / control["fcs_path"]
        fingerprint = digest(fcs)
        sample = fk.Sample(str(fcs))
        missing = set(detectors) - set(sample.pnn_labels)
        if missing:
            raise ValueError(f"Control missing detectors: {sorted(missing)}")
        indices = [sample.pnn_labels.index(d) for d in detectors]
        data = sample.get_events(source="raw")[:, indices]
        if not np.isfinite(data).all():
            raise ValueError("Controls contain nonfinite events")
        if config.get("cleanup_recipe"):
            recipe = cleanup
            if recipe["compensation"]["mode"] != "none":
                raise ValueError("Control cleanup recipe must be uncompensated")
            masks = evaluate(prepare(sample, recipe), recipe)
            data = data[masks[config["cleanup_gate"]]]
        low, high = control["negative_max"], control["positive_min"]
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError("Control thresholds must be finite and negative_max < positive_min")
        j = detectors.index(source)
        neg, pos = data[:, j] <= low, data[:, j] >= high
        if min(int(neg.sum()), int(pos.sum())) < minimum:
            raise ValueError(f"{source}: too few positive or negative control events")
        med_neg, med_pos = np.median(data[neg], axis=0), np.median(data[pos], axis=0)
        delta = med_pos - med_neg
        if delta[j] <= 0:
            raise ValueError(f"{source}: positive signal must exceed negative signal")
        # Saturated bright controls cannot determine spillover reliably.
        limit = float(sample.channels.iloc[indices[j]]["pnr"]) - 1
        if np.any(data[pos, j] >= limit):
            raise ValueError(f"{source}: positive control includes saturated events")
        matrix[j] = delta / delta[j]
        if digest(fcs) != fingerprint:
            raise ValueError("Control file changed during estimation")
        evidence.append(
            {
                "detector": source,
                "fcs_path": control["fcs_path"],
                "sha256": fingerprint,
                "negative_max": low,
                "positive_min": high,
                "positive_count": int(pos.sum()),
                "negative_count": int(neg.sum()),
                "negative_medians": med_neg.tolist(),
                "positive_medians": med_pos.tolist(),
            }
        )
    if digest(path) != config_fingerprint:
        raise ValueError("Control configuration changed during estimation")
    if cleanup_fingerprint is not None and digest(cleanup_path) != cleanup_fingerprint:
        raise ValueError("Cleanup recipe changed during estimation")
    spec = {
        "mode": "matrix",
        "detectors": detectors,
        "values": matrix.tolist(),
        "estimation": {
            "method": "positive-minus-negative medians",
            "controls": evidence,
            "config_sha256": config_fingerprint,
            "cleanup_recipe_sha256": cleanup_fingerprint,
            "reviewed": False,
        },
    }
    validate_compensation(spec)
    return spec


def matrix_diagnostic(spec, path):
    """Plot labelled spillover coefficients for review."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(9, 6))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    values = np.asarray(spec["values"])
    view = ax.imshow(values, cmap="Blues")
    labels = spec["detectors"]
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set(
        xlabel="Receiving detector",
        ylabel="Source detector",
        title="Spillover coefficients (fractions) — review controls",
    )
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{values[i, j]:.4f}", ha="center", va="center", color="red")
    fig.colorbar(view, ax=ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def control_diagnostics(config_path, spec, output):
    """Show raw and compensated secondary signals for every single-stain control."""
    from .plots import new_figure
    from .recipes import digest

    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    base = Path(config_path).resolve().parent
    detectors = spec["detectors"]
    if len(detectors) < 2:
        return
    for index, control in enumerate(spec["estimation"]["controls"], 1):
        path = base / control["fcs_path"]
        if digest(path) != control["sha256"]:
            raise ValueError("Control changed since matrix estimation")
        sample = fk.Sample(str(path))
        columns = [sample.pnn_labels.index(d) for d in detectors]
        raw = sample.get_events(source="raw")[:, columns]
        compensated = np.linalg.solve(np.asarray(spec["values"]).T, raw.T).T
        source = detectors.index(control["detector"])
        others = [i for i in range(len(detectors)) if i != source]
        fig = new_figure(4 * len(others), 7)
        fig.suptitle(f"{control['detector']} single-stain — descriptive QC, review cleanup/thresholds")
        step = max(1, len(raw) // 5000)
        for k, target in enumerate(others):
            for row, data in enumerate([raw, compensated]):
                ax = fig.add_subplot(2, len(others), row * len(others) + k + 1)
                # Plot all events up to 5000, then a fixed-stride visual sample;
                # estimation itself always uses every eligible event.
                ax.scatter(raw[::step, source], data[::step, target], s=2, alpha=0.2)
                ax.axvline(control["negative_max"], color="grey", ls="--")
                ax.axvline(control["positive_min"], color="red", ls="--")
                ax.set(
                    xlabel=f"{control['detector']} raw",
                    ylabel=detectors[target],
                    title="Raw" if row == 0 else "Compensated",
                )
        fig.tight_layout()
        fig.savefig(out / f"control-{index:02d}.png", dpi=130)
