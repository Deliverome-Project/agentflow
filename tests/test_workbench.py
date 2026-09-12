import copy
import json
import os
from types import SimpleNamespace

import numpy as np
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


def gallery_items(window):
    items = []
    window.update_gallery()
    for page in range(1, window.gallery_page.maximum() + 1):
        window.gallery_page.setValue(page)
        window.update_gallery()
        items.extend(window.gallery_axes.items())
    return items


def find_gallery(window, target):
    window.update_gallery()
    for page in range(1, window.gallery_page.maximum() + 1):
        window.gallery_page.setValue(page)
        window.update_gallery()
        for ax, value in window.gallery_axes.items():
            if value == target:
                return ax
    raise AssertionError(f"Missing plot: {target}")


def test_gallery_detector_labels_selection_and_sample_comparison(window):
    window.gallery_mode.setCurrentText("All populations")
    assert len(gallery_items(window)) == 6
    assert all(ax.get_xlabel() for ax in window.gallery_axes)
    ax = find_gallery(window, ("gate", "gfp"))
    window.select_gallery(SimpleNamespace(inaxes=ax))
    assert window.active_name == "gfp"
    window.gallery_mode.setCurrentIndex(1)
    W.QApplication.processEvents()
    assert len(gallery_items(window)) == 3
    ax = find_gallery(window, ("sample", "DUMMY-3"))
    window.select_gallery(SimpleNamespace(inaxes=ax))
    assert window.record["sample_id"] == "DUMMY-3"
    limits = []
    for page in range(1, window.gallery_page.maximum() + 1):
        window.gallery_page.setValue(page)
        window.update_gallery()
        limits.extend(ax.get_xlim() for ax in window.gallery_axes)
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

    window.range_mode.setCurrentIndex(1)  # Explicitly test the optional one-sided mode.
    window.apply_bounds()
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
    window.group_choice.setCurrentText("High positive fraction")
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
    assert [value[1] for _, value in gallery_items(window)] == ["cells", "singlets", "live", "gfp"]
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
    window.group_choice.setCurrentText("High positive fraction")
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
    assert len(gallery_items(window)) == 3
    window.save()
    saved = json.loads(window.state.path.read_text())
    assert saved["display"]["gallery_mode"] == "Ancestry"


def test_small_window_keeps_plot_and_labels_separate(window):
    from PySide6.QtTest import QTest

    window.resize(1180, 800)
    window.gallery_mode.setCurrentText("Ancestry")
    QTest.qWait(100)
    W.QApplication.processEvents()
    assert window.canvas.height() >= 180
    assert window.canvas.geometry().bottom() < window.help.geometry().top()
    assert all(ax.get_subplotspec().get_gridspec().ncols == 1 for ax in window.gallery_axes)
    assert not window.parent_button.isHidden()


@pytest.mark.parametrize("size", [(1280, 720), (980, 620)])
def test_laptop_layout_keeps_save_and_polygon_accessible(window, size):
    from PySide6.QtTest import QTest

    window.resize(*size)
    QTest.qWait(150)
    assert window.width() <= size[0]
    assert window.height() <= size[1]
    root = window.centralWidget()
    for widget in (window.save_button, window.polygon_button):
        position = widget.mapTo(root, QtCore.QPoint(0, 0))
        assert root.rect().contains(QtCore.QRect(position, widget.size()))
    assert window.plot_splitter.count() == 2


def test_draw_polygon_from_histogram_and_save_vertices(window):
    from matplotlib.backend_bases import MouseEvent

    from agentflow.engine import load_recipe

    def fill():
        dialog = W.QApplication.activeModalWidget()
        assert dialog.findChild(W.QComboBox, "gate_kind").currentText() == "polygon"
        x = dialog.findChild(W.QComboBox, "x_detector")
        y = dialog.findChild(W.QComboBox, "y_detector")
        assert x.currentText() != y.currentText()
        dialog.findChild(W.QLineEdit, "population_name").setText("custom_polygon")
        x.setCurrentText("BL1-A")
        y.setCurrentText("YL2-A")
        next(b for b in dialog.findChildren(W.QPushButton) if b.text() == "Add draft population").click()

    QtCore.QTimer.singleShot(0, fill)
    window.polygon_button.click()
    window.canvas.draw()
    bounds = window.ax.get_xlim(), window.ax.get_ylim()
    vertices = [
        [bounds[0][0] + fx * (bounds[0][1] - bounds[0][0]), bounds[1][0] + fy * (bounds[1][1] - bounds[1][0])]
        for fx, fy in [(0.2, 0.2), (0.8, 0.2), (0.5, 0.8)]
    ]
    for vertex in vertices + vertices[:1]:
        x, y = window.ax.transData.transform(vertex)
        for name in ("motion_notify_event", "button_press_event", "button_release_event"):
            event = MouseEvent(name, window.canvas, x, y, button=1)
            window.canvas.callbacks.process(name, event)
    np.testing.assert_allclose(window.state.gate("custom_polygon")["vertices"], vertices)
    assert window.save_changes()
    saved = load_recipe(window.state.path.with_suffix(".reproducibility.yaml"))
    gate = next(g for g in saved["gates"] if g["name"] == "custom_polygon")
    assert gate["parent"] == "live"
    np.testing.assert_allclose(gate["vertices"], vertices)


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


def test_compensation_cleanup_selection_and_small_screen(window, demo, tmp_path, monkeypatch):
    from agentflow.compensation_wizard import CompensationWizard
    from agentflow.control_review import resolve_config

    window.records[0]["compensation_path"] = "assigned.json"
    wizard = CompensationWizard(window, ["BL1-A"])
    assert "2 of 3" in wizard.assignment_summary.text()
    assert "keeps assigned matrix" in wizard.assignments.itemText(0)
    wizard.set_config(resolve_config(json.loads((demo / "controls.json").read_text()), demo))
    cleanup = {
        "version": 1,
        "compensation": {"mode": "none"},
        "transforms": {"FSC-A": {"kind": "linear"}},
        "gates": [
            {"name": "cells", "kind": "range", "parent": "root", "channels": ["FSC-A"], "bounds": [0, None]},
            {
                "name": "singlets",
                "kind": "range",
                "parent": "cells",
                "channels": ["FSC-A"],
                "bounds": [1, None],
            },
        ],
    }
    path = tmp_path / "cleanup.json"
    path.write_text(json.dumps(cleanup))
    monkeypatch.setattr(W.QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    wizard.spec = {"draft": True}
    wizard.choose_cleanup()
    assert wizard.spec is None
    assert wizard.configuration()["cleanup_gate"] == "singlets"
    wizard.cleanup_gate.setCurrentText("cells")
    assert wizard.configuration()["cleanup_gate"] == "cells"
    wizard.clear_cleanup()
    assert "cleanup_recipe" not in wizard.configuration()
    wizard.add_row("NEW-A")
    wizard.table.selectRow(wizard.table.rowCount() - 1)
    assert wizard.ax is None  # Never edit a previous control's stale histogram.
    assert "Choose" in wizard.status.text()
    wizard.resize(980, 620)
    wizard.show()
    W.QApplication.processEvents()
    point = wizard.apply_button.mapTo(wizard, QtCore.QPoint(0, 0))
    assert point.y() + wizard.apply_button.height() <= wizard.height()
    assert point.x() + wizard.apply_button.width() <= wizard.width()
    wizard.grab().save("/private/tmp/agentflow-compensation-setup.png")
    wizard.reject()
    window.records[0].pop("compensation_path")


def test_ratio_dialog_scatter_and_snapshot(window, tmp_path):
    import yaml

    def accept_ratio():
        dialog = W.QApplication.activeModalWidget()
        for button in dialog.findChildren(W.QPushButton):
            if button.text() == "Show scatter and apply ratio":
                button.click()
                return
        dialog.reject()

    QtCore.QTimer.singleShot(20, accept_ratio)
    QtCore.QTimer.singleShot(
        2000,
        lambda: W.QApplication.activeModalWidget().reject() if W.QApplication.activeModalWidget() else None,
    )
    window.ratio_dialog()
    gate = window.state.gate("gfp_cy5_ratio")
    assert gate is not None
    assert gate["channels"] == ["BL1-A", "RL1-A"]
    assert window.plot_type.currentText() == "Scatter"
    assert window.selector is None
    assert len(window.ax.lines) >= 3
    window.state.save()
    snapshot = yaml.safe_load(window.state.path.with_suffix(".reproducibility.yaml").read_text())
    assert snapshot["inspected_sample"]["instrument"]["detectors"]["BL1-A"]["gain"] == 1
    assert "fcs_keywords" in snapshot["inspected_sample"]["instrument"]
    W.QApplication.processEvents()
    window.grab().save("/private/tmp/agentflow-ratio-scatter.png")


def test_launcher_opens_yaml_and_rejects_ambiguous_recipe(window, demo, tmp_path, monkeypatch):
    import pandas as pd

    from agentflow.launcher import Launcher
    from agentflow.recipes import save_recipe

    folder = tmp_path / "yaml-project"
    folder.mkdir()
    save_recipe(folder / "recipe.yaml", window.state.recipe)
    pd.DataFrame(read_samples(demo / "workflow/samples.csv")).to_csv(folder / "samples.csv", index=False)
    monkeypatch.setattr(W.QFileDialog, "getExistingDirectory", lambda *a: str(folder))
    launcher = Launcher()
    launcher.open_folder()
    assert launcher.selection[0].name == "recipe.yaml"
    save_recipe(folder / "recipe.json", window.state.recipe)
    other = Launcher()
    other.open_folder()
    assert other.selection is None
    assert "multiple recipes" in other.status.text()
    launcher.show()
    W.QApplication.processEvents()
    launcher.grab().save("/private/tmp/agentflow-polished-launcher.png")
    launcher.close()
    other.close()


@pytest.mark.parametrize("size", [(980, 620), (1280, 720), (1440, 900)])
def test_counts_and_gallery_fit_without_scrolling(window, size):
    window.gallery_mode.setCurrentText("All populations")
    window.resize(*size)
    window.show_gate("live")
    W.QApplication.processEvents()
    window.update_gallery()
    W.QApplication.processEvents()
    from PySide6.QtTest import QTest

    QTest.qWait(150)
    assert (window.width(), window.height()) == size
    assert window.plot_scroll.verticalScrollBar().maximum() == 0, [
        (x.__class__.__name__, x.height(), x.minimumSizeHint().height())
        for x in (
            window.plot_scroll,
            window.title,
            window.subtitle,
            window.stack,
            window.canvas,
            window.bounds_widget,
        )
    ]
    for widget in (window.count, window.percent, window.review_button, window.gallery_canvas):
        top = widget.mapTo(window, QtCore.QPoint(0, 0))
        assert top.y() >= 0
        assert top.y() + widget.height() < window.height()
    assert window.gallery_canvas.height() <= window.gallery_panel.height()
    assert len(window.gallery_axes) >= 2
    window.gallery_canvas.draw()
    renderer = window.gallery_canvas.get_renderer()
    for ax in window.gallery_axes:
        extent = ax.get_tightbbox(renderer)
        assert extent.y0 >= -1
        assert extent.y1 <= window.gallery_canvas.height() + 1
    window.grab().save(f"/private/tmp/agentflow-layout-{size[0]}x{size[1]}.png")


def test_dummy_histograms_open_between_and_scatter_exploration_is_read_only(window):
    from agentflow.scatter_viewer import ScatterDialog

    assert window.range_mode.currentText() == "Between bounds"
    for gate in window.state.recipe["gates"]:
        if gate["kind"] == "range":
            assert all(value is not None for value in gate["bounds"])
    before = copy.deepcopy(window.state.recipe)
    dialog = ScatterDialog(window)
    dialog.population.setCurrentText("live")
    dialog.x.setCurrentText("BL1-A")
    dialog.y.setCurrentText("RL1-A")
    dialog.style.setCurrentText("Density")
    assert dialog.ax.get_xlabel() == "BL1-A · logicle"
    assert dialog.ax.get_ylabel() == "RL1-A · logicle"
    assert f"{window.state.counts()['live']:,}" in dialog.count.text()
    assert window.state.recipe == before

    def fill():
        active = W.QApplication.activeModalWidget()
        assert active.findChild(W.QComboBox, "parent_population").currentText() == "live"
        assert active.findChild(W.QComboBox, "x_detector").currentText() == "BL1-A"
        assert active.findChild(W.QComboBox, "y_detector").currentText() == "RL1-A"
        active.findChild(W.QLineEdit, "population_name").setText("reporter_subset")
        next(b for b in active.findChildren(W.QPushButton) if b.text() == "Add draft population").click()

    QtCore.QTimer.singleShot(0, fill)
    dialog.create_population()
    assert window.state.gate("reporter_subset")["parent"] == "live"
    assert window.state.gate("reporter_subset")["channels"] == ["BL1-A", "RL1-A"]
    dialog.close()


@pytest.mark.parametrize("size,minimum", [((980, 620), 2), ((1280, 720), 3), ((1440, 900), 3)])
def test_compact_sample_comparison_shows_multiple_plots(window, size, minimum):
    window.resize(*size)
    window.gallery_mode.setCurrentText("Compare samples")
    W.QApplication.processEvents()
    window.update_gallery()
    W.QApplication.processEvents()
    assert len(window.gallery_axes) >= minimum
    assert window.plot_scroll.verticalScrollBar().maximum() == 0
    window.gallery_canvas.draw()
    renderer = window.gallery_canvas.get_renderer()
    for ax in window.gallery_axes:
        extent = ax.get_tightbbox(renderer)
        assert extent.x0 >= -1
        assert extent.x1 <= window.gallery_canvas.width() + 1
        assert extent.y0 >= -1
        assert extent.y1 <= window.gallery_canvas.height() + 1
    window.grab().save(f"/private/tmp/agentflow-compare-{size[0]}x{size[1]}.png")


def test_delete_population_cascade_cancel_undo_and_save(window, monkeypatch):
    from agentflow.engine import load_recipe

    candidate = copy.deepcopy(window.state.recipe)
    candidate["gates"].extend(
        [
            {
                "name": "gfp_child",
                "parent": "gfp",
                "kind": "range",
                "channels": ["BL1-A"],
                "bounds": [5, 7],
                "reviewed": False,
            },
            {
                "name": "double",
                "parent": "live",
                "kind": "boolean",
                "channels": ["BL1-A", "RL1-A"],
                "references": ["gfp", "cy5"],
                "operation": "and",
                "reviewed": False,
            },
        ]
    )
    candidate["sample_overrides"] = {"DUMMY-2": {"gfp": {"reviewed": True}, "cy5": {"reviewed": True}}}
    window.state.apply(candidate)
    window.rebuild("gfp")
    before = copy.deepcopy(window.state.recipe)
    monkeypatch.setattr(W.QMessageBox, "exec", lambda self: W.QMessageBox.Cancel)
    window.delete_population()
    assert window.state.recipe == before
    monkeypatch.setattr(W.QMessageBox, "exec", lambda self: W.QMessageBox.Yes)
    assert window.state.deletion_set("gfp") == ["gfp", "gfp_child", "double"]
    window.delete_population()
    assert window.active_name == "live"
    assert all(window.state.gate(n) is None for n in ["gfp", "gfp_child", "double"])
    assert window.state.recipe["sample_overrides"]["DUMMY-2"] == {"cy5": {"reviewed": True}}
    assert window.state.counts()["cy5"] > 0
    window.travel(False)
    assert window.state.recipe == before
    window.travel(True)
    assert window.state.gate("gfp") is None
    window.save_changes(close=False)
    assert all(g["name"] != "gfp" for g in load_recipe(window.state.path)["gates"])
    window.state.sample_scope = True
    with pytest.raises(ValueError, match="All samples"):
        window.state.delete_population("cy5")
    window.state.sample_scope = False
    with pytest.raises(ValueError, match="at least one"):
        window.state.delete_population("cells")


def test_sample_mfi_default_uses_metadata_and_untransformed_signal(window):
    assert window.gallery_mode.currentText() == "Sample MFI"
    window.summary_detector.setCurrentIndex(0)
    table = window.sample_summary_table()
    assert len(table) == len(window.records)
    first = table.iloc[0]
    prepared, masks = window.session.get(window.records[0], window.state.recipe)
    expected = prepared.values.loc[masks[first.population], first.detector].mean()
    assert first.value == pytest.approx(expected)
    assert first.event_count == int(masks[first.population].sum())
    window.summary_statistic.setCurrentIndex(1)
    assert window.sample_summary_table().iloc[0].value == pytest.approx(
        prepared.values.loc[masks[first.population], first.detector].median()
    )
    window.update_gallery()
    ax = next(iter(window.gallery_axes))
    sid = window.gallery_axes[ax][1][1]
    window.select_gallery(SimpleNamespace(inaxes=ax, ydata=1))
    assert window.record["sample_id"] == sid


def test_scatter_limits_resist_outliers_without_changing_data():
    from agentflow.plot_views import scatter_limits

    data = np.column_stack([np.arange(1000), np.arange(1000)]).astype(float)
    data[-1] = 1e8
    original = data.copy()
    central = scatter_limits(data, ["FSC-A", "SSC-A"])
    full = scatter_limits(data, ["FSC-A", "SSC-A"], full_range=True)
    assert central[1].max() < 2000
    assert full[1].min() > 1e8
    np.testing.assert_array_equal(data, original)
    assert scatter_limits(data, ["FL1-A", "SSC-A"]) is None


def test_summary_shows_30_samples_and_refreshes_after_gate_edit(window):
    # Distinct sample IDs may legitimately refer to reused synthetic data.
    window.records = [
        dict(window.records[0], sample_id=f"S{i}", condition=f"Condition {i}") for i in range(30)
    ]
    window.record = window.records[0]
    window.show_gate("gfp")
    window.update_gallery()
    assert window.summary_population.currentText() == "gfp"
    ax = next(iter(window.gallery_axes))
    assert len(ax.patches) == 30
    assert window.gallery_page.maximum() == 1
    before = window.sample_summary_table()
    gate = window.state.gate("gfp")
    prepared, masks = window.session.get(window.records[0], window.state.recipe)
    values = prepared.transformed.loc[masks["gfp"], gate["channels"][0]]
    # Tightening the gate must invalidate cached memberships and change the actual bars.
    bounds = [float(values.quantile(0.8)), gate["bounds"][1]]
    window.perform(lambda: window.state.geometry("gfp", "bounds", bounds), redraw=False)
    W.QApplication.processEvents()
    window.update_gallery()
    after = window.sample_summary_table()
    assert (after.event_count < before.event_count).all()
    assert not np.allclose(after.value, before.value)
    ax = next(iter(window.gallery_axes))
    np.testing.assert_allclose([bar.get_width() for bar in ax.patches], after.value)
    window.summary_follow.setChecked(False)
    window.summary_population.setCurrentText("live")
    window.show_gate("cy5")
    window.update_gallery()
    assert window.summary_population.currentText() == "live"


def test_comparison_titles_include_condition_and_file(window):
    window.records[0]["condition"] = "Accutase 37C (5 min)"
    window.gallery_mode.setCurrentText("Compare samples")
    ax = find_gallery(window, ("sample", window.records[0]["sample_id"]))
    assert "Accutase 37C (5 min)" in ax.get_title()
    assert window.records[0]["sample_id"] in ax.get_title()


def test_density_grid_uses_visible_scatter_extent():
    from matplotlib.figure import Figure

    from agentflow.plot_views import draw_events, scatter_limits

    rng = np.random.default_rng(17)
    cloud = rng.normal(500000, 100000, (5000, 2))
    data = np.vstack([cloud, [1e8, 1e8]])
    original = data.copy()
    limits = scatter_limits(data, ["FSC-A", "SSC-A"])
    ax = Figure().subplots()
    draw_events(ax, data, ["FSC-A", "SSC-A"], limits=limits)
    occupied = ax.collections[0].get_offsets()
    assert len(occupied) > 500  # Fine cell-cloud detail, not a handful of giant full-range bins.
    assert occupied[:, 0].max() < 2e6
    np.testing.assert_array_equal(data, original)


@pytest.mark.parametrize("total", [5, 6, 7])
def test_comparison_last_page_keeps_fixed_two_by_two_cells(window, total):
    window.records = [
        dict(window.records[0], sample_id=f"S{i}", condition=f"Condition {i}") for i in range(total)
    ]
    window.gallery_mode.setCurrentText("Compare samples")
    window.update_gallery()
    first = [ax.get_position().bounds for ax in window.gallery_axes]
    assert len(first) == 4
    window.gallery_page.setValue(2)
    window.update_gallery()
    last = list(window.gallery_axes)
    assert len(last) == total - 4
    for i, ax in enumerate(last):
        np.testing.assert_allclose(ax.get_position().bounds, first[i])
        assert ax.get_subplotspec().get_gridspec().get_geometry() == (2, 2)


def test_compensation_logicle_preserves_raw_threshold_selection(window, demo, tmp_path):
    from agentflow import flowkit
    from agentflow.compensation_wizard import CompensationWizard
    from agentflow.control_review import resolve_config
    from agentflow.engine import make_transform
    from agentflow.workflow import default_transform

    wizard = CompensationWizard(window, ["BL1-A"])
    config = resolve_config(json.loads((demo / "controls.json").read_text()), demo)
    wizard.set_config(config)
    wizard.table.selectRow(0)
    wizard.preview()
    assert "logicle" in wizard.ax.get_xlabel()
    detector, path = [wizard.table.item(0, c).text() for c in range(2)]
    sample = flowkit.Sample(path)
    transform = make_transform(default_transform(sample, detector))
    values = np.array([-100.0, 0.0, 100.0, 10000.0])
    np.testing.assert_allclose(wizard.ax.xaxis.get_transform().transform(values), transform.apply(values))
    before = wizard.configuration()
    wizard.place_threshold(SimpleNamespace(button=1, inaxes=wizard.ax, xdata=250.0))
    after = wizard.configuration()
    assert after["controls"][0]["negative_max"] == 250.0
    assert after["controls"][0]["positive_min"] == before["controls"][0]["positive_min"]
    raw = sample.get_channel_events(detector, source="raw")
    assert f"Negative: {np.count_nonzero(raw <= 250):,}" in wizard.status.text()
    wizard.canvas.draw()
    wizard.figure.savefig(tmp_path / "compensation.png")
    wizard.reject()
