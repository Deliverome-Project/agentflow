"""The run output format other tools read: change it only together with them.

deliverome-analysis indexes every published run into a shared SQL database
(deliverome_analysis.qcdb, FLOW_* constants) and queries events across runs with DuckDB
(deliverome_analysis.flowdb). They read the columns and keys pinned here. A failure here means
a format change: update this test AND those readers in the same change, or the shared index
starts listing published runs under build_errors instead of indexing them.
"""

import json
import re

import flowio
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml

from agentflow.batch import run_batch
from agentflow.engine import save_recipe
from agentflow.sample_sheet import draft_sample_sheet

SUMMARY_REQUIRED = {
    "sample_id", "gate", "parent", "count", "parent_count", "percent_parent", "percent_total",
}  # fmt: skip
SUMMARY_OPTIONAL = {"reviewed", "experiment_label", "is_example"}
STAT_COLUMN = re.compile(
    r"^(finite_signal_count|(?:median|mean|min|max|p05|p25|p75|p95|sd)_signal):(?P<det>.+)$"
)
RUN_JSON_KEYS = {"inputs", "agentflow", "recipe_sha256", "signal_space", "versions"}
INPUT_KEYS = {"sample_id", "sha256", "signal_space"}
EVENT_REQUIRED = {"sample_id", "event_index"}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("contract")
    truth = np.array([[10.0, 20.0], [100.0, 200.0], [-3.0, 0.0]])
    for i in (1, 2):
        with (d / f"{i}.fcs").open("wb") as handle:
            flowio.create_fcs(handle, truth.ravel().tolist(), ["A", "B"])
    annotations = d / "annotations.yaml"
    annotations.write_text(
        yaml.safe_dump(
            {"samples": [{"file": "1.fcs", "metadata": {"group": "T", "well": "A01"}, "reviewed": False}]}
        )
    )
    draft_sample_sheet(d, d / "sheet", annotations)
    save_recipe(
        d / "recipe.yaml",
        {
            "version": 1,
            "compensation": {"mode": "none"},
            "transforms": {"A": {"kind": "linear"}, "B": {"kind": "linear"}},
            "gates": [
                {
                    "name": "positive",
                    "parent": "root",
                    "kind": "range",
                    "channels": ["A"],
                    "bounds": [0, 1000],
                }
            ],
        },
    )
    run_batch(d / "sheet" / "samples.csv", d / "recipe.yaml", d / "run")
    return d / "run"


def test_summary_columns(run):
    summary = pd.read_csv(run / "summary.csv")
    cols = set(summary.columns)
    assert SUMMARY_REQUIRED <= cols
    outside = [
        c for c in cols
        if c not in SUMMARY_REQUIRED | SUMMARY_OPTIONAL
        and not c.startswith("metadata:") and not STAT_COLUMN.match(c)
    ]  # fmt: skip
    assert outside == [], "new summary.csv columns: teach deliverome_analysis.qcdb about them"
    stats = [c for c in cols if STAT_COLUMN.match(c)]
    assert {STAT_COLUMN.match(c)["det"] for c in stats} == {"A", "B"}
    assert all(pd.api.types.is_numeric_dtype(summary[c]) for c in stats)
    assert any(c.startswith("metadata:") for c in cols)


def test_run_json_keys(run):
    provenance = json.loads((run / "run.json").read_text())
    assert RUN_JSON_KEYS <= set(provenance)
    assert provenance["inputs"] and all(INPUT_KEYS <= set(i) for i in provenance["inputs"])
    assert {"version", "git_commit"} <= set(provenance["agentflow"])


def test_event_columns(run):
    schema = pq.read_schema(run / "events.parquet")
    names = set(schema.names)
    assert EVENT_REQUIRED <= names
    for prefix in ("raw:", "signal:"):
        assert {n[len(prefix) :] for n in names if n.startswith(prefix)} == {"A", "B"}
    gates = [n for n in names if n.startswith("gate:")]
    assert {"gate:root", "gate:positive"} <= set(gates)
    assert all(str(schema.field(g).type) == "bool" for g in gates)
