"""Optional native control assignment and threshold review; estimation stays headless."""

import json
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtWidgets as W

from . import flowkit
from .control_review import export_control_review, resolve_config
from .desktop import button, label


class CompensationWizard(W.QDialog):
    def __init__(self, parent, detectors):
        super().__init__(parent)
        self.setWindowTitle("Compensation · single-stain control review")
        self.resize(1100, 880)
        self.spec = None
        self.extra = {}
        self.loading = False
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Calculate compensation", "title"))
        layout.addWidget(
            label(
                "Assign one single-stain file per detector. Review negative and positive populations in raw signal units.\n"
                "Use matching particle/background types and acquisition settings. Estimates remain draft."
            )
        )
        actions = W.QHBoxLayout()
        actions.addWidget(button("Load control config…", self.load_config))
        actions.addWidget(button("Add detector", self.add_row))
        actions.addWidget(button("Remove selected detector", self.remove_row))
        actions.addWidget(button("Choose FCS for selected row…", self.choose_file))
        layout.addLayout(actions)
        self.table = W.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Source detector (PnN)", "Single-stain FCS", "Negative ≤", "Positive ≥"]
        )
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.setMaximumHeight(190)
        self.table.itemSelectionChanged.connect(self.preview)
        self.table.itemChanged.connect(self.changed)
        layout.addWidget(self.table)
        options = W.QHBoxLayout()
        options.addWidget(label("Minimum events per population"))
        self.minimum = W.QSpinBox()
        self.minimum.setRange(2, 1000000)
        self.minimum.setValue(50)
        self.minimum.valueChanged.connect(self.changed)
        options.addWidget(self.minimum)
        options.addWidget(label("Click histogram to place"))
        self.threshold = W.QComboBox()
        self.threshold.addItems(["Negative maximum", "Positive minimum"])
        options.addWidget(self.threshold)
        options.addStretch()
        layout.addLayout(options)
        self.figure = Figure(figsize=(9, 3), facecolor="white", layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(260)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("button_press_event", self.place_threshold)
        self.status = label("Select a control to inspect it. Blank thresholds must be supplied.", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cleanup = label(
            "Cleanup: all acquired events. Load a config to specify an uncompensated cleanup recipe.", "muted"
        )
        layout.addWidget(self.cleanup)
        bottom = W.QHBoxLayout()
        bottom.addWidget(button("Calculate & export review…", self.calculate))
        self.apply_button = button("Apply draft matrix", self.accept)
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        bottom.addWidget(self.apply_button)
        bottom.addWidget(button("Close", self.reject))
        layout.addLayout(bottom)
        self.loading = True
        for detector in detectors:
            self.add_row(detector)
        self.loading = False

    def add_row(self, detector=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate([detector if isinstance(detector, str) else "", "", "", ""]):
            self.table.setItem(row, col, W.QTableWidgetItem(str(value)))

    def remove_row(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.changed()

    def changed(self, *_):
        if self.loading:
            return
        self.spec = None
        self.apply_button.setEnabled(False)
        self.preview()

    def load_config(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Control configuration", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.set_config(resolve_config(json.loads(Path(path).read_text()), Path(path).parent))
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def set_config(self, config):
        self.spec = None
        self.apply_button.setEnabled(False)
        self.loading = True
        try:
            self.extra = {k: v for k, v in config.items() if k not in {"controls", "detectors", "min_events"}}
            self.table.setRowCount(0)
            for control in config["controls"]:
                self.add_row(control["detector"])
                row = self.table.rowCount() - 1
                for col, key in enumerate(["fcs_path", "negative_max", "positive_min"], 1):
                    self.table.item(row, col).setText(str(control[key]))
            self.minimum.setValue(config.get("min_events", 50))
            self.cleanup.setText(
                "Cleanup: "
                + str(config.get("cleanup_recipe", "all acquired events"))
                + " · "
                + str(config.get("cleanup_gate", "root"))
            )
            self.table.selectRow(0)
        finally:
            self.loading = False
        self.changed()

    def choose_file(self):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText("Select a detector row first.")
            return
        path, _ = W.QFileDialog.getOpenFileName(self, "Single-stain control", "", "FCS (*.fcs *.FCS)")
        if path:
            self.table.item(row, 1).setText(path)

    def configuration(self):
        controls = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text().strip() for col in range(4)]
            if not values[0] or not values[1] or not Path(values[1]).is_absolute():
                raise ValueError("Each row requires a detector and an absolute FCS path; use Choose FCS.")
            controls.append(
                {
                    "detector": values[0],
                    "fcs_path": values[1],
                    "negative_max": float(values[2]),
                    "positive_min": float(values[3]),
                }
            )
        return dict(
            self.extra,
            detectors=[c["detector"] for c in controls],
            controls=controls,
            min_events=self.minimum.value(),
        )

    def preview(self):
        if self.loading or self.table.currentRow() < 0:
            return
        row = self.table.currentRow()
        try:
            detector, path, low, high = [self.table.item(row, c).text().strip() for c in range(4)]
            if not path:
                return
            sample = flowkit.Sample(path)
            data = sample.get_channel_events(detector, source="raw")
            if self.extra.get("cleanup_recipe"):
                from .engine import evaluate, load_recipe, prepare

                recipe = load_recipe(self.extra["cleanup_recipe"])
                if recipe["compensation"]["mode"] != "none":
                    raise ValueError("Cleanup recipe must be uncompensated")
                data = data[evaluate(prepare(sample, recipe), recipe)[self.extra["cleanup_gate"]]]
            self.figure.clear()
            self.ax = self.figure.add_subplot(111)
            # Equal bins in asinh space retain visibility around zero, including negative events.
            scaled = np.arcsinh(data / 150)
            counts, edges = np.histogram(scaled, bins=100)
            self.ax.stairs(counts, 150 * np.sinh(edges), color="#6f0835", fill=True, alpha=0.65)
            self.ax.set_xscale("asinh", linear_width=150)
            counts_text = []
            for value, color, title, below in [
                (low, "#3d6b60", "Negative", True),
                (high, "#e2655e", "Positive", False),
            ]:
                if value:
                    value = float(value)
                    self.ax.axvline(value, color=color, linewidth=2, label=title)
                    count = int(np.count_nonzero(data <= value if below else data >= value))
                    counts_text.append(f"{title}: {count:,}")
            self.ax.set(xlabel=f"{detector} · raw signal · asinh display", ylabel="Events per display bin")
            if counts_text:
                self.ax.legend(frameon=False)
            self.canvas.draw_idle()
            self.status.setText(
                " · ".join(counts_text) + f" · {len(data):,} eligible events. Click to adjust thresholds."
            )
        except (ValueError, OSError, KeyError, IndexError, TypeError) as error:
            self.status.setText(f"Preview unavailable: {error}")

    def place_threshold(self, event):
        if self.toolbar.mode or event.button != 1 or event.inaxes != getattr(self, "ax", None):
            return
        if event.xdata is not None:
            self.table.item(self.table.currentRow(), 2 + self.threshold.currentIndex()).setText(
                f"{event.xdata:.10g}"
            )

    def calculate(self):
        try:
            config = self.configuration()
            path, _ = W.QFileDialog.getSaveFileName(self, "New review folder (will contain matrix and plots)")
            if not path:
                return
            self.spec = export_control_review(config, path)
            self.apply_button.setEnabled(True)
            self.status.setText(
                f"Draft matrix exported to {path}. Inspect matrix.png and diagnostics before use. "
                "Apply affects the shared recipe; sample-sheet matrix assignments take precedence."
            )
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            values = np.asarray(self.spec["values"])
            ax.imshow(values, cmap="Purples")
            labels = self.spec["detectors"]
            ax.set_xticks(range(len(labels)), labels)
            ax.set_yticks(range(len(labels)), labels)
            for i in range(len(labels)):
                for j in range(len(labels)):
                    ax.text(
                        j,
                        i,
                        f"{values[i, j]:.4f}",
                        ha="center",
                        va="center",
                        color="white" if values[i, j] > 0.5 else "#141414",
                    )
            ax.set(xlabel="Receiving detector", ylabel="Source detector", title="DRAFT · spillover fractions")
            self.canvas.draw_idle()
            self.ax = None
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.spec = None
            self.apply_button.setEnabled(False)
            self.status.setText(f"Not calculated: {error}")
