import io
from pathlib import Path

import numpy as np

from agentflow import flowkit as fk
from agentflow.vendor_info import vendor_identity


def test_vendored_api_and_gatingml_resources():
    assert "agentflow/_vendor/flowkit" in Path(fk.__file__).as_posix()
    strategy = fk.GatingStrategy()
    strategy.add_comp_matrix("spill", fk.Matrix(np.eye(2), ["A-A", "B-A"], ["dyeA", "dyeB"]))
    strategy.add_transform("scale", fk.transforms.LinearTransform(param_t=100, param_a=0))
    strategy.add_gate(
        fk.gates.RectangleGate(
            "positive",
            [fk.Dimension("A-A", compensation_ref="spill", transformation_ref="scale", range_min=0.5)],
        ),
        ("root",),
    )
    sample = fk.Sample(np.array([[25.0, 10.0], [75.0, 10.0]]), sample_id="s", channel_labels=["A-A", "B-A"])
    stream = io.BytesIO()
    fk.export_gatingml(strategy, stream)
    stream.seek(0)
    restored = fk.parse_gating_xml(stream)
    np.testing.assert_array_equal(restored.gate_sample(sample).get_gate_membership("positive"), [False, True])
    identity = vendor_identity()
    assert identity["upstream_version"] == "1.3.2"
    assert len(identity["source_sha256"]) == 64


def test_schema_files_retain_upstream_bytes():
    import hashlib
    import json

    root = Path(fk.__file__).parent
    original = json.loads((root / "UPSTREAM.json").read_text())["original_files_sha256"]
    for path in (root / "_resources").glob("*.xsd"):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original[path.relative_to(root).as_posix()]
