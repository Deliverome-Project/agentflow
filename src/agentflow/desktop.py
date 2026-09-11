"""Native desktop gate review with an embedded Matplotlib canvas.

Imported only by the optional edit command; batch use never requires Qt.
"""

import re

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.widgets import PolygonSelector, RectangleSelector, SpanSelector
from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .compensation import load_matrix
from .editor_state import EditorState
from .engine import evaluate
from .plots import draw_population
from .population_tree import PopulationTree
from .theme import ASSETS, BERRY, CORAL, desktop_style, setup_plots
from .threshold import ThresholdSelector
from .workflow import ROLES

TITLES = {
    "cells": "Cells",
    "singlets": "Singlets",
    "live": "Live / dead",
    "gfp": "GFP",
    "mscarlet": "mScarlet",
    "cy5": "Cy5",
}


def label(text="", style=None):
    result = W.QLabel(text)
    result.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    if style:
        result.setObjectName(style)
    return result


def button(text, callback, primary=False):
    result = W.QPushButton(text)
    result.clicked.connect(callback)
    if primary:
        result.setObjectName("primary")
    return result


class GateWindow(W.QMainWindow):
    def __init__(self, prepared, recipe, name, path):
        super().__init__()
        setup_plots()
        for font in ASSETS.glob("*.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font))
        self.state = EditorState(prepared, recipe, path)
        self.selector = None
        self.discarding = False
        self.setWindowTitle("Agentflow · Gate review")
        self.resize(1260, 840)
        self.setMinimumSize(980, 700)
        self.setStyleSheet(desktop_style())
        root = W.QWidget(objectName="root")
        self.setCentralWidget(root)
        layout = W.QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        self.root_layout = layout
        header = W.QHBoxLayout()
        header.addWidget(label("agentflow", "brand"))
        header.addSpacing(18)
        header.addWidget(label("FLOW CYTOMETRY  /  GATE REVIEW", "eyebrow"))
        header.addStretch()
        if recipe.get("experiment", {}).get("is_example"):
            header.addWidget(label("DUMMY / EXAMPLE", "badge"))
        layout.addLayout(header)
        body = W.QHBoxLayout()
        body.setSpacing(18)
        self.body_layout = body
        layout.addLayout(body, 1)
        sidebar = W.QVBoxLayout()
        side = W.QWidget()
        side.setFixedWidth(190)
        side.setLayout(sidebar)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.addWidget(label("POPULATIONS", "eyebrow"))
        self.progress = label("", "muted")
        sidebar.addWidget(self.progress)
        self.gates = PopulationTree()
        self.gates.currentRowChanged.connect(self.change_row)
        sidebar.addWidget(self.gates, 1)
        sidebar.addWidget(label("SAMPLE", "eyebrow"))
        sample_name = label(str(prepared.sample.id), "muted")
        self.sample_label = sample_name
        sample_name.setWordWrap(True)
        sidebar.addWidget(sample_name)
        self.event_label = label(f"{prepared.sample.event_count:,} acquired events", "muted")
        sidebar.addWidget(self.event_label)
        sidebar.addSpacing(20)
        sidebar.addWidget(label("COMPENSATION", "eyebrow"))
        self.compensation_label = label("", "muted")
        self.compensation_label.setWordWrap(True)
        sidebar.addWidget(self.compensation_label)
        sidebar.addWidget(button("View / change matrix…", self.matrix_dialog))
        if hasattr(self, "compensation_wizard"):
            sidebar.addWidget(button("Set up compensation…", self.compensation_wizard))
        body.addWidget(side)
        main = W.QVBoxLayout()
        main.setSpacing(10)
        self.main_layout = main
        main_widget = W.QWidget(objectName="analysis_panel")
        main_widget.setLayout(main)
        main_scroll = W.QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(W.QFrame.NoFrame)
        main_scroll.setWidget(main_widget)
        main_scroll.setMinimumWidth(360)
        self.main_scroll = main_scroll
        body.addWidget(main_scroll, 1)
        self.title = label("", "title")
        self.subtitle = label("", "muted")
        main.addWidget(self.title)
        main.addWidget(self.subtitle)
        self.stack = W.QStackedWidget()
        self.stack.setMinimumHeight(380)
        self.stack.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Ignored)
        main.addWidget(self.stack, 1)
        plot_card = W.QFrame(objectName="card")
        card_layout = W.QVBoxLayout(plot_card)
        card_layout.setContentsMargins(12, 12, 12, 6)
        tools = W.QHBoxLayout()
        self.edit_button = button("Edit gate", self.edit_mode)
        self.pan_button = button("Pan", self.pan_mode)
        self.zoom_button = button("Zoom", self.zoom_mode)
        for item in (self.edit_button, self.pan_button, self.zoom_button):
            item.setCheckable(True)
            tools.addWidget(item)
        tools.addWidget(button("Fit view", self.fit_view))
        tools.addStretch()
        self.review_badge = label("", "badge")
        tools.addWidget(self.review_badge)
        card_layout.addLayout(tools)
        self.figure = Figure(figsize=(8, 5), facecolor="white", layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.canvas.setMinimumHeight(260)
        self.canvas.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Ignored)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.hide()
        card_layout.addWidget(self.canvas, 1)
        self.help = label("", "muted")
        self.help.setWordWrap(True)
        self.help.setMaximumHeight(44)
        card_layout.addWidget(self.help)
        self.stack.addWidget(plot_card)
        pending = W.QFrame(objectName="card")
        pending_layout = W.QVBoxLayout(pending)
        pending_layout.setContentsMargins(36, 32, 36, 32)
        pending_layout.addStretch()
        pending_layout.addWidget(label("Choose a detector to begin", "title"))
        self.pending_reason = label("", "muted")
        self.pending_reason.setWordWrap(True)
        pending_layout.addWidget(self.pending_reason)
        self.channel = W.QComboBox()
        pending_layout.addWidget(self.channel)
        self.confirm_mapping = W.QCheckBox("I confirm this detector measures the intended dye")
        pending_layout.addWidget(self.confirm_mapping)
        self.assign_button = button("Add draft gate", self.assign, True)
        self.assign_button.setEnabled(False)
        self.confirm_mapping.toggled.connect(
            lambda checked: self.assign_button.setEnabled(checked and self.channel.count() > 0)
        )
        pending_layout.addWidget(self.assign_button)
        pending_layout.addWidget(label("Unmapped populations are not included in analysis.", "muted"))
        pending_layout.addStretch()
        self.stack.addWidget(pending)
        self.bounds_widget = W.QWidget()
        bounds_layout = W.QHBoxLayout(self.bounds_widget)
        bounds_layout.setContentsMargins(0, 0, 0, 0)
        bounds_layout.addWidget(label("Keep events"))
        self.range_mode = W.QComboBox()
        self.range_mode.addItems(["Above threshold", "Below threshold", "Between bounds"])
        self.range_mode.currentIndexChanged.connect(self.change_range_mode)
        bounds_layout.addWidget(self.range_mode)
        self.lower = W.QLineEdit()
        self.upper = W.QLineEdit()
        self.lower.setPlaceholderText("Lower bound")
        self.upper.setPlaceholderText("Upper bound")
        self.lower.returnPressed.connect(self.apply_bounds)
        self.upper.returnPressed.connect(self.apply_bounds)
        bounds_layout.addWidget(self.lower)
        bounds_layout.addWidget(self.upper)
        bounds_layout.addWidget(button("Apply", self.apply_bounds))
        main.addWidget(self.bounds_widget)
        stats = W.QHBoxLayout()
        self.count = label("", "metric")
        self.percent = label("", "muted")
        stats.addWidget(self.count)
        stats.addWidget(self.percent)
        stats.addStretch()
        self.review_button = button("Review & next →", self.review_next)
        stats.addWidget(self.review_button)
        main.addLayout(stats)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        main.addWidget(self.note)
        footer = W.QHBoxLayout()
        self.undo_button = button("Undo", lambda: self.travel(False))
        self.redo_button = button("Redo", lambda: self.travel(True))
        footer.addWidget(self.undo_button)
        footer.addWidget(self.redo_button)
        self.message = label("Changes stay local until you save.", "muted")
        self.message.setWordWrap(True)
        footer.addWidget(self.message, 1)
        footer.addWidget(button("Cancel", self.close))
        self.save_button = button("Save & close", self.save, True)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        for key, callback in [
            ("Ctrl+S", self.save),
            ("Ctrl+Z", lambda: self.travel(False)),
            ("Ctrl+Shift+Z", lambda: self.travel(True)),
        ]:
            action = QtGui.QAction(self)
            action.setShortcut(QtGui.QKeySequence(key))
            action.triggered.connect(callback)
            self.addAction(action)
        self.rebuild(name)

    def rebuild(self, name=None):
        actual = [g["name"] for g in self.state.recipe["gates"]]
        pending = [g["name"] for g in self.state.recipe.get("pending_gates", [])]
        order = ["cells", "singlets", *ROLES]
        self.names = [n for n in order if n in actual + pending]
        self.names += [n for n in actual + pending if n not in self.names]
        self.gates.blockSignals(True)
        self.gates.populate(self.names, self.state.recipe["gates"], TITLES)
        row = self.names.index(name) if name in self.names else 0
        self.gates.setCurrentRow(row)
        self.gates.blockSignals(False)
        self.show_gate(self.names[row])

    def change_row(self, row):
        if row >= 0:
            try:
                self.flush_bounds()
            except (ValueError, TypeError) as error:
                self.message.setText(f"Fix the threshold before changing gates: {error}")
                self.gates.blockSignals(True)
                self.gates.setCurrentRow(self.names.index(self.active_name))
                self.gates.blockSignals(False)
                return
            self.show_gate(self.names[row])

    def bound_value(self, field, index):
        # Short display text must not round an untouched saved coordinate.
        bounds = self.state.gate(self.active_name)["bounds"]
        for original in (bounds[index], bounds[1 - index]):
            if original is not None and field.text() == f"{original:.8g}":
                return original
        return float(field.text())

    def flush_bounds(self):
        if not hasattr(self, "active_name"):
            return
        gate = self.state.gate(self.active_name)
        if gate and gate["kind"] == "range":
            mode = self.range_mode.currentIndex()
            bounds = [
                None if mode == 1 else self.bound_value(self.lower, 0),
                None if mode == 0 else self.bound_value(self.upper, 1),
            ]
            self.state.geometry(self.active_name, "bounds", bounds)

    def show_gate(self, name):
        self.active_name = name
        if self.selector:
            self.selector.disconnect_events()
        self.selector = None
        self.toolbar.mode and self.edit_mode()
        self.ax.clear()
        gate = self.state.gate(name)
        mapping = self.state.recipe.get("channel_roles", {}).get(name)
        uncertain = mapping is not None and not mapping.get("confirmed", False)
        self.title.setText(TITLES.get(name, name) + (" candidate" if uncertain else ""))
        self.bounds_widget.setVisible(bool(gate and gate["kind"] == "range"))
        self.review_button.setEnabled(gate is not None)
        if gate is None:
            self.stack.setCurrentIndex(1)
            entry = next(p for p in self.state.recipe["pending_gates"] if p["name"] == name)
            self.pending_reason.setText(entry["reason"])
            self.subtitle.setText("Detector not assigned · Not analyzed")
            self.channel.clear()
            used = {
                re.sub(r"-[AHW]$", "", value["detector"])
                for value in self.state.recipe.get("channel_roles", {}).values()
            }
            available = [
                self.state.prepared.sample.pnn_labels[i]
                for i in self.state.prepared.sample.fluoro_indices
                if re.sub(r"-[AHW]$", "", self.state.prepared.sample.pnn_labels[i]) not in used
            ]
            self.channel.addItems(available)
            self.confirm_mapping.setEnabled(bool(available))
            if not available:
                self.pending_reason.setText(
                    entry["reason"] + " No unassigned fluorescence detector is available in this sample."
                )
            self.confirm_mapping.setChecked(False)
            self.assign_button.setEnabled(False)
            self.note.setText("Use the acquisition panel or controls to confirm dye assignments.")
            self.count.setText("—")
            self.percent.setText("No population count")
            self.refresh()
            return
        self.stack.setCurrentIndex(0)
        self.subtitle.setText(
            "Parent: "
            + TITLES.get(gate["parent"], gate["parent"]).replace("root", "All events")
            + "  ·  "
            + " × ".join(gate["channels"])
        )
        if uncertain:
            self.subtitle.setText(self.subtitle.text() + "  ·  Dye mapping unconfirmed")
        parent = evaluate(self.state.prepared, self.state.active_recipe)[gate["parent"]]
        self.draw_active(gate, parent)
        for axis, channel in zip((self.ax.xaxis, self.ax.yaxis), gate["channels"]):
            axis.set_label_text(f"{channel}  ·  {self.state.recipe['transforms'][channel]['kind']}")
        kind = gate["kind"]
        if kind == "polygon":
            self.ax.update_datalim(gate["vertices"])
            self.ax.autoscale_view()
            self.selector = PolygonSelector(
                self.ax,
                self.polygon,
                useblit=True,
                props={"color": CORAL, "linewidth": 2},
                handle_props={"markerfacecolor": "white", "markeredgecolor": BERRY, "markersize": 8},
                grab_range=15,
            )
            self.selector.verts = gate["vertices"]
            help_text = "Drag a vertex to reshape. Shift-drag moves the gate; click to draw a new polygon."
        elif kind == "rectangle":
            a, b, c, d = gate["bounds"]
            self.ax.update_datalim([[a, c], [b, d]])
            self.ax.autoscale_view()
            self.selector = RectangleSelector(
                self.ax,
                self.rectangle,
                interactive=True,
                useblit=True,
                button=[1],
                grab_range=15,
                handle_props={"markersize": 8},
                props={"facecolor": CORAL, "edgecolor": BERRY, "alpha": 0.2, "linewidth": 2},
            )
            self.selector.extents = gate["bounds"]
            help_text = (
                "Drag a corner or edge to resize. Drag inside to move; drag outside to draw a new gate."
            )
        elif kind == "boolean":
            help_text = (
                "Combined population: "
                + (" " + gate["operation"].upper() + " ").join(gate["references"])
                + ". Adjust its defining gates to change membership."
            )
        else:
            low, high = gate["bounds"]
            for value in (low, high):
                if value is not None:
                    self.ax.update_datalim([[value, 0]])
            self.ax.autoscale_view()
            self.range_mode.blockSignals(True)
            self.range_mode.setCurrentIndex(0 if high is None else 1 if low is None else 2)
            self.range_mode.blockSignals(False)
            self.lower.setText("" if low is None else f"{low:.8g}")
            self.upper.setText("" if high is None else f"{high:.8g}")
            self.update_bound_fields()
            self.selector = SpanSelector(
                self.ax,
                self.span,
                "horizontal",
                interactive=True,
                useblit=True,
                drag_from_anywhere=True,
                props={"facecolor": CORAL, "alpha": 0.1},
                handle_props={"color": BERRY, "linewidth": 2},
            )
            xmin, xmax = self.ax.get_xlim()
            self.selector.extents = (xmin if low is None else low, xmax if high is None else high)
            if low is None or high is None:
                self.selector.set_visible(False)
                self.selector.disconnect_events()
                self.selector = ThresholdSelector(
                    self.ax, high if low is None else low, low is None, self.span, BERRY
                )
            help_text = "Drag the shaded edge to set a threshold, or enter an exact value below. Units are transformed."
        self.help.setText(help_text)
        self.note.setText(
            gate.get("note", "Counts use every event; the saved recipe also drives batch analysis.")
        )
        self.edit_mode()
        self.refresh()
        self.finish_plot(gate)
        self.canvas.draw_idle()

    def draw_active(self, gate, parent):
        draw_population(self.ax, self.state.prepared, gate, parent)

    def finish_plot(self, gate):
        pass

    def refresh(self):
        counts = self.state.counts()
        for i, name in enumerate(self.names):
            gate = self.state.gate(name)
            suffix = "Not assigned" if gate is None else ("Reviewed" if gate.get("reviewed") else "Draft")
            count = "" if gate is None else f"  ·  {counts[name]:,}"
            exception = name in self.state.recipe.get("sample_overrides", {}).get(self.state.sample_id, {})
            ownership = "Exception" if exception else "Shared"
            detail = f"{suffix}{count}"
            if gate:
                detail += f" · {ownership}"
            tooltip = f"{name} · {detail}"
            if gate:
                parent_count = counts[gate["parent"]]
                percent = f"{100 * counts[name] / parent_count:.2f}%" if parent_count else "Not available"
                tooltip += f"\nParent: {gate['parent']} · {percent} of parent\nDetectors: {', '.join(gate['channels'])}"
            self.gates.set_population_text(i, TITLES.get(name, name), detail, tooltip)
        gate = self.state.gate(self.active_name)
        if gate:
            count, parent = counts[gate["name"]], counts[gate["parent"]]
            self.count.setText(f"{count:,}")
            self.percent.setText(
                f"events kept  ·  {100 * count / parent:.2f}% of {parent:,} parent events"
                if parent
                else "events kept  ·  parent is empty"
            )
            self.review_badge.setText("Reviewed" if gate.get("reviewed") else "Draft gate")
        reviewed = sum(bool(g.get("reviewed")) for g in self.state.active_recipe["gates"])
        self.progress.setText(f"{reviewed} of {len(self.state.recipe['gates'])} gates reviewed")
        spec = self.state.recipe["compensation"]
        mode = spec["mode"]
        matrix = self.state.prepared.matrix
        text = {"none": "Uncompensated", "fcs": "From sample", "matrix": "Imported matrix"}[mode]
        if matrix is not None and np.allclose(matrix.matrix, np.eye(len(matrix.detectors))):
            text += "\nIdentity matrix · no correction"
        self.compensation_label.setText(text)
        self.undo_button.setEnabled(bool(self.state.history))
        self.redo_button.setEnabled(bool(self.state.future))
        self.save_button.setText("Save changes & close" if self.state.dirty else "Save & close")
        self.after_refresh()

    def after_refresh(self):
        pass

    def perform(self, action, redraw=True):
        try:
            action()
            if redraw:
                self.show_gate(self.active_name)
            else:
                self.refresh()
            self.message.setText(
                "Unsaved changes · Undo is available." if self.state.dirty else "No unsaved changes."
            )
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.message.setText(str(error))

    def polygon(self, points):
        self.perform(
            lambda: self.state.geometry(
                self.active_name, "vertices", [[float(x), float(y)] for x, y in points]
            ),
            False,
        )

    def rectangle(self, _press, _release):
        self.perform(
            lambda: self.state.geometry(self.active_name, "bounds", list(self.selector.extents)), False
        )

    def span(self, low, high):
        limits = self.ax.get_xlim(), self.ax.get_ylim()
        mode = self.range_mode.currentIndex()
        bounds = [None if mode == 1 else float(low), None if mode == 0 else float(high)]
        self.perform(lambda: self.state.geometry(self.active_name, "bounds", bounds))
        self.ax.set_xlim(limits[0])
        self.ax.set_ylim(limits[1])
        self.canvas.draw_idle()

    def update_bound_fields(self):
        mode = self.range_mode.currentIndex()
        self.lower.setVisible(mode != 1)
        self.upper.setVisible(mode != 0)

    def change_range_mode(self):
        self.update_bound_fields()
        # Keep the existing finite threshold when reversing the retained side.
        if not self.lower.text():
            self.lower.setText(self.upper.text())
        if not self.upper.text():
            self.upper.setText(self.lower.text())

    def apply_bounds(self):
        def apply():
            mode = self.range_mode.currentIndex()
            bounds = [
                None if mode == 1 else self.bound_value(self.lower, 0),
                None if mode == 0 else self.bound_value(self.upper, 1),
            ]
            self.state.geometry(self.active_name, "bounds", bounds)

        self.perform(apply)

    def assign(self):
        if self.confirm_mapping.isChecked():
            self.perform(lambda: self.state.assign(self.active_name, self.channel.currentText()))

    def travel(self, redo):
        self.perform(lambda: self.state.travel(redo))

    def review_next(self):
        def review():
            self.flush_bounds()
            self.state.review(self.active_name)
            index = self.names.index(self.active_name)
            if index + 1 < len(self.names):
                self.gates.setCurrentRow(index + 1)

        self.perform(review)

    def edit_mode(self):
        if self.toolbar.mode == "pan/zoom":
            self.toolbar.pan()
        elif self.toolbar.mode == "zoom rect":
            self.toolbar.zoom()
        if self.selector:
            self.selector.set_active(True)
        self.edit_button.setChecked(True)
        self.pan_button.setChecked(False)
        self.zoom_button.setChecked(False)

    def pan_mode(self):
        self.edit_mode()
        if self.selector:
            self.selector.set_active(False)
        self.toolbar.pan()
        self.edit_button.setChecked(False)
        self.pan_button.setChecked(True)

    def zoom_mode(self):
        self.edit_mode()
        if self.selector:
            self.selector.set_active(False)
        self.toolbar.zoom()
        self.edit_button.setChecked(False)
        self.zoom_button.setChecked(True)

    def fit_view(self):
        self.show_gate(self.active_name)

    def matrix_dialog(self, allow_import=True):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Compensation")
        dialog.resize(640, 420)
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(label("Compensation matrix", "title"))
        layout.addWidget(label(self.compensation_label.text(), "muted"))
        matrix = self.state.prepared.matrix
        if matrix is not None:
            table = W.QTableWidget(len(matrix.detectors), len(matrix.detectors))
            table.setHorizontalHeaderLabels(matrix.detectors)
            table.setVerticalHeaderLabels(matrix.detectors)
            table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, row in enumerate(matrix.matrix):
                for j, value in enumerate(row):
                    table.setItem(i, j, W.QTableWidgetItem(f"{value:.5g}"))
            layout.addWidget(table)
        info = label(
            "Import a labelled CSV, TSV or JSON spillover matrix. Changing compensation resets gate review.",
            "muted",
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        def load():
            path, _ = W.QFileDialog.getOpenFileName(
                dialog, "Import compensation matrix", "", "Matrix files (*.csv *.tsv *.json)"
            )
            if path:
                try:
                    self.state.compensate(load_matrix(path))
                    self.show_gate(self.active_name)
                    self.message.setText("Matrix applied. Review gates in the new compensated space.")
                    dialog.accept()
                except (ValueError, OSError, KeyError, TypeError) as error:
                    info.setText(str(error))

        if allow_import:
            layout.addWidget(button("Import matrix…", load, True))
        else:
            info.setText(
                "Assigned by compensation_path in the sample sheet. Change that assignment to use another matrix."
            )
        layout.addWidget(button("Done", dialog.accept))
        dialog.exec()

    def save(self):
        # Commit a typed threshold even if focus has not left the input field.
        gate = self.state.gate(self.active_name)
        try:
            if gate and gate["kind"] == "range":
                mode = self.range_mode.currentIndex()
                bounds = [
                    None if mode == 1 else self.bound_value(self.lower, 0),
                    None if mode == 0 else self.bound_value(self.upper, 1),
                ]
                self.state.geometry(self.active_name, "bounds", bounds)
            self.state.save()
            self.close()
        except (ValueError, OSError, TypeError) as error:
            self.message.setText(f"Not saved: {error}")

    def closeEvent(self, event):
        pending_invalid = False
        if not self.discarding:
            try:
                self.flush_bounds()
            except (ValueError, TypeError):
                pending_invalid = True
        if (self.state.dirty or pending_invalid) and not self.discarding:
            answer = W.QMessageBox.question(
                self,
                "Unsaved gate edits",
                "Save your gate changes before closing?",
                W.QMessageBox.StandardButton.Save
                | W.QMessageBox.StandardButton.Discard
                | W.QMessageBox.StandardButton.Cancel,
                W.QMessageBox.StandardButton.Cancel,
            )
            if answer == W.QMessageBox.StandardButton.Save:
                event.ignore()
                self.save()
                return
            if answer != W.QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()


def run_editor(prepared, recipe, name, path):
    app = W.QApplication.instance() or W.QApplication([])
    app.setApplicationName("Agentflow")
    window = GateWindow(prepared, recipe, name, path)
    window.show()
    app.exec()
    return window.state.saved
