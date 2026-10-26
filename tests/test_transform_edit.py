"""Editable detector transforms on the synthetic demo: gates keep their raw-signal boundaries."""

import copy
import json
import os

import numpy as np
import pytest

from agentflow import transform_edit
from agentflow.demo import make_demo
from agentflow.editor_state import EditorState
from agentflow.engine import make_transform, prepare
from agentflow.overrides import effective_recipe
from agentflow.recipes import load_recipe, save_recipe
from agentflow.samples import read_samples
from agentflow.transform_edit import count_changes, retransform

# Densified polygons follow the migrated curve to 1e-4 of their extent. On the
# demo that leaves at most a few boundary events; allow 0.5% of the gate count.
POLYGON_COUNT_TOLERANCE = 0.005


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("transforms") / "demo")


@pytest.fixture(scope="module")
def records(demo):
    return read_samples(demo / "workflow/samples.csv")


@pytest.fixture
def recipe(demo):
    """Demo gates plus a rectangle and a polygon on BL1-A × YL2-A, all reviewed."""
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    recipe["gates"] += [
        {"name": "rect", "parent": "live", "kind": "rectangle", "channels": ["BL1-A", "YL2-A"],
         "bounds": [0.5, 0.95, 0.5, 0.95]},
        {"name": "poly", "parent": "live", "kind": "polygon", "channels": ["BL1-A", "YL2-A"],
         "vertices": [[0.2, 0.2], [0.9, 0.3], [0.85, 0.9], [0.3, 0.7]]},
        {"name": "poly_child", "parent": "poly", "kind": "range", "channels": ["RL1-A"],
         "bounds": [0.6, None]},
    ]
    recipe["sample_overrides"] = {"DUMMY-2": {"rect": {"bounds": [0.45, 0.9, 0.55, 0.95]}}}
    for gate in recipe["gates"]:
        gate["reviewed"] = True
    return recipe


def with_w(recipe, channel, w):
    spec = copy.deepcopy(recipe["transforms"][channel])
    spec["parameters"]["param_w"] = w
    return spec


def assert_counts_preserved(changes, migrated_kinds):
    """Range/rectangle/unaffected gates exact; polygons within the stated tolerance."""
    for name, (before, after) in changes.items():
        if migrated_kinds.get(name) == "polygon":
            assert abs(after - before) <= max(1, POLYGON_COUNT_TOLERANCE * before), (name, before, after)
        else:
            assert after == before, (name, before, after)


def kinds(recipe, names):
    """Migrated gate kinds; descendants of a migrated polygon inherit its tolerance."""
    result = {}
    for gate in recipe["gates"]:
        if gate["name"] in names:
            result[gate["name"]] = gate["kind"]
        if result.get(gate["parent"]) == "polygon":
            result[gate["name"]] = "polygon"
    return result


@pytest.mark.parametrize(
    "spec",
    [
        {"w": 0.0},
        {"w": 1.0},
        {"w": 1.5},
        {"kind": "asinh", "cofactor": 150},
        {"kind": "linear"},
    ],
)
def test_transform_change_preserves_counts_on_every_demo_sample(recipe, records, spec):
    new_spec = with_w(recipe, "BL1-A", spec["w"]) if "w" in spec else spec
    candidate, migrated = retransform(recipe, "BL1-A", new_spec)
    assert set(migrated) == {"gfp", "rect", "poly"}
    for record in records:
        effective = [effective_recipe(r, record["sample_id"]) for r in (recipe, candidate)]
        changes = count_changes(record["fcs_path"], *effective)
        assert_counts_preserved(changes, kinds(recipe, migrated))
        assert changes["rect"][0] > 0 and changes["poly"][0] > 0


def test_scatter_polygons_survive_linear_to_logicle(recipe, records):
    spec = {"kind": "logicle", "parameters": {"param_t": 262144, "param_w": 0.5, "param_m": 4.5, "param_a": 0}}
    candidate, migrated = retransform(recipe, "FSC-A", spec)
    assert migrated == ["cells", "singlets"]
    singlets = next(g for g in candidate["gates"] if g["name"] == "singlets")
    assert len(singlets["vertices"]) > 4  # Straight linear edges are curved on logicle.
    changes = count_changes(records[2]["fcs_path"], recipe, candidate)
    assert_counts_preserved(changes, kinds(recipe, migrated))


def test_migrated_geometry_keeps_raw_signal_boundaries(recipe):
    new_spec = with_w(recipe, "BL1-A", 1.0)
    candidate, _ = retransform(recipe, "BL1-A", new_spec)
    old_t, new_t = make_transform(recipe["transforms"]["BL1-A"]), make_transform(new_spec)
    old = {g["name"]: g for g in recipe["gates"]}
    new = {g["name"]: g for g in candidate["gates"]}
    np.testing.assert_allclose(
        new_t.inverse(np.array(new["gfp"]["bounds"])), old_t.inverse(np.array(old["gfp"]["bounds"])), rtol=1e-9
    )
    a, b, c, d = new["rect"]["bounds"]
    np.testing.assert_allclose(new_t.inverse(np.array([a, b])), old_t.inverse(np.array([0.5, 0.95])), rtol=1e-9)
    assert [c, d] == [0.5, 0.95]  # The unchanged detector keeps its coordinates.
    raw_old = old_t.inverse(np.array(old["poly"]["vertices"])[:, 0])
    vertices = np.array(new["poly"]["vertices"])
    raw_new = new_t.inverse(vertices[:, 0])
    for x, yv in zip(raw_old, np.array(old["poly"]["vertices"])[:, 1]):
        assert np.any(np.isclose(raw_new, x, rtol=1e-9) & np.isclose(vertices[:, 1], yv))
    # Sample exceptions migrate with the shared gate.
    override = candidate["sample_overrides"]["DUMMY-2"]["rect"]["bounds"]
    np.testing.assert_allclose(new_t.inverse(np.array(override[:2])), old_t.inverse(np.array([0.45, 0.9])), rtol=1e-9)
    assert override[2:] == [0.55, 0.95]


@pytest.fixture
def state(recipe, records, tmp_path):
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    return EditorState(prepare(records[1]["fcs_path"], recipe), recipe, path)


def test_editor_transaction_invalidates_reviews_saves_runs_and_undoes(state, recipe, records, tmp_path):
    from agentflow.batch import run_batch

    state.sample_id = "DUMMY-2"
    before = state.counts()
    migrated = state.set_transform("BL1-A", with_w(recipe, "BL1-A", 1.5))
    assert set(migrated) == {"gfp", "rect", "poly"}
    reviewed = {g["name"]: g["reviewed"] for g in state.recipe["gates"]}
    assert not any(reviewed[n] for n in ["gfp", "rect", "poly", "poly_child"])
    assert all(reviewed[n] for n in ["cells", "singlets", "live", "mscarlet", "cy5"])
    assert state.history_labels[-1] == "transform BL1-A"
    assert state.recipe["transforms"]["BL1-A"]["parameters"]["param_w"] == 1.5
    assert state.prepared.transformed["BL1-A"].to_numpy() == pytest.approx(
        make_transform(state.recipe["transforms"]["BL1-A"]).apply(state.prepared.values["BL1-A"].to_numpy())
    )
    assert_counts_preserved(
        {n: (before[n], c) for n, c in state.counts().items()}, kinds(recipe, migrated)
    )

    state.save()
    assert load_recipe(state.path) == state.recipe
    sheet = tmp_path / "samples.csv"
    sheet.write_text(
        "sample_id,fcs_path\n" + "".join(f"{r['sample_id']},{r['fcs_path']}\n" for r in records)
    )
    original = tmp_path / "original.json"
    save_recipe(original, recipe)
    old = run_batch(sheet, original, tmp_path / "old").set_index(["sample_id", "gate"])["count"]
    new = run_batch(sheet, state.path, tmp_path / "new").set_index(["sample_id", "gate"])["count"]
    for (sample_id, gate), count in old.items():
        if gate in {"poly", "poly_child"}:
            assert abs(new[sample_id, gate] - count) <= max(1, POLYGON_COUNT_TOLERANCE * count)
        else:
            assert new[sample_id, gate] == count, (sample_id, gate)
    batch_recipe = json.loads((tmp_path / "new/recipe.json").read_text())
    assert batch_recipe["transforms"]["BL1-A"] == state.recipe["transforms"]["BL1-A"]

    state.travel()
    assert state.recipe == recipe
    assert state.counts() == before
    assert state.prepared.transformed["BL1-A"].to_numpy() == pytest.approx(
        make_transform(recipe["transforms"]["BL1-A"]).apply(state.prepared.values["BL1-A"].to_numpy())
    )


def test_linked_quadrants_stay_linked_with_identical_counts(state, recipe):
    state.quadrants("Q", "live", ["BL1-A", "YL2-A"], 0.6, 0.6)
    before = state.counts()
    state.set_transform("BL1-A", {"kind": "asinh", "cofactor": 300})
    quadrants = [g for g in state.recipe["gates"] if g["kind"] == "quadrant"]
    assert len({next(v for v in g["bounds"][:2] if v is not None) for g in quadrants}) == 1
    assert all(not g["reviewed"] for g in quadrants)
    after = state.counts()
    assert {n: after[n] for n in before if n.startswith("Q")} == {n: before[n] for n in before if n.startswith("Q")}
    assert sum(after[g["name"]] for g in quadrants) == after["live"]


def test_transform_change_is_shared_and_validated(state, recipe):
    state.sample_scope = True
    with pytest.raises(ValueError, match="shared"):
        state.set_transform("BL1-A", with_w(recipe, "BL1-A", 1.0))
    state.sample_scope = False
    with pytest.raises(ValueError, match="logicle"):
        state.set_transform("BL1-A", with_w(recipe, "BL1-A", 3.0))  # 2W > M.
    assert state.recipe == recipe and not state.history


def test_skipping_gate_migration_is_caught(recipe, records, monkeypatch):
    """Seeded defect: without migration the same coordinates select different events."""
    monkeypatch.setattr(transform_edit, "migrate_geometry", lambda geometry, *_: {})
    candidate, migrated = retransform(recipe, "BL1-A", with_w(recipe, "BL1-A", 1.5))
    changes = count_changes(records[2]["fcs_path"], recipe, candidate)
    with pytest.raises(AssertionError):
        assert_counts_preserved(changes, kinds(recipe, migrated))


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(demo, recipe, records, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets as W

    from agentflow.workbench import ScreenWindow

    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    w = ScreenWindow(records, copy.deepcopy(recipe), "rect", path)
    w.show()
    app.processEvents()
    yield w
    w.discarding = True
    w.close()
    app.processEvents()


def test_transform_dialog_previews_applies_resets_and_undoes(window, recipe):
    window.gates.setCurrentRow(window.names.index("rect"))
    counts = window.state.counts()
    dialog = window.transform_dialog("BL1-A")
    assert dialog.channel == "BL1-A" and dialog.kind.currentData() == "logicle"
    assert dialog.w_note.isVisibleTo(dialog) and "linear region" in dialog.w_note.text()
    dialog.spins["param_w"].setValue(1.5)
    dialog.preview()
    rows = {dialog.table.item(r, 0).text(): dialog.table.item(r, 2).text() for r in range(dialog.table.rowCount())}
    assert set(rows) == {"gfp", "rect", "poly"}
    assert "unchanged" in rows["rect"] and "unchanged" in rows["gfp"]
    assert dialog.ax.get_xlabel().startswith("BL1-A") or "BL1" in dialog.ax.get_xlabel()
    assert dialog.ax.lines  # The migrated rectangle is drawn on the new axis.

    dialog.spins["param_w"].setValue(3.0)  # Invalid: 2W > M.
    dialog.preview()
    assert not dialog.apply_button.isEnabled() and "Not applicable" in dialog.status.text()
    dialog.reset()
    assert dialog.spec() == recipe["transforms"]["BL1-A"]
    dialog.kind.setCurrentIndex(dialog.kind.findData("asinh"))
    assert not dialog.w_note.isVisibleTo(dialog) and dialog.cofactor.isEnabled()
    dialog.kind.setCurrentIndex(dialog.kind.findData("logicle"))
    dialog.spins["param_w"].setValue(1.5)
    dialog.apply()

    assert window.state.recipe["transforms"]["BL1-A"]["parameters"]["param_w"] == 1.5
    assert not window.state.gate("rect")["reviewed"]
    old_t = make_transform(recipe["transforms"]["BL1-A"])
    new_t = make_transform(window.state.recipe["transforms"]["BL1-A"])
    np.testing.assert_allclose(
        new_t.inverse(np.array(window.state.gate("rect")["bounds"][:2])), old_t.inverse(np.array([0.5, 0.95]))
    )
    after = window.state.counts()
    assert {n: c for n, c in after.items() if not n.startswith("poly")} == {
        n: c for n, c in counts.items() if not n.startswith("poly")
    }
    assert "Undo" in window.message.text()
    window.travel(False)
    assert window.state.recipe["transforms"] == recipe["transforms"]
    assert window.state.gate("rect")["reviewed"]
