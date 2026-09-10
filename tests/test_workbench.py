import copy
import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6 import QtCore
from PySide6 import QtWidgets as W

from agentflow.demo import make_demo
from agentflow.samples import read_samples
from agentflow.workbench import ScreenWindow


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("desktop-screen") / "demo")


@pytest.fixture
def window(demo, tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    w = ScreenWindow(read_samples(demo / "workflow/samples.csv"), recipe, "live", path)
    w.show()
    app.processEvents()
    yield w
    w.discarding = True
    w.close()
    app.processEvents()


def test_gallery_detector_labels_selection_and_sample_comparison(window):
    assert len(window.gallery_axes) == 6
    assert all(ax.get_xlabel() for ax in window.gallery_axes)
    ax = next(ax for ax, value in window.gallery_axes.items() if value == ("gate", "gfp"))
    window.select_gallery(SimpleNamespace(inaxes=ax))
    assert window.active_name == "gfp"
    window.gallery_mode.setCurrentIndex(1)
    W.QApplication.processEvents()
    assert len(window.gallery_axes) == 3
    ax = next(ax for ax, value in window.gallery_axes.items() if value == ("sample", "DUMMY-3"))
    window.select_gallery(SimpleNamespace(inaxes=ax))
    assert window.record["sample_id"] == "DUMMY-3"
    limits = [ax.get_xlim() for ax in window.gallery_axes]
    assert all(lim == limits[0] for lim in limits)


def test_dummy_live_threshold_signal_units_and_save(window):
    assert float(window.upper.text()) == pytest.approx(5000)
    window.upper.setText("4000")
    window.apply_bounds()
    assert float(window.upper.text()) == pytest.approx(4000)
    window.save()
    assert window.state.saved
    assert "display" in json.loads(window.state.path.read_text())


def test_histogram_drag_keeps_threshold_and_zoom(window):
    from matplotlib.backend_bases import MouseEvent

    from agentflow.engine import load_recipe
    from agentflow.threshold import ThresholdSelector

    window.canvas.draw()
    xlim, ylim = window.ax.get_xlim(), window.ax.get_ylim()
    for fraction in (0.35, 0.65, 0.45):
        assert isinstance(window.selector, ThresholdSelector)
        value = xlim[0] + fraction * (xlim[1] - xlim[0])
        x, y = window.ax.transData.transform((value, sum(ylim) / 2))
        for name in ("button_press_event", "motion_notify_event", "button_release_event"):
            event = MouseEvent(name, window.canvas, x, y, button=1)
            window.canvas.callbacks.process(name, event)
        W.QApplication.processEvents()
        assert window.state.gate("live")["bounds"] == pytest.approx([None, value])
        assert window.ax.get_xlim() == pytest.approx(xlim)
        assert window.ax.get_ylim() == pytest.approx(ylim)
        assert window.isVisible()
    assert window.save_changes()
    snapshot = window.state.path.with_suffix(".reproducibility.yaml")
    assert load_recipe(snapshot) == load_recipe(window.state.path)


def test_overlay_scatter_density_axes_and_counts(window):
    window.gates.setCurrentRow(0)
    before = copy.deepcopy(window.state.recipe)
    counts = window.state.counts()
    window.overlay.setChecked(True)
    assert len(window.ax.collections) == 3
    colors = [tuple(c.get_facecolors()[0][:3]) for c in window.ax.collections]
    assert len(set(colors)) == 3
    window.plot_type.setCurrentText("Density")
    window.x_scale.setCurrentText("Logicle")
    W.QApplication.processEvents()
    assert not window.selector.active
    assert window.state.counts() == counts
    assert window.state.recipe == before
    window.gating_axes()
    assert window.selector.active


def test_scroll_zoom_and_geometry_leave_other_samples_available(window):
    window.gates.setCurrentRow(0)
    old = window.ax.get_xlim()
    window.scroll_zoom(
        SimpleNamespace(
            inaxes=window.ax, xdata=sum(old) / 2, ydata=sum(window.ax.get_ylim()) / 2, button="up"
        )
    )
    assert window.ax.get_xlim()[1] - window.ax.get_xlim()[0] < old[1] - old[0]
    window.state.geometry("cells", "vertices", [[0, 0], [1, 0], [1, 1], [0, 1]])
    window.switch_sample(1)
    assert window.state.counts()["cells"] == 0


def test_new_boolean_population_and_undo(window):
    def fill():
        dialog = window.findChild(W.QDialog)
        dialog.findChild(W.QLineEdit, "population_name").setText("double_positive")
        dialog.findChild(W.QComboBox, "parent_population").setCurrentText("live")
        dialog.findChild(W.QComboBox, "gate_kind").setCurrentText("boolean")
        dialog.findChild(W.QComboBox, "x_detector").setCurrentText("BL1-A")
        dialog.findChild(W.QComboBox, "y_detector").setCurrentText("YL2-A")
        for b in dialog.findChildren(W.QPushButton):
            if b.text() == "Add draft population":
                b.click()
                return

    QtCore.QTimer.singleShot(0, fill)
    window.new_population()
    assert window.state.gate("double_positive")["references"] == ["gfp", "mscarlet"]
    assert window.active_name == "double_positive"
    window.travel(False)
    assert window.state.gate("double_positive") is None
    assert window.active_name == "cells"
    window.travel(True)
    assert window.state.gate("double_positive") is not None


def test_plate_map_click_selects_sample(window):
    window.gallery_mode.setCurrentText("Plate map")
    W.QApplication.processEvents()
    ax = next(iter(window.gallery_axes))
    window.select_gallery(SimpleNamespace(inaxes=ax, xdata=2.0, ydata=0.0))
    assert window.record["sample_id"] == "DUMMY-3"


def test_cli_multi_sample_dispatch(window, monkeypatch, capsys):
    import agentflow.workbench
    from agentflow.cli import main

    def run(records, recipe, gate, path):
        assert len(records) == 3
        assert records[0]["group"] == "Negative control"
        return False

    monkeypatch.setattr(agentflow.workbench, "run_workbench", run)
    samples = str(__import__("pathlib").Path(window.records[0]["fcs_path"]).parent / "workflow/samples.csv")
    assert main(["edit", "--samples", samples, "--recipe", str(window.state.path)]) == 2
    assert "cancelled" in capsys.readouterr().out


def test_sample_exception_shared_counts_save_and_undo(window):
    from agentflow.samples import sample_recipe

    shared = copy.deepcopy(window.state.recipe)
    other = window.records[1]
    _, masks = window.session.get(other, shared)
    expected = int(masks["live"].sum())
    window.edit_scope.setCurrentIndex(1)
    window.upper.setText("10")
    window.apply_bounds()
    assert window.state.counts()["live"] < 100
    assert window.state.recipe["gates"] == shared["gates"]
    assert sample_recipe(window.state.recipe, other)["gates"] == shared["gates"]
    window.sample_choice.setCurrentIndex(1)
    assert window.state.counts()["live"] == expected
    window.sample_choice.setCurrentIndex(0)
    assert window.state.counts()["live"] < 100
    window.travel(False)
    assert window.state.counts()["live"] > 3000
    window.travel(True)
    assert window.state.counts()["live"] < 100
    window.save()
    saved = json.loads(window.state.path.read_text())
    assert "bounds" in saved["sample_overrides"]["DUMMY-1"]["live"]


def test_pinned_reference_survives_group_filter(window):
    window.pinned = {"DUMMY-1"}
    window.sample_choice.setCurrentIndex(2)
    window.group_choice.setCurrentText("High expression")
    assert [r["sample_id"] for r in window.plot_records()] == ["DUMMY-1", "DUMMY-3"]
    assert any("Pinned · DUMMY-1" in t.get_text() for t in window.ax.get_legend().texts)
    window.save()
    assert json.loads(window.state.path.read_text())["display"]["pinned_samples"] == ["DUMMY-1"]


def test_compensation_wizard_review_click_export(window, demo, tmp_path, monkeypatch):
    from agentflow.compensation_wizard import CompensationWizard
    from agentflow.control_review import resolve_config

    wizard = CompensationWizard(window, ["BL1-A"])
    wizard.set_config(resolve_config(json.loads((demo / "controls.json").read_text()), demo))
    wizard.show()
    W.QApplication.processEvents()
    assert "Negative: 1,000" in wizard.status.text()
    wizard.place_threshold(SimpleNamespace(button=1, inaxes=wizard.ax, xdata=600.0))
    assert float(wizard.table.item(0, 2).text()) == 600
    output = tmp_path / "review"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *a: (str(output), ""))
    wizard.calculate()
    assert wizard.spec is not None, wizard.status.text()
    assert wizard.apply_button.isEnabled()
    assert (output / "diagnostics/control-01.png").exists()
    expected = json.loads((demo / "expected-spillover.json").read_text())
    import numpy as np

    np.testing.assert_allclose(wizard.spec["values"], expected["values"], atol=0.001)
    wizard.table.item(0, 2).setText("700")
    assert wizard.spec is None
    assert not wizard.apply_button.isEnabled()
    wizard.reject()


def test_population_tree_ancestry_and_parent_navigation(window):
    nodes = {name: window.gates.rows[i] for i, name in enumerate(window.names)}
    assert nodes["singlets"].parent() is nodes["cells"]
    assert nodes["gfp"].parent() is nodes["live"]
    window.gates.setCurrentRow(window.names.index("gfp"))
    window.gallery_mode.setCurrentText("Ancestry")
    W.QApplication.processEvents()
    assert [value[1] for value in window.gallery_axes.values()] == ["cells", "singlets", "live", "gfp"]
    nodes["cells"].setExpanded(False)
    window.select_parent()
    assert window.active_name == "live"
    assert nodes["cells"].isExpanded()
    assert "Parent: singlets" in nodes["live"].toolTip(0)


def test_sample_steps_respect_filters_and_flush_edits(window):
    window.edit_scope.setCurrentIndex(1)
    window.upper.setText("2000")
    window.step_sample(1)
    assert window.record["sample_id"] == "DUMMY-2"
    assert "DUMMY-1" in window.state.recipe["sample_overrides"]
    window.step_sample(-1)
    assert float(window.upper.text()) == pytest.approx(2000)
    window.group_choice.setCurrentText("High expression")
    window.step_sample(1)
    assert window.record["sample_id"] == "DUMMY-3"
    assert not window.next_sample.isEnabled()
    assert not window.previous_sample.isEnabled()


def test_tree_rebuild_preserves_collapsed_branches(window):
    cells = window.gates.rows[window.names.index("cells")]
    window.gates.setCurrentRow(window.names.index("cells"))
    cells.setExpanded(False)
    window.rebuild("cells")
    assert not window.gates.rows[window.names.index("cells")].isExpanded()


def test_next_draft_skips_reviewed_and_keeps_masks(window):
    before = window.state.counts()
    window.state.review("gfp")
    window.next_draft()
    assert window.active_name == "mscarlet"
    assert window.state.counts() == before


def test_focus_plot_enlarges_canvas_and_saves_view(window):
    before = window.canvas.width()
    masks = window.state.counts()
    window.gallery_mode.setCurrentText("Ancestry")
    window.focus_plot.setChecked(True)
    W.QApplication.processEvents()
    assert window.gallery_panel.isHidden()
    assert window.canvas.width() > before
    assert window.state.counts() == masks
    window.focus_plot.setChecked(False)
    W.QApplication.processEvents()
    assert not window.gallery_panel.isHidden()
    assert len(window.gallery_axes) == 3
    window.save()
    saved = json.loads(window.state.path.read_text())
    assert saved["display"]["gallery_mode"] == "Ancestry"


def test_small_window_keeps_plot_and_labels_separate(window):
    from PySide6.QtTest import QTest

    window.resize(1180, 800)
    window.gallery_mode.setCurrentText("Ancestry")
    QTest.qWait(100)
    W.QApplication.processEvents()
    assert window.canvas.height() >= 260
    assert window.canvas.geometry().bottom() < window.help.geometry().top()
    assert all(ax.get_subplotspec().get_gridspec().ncols == 1 for ax in window.gallery_axes)
    assert not window.parent_button.isHidden()


def test_save_continue_then_edit_requires_save_again(window):
    assert window.save_changes(close=False)
    assert window.isVisible()
    assert not window.state.dirty
    window.upper.setText("2500")
    window.apply_bounds()
    assert window.state.dirty
    assert not window.state.saved


def test_child_and_sibling_creation_are_explicit(window):
    def inspect():
        dialog = W.QApplication.activeModalWidget()
        relationship = dialog.findChild(W.QComboBox, "population_relationship")
        parent = dialog.findChild(W.QComboBox, "parent_population")
        assert dialog.findChild(W.QComboBox, "gate_kind").currentText() == "range"
        assert parent.currentText() == "live"
        assert not parent.isEnabled()
        relationship.setCurrentIndex(1)
        assert parent.currentText() == "singlets"
        relationship.setCurrentIndex(2)
        assert parent.isEnabled()
        dialog.reject()

    QtCore.QTimer.singleShot(0, inspect)
    window.new_population()


def test_background_analysis_saved_recipe_matches_gui(window, tmp_path, monkeypatch):
    import pandas as pd
    from PySide6 import QtGui
    from PySide6.QtTest import QTest

    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: True)
    window.upper.setText("2500")
    window.apply_bounds()
    assert window.save_changes(close=False)
    expected = window.state.counts()["live"]
    window.start_analysis(tmp_path / "run")
    for _ in range(600):
        QTest.qWait(50)
        if not window.analysis_job.isRunning() and window.centralWidget().isEnabled():
            break
    assert not window.analysis_job.isRunning()
    assert window.centralWidget().isEnabled()
    assert window.analysis_error is None
    table = pd.read_csv(tmp_path / "run/summary.csv")
    assert table.loc[(table.sample_id == "DUMMY-1") & (table.gate == "live"), "count"].iloc[0] == expected


def test_launcher_reopens_saved_analysis(window, demo):
    from agentflow.launcher import Launcher

    assert window.save_changes(close=False)
    launcher = Launcher()
    launcher.select(window.state.path, demo / "workflow/samples.csv")
    assert launcher.selection[0] == window.state.path
    assert len(launcher.selection[1]) == 3


def test_compensation_diagnostics_open_inside_app(window, demo):
    from agentflow.compensation_wizard import CompensationWizard

    wizard = CompensationWizard(window, [])
    wizard.spec = json.loads((demo / "compensation.json").read_text())
    # Matrix column order may differ from the order of control review images.
    wizard.spec["detectors"] = list(reversed(wizard.spec["detectors"]))
    # Existing demo diagnostics have the same files as exported review bundles.
    wizard.review_directory = demo
    source = demo / "control-diagnostics"
    # Choose a tiny local bundle without changing the source demo.
    import shutil
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        shutil.copytree(source, Path(folder) / "diagnostics")
        wizard.review_directory = Path(folder)
        seen = []

        def inspect():
            dialog = W.QApplication.activeModalWidget()
            choice = dialog.findChild(W.QComboBox)
            assert choice.count() == 4
            assert choice.itemText(0) == f"1. {wizard.spec['estimation']['controls'][0]['detector']}"
            choice.setCurrentIndex(1)
            picture = dialog.findChild(W.QScrollArea).widget()
            assert not picture.pixmap().isNull()
            seen.append(True)
            dialog.accept()

        QtCore.QTimer.singleShot(0, inspect)
        wizard.show_diagnostics()
        assert seen
    wizard.reject()


def test_failed_analysis_restores_editor(window, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest

    assert window.save_changes(close=False)
    # Existing output is rejected by the same CLI safeguard.
    output = tmp_path / "existing"
    output.mkdir()
    window.start_analysis(output)
    for _ in range(600):
        QTest.qWait(50)
        if window.centralWidget().isEnabled():
            break
    assert window.centralWidget().isEnabled()
    assert "already exists" in window.analysis_error
    assert list(output.iterdir()) == []
