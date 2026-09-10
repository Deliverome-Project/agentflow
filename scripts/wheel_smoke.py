"""Run outside the checkout's editable environment against the built wheel."""

import importlib.util
import io
from pathlib import Path

import numpy as np

from agentflow import flowkit as fk
from agentflow.vendor_info import vendor_identity

assert importlib.util.find_spec("flowkit") is None
assert "site-packages" in str(Path(fk.__file__))
strategy = fk.GatingStrategy()
strategy.add_gate(fk.gates.RectangleGate("positive", [fk.Dimension("A-A", range_min=50)]), ("root",))
stream = io.BytesIO()
fk.export_gatingml(strategy, stream)
stream.seek(0)
restored = fk.parse_gating_xml(stream)
sample = fk.Sample(np.array([[20.0], [80.0]]), sample_id="s", channel_labels=["A-A"])
np.testing.assert_array_equal(restored.gate_sample(sample).get_gate_membership("positive"), [False, True])
assert (Path(fk.__file__).parent / "LICENSE").exists()
assert vendor_identity()["upstream_version"] == "1.3.2"
print("Installed wheel: vendored imports, XML resources, license and provenance passed.")
