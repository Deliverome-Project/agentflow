"""Per-detector transform editor, like FlowJo's Customize Axis / transform dialog."""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6 import QtCore
from PySide6 import QtWidgets as W

from .channel_names import add_detector_choices, channel_label, select_detector
from .desktop import button, label
from .engine import evaluate, prepare
from .overrides import effective_recipe
from .plot_views import apply_axes, draw_boundary, draw_events, fixed_limits, plot_channels, set_limits
from .transform_edit import retransform
from .workflow import default_transform

KINDS = [("Linear", "linear"), ("Biexponential (logicle)", "logicle"), ("Arcsinh", "asinh")]
LOGICLE = [
    ("param_t", "T (top of scale)", 1.0, 1e12, 0),
    ("param_w", "W (linear width, decades)", 0.0, 5.0, 3),
    ("param_m", "M (decades)", 0.5, 10.0, 3),
    ("param_a", "A (extra negative decades)", -5.0, 5.0, 3),
]
W_NOTE = (
    "W widens or narrows the linear region around zero. Raise it when compensated "
    "negative events pile up against the bottom of the axis; lower it when the "
    "negative population looks artificially spread. FlowJo's default is 0.5."
)


class TransformDialog(W.QDialog):
    """Edit one detector's recipe transform; gates are migrated through raw signal on Apply."""

    def __init__(self, window, channel=None):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Detector transform")
        self.resize(1040, 600)
        state = window.state
        layout = W.QVBoxLayout(self)
        body = W.QHBoxLayout()
        controls = W.QVBoxLayout()
        form = self.form = W.QFormLayout()
        self.detector = W.QComboBox()
        add_detector_choices(self.detector, state.prepared.sample, state.recipe["transforms"])
        gate = state.gate(window.active_name)
        select_detector(self.detector, channel or (gate["channels"][0] if gate else None))
        form.addRow("Detector", self.detector)
        self.kind = W.QComboBox()
        for title, kind in KINDS:
            self.kind.addItem(title, kind)
        form.addRow("Transform", self.kind)
        self.spins = {}
        for key, title, low, high, decimals in LOGICLE:
            spin = W.QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(decimals)
            spin.setSingleStep(0.1 if decimals else 1000)
            spin.setKeyboardTracking(False)
            self.spins[key] = spin
            form.addRow(title, spin)
        self.cofactor = W.QDoubleSpinBox()
        self.cofactor.setRange(0.001, 1e9)
        self.cofactor.setDecimals(3)
        self.cofactor.setKeyboardTracking(False)
        form.addRow("Cofactor", self.cofactor)
        controls.addLayout(form)
        self.w_note = label(W_NOTE, "muted")
        self.w_note.setWordWrap(True)
        controls.addWidget(self.w_note)
        controls.addStretch()
        body.addLayout(controls, 2)
        self.figure = Figure(figsize=(5.6, 3.8), constrained_layout=True)
        self.ax = self.figure.add_subplot()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(420, 300)
        body.addWidget(self.canvas, 3)
        layout.addLayout(body, 1)
        self.table = W.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Population", "Gate", "Events (this sample)"])
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(170)
        layout.addWidget(self.table)
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = W.QHBoxLayout()
        actions.addWidget(button("Reset to FlowJo default", self.reset))
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject))
        self.apply_button = button("Apply", self.apply, True)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.timer = QtCore.QTimer(self, singleShot=True, interval=150)
        self.timer.timeout.connect(self.preview)
        self.detector.currentIndexChanged.connect(self.load)
        self.kind.currentIndexChanged.connect(self.changed)
        for spin in [*self.spins.values(), self.cofactor]:
            spin.valueChanged.connect(lambda *_: self.timer.start())
        self.load()

    @property
    def channel(self):
        return self.detector.currentData()

    def load(self, *_):
        self.show_spec(self.window.state.recipe["transforms"][self.channel])

    def reset(self):
        self.show_spec(default_transform(self.window.state.prepared.sample, self.channel))

    def show_spec(self, spec):
        widgets = [self.kind, *self.spins.values(), self.cofactor]
        for widget in widgets:
            widget.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(spec["kind"]))
        sample = self.window.state.prepared.sample
        logicle = spec.get("parameters") or default_transform(sample, self.channel).get("parameters")
        if logicle is None:  # Scatter defaults to linear; offer FlowJo's logicle values.
            top = float(sample.channels.iloc[sample.pnn_labels.index(self.channel)]["pnr"])
            logicle = {"param_t": top, "param_w": 0.5, "param_m": 4.5, "param_a": 0}
        for key, spin in self.spins.items():
            spin.setValue(float(logicle[key]))
        self.cofactor.setValue(float(spec.get("cofactor", 150)))
        for widget in widgets:
            widget.blockSignals(False)
        self.changed()

    def changed(self, *_):
        kind = self.kind.currentData()
        for spin in self.spins.values():
            spin.setEnabled(kind == "logicle")
            self.form.labelForField(spin).setEnabled(kind == "logicle")
        self.cofactor.setEnabled(kind == "asinh")
        self.w_note.setVisible(kind == "logicle")
        self.timer.start()

    def spec(self):
        kind = self.kind.currentData()
        if kind == "logicle":
            return {"kind": kind, "parameters": {k: float(s.value()) for k, s in self.spins.items()}}
        if kind == "asinh":
            return {"kind": kind, "cofactor": float(self.cofactor.value())}
        return {"kind": "linear"}

    def preview(self):
        """Show the current population on the new axis with migrated gates and count changes."""
        state = self.window.state
        self.ax.clear()
        self.table.setRowCount(0)
        try:
            candidate, migrated = retransform(state.recipe, self.channel, self.spec())
            effective = effective_recipe(candidate, state.sample_id)
            prepared = prepare(state.prepared.sample, effective)
            after = evaluate(prepared, effective, allow_unfinished=True)
        except (ValueError, TypeError, ZeroDivisionError) as error:
            self.status.setText(f"Not applicable: {error}")
            self.apply_button.setEnabled(False)
            self.canvas.draw_idle()
            return
        self.apply_button.setEnabled(True)
        before = state.counts()
        gate = next((g for g in effective["gates"] if g["name"] == self.window.active_name), None)
        if gate is not None and self.channel in plot_channels(gate, effective):
            channels, population = plot_channels(gate, effective), gate["parent"]
            shown = [g for g in effective["gates"] if g["name"] == gate["name"]]
        else:
            channels, population, shown = [self.channel], self.window.active_name, []
            population = population if population in after else "root"
        data = prepared.transformed.loc[after[population], channels].to_numpy()
        limits = fixed_limits(effective, channels, prepared.sample)
        bins = np.linspace(limits[0][0], limits[1][0], 101) if len(channels) == 1 else None
        draw_events(self.ax, data, channels, "density dots", bins=bins, limits=limits)
        set_limits(self.ax, limits, len(channels))
        apply_axes(self.ax, channels, effective, ["recipe"] * len(channels), prepared.sample)
        for g in shown:
            draw_boundary(self.ax, g, recipe=effective)
        self.ax.set_title(f"{population} · {len(data):,} events · {state.sample_id or 'this sample'}", fontsize=9)
        self.canvas.draw_idle()
        polygons = 0
        for name in migrated:
            kind = next(g["kind"] for g in candidate["gates"] if g["name"] == name)
            old, new = before.get(name), int(after[name].sum())
            row = self.table.rowCount()
            self.table.insertRow(row)
            change = "unchanged" if old == new else f"{new - old:+,}"
            for column, value in enumerate([name, kind, f"{old:,} → {new:,} ({change})"]):
                self.table.setItem(row, column, W.QTableWidgetItem(value))
            polygons += kind == "polygon"
        text = (
            f"{channel_label(state.prepared.sample, self.channel)}: {len(migrated)} gate(s) keep their "
            "signal boundaries; Apply clears their review and their descendants'. Shared by all samples."
        )
        if polygons:
            text += " Polygon edges are densified so they follow the same signal path; small count changes remain."
        self.status.setText(text)

    def apply(self):
        window = self.window
        try:
            window.flush_bounds()
            migrated = window.state.set_transform(self.channel, self.spec())
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText(f"Not applied: {error}")
            return
        self.accept()
        window.rebuild(window.active_name)
        window.message.setText(
            f"{self.channel} transform changed; {len(migrated)} gate(s) migrated and need review · Undo is available."
        )
