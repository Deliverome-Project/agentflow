"""Descriptive acquisition checks; flags do not silently remove events."""

import numpy as np

from .acquisition import upper_limits


def sample_quality(prepared):
    raw = prepared.sample.get_events(source="raw")
    counts = []
    limits = upper_limits(prepared.sample)
    for i, channel in enumerate(prepared.sample.pnn_labels):
        data = raw[:, i]
        finite = np.isfinite(data)
        limit = limits[i]
        at_top = int(np.sum(data[finite] >= limit))
        if at_top:
            counts.append(
                {
                    "detector": channel,
                    "at_upper_range": at_top,
                    "percent": 100 * at_top / len(data) if len(data) else 0,
                }
            )
    matrix = prepared.matrix
    return {
        "event_count": len(raw),
        "upper_range_events": counts,
        "identity_compensation": matrix is not None
        and bool(np.allclose(matrix.matrix, np.eye(len(matrix.detectors)))),
        "uncompensated": matrix is None,
        "time_nonmonotonic": bool(np.any(np.diff(raw[:, prepared.sample.pnn_labels.index("Time")]) < 0))
        if "Time" in prepared.sample.pnn_labels
        else None,
    }
