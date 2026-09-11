import json

import flowio
import numpy as np
import pandas as pd
import pytest
import yaml

from agentflow.batch import run_batch
from agentflow.engine import evaluate, prepare, save_recipe, summarize
from agentflow.event_export import EventWriter
from agentflow.sample_sheet import draft_sample_sheet


def test_events_and_summary_agree_with_compensation(tmp_path):
    truth = np.array([[10.0, 20.0], [100.0, 200.0], [-3.0, 0.0]])
    matrix = np.array([[1, 0.1], [0.2, 1]])
    recipe = {
        "version": 1,
        "compensation": {"mode": "matrix", "detectors": ["A", "B"], "values": matrix.tolist()},
        "transforms": {"A": {"kind": "linear"}, "B": {"kind": "linear"}},
        "gates": [
            {"name": "positive", "parent": "root", "kind": "range", "channels": ["A"], "bounds": [0, 1000]}
        ],
    }
    for i in (1, 2):
        with (tmp_path / f"{i}.fcs").open("wb") as handle:
            flowio.create_fcs(
                handle,
                (truth @ matrix).ravel().tolist(),
                ["A", "B"],
                metadata_dict={"cyt": "Example instrument", "cytsn": "123"},
            )
    annotations = tmp_path / "annotations.yaml"
    annotations.write_text(
        yaml.safe_dump(
            {
                "samples": [
                    {
                        "file": "1.fcs",
                        "metadata": {"group": "Treatment", "well": "A01"},
                        "source_url": "https://www.notion.so/example",
                        "reviewed": False,
                    }
                ]
            }
        )
    )
    sheet = tmp_path / "sheet"
    rows = draft_sample_sheet(tmp_path, sheet, annotations)
    assert rows[0]["group"] == "Treatment"
    assert rows[1]["group"] == ""
    assert rows[0]["fcs:instrument"] == "Example instrument"
    assert not rows[0]["metadata_reviewed"]
    save_recipe(tmp_path / "recipe.yaml", recipe)
    summary = run_batch(sheet / "samples.csv", tmp_path / "recipe.yaml", tmp_path / "run")
    events = pd.read_parquet(tmp_path / "run/events.parquet")
    assert len(events) == 6
    assert not events.duplicated(["sample_id", "event_index"]).any()
    for sample_id, group in events.groupby("sample_id"):
        np.testing.assert_array_equal(group.event_index, [0, 1, 2])
        np.testing.assert_allclose(group[["signal:A", "signal:B"]], truth, atol=1e-5)
        np.testing.assert_allclose(group[["raw:A", "raw:B"]], truth @ matrix, atol=1e-5)
        for gate in ("root", "positive"):
            selected = group.loc[group["gate:" + gate], "signal:A"]
            row = summary.loc[(summary.sample_id == sample_id) & (summary.gate == gate)].iloc[0]
            assert row["count"] == len(selected)
            assert row["mean_signal:A"] == pytest.approx(selected.mean())
            assert row["sd_signal:A"] == pytest.approx(selected.std())
            assert row["p95_signal:A"] == pytest.approx(selected.quantile(0.95))
    assert json.loads(events.iloc[0].instrument_json)["serial_number"] == "123"
    assert events.iloc[0]["metadata:annotation_source"] == "https://www.notion.so/example"
    with (tmp_path / "1.fcs").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="fingerprint"):
        run_batch(sheet / "samples.csv", tmp_path / "recipe.yaml", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_export_union_detectors_and_empty_statistics(tmp_path):
    recipe = {
        "version": 1,
        "compensation": {"mode": "none"},
        "transforms": {"A": {"kind": "linear"}},
        "gates": [
            {"name": "empty", "parent": "root", "kind": "range", "channels": ["A"], "bounds": [100, 200]}
        ],
    }
    records = []
    for i, channels in enumerate([["A", "Extra"], ["A"]]):
        path = tmp_path / f"{i}.fcs"
        with path.open("wb") as handle:
            flowio.create_fcs(handle, [1.0] * len(channels), channels)
        records.append({"sample_id": str(i), "fcs_path": str(path)})
    writer = EventWriter(tmp_path / "events.parquet", records, recipe)
    for record in records:
        prepared = prepare(record["fcs_path"], recipe)
        masks = evaluate(prepared, recipe)
        writer.write(prepared, masks, record, "hash")
        stats = summarize(prepared, recipe, masks).set_index("gate")
        assert pd.isna(stats.loc["empty", "mean_signal:A"])
        assert pd.isna(stats.loc["root", "sd_signal:A"])
    writer.close()
    table = pd.read_parquet(tmp_path / "events.parquet")
    assert table.loc[0, "signal:Extra"] == 1
    assert pd.isna(table.loc[1, "signal:Extra"])


def test_annotations_reject_ambiguous_or_unknown_files(tmp_path):
    path = tmp_path / "sample.fcs"
    with path.open("wb") as handle:
        flowio.create_fcs(handle, [1.0], ["A"])
    annotation = tmp_path / "notes.yaml"
    for entries in [[{"file": "missing.fcs"}], [{"file": "sample.fcs"}, {"file": "sample.fcs"}]]:
        annotation.write_text(yaml.safe_dump({"samples": entries}))
        with pytest.raises(ValueError, match="exact relative"):
            draft_sample_sheet(tmp_path, tmp_path / "out", annotation)


def test_screen_mean_uses_finite_population_events(tmp_path):
    from agentflow.screening import screen_report

    run = tmp_path / "run"
    run.mkdir()
    pd.DataFrame(
        [
            {
                "sample_id": "s1",
                "gate": "gfp",
                "count": 500,
                "parent_count": 1000,
                "mean_signal:A": 10,
                "finite_signal_count:A": 2,
                "metadata:well": "A01",
            }
        ]
    ).to_csv(run / "summary.csv", index=False)
    result = screen_report(run, tmp_path / "screen", "gfp", metric="mean_signal:A", min_events=100)
    assert not result.iloc[0].qc_pass
    assert result.iloc[0].qc_population_events == 2
