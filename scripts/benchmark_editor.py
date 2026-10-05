"""Offscreen Qt interaction benchmark against benchmark_plate's synthetic fixture."""

import argparse
import json
import os
import time
from itertools import pairwise
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore
from PySide6 import QtWidgets as W

from agentflow.samples import read_samples
from agentflow.workbench import ScreenWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
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
    window.grab().save(str(args.out / "editor.png"))
    window.discarding = True
    window.close()
    heartbeat.stop()
    (args.out / "timings.json").write_text(json.dumps(times, indent=2))
    print(json.dumps(times, indent=2))


if __name__ == "__main__":
    main()
