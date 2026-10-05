"""Reproducible synthetic plate benchmark; writes data/results only to --out."""

import argparse
import copy
import cProfile
import json
import platform
import pstats
import time
from pathlib import Path

import flowio
import numpy as np
import pandas as pd

from agentflow.batch import run_batch
from agentflow.engine import evaluate, prepare, summarize
from agentflow.plots import save_qc
from agentflow.sample_summary import signal_summary
from agentflow.samples import SampleSession, read_samples


def fixture(out, wells, events, channel_count):
    rng = np.random.default_rng(42)
    channels = ["Time", "FSC-A", "SSC-A", "FSC-H", "BV1-A", "BL1-A", "YL2-A", "RL1-A"]
    channels += [f"Unused-{i}-A" for i in range(channel_count - len(channels))]
    matrix = np.eye(4) + (np.ones((4, 4)) - np.eye(4)) * 0.02
    recipe = {
        "version": 1,
        "experiment": {"label": "SYNTHETIC PERFORMANCE BENCHMARK", "is_example": True},
        "compensation": {"mode": "matrix", "detectors": channels[4:8], "values": matrix.tolist()},
        "transforms": {c: {"kind": "linear"} for c in channels[1:4]},
        "gates": [
            {
                "name": "cells",
                "parent": "root",
                "kind": "rectangle",
                "channels": channels[1:3],
                "bounds": [20000, 150000, 10000, 100000],
            },
            {
                "name": "singlets",
                "parent": "cells",
                "kind": "polygon",
                "channels": ["FSC-A", "FSC-H"],
                "vertices": [[20000, 10000], [150000, 110000], [150000, 150000], [20000, 25000]],
            },
        ],
    }
    for c in channels[4:8]:
        recipe["transforms"][c] = {
            "kind": "logicle",
            "parameters": {"param_t": 262144, "param_w": 0.5, "param_m": 4.5, "param_a": 0},
        }
        recipe["gates"].append(
            {"name": c, "parent": "singlets", "kind": "range", "channels": [c], "bounds": [0.4, None]}
        )
    recipe["gates"].append(
        {
            "name": "double",
            "parent": "singlets",
            "kind": "boolean",
            "channels": ["BL1-A", "YL2-A"],
            "operation": "and",
            "references": ["BL1-A", "YL2-A"],
        }
    )
    records = []
    for i in range(wells):
        area = rng.lognormal(np.log(60000), 0.25, events)
        truth = rng.normal(100, 30, (events, 4)) + 20000 * (rng.random((events, 4)) < 0.3)
        data = np.column_stack(
            [
                np.arange(events) * 0.01,
                area,
                rng.lognormal(np.log(30000), 0.3, events),
                area * rng.normal(0.85, 0.05, events),
                truth @ matrix,
            ]
        )
        data = np.column_stack([data, rng.normal(100, 30, (events, channel_count - 8))])
        path = out / f"well-{i:03d}.fcs"
        with path.open("wb") as handle:
            flowio.create_fcs(handle, data.ravel().tolist(), channels)
        records.append(
            {
                "sample_id": f"SYNTHETIC-{i:03d}",
                "fcs_path": str(path),
                "well": f"{chr(65 + i // 12)}{i % 12 + 1:02d}",
                "plate": "Synthetic",
            }
        )
    pd.DataFrame(records).to_csv(out / "samples.csv", index=False)
    (out / "recipe.json").write_text(json.dumps(recipe))
    return recipe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wells", type=int, default=96)
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--input", type=Path, help="Reuse an existing synthetic fixture folder")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--skip-batch", action="store_true")
    args = parser.parse_args()
    if args.wells < 1 or args.events < 1 or args.channels < 8:
        parser.error("Use positive wells/events and at least eight channels")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    source = args.input.resolve() if args.input else args.out
    recipe = (
        json.loads((source / "recipe.json").read_text())
        if args.input
        else fixture(args.out, args.wells, args.events, args.channels)
    )
    records = read_samples(source / "samples.csv")
    headers = [flowio.FlowData(record["fcs_path"], only_text=True) for record in records]
    metadata = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "wells": len(records),
        "channels": sorted({h.channel_count for h in headers}),
        "events_per_well": [h.event_count for h in headers],
        "profiled": args.profile,
        "workers": args.workers,
    }
    times = {}

    def timed(name, function):
        start = time.perf_counter()
        result = function()
        times[name] = time.perf_counter() - start
        print(f"{name}: {times[name]:.4f}s", flush=True)
        (args.out / "timings.json").write_text(json.dumps({**metadata, "seconds": times}, indent=2))
        return result

    prepared = timed("prepare_one", lambda: prepare(records[0]["fcs_path"], recipe))
    masks = timed("gate_one", lambda: evaluate(prepared, recipe))
    timed("summarize_one", lambda: summarize(prepared, recipe, masks))
    timed("qc_one", lambda: save_qc(prepared, recipe, masks, args.out / "qc.png", "Synthetic"))
    session = SampleSession(records)
    for phase in ["cold", "warm", "edited"]:
        if phase == "edited":
            recipe = copy.deepcopy(recipe)
            recipe["gates"][2]["bounds"][0] += 0.05
        frame = timed(
            f"plate_summary_{phase}",
            lambda recipe=recipe: signal_summary(records, session, recipe, "BV1-A", "BL1-A", "median"),
        )
        frame.to_csv(args.out / f"summary-{phase}.csv", index=False)
    profile = cProfile.Profile()
    if not args.skip_batch:
        if args.profile:
            profile.enable()
        timed(
            "batch",
            lambda: run_batch(
                source / "samples.csv",
                source / "recipe.json",
                args.out / "run",
                **({"workers": args.workers} if args.workers != 1 else {}),
            ),
        )
        profile.disable()
        if args.profile:
            with (args.out / "profile.txt").open("w") as handle:
                pstats.Stats(profile, stream=handle).sort_stats("cumulative").print_stats(45)


if __name__ == "__main__":
    main()
