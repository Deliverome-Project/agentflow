"""Independent compensation fixtures, including acquisition and display edge cases."""

import json

import flowio
import numpy as np
import pytest

from agentflow import flowkit as fk
from agentflow.compensation import estimate_controls
from agentflow.engine import evaluate, prepare


def write_fcs(path, data, labels, metadata=None):
    with path.open("wb") as handle:
        flowio.create_fcs(handle, np.asarray(data).ravel().tolist(), labels, metadata_dict=metadata)


@pytest.mark.parametrize("mode", ["matrix", "fcs"])
def test_asymmetric_reordered_subset_negative_and_repeat(tmp_path, mode):
    truth = np.array([[100.0, 20.0, -5.0], [-10.0, 50.0, 70.0], [0.0, 0.0, 0.0]])
    spill = np.array([[1.0, 0.2, 0.05], [0.07, 1.0, 0.13], [0.03, 0.11, 1.0]])
    measured = truth @ spill
    data = np.column_stack([measured[:, 2], [1000, 2000, 3000], measured[:, 0], measured[:, 1]])
    order = [1, 2, 0]
    reordered = spill[np.ix_(order, order)]
    detectors = ["B-A", "C-A", "A-A"]
    metadata = {"spillover": ",".join(["3", *detectors, *map(str, reordered.ravel())])}
    path = tmp_path / "sample.fcs"
    write_fcs(path, data, ["C-A", "FSC-A", "A-A", "B-A"], metadata)
    sample = fk.Sample(str(path))
    untouched = sample.get_events(source="raw").copy()
    recipe = {
        "version": 1,
        "compensation": {"mode": mode, "detectors": detectors, "values": reordered.tolist()},
        "transforms": {"A-A": {"kind": "asinh", "cofactor": 150}},
        "gates": [
            {
                "name": "positive",
                "kind": "range",
                "parent": "root",
                "channels": ["A-A"],
                "bounds": [0.1, None],
            }
        ],
    }
    for _ in range(2):
        result = prepare(sample, recipe)
        np.testing.assert_allclose(result.values[["A-A", "B-A", "C-A"]], truth, atol=2e-5)
        np.testing.assert_array_equal(result.values["FSC-A"], data[:, 1])
        np.testing.assert_array_equal(evaluate(result, recipe)["positive"], [True, False, False])
        np.testing.assert_array_equal(sample.get_events(source="raw"), untouched)
    recipe["compensation"] = {"mode": "none"}
    np.testing.assert_array_equal(prepare(sample, recipe).values, untouched)


def controls_config(tmp_path, metadata=None, first_positive=(100.0, 20.0)):
    controls = []
    for index, detector in enumerate(["A-A", "B-A"]):
        path = tmp_path / f"control-{index}.fcs"
        positive = first_positive if index == 0 else (15.0, 100.0)
        data = np.vstack([np.tile([1.0, 1.0], (60, 1)), np.tile(positive, (60, 1))])
        write_fcs(path, data, ["A-A", "B-A"], metadata)
        controls.append(
            {"detector": detector, "fcs_path": str(path), "negative_max": 2.0, "positive_min": 5.0}
        )
    path = tmp_path / "controls.json"
    path.write_text(json.dumps({"detectors": ["A-A", "B-A"], "controls": controls}))
    return path


@pytest.mark.parametrize(
    "metadata,positive",
    [
        ({"p1r": "1024", "p1g": "10"}, (1023.0, 20.0)),
        ({"p2r": "1024"}, (100.0, 1023.0)),
    ],
)
def test_reject_saturation_after_gain_or_in_receiving_detector(tmp_path, metadata, positive):
    config = controls_config(tmp_path, metadata, positive)
    with pytest.raises(ValueError, match="saturated"):
        estimate_controls(config)


def test_estimated_matrix_rejects_sample_voltage_change(tmp_path):
    from agentflow.compensation import resolve_compensation

    config = controls_config(tmp_path, {"p1v": "450", "p2v": "500"})
    spec = estimate_controls(config)
    path = tmp_path / "experiment.fcs"
    write_fcs(path, [[100.0, 20.0]], ["A-A", "B-A"], {"p1v": "451", "p2v": "500"})
    with pytest.raises(ValueError, match="A-A.*voltage"):
        resolve_compensation(fk.Sample(str(path)), spec)


def test_reject_control_voltage_change(tmp_path):
    config = controls_config(tmp_path, {"p1v": "450", "p2v": "500"})
    path = tmp_path / "control-1.fcs"
    original = fk.Sample(str(path)).get_events(source="raw")
    write_fcs(path, original, ["A-A", "B-A"], {"p1v": "450", "p2v": "550"})
    with pytest.raises(ValueError, match="B-A.*voltage"):
        estimate_controls(config)


def test_diagnostics_use_saved_cleanup_and_native_compensation(tmp_path, monkeypatch):
    from agentflow import plots, save_recipe
    from agentflow.compensation import control_diagnostics

    config_path = controls_config(tmp_path)
    config = json.loads(config_path.read_text())
    for control in config["controls"]:
        path = tmp_path / (control["detector"] + ".fcs")
        data = fk.Sample(control["fcs_path"]).get_events(source="raw")
        data = np.column_stack([data, np.tile([10.0, 100.0], 60)])
        write_fcs(path, data, ["A-A", "B-A", "FSC-A"])
        control["fcs_path"] = str(path)
    config["min_events"] = 20
    config["cleanup_recipe"], config["cleanup_gate"] = "cleanup.json", "cells"
    cleanup = {
        "version": 1,
        "compensation": {"mode": "none"},
        "transforms": {"FSC-A": {"kind": "linear"}},
        "gates": [
            {"name": "cells", "kind": "range", "parent": "root", "channels": ["FSC-A"], "bounds": [50, None]}
        ],
    }
    save_recipe(tmp_path / "cleanup.json", cleanup)
    config_path.write_text(json.dumps(config))
    spec = estimate_controls(config_path)
    assert all(c["positive_count"] == 30 for c in spec["estimation"]["controls"])
    # Later edits to the source cleanup must not alter what a saved matrix review shows.
    cleanup["gates"][0]["bounds"] = [None, 0]
    save_recipe(tmp_path / "cleanup.json", cleanup)
    figures = []
    original = plots.new_figure

    def capture(*args):
        fig = original(*args)
        figures.append(fig)
        return fig

    monkeypatch.setattr(plots, "new_figure", capture)
    control_diagnostics(config_path, spec, tmp_path / "diagnostics")
    for fig in figures:
        assert len(fig.axes[0].collections[0].get_offsets()) == 60
        corrected = np.asarray(fig.axes[1].collections[0].get_offsets())[:, 1]
        assert np.median(corrected[:30]) == pytest.approx(np.median(corrected[30:]), abs=1e-10)


def test_quality_upper_range_uses_gain_adjusted_units(tmp_path):
    from agentflow.quality import sample_quality

    path = tmp_path / "saturated.fcs"
    write_fcs(path, [[1023.0, 1.0], [1.0, 1.0]], ["A-A", "B-A"], {"p1r": "1024", "p1g": "10"})
    result = prepare(path, {"version": 1, "compensation": {"mode": "none"}, "transforms": {}, "gates": []})
    assert sample_quality(result)["upper_range_events"] == [
        {"detector": "A-A", "at_upper_range": 1, "percent": 50.0}
    ]
