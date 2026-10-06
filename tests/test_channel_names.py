from types import SimpleNamespace

import numpy as np
import pytest

from agentflow.channel_names import CYTOFLEX_ALIASES, channel_annotation, channel_label, instrument_name
from agentflow.plot_views import DENSITY, density_points, plot_channels


def sample(detectors, names, metadata):
    return SimpleNamespace(pnn_labels=detectors, pns_labels=names, get_metadata=lambda: metadata)


@pytest.mark.parametrize("number,alias", CYTOFLEX_ALIASES.items())
@pytest.mark.parametrize("suffix", ["A", "H"])
def test_supplied_cytoflex_aliases_preserve_detector(number, alias, suffix):
    detector = f"FL{number}-{suffix}"
    s = sample([detector], [""], {"$CYT": "CytoFLEX S"})
    assert channel_label(s, detector) == f"{alias}-{suffix} · {detector}"
    assert channel_annotation(s, detector)["source"].startswith("User-supplied")
    assert s.pnn_labels == [detector]


def test_ma900_names_are_per_file_metadata_not_a_global_stain_assignment():
    detectors = ["FL1-A", "FL6-A", "FL10-A", "FL3-A"]
    names = ["Alexa Fluor 488-A", "Brilliant Violet 421-A", "Alexa Fluor 647-A", "mScarlet3-A"]
    # Synthetic combined fixture representing labels observed in two historical panels.
    s = sample(detectors, names, {"cyt": "LE-MA900FP"})
    assert instrument_name(s) == "LE-MA900FP"
    for detector, name in zip(detectors, names):
        assert channel_annotation(s, detector) == {"detector": detector, "name": name, "source": "FCS $PnS"}
    s.pns_labels = [""] * 4
    assert all(channel_label(s, d) == d for d in detectors)


def test_metadata_overrides_alias_and_unknown_instrument_is_not_guessed():
    s = sample(["FL5-A"], ["CD3-FITC"], {"cyt": "CytoFLEX"})
    assert channel_label(s, "FL5-A") == "CD3-FITC · FL5-A"
    s.pns_labels = [""]
    s.get_metadata = dict
    assert channel_label(s, "FL5-A") == "FL5-A"
    assert instrument_name(s) == "Unknown instrument"
    s.pns_labels = ["FL5-A"]
    assert channel_annotation(s, "FL5-A")["name"] == "FL5-A"


def test_fcs_inspection_derives_labels_without_renaming_data(tmp_path):
    import flowio

    from agentflow import flowkit
    from agentflow.workflow import inspect_sample

    path = tmp_path / "synthetic-ma900.fcs"
    with path.open("wb") as handle:
        flowio.create_fcs(
            handle,
            [1.0, 2.0, 3.0, 4.0],
            ["FL1-A", "FL10-A"],
            ["Alexa Fluor 488-A", "Alexa Fluor 647-A"],
            metadata_dict={"cyt": "LE-MA900FP"},
        )
    original = path.read_bytes()
    info = inspect_sample(path)
    assert info["instrument"] == "LE-MA900FP"
    assert info["channels"][0]["name"] == "Alexa Fluor 488-A"
    assert info["channels"][1]["source"] == "FCS $PnS"
    assert flowkit.Sample(str(path)).pnn_labels == ["FL1-A", "FL10-A"]
    assert path.read_bytes() == original


def test_density_uses_all_events_and_caps_only_display_points():
    data = np.concatenate([np.zeros((30000, 2)), [[10, 10], [np.nan, 0]]])
    original = data.copy()
    points, counts = density_points(data)
    assert len(points) == 20000
    assert counts.max() == 30000  # not the 20,000 display subset
    assert np.all(np.diff(counts) >= 0)
    np.testing.assert_array_equal(data, original)
    np.testing.assert_array_equal(density_points(data)[0], points)
    assert DENSITY(0.0)[2] > DENSITY(0.0)[0]
    assert DENSITY(1.0)[0] > DENSITY(1.0)[2]
    assert len(density_points(data, (np.array([20, 20]), np.array([30, 30])))[0]) == 0
    assert density_points(np.empty((0, 2)))[0].shape == (0, 2)


def test_display_axes_do_not_change_one_dimensional_gate():
    gate = {"kind": "range", "channels": ["FL3-A"], "bounds": [1, None]}
    recipe = {"transforms": {"FL3-A": {}, "SSC-A": {}, "FSC-A": {}}}
    assert plot_channels(gate, recipe) == ["FL3-A", "SSC-A"]
    assert plot_channels(gate, recipe, {"range_y_channel": "FSC-A"}) == ["FL3-A", "FSC-A"]
    assert plot_channels(gate, recipe, {"plot_type": "Histogram"}) == ["FL3-A"]
    assert plot_channels(gate, {"transforms": {"FL3-A": {}}}) == ["FL3-A"]
    assert gate["channels"] == ["FL3-A"]
