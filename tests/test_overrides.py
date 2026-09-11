import copy
import json

import numpy as np
import pytest

from agentflow.control_review import export_control_review, resolve_config
from agentflow.demo import make_demo
from agentflow.editor_state import EditorState
from agentflow.engine import evaluate, load_recipe, prepare, validate
from agentflow.samples import read_samples, sample_recipe


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("exceptions") / "demo")


def test_override_validation_and_effective_native_masks(demo):
    recipe = load_recipe(demo / "workflow/recipe.json")
    records = read_samples(demo / "workflow/samples.csv")
    recipe["sample_overrides"] = {"DUMMY-1": {"live": {"bounds": [None, 0.1], "reviewed": False}}}
    validate(recipe)
    effective = sample_recipe(recipe, records[0])
    masks = evaluate(prepare(records[0]["fcs_path"], effective), effective)
    assert int(masks["live"].sum()) < 100
    assert sample_recipe(recipe, records[1])["gates"] == recipe["gates"]
    invalid = copy.deepcopy(recipe)
    invalid["sample_overrides"]["DUMMY-1"]["live"]["parent"] = "root"
    with pytest.raises(ValueError, match="only geometry"):
        validate(invalid)
    invalid = copy.deepcopy(recipe)
    invalid["sample_overrides"]["DUMMY-1"]["live"]["bounds"] = [10, 0]
    with pytest.raises(ValueError, match="minimum"):
        validate(invalid)


def test_override_reset_and_parent_review_invalidation(demo, tmp_path):
    recipe = load_recipe(demo / "workflow/recipe.json")
    for gate in recipe["gates"]:
        gate["reviewed"] = True
    state = EditorState(prepare(demo / "sample-1.fcs", recipe), recipe, tmp_path / "recipe.json")
    state.sample_id, state.sample_scope = "one", True
    state.geometry("live", "bounds", [None, 0.1])
    assert not state.gate("gfp")["reviewed"]
    assert state.gate("cells")["reviewed"]
    state.review("live")
    state.sample_scope = False
    with pytest.raises(ValueError, match="sample exception"):
        state.geometry("live", "bounds", [None, 0.2])
    state.geometry("cells", "vertices", [[1, 1], [100000, 1], [100000, 100000], [1, 100000]])
    assert not state.gate("live")["reviewed"]
    state.reset_override("live")
    assert state.gate("live")["bounds"] == recipe["gates"][2]["bounds"]
    assert not state.gate("live")["reviewed"]


def test_compensation_export_atomic_failure(demo, tmp_path):
    config = resolve_config(json.loads((demo / "controls.json").read_text()), demo)
    config["controls"][0]["positive_min"] = 1e15
    output = tmp_path / "bad-review"
    with pytest.raises(ValueError, match="too few"):
        export_control_review(config, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".compensation-*"))


def test_batch_records_exception_and_uses_same_masks(demo, tmp_path):
    from agentflow.batch import run_batch
    from agentflow.engine import save_recipe

    recipe = load_recipe(demo / "workflow/recipe.json")
    recipe["sample_overrides"] = {"DUMMY-1": {"live": {"bounds": [None, 0.1], "reviewed": False}}}
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    out = tmp_path / "run"
    run_batch(demo / "workflow/samples.csv", path, out)
    import pandas as pd

    summary = pd.read_csv(out / "summary.csv")
    row = summary[(summary.sample_id == "DUMMY-1") & (summary.gate == "live")].iloc[0]
    assert row["count"] < 100
    from agentflow import flowkit
    from agentflow.engine import evaluate, prepare
    from agentflow.samples import read_samples, sample_recipe

    records = read_samples(demo / "workflow/samples.csv")
    for index, record in enumerate(records, 1):
        effective = sample_recipe(recipe, record)
        prepared = prepare(record["fcs_path"], effective)
        restored = flowkit.parse_gating_xml(str(out / f"gates-{index:04d}.gatingml.xml"))
        result = restored.gate_sample(prepared.sample)
        for name, expected in evaluate(prepared, effective).items():
            if name != "root":
                np.testing.assert_array_equal(result.get_gate_membership(name), expected)

    assert (
        json.loads((out / "run.json").read_text())["inputs"][0]["gate_overrides"]
        == recipe["sample_overrides"]["DUMMY-1"]
    )


def test_export_requires_explicit_override_scope(demo, tmp_path, capsys):
    from agentflow.cli import main
    from agentflow.engine import save_recipe

    recipe = load_recipe(demo / "workflow/recipe.json")
    recipe["sample_overrides"] = {"DUMMY-1": {"live": {"bounds": [None, 0.1]}}}
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    args = [
        "export-gml",
        str(demo / "sample-1.fcs"),
        "--recipe",
        str(path),
        "--out",
        str(tmp_path / "gates.xml"),
    ]
    assert main(args) == 1
    assert "--sample-id" in capsys.readouterr().err
    assert main([*args, "--sample-id", "DUMMY-1"]) in (0, None)
    assert (tmp_path / "gates.xml").exists()
