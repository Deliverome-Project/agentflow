import copy
import json
from types import SimpleNamespace

import flowio
import matplotlib
import numpy as np
import pandas as pd
import pytest

from agentflow import flowkit as fk

matplotlib.use("Agg")

from agentflow import analyze_sample, save_recipe
from agentflow.batch import run_batch
from agentflow.editor import GateEditor
from agentflow.engine import evaluate, prepare, validate


@pytest.fixture
def recipe():
    return {
        "version": 1,
        "compensation": {"mode": "matrix", "detectors": ["A-A", "B-A"], "values": [[1, 0.15], [0.08, 1]]},
        "transforms": {"A-A": {"kind": "asinh", "cofactor": 100}, "B-A": {"kind": "linear"}},
        "gates": [
            {
                "name": "a",
                "parent": "root",
                "kind": "rectangle",
                "channels": ["A-A", "B-A"],
                "bounds": [np.arcsinh(0.5), np.arcsinh(2), -100, 300],
            },
            {
                "name": "both",
                "parent": "a",
                "kind": "polygon",
                "channels": ["A-A", "B-A"],
                "vertices": [[0, 100], [2, 100], [2, 200], [0, 200]],
            },
        ],
    }


def sample(recipe):
    truth = np.array([[10.0, 20.0], [120.0, 20.0], [120.0, 150.0], [10.0, 150.0]])
    measured = truth @ np.asarray(recipe["compensation"]["values"])
    return fk.Sample(measured[:, ::-1], sample_id="s", channel_labels=["B-A", "A-A"])


def test_compensation_labels_transforms_and_hierarchy(recipe):
    prepared = prepare(sample(recipe), recipe)
    np.testing.assert_allclose(prepared.values["A-A"], [10, 120, 120, 10], atol=1e-4)
    np.testing.assert_allclose(
        prepared.transformed["A-A"], np.arcsinh(np.array([10, 120, 120, 10]) / 100), atol=1e-6
    )
    masks = evaluate(prepared, recipe)
    np.testing.assert_array_equal(masks["a"], [False, True, True, False])
    np.testing.assert_array_equal(masks["both"], [False, False, True, False])
    stats = analyze_sample(sample(recipe), recipe).set_index("gate")
    assert stats.loc["both", "percent_parent"] == 50
    assert stats.loc["both", "median_signal:A-A"] == pytest.approx(120)


def test_empty_parent_is_missing_percentage(recipe):
    recipe["gates"][0]["bounds"] = [10, 11, 0, 300]
    stats = analyze_sample(sample(recipe), recipe).set_index("gate")
    assert stats.loc["both", "count"] == 0
    assert pd.isna(stats.loc["both", "percent_parent"])


def test_missing_fcs_compensation_fails(recipe):
    s = sample(recipe)
    recipe["compensation"] = {"mode": "fcs"}
    with pytest.raises(ValueError, match="no spillover"):
        prepare(s, recipe)


def test_invalid_matrix_and_parent(recipe):
    broken = copy.deepcopy(recipe)
    broken["compensation"]["values"] = [[1, 1], [1, 1]]
    with pytest.raises(ValueError, match="singular"):
        validate(broken)
    recipe["gates"][0]["parent"] = "both"
    with pytest.raises(ValueError, match="parents"):
        validate(recipe)


def test_batch_replay_and_metadata(tmp_path, recipe):
    s = sample(recipe)
    with (tmp_path / "s.fcs").open("wb") as handle:
        flowio.create_fcs(handle, s.get_events(source="raw").ravel().tolist(), s.pnn_labels)
    samples = tmp_path / "samples.csv"
    samples.write_text("sample_id,fcs_path,well,condition\ns,s.fcs,A01,control\n")
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    first = run_batch(samples, path, tmp_path / "one")
    second = run_batch(samples, path, tmp_path / "two")
    pd.testing.assert_frame_equal(first, second)
    assert first["metadata:well"].eq("A01").all()
    import yaml

    snapshot = yaml.safe_load((tmp_path / "one/reproducibility.yaml").read_text())
    assert "detectors" in snapshot["run"]["inputs"][0]["instrument"]
    assert (tmp_path / "one/gates-0001.png").exists()
    import base64
    import re

    # Copying only the HTML must retain exact image content, without PNG requests.
    html = (tmp_path / "one/report.html").read_text()
    standalone = tmp_path / "standalone.html"
    standalone.write_text(html)
    sources = re.findall(r"<img src='([^']+)'", standalone.read_text())
    assert sources and all(source.startswith("data:image/png;base64,") for source in sources)
    assert base64.b64decode(sources[0].split(",", 1)[1]) == (tmp_path / "one/gates-0001.png").read_bytes()

    assert json.loads((tmp_path / "one/run.json").read_text()) == json.loads(
        (tmp_path / "two/run.json").read_text()
    )
    import yaml

    snapshot = tmp_path / "one/reproducibility.yaml"
    saved = yaml.safe_load(snapshot.read_text())
    assert len(saved["agentflow"]["git_commit"]) == 40
    assert len(saved["agentflow"]["source_sha256"]) == 64
    replay = run_batch(samples, snapshot, tmp_path / "yaml-replay")
    pd.testing.assert_frame_equal(first, replay)
    with pytest.raises(ValueError, match="exists"):
        run_batch(samples, path, tmp_path / "one")
    samples.write_text("sample_id,fcs_path\ns,missing.fcs\n")
    with pytest.raises(OSError):
        run_batch(samples, path, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()


def test_editor_save_cancel_and_conflict(tmp_path, recipe):
    import matplotlib.pyplot as plt

    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    before = path.read_bytes()
    prepared = prepare(sample(recipe), recipe)
    editor = GateEditor(prepared, recipe, "a", path)
    editor.selector.extents = [0, 1.4, -100, 300]
    editor.rectangle_changed(SimpleNamespace(), SimpleNamespace())
    plt.close(editor.fig)
    assert path.read_bytes() == before and not editor.saved
    editor = GateEditor(prepared, recipe, "a", path)
    editor.selector.extents = [0, 1.4, -100, 300]
    editor.save()
    assert editor.saved
    changed = json.loads(path.read_text())
    assert changed["gates"][0]["bounds"] == [0, 1.4, -100, 300]
    editor = GateEditor(prepared, changed, "a", path)
    path.write_text(path.read_text() + "\n")
    editor.save()
    assert not editor.saved
    assert "changed on disk" in editor.status.get_text()
    plt.close(editor.fig)


@pytest.mark.parametrize("name", ["a", "both"])
def test_editor_unchanged_gate_roundtrip(tmp_path, recipe, name):
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    editor = GateEditor(prepare(sample(recipe), recipe), recipe, name, path)
    editor.save()
    assert editor.saved
    assert json.loads(path.read_text()) == recipe
