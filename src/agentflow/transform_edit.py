"""Change a detector's transform while keeping every gate's raw-signal boundary.

Gate geometry is stored in transformed coordinates, so a new transform would
otherwise move every gate on that detector. Each coordinate is converted through
raw signal (old inverse, then new forward). Transforms are monotonic, so range,
rectangle and quadrant membership is unchanged. A straight polygon edge in the
old space is a curve in the new one; edges are subdivided until the new chords,
mapped back, stay within ``tolerance`` of the drawn edge. The residual count
change is reported to the user.
"""

import copy

import numpy as np

from .engine import evaluate, make_transform, prepare
from .recipes import validate

# Fraction of the drawn polygon's extent on each axis.
POLYGON_TOLERANCE = 1e-4
MAX_DEPTH = 10
NO_GEOMETRY = {"boolean", "ratio"}  # Ratios are gated on raw signal.


def converter(old_spec, new_spec):
    old, new = make_transform(old_spec), make_transform(new_spec)

    def convert(values):
        values = np.asarray(values, dtype=float)
        raw = values if old is None else old.inverse(values)
        return raw if new is None else new.apply(raw)

    return convert


def _bounds(bounds, converters):
    """Convert [lo, hi] pairs per channel; null endpoints stay open."""
    result = []
    for i, value in enumerate(bounds):
        forward = converters[i // 2][0]
        result.append(None if value is None else float(forward(np.array([value]))[0]))
    return result


def _polygon(vertices, converters, tolerance=POLYGON_TOLERANCE):
    """Map vertices and subdivide each edge until it follows the drawn edge.

    Deviation is measured where the gate was drawn: new chords are mapped back
    to the old coordinates and compared with the original straight edge, per
    axis relative to the drawn polygon's extent.
    """
    old = np.asarray(vertices, dtype=float)

    def through(points, direction):
        points = np.atleast_2d(points)
        return np.column_stack([converters[0][direction](points[:, 0]), converters[1][direction](points[:, 1])])

    moved = through(old, 0)
    scale = np.ptp(old, axis=0)
    scale[scale <= 0] = 1.0

    def deviation(a, b, fa, fb):
        t = np.array([0.25, 0.5, 0.75])[:, None]
        back = through(fa + t * (fb - fa), 1) / scale
        start, edge = a / scale, (b - a) / scale
        length = float(edge @ edge)
        along = np.clip((back - start) @ edge / length, 0, 1) if length else np.zeros(len(t))
        return float(np.max(np.linalg.norm(back - start - along[:, None] * edge, axis=1)))

    def split(a, b, fa, fb, depth):
        if depth >= MAX_DEPTH or deviation(a, b, fa, fb) <= tolerance:
            return []
        middle = (a + b) / 2
        fm = through(middle, 0)[0]
        return [*split(a, middle, fa, fm, depth + 1), fm, *split(middle, b, fm, fb, depth + 1)]

    result = []
    for i in range(len(old)):
        j = (i + 1) % len(old)
        result.append(moved[i])
        result.extend(split(old[i], old[j], moved[i], moved[j], 0))
    return [[float(x), float(y)] for x, y in result]


def migrate_geometry(geometry, converters, tolerance=POLYGON_TOLERANCE):
    """Migrate one gate's ``bounds``/``vertices`` (a gate or a sample-override patch).

    ``converters`` holds a (forward, backward) pair of functions per gate channel.
    """
    result = {}
    if "vertices" in geometry:
        result["vertices"] = _polygon(geometry["vertices"], converters, tolerance)
    if "bounds" in geometry:
        result["bounds"] = _bounds(geometry["bounds"], converters)
    return result


def affected_gates(recipe, channel):
    return [
        g["name"]
        for g in recipe["gates"]
        if channel in g["channels"] and g["kind"] not in NO_GEOMETRY
    ]


def retransform(recipe, channel, spec, tolerance=POLYGON_TOLERANCE):
    """Return (candidate recipe, migrated gate names); review status is left to the caller."""
    if channel not in recipe["transforms"]:
        raise ValueError(f"{channel} has no transform in this recipe")
    candidate = copy.deepcopy(recipe)
    old_spec = recipe["transforms"][channel]
    candidate["transforms"][channel] = copy.deepcopy(spec)
    if spec == old_spec:
        return candidate, []
    convert = converter(old_spec, spec), converter(spec, old_spec)
    names = affected_gates(recipe, channel)

    def same(values):
        return np.asarray(values, dtype=float)

    gates = {g["name"]: g for g in candidate["gates"]}
    for name in names:
        gate = gates[name]
        converters = [convert if c == channel else (same, same) for c in gate["channels"]]
        gate.update(migrate_geometry(gate, converters, tolerance))
        for changes in candidate.get("sample_overrides", {}).values():
            if name in changes:
                changes[name].update(migrate_geometry(changes[name], converters, tolerance))
    validate(candidate)
    return candidate, names


def count_changes(sample, old_recipe, new_recipe):
    """All-event counts per gate before and after, on one sample: {name: (before, after)}."""
    before = evaluate(prepare(sample, old_recipe), old_recipe, allow_unfinished=True)
    after = evaluate(prepare(sample, new_recipe), new_recipe, allow_unfinished=True)
    return {g["name"]: (int(before[g["name"]].sum()), int(after[g["name"]].sum())) for g in old_recipe["gates"]}
