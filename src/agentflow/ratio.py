"""Ratio population evaluated by FlowKit in compensated, pre-display signal units."""

import numpy as np

from ._vendor.flowkit._models.gates._base_gate import Gate


class SignalRatioGate(Gate):
    def __init__(self, name, dimensions, bounds, denominator_min):
        super().__init__(name, dimensions)
        self.gate_type = "SignalRatioGate"
        self.bounds = bounds
        self.denominator_min = denominator_min

    def apply(self, df_events):
        numerator, denominator = [df_events[d.id].to_numpy() for d in self.dimensions]
        valid = np.isfinite(numerator) & np.isfinite(denominator) & (denominator > self.denominator_min)
        ratio = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=valid)
        return valid & (ratio >= self.bounds[0]) & (ratio < self.bounds[1])
