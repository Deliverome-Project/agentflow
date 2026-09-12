"""Multi-sample desktop review, population gallery and group overlays."""

import copy
import re
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .desktop import TITLES, GateWindow, button, label
from .engine import make_transform
from .plot_views import apply_axes, display_spec, draw_boundary, draw_events, scatter_limits
from .samples import SampleSession, sample_recipe


class ScreenWindow(GateWindow):
    def __init__(self, records, recipe, name, path):
        self.session = SampleSession(records)
        self.records = records
        self.record = records[0]
        self.pinned = set(recipe.get("display", {}).get("pinned_samples", []))
        self.ready = False
        self.gallery_pending = False
        prepared, _ = self.session.get(self.record, recipe)
        super().__init__(prepared, recipe, name, path)
        self.setWindowTitle("Agentflow · Multi-sample screen review")
        self.setMinimumSize(980, 620)
        available = self.screen().availableGeometry()
        self.resize(min(1440, max(980, available.width() - 40)), min(900, max(620, available.height() - 60)))
        top = W.QHBoxLayout()
        analysis_menu = W.QMenu(self)
        analysis_menu.addAction("Open analysis…", self.open_analysis)
        analysis_menu.addAction("Save and keep editing", lambda: self.save_changes(close=False))
        analysis_menu.addAction("Save and run all samples…", self.run_analysis)
        analysis_menu.addSeparator()
        analysis_menu.addAction("Delete selected population…", self.delete_population)
        self.gates.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.gates.customContextMenuRequested.connect(self.population_menu)
        analysis_menu.addAction("Detectors…", self.detectors_dialog)
        analysis_menu.addAction("Calculate compensation…", self.compensation_wizard)
        analysis_menu.addAction("Pinned controls…", self.pin_dialog)
        analysis_menu.addAction("Reset selected sample exception", self.reset_exception)
        analysis_button = W.QPushButton("Analysis")
        analysis_button.setMenu(analysis_menu)
        top.addWidget(analysis_button)
        top.addWidget(label("SAMPLE"))
        self.sample_choice = W.QComboBox()
        self.sample_choice.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.sample_choice.setMinimumContentsLength(12)
        for r in records:
            self.sample_choice.addItem(f"{r['sample_id']} · {r['group']}")
        self.sample_choice.currentIndexChanged.connect(self.switch_sample)
        top.addWidget(self.sample_choice, 1)
        self.previous_sample = button("‹", lambda: self.step_sample(-1))
        self.previous_sample.setToolTip("Previous sample in the comparison group")
        self.next_sample = button("›", lambda: self.step_sample(1))
        self.next_sample.setToolTip("Next sample in the comparison group")
        top.addWidget(self.previous_sample)
        top.addWidget(self.next_sample)
        top.addWidget(label("COMPARE"))
        self.group_choice = W.QComboBox()
        self.group_choice.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_choice.setMinimumContentsLength(10)
        self.group_choice.addItem("All groups")
        self.group_choice.addItems(sorted({r["group"] for r in records}))
        self.group_choice.currentIndexChanged.connect(self.redraw)
        top.addWidget(self.group_choice)
        self.overlay = W.QCheckBox("Overlay samples")
        self.overlay.toggled.connect(self.redraw)
        top.addWidget(self.overlay)
        top.addWidget(button("New subpopulation…", self.new_population))
        experiment_bar = W.QWidget(objectName="experiment_bar")
        experiment_bar.setLayout(top)
        top.setContentsMargins(10, 8, 10, 8)
        self.root_layout.insertWidget(1, experiment_bar)
        self.scope = label(
            f"Shared recipe · edits apply to all {len(records)} samples in this sheet. Colors identify groups.",
            "muted",
        )
        self.root_layout.insertWidget(2, self.scope)
        scopes = W.QHBoxLayout()
        scopes.addWidget(label("Edit gates for"))
        self.edit_scope = W.QComboBox()
        self.edit_scope.addItems(["All samples", "This sample only"])
        self.edit_scope.currentIndexChanged.connect(self.change_scope)
        scopes.addWidget(self.edit_scope)
        scopes.addWidget(button("Next draft →", self.next_draft))
        self.focus_plot = W.QCheckBox("Focus plot")
        self.focus_plot.setToolTip("Hide comparison thumbnails to enlarge the editable plot")
        self.focus_plot.toggled.connect(self.toggle_focus)
        scopes.addWidget(self.focus_plot)
        scopes.addStretch()
        scopes.addWidget(button("Save & run experiment…", self.run_analysis, True))
        self.root_layout.insertLayout(3, scopes)
        display_panel = W.QWidget()
        display_layout = W.QVBoxLayout(display_panel)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_panel.hide()
        self.display_panel = display_panel
        display_toggle = W.QCheckBox("Plot settings")
        display_toggle.toggled.connect(display_panel.setVisible)
        plot_actions = W.QHBoxLayout()
        plot_actions.addWidget(display_toggle)
        plot_actions.addStretch()
        self.polygon_button = button("Polygon…", lambda: self.new_population("polygon"))
        plot_actions.addWidget(button("Scatterplot…", self.scatter_dialog))
        plot_actions.addWidget(self.polygon_button)
        ratio_button = button("GFP / Cy5…", self.ratio_dialog)
        ratio_button.setToolTip("Plot reporter signals and select a numerator / denominator ratio")
        plot_actions.addWidget(ratio_button)
        self.main_layout.insertLayout(2, plot_actions)
        settings = W.QHBoxLayout()
        self.plot_type = W.QComboBox()
        self.plot_type.addItems(["Scatter", "Density", "Contour"])
        self.plot_type.currentIndexChanged.connect(self.redraw)
        settings.addWidget(self.plot_type)
        self.histogram_label = label("Histogram")
        settings.addWidget(self.histogram_label)
        self.histogram_label.hide()
        self.point_size_label = label("Point size")
        settings.addWidget(self.point_size_label)
        self.point_size = W.QSpinBox()
        self.point_size.setRange(1, 35)
        self.point_size.setValue(8)
        self.point_size.valueChanged.connect(self.redraw)
        settings.addWidget(self.point_size)
        settings.addWidget(label("Opacity"))
        self.opacity = W.QSpinBox()
        self.opacity.setRange(10, 100)
        self.opacity.setValue(65)
        self.opacity.setSuffix("%")
        self.opacity.valueChanged.connect(self.redraw)
        settings.addWidget(self.opacity)
        self.normalization = W.QComboBox()
        self.normalization.addItems(["Event counts", "Unit area", "% of peak"])
        self.normalization.currentIndexChanged.connect(self.redraw)
        settings.addWidget(self.normalization)
        display_layout.addLayout(settings)
        axes = W.QHBoxLayout()
        axes.addWidget(label("Display axes"))
        self.x_scale, self.y_scale = W.QComboBox(), W.QComboBox()
        for title, combo in [("X", self.x_scale), ("Y", self.y_scale)]:
            axes.addWidget(label(title))
            combo.addItems(["Recipe scale", "Linear", "Asinh", "Logicle"])
            combo.currentIndexChanged.connect(self.redraw)
            axes.addWidget(combo)
        axes.addWidget(button("Use gating axes", self.gating_axes))
        self.full_scatter = W.QCheckBox("Full scatter range")
        self.full_scatter.setToolTip(
            "Unchecked: central 99% view. Off-screen events still count; gates are unchanged."
        )
        self.full_scatter.toggled.connect(self.redraw)
        axes.addWidget(self.full_scatter)
        self.parent_button = button("↑ Parent", self.select_parent)
        self.parent_button.setToolTip("Select the upstream population")
        self.main_layout.takeAt(0)
        heading = W.QHBoxLayout()
        heading.addWidget(self.title, 1)
        heading.addWidget(self.parent_button)
        self.main_layout.insertLayout(0, heading)
        axes.addStretch()
        display_layout.addLayout(axes)
        self.main_layout.insertWidget(3, display_panel)
        gallery_panel = W.QWidget(objectName="gallery")
        self.gallery_panel = gallery_panel
        gallery_panel.setMinimumWidth(240)
        gallery_layout = W.QVBoxLayout(gallery_panel)
        gallery_layout.setContentsMargins(10, 12, 10, 8)
        gallery_layout.addWidget(label("POPULATION OVERVIEW", "eyebrow"))
        self.gallery_mode = W.QComboBox()
        self.gallery_mode.addItems(
            ["All populations", "Compare samples", "Plate map", "Ancestry", "Sample MFI"]
        )
        self.gallery_mode.currentIndexChanged.connect(self.request_gallery)
        self.gallery_mode.setCurrentIndex(4)
        gallery_layout.addWidget(self.gallery_mode)
        self.summary_settings = W.QCheckBox("Summary settings")
        self.summary_settings.toggled.connect(self.request_gallery)
        gallery_layout.addWidget(self.summary_settings)
        self.summary_controls = W.QWidget()
        summary_layout = W.QFormLayout(self.summary_controls)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_population = W.QComboBox()
        names = ["root"] + [g["name"] for g in recipe["gates"]]
        self.summary_population.addItems(names)
        self.summary_population.setCurrentText("live" if "live" in names else "root")
        self.summary_follow = W.QCheckBox("Follow selected population")
        self.summary_follow.setChecked(True)
        self.summary_follow.toggled.connect(self.request_gallery)
        summary_layout.addRow(self.summary_follow)
        self.summary_detector = W.QComboBox()
        sample = self.state.prepared.sample
        detectors = [sample.pnn_labels[i] for i in sample.fluoro_indices]
        detectors.sort(key=lambda c: (not c.endswith("-A"), c))
        for c in detectors:
            marker = sample.pns_labels[sample.pnn_labels.index(c)]
            self.summary_detector.addItem(f"{marker or c} · {c}" if marker else c, c)
        preferred = recipe.get("channel_roles", {}).get("gfp", {}).get("detector")
        if not preferred and "FL5-A" in detectors:
            preferred = "FL5-A"
        if preferred in detectors:
            self.summary_detector.setCurrentIndex(detectors.index(preferred))
        self.summary_statistic = W.QComboBox()
        self.summary_statistic.addItems(["MFI (arithmetic mean)", "Median fluorescence"])
        for title, control in [
            ("Population", self.summary_population),
            ("Detector", self.summary_detector),
            ("Statistic", self.summary_statistic),
        ]:
            summary_layout.addRow(title, control)
            control.currentIndexChanged.connect(self.request_gallery)
        summary_layout.addRow(button("Export summary CSV…", self.export_sample_summary))
        gallery_layout.addWidget(self.summary_controls)
        self.plate_metric = W.QComboBox()
        self.plate_metric.addItems(["% of parent", "Event count", "Median signal (first detector)"])
        self.plate_metric.currentIndexChanged.connect(self.request_gallery)
        gallery_layout.addWidget(self.plate_metric)
        self.plate_metric.hide()
        paging = W.QHBoxLayout()
        paging.addWidget(button("‹", lambda: self.gallery_page.setValue(self.gallery_page.value() - 1)))
        self.gallery_page = W.QSpinBox()
        self.gallery_page.setMinimum(1)
        self.gallery_page.valueChanged.connect(self.request_gallery)
        self.gallery_page.hide()
        paging.addWidget(self.gallery_page)
        paging.addWidget(button("›", lambda: self.gallery_page.setValue(self.gallery_page.value() + 1)))
        self.gallery_range = label("", "muted")
        self.gallery_range.setWordWrap(True)
        paging.insertWidget(0, self.gallery_range, 1)
        paging.addStretch()
        gallery_layout.addLayout(paging)
        self.gallery_mode.setToolTip(
            "Click a plot to select its population or sample. Use arrows for more plots."
        )
        self.gallery_figure = Figure(figsize=(5, 8), facecolor="white")
        self.gallery_canvas = FigureCanvasQTAgg(self.gallery_figure)
        self.gallery_canvas.installEventFilter(self)
        self.gallery_canvas.setMinimumHeight(120)
        self.gallery_canvas.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Ignored)
        gallery_layout.addWidget(self.gallery_canvas, 1)
        self.gallery_axes = {}
        self.gallery_canvas.mpl_connect("button_press_event", self.select_gallery)
        self.body_layout.removeWidget(self.main_scroll)
        self.plot_splitter = W.QSplitter(QtCore.Qt.Horizontal)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.addWidget(self.main_scroll)
        self.plot_splitter.addWidget(gallery_panel)
        self.plot_splitter.setStretchFactor(0, 3)
        self.plot_splitter.setStretchFactor(1, 2)
        self.body_layout.addWidget(self.plot_splitter, 1)
        self.canvas.mpl_connect("scroll_event", self.scroll_zoom)
        self.canvas.mpl_connect("pick_event", self.pick_population)
        self.picked = {}
        display = recipe.get("display", {})
        for key, combo in [
            ("plot_type", self.plot_type),
            ("normalization", self.normalization),
            ("x_scale", self.x_scale),
            ("y_scale", self.y_scale),
        ]:
            if display.get(key) in [combo.itemText(i) for i in range(combo.count())]:
                combo.setCurrentText(display[key])
        self.point_size.setValue(display.get("point_size", 8))
        self.opacity.setValue(display.get("opacity", 65))
        self.summary_population.setCurrentText(
            display.get("summary_population", self.summary_population.currentText())
        )
        detector_index = self.summary_detector.findData(display.get("summary_detector"))
        if detector_index >= 0:
            self.summary_detector.setCurrentIndex(detector_index)
        self.summary_statistic.setCurrentText(display.get("summary_statistic", "MFI (arithmetic mean)"))
        self.summary_follow.setChecked(display.get("summary_follow", True))
        self.full_scatter.setChecked(display.get("full_scatter", False))
        self.ready = True
        self.gallery_mode.setCurrentText(display.get("gallery_mode", "Sample MFI"))
        self.focus_plot.setChecked(display.get("focus_plot", False))
        self.show_gate(self.active_name)

    def open_analysis(self):
        from .engine import load_recipe
        from .launcher import Launcher

        dialog = Launcher()
        if dialog.exec() == W.QDialog.Accepted:
            path, records = dialog.selection
            window = ScreenWindow(records, load_recipe(path), None, path)
            self.open_windows = getattr(self, "open_windows", []) + [window]
            window.show()

    def run_analysis(self):
        parent = W.QFileDialog.getExistingDirectory(
            self, "Choose results location · a new run folder will be created"
        )
        if not parent or not self.save_changes(close=False):
            return
        index = 1
        while (Path(parent) / f"run-{index:03d}").exists():
            index += 1
        self.start_analysis(Path(parent) / f"run-{index:03d}")

    def start_analysis(self, output):
        from .desktop_jobs import AnalysisJob

        self.analysis_job = AnalysisJob(copy.deepcopy(self.records), self.state.path, output, self)
        self.analysis_progress = W.QProgressDialog("Analyzing all samples…", "", 0, 0, self)
        self.analysis_progress.setCancelButton(None)
        self.analysis_progress.setWindowModality(QtCore.Qt.WindowModal)
        self.analysis_progress.setWindowTitle("Running saved analysis")
        self.centralWidget().setEnabled(False)
        self.analysis_error = None
        self.analysis_report = None
        self.analysis_job.completed.connect(lambda path: setattr(self, "analysis_report", path))
        self.analysis_job.failed.connect(lambda message: setattr(self, "analysis_error", message))
        self.analysis_job.finished.connect(self.finish_analysis)
        self.analysis_progress.show()
        self.analysis_job.start()

    def finish_analysis(self):
        self.analysis_progress.close()
        self.centralWidget().setEnabled(True)
        if self.analysis_error:
            self.message.setText(f"Analysis failed: {self.analysis_error}")
        else:
            self.message.setText(f"Analysis complete: {self.analysis_report}")
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.analysis_report))

    def closeEvent(self, event):
        if getattr(self, "analysis_job", None) is not None and self.analysis_job.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "ready", False):
            compact = self.height() < 800
            self.stack.setMinimumHeight(180 if compact else 280)
            self.canvas.setMinimumHeight(90 if compact else 180)
            self.main_layout.setSpacing(4 if compact else 6)
            self.note.setVisible(not compact)
            self.scope.setVisible(not compact)
            self.request_gallery()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "gallery_canvas", None) and event.type() == QtCore.QEvent.Resize:
            self.request_gallery()
        return super().eventFilter(watched, event)

    def toggle_focus(self, checked):
        if not self.ready:
            return
        self.gallery_panel.setVisible(not checked)
        if not checked:
            self.request_gallery()
        self.canvas.draw_idle()

    def next_draft(self):
        start = self.names.index(self.active_name)
        candidates = self.names[start + 1 :] + self.names[: start + 1]
        for name in candidates:
            gate = self.state.gate(name)
            if gate is None or not gate.get("reviewed"):
                self.gates.setCurrentRow(self.names.index(name))
                return
        self.message.setText("All populations in this sample are reviewed.")

    def step_sample(self, step):
        records = self.selected_records()
        if not records:
            return
        index = records.index(self.record) if self.record in records else (-1 if step > 0 else len(records))
        target = index + step
        if 0 <= target < len(records):
            self.sample_choice.setCurrentIndex(self.records.index(records[target]))

    def select_parent(self):
        gate = self.state.gate(self.active_name)
        if gate and gate["parent"] in self.names:
            self.gates.setCurrentRow(self.names.index(gate["parent"]))

    def ancestry(self):
        gates = {g["name"]: g for g in self.state.active_recipe["gates"]}
        lineage = []
        name = self.active_name
        while name in gates:
            lineage.append(gates[name])
            name = gates[name]["parent"]
        return lineage[::-1]

    def change_scope(self, index):
        if not self.ready:
            return
        try:
            self.flush_bounds()
        except ValueError as error:
            self.edit_scope.blockSignals(True)
            self.edit_scope.setCurrentIndex(int(self.state.sample_scope))
            self.edit_scope.blockSignals(False)
            self.message.setText(str(error))
            return
        self.state.sample_scope = bool(index)
        self.show_gate(self.active_name)

    def reset_exception(self):
        try:
            self.flush_bounds()
            self.state.reset_override(self.active_name)
            self.show_gate(self.active_name)
        except (ValueError, OSError, TypeError) as error:
            self.message.setText(str(error))

    def pin_dialog(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Keep reference samples visible")
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(label("Pinned samples stay overlaid across sample and group changes."))
        choices = W.QListWidget()
        for record in self.records:
            item = W.QListWidgetItem(f"{record['sample_id']} · {record['group']}", choices)
            item.setData(QtCore.Qt.UserRole, record["sample_id"])
            item.setCheckState(
                QtCore.Qt.Checked if record["sample_id"] in self.pinned else QtCore.Qt.Unchecked
            )
        layout.addWidget(choices)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == W.QDialog.Accepted:
            self.pinned = {
                choices.item(i).data(QtCore.Qt.UserRole)
                for i in range(choices.count())
                if choices.item(i).checkState() == QtCore.Qt.Checked
            }
            candidate = copy.deepcopy(self.state.recipe)
            candidate.setdefault("display", {})["pinned_samples"] = sorted(self.pinned)
            self.state.apply(candidate)
            self.redraw()

    def plot_records(self):
        selected = self.selected_records() if self.overlay.isChecked() else [self.record]
        ids = {r["sample_id"] for r in selected} | self.pinned | {self.record["sample_id"]}
        return [r for r in self.records if r["sample_id"] in ids]

    def selected_records(self):
        group = self.group_choice.currentText()
        return [r for r in self.records if group == "All groups" or r["group"] == group]

    def show_gate(self, name):
        if self.ready:
            self.state.sample_id = self.record["sample_id"]
            prepared, _ = self.session.get(self.record, self.state.recipe)
            self.state.prepared = prepared
            self.sample_label.setText(self.record["sample_id"] + "\n" + self.record["group"])
            self.event_label.setText(f"{prepared.sample.event_count:,} acquired events")
            records = self.selected_records()
            index = records.index(self.record) if self.record in records else -1
            self.previous_sample.setEnabled(bool(records) and index != 0)
            self.next_sample.setEnabled(bool(records) and index != len(records) - 1)
            gate = self.state.gate(name)
            self.parent_button.setEnabled(bool(gate and gate["parent"] != "root"))
        super().show_gate(name)
        gate = self.state.gate(name)
        if self.ready and gate and gate["kind"] == "range":
            transform = make_transform(self.state.recipe["transforms"][gate["channels"][0]])
            for field, value in zip([self.lower, self.upper], gate["bounds"]):
                raw = (
                    None
                    if value is None
                    else value
                    if transform is None
                    else transform.inverse(np.array([value]))[0]
                )
                field.setText("" if raw is None else f"{raw:.8g}")
            self.help.setText(
                self.help.text().replace(
                    "Units are transformed.", "Threshold fields use signal units, matching the tick labels."
                )
            )

    def bound_value(self, field, index):
        if not self.ready:
            return super().bound_value(field, index)
        gate = self.state.gate(self.active_name)
        transform = make_transform(self.state.recipe["transforms"][gate["channels"][0]])
        for original in (gate["bounds"][index], gate["bounds"][1 - index]):
            if original is not None:
                raw = original if transform is None else transform.inverse(np.array([original]))[0]
                if field.text() == f"{raw:.8g}":
                    return original
        value = float(field.text())
        return value if transform is None else float(transform.apply(np.array([value]))[0])

    def change_row(self, row):
        try:
            super().change_row(row)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.message.setText(f"Population unavailable: {error}")

    def redraw(self, *_):
        if self.ready:
            try:
                self.flush_bounds()
                self.show_gate(self.active_name)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.message.setText(str(error))

    def switch_sample(self, index):
        if not self.ready:
            return
        previous = self.records.index(self.record)
        try:
            self.flush_bounds()
            record = self.records[index]
            self.session.get(record, self.state.recipe)
            self.record = record
            self.show_gate(self.active_name)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.sample_choice.blockSignals(True)
            self.sample_choice.setCurrentIndex(previous)
            self.sample_choice.blockSignals(False)
            self.message.setText(f"Sample not loaded: {error}")

    def draw_active(self, gate, parent):
        if not self.ready:
            return super().draw_active(gate, parent)
        records = self.plot_records()
        datasets = []
        for r in records:
            prepared, masks = self.session.get(r, self.state.recipe)
            datasets.append(
                (
                    r,
                    prepared.transformed.loc[
                        masks[gate["name"] if gate["kind"] == "boolean" else gate["parent"]], gate["channels"]
                    ].to_numpy(),
                )
            )
        bins = None
        if len(gate["channels"]) == 1:
            arrays = [d[:, 0] for _, d in datasets if len(d)]
            if arrays:
                lo, hi = min(d.min() for d in arrays), max(d.max() for d in arrays)
                bins = np.linspace(lo if lo != hi else lo - 1, hi if lo != hi else hi + 1, 101)
        kind = self.plot_type.currentText().lower()
        # Group identity cannot be encoded by a pooled density color ramp.
        if len(records) > 1 and kind == "density":
            kind = "contour"
        seen_groups = set()
        for r, data in datasets:
            group_label = r["group"] if r["group"] not in seen_groups else "_nolegend_"
            seen_groups.add(r["group"])
            draw_events(
                self.ax,
                data,
                gate["channels"],
                kind,
                r["color"],
                (f"Pinned · {r['sample_id']}" if r["sample_id"] in self.pinned else group_label)
                if len(records) > 1
                else None,
                self.point_size.value(),
                self.opacity.value() / 100,
                ["count", "area", "peak"][self.normalization.currentIndex()],
                bins,
                limits=scatter_limits(data, gate["channels"], self.full_scatter.isChecked()),
            )
        if len(records) > 1:
            self.ax.legend(fontsize=8, loc="upper right", frameon=False)

    def finish_plot(self, gate):
        if not self.ready:
            return
        modes = [
            ["recipe", "linear", "asinh", "logicle"][c.currentIndex()] for c in [self.x_scale, self.y_scale]
        ]
        self.plot_type.setVisible(len(gate["channels"]) == 2)
        self.histogram_label.setVisible(len(gate["channels"]) == 1)
        self.normalization.setEnabled(len(gate["channels"]) == 1)
        show_points = len(gate["channels"]) == 2 and self.plot_type.currentText() == "Scatter"
        self.point_size.setVisible(show_points)
        self.point_size_label.setVisible(show_points)
        if len(gate["channels"]) == 2:
            arrays = []
            for record in self.plot_records():
                prepared, masks = self.session.get(record, self.state.recipe)
                arrays.append(prepared.transformed.loc[masks[gate["parent"]], gate["channels"]].to_numpy())
            limits = scatter_limits(
                np.concatenate(arrays) if arrays else [], gate["channels"], self.full_scatter.isChecked()
            )
            if limits is not None:
                self.ax.set_xlim(limits[0][0], limits[1][0])
                self.ax.set_ylim(limits[0][1], limits[1][1])
        apply_axes(self.ax, gate["channels"], self.state.recipe, modes)
        self.picked = {}
        for other in self.state.active_recipe["gates"]:
            if (
                other["name"] != gate["name"]
                and other.get("channels") == gate["channels"]
                and other["parent"] == gate["parent"]
            ):
                for artist in draw_boundary(self.ax, other, "#5848a8", 1.6, True, recipe=self.state.recipe):
                    self.picked[artist] = other["name"]
        preview = self.polygon_preview(gate)
        if preview:
            if self.selector:
                self.selector.set_active(False)
                self.selector.set_visible(False)
            draw_boundary(self.ax, gate, recipe=self.state.recipe)
            self.help.setText(
                "Display preview · counts and gates are unchanged. Use gating axes to edit. Asinh cofactor 150; logicle T=262144, W=.5, M=4.5, A=0."
            )
        else:
            self.help.setText(
                self.help.text()
                + " Scroll to zoom. Scatter displays up to 20,000 events per sample; counts use all events."
            )
        self.help.setToolTip(self.help.text())
        self.help.setText(
            {
                "range": "Drag either boundary or enter exact limits below.",
                "polygon": "Drag vertices to reshape · shift-drag to move the gate.",
                "rectangle": "Drag an edge or corner to resize the population.",
                "ratio": "Signal ratio boundaries · choose GFP / Cy5… to adjust.",
                "boolean": "Membership follows the defining populations.",
            }.get(gate["kind"], self.help.text())
        )
        self.review_badge.setToolTip(self.note.text())
        self.edit_button.setEnabled(not preview)
        self.bounds_widget.setEnabled(not preview)
        self.y_scale.setEnabled(len(gate["channels"]) == 2)
        exceptions = self.state.recipe.get("sample_overrides", {}).get(self.record["sample_id"], {})
        scope = self.record["sample_id"] if self.state.sample_scope else f"all {len(self.records)} samples"
        geometry_exception = any(k in exceptions.get(gate["name"], {}) for k in ("bounds", "vertices"))
        if geometry_exception and not self.state.sample_scope:
            if self.selector:
                self.selector.set_active(False)
            self.edit_button.setEnabled(False)
            self.bounds_widget.setEnabled(False)
            self.help.setText(
                "This sample has different gate geometry. Choose This sample only to edit, or reset its exception."
            )
        self.review_button.setEnabled(self.state.sample_scope or gate["name"] not in exceptions)
        badge = " · Sample-specific geometry/review" if gate["name"] in exceptions else ""
        self.scope.setText(
            f"Editing {scope}{badge}. Counts: {self.record['sample_id']}. Pinned references: {len(self.pinned)}."
        )
        self.request_gallery()

    def after_refresh(self):
        if self.ready:
            self.request_gallery()

    def request_gallery(self, *_):
        if self.ready and not self.focus_plot.isChecked() and not self.gallery_pending:
            self.gallery_pending = True
            QtCore.QTimer.singleShot(0, self.update_gallery)

    def update_gallery(self, *_):
        try:
            self._update_gallery()
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.gallery_figure.clear()
            self.gallery_axes.clear()
            ax = self.gallery_figure.add_subplot(111)
            ax.set_axis_off()
            ax.text(0.05, 0.5, str(error), transform=ax.transAxes, wrap=True)
            self.message.setText(f"Comparison unavailable: {error}")
            self.gallery_canvas.draw_idle()

    def _update_gallery(self):
        self.gallery_pending = False
        if not self.ready:
            return
        self.gallery_figure.clear()
        self.gallery_axes.clear()
        summary = self.gallery_mode.currentText() == "Sample MFI"
        self.summary_settings.setVisible(summary)
        self.summary_controls.setVisible(summary and self.summary_settings.isChecked())
        self.plate_metric.setVisible(self.gallery_mode.currentIndex() == 2)
        if summary:
            self.draw_sample_summary()
            return
        if self.gallery_mode.currentIndex() == 2:
            self.draw_plates()
            return
        compare = self.gallery_mode.currentIndex() == 1
        items = self.selected_records() if compare else self.state.active_recipe["gates"]
        if self.gallery_mode.currentText() == "Ancestry":
            items = self.ancestry()
        columns = 1 if self.gallery_canvas.width() < 330 else 2
        available_rows = max(2, self.gallery_canvas.height() // 145)
        capacity = min(12, columns * available_rows)
        if compare:
            columns, capacity = 2, 4
        self.gallery_page.setMaximum(max(1, (len(items) + capacity - 1) // capacity))
        start = (self.gallery_page.value() - 1) * capacity
        all_items = items
        items = items[start : start + capacity]
        n = len(items)
        rows = 2 if compare else max(1, (n + columns - 1) // columns)
        self.gallery_range.setText(f"{start + 1 if n else 0}–{start + n} of {len(all_items)} plots")
        shared_limits = None
        active = self.state.gate(self.active_name)
        if compare and active:
            limits = []
            for r in all_items:
                prepared, masks = self.session.get(r, self.state.recipe)
                values = prepared.transformed.loc[masks[active["parent"]], active["channels"]].to_numpy()
                if len(values):
                    limits.append(
                        scatter_limits(values, active["channels"], self.full_scatter.isChecked())
                        or (values.min(axis=0), values.max(axis=0))
                    )
            if limits:
                shared_limits = (
                    np.min([v[0] for v in limits], axis=0),
                    np.max([v[1] for v in limits], axis=0),
                )
        for i, item in enumerate(items):
            gate, record = (active, item) if compare else (item, self.record)
            if gate is None:
                continue
            gate = next(
                g for g in sample_recipe(self.state.recipe, record)["gates"] if g["name"] == gate["name"]
            )
            ax = self.gallery_figure.add_subplot(rows, columns, i + 1)
            self.gallery_axes[ax] = ("sample", record["sample_id"]) if compare else ("gate", gate["name"])
            try:
                prepared, masks = self.session.get(record, self.state.recipe)
                data = prepared.transformed.loc[
                    masks[gate["name"] if gate["kind"] == "boolean" else gate["parent"]], gate["channels"]
                ].to_numpy()
                individual_limits = scatter_limits(data, gate["channels"], self.full_scatter.isChecked())
                density_limits = shared_limits if shared_limits is not None else individual_limits
                draw_events(ax, data, gate["channels"], "density", record["color"], limits=density_limits)
                draw_boundary(ax, gate, recipe=self.state.recipe)
                count = int(masks[gate["name"]].sum())
                total = int(masks[gate["parent"]].sum())
                title = (
                    f"{record.get('condition') or record.get('label') or record['group']}\n{record['sample_id']}"
                    if compare
                    else TITLES.get(gate["name"], gate["name"])
                )
                ax.set_title(
                    f"{title}\n{count:,} / {total:,}",
                    fontsize=min(7, self.gallery_canvas.width() / 65) if compare else 8,
                    color="#922038" if gate["name"] == self.active_name else "#141414",
                )
                if individual_limits is not None and not shared_limits:
                    ax.set_xlim(individual_limits[0][0], individual_limits[1][0])
                    ax.set_ylim(individual_limits[0][1], individual_limits[1][1])
                if shared_limits:
                    for dim, setter in enumerate([ax.set_xlim, ax.set_ylim][: len(gate["channels"])]):
                        lo, hi = shared_limits[0][dim], shared_limits[1][dim]
                        margin = max((hi - lo) * 0.05, 0.01)
                        setter(lo - margin, hi + margin)
                apply_axes(ax, gate["channels"], self.state.recipe, ["recipe", "recipe"])
                ax.tick_params(labelsize=6, pad=2)
                ax.xaxis.label.set_size(7)
                ax.yaxis.label.set_size(7)
            except (ValueError, OSError, KeyError) as error:
                ax.text(0.05, 0.5, str(error), transform=ax.transAxes, wrap=True, fontsize=8)
        if compare:
            # Fixed cell geometry across pages, including the partly filled final page.
            self.gallery_figure.subplots_adjust(
                left=0.18, right=0.98, bottom=0.17, top=0.83, wspace=0.65, hspace=0.95
            )
        else:
            self.gallery_figure.tight_layout(pad=0.8, h_pad=1.2, w_pad=0.8)
        self.gallery_canvas.draw_idle()

    def sample_summary_table(self):
        from .sample_summary import signal_summary

        return signal_summary(
            self.selected_records(),
            self.session,
            self.state.recipe,
            self.summary_population.currentText(),
            self.summary_detector.currentData(),
            "mean" if self.summary_statistic.currentIndex() == 0 else "median",
        )

    def export_sample_summary(self):
        path, _ = W.QFileDialog.getSaveFileName(
            self, "Export sample summary", "sample-summary.csv", "CSV (*.csv)"
        )
        if path:
            try:
                self.sample_summary_table().to_csv(path, index=False)
                self.message.setText(f"Sample summary saved: {path}")
            except (ValueError, OSError, KeyError) as error:
                self.message.setText(str(error))

    def draw_sample_summary(self):
        names = ["root"] + [g["name"] for g in self.state.recipe["gates"]]
        current = self.summary_population.currentText()
        if names != [self.summary_population.itemText(i) for i in range(self.summary_population.count())]:
            self.summary_population.blockSignals(True)
            self.summary_population.clear()
            self.summary_population.addItems(names)
            self.summary_population.setCurrentText(current if current in names else "root")
            self.summary_population.blockSignals(False)
        self.summary_population.setEnabled(not self.summary_follow.isChecked())
        if self.summary_follow.isChecked() and self.active_name in names:
            self.summary_population.blockSignals(True)
            self.summary_population.setCurrentText(self.active_name)
            self.summary_population.blockSignals(False)
        table = self.sample_summary_table()
        # Stable group ordering retains acquisition/sample order within each group.
        order = list(dict.fromkeys(table["group"]))
        table = table.assign(_group=table["group"].map({g: i for i, g in enumerate(order)})).sort_values(
            "_group", kind="stable"
        )
        capacity = 30
        self.gallery_page.setMaximum(max(1, (len(table) + capacity - 1) // capacity))
        start = (self.gallery_page.value() - 1) * capacity
        shown = table.iloc[start : start + capacity]
        ax = self.gallery_figure.add_subplot(111)
        y = np.arange(len(shown))
        ax.barh(y, shown.value, color=shown.color)
        labels = [
            str(r.get("condition") or r.get("label") or r["sample_id"]) for r in shown.to_dict("records")
        ]
        # One line per sample keeps up to 30 bars visible without pagination.
        label_size = max(5.5, min(8, (self.gallery_canvas.height() - 80) / max(len(shown), 1) * 0.55))
        ax.set_yticks(y, labels, fontsize=label_size)
        ax.invert_yaxis()
        ax.set_xlabel(
            self.summary_statistic.currentText() + "\n" + str(self.summary_detector.currentData()), fontsize=9
        )
        ax.set_title(self.summary_population.currentText(), fontsize=10)
        for i, row in enumerate(shown.itertuples()):
            if not np.isfinite(row.value):
                ax.text(0, i, "No events", va="center", fontsize=8)
        ax.grid(axis="y", visible=False)
        self.gallery_axes[ax] = ("bars", shown.sample_id.tolist())
        self.gallery_range.setText(
            f"{start + 1}–{start + len(shown)} of {len(table)} · {'follows selection' if self.summary_follow.isChecked() else 'fixed population'}"
        )
        self.gallery_range.setToolTip(
            "Values follow the population named above. Editing a child does not change its parent population's MFI."
        )
        self.gallery_figure.tight_layout(pad=1)
        self.gallery_canvas.draw_idle()

    def draw_plates(self):
        gate = self.state.gate(self.active_name)
        records = self.selected_records()
        plates = sorted({r.get("plate", "Unassigned") for r in records})
        self.gallery_page.setMaximum(max(1, len(plates)))
        if gate is None or not plates:
            return
        plate = plates[self.gallery_page.value() - 1]
        ax = self.gallery_figure.add_subplot(111)
        entries, positions = [], {}
        for r in records:
            if r.get("plate", "Unassigned") != plate:
                continue
            match = re.fullmatch(r"([A-Pa-p])(0?[1-9]|1[0-9]|2[0-4])", r.get("well", ""))
            if not match:
                ax.text(
                    0.5,
                    0.5,
                    "No well assignment for this sample. Add plate and well columns (A01–P24) to the sample sheet, or choose Sample MFI to compare labeled conditions.",
                    transform=ax.transAxes,
                    ha="center",
                    wrap=True,
                )
                self.gallery_canvas.draw_idle()
                return
            location = (ord(match[1].upper()) - ord("A"), int(match[2]) - 1)
            if location in positions:
                ax.text(
                    0.5,
                    0.5,
                    "Duplicate well positions in the selected plate.",
                    transform=ax.transAxes,
                    ha="center",
                )
                self.gallery_canvas.draw_idle()
                return
            prepared, masks = self.session.get(r, self.state.recipe)
            count = int(masks[gate["name"]].sum())
            parent = int(masks[gate["parent"]].sum())
            metric = self.plate_metric.currentIndex()
            value = count if metric == 1 else (100 * count / parent if parent else np.nan)
            if metric == 2:
                value = prepared.values.loc[masks[gate["name"]], gate["channels"][0]].median()
            entries.append((location, value))
            positions[location] = r["sample_id"]
        large = any(row > 7 or col > 11 for row, col in positions)
        values = np.full((16, 24) if large else (8, 12), np.nan)
        for location, value in entries:
            values[location] = value
        image = ax.imshow(
            np.ma.masked_invalid(values),
            cmap="magma",
            vmin=0 if self.plate_metric.currentIndex() == 0 else None,
            vmax=100 if self.plate_metric.currentIndex() == 0 else None,
        )
        ax.set_xticks(range(values.shape[1]), range(1, values.shape[1] + 1), fontsize=8)
        ax.set_yticks(range(values.shape[0]), [chr(65 + i) for i in range(values.shape[0])], fontsize=8)
        ax.set_title(plate + "\n" + TITLES.get(gate["name"], gate["name"]), fontsize=12)
        self.gallery_figure.colorbar(
            image, ax=ax, orientation="horizontal", pad=0.12, label=self.plate_metric.currentText()
        )
        self.gallery_axes[ax] = ("plate", positions)
        self.gallery_range.setText(f"Plate {self.gallery_page.value()} of {len(plates)}")
        self.gallery_figure.tight_layout()
        self.gallery_canvas.draw_idle()

    def select_gallery(self, event):
        selected = self.gallery_axes.get(event.inaxes)
        if selected:
            kind, value = selected
            if kind == "bars":
                if event.ydata is None or not 0 <= round(event.ydata) < len(value):
                    return
                value = value[round(event.ydata)]
                kind = "sample"
            if kind == "plate":
                if event.xdata is None or event.ydata is None:
                    return
                value = value.get((round(event.ydata), round(event.xdata)))
                if value is None:
                    return
                kind = "sample"
            if kind == "gate":
                self.gates.setCurrentRow(self.names.index(value))
            else:
                self.sample_choice.setCurrentIndex(
                    next(i for i, r in enumerate(self.records) if r["sample_id"] == value)
                )

    def pick_population(self, event):
        if event.artist in self.picked:
            self.gates.setCurrentRow(self.names.index(self.picked[event.artist]))

    def gating_axes(self):
        for combo in [self.x_scale, self.y_scale]:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.redraw()

    def scroll_zoom(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        factor = 0.8 if event.button == "up" else 1.25
        # Zoom in display coordinates, then invert to canonical coordinates.
        for axis, limits, center, setter in [
            (self.ax.xaxis, self.ax.get_xlim(), event.xdata, self.ax.set_xlim),
            (self.ax.yaxis, self.ax.get_ylim(), event.ydata, self.ax.set_ylim),
        ]:
            transform = axis.get_transform()
            lo, hi = transform.transform(np.array(limits))
            mid = transform.transform(np.array([center]))[0]
            bounds = transform.inverted().transform(mid + (np.array([lo, hi]) - mid) * factor)
            setter(*bounds)
        self.canvas.draw_idle()

    def polygon_preview(self, gate):
        if not gate or gate["kind"] != "polygon":
            return False
        for channel, combo in zip(gate["channels"], [self.x_scale, self.y_scale]):
            mode = ["recipe", "linear", "asinh", "logicle"][combo.currentIndex()]
            if mode != "recipe" and display_spec(mode) != self.state.recipe["transforms"][channel]:
                return True
        return False

    def edit_mode(self):
        super().edit_mode()
        if self.ready and self.selector and self.polygon_preview(self.state.gate(self.active_name)):
            self.selector.set_active(False)

    def save(self):
        self.save_changes(close=True)

    def save_changes(self, close=False):
        try:
            self.flush_bounds()
            candidate = copy.deepcopy(self.state.recipe)
            candidate["display"] = {
                "pinned_samples": sorted(self.pinned),
                "focus_plot": self.focus_plot.isChecked(),
                "gallery_mode": self.gallery_mode.currentText(),
                "summary_population": self.summary_population.currentText(),
                "summary_follow": self.summary_follow.isChecked(),
                "summary_detector": self.summary_detector.currentData(),
                "summary_statistic": self.summary_statistic.currentText(),
                "full_scatter": self.full_scatter.isChecked(),
                "plot_type": self.plot_type.currentText(),
                "point_size": self.point_size.value(),
                "opacity": self.opacity.value(),
                "normalization": self.normalization.currentText(),
                "x_scale": self.x_scale.currentText(),
                "y_scale": self.y_scale.currentText(),
            }
            self.state.apply(candidate)
            self.state.save()
            self.message.setText("Saved. You can continue editing or run this analysis.")
            if close:
                self.close()
            return True
        except (ValueError, OSError, TypeError) as error:
            self.message.setText(f"Not saved: {error}")
            return False

    def detectors_dialog(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Acquired detectors and assigned roles")
        dialog.resize(720, 450)
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(label(self.record["sample_id"] + " · Acquired detector names", "title"))
        sample = self.state.prepared.sample
        table = W.QTableWidget(len(sample.pnn_labels), 3)
        table.setHorizontalHeaderLabels(["Detector (PnN)", "Marker (PnS)", "Assigned role"])
        roles = self.state.recipe.get("channel_roles", {})
        for i, detector in enumerate(sample.pnn_labels):
            assigned = ", ".join(
                role + (" (unconfirmed)" if not spec.get("confirmed") else "")
                for role, spec in roles.items()
                if spec["detector"] == detector
            )
            marker = sample.pns_labels[i] if sample.pns_labels else ""
            for j, value in enumerate([detector, marker, assigned]):
                table.setItem(i, j, W.QTableWidgetItem(str(value)))
        table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        layout.addWidget(button("Done", dialog.accept))
        dialog.exec()

    def travel(self, redo):
        try:
            self.state.travel(redo)
            self.pinned = set(self.state.recipe.get("display", {}).get("pinned_samples", []))
            self.rebuild(self.active_name)
        except (ValueError, OSError, KeyError) as error:
            self.message.setText(str(error))

    def compensation_wizard(self):
        from .compensation_wizard import CompensationWizard

        sample = self.state.prepared.sample
        detectors = [sample.pnn_labels[i] for i in sample.fluoro_indices]
        wizard = CompensationWizard(self, detectors)
        if wizard.exec() == W.QDialog.Accepted and wizard.spec is not None:
            try:
                self.flush_bounds()
                self.state.compensate(wizard.spec)
                self.show_gate(self.active_name)
            except (ValueError, OSError, KeyError) as error:
                self.message.setText(f"Matrix not applied: {error}")

    def matrix_dialog(self):
        super().matrix_dialog(allow_import=not bool(self.record.get("compensation_path")))

    def ratio_dialog(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Reporter scatter and ratio")
        form = W.QFormLayout(dialog)
        active = self.state.gate(self.active_name)
        existing = active if active and active["kind"] == "ratio" else None
        name = W.QLineEdit(existing["name"] if existing else "gfp_cy5_ratio")
        name.setEnabled(existing is None)
        name.setObjectName("ratio_name")
        numerator, denominator, parent = W.QComboBox(), W.QComboBox(), W.QComboBox()
        roles = self.state.recipe.get("channel_roles", {})
        for combo, role, index in [(numerator, "gfp", 0), (denominator, "cy5", 1)]:
            combo.addItems(list(self.state.recipe["transforms"]))
            combo.setCurrentText(
                existing["channels"][index] if existing else roles.get(role, {}).get("detector", "")
            )
        parent.addItems(
            ["root"]
            + [g["name"] for g in self.state.recipe["gates"] if not existing or g["name"] != existing["name"]]
        )
        parent.setCurrentText(
            existing["parent"]
            if existing
            else "live"
            if "live" in [g["name"] for g in self.state.recipe["gates"]]
            else "root"
        )
        low, high, floor = W.QLineEdit(), W.QLineEdit(), W.QLineEdit()
        for field, identifier in [(low, "ratio_low"), (high, "ratio_high"), (floor, "ratio_floor")]:
            field.setObjectName(identifier)
        low.setText(str(existing["bounds"][0]) if existing else "0.5")
        high.setText(str(existing["bounds"][1]) if existing else "2")
        floor.setText(str(existing["denominator_min"]) if existing else "0")
        for title, field in [
            ("Population name", name),
            ("Parent", parent),
            ("Numerator (X)", numerator),
            ("Denominator (Y)", denominator),
            ("Ratio minimum ≥", low),
            ("Ratio maximum <", high),
            ("Denominator signal must exceed", floor),
        ]:
            form.addRow(title, field)
        note = label(
            "Shared population · numerator / denominator uses compensated signal before display transforms. Set the denominator cutoff from controls to exclude background near zero. Initial bounds are examples.",
            "muted",
        )
        note.setWordWrap(True)
        form.addRow(note)

        def create():
            try:
                self.flush_bounds()
                if existing and any(
                    existing["name"] in changes
                    for changes in self.state.recipe.get("sample_overrides", {}).values()
                ):
                    raise ValueError(
                        "Reset this ratio population’s sample exceptions before changing its shared definition."
                    )
                gate = {
                    "name": name.text().strip(),
                    "parent": parent.currentText(),
                    "kind": "ratio",
                    "channels": [numerator.currentText(), denominator.currentText()],
                    "bounds": [float(low.text()), float(high.text())],
                    "denominator_min": float(floor.text()),
                    "reviewed": False,
                }
                candidate = copy.deepcopy(self.state.recipe)
                if existing:
                    candidate["gates"][
                        next(i for i, g in enumerate(candidate["gates"]) if g["name"] == existing["name"])
                    ] = gate
                    self.state.invalidate(candidate, gate["name"])
                else:
                    candidate["gates"].append(gate)
                self.state.apply(candidate)
                self.rebuild(gate["name"])
                self.plot_type.setCurrentText("Scatter")
                dialog.accept()
            except (ValueError, KeyError, TypeError) as error:
                note.setText(str(error))

        form.addRow(button("Show scatter and apply ratio", create, True))
        form.addRow(button("Cancel", dialog.reject))
        dialog.exec()

    def population_menu(self, position):
        item = self.gates.itemAt(position)
        if item is None:
            return
        self.gates.setCurrentItem(item)
        if self.active_name != item.data(0, QtCore.Qt.UserRole):
            return
        menu = W.QMenu(self)
        menu.addAction("New subpopulation…", self.new_population)
        menu.addAction("Delete population…", self.delete_population)
        menu.exec(self.gates.viewport().mapToGlobal(position))

    def delete_population(self):
        try:
            self.flush_bounds()
            affected = self.state.deletion_set(self.active_name)
            parent = self.state.gate(self.active_name)["parent"]
            message = W.QMessageBox(self)
            message.setWindowTitle("Delete population")
            message.setText(f"Remove {len(affected)} population(s) from all samples?")
            message.setInformativeText(
                "This includes child and dependent populations:\n"
                + ", ".join(affected)
                + "\n\nYou can Undo this change. It is written to the recipe when you save."
            )
            message.setStandardButtons(W.QMessageBox.Cancel | W.QMessageBox.Yes)
            message.button(W.QMessageBox.Yes).setText("Delete populations")
            message.setDefaultButton(W.QMessageBox.Cancel)
            if message.exec() != W.QMessageBox.Yes:
                return
            self.state.delete_population(self.active_name)
            self.rebuild(parent)
            self.message.setText(f"Removed {len(affected)} population(s). Undo restores them.")
        except (ValueError, KeyError) as error:
            self.message.setText(str(error))

    def scatter_dialog(self):
        from .scatter_viewer import ScatterDialog

        self.flush_bounds()
        ScatterDialog(self).exec()

    def new_population(self, preferred_kind=None, preferred_channels=None, parent_name=None):
        active = self.state.gate(self.active_name)
        if active is None:
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Add population")
        form = W.QFormLayout(dialog)
        name, x, y, parent, kind = W.QLineEdit(), W.QComboBox(), W.QComboBox(), W.QComboBox(), W.QComboBox()
        for identifier, widget in [
            ("population_name", name),
            ("x_detector", x),
            ("y_detector", y),
            ("parent_population", parent),
            ("gate_kind", kind),
        ]:
            widget.setObjectName(identifier)
        for combo in [x, y]:
            combo.addItems(list(self.state.recipe["transforms"]))
        x.setCurrentText(active["channels"][0])
        y.setCurrentText(active["channels"][-1])
        if x.currentText() == y.currentText() and y.count() > 1:
            y.setCurrentIndex((x.currentIndex() + 1) % y.count())
        if preferred_channels:
            x.setCurrentText(preferred_channels[0])
            y.setCurrentText(preferred_channels[1])
        parent.addItems(["root"] + [g["name"] for g in self.state.recipe["gates"]])
        relationship = W.QComboBox()
        relationship.setObjectName("population_relationship")
        relationship.addItems(
            ["Child of selected population", "Sibling of selected population", "Choose parent"]
        )
        parent.setCurrentText(active["name"])
        parent.setEnabled(False)

        def choose_relationship(index):
            parent.setEnabled(index == 2)
            if index != 2:
                parent.setCurrentText(active["name"] if index == 0 else active["parent"])

        relationship.currentIndexChanged.connect(choose_relationship)
        if parent_name is not None:
            relationship.setCurrentIndex(2)
            parent.setCurrentText(parent_name)
        form.addRow("Create as", relationship)
        kind.addItems(["rectangle", "polygon", "range", "boolean"])
        for title, field in [
            ("Name", name),
            ("Parent population", parent),
            ("Gate type", kind),
            ("X detector", x),
            ("Y detector", y),
        ]:
            form.addRow(title, field)
        left, right, operation = W.QComboBox(), W.QComboBox(), W.QComboBox()
        for field in [left, right]:
            field.addItems([g["name"] for g in self.state.recipe["gates"]])
        left.setObjectName("left_population")
        right.setObjectName("right_population")
        left.setCurrentText("gfp")
        right.setCurrentText("mscarlet")
        operation.addItems(["and", "or"])
        for title, field in [
            ("First population", left),
            ("Combine with", operation),
            ("Second population", right),
        ]:
            form.addRow(title, field)
            form.setRowVisible(field, False)
        kind.currentTextChanged.connect(
            lambda text: [form.setRowVisible(field, text == "boolean") for field in [left, right, operation]]
        )
        kind.currentTextChanged.connect(lambda text: form.setRowVisible(y, text != "range"))
        kind.setCurrentText(preferred_kind or ("range" if len(active["channels"]) == 1 else "rectangle"))
        message = label("Choose channels and a parent, then reshape the draft gate in the plot.", "muted")
        message.setWordWrap(True)
        form.addRow(message)

        def create():
            try:
                channels = (
                    [x.currentText()] if kind.currentText() == "range" else [x.currentText(), y.currentText()]
                )
                prepared, masks = self.session.get(self.record, self.state.recipe)
                values = prepared.transformed.loc[masks[parent.currentText()], channels].to_numpy()
                if not len(values):
                    raise ValueError("Parent contains no events")
                lo, hi = np.quantile(values, [0.1, 0.9], axis=0)
                hi = np.maximum(hi, lo + 0.001)
                gate = {
                    "name": name.text().strip(),
                    "parent": parent.currentText(),
                    "kind": kind.currentText(),
                    "channels": channels,
                    "reviewed": False,
                }
                if gate["kind"] == "boolean":
                    gate["operation"] = operation.currentText()
                    gate["references"] = [left.currentText(), right.currentText()]
                elif gate["kind"] == "polygon":
                    gate["vertices"] = [lo.tolist(), [hi[0], lo[1]], hi.tolist(), [lo[0], hi[1]]]
                elif gate["kind"] == "rectangle":
                    gate["bounds"] = [lo[0], hi[0], lo[1], hi[1]]
                else:
                    gate["bounds"] = [lo[0], hi[0]]
                candidate = copy.deepcopy(self.state.recipe)
                candidate["gates"].append(gate)
                self.state.apply(candidate)
                self.rebuild(gate["name"])
                dialog.accept()
                if gate["kind"] == "polygon":
                    self.gating_axes()
                    self.selector.clear()
                    self.help.setText(
                        "Click each vertex, then click the first vertex to finish. "
                        "The draft population is replaced when you finish drawing."
                    )
                    self.help.setToolTip(self.help.text())
            except (ValueError, KeyError, TypeError) as error:
                message.setText(str(error))

        form.addRow(button("Add draft population", create, True))
        dialog.exec()


def run_workbench(records, recipe, name, path):
    app = W.QApplication.instance() or W.QApplication([])
    app.setApplicationName("Agentflow")
    window = ScreenWindow(records, recipe, name, path)
    window.show()
    app.exec()
    return window.state.saved
