import numpy as np

from agentflow import flowkit
from agentflow.engine import evaluate, prepare
from agentflow.recipes import load_recipe, save_recipe


def test_compensated_ratio_bounds_and_yaml(tmp_path):
    truth = np.array([[20.0, 10.0], [10.0, 10.0], [5.0, 10.0], [1.0, 0.0], [-1.0, -1.0], [20.0, 1.0]])
    spill = np.array([[1.0, 0.2], [0.1, 1.0]])
    sample = flowkit.Sample(truth @ spill, sample_id="ratio", channel_labels=["GFP-A", "CY5-A"])
    recipe = {
        "version": 1,
        "compensation": {"mode": "matrix", "detectors": ["GFP-A", "CY5-A"], "values": spill.tolist()},
        "transforms": {c: {"kind": "asinh", "cofactor": 150} for c in sample.pnn_labels},
        "gates": [
            {
                "name": "ratio",
                "parent": "root",
                "kind": "ratio",
                "channels": sample.pnn_labels,
                "bounds": [0.75, 1.75],
                "denominator_min": 2.0,
                "reviewed": False,
            },
            {
                "name": "child",
                "parent": "ratio",
                "kind": "range",
                "channels": ["GFP-A"],
                "bounds": [0.0, 100.0],
            },
        ],
    }
    path = tmp_path / "recipe.yaml"
    save_recipe(path, recipe)
    restored = load_recipe(path)
    masks = evaluate(prepare(sample, restored), restored)
    np.testing.assert_array_equal(masks["ratio"], [False, True, False, False, False, False])
    np.testing.assert_array_equal(masks["child"], masks["ratio"])


def test_instrument_metadata_preserves_reported_fields(tmp_path):
    import flowio

    from agentflow.acquisition import instrument_provenance

    path = tmp_path / "instrument.fcs"
    with path.open("wb") as handle:
        flowio.create_fcs(
            handle,
            [10.0, 20.0],
            ["GFP-A", "CY5-A"],
            metadata_dict={
                "cyt": "Example instrument",
                "cytsn": "DEMO-123",
                "p1g": "2",
                "p1v": "450",
                "date": "10-SEP-2026",
            },
        )
    result = instrument_provenance(flowkit.Sample(str(path)))
    assert result["instrument"] == "Example instrument"
    assert result["serial_number"] == "DEMO-123"
    assert result["detectors"]["GFP-A"]["gain"] == 2
    assert result["detectors"]["GFP-A"]["voltage"] == 450
    assert result["detectors"]["CY5-A"]["voltage"] is None


def test_standard_ratio_gatingml_roundtrip_and_cached_transforms(tmp_path):
    from agentflow.engine import build_strategy

    truth = np.array([[10.0, 10.0], [20.0, 10.0], [1.0, 0.0], [-2.0, -1.0], [5.0, 2.0]])
    spill = np.array([[1.0, 0.2], [0.1, 1.0]])
    sample = flowkit.Sample(truth @ spill, sample_id="gml-ratio", channel_labels=["GFP-A", "CY5-A"])
    recipe = {
        "version": 1,
        "compensation": {"mode": "matrix", "detectors": sample.pnn_labels, "values": spill.tolist()},
        "transforms": {c: {"kind": "asinh", "cofactor": 150} for c in sample.pnn_labels},
        "gates": [
            {
                "name": "all",
                "parent": "root",
                "kind": "range",
                "channels": ["GFP-A"],
                "bounds": [-10.0, 10.0],
            },
            {
                "name": "ratio",
                "parent": "all",
                "kind": "ratio",
                "channels": sample.pnn_labels,
                "bounds": [0.75, 1.75],
                "denominator_min": 0.0,
            },
        ],
    }
    prepared = prepare(sample, recipe)
    strategy = build_strategy(recipe, prepared.matrix)
    path = tmp_path / "ratio.gml"
    with path.open("wb") as handle:
        flowkit.export_gatingml(strategy, handle)
    restored = flowkit.parse_gating_xml(str(path))
    for engine in (strategy, restored):
        for _ in range(3):
            results = engine.gate_sample(sample, cache_events=True)
            np.testing.assert_array_equal(
                results.get_gate_membership("ratio"), [True, False, False, False, False]
            )
    # Two ratio dimensions keep one event per row, and obey their declared compensation.
    for ref, channels in [("first", sample.pnn_labels), ("second", list(reversed(sample.pnn_labels)))]:
        strategy.add_transform(ref, flowkit.transforms.RatioTransform(channels, 1.0, 0.0, 0.0))
    strategy.add_gate(
        flowkit.gates.RectangleGate(
            "two-ratios",
            [
                flowkit.RatioDimension("first", "compensation", range_min=0.75, range_max=1.75),
                flowkit.RatioDimension("second", "compensation", range_min=0.75, range_max=1.75),
            ],
        ),
        ("root",),
    )
    np.testing.assert_array_equal(
        strategy.gate_sample(sample).get_gate_membership("two-ratios"), [True, False, False, False, False]
    )
    transform = flowkit.transforms.RatioTransform(sample.pnn_labels, 1.0, 0.0, 0.0)
    raw = sample.get_events(source="raw")
    np.testing.assert_allclose(transform.apply(sample), raw[:, 0] / raw[:, 1])
