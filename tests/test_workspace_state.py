"""Synthetic workspace safety, recovery and all-event quadrant conservation."""

import copy

import numpy as np
import pytest

from agentflow import flowkit
from agentflow.editor_state import EditorState
from agentflow.engine import analyze_sample, build_strategy, evaluate, prepare
from agentflow.recipes import load_recipe, save_recipe, validate


@pytest.fixture
def state(tmp_path):
    recipe = {
        "version": 1,
        "compensation": {"mode": "none"},
        "transforms": {"X": {"kind": "linear"}, "Y": {"kind": "linear"}},
        "gates": [
            {
                "name": "cells",
                "kind": "rectangle",
                "parent": "root",
                "channels": ["X", "Y"],
                "bounds": [-2, 2, -2, 2],
                "reviewed": True,
            }
        ],
    }
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    sample = flowkit.Sample(
        np.array([[x, y] for x in [-1.0, 0.0, 1.0] for y in [-1.0, 0.0, 1.0]]),
        sample_id="synthetic",
        channel_labels=["X", "Y"],
    )
    return EditorState(prepare(sample, recipe), recipe, path)


def test_unfinished_gate_has_no_count_and_blocks_execution_export(state):
    before = state.counts()
    state.add_draft("new", "cells", ["X", "Y"])
    assert state.counts() == before
    assert state.gate("new") is None
    for run in (
        lambda: evaluate(state.prepared, state.recipe),
        lambda: build_strategy(state.recipe),
        lambda: analyze_sample(state.prepared.sample, state.recipe),
    ):
        with pytest.raises(ValueError, match="unfinished.*new"):
            run()
    state.save()
    assert load_recipe(state.path)["draft_gates"][0]["name"] == "new"
    state.draft_type("new", "polygon")
    state.complete_draft("new", {"vertices": [[-1.5, -1.5], [1.5, -1.5], [1.5, 1.5], [-1.5, 1.5]]})
    assert state.counts()["new"] == 9
    assert not state.gate("new")["reviewed"]
    evaluate(state.prepared, state.recipe)
    state.travel()
    assert state.draft("new") and "new" not in state.counts()
    state.travel(redo=True)
    assert state.counts()["new"] == 9


def test_drafts_reject_duplicate_name_missing_parent_and_empty_geometry(state):
    for name, parent, channels in (
        ("cells", "root", ["X", "Y"]),
        ("new", "absent", ["X", "Y"]),
        ("new", "cells", ["X", "X"]),
    ):
        with pytest.raises(ValueError):
            state.add_draft(name, parent, channels)
    assert not state.dirty
    state.add_draft("new", "cells", ["X", "Y"])
    with pytest.raises(ValueError):
        state.complete_draft("new", {"bounds": [0, 0, 0, 0]})
    assert state.draft("new")
    state.rename_population("cells", "parent renamed")
    assert state.draft("new")["parent"] == "parent renamed"
    state.delete_population("new")
    assert not state.recipe["draft_gates"]


def test_quadrant_boundary_conservation_and_linked_sample_edits(state):
    state.quadrants("reporters", "cells", ["X", "Y"], 0.0, 0.0)
    names = ["reporters " + s for s in ("--", "+-", "-+", "++")]
    masks = state.masks()
    assert [int(masks[n].sum()) for n in names] == [1, 2, 2, 4]
    np.testing.assert_array_equal(sum(masks[n].astype(int) for n in names), masks["cells"].astype(int))
    state.sample_scope, state.sample_id = True, "synthetic"
    state.move_quadrants(names[0], 1.0, 1.0)
    assert [state.counts()[n] for n in names] == [4, 2, 2, 1]
    shared = evaluate(state.prepared, state.recipe)
    assert [int(shared[n].sum()) for n in names] == [1, 2, 2, 4]
    assert len(state.recipe["sample_overrides"]["synthetic"]) == 4
    state.save()
    validate(load_recipe(state.path))
    state.travel()
    assert [state.counts()[n] for n in names] == [1, 2, 2, 4]
    state.sample_scope = False
    state.delete_population(names[0])
    assert len(state.recipe["gates"]) == 1


def test_quadrants_cannot_be_partially_moved_or_created(state):
    before = copy.deepcopy(state.recipe)
    with pytest.raises(ValueError):
        state.quadrants("bad", "cells", ["X", "X"], 0, 0)
    assert state.recipe == before
    state.quadrants("q", "cells", ["X", "Y"], 0.0, 0.0)
    with pytest.raises(ValueError, match="linked"):
        state.geometry("q --", "bounds", [None, 0.5, None, 0.0])


def test_recovery_checkpoint_and_disk_conflict(state):
    state.checkpoint("Before drawing")
    state.add_draft("new", "cells", ["X", "Y"])
    assert state.recovery_path.exists()
    restored = EditorState(state.prepared, load_recipe(state.path), state.path)
    assert restored.recovery_pending
    restored.recover()
    assert restored.recipe == state.recipe
    restored.restore_checkpoint("Before drawing")
    assert not restored.recipe.get("draft_gates")
    restored.travel()
    assert restored.draft("new")
    with pytest.raises(ValueError, match="already exists"):
        restored.checkpoint("Before drawing")
    with pytest.raises(ValueError):
        restored.checkpoint("../escape")
    changed = copy.deepcopy(state.initial)
    changed["gates"][0]["bounds"] = [-3, 3, -3, 3]
    save_recipe(state.path, changed)
    with pytest.raises(ValueError, match="different saved revision"):
        state.recover()
    with pytest.raises(ValueError, match="changed on disk"):
        state.save()


def test_batch_blocks_unfinished_before_creating_output(state, tmp_path):
    from agentflow.batch import run_batch

    state.add_draft("new", "cells", ["X", "Y"])
    state.save()
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="unfinished"):
        run_batch(tmp_path / "missing.csv", state.path, output)
    assert not output.exists()


def test_range_draft_single_detector_and_transformed_quadrants(state):
    state.add_draft("range", "cells", ["X"], "range")
    state.complete_draft("range", {"bounds": [0.0, 1.0]})
    assert state.counts()["range"] == 3
    candidate = copy.deepcopy(state.recipe)
    candidate["transforms"] = {c: {"kind": "asinh", "cofactor": 0.5} for c in ("X", "Y")}
    state.apply(candidate, reprepare=True)
    state.quadrants("q", "cells", ["X", "Y"], 0.0, 0.0)
    masks = state.masks()
    names = ["q " + s for s in ("--", "+-", "-+", "++")]
    np.testing.assert_array_equal(sum(masks[n].astype(int) for n in names), masks["cells"].astype(int))


def test_existing_recovery_is_not_overwritten_before_explicit_recovery(state):
    state.add_draft("unsaved", "cells", ["X", "Y"])
    before = state.recovery_path.read_bytes()
    reopened = EditorState(state.prepared, load_recipe(state.path), state.path)
    reopened.add_draft("different", "cells", ["X", "Y"])
    assert reopened.recovery_path.read_bytes() == before
    with pytest.raises(ValueError, match="Recover or discard"):
        reopened.save()
    reopened.recover()
    assert reopened.draft("unsaved") and not reopened.draft("different")


def test_new_workspace_features_require_schema_version_two(state):
    assert state.recipe["version"] == 1
    state.add_draft("new", "cells", ["X", "Y"])
    assert state.recipe["version"] == 2
    invalid = copy.deepcopy(state.recipe)
    invalid["version"] = 1
    with pytest.raises(ValueError, match="version 2"):
        validate(invalid)
    state.travel()
    assert state.recipe["version"] == 1
    state.quadrants("q", "cells", ["X", "Y"], 0.0, 0.0)
    assert state.recipe["version"] == 2
    state.save()
    assert load_recipe(state.path)["version"] == 2


def test_parent_deletion_includes_unfinished_children_in_confirmation(state):
    candidate = copy.deepcopy(state.recipe)
    candidate["gates"].append({"name": "other", "parent": "root", "kind": "range",
                               "channels": ["X"], "bounds": [-2, 2]})
    state.apply(candidate)
    state.add_draft("new", "cells", ["X", "Y"])
    assert state.deletion_set("cells") == ["cells", "new"]
    state.delete_population("cells")
    assert state.gate("other") and not state.draft("new")
    state.travel()
    assert state.gate("cells") and state.draft("new")
