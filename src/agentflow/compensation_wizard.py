"""Optional native control assignment and threshold review; estimation stays headless."""

import json
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter
from PySide6 import QtGui
from PySide6 import QtWidgets as W

from . import flowkit
from .control_review import export_control_review, resolve_config
from .desktop import button, label
from .engine import make_transform
from .workflow import default_transform


class ControlFilenameDelegate(W.QStyledItemDelegate):
    def displayText(self, value, locale):
        return Path(str(value)).name if value else "Choose a control file"


class CompensationWizard(W.QDialog):
    def __init__(self, parent, detectors):
        super().__init__(parent)
        self.setWindowTitle("Compensation · single-stain control review")
        available = self.screen().availableGeometry()
        self.resize(min(1080, available.width() - 40), min(820, available.height() - 60))
        self.spec = None
        self.extra = {}
        self.loading = False
        outer = W.QVBoxLayout(self)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        content = W.QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        layout = W.QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Calculate compensation", "title"))
        layout.addWidget(
            label(
                "Assign one single-stain file per detector. Review negative and positive populations in raw signal units.\n"
                "Each file must contain both negative and positive events; separate unstained files are not supported."
            )
        )
        layout.addWidget(label("1 · Assign single-stain controls", "eyebrow"))
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
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(190)
        self.table.setItemDelegateForColumn(1, ControlFilenameDelegate(self.table))
        self.table.itemSelectionChanged.connect(self.preview)
        self.table.itemChanged.connect(self.changed)
        layout.addWidget(self.table)
        layout.addWidget(label("2 · Choose cleanup and select populations", "eyebrow"))
        cleanup_actions = W.QHBoxLayout()
        cleanup_actions.addWidget(button("Choose cleanup recipe…", self.choose_cleanup))
        self.cleanup_gate = W.QComboBox()
        self.cleanup_gate.setMinimumContentsLength(12)
        self.cleanup_gate.currentTextChanged.connect(self.select_cleanup_gate)
        cleanup_actions.addWidget(self.cleanup_gate, 1)
        cleanup_actions.addWidget(button("Use all events", self.clear_cleanup))
        layout.addLayout(cleanup_actions)
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
        self.canvas.setMinimumHeight(200)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("button_press_event", self.place_threshold)
        self.status = label("Select a control to inspect it. Blank thresholds must be supplied.", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cleanup = label(
            "Cleanup: all acquired events. Choose a saved uncompensated recipe to exclude debris or doublets.",
            "muted",
        )
        self.cleanup.setWordWrap(True)
        layout.addWidget(self.cleanup)
        layout.addWidget(label("3 · Review and apply", "eyebrow"))
        records = getattr(parent, "records", [])
        shared = [r for r in records if not r.get("compensation_path")]
        assigned = [r for r in records if r.get("compensation_path")]
        self.assignment_summary = label(
            f"Applies to {len(shared)} of {len(records)} samples. "
            f"{len(assigned)} keep their individually assigned matrices. Save the analysis to keep this change."
            if records
            else "Applies to the shared recipe. Save the analysis to keep this change.",
            "muted",
        )
        self.assignment_summary.setWordWrap(True)
        layout.addWidget(self.assignment_summary)
        self.assignments = W.QComboBox()
        for record in records:
            mode = "keeps assigned matrix" if record.get("compensation_path") else "uses new matrix"
            self.assignments.addItem(f"{record['sample_id']} · {mode}")
        self.assignments.setVisible(bool(records))
        layout.addWidget(self.assignments)
        bottom = W.QHBoxLayout()
        bottom.addWidget(button("Calculate & export review…", self.calculate))
        self.diagnostics_button = button("Review before / after…", self.show_diagnostics)
        self.diagnostics_button.setEnabled(False)
        bottom.addWidget(self.diagnostics_button)
        self.apply_button = button("Apply draft matrix", self.accept)
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        bottom.addWidget(self.apply_button)
        bottom.addWidget(button("Close", self.reject))
        outer.addLayout(bottom)
        self.loading = True
        for detector in detectors:
            self.add_row(detector)
        self.loading = False
        if self.table.rowCount():
            self.table.selectRow(0)

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
        self.diagnostics_button.setEnabled(False)
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
        self.diagnostics_button.setEnabled(False)
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
                    self.table.item(row, col).setToolTip(str(control[key]))
            self.minimum.setValue(config.get("min_events", 50))
            self.refresh_cleanup()
            self.table.selectRow(0)
        finally:
            self.loading = False
        self.changed()

    def refresh_cleanup(self):
        from .engine import load_recipe

        self.cleanup_gate.blockSignals(True)
        try:
            self.cleanup_gate.clear()
            path = self.extra.get("cleanup_recipe")
            if path:
                recipe = load_recipe(path)
                if recipe["compensation"]["mode"] != "none":
                    raise ValueError("Choose an uncompensated cleanup recipe.")
                self.cleanup_gate.addItems([g["name"] for g in recipe["gates"]])
                self.cleanup_gate.setCurrentText(self.extra.get("cleanup_gate", ""))
                self.cleanup.setText(f"Cleanup recipe: {Path(path).name}")
                self.cleanup.setToolTip(str(path))
            else:
                self.cleanup.setText("Cleanup: all acquired events.")
                self.cleanup.setToolTip("")
        finally:
            self.cleanup_gate.blockSignals(False)

    def choose_cleanup(self):
        from .engine import load_recipe

        path, _ = W.QFileDialog.getOpenFileName(self, "Uncompensated cleanup recipe", "", "Recipe (*.json)")
        if not path:
            return
        try:
            recipe = load_recipe(path)
            if recipe["compensation"]["mode"] != "none" or not recipe["gates"]:
                raise ValueError("Choose an uncompensated recipe with at least one cleanup gate.")
            self.extra.update(
                cleanup_recipe=str(Path(path).resolve()), cleanup_gate=recipe["gates"][-1]["name"]
            )
            self.refresh_cleanup()
            self.changed()
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def select_cleanup_gate(self, name):
        if name:
            self.extra["cleanup_gate"] = name
            self.changed()

    def clear_cleanup(self):
        self.extra.pop("cleanup_recipe", None)
        self.extra.pop("cleanup_gate", None)
        self.refresh_cleanup()
        self.changed()

    def choose_file(self):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText("Select a detector row first.")
            return
        path, _ = W.QFileDialog.getOpenFileName(self, "Single-stain control", "", "FCS (*.fcs *.FCS)")
        if path:
            self.table.item(row, 1).setText(path)
            self.table.item(row, 1).setToolTip(path)

    def configuration(self):
        controls = []
        if not self.table.rowCount():
            raise ValueError("Add at least one detector and its single-stain control.")
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text().strip() for col in range(4)]
            if not values[0] or not values[1] or not Path(values[1]).is_absolute():
                raise ValueError("Each row requires a detector and an absolute FCS path; use Choose FCS.")
            if not values[2] or not values[3]:
                raise ValueError(
                    f"{values[0]}: select both negative and positive thresholds on the histogram."
                )
            if not np.isfinite([float(values[2]), float(values[3])]).all() or float(values[2]) >= float(
                values[3]
            ):
                raise ValueError(
                    f"{values[0]}: negative maximum must be below positive minimum and both must be finite."
                )
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
        self.figure.clear()
        self.ax = None
        self.canvas.draw_idle()
        try:
            detector, path, low, high = [self.table.item(row, c).text().strip() for c in range(4)]
            if not path:
                self.status.setText("Choose the single-stain FCS file for this detector.")
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
            spec = default_transform(sample, detector)
            transform = make_transform(spec)
            if transform is None:
                raise ValueError("Select an acquired fluorescence detector for compensation")
            # Bin in logicle space while retaining raw axis coordinates for clicks and thresholds.
            scaled = transform.apply(data)
            counts, edges = np.histogram(scaled, bins=100)
            raw_edges = transform.inverse(edges)
            self.ax.stairs(counts, raw_edges, color="#6f0835", fill=True, alpha=0.65)
            self.ax.set_xscale("function", functions=(transform.apply, transform.inverse))
            ticks = np.r_[-(10.0 ** np.arange(7, -1, -1)), 0, 10.0 ** np.arange(0, 8)]
            ticks = ticks[(ticks >= raw_edges[0]) & (ticks <= raw_edges[-1])]
            # Keep labels separated in the central linear region, preferring zero.
            chosen = []
            span = edges[-1] - edges[0]
            for tick in sorted(ticks, key=abs):
                position = transform.apply(np.array([tick]))[0]
                if all(abs(position - p) > span * 0.09 for _, p in chosen):
                    chosen.append((tick, position))
            self.ax.xaxis.set_major_locator(FixedLocator(sorted(t for t, _ in chosen)))
            self.ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}"))
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
            self.ax.set(xlabel=f"{detector} · raw signal · logicle display", ylabel="Events per display bin")
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

    def show_diagnostics(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Single-stain controls · before and after compensation")
        dialog.resize(1050, 820)
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(
            label("Descriptive control QC · inspect spillover before applying the draft matrix", "muted")
        )
        choice = W.QComboBox()
        files = sorted((self.review_directory / "diagnostics").glob("*.png"))
        controls = self.spec["estimation"]["controls"]
        choice.addItems([f"{i + 1}. {controls[i]['detector']}" for i in range(len(files))])
        layout.addWidget(choice)
        scroll = W.QScrollArea()
        picture = W.QLabel()
        scroll.setWidget(picture)
        layout.addWidget(scroll, 1)

        def display(index):
            if index >= 0 and files:
                pixmap = QtGui.QPixmap(str(files[index]))
                picture.setPixmap(pixmap)
                picture.resize(pixmap.size())

        choice.currentIndexChanged.connect(display)
        display(0)
        if not files:
            layout.addWidget(label("No secondary detector pairs in this matrix."))
        layout.addWidget(button("Done", dialog.accept))
        dialog.exec()

    def calculate(self):
        try:
            config = self.configuration()
            path, _ = W.QFileDialog.getSaveFileName(self, "New review folder (will contain matrix and plots)")
            if not path:
                return
            self.spec = export_control_review(config, path)
            self.review_directory = Path(path)
            self.diagnostics_button.setEnabled(True)
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
            self.diagnostics_button.setEnabled(False)
            self.spec = None
            self.apply_button.setEnabled(False)
            self.status.setText(f"Not calculated: {error}")
