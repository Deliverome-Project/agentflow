"""Flip through samples on the N×N compensation check, as in FlowJo's matrix editor."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .channel_names import channel_label
from .compensation_view import DISPLAY_EVENTS, draw_compensation_matrix, matrix_channels
from .desktop import button, label


class CompensationMatrixDialog(W.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Compensation matrix check")
        self.resize(980, 820)
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
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(8, 7), facecolor="white", layout="constrained"))
        layout.addWidget(self.canvas, 1)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addWidget(button("Close", self.accept))
        for keys, delta in [((QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown), 1), ((QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp), -1)]:
            for key in keys:
                shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
                shortcut.activated.connect(lambda d=delta: self.step(d))
        self.axes = {}
        self.channels = []
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

    def redraw(self, *_):
        if not hasattr(self, "canvas"):
            return
        w = self.window
        try:
            prepared, masks = w.session.get(self.record(), w.state.recipe)
            self.build_detector_menu(prepared)
            chosen = self.selected_channels()
            self.detectors.setText(
                "All detectors" if len(chosen) == len(self.channels) else f"{len(chosen)} of {len(self.channels)} detectors"
            )
            compensated = prepared.matrix is not None
            self.overlay.setEnabled(compensated)
            mask = masks[self.population.currentData()]
            self.axes = draw_compensation_matrix(
                self.canvas.figure,
                prepared,
                w.state.recipe,
                chosen,
                mask,
                self.overlay.isChecked(),
                getattr(w, "axis_ranges", {}),
            )
            shown = min(int(mask.sum()), DISPLAY_EVENTS)
            if compensated:
                text = (
                    f"Compensated events in black{'; uncompensated (same events) in coral' if self.overlay.isChecked() else ''}. "
                    f"Matrix: {len(prepared.matrix.detectors)} detectors from this sample's recipe. "
                )
            else:
                text = (
                    "No compensation is applied to this sample, so these are uncompensated detectors and the overlay "
                    "is unavailable. Agentflow never infers a matrix; assign one in Compensation. "
                )
            self.note.setText(
                text
                + f"Showing {shown:,} of {int(mask.sum()):,} events. Axes are fixed by each detector's range and "
                "transform, so they stay put between samples. ← / → or Page Up / Down flip samples. Display only."
            )
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.canvas.figure.clear()
            self.axes = {}
            self.note.setText(f"Sample not shown: {error}")
        self.canvas.draw_idle()
