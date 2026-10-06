"""Offscreen Qt interaction benchmark against benchmark_plate's synthetic fixture."""

import argparse
import json
import os
import time
from itertools import pairwise
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore
from PySide6 import QtWidgets as W

from agentflow.samples import read_samples
from agentflow.workbench import ScreenWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=20, help="Warm interaction trials per action")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    recipe = json.loads((args.input / "recipe.json").read_text())
    records = read_samples(args.input / "samples.csv")
    app = W.QApplication.instance() or W.QApplication([])
    times = {}
    ticks = []
    heartbeat = QtCore.QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
    heartbeat.start(20)
    started = time.perf_counter()
    ticks.append(started)
    window = ScreenWindow(records, recipe, "BV1-A", args.input / "recipe.json")
    window.show()

    def settle():
        deadline = time.perf_counter() + 180
        while True:
            app.processEvents()
            if not window.gallery_pending:
                window.canvas.draw()
                window.gallery_canvas.draw()
                app.processEvents()
                if not window.gallery_pending:
                    return
            if time.perf_counter() > deadline:
                raise TimeoutError("Editor did not finish its comparison")

    settle()
    times["open_complete"] = time.perf_counter() - started
    times["open_max_heartbeat_gap"] = max(b - a for a, b in pairwise(ticks))
    for name, action in [
        ("switch_sample", lambda: window.sample_choice.setCurrentIndex(1)),
        ("redraw", window.redraw),
        ("select_population", lambda: window.show_gate("BL1-A")),
    ]:
        started = time.perf_counter()
        action()
        times[name + "_handler"] = time.perf_counter() - started
        settle()
        times[name + "_complete"] = time.perf_counter() - started
    started = time.perf_counter()
    window.state.geometry("BL1-A", "bounds", [0.45, None])
    window.show_gate("BL1-A")
    times["edit_gate_handler"] = time.perf_counter() - started
    settle()
    times["edit_gate_complete"] = time.perf_counter() - started
    for name, action in [
        ("compare_samples_first", lambda: window.gallery_mode.setCurrentIndex(1)),
        ("compare_samples_next_page", lambda: window.gallery_page.setValue(2)),
        ("compare_samples_redraw", window.request_gallery),
    ]:
        started = time.perf_counter()
        action()
        settle()
        times[name] = time.perf_counter() - started
    window.grab().save(str(args.out / "editor.png"))

    # Separately measure the first main-plot Agg render. The older completion
    # timer deliberately forces both canvases to draw and is not input-to-paint.
    # These offscreen timings cannot establish native on-screen presentation latency.
    first_draws = []
    token = window.canvas.mpl_connect("draw_event", lambda event: first_draws.append(time.perf_counter()))
    trials = {}

    def trial(action):
        first_draws.clear()
        started = time.perf_counter()
        action()
        handler = time.perf_counter() - started
        deadline = started + 180
        while window.gallery_pending or not first_draws:
            app.processEvents()
            if time.perf_counter() > deadline:
                raise TimeoutError("Repeated interaction did not render")
        app.processEvents()
        return {
            "handler": handler,
            "first_plot_draw": first_draws[0] - started,
            "comparison_complete": time.perf_counter() - started,
        }

    window.gallery_mode.setCurrentText("Sample MFI")
    settle()
    # Warm both focused samples. Plate summaries and render caches are separate.
    for index in [1, 0]:
        window.sample_choice.setCurrentIndex(min(index, len(records) - 1))
        settle()
    for name, action in [
        (
            "cached_sample_switch",
            lambda i: window.sample_choice.setCurrentIndex((i + 1) % min(2, len(records))),
        ),
        ("cached_redraw", lambda i: window.redraw()),
        ("cached_population", lambda i: window.show_gate("BV1-A" if i % 2 == 0 else "BL1-A")),
        ("threshold_drag_preview", lambda i: window.selector.update(0.44 + (i % 2) * 0.01)),
    ]:
        if name == "cached_sample_switch" and len(records) < 2:
            continue
        rows = [trial(lambda i=i, action=action: action(i)) for i in range(args.repetitions)]
        trials[name] = {
            "repetitions": len(rows),
            "seconds": {
                key: {
                    "p50": float(np.percentile([r[key] for r in rows], 50)),
                    "p95": float(np.percentile([r[key] for r in rows], 95)),
                    "max": max(r[key] for r in rows),
                }
                for key in rows[0]
            },
            "trials": rows,
        }
    window.canvas.mpl_disconnect(token)
    (args.out / "interactions.json").write_text(json.dumps(trials, indent=2))
    window.discarding = True
    window.close()
    heartbeat.stop()
    (args.out / "timings.json").write_text(json.dumps(times, indent=2))
    print(json.dumps(times, indent=2))


if __name__ == "__main__":
    main()
