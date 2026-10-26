import copy
import json
import os

import numpy as np
import pytest
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure

from agentflow.compensation_view import (
    COMPENSATED_COLOR,
    UNCOMPENSATED_COLOR,
    draw_compensation_matrix,
    matrix_channels,
)
from agentflow.demo import make_demo
from agentflow.engine import prepare
from agentflow.plot_views import axis_range, fixed_limits
from agentflow.samples import read_samples


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("fixed-axes") / "demo")


@pytest.fixture(scope="module")
def recipe(demo):
    return json.loads((demo / "workflow/recipe.json").read_text())


@pytest.fixture(scope="module")
def prepared(demo, recipe):
    return [prepare(r["fcs_path"], recipe) for r in read_samples(demo / "workflow/samples.csv")]


def test_flowjo_default_transforms_linear_scatter_logicle_fluorescence(recipe):
    transforms = recipe["transforms"]
    assert transforms["FSC-A"]["kind"] == "linear"
    assert transforms["SSC-A"]["kind"] == "linear"
    for detector in ["BV1-A", "BL1-A", "YL2-A", "RL1-A"]:
        assert transforms[detector]["kind"] == "logicle"


def test_axis_range_comes_from_the_parameter_not_the_events(recipe, prepared):
    first, last = prepared[0], prepared[-1]
    # The DUMMY samples differ: 5% vs 60% reporter-positive events.
    assert not np.allclose(
        first.transformed["BL1-A"].quantile(0.9), last.transformed["BL1-A"].quantile(0.9)
    )
    for channels in (["FSC-A", "SSC-A"], ["BL1-A", "YL2-A"], ["BV1-A"]):
        a = fixed_limits(recipe, channels, first.sample)
        b = fixed_limits(recipe, channels, last.sample)
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])
    # Linear scatter spans 0..$PnR; logicle spans its full display range.
    pnr = float(first.sample.channels.iloc[first.sample.pnn_labels.index("FSC-A")]["pnr"])
    assert axis_range(recipe, "FSC-A", first.sample) == (0.0, pnr)
    assert axis_range(recipe, "BL1-A", first.sample) == pytest.approx((0.0, 1.0))


def test_locked_range_and_gate_geometry_widen_only_the_view(recipe, prepared):
    sample = prepared[0].sample
    assert axis_range(recipe, "FSC-A", sample, locked=[1000, 90000]) == (1000.0, 90000.0)
    gate = {"kind": "rectangle", "channels": ["FSC-A", "SSC-A"], "bounds": [-500, 1e6, 10, 20]}
    low, high = fixed_limits(recipe, ["FSC-A", "SSC-A"], sample, gate)
    assert low[0] == -500 and high[0] == 1e6
    assert low[1] == 0  # Gate inside the default range leaves it alone.


def test_matrix_view_overlay_toggle_and_fixed_axes(recipe, prepared):
    channels = matrix_channels(prepared[0])
    assert channels == ["BV1-A", "BL1-A", "YL2-A", "RL1-A"]
    n = len(channels)
    views = {}
    for overlay in (False, True):
        for i, sample in enumerate((prepared[0], prepared[-1])):
            fig = Figure()
            axes = draw_compensation_matrix(fig, sample, recipe, channels, overlay=overlay)
            assert len(axes) == n * (n - 1) // 2
            views[overlay, i] = {k: (ax.get_xlim(), ax.get_ylim()) for k, ax in axes.items()}
            ax = axes[("BL1-A", "YL2-A")]
            assert ax.get_xlabel().startswith("Comp-") and ax.get_ylabel().startswith("Comp-")
            colors = [to_rgb(c.get_facecolors()[0]) for c in ax.collections]
            if overlay:
                assert colors == [to_rgb(COMPENSATED_COLOR), to_rgb(UNCOMPENSATED_COLOR)]
                compensated, uncompensated = (c.get_offsets() for c in ax.collections)
                # BL1 spills 8% into YL2: uncompensated YL2 (x) sits higher for the same events.
                assert np.median(uncompensated[:, 0] - compensated[:, 0]) > 0
                assert len(fig.legends) == 1
            else:
                assert colors == [to_rgb(COMPENSATED_COLOR)]
                assert not fig.legends
    # Axes are identical across samples and with the overlay on or off.
    assert views[False, 0] == views[False, 1] == views[True, 0] == views[True, 1]


def test_matrix_view_without_compensation_never_overlays(recipe, prepared, demo):
    uncompensated = copy.deepcopy(recipe)
    uncompensated["compensation"] = {"mode": "none"}
    sample = prepare(read_samples(demo / "workflow/samples.csv")[0]["fcs_path"], uncompensated)
    channels = matrix_channels(sample)
    axes = draw_compensation_matrix(Figure(), sample, uncompensated, channels, overlay=True)
    assert all(len(ax.collections) == 1 for ax in axes.values())
    assert not any(ax.get_xlabel().startswith("Comp-") for ax in axes.values())


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(demo, recipe, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets as W

    from agentflow.workbench import ScreenWindow

    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    w = ScreenWindow(read_samples(demo / "workflow/samples.csv"), copy.deepcopy(recipe), "live", path)
    w.show()
    app.processEvents()
    yield w
    w.discarding = True
    w.close()
    app.processEvents()


def test_main_plot_axes_stay_constant_when_flipping_samples(window):
    for name in window.names:
        if window.state.gate(name) is None or window.state.draft(name):
            continue
        window.switch_sample(0)
        window.show_gate(name)
        first = window.ax.get_xlim(), window.ax.get_ylim()
        window.switch_sample(2)
        window.show_gate(name)  # Redraw from scratch, not the zoom carried across.
        assert (window.ax.get_xlim(), window.ax.get_ylim()) == first, name


def test_fit_to_events_and_locked_range_are_saved_view_settings(window):
    window.gates.setCurrentRow(window.names.index("cells"))
    fixed = window.ax.get_xlim()
    window.fit_axes.setChecked(True)
    assert window.ax.get_xlim() != fixed
    window.fit_axes.setChecked(False)
    assert window.ax.get_xlim() == fixed
    counts = window.state.counts()
    window.axis_ranges["FSC-A"] = [1000.0, 150000.0]
    window.redraw()
    assert window.ax.get_xlim() == (1000.0, 150000.0)
    assert window.state.counts() == counts
    assert window.save_changes()
    saved = json.loads(window.state.path.read_text())["display"]
    assert saved["axis_ranges"] == {"FSC-A": [1000.0, 150000.0]}
    assert saved["fit_axes"] is False


def test_compensation_matrix_dialog_flips_samples_subsets_and_overlays(window):
    from PySide6 import QtCore
    from PySide6 import QtWidgets as W
    from PySide6.QtTest import QTest

    window.compensation_matrix_dialog()
    dialog = window.matrix_view
    W.QApplication.processEvents()
    assert len(dialog.axes) == 6
    limits = {k: (ax.get_xlim(), ax.get_ylim()) for k, ax in dialog.axes.items()}
    QTest.keyClick(dialog, QtCore.Qt.Key_Right)
    assert dialog.sample.currentIndex() == 1
    assert {k: (ax.get_xlim(), ax.get_ylim()) for k, ax in dialog.axes.items()} == limits
    QTest.keyClick(dialog, QtCore.Qt.Key_Left)
    assert dialog.sample.currentIndex() == 0
    assert all(len(ax.collections) == 1 for ax in dialog.axes.values())
    dialog.overlay.setChecked(True)
    assert all(len(ax.collections) == 2 for ax in dialog.axes.values())
    assert "coral" in dialog.note.text()
    dialog.overlay.setChecked(False)
    assert all(len(ax.collections) == 1 for ax in dialog.axes.values())
    detector = next(a for a in dialog.detector_menu.actions() if a.data() == "RL1-A")
    detector.setChecked(False)
    assert len(dialog.axes) == 3
    assert dialog.detectors.text() == "3 of 4 detectors"
    dialog.step(1)  # The subset survives a sample change.
    assert len(dialog.axes) == 3
    dialog.population.setCurrentIndex(dialog.population.findData("cells"))
    assert "events" in dialog.note.text()
    dialog.close()
