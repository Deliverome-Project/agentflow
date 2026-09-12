"""Headless per-sample signal summaries, preserving explicit sample metadata."""

import numpy as np
import pandas as pd


def signal_summary(records, session, recipe, population, detector, statistic="mean"):
    if statistic not in {"mean", "median"}:
        raise ValueError("Statistic must be mean or median")
    rows = []
    for record in records:
        prepared, masks = session.get(record, recipe)
        if population not in masks or detector not in prepared.values:
            raise ValueError(f"{record['sample_id']}: population or detector unavailable")
        values = prepared.values.loc[masks[population], detector].to_numpy()
        finite = values[np.isfinite(values)]
        rows.append(
            {
                **record,
                "population": population,
                "detector": detector,
                "statistic": statistic,
                "event_count": len(values),
                "finite_event_count": len(finite),
                "signal_space": "compensated" if prepared.matrix is not None else "raw",
                "value": float(getattr(np, statistic)(finite)) if len(finite) else np.nan,
            }
        )
    return pd.DataFrame(rows)
