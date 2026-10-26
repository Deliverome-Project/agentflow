"""Flip through samples on the N×N compensation check and edit spillover, as in FlowJo's matrix editor."""

import time
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .channel_names import channel_label
from .compensation_view import DISPLAY_EVENTS, draw_compensation_matrix, matrix_channels
from .desktop import button, label
from .spillover_edit import SpilloverDraft, drag_edit, save_edited_matrix
from .theme import CORAL

EDITED_CELL = QtGui.QColor("#fde3df")
# A drag shorter than this fraction of the plot is a click, not an edit.
MINIMUM_DRAG = 0.03


class CompensationMatrixDialog(W.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Compensation matrix check")
        self.resize(1000, 940)
        layout = W.QVBoxLayout(self)
        controls = W.QHBoxLayout()
        controls.addWidget(label("Preview sample"))
        self.sample = W.QComboBox()
        for record in window.records:
            self.sample.addItem(record["sample_id"], record["sample_id"])
        self.sample.setCurrentIndex(self.sample.findData(window.record["sample_id"]))
        controls.addWidget(button("‹", lambda: self.step(-1)))
        controls.addWidget(self.sample, 1)
        controls.addWidget(button("›", lambda: self.step(1)))
        controls.addWidget(label("Population"))
        self.population = W.QComboBox()
        self.population.addItem("All events", "root")
        for gate in window.state.recipe["gates"]:
            self.population.addItem(gate.get("label", gate["name"]), gate["name"])
        controls.addWidget(self.population)
        self.detectors = W.QToolButton()
        self.detectors.setPopupMode(W.QToolButton.InstantPopup)
        self.detector_menu = W.QMenu(self.detectors)
        self.detectors.setMenu(self.detector_menu)
        controls.addWidget(self.detectors)
        self.overlay = W.QCheckBox("Overlay uncompensated")
        self.overlay.setToolTip("Draw the same events before compensation on top, in coral.")
        controls.addWidget(self.overlay)
        layout.addLayout(controls)
        split = W.QSplitter(QtCore.Qt.Vertical)
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(8, 7), facecolor="white", layout="constrained"))
        split.addWidget(self.canvas)
        editor = W.QWidget()
        editor_layout = W.QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 4, 0, 0)
        editor_layout.addWidget(label("Spillover (%) · row dye measured in column detector", "eyebrow"))
        self.table = W.QTableWidget(0, 0)
        self.table.itemChanged.connect(self.cell_edited)
        editor_layout.addWidget(self.table, 1)
        self.edit_note = label("", "muted")
        self.edit_note.setWordWrap(True)
        editor_layout.addWidget(self.edit_note)
        split.addWidget(editor)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        actions = W.QHBoxLayout()
        self.undo_button = button("Undo edit", self.undo)
        self.reset_button = button("Reset to assigned matrix", self.reset)
        self.apply_button = button("Apply edited matrix…", self.confirm_apply, True)
        for widget in (self.undo_button, self.reset_button):
            actions.addWidget(widget)
        actions.addStretch()
        actions.addWidget(self.apply_button)
        actions.addWidget(button("Close", self.accept))
        layout.addLayout(actions)
        for keys, delta in [((QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown), 1), ((QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp), -1)]:
            for key in keys:
                shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
                shortcut.activated.connect(lambda d=delta: self.step(d))
        QtGui.QShortcut(QtGui.QKeySequence.Undo, self).activated.connect(self.undo)
        self.canvas.mpl_connect("button_press_event", self.drag_start)
        self.canvas.mpl_connect("button_release_event", self.drag_end)
        self.pressed = None
        self.axes = {}
        self.channels = []
        self.draft = None
        self.load_draft()
        self.sample.currentIndexChanged.connect(self.redraw)
        self.population.currentIndexChanged.connect(self.redraw)
        self.overlay.toggled.connect(self.redraw)
        self.redraw()

    def record(self):
        return self.window.records[self.sample.currentIndex()]

    def step(self, delta):
        count = self.sample.count()
        if count:
            self.sample.setCurrentIndex((self.sample.currentIndex() + delta) % count)

    def build_detector_menu(self, prepared):
        """Rebuild only when the available detectors change; keep the user's subset."""
        available = matrix_channels(prepared)
        if available == self.channels:
            return
        previous = {a.data() for a in self.detector_menu.actions() if a.isCheckable() and not a.isChecked()}
        self.channels = available
        self.detector_menu.clear()
        everything = self.detector_menu.addAction("All")
        everything.triggered.connect(lambda: self.set_all(True))
        self.detector_menu.addSeparator()
        for channel in available:
            action = self.detector_menu.addAction(channel_label(prepared.sample, channel))
            action.setData(channel)
            action.setCheckable(True)
            action.setChecked(channel not in previous)
            action.toggled.connect(self.redraw)

    def set_all(self, checked):
        for action in self.detector_menu.actions():
            if action.isCheckable():
                action.blockSignals(True)
                action.setChecked(checked)
                action.blockSignals(False)
        self.redraw()

    def selected_channels(self):
        return [a.data() for a in self.detector_menu.actions() if a.isCheckable() and a.isChecked()]

    # Spillover editing. The draft edits the shared recipe matrix; samples with
    # their own sample-sheet compensation_path keep that file and never show it.

    def load_draft(self):
        """Start editing from the shared recipe matrix, or explain why editing is unavailable."""
        try:
            self.draft = SpilloverDraft(self.window.state.recipe["compensation"])
        except ValueError as error:
            self.draft = None
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.table.setEnabled(False)
            self.edit_note.setText(str(error))
        else:
            self.table.setEnabled(True)
            self.fill_table()
        self.update_actions()

    def fill_table(self):
        draft = self.draft
        names = draft.detectors
        changed = set(draft.changed_cells())
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(names))
            self.table.setColumnCount(len(names))
            sample = self.window.state.prepared.sample
            labels = [channel_label(sample, n) for n in names]
            self.table.setHorizontalHeaderLabels(labels)
            self.table.setVerticalHeaderLabels(labels)
            for i in range(len(names)):
                for j in range(len(names)):
                    item = W.QTableWidgetItem(f"{100 * draft.values[i, j]:.3f}")
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    if i == j:
                        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                        item.setForeground(QtGui.QColor("#9a8f8d"))
                    elif (i, j) in changed:
                        item.setBackground(EDITED_CELL)
                        item.setToolTip(
                            f"Edited · assigned {100 * draft.original[i, j]:.3f}% → draft {100 * draft.values[i, j]:.3f}%"
                        )
                    else:
                        item.setToolTip(f"{labels[i]} measured in {labels[j]} · assigned value")
                    self.table.setItem(i, j, item)
            self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
            # Show every row up to about ten detectors; larger matrices scroll.
            rows = self.table.verticalHeader().defaultSectionSize() * min(len(names), 10)
            self.table.setMinimumHeight(rows + self.table.horizontalHeader().sizeHint().height() + 2 * self.table.frameWidth() + 8)
        finally:
            self.table.blockSignals(False)

    def cell_edited(self, item):
        if self.draft is None:
            return
        names = self.draft.detectors
        try:
            self.draft.set(names[item.row()], names[item.column()], float(item.text().strip().rstrip("%")) / 100)
        except ValueError as error:
            self.edit_note.setText(f"Not changed: {error}")
            self.fill_table()
            return
        self.edited()

    def edited(self):
        self.fill_table()
        self.update_actions()
        self.redraw()

    def undo(self):
        if self.draft is not None and self.draft.history:
            self.draft.undo()
            self.edited()

    def reset(self):
        if self.draft is not None and self.draft.dirty:
            self.draft.reset()
            self.edited()

    def update_actions(self):
        draft = self.draft
        self.undo_button.setEnabled(bool(draft and draft.history))
        self.reset_button.setEnabled(bool(draft and draft.dirty))
        self.apply_button.setEnabled(bool(draft and draft.dirty))
        if draft is None:
            return
        own = [r["sample_id"] for r in self.window.records if r.get("compensation_path")]
        scope = (
            f"Edits apply to {len(self.window.records) - len(own)} of {len(self.window.records)} samples. "
            f"Sample-sheet matrices are kept and never show the edit: {', '.join(own)}. "
            if own
            else f"Edits apply to all {len(self.window.records)} samples (none has its own sample-sheet matrix). "
        )
        count = len(draft.changed_cells())
        state = (
            f"{count} edited value{'s' if count != 1 else ''} (shaded); the plots show the draft. "
            "Nothing changes until you apply. "
            if count
            else "Type a percent, or drag a population on a plot: down/left raises the spillover it subtracts. "
        )
        self.edit_note.setText(state + scope)

    def draft_for(self, record):
        """The draft spec for this sample, or None when it keeps its own matrix or nothing is edited."""
        if self.draft is None or not self.draft.dirty or record.get("compensation_path"):
            return None
        return self.draft.spec()

    def drag_start(self, event):
        ax = event.inaxes
        if event.button != 1 or ax is None or ax not in self.axes.values():
            self.pressed = None
            return
        self.pressed = (ax, event.x, event.y)

    def drag_end(self, event):
        if self.pressed is None:
            return
        ax, x, y = self.pressed
        self.pressed = None
        box = ax.bbox
        self.drag(ax, (event.x - x) / box.width, (event.y - y) / box.height)

    def drag(self, ax, dx, dy):
        """Nudge the spillover a drag on one plot corresponds to (dx, dy: axis fractions)."""
        if self.draft is None or max(abs(dx), abs(dy)) < MINIMUM_DRAG:
            return
        if self.record().get("compensation_path"):
            self.edit_note.setText("This sample keeps its sample-sheet matrix; preview a shared-matrix sample to edit.")
            return
        channels = next(k for k, v in self.axes.items() if v is ax)
        source, target, delta = drag_edit(channels, dx, dy)
        try:
            self.draft.nudge(source, target, delta)
        except ValueError as error:
            self.edit_note.setText(f"Not changed: {error}")
            return
        self.edited()

    def confirm_apply(self):
        draft = self.draft
        if draft is None or not draft.dirty:
            return
        lines = [
            f"{c['source']} → {c['target']}: {100 * c['from']:.3f}% → {100 * c['to']:.3f}%" for c in draft.changes()
        ]
        own = [r["sample_id"] for r in self.window.records if r.get("compensation_path")]
        detail = (
            "Changed spillover values:\n"
            + "\n".join(lines)
            + "\n\nApplying writes a new matrix file (the assigned matrix and its files are not changed), "
            "replaces the shared recipe matrix with it and resets every gate review. "
            + (
                f"These samples keep their sample-sheet matrix and are not affected: {', '.join(own)}. "
                if own
                else ""
            )
            + "Save the analysis to keep the change; Undo in the main window reverts it."
        )
        answer = W.QMessageBox.question(self, "Apply edited matrix", detail)
        if answer != W.QMessageBox.Yes:
            return
        folder = Path(self.window.state.path).parent
        default = folder / f"compensation-edited-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path, _ = W.QFileDialog.getSaveFileName(
            self, "New matrix file for the edited spillover", str(default), "Matrix JSON (*.json)",
            options=W.QFileDialog.DontConfirmOverwrite,
        )
        if path:
            self.apply_draft(path)

    def apply_draft(self, path):
        """Write the draft to a new file, then apply it through the wizard's path."""
        w = self.window
        try:
            if w.state.recipe["compensation"] != self.draft.base:
                raise ValueError("The recipe's matrix changed since editing began. Reset to start from it.")
            spec = save_edited_matrix(self.draft.spec(), path)
            w.apply_draft_matrix(spec)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.edit_note.setText(f"Matrix not applied: {error}")
            return False
        self.load_draft()
        self.redraw()
        self.edit_note.setText(
            f"Applied and saved as {Path(path).name}. Gate reviews were reset. Save the analysis to keep this change."
        )
        return True

    def redraw(self, *_):
        if not hasattr(self, "canvas"):
            return
        w = self.window
        try:
            record = self.record()
            prepared, masks = w.session.get(record, w.state.recipe)
            self.build_detector_menu(prepared)
            chosen = self.selected_channels()
            self.detectors.setText(
                "All detectors" if len(chosen) == len(self.channels) else f"{len(chosen)} of {len(self.channels)} detectors"
            )
            compensated = prepared.matrix is not None
            self.overlay.setEnabled(compensated)
            mask = masks[self.population.currentData()]
            draft = self.draft_for(record) if compensated else None
            self.axes = draw_compensation_matrix(
                self.canvas.figure,
                prepared,
                w.state.recipe,
                chosen,
                mask,
                self.overlay.isChecked(),
                getattr(w, "axis_ranges", {}),
                draft=draft,
            )
            shown = min(int(mask.sum()), DISPLAY_EVENTS)
            if draft is not None:
                text = (
                    f"DRAFT matrix with {len(self.draft.changed_cells())} edited value(s), compensated events in black"
                    f"{'; uncompensated (same events) in coral' if self.overlay.isChecked() else ''}. "
                    "Population membership still uses the assigned matrix until you apply. "
                )
                self.canvas.figure.suptitle("DRAFT spillover · not applied", color=CORAL, fontsize=10)
            elif compensated:
                source = (
                    f"this sample's sample-sheet file {Path(record['compensation_path']).name}, which edits do not change"
                    if record.get("compensation_path")
                    else "the shared recipe matrix"
                )
                text = (
                    f"Compensated events in black{'; uncompensated (same events) in coral' if self.overlay.isChecked() else ''}. "
                    f"Matrix: {len(prepared.matrix.detectors)} detectors from {source}. "
                )
            else:
                text = (
                    "No compensation is applied to this sample, so these are uncompensated detectors and the overlay "
                    "is unavailable. Agentflow never infers a matrix; assign one in Compensation. "
                )
            self.note.setText(
                text
                + f"Showing {shown:,} of {int(mask.sum()):,} events. Axes are fixed by each detector's range and "
                "transform, so they stay put between samples. ← / → or Page Up / Down flip samples."
            )
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.canvas.figure.clear()
            self.axes = {}
            self.note.setText(f"Sample not shown: {error}")
        self.canvas.draw_idle()
