"""Draft spillover edits for the N×N compensation view, as in FlowJo's matrix editor.

Values stay fractions (measured = true @ spillover); the GUI shows percent.
Drawing a draft uses FlowKit's Matrix.apply, never a separate inverse here.
Nothing in this module changes a recipe or an existing matrix file: applying
writes a new matrix file and then goes through EditorState.compensate.
"""

import copy
import hashlib
import json

import numpy as np

from . import flowkit
from .acquisition import acquisition_settings, check_acquisition
from .compensation import save_matrix, validate_compensation
from .recipes import digest

EDIT_METHOD = "manual spillover edit in the N×N compensation view"
# Dragging a population by a whole axis changes the spillover by this fraction.
DRAG_FRACTION_PER_AXIS = 0.1


def spec_sha256(spec):
    """Fingerprint of a matrix spec's canonical JSON, recorded as the edit's base."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, allow_nan=False).encode()).hexdigest()


def compensate_events(sample, spec):
    """All events of `sample` compensated with `spec` by FlowKit, without changing the sample."""
    validate_compensation(spec)
    if spec["mode"] != "matrix":
        raise ValueError("Draft compensation needs an explicit matrix")
    matrix = flowkit.Matrix(
        np.asarray(spec["values"], dtype=float),
        spec["detectors"],
        fluorochromes=spec.get("fluorochromes", spec["detectors"]),
    )
    if spec.get("acquisition"):
        check_acquisition(spec["acquisition"], acquisition_settings(sample, spec["detectors"]))
    return matrix.apply(sample)


class SpilloverDraft:
    """An edited copy of one assigned matrix with undo, reset and a list of changed cells."""

    def __init__(self, base):
        if base.get("mode") != "matrix":
            raise ValueError(
                "Spillover editing needs an explicit matrix. Import or calculate one first; "
                "Agentflow never infers compensation."
            )
        validate_compensation(base)
        self.base = copy.deepcopy(base)
        self.values = np.asarray(base["values"], dtype=float).copy()
        self.history = []

    @property
    def detectors(self):
        return list(self.base["detectors"])

    @property
    def original(self):
        return np.asarray(self.base["values"], dtype=float)

    @property
    def dirty(self):
        return bool(self.changed_cells())

    def changed_cells(self):
        return [tuple(int(v) for v in cell) for cell in np.argwhere(self.values != self.original)]

    def set(self, source, target, fraction):
        """Set how much of `source`'s dye is measured in `target` (a fraction, not percent)."""
        i, j = self.detectors.index(source), self.detectors.index(target)
        if i == j:
            raise ValueError("The diagonal is fixed at 100%")
        fraction = float(fraction)
        if not np.isfinite(fraction):
            raise ValueError("Spillover must be a finite number")
        if fraction == self.values[i, j]:
            return
        candidate = self.values.copy()
        candidate[i, j] = fraction
        validate_compensation({"mode": "matrix", "detectors": self.detectors, "values": candidate.tolist()})
        self.history.append(self.values)
        self.values = candidate

    def nudge(self, source, target, delta):
        i, j = self.detectors.index(source), self.detectors.index(target)
        self.set(source, target, self.values[i, j] + delta)

    def undo(self):
        if self.history:
            self.values = self.history.pop()

    def reset(self):
        """Back to the assigned matrix; undo can bring the edits back."""
        if self.dirty:
            self.history.append(self.values)
            self.values = self.original.copy()

    def changes(self):
        names = self.detectors
        return [
            {"source": names[i], "target": names[j], "from": float(self.original[i, j]), "to": float(self.values[i, j])}
            for i, j in self.changed_cells()
        ]

    def spec(self):
        """The draft as a matrix spec. Unedited, it is the assigned matrix itself."""
        if not self.dirty:
            return copy.deepcopy(self.base)
        base = self.base
        spec = {"mode": "matrix", "detectors": self.detectors, "values": self.values.tolist()}
        for key in ("fluorochromes", "acquisition"):
            if key in base:
                spec[key] = copy.deepcopy(base[key])
        # The edited values are no longer the estimate, so the control evidence
        # moves under edit.base_estimation instead of describing these values.
        spec["edit"] = {
            "method": EDIT_METHOD,
            "base_sha256": spec_sha256(base),
            "base_estimation": copy.deepcopy(base.get("estimation")),
            "base_edit": copy.deepcopy(base.get("edit")),
            "changes": self.changes(),
            "reviewed": False,
        }
        validate_compensation(spec)
        return spec


def drag_edit(channels, dx, dy):
    """Map a drag on plot (y_channel, x_channel) to a spillover nudge, as in FlowJo.

    dx and dy are fractions of the axis width and height. Moving the population
    down subtracts more x signal from y (raises spillover x→y); moving it left
    raises y→x. The larger movement wins. Returns (source, target, delta).
    """
    y_channel, x_channel = channels
    if abs(dy) >= abs(dx):
        return x_channel, y_channel, -dy * DRAG_FRACTION_PER_AXIS
    return y_channel, x_channel, -dx * DRAG_FRACTION_PER_AXIS


def save_edited_matrix(spec, path):
    """Write the edited matrix to a new file (never over an existing one) and record its hash."""
    if "edit" not in spec:
        raise ValueError("No spillover values were edited")
    save_matrix(spec, path)
    applied = copy.deepcopy(spec)
    applied["edit"]["saved_as"] = str(path)
    applied["edit"]["saved_sha256"] = digest(path)
    return applied
