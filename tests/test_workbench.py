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
