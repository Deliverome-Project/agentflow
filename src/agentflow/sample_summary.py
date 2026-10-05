"""Headless per-sample signal summaries, preserving explicit sample metadata."""

import pandas as pd


def signal_summary(records, session, recipe, population, detector, statistic="mean"):
    if statistic not in {"mean", "median"}:
        raise ValueError("Statistic must be mean or median")
    rows = []
    for record in records:
        metrics = session.metrics(record, recipe, population, detector)
        rows.append(
            {
                **record,
                "population": population,
                "detector": detector,
                "statistic": statistic,
                "event_count": metrics["event_count"],
                "finite_event_count": metrics["finite_event_count"],
                "signal_space": metrics["signal_space"],
                "value": metrics[statistic],
            }
        )
    return pd.DataFrame(rows)
