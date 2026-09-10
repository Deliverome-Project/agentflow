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
from .plot_views import apply_axes, draw_boundary, draw_events
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
        self.resize(1540, 960)
        self.setMinimumSize(1180, 800)
        top = W.QHBoxLayout()
        analysis_menu = W.QMenu(self)
        analysis_menu.addAction("Open analysis…", self.open_analysis)
        analysis_menu.addAction("Save and keep editing", lambda: self.save_changes(close=False))
        analysis_menu.addAction("Save and run all samples…", self.run_analysis)
        analysis_button = W.QPushButton("Analysis")
        analysis_button.setMenu(analysis_menu)
        top.addWidget(analysis_button)
        top.addWidget(label("SAMPLE"))
        self.sample_choice = W.QComboBox()
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
        self.group_choice.addItem("All groups")
        self.group_choice.addItems(sorted({r["group"] for r in records}))
        self.group_choice.currentIndexChanged.connect(self.redraw)
        top.addWidget(self.group_choice)
        self.overlay = W.QCheckBox("Overlay samples")
        self.overlay.toggled.connect(self.redraw)
        top.addWidget(self.overlay)
        top.addWidget(button("Detectors…", self.detectors_dialog))
        top.addWidget(button("New population…", self.new_population))
        self.root_layout.insertLayout(1, top)
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
        scopes.addWidget(button("Reset selected exception", self.reset_exception))
        scopes.addWidget(button("Next draft →", self.next_draft))
        self.focus_plot = W.QCheckBox("Focus plot")
        self.focus_plot.setToolTip("Hide comparison thumbnails to enlarge the editable plot")
        self.focus_plot.toggled.connect(self.toggle_focus)
        scopes.addWidget(self.focus_plot)
        scopes.addStretch()
        scopes.addWidget(button("Pinned controls…", self.pin_dialog))
        scopes.addWidget(button("Calculate compensation…", self.compensation_wizard))
        self.root_layout.insertLayout(3, scopes)
        display_panel = W.QWidget()
        display_layout = W.QVBoxLayout(display_panel)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_panel.hide()
        self.display_panel = display_panel
        display_toggle = W.QCheckBox("Plot appearance && axes")
        display_toggle.toggled.connect(display_panel.setVisible)
        self.main_layout.insertWidget(2, display_toggle)
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
        gallery_panel = W.QWidget()
        self.gallery_panel = gallery_panel
        gallery_panel.setMinimumWidth(310)
        gallery_layout = W.QVBoxLayout(gallery_panel)
        gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_mode = W.QComboBox()
        self.gallery_mode.addItems(["All populations", "Compare samples", "Plate map", "Ancestry"])
        self.gallery_mode.currentIndexChanged.connect(self.request_gallery)
        gallery_layout.addWidget(self.gallery_mode)
        self.plate_metric = W.QComboBox()
        self.plate_metric.addItems(["% of parent", "Event count", "Median signal (first detector)"])
        self.plate_metric.currentIndexChanged.connect(self.request_gallery)
        gallery_layout.addWidget(self.plate_metric)
        self.plate_metric.hide()
        paging = W.QHBoxLayout()
        paging.addWidget(label("Page", "muted"))
        self.gallery_page = W.QSpinBox()
        self.gallery_page.setMinimum(1)
        self.gallery_page.valueChanged.connect(self.request_gallery)
        paging.addWidget(self.gallery_page)
        paging.addStretch()
        gallery_layout.addLayout(paging)
        gallery_layout.addWidget(label("Click a plot to select it", "muted"))
        self.gallery_figure = Figure(figsize=(5, 8), facecolor="white")
        self.gallery_canvas = FigureCanvasQTAgg(self.gallery_figure)
        self.gallery_canvas.setMinimumHeight(600)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.gallery_canvas)
        gallery_layout.addWidget(scroll, 1)
        self.gallery_axes = {}
        self.gallery_canvas.mpl_connect("button_press_event", self.select_gallery)
        self.body_layout.addWidget(gallery_panel, 2)
        self.body_layout.setStretch(1, 3)
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
        self.ready = True
        self.gallery_mode.setCurrentText(display.get("gallery_mode", "All populations"))
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
            self.request_gallery()

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
        apply_axes(self.ax, gate["channels"], self.state.recipe, modes)
        self.picked = {}
        for other in self.state.active_recipe["gates"]:
            if (
                other["name"] != gate["name"]
                and other.get("channels") == gate["channels"]
                and other["parent"] == gate["parent"]
            ):
                for artist in draw_boundary(self.ax, other, "#5848a8", 1.6, True):
                    self.picked[artist] = other["name"]
        preview = gate["kind"] == "polygon" and any(m != "recipe" for m in modes[: len(gate["channels"])])
        if preview:
            if self.selector:
                self.selector.set_active(False)
                self.selector.set_visible(False)
            draw_boundary(self.ax, gate)
            self.help.setText(
                "Display preview · counts and gates are unchanged. Use gating axes to edit. Asinh cofactor 150; logicle T=262144, W=.5, M=4.5, A=0."
            )
        else:
            self.help.setText(
                self.help.text()
                + " Scroll to zoom. Scatter displays up to 20,000 events per sample; counts use all events."
            )
        self.help.setToolTip(self.help.text())
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
        self.plate_metric.setVisible(self.gallery_mode.currentIndex() == 2)
        if self.gallery_mode.currentIndex() == 2:
            self.draw_plates()
            return
        compare = self.gallery_mode.currentIndex() == 1
        items = self.selected_records() if compare else self.state.active_recipe["gates"]
        if self.gallery_mode.currentText() == "Ancestry":
            items = self.ancestry()
        self.gallery_page.setMaximum(max(1, (len(items) + 11) // 12))
        start = (self.gallery_page.value() - 1) * 12
        all_items = items
        items = items[start : start + 12]
        n = len(items)
        columns = 1 if self.gallery_canvas.width() < 420 else 2
        rows = max(1, (n + columns - 1) // columns)
        self.gallery_canvas.setMinimumHeight(rows * 260)
        shared_limits = None
        active = self.state.gate(self.active_name)
        if compare and active:
            limits = []
            for r in all_items:
                prepared, masks = self.session.get(r, self.state.recipe)
                values = prepared.transformed.loc[masks[active["parent"]], active["channels"]].to_numpy()
                if len(values):
                    limits.append((values.min(axis=0), values.max(axis=0)))
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
                draw_events(ax, data, gate["channels"], "density", record["color"])
                draw_boundary(ax, gate)
                count = int(masks[gate["name"]].sum())
                total = int(masks[gate["parent"]].sum())
                title = record["sample_id"] if compare else TITLES.get(gate["name"], gate["name"])
                ax.set_title(
                    f"{title}\n{count:,} / {total:,}",
                    fontsize=9,
                    color="#922038" if gate["name"] == self.active_name else "#141414",
                )
                if shared_limits:
                    for dim, setter in enumerate([ax.set_xlim, ax.set_ylim][: len(gate["channels"])]):
                        lo, hi = shared_limits[0][dim], shared_limits[1][dim]
                        margin = max((hi - lo) * 0.05, 0.01)
                        setter(lo - margin, hi + margin)
                apply_axes(ax, gate["channels"], self.state.recipe, ["recipe", "recipe"])
                ax.tick_params(labelsize=7)
                ax.xaxis.label.set_size(8)
                ax.yaxis.label.set_size(8)
            except (ValueError, OSError, KeyError) as error:
                ax.text(0.05, 0.5, str(error), transform=ax.transAxes, wrap=True, fontsize=8)
        self.gallery_figure.tight_layout(pad=1.6)
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
                    "Plate map needs valid plate/well metadata (A01–P24).",
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
        self.gallery_canvas.setMinimumHeight(500)
        self.gallery_figure.tight_layout()
        self.gallery_canvas.draw_idle()

    def select_gallery(self, event):
        selected = self.gallery_axes.get(event.inaxes)
        if selected:
            kind, value = selected
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

    def edit_mode(self):
        super().edit_mode()
        if self.ready and any(c.currentIndex() for c in [self.x_scale, self.y_scale]) and self.selector:
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

        detectors = [c for c, t in self.state.recipe["transforms"].items() if t["kind"] != "linear"]
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

    def new_population(self):
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
        kind.setCurrentText("range" if len(active["channels"]) == 1 else "rectangle")
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
                    gate["bounds"] = [lo[0], None]
                candidate = copy.deepcopy(self.state.recipe)
                candidate["gates"].append(gate)
                self.state.apply(candidate)
                self.rebuild(gate["name"])
                dialog.accept()
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
