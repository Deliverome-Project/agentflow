"""Plate and replicate summaries with explicit controls and optional hit thresholds."""

import json
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .plots import new_figure
from .recipes import digest


def _screen_report(run, output, gate, metric="percent_parent", min_events=100, hit_threshold=None):
    run, out = Path(run), Path(output)
    if out.exists():
        raise ValueError("Screen output already exists; choose a new directory")
    if min_events < 1:
        raise ValueError("Minimum event count must be positive")
    source = run / "summary.csv"
    source_fingerprint = digest(source)
    table = pd.read_csv(source, keep_default_na=False)
    table = table.loc[table.gate == gate].copy()
    if table.empty or metric not in table:
        raise ValueError("Choose an existing gate and numeric metric from summary.csv")
    table["value"] = pd.to_numeric(table[metric], errors="coerce")
    table["plate"] = table.get("metadata:plate", pd.Series("Unassigned", index=table.index))
    table["group"] = table.get(
        "metadata:group", table.get("metadata:condition", pd.Series("All samples", index=table.index))
    )
    roles = table.get("metadata:control_role", pd.Series("sample", index=table.index))
    table["control_role"] = roles
    qc_counts = table["parent_count"]
    if "_signal:" in metric:
        channel = metric.split(":", 1)[1]
        qc_counts = table.get("finite_signal_count:" + channel, table["count"])
    table["qc_population_events"] = qc_counts
    table["qc_pass"] = (qc_counts >= min_events) & np.isfinite(table["value"])
    table["qc_reason"] = np.where(
        table["qc_pass"], "", "Low population/denominator count or missing endpoint"
    )
    table["percent_control"] = np.nan
    plate_rows = []
    for plate, group in table.groupby("plate", sort=False):
        eligible = group.loc[group.qc_pass]
        negative = eligible.loc[eligible.control_role == "negative", "value"]
        positive = eligible.loc[eligible.control_role == "positive", "value"]
        n, p = negative.median(), positive.median()
        delta = p - n
        valid = np.isfinite(delta) and delta != 0
        if valid:
            table.loc[group.index, "percent_control"] = 100 * (group.value - n) / delta
        zprime = np.nan
        # Classical Z-prime uses means and sample standard deviations.
        mean_gap = abs(positive.mean() - negative.mean())
        if len(negative) >= 2 and len(positive) >= 2 and mean_gap > 0:
            zprime = 1 - 3 * (positive.std(ddof=1) + negative.std(ddof=1)) / mean_gap
        plate_rows.append(
            {
                "plate": plate,
                "negative_n": len(negative),
                "positive_n": len(positive),
                "negative_median": n,
                "positive_median": p,
                "z_prime": zprime,
                "normalization_status": "ok" if valid else "Missing or indistinguishable controls",
                "failed_sample_count": int((~group.qc_pass).sum()),
            }
        )
    if hit_threshold is not None:
        if not np.isfinite(hit_threshold):
            raise ValueError("Hit threshold must be finite")
        table["hit"] = (
            table.qc_pass & (table.control_role == "sample") & (table.percent_control >= hit_threshold)
        )
    table["review_status"] = "DRAFT / requires experiment review"
    out.mkdir(parents=True)
    table.to_csv(out / "wells.csv", index=False)
    pd.DataFrame(plate_rows).to_csv(out / "plates.csv", index=False)
    # Independent units remain wells. Preserve biological replicate metadata;
    # this descriptive table does not treat single cells as replicates or test hypotheses.
    replicate_keys = ["plate", "group"]
    if "metadata:biological_replicate" in table:
        replicate_keys.append("metadata:biological_replicate")
    table.loc[table.qc_pass].groupby(replicate_keys, dropna=False).agg(
        wells=("sample_id", "size"),
        mean=("value", "mean"),
        median=("value", "median"),
        sd_between_wells=("value", "std"),
        mean_percent_control=("percent_control", "mean"),
    ).reset_index().to_csv(out / "replicates.csv", index=False)
    for index, (plate, group) in enumerate(table.groupby("plate", sort=False), 1):
        if "metadata:well" not in group:
            continue
        positions = [
            re.fullmatch(r"([A-Pa-p])(0?[1-9]|1[0-9]|2[0-4])", str(w)) for w in group["metadata:well"]
        ]
        if not all(positions):
            raise ValueError(f"Invalid well label in plate {plate}; use A01–P24")
        values = np.full(
            (
                16 if any(ord(m[1].upper()) > ord("H") or int(m[2]) > 12 for m in positions) else 8,
                24 if any(ord(m[1].upper()) > ord("H") or int(m[2]) > 12 for m in positions) else 12,
            ),
            np.nan,
        )
        seen = set()
        for match, value in zip(positions, group.value):
            location = (ord(match[1].upper()) - ord("A"), int(match[2]) - 1)
            if location in seen:
                raise ValueError(f"Duplicate well location in plate {plate}")
            seen.add(location)
            values[location] = value
        fig = new_figure(10, 5)
        ax = fig.add_subplot(111)
        image = ax.imshow(np.ma.masked_invalid(values), cmap="magma")
        ax.set_xticks(range(values.shape[1]), range(1, values.shape[1] + 1))
        ax.set_yticks(range(values.shape[0]), [chr(65 + i) for i in range(values.shape[0])])
        ax.set_title(f"{plate} · {gate} · {metric}\nDRAFT screen summary")
        fig.colorbar(image, ax=ax, label=metric)
        fig.tight_layout()
        fig.savefig(out / f"plate-{index:03}.png", dpi=150)
    if digest(source) != source_fingerprint:
        raise ValueError("Source summary changed during screen analysis")
    (out / "screen.json").write_text(
        json.dumps(
            {
                "source_summary_sha256": source_fingerprint,
                "gate": gate,
                "metric": metric,
                "min_events": min_events,
                "hit_threshold": hit_threshold,
                "normalization": "100 * (value - negative median) / (positive median - negative median), within plate",
                "replication": "Descriptive well-level summaries; no event-level hypothesis tests",
                "reviewed": False,
            },
            indent=2,
        )
        + "\n"
    )
    return table


def screen_report(run, output, gate, metric="percent_parent", min_events=100, hit_threshold=None):
    """Publish a complete screen summary atomically; failures leave no output directory."""
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("Screen output already exists; choose a new directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".agentflow-screen-", dir=out.parent))
    try:
        table = _screen_report(run, temporary / "result", gate, metric, min_events, hit_threshold)
        if out.exists():
            raise ValueError("Output appeared during screen analysis")
        (temporary / "result").rename(out)
        return table
    finally:
        shutil.rmtree(temporary)
