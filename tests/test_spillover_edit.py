"""Spillover editing in the N×N view, on the DUMMY demo with known spillover (synthetic only)."""

import copy
import json
import os

import numpy as np
import pytest
from matplotlib.figure import Figure

from agentflow.compensation_view import draw_compensation_matrix, matrix_channels
from agentflow.demo import make_demo
from agentflow.engine import prepare
from agentflow.recipes import digest
from agentflow.samples import read_samples
from agentflow.spillover_edit import (
    EDIT_METHOD,
    SpilloverDraft,
    compensate_events,
    drag_edit,
    save_edited_matrix,
    spec_sha256,
)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("spillover-edit") / "demo")


@pytest.fixture(scope="module")
def recipe(demo):
    return json.loads((demo / "workflow/recipe.json").read_text())


@pytest.fixture(scope="module")
def prepared(demo, recipe):
    # DUMMY-3: 60% of events are positive for each reporter, so every pair has a bright population.
    return prepare(read_samples(demo / "workflow/samples.csv")[2]["fcs_path"], recipe)


def drawn(prepared, recipe, draft=None):
    axes = draw_compensation_matrix(Figure(), prepared, recipe, matrix_channels(prepared), draft=draft)
    # Row BL1-A (y) against YL2-A (x): BL1 dye spills 8% into YL2 in the demo.
    return np.asarray(axes[("BL1-A", "YL2-A")].collections[0].get_offsets())


def bl1_only(offsets):
    """BL1-bright, YL2-dim events: the population whose YL2 position shows BL1 spillover."""
    return (offsets[:, 1] > np.quantile(offsets[:, 1], 0.7)) & (offsets[:, 0] < np.quantile(offsets[:, 0], 0.3))


def test_unedited_draft_is_flowkits_assigned_compensation(recipe, prepared, demo):
    draft = SpilloverDraft(recipe["compensation"])
    expected = json.loads((demo / "expected-spillover.json").read_text())
    np.testing.assert_allclose(draft.original, expected["values"], atol=0.01)
    np.testing.assert_array_equal(compensate_events(prepared.sample, draft.spec()), prepared.values.to_numpy())
    assert draft.spec() == recipe["compensation"]
    np.testing.assert_array_equal(drawn(prepared, recipe, draft.spec()), drawn(prepared, recipe))


def test_edit_moves_drawn_compensated_positions_in_the_expected_direction(recipe, prepared):
    base = drawn(prepared, recipe)
    bright = bl1_only(base)
    assert bright.sum() > 100
    draft = SpilloverDraft(recipe["compensation"])
    assigned = draft.values[1, 2]
    draft.set("BL1-A", "YL2-A", assigned + 0.07)
    over = drawn(prepared, recipe, draft.spec())
    # More BL1 spillover subtracted from YL2 pushes BL1-bright events left (down in YL2) ...
    assert np.median(over[bright, 0] - base[bright, 0]) < -0.01
    # ... and leaves BL1 itself and the BL1-dim events where they were ...
    np.testing.assert_allclose(over[:, 1], base[:, 1], atol=1e-3)
    dim = base[:, 1] < np.quantile(base[:, 1], 0.3)
    assert abs(np.median(over[dim, 0] - base[dim, 0])) < 0.005
    draft.set("BL1-A", "YL2-A", 0.0)
    under = drawn(prepared, recipe, draft.spec())
    # ... and removing the correction moves them right, towards the uncompensated position.
    assert np.median(under[bright, 0] - base[bright, 0]) > 0.01
    assert draft.changed_cells() == [(1, 2)]


def test_reset_and_undo_restore_the_assigned_matrix(recipe, prepared):
    draft = SpilloverDraft(recipe["compensation"])
    draft.set("BL1-A", "YL2-A", 0.2)
    draft.set("YL2-A", "RL1-A", 0.0)
    assert len(draft.changes()) == 2 and draft.dirty
    draft.undo()
    assert draft.changed_cells() == [(1, 2)]
    draft.reset()
    assert not draft.dirty and draft.spec() == recipe["compensation"]
    np.testing.assert_array_equal(drawn(prepared, recipe, draft.spec()), drawn(prepared, recipe))
    draft.undo()  # Reset is itself undoable.
    assert draft.changed_cells() == [(1, 2)]


def test_edits_are_validated_and_provenance_is_kept(recipe):
    draft = SpilloverDraft(recipe["compensation"])
    with pytest.raises(ValueError, match="diagonal"):
        draft.set("BL1-A", "BL1-A", 0.5)
    with pytest.raises(ValueError, match="finite"):
        draft.set("BL1-A", "YL2-A", float("nan"))
    pair = SpilloverDraft({"mode": "matrix", "detectors": ["A", "B"], "values": [[1, 0.5], [0.5, 1]]})
    with pytest.raises(ValueError, match="singular"):
        pair.set("A", "B", 2.0)
    assert not pair.dirty and not pair.history
    assert not draft.dirty and not draft.history
    draft.set("BL1-A", "YL2-A", 0.1)
    spec = draft.spec()
    assert "estimation" not in spec and spec["acquisition"] == recipe["compensation"]["acquisition"]
    edit = spec["edit"]
    assert edit["method"] == EDIT_METHOD and edit["reviewed"] is False
    assert edit["base_sha256"] == spec_sha256(recipe["compensation"])
    assert edit["base_estimation"] == recipe["compensation"]["estimation"]
    assert edit["changes"] == [
        {"source": "BL1-A", "target": "YL2-A", "from": recipe["compensation"]["values"][1][2], "to": 0.1}
    ]


def test_editing_needs_an_explicit_matrix():
    with pytest.raises(ValueError, match="never infers"):
        SpilloverDraft({"mode": "fcs"})


def test_drag_direction_matches_flowjo():
    # Comp-BL1 (y) against Comp-YL2 (x): dragging down subtracts more YL2 dye from BL1,
    # dragging left subtracts more BL1 dye from YL2.
    assert drag_edit(("BL1-A", "YL2-A"), 0.0, -0.2) == ("YL2-A", "BL1-A", pytest.approx(0.02))
    assert drag_edit(("BL1-A", "YL2-A"), -0.3, 0.1) == ("BL1-A", "YL2-A", pytest.approx(0.03))


def test_saved_matrix_never_overwrites(recipe, tmp_path):
    draft = SpilloverDraft(recipe["compensation"])
    with pytest.raises(ValueError, match="No spillover"):
        save_edited_matrix(draft.spec(), tmp_path / "edited.json")
    draft.set("BL1-A", "YL2-A", 0.1)
    applied = save_edited_matrix(draft.spec(), tmp_path / "edited.json")
    assert applied["edit"]["saved_sha256"] == digest(tmp_path / "edited.json")
    with pytest.raises(FileExistsError):
        save_edited_matrix(draft.spec(), tmp_path / "edited.json")


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def open_window(demo, recipe, tmp_path, records):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets as W

    from agentflow.workbench import ScreenWindow

    app = W.QApplication.instance() or W.QApplication([])
    reviewed = copy.deepcopy(recipe)
    for gate in reviewed["gates"]:
        gate["reviewed"] = True
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(reviewed))
    w = ScreenWindow(records, reviewed, "live", path)
    w.show()
    app.processEvents()
    w.compensation_matrix_dialog()
    return app, w, w.matrix_view


@pytest.fixture
def gui(demo, recipe, tmp_path):
    records = read_samples(demo / "workflow/samples.csv")
    # DUMMY-2 keeps its own sample-sheet matrix, as a FlowJo user might assign per sample.
    records[1]["compensation_path"] = str(demo / "compensation.json")
    app, w, dialog = open_window(demo, recipe, tmp_path, records)
    yield w, dialog
    dialog.close()
    w.discarding = True
    w.close()
    app.processEvents()


def cell(dialog, source, target):
    names = dialog.draft.detectors
    return dialog.table.item(names.index(source), names.index(target))


def plotted(dialog):
    return np.asarray(dialog.axes[("BL1-A", "YL2-A")].collections[0].get_offsets())


def test_dialog_edits_redraw_live_mark_cells_and_undo(gui):
    from PySide6 import QtCore

    _, dialog = gui
    dialog.sample.setCurrentIndex(2)
    base = plotted(dialog)
    bright = bl1_only(base)
    assert not dialog.apply_button.isEnabled() and not dialog.undo_button.isEnabled()
    assert "2 of 3 samples" in dialog.edit_note.text() and "DUMMY-2" in dialog.edit_note.text()
    cell(dialog, "BL1-A", "YL2-A").setText("15")
    edited = plotted(dialog)
    assert np.median(edited[bright, 0] - base[bright, 0]) < -0.01
    assert cell(dialog, "BL1-A", "YL2-A").background().color() == dialog_module().EDITED_CELL
    assert cell(dialog, "YL2-A", "BL1-A").background().style() == QtCore.Qt.NoBrush  # Unedited cells stay plain.
    assert "DRAFT" in dialog.note.text() and dialog.canvas.figure.get_suptitle()
    assert dialog.apply_button.isEnabled() and dialog.reset_button.isEnabled()
    # The sample with its own matrix never shows the draft.
    dialog.sample.setCurrentIndex(1)
    assert "DRAFT" not in dialog.note.text() and "do not change" in dialog.note.text()
    dialog.sample.setCurrentIndex(2)
    cell(dialog, "BL1-A", "BL1-A").setText("50")  # Diagonal is read-only; a forced edit is refused.
    assert "diagonal" in dialog.edit_note.text()
    dialog.undo()
    np.testing.assert_array_equal(plotted(dialog), base)
    cell(dialog, "BL1-A", "YL2-A").setText("0")
    dialog.reset()
    np.testing.assert_array_equal(plotted(dialog), base)
    assert cell(dialog, "BL1-A", "YL2-A").text() == f"{100 * dialog.draft.original[1, 2]:.3f}"
    assert not dialog.apply_button.isEnabled()


def test_dialog_drag_nudges_the_matching_spillover(gui):
    _, dialog = gui
    dialog.sample.setCurrentIndex(2)
    ax = dialog.axes[("BL1-A", "YL2-A")]
    before = dialog.draft.values.copy()
    dialog.drag(ax, 0.0, 0.01)  # Too short: a click, not an edit.
    assert not dialog.draft.dirty
    dialog.drag(ax, -0.25, 0.0)
    assert dialog.draft.changed_cells() == [(1, 2)]
    assert dialog.draft.values[1, 2] == pytest.approx(before[1, 2] + 0.025)


def test_apply_writes_a_new_file_resets_reviews_and_keeps_the_original(gui, demo, tmp_path):
    w, dialog = gui
    original = demo / "compensation.json"
    original_hash = digest(original)
    assert all(g["reviewed"] for g in w.state.recipe["gates"])
    cell(dialog, "BL1-A", "YL2-A").setText("12.5")
    assert not dialog.apply_draft(original)  # An existing file is never overwritten.
    assert "exists" in dialog.edit_note.text()
    assert all(g["reviewed"] for g in w.state.recipe["gates"])
    target = tmp_path / "edited.json"
    assert dialog.apply_draft(target)
    assert digest(original) == original_hash
    applied = w.state.recipe["compensation"]
    assert applied["values"][1][2] == 0.125
    assert applied["edit"]["saved_as"] == str(target)
    assert applied["edit"]["saved_sha256"] == digest(target)
    assert json.loads(target.read_text())["values"] == applied["values"]
    assert not any(g["reviewed"] for g in w.state.recipe["gates"])
    # The applied matrix is the new assigned one: nothing is edited, and undo in the window reverts it.
    assert dialog.draft.base == applied and not dialog.draft.dirty
    assert "Applied and saved as edited.json" in dialog.edit_note.text()
    w.travel(False)
    assert w.state.recipe["compensation"]["values"][1][2] != 0.125


def dialog_module():
    from agentflow import compensation_matrix_dialog

    return compensation_matrix_dialog
