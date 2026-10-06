"""Correctness and work-avoidance regressions; no machine-dependent timing assertions."""

import copy

import numpy as np
import pandas as pd
import pytest
from test_screening import demo  # noqa: F401

from agentflow.engine import evaluate, prepare, summarize
from agentflow.plot_views import apply_axes
from agentflow.plots import new_figure
from agentflow.sample_summary import signal_summary
from agentflow.samples import SampleSession, read_samples


def inputs(demo):  # noqa: F811
    import json

    return read_samples(demo / "workflow/samples.csv"), json.loads(
        (demo / "workflow/recipe.json").read_text()
    )


def test_summary_survives_event_cache_eviction(demo, monkeypatch):  # noqa: F811
    records, recipe = inputs(demo)
    session = SampleSession(records, limit=1)
    expected = signal_summary(records, session, recipe, "gfp", "BL1-A", "median")
    assert len(session.prepared) == 1

    def unexpected(*args, **kwargs):
        raise AssertionError("An unchanged summary must not reload events")

    monkeypatch.setattr(session, "get", unexpected)
    actual = signal_summary(records, session, recipe, "gfp", "BL1-A", "median")
    pd.testing.assert_frame_equal(actual, expected)
    changed = copy.deepcopy(recipe)
    changed["display"] = {"color": "red"}
    changed["gates"][0]["reviewed"] = True
    pd.testing.assert_frame_equal(
        signal_summary(records, session, changed, "gfp", "BL1-A", "median"), expected
    )


def test_summary_invalidation_and_all_event_counts(demo):  # noqa: F811
    records, recipe = inputs(demo)
    session = SampleSession(records, limit=1)
    record = records[0]
    first = session.metrics(record, recipe, "gfp", "BL1-A")
    prepared, masks = session.get(record, recipe)
    assert first["event_count"] == int(masks["gfp"].sum())
    assert first["median"] == np.median(prepared.values.loc[masks["gfp"], "BL1-A"])
    changed = copy.deepcopy(recipe)
    next(g for g in changed["gates"] if g["name"] == "gfp")["bounds"] = [100, None]
    empty = session.metrics(record, changed, "gfp", "BL1-A")
    assert empty["event_count"] == 0 and np.isnan(empty["median"])
    assert session.metrics(record, recipe, "gfp", "BL1-A") == first
    changed = copy.deepcopy(recipe)
    changed["compensation"] = {"mode": "none"}
    assert session.metrics(record, changed, "gfp", "BL1-A")["signal_space"] == "raw"
    changed = copy.deepcopy(recipe)
    changed.setdefault("sample_overrides", {})[record["sample_id"]] = {"gfp": {"bounds": [100, None]}}
    assert session.metrics(record, changed, "gfp", "BL1-A")["event_count"] == 0


def test_fingerprint_checked_in_preview(demo):  # noqa: F811
    records, recipe = inputs(demo)
    session = SampleSession(records)
    session.get(records[0], recipe)
    bad = {**records[0], "input_sha256": "0" * 64}
    with pytest.raises(ValueError, match="fingerprint"):
        session.get(bad, recipe)


def test_recipe_axes_are_affine_but_ticks_remain_signal_units(demo):  # noqa: F811
    _, recipe = inputs(demo)
    fig = new_figure()
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 1)
    apply_axes(ax, ["BL1-A"], recipe, ["recipe"])
    assert ax.xaxis.get_transform().is_affine
    np.testing.assert_array_equal(ax.xaxis.get_transform().transform([0.1, 0.8]), [0.1, 0.8])
    assert ax.xaxis.get_major_formatter()(0, 0) is not None


def test_gallery_extents_survive_eviction_and_invalidate(demo, monkeypatch):  # noqa: F811
    records, recipe = inputs(demo)
    session = SampleSession(records, limit=1)
    channels = ["FSC-A", "SSC-A"]
    limits = [session.plot_limits(r, recipe, "cells", channels) for r in records]
    assert len(session.prepared) == 1

    def unexpected(*args, **kwargs):
        raise AssertionError("reload")

    monkeypatch.setattr(session, "get", unexpected)
    for r, expected in zip(records, limits):
        np.testing.assert_array_equal(session.plot_limits(r, recipe, "cells", channels), expected)
    changed = copy.deepcopy(recipe)
    changed["gates"][0]["vertices"][0][0] += 1
    with pytest.raises(AssertionError, match="reload"):
        session.plot_limits(records[0], changed, "cells", channels)
    with pytest.raises(AssertionError, match="reload"):
        session.plot_limits(records[0], recipe, "cells", channels, full=True)


def test_statistics_match_independent_numpy_calculations(demo):  # noqa: F811
    records, recipe = inputs(demo)
    prepared = prepare(records[0]["fcs_path"], recipe)
    masks = evaluate(prepared, recipe)
    table = summarize(prepared, recipe, masks).set_index("gate")
    for name, mask in masks.items():
        for channel in recipe["transforms"]:
            values = prepared.values.loc[mask, channel].to_numpy()
            for label, q in [("p05", 0.05), ("p25", 0.25), ("p75", 0.75), ("p95", 0.95)]:
                assert table.loc[name, f"{label}_signal:{channel}"] == pytest.approx(np.quantile(values, q))
            assert table.loc[name, f"median_signal:{channel}"] == np.median(values)


def test_summary_cache_bounded_and_file_changes_invalidate(demo, tmp_path, monkeypatch):  # noqa: F811
    import os
    import shutil

    records, recipe = inputs(demo)
    local = tmp_path / "sample.fcs"
    shutil.copyfile(records[0]["fcs_path"], local)
    record = {**records[0], "fcs_path": str(local)}
    session = SampleSession([record], metric_limit=1)
    session.metrics(record, recipe, "gfp", "BL1-A")
    session.metrics(record, recipe, "root", "BL1-A")
    assert len(session.summaries) == 1
    old = local.stat()
    os.utime(local, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))

    def fail(*args, **kwargs):
        raise ValueError("reloaded changed file")

    monkeypatch.setattr(session, "get", fail)
    with pytest.raises(ValueError, match="reloaded changed file"):
        session.metrics(record, recipe, "root", "BL1-A")
    local.unlink()
    with pytest.raises(FileNotFoundError):
        session.metrics(record, recipe, "root", "BL1-A")


def test_parallel_qc_preserves_results_and_exports(demo, tmp_path):  # noqa: F811
    import pyarrow.parquet as pq

    from agentflow.batch import run_batch

    first = run_batch(demo / "workflow/samples.csv", demo / "workflow/recipe.json", tmp_path / "one")
    second = run_batch(
        demo / "workflow/samples.csv", demo / "workflow/recipe.json", tmp_path / "two", workers=2
    )
    pd.testing.assert_frame_equal(first, second)
    a, b = [pq.read_table(tmp_path / name / "events.parquet") for name in ["one", "two"]]
    assert a.equals(b)
    for path in (tmp_path / "one").glob("*.png"):
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes()
    for path in (tmp_path / "one").glob("*.xml"):
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes()


def test_qc_worker_failure_does_not_publish(demo, tmp_path):  # noqa: F811
    from agentflow.batch import run_batch
    from agentflow.recipes import save_recipe

    _, recipe = inputs(demo)
    recipe["display"] = {"opacity": "invalid-render-value"}
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    with pytest.raises(TypeError):
        run_batch(demo / "workflow/samples.csv", path, tmp_path / "failed", workers=2)
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".agentflow-*"))


def test_population_selection_and_unrelated_edits_reuse_summaries(demo, monkeypatch):  # noqa: F811
    records, recipe = inputs(demo)
    session = SampleSession(records, limit=1)
    signal_summary(records, session, recipe, "gfp", "BL1-A")

    def unexpected(*args, **kwargs):
        raise AssertionError("Unchanged ancestor populations must stay cached")

    monkeypatch.setattr(session, "get", unexpected)
    signal_summary(records, session, recipe, "root", "BL1-A")
    changed = copy.deepcopy(recipe)
    next(g for g in changed["gates"] if g["name"] == "gfp")["bounds"] = [100, None]
    signal_summary(records, session, changed, "root", "BL1-A")
    signal_summary(records, session, changed, "live", "BL1-A")


def test_summary_boolean_transform_and_matrix_invalidation(demo, tmp_path):  # noqa: F811
    import json

    records, recipe = inputs(demo)
    record = records[0]
    recipe["gates"].append(
        {
            "name": "either",
            "parent": "live",
            "kind": "boolean",
            "channels": ["BL1-A", "YL2-A"],
            "operation": "or",
            "references": ["gfp", "mscarlet"],
        }
    )
    session = SampleSession(records)
    original = session.metrics(record, recipe, "either", "BL1-A")
    assert original["event_count"] > 0
    changed = copy.deepcopy(recipe)
    for gate in changed["gates"]:
        if gate["name"] in {"gfp", "mscarlet"}:
            gate["bounds"] = [100, None]
    assert session.metrics(record, changed, "either", "BL1-A")["event_count"] == 0
    changed["transforms"]["BL1-A"] = {"kind": "linear"}
    _, masks = session.get(record, changed)
    result = session.metrics(record, changed, "either", "BL1-A")
    assert result["event_count"] == int(masks["either"].sum()) > 0
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps(recipe["compensation"]))
    assigned = {**record, "compensation_path": str(matrix)}
    first = session.metrics(assigned, recipe, "root", "BL1-A")
    spec = copy.deepcopy(recipe["compensation"])
    spec["values"] = np.eye(len(spec["detectors"])).tolist()
    matrix.write_text(json.dumps(spec))
    second = session.metrics(assigned, recipe, "root", "BL1-A")
    assert second["mean"] != first["mean"]
