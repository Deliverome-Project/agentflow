import copy
import json

import matplotlib.pyplot as plt
import numpy as np
import pytest

from agentflow import flowkit as fk
from agentflow import save_recipe
from agentflow.cli import main
from agentflow.compensation import estimate_controls, load_matrix, validate_compensation
from agentflow.demo import make_demo
from agentflow.editor import GateEditor
from agentflow.engine import analyze_sample, prepare
from agentflow.workflow import add_reporter, mark_unreviewed, scaffold


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("screen") / "dummy")


def test_compensation_estimate_recovers_known_matrix(demo):
    expected = load_matrix(demo / "expected-spillover.json")
    result = estimate_controls(demo / "controls.json")
    np.testing.assert_allclose(result["values"], expected["values"], atol=2e-4)
    assert all(c["positive_count"] == 1000 for c in result["estimation"]["controls"])
    assert not result["estimation"]["reviewed"]


def test_estimation_requires_all_controls_and_populations(demo, tmp_path):
    config = json.loads((demo / "controls.json").read_text())
    for control in config["controls"]:
        control["fcs_path"] = str(demo / control["fcs_path"])
    config["controls"][0]["positive_min"] = 1e9
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="too few"):
        estimate_controls(path)
    config["controls"].pop()
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="exactly one"):
        estimate_controls(path)


def test_matrix_csv_label_order_and_units(tmp_path):
    path = tmp_path / "matrix.csv"
    path.write_text("source,A,B\nA,1,.1\nB,.2,1\n")
    assert load_matrix(path)["detectors"] == ["A", "B"]
    path.write_text("source,A,B\nB,1,.1\nA,.2,1\n")
    with pytest.raises(ValueError, match="row labels"):
        load_matrix(path)
    with pytest.raises(ValueError, match="diagonal"):
        validate_compensation({"mode": "matrix", "detectors": ["A", "B"], "values": [[100, 10], [20, 100]]})


def test_default_gates_missing_channels_and_mapping(demo, tmp_path):
    recipe = scaffold(demo / "sample-1.fcs", tmp_path / "draft", example=True, compensation="none")
    assert [g["name"] for g in recipe["gates"]] == ["cells", "singlets"]
    assert {g["name"] for g in recipe["pending_gates"]} == {"live", "gfp", "mscarlet", "cy5"}
    with pytest.raises(ValueError, match="acquired"):
        add_reporter(recipe, demo / "sample-1.fcs", "cy5", "not-collected")
    recipe = add_reporter(recipe, demo / "sample-1.fcs", "gfp", "BL1-A")
    recipe = add_reporter(recipe, demo / "sample-1.fcs", "live", "BV1-A")
    assert next(g for g in recipe["gates"] if g["name"] == "gfp")["parent"] == "live"
    assert all(all(v is not None for v in g["bounds"]) for g in recipe["gates"] if g["kind"] == "range")
    with pytest.raises(ValueError, match="already assigned"):
        add_reporter(recipe, demo / "sample-1.fcs", "cy5", "BL1-A")


def test_range_boundaries_and_unbounded_ranges():
    sample = fk.Sample(np.array([[-1.0], [0.0], [1.0], [2.0]]), sample_id="s", channel_labels=["A"])
    recipe = {
        "version": 1,
        "compensation": {"mode": "none"},
        "transforms": {"A": {"kind": "linear"}},
        "gates": [
            {"name": "positive", "parent": "root", "kind": "range", "channels": ["A"], "bounds": [0, 2]}
        ],
    }
    assert analyze_sample(sample, recipe).set_index("gate").loc["positive", "count"] == 2
    recipe["gates"][0]["bounds"] = [None, 0]
    assert analyze_sample(sample, recipe).set_index("gate").loc["positive", "count"] == 1


def test_review_invalidation():
    recipe = {
        "gates": [
            {"name": "cells", "parent": "root", "reviewed": True},
            {"name": "singlets", "parent": "cells", "reviewed": True},
            {"name": "gfp", "parent": "singlets", "reviewed": True},
        ]
    }
    mark_unreviewed(recipe, "cells")
    assert not any(g["reviewed"] for g in recipe["gates"])


def test_workflow_editor_tabs_undo_and_range_roundtrip(demo, tmp_path):
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    editor = GateEditor(prepare(demo / "sample-1.fcs", recipe), recipe, None, path)
    for name in ["cells", "singlets", "live", "gfp", "mscarlet", "cy5"]:
        editor.select_gate(name)
    original = copy.deepcopy(editor.gate["bounds"])
    editor.range_changed(0.5, 3)
    editor.undo()
    assert editor.gate["bounds"] == original
    editor.redo()
    assert editor.gate["bounds"] == [0.5, 3]
    editor.undo()
    editor.save()
    assert json.loads(path.read_text()) == recipe
    assert editor.saved
    plt.close("all")


def test_pending_editor_and_headless_cli(demo, tmp_path, capsys):
    recipe = scaffold(demo / "sample-1.fcs", tmp_path / "draft", example=True, compensation="none")
    editor = GateEditor(prepare(demo / "sample-1.fcs", recipe), recipe, "cy5", tmp_path / "draft/recipe.json")
    assert editor.gate is None
    assert "NOT ANALYZED" in editor.heading.get_text()
    plt.close(editor.fig)
    assert main(["validate", str(tmp_path / "draft/recipe.json")]) == 0
    assert main(["inspect", str(demo / "sample-1.fcs")]) == 0
    assert (
        main(
            [
                "run",
                str(demo / "workflow/samples.csv"),
                "--recipe",
                str(demo / "workflow/recipe.json"),
                "--out",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )
    report = (tmp_path / "run/report.html").read_text()
    assert "DUMMY / EXAMPLE" in report and "NOT VALIDATED" in report
    assert (tmp_path / "run/time-0001.png").exists()
    assert (
        main(
            [
                "run",
                str(demo / "workflow/samples.csv"),
                "--recipe",
                str(demo / "workflow/recipe.json"),
                "--out",
                str(tmp_path / "run"),
            ]
        )
        == 1
    )
    assert "error" in capsys.readouterr().err


def test_gui_matrix_load_invalidation_and_undo(demo, tmp_path):
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    for gate in recipe["gates"]:
        gate["reviewed"] = True
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    editor = GateEditor(prepare(demo / "sample-1.fcs", recipe), recipe, "gfp", path)
    new = copy.deepcopy(recipe["compensation"])
    new["values"] = np.eye(4).tolist()
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps(new))
    editor.matrix_box.set_val(str(matrix))
    editor.apply_matrix()
    assert not any(g["reviewed"] for g in editor.recipe["gates"])
    np.testing.assert_array_equal(editor.prepared.matrix.matrix, np.eye(4))
    editor.undo()
    assert all(g["reviewed"] for g in editor.recipe["gates"])
    np.testing.assert_allclose(editor.prepared.matrix.matrix, recipe["compensation"]["values"])
    assert json.loads(path.read_text()) == recipe
    plt.close(editor.fig)


def test_default_singlet_band_does_not_expand_to_extreme_ratios(demo, tmp_path):
    recipe = scaffold(demo / "sample-1.fcs", tmp_path / "draft", example=True, compensation="none")
    gate = next(g for g in recipe["gates"] if g["name"] == "singlets")
    vertices = np.array(gate["vertices"])
    ratios = vertices[:, 1] / vertices[:, 0]
    assert ratios.max() / ratios.min() == pytest.approx(1.25 / 0.75)


def test_editor_resize_events_preserve_range_and_pending_panels(demo, tmp_path):
    from matplotlib.backend_bases import ResizeEvent

    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    editor = GateEditor(prepare(demo / "sample-1.fcs", recipe), recipe, "gfp", path)
    editor.fig.canvas.callbacks.exception_handler = None
    ResizeEvent("resize_event", editor.fig.canvas)._process()
    editor.fig.canvas.draw()
    assert editor.gate["bounds"] == next(g for g in recipe["gates"] if g["name"] == "gfp")["bounds"]
    plt.close(editor.fig)
