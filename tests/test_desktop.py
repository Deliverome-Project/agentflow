"""Native widgets and mouse interactions; run with QT_QPA_PLATFORM=offscreen."""

import copy
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from matplotlib.backend_bases import MouseEvent
from PySide6 import QtCore, QtTest
from PySide6 import QtWidgets as W

from agentflow import flowkit as fk
from agentflow.desktop import GateWindow
from agentflow.engine import load_recipe, prepare, save_recipe


@pytest.fixture(scope="module")
def app():
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def window(app, tmp_path):
    recipe = {
        "version": 1,
        "compensation": {"mode": "none"},
        "experiment": {"label": "DUMMY / EXAMPLE", "is_example": True},
        "transforms": {"A": {"kind": "linear"}, "B": {"kind": "linear"}},
        "gates": [
            {
                "name": "cells",
                "parent": "root",
                "kind": "rectangle",
                "channels": ["A", "B"],
                "bounds": [0.0, 4.0, 0.0, 4.0],
                "reviewed": True,
            },
            {
                "name": "gfp",
                "parent": "cells",
                "kind": "range",
                "channels": ["A"],
                "bounds": [1.0, None],
                "reviewed": True,
            },
        ],
    }
    path = tmp_path / "recipe.json"
    save_recipe(path, recipe)
    sample = fk.Sample(
        np.array([[0.5, 0.5], [1.5, 1.5], [2.5, 2.5], [3.5, 3.5]]),
        sample_id="synthetic",
        channel_labels=["A", "B"],
    )
    w = GateWindow(prepare(sample, recipe), recipe, None, path)
    w.show()
    app.processEvents()
    yield w
    w.discarding = True
    w.close()


def click(widget):
    QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)


def test_native_threshold_typing_save_and_reopen(window, app):
    window.gates.setCurrentRow(1)
    window.lower.selectAll()
    QtTest.QTest.keyClicks(window.lower, "2")
    click(window.save_button)
    assert window.state.saved
    assert load_recipe(window.state.path)["gates"][1]["bounds"] == [2.0, None]
    assert load_recipe(window.state.path)["gates"][1]["reviewed"]


def test_mouse_drag_counts_undo_redo_and_resize(window, app):
    canvas, ax = window.canvas, window.ax
    # Draw a new rectangle with real Matplotlib pointer events through the canvas.
    for name, xy in [
        ("button_press_event", (-0.1, -0.1)),
        ("motion_notify_event", (2.0, 2.0)),
        ("button_release_event", (2.0, 2.0)),
    ]:
        x, y = ax.transData.transform(xy)
        MouseEvent(name, canvas, x, y, button=1)._process()
    assert window.state.counts()["cells"] == 2
    assert window.state.counts()["gfp"] == 1
    assert not window.state.gate("gfp")["reviewed"]
    click(window.undo_button)
    assert window.state.counts()["cells"] == 4
    click(window.redo_button)
    assert window.state.counts()["cells"] == 2
    before = copy.deepcopy(window.state.recipe)
    window.resize(980, 700)
    app.processEvents()
    window.resize(1400, 900)
    app.processEvents()
    assert window.state.recipe == before
    click(window.pan_button)
    assert not window.selector.active
    click(window.edit_button)
    assert window.selector.active


def test_one_sided_threshold_and_review_next(window):
    window.gates.setCurrentRow(1)
    window.span(2, 3)
    assert window.state.gate("gfp")["bounds"] == [2.0, None]
    window.range_mode.setCurrentIndex(1)
    window.apply_bounds()
    assert window.state.gate("gfp")["bounds"] == [None, 2.0]
    assert window.state.counts()["gfp"] == 2
    window.gates.setCurrentRow(0)
    click(window.review_button)
    assert window.active_name == "gfp"
    assert window.state.gate("cells")["reviewed"]


def test_invalid_input_conflict_and_cancel_preserve_disk(window, monkeypatch):
    original = window.state.path.read_bytes()
    window.gates.setCurrentRow(1)
    window.lower.setText("not a number")
    click(window.save_button)
    assert not window.state.saved
    assert window.state.path.read_bytes() == original
    window.lower.setText("2")
    window.apply_bounds()
    monkeypatch.setattr(W.QMessageBox, "question", lambda *a: W.QMessageBox.StandardButton.Cancel)
    window.close()
    assert window.isVisible()
    window.state.path.write_bytes(original + b"\n")
    click(window.save_button)
    assert "changed on disk" in window.message.text()
    assert not window.state.saved
    monkeypatch.setattr(W.QMessageBox, "question", lambda *a: W.QMessageBox.StandardButton.Discard)
    window.close()
    assert window.state.path.read_bytes() == original + b"\n"


def test_fonts_are_bundled_and_registered(window):
    from PySide6.QtGui import QFontDatabase

    assert "Manrope" in QFontDatabase.families()
    assert "Playfair Display" in QFontDatabase.families()


def test_threshold_switch_commits_and_invalid_switch_is_blocked(window):
    window.gates.setCurrentRow(1)
    window.lower.setText("2")
    window.gates.setCurrentRow(0)
    assert window.state.gate("gfp")["bounds"] == [2.0, None]
    window.gates.setCurrentRow(1)
    window.lower.setText("invalid")
    window.gates.setCurrentRow(0)
    assert window.active_name == "gfp"
    assert window.gates.currentRow() == 1
    assert "Fix the threshold" in window.message.text()


def test_matrix_dialog_import_and_undo(window, tmp_path, monkeypatch):
    path = tmp_path / "matrix.csv"
    path.write_text("source,A,B\nA,1,0.1\nB,0.2,1\n")
    monkeypatch.setattr(W.QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))

    def choose():
        dialog = window.findChild(W.QDialog)
        for b in dialog.findChildren(W.QPushButton):
            if b.text() == "Import matrix…":
                click(b)
                break

    QtCore.QTimer.singleShot(0, choose)
    window.matrix_dialog()
    assert window.state.recipe["compensation"]["mode"] == "matrix"
    assert not any(g["reviewed"] for g in window.state.recipe["gates"])
    click(window.undo_button)
    assert window.state.recipe["compensation"]["mode"] == "none"


def test_mapping_requires_confirmation(window):
    window.state.recipe["pending_gates"] = [
        {"name": "cy5", "label": "Cy5", "reason": "Unknown dye assignment"}
    ]
    window.rebuild("cy5")
    assert not window.assign_button.isEnabled()
    window.channel.setCurrentText("B")
    W.QApplication.processEvents()
    QtTest.QTest.mouseClick(
        window.confirm_mapping,
        QtCore.Qt.MouseButton.LeftButton,
        pos=QtCore.QPoint(8, window.confirm_mapping.height() // 2),
    )
    click(window.assign_button)
    assert window.state.gate("cy5") is not None, (
        window.channel.count(),
        window.confirm_mapping.isChecked(),
        window.message.text(),
    )
    assert window.state.recipe["channel_roles"]["cy5"]["confirmed"]
    click(window.undo_button)
    assert window.state.gate("cy5") is None


def test_untouched_precision_is_preserved(window):
    exact = 1.2345678901234567
    window.state.recipe["gates"][1]["bounds"] = [exact, None]
    window.gates.setCurrentRow(1)
    assert window.lower.text() == "1.2345679"
    click(window.save_button)
    assert window.state.gate("gfp")["bounds"][0] == exact


def pointer(window, name, xy, key=None):
    x, y = window.ax.transData.transform(xy)
    MouseEvent(name, window.canvas, x, y, button=1, key=key)._process()


def test_rectangle_interior_drag_preserves_size(window):
    window.ax.set_xlim(-1, 6)
    window.ax.set_ylim(-1, 6)
    window.canvas.draw()
    before = np.array(window.state.gate("cells")["bounds"])
    for name, xy in [
        ("button_press_event", (1, 2)),
        ("motion_notify_event", (1.3, 2.2)),
        ("button_release_event", (1.3, 2.2)),
    ]:
        pointer(window, name, xy)
    after = np.array(window.state.gate("cells")["bounds"])
    np.testing.assert_allclose(after - before, [0.3, 0.3, 0.2, 0.2], atol=0.02)
    window.travel(False)
    np.testing.assert_allclose(window.state.gate("cells")["bounds"], before)


def test_polygon_drag_insert_save_and_undo(window):
    candidate = copy.deepcopy(window.state.recipe)
    gate = candidate["gates"][0]
    gate["kind"] = "polygon"
    del gate["bounds"]
    gate["vertices"] = [[0, 0], [4, 0], [4, 4], [0, 4]]
    window.state.apply(candidate)
    window.show_gate("cells")
    window.canvas.draw()
    for name, xy in [
        ("button_press_event", (1, 2)),
        ("motion_notify_event", (1.2, 2.2)),
        ("button_release_event", (1.2, 2.2)),
    ]:
        pointer(window, name, xy)
    moved = np.array(window.state.gate("cells")["vertices"])
    np.testing.assert_allclose(moved, np.array(gate["vertices"]) + 0.2, atol=0.02)
    for name in ("button_press_event", "button_release_event"):
        pointer(window, name, (2, 0.7), key="control")
    assert len(window.state.gate("cells")["vertices"]) == 5
    assert "Ctrl+click" in window.help.text()
    window.state.save()
    assert len(load_recipe(window.state.path)["gates"][0]["vertices"]) == 5
    window.travel(False)
    np.testing.assert_allclose(window.state.gate("cells")["vertices"], moved)


def test_rename_preserves_membership_dependents_overrides_and_roundtrip(window, monkeypatch):
    candidate = copy.deepcopy(window.state.recipe)
    candidate["gates"].append(
        {
            "name": "combined",
            "parent": "cells",
            "kind": "boolean",
            "channels": ["A", "B"],
            "references": ["cells", "gfp"],
            "operation": "or",
        }
    )
    candidate["sample_overrides"] = {"synthetic": {"gfp": {"bounds": [2.0, None], "reviewed": True}}}
    candidate["display"] = {"summary_population": "gfp"}
    window.state.apply(candidate)
    window.state.sample_id = "synthetic"
    before = window.state.counts()
    window.rebuild("gfp")
    monkeypatch.setattr(W.QInputDialog, "getText", lambda *a, **k: ("Reporter positive", True))
    window.rename_population()
    assert window.active_name == "Reporter positive"
    assert window.state.counts()["Reporter positive"] == before["gfp"]
    assert window.state.counts()["combined"] == before["combined"]
    assert window.state.gate("Reporter positive")["reviewed"]
    assert window.state.recipe["display"]["summary_population"] == "Reporter positive"
    window.state.save()
    saved = load_recipe(window.state.path)
    assert saved["gates"][-1]["references"] == ["cells", "Reporter positive"]
    assert "Reporter positive" in saved["sample_overrides"]["synthetic"]
    window.travel(False)
    assert window.state.gate("gfp") is not None
    window.travel(True)
    assert window.state.gate("Reporter positive") is not None
    window.state.rename_population("cells", "All cells")
    assert window.state.gate("Reporter positive")["parent"] == "All cells"
    assert window.state.gate("combined")["parent"] == "All cells"
    for invalid in ("", "root", "All cells"):
        with pytest.raises(ValueError):
            window.state.rename_population("Reporter positive", invalid)
    window.state.sample_scope = True
    with pytest.raises(ValueError, match="All samples"):
        window.state.rename_population("Reporter positive", "new")
