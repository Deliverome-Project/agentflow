"""Linked quadrant editing and side-by-side control/backgating views."""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtWidgets as W

from .channel_names import add_detector_choices, select_detector
from .desktop import button, label
from .engine import make_transform
from .plot_views import apply_axes, draw_boundary, draw_events, subset_indices


class QuadrantDialog(W.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Linked quadrants")
        form = W.QFormLayout(self)
        gate = window.state.gate(window.active_name)
        self.name = W.QLineEdit()
        self.x, self.y = W.QComboBox(), W.QComboBox()
        for combo in (self.x, self.y):
            add_detector_choices(combo, window.state.prepared.sample, window.state.recipe["transforms"])
        self.x_cut, self.y_cut = W.QDoubleSpinBox(), W.QDoubleSpinBox()
        for spin in (self.x_cut, self.y_cut):
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(8)
            spin.setSpecialValueText("Enter threshold")
            spin.setValue(spin.minimum())
        existing = bool(gate and gate["kind"] == "quadrant")
        if gate:
            select_detector(self.x, gate["channels"][0])
            select_detector(self.y, gate["channels"][-1])
        if self.x.currentData() == self.y.currentData() and self.y.count() > 1:
            self.y.setCurrentIndex((self.x.currentIndex() + 1) % self.y.count())
        if existing:
            self.name.setText(gate["quadrant_group"])
            for i, (combo, spin) in enumerate(((self.x, self.x_cut), (self.y, self.y_cut))):
                value = next(v for v in gate["bounds"][2 * i : 2 * i + 2] if v is not None)
                transform = make_transform(window.state.recipe["transforms"][combo.currentData()])
                raw = value if transform is None else float(transform.inverse(np.array([value]))[0])
                spin.setValue(raw)
            for control in (self.name, self.x, self.y):
                control.setEnabled(False)
        for title, field in (
            ("Population prefix", self.name),
            ("X detector", self.x),
            ("Y detector", self.y),
            ("X threshold (signal units)", self.x_cut),
            ("Y threshold (signal units)", self.y_cut),
        ):
            form.addRow(title, field)
        self.note = label(
            "Four linked populations: X−Y−, X+Y−, X−Y+, X+Y+. Threshold values belong to the positive side. "
            "Thresholds use signal units before display transforms, matching the axis labels; enter values based on your controls. "
            + ("Edits affect this sample." if window.state.sample_scope else "Edits affect all samples."),
            "muted",
        )
        self.note.setWordWrap(True)
        form.addRow(self.note)

        def apply():
            try:
                if any(spin.value() == spin.minimum() for spin in (self.x_cut, self.y_cut)):
                    raise ValueError("Enter both thresholds based on your controls.")
                thresholds = []
                for i, (combo, spin) in enumerate(((self.x, self.x_cut), (self.y, self.y_cut))):
                    transform = make_transform(window.state.recipe["transforms"][combo.currentData()])
                    value = (
                        spin.value()
                        if transform is None
                        else float(transform.apply(np.array([spin.value()]))[0])
                    )
                    if existing:
                        previous = next(v for v in gate["bounds"][2 * i : 2 * i + 2] if v is not None)
                        raw = (
                            previous
                            if transform is None
                            else float(transform.inverse(np.array([previous]))[0])
                        )
                        if spin.value() == round(raw, spin.decimals()):
                            value = previous
                    thresholds.append(value)
                if existing:
                    window.state.move_quadrants(gate["name"], *thresholds)
                    selected = gate["name"]
                else:
                    parent = gate["name"] if gate else "root"
                    window.state.quadrants(
                        self.name.text(),
                        parent,
                        [self.x.currentData(), self.y.currentData()],
                        *thresholds,
                    )
                    selected = self.name.text().strip() + " ++"
                window.rebuild(selected)
                self.accept()
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.note.setText(str(error))

        form.addRow(button("Apply linked thresholds" if existing else "Create four populations", apply, True))
        form.addRow(button("Cancel", self.reject))


class ComparisonDialog(W.QDialog):
    def __init__(self, window, backgate=False):
        super().__init__(window)
        self.window, self.backgate_mode = window, backgate
        self.setWindowTitle("Population on parent" if backgate else "Compare with control · linked axes")
        self.resize(960, 650)
        layout = W.QVBoxLayout(self)
        self.choice = W.QComboBox()
        for record in window.records:
            self.choice.addItem(
                f"{record['sample_id']} · {record.get('condition', record['group'])}", record["sample_id"]
            )
        pinned = next((r["sample_id"] for r in window.records if r["sample_id"] in window.pinned), None)
        if pinned:
            self.choice.setCurrentIndex(self.choice.findData(pinned))
        if not backgate:
            layout.addWidget(label("Choose a known control (its biological role is not inferred)", "muted"))
            layout.addWidget(self.choice)
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(9, 5), layout="constrained"))
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        if not backgate:
            layout.addWidget(button("Pin this reference", self.pin))
        layout.addWidget(button("Close", self.accept))
        self.choice.currentIndexChanged.connect(self.redraw)
        self.redraw()

    def pin(self):
        self.window.pinned.add(self.choice.currentData())
        self.window.redraw()
        self.note.setText("Reference pinned. Save the analysis to retain pinned references.")

    def redraw(self):
        w = self.window
        gate = w.state.gate(w.active_name)
        channels = w.display_channels(gate)
        self.canvas.figure.clear()
        records = (
            [w.record]
            if self.backgate_mode
            else [w.record, next(r for r in w.records if r["sample_id"] == self.choice.currentData())]
        )
        axes, arrays = [], []
        try:
            for i, record in enumerate(records):
                prepared, masks = w.session.get(record, w.state.recipe)
                ax = self.canvas.figure.add_subplot(
                    1, len(records), i + 1, sharex=axes[0] if axes else None, sharey=axes[0] if axes else None
                )
                axes.append(ax)
                data = prepared.transformed.loc[masks[gate["parent"]], channels].to_numpy()
                arrays.append(data)
                draw_events(
                    ax, data, channels, "scatter" if self.backgate_mode else "density dots", color="#b0b0b0"
                )
                if self.backgate_mode:
                    chosen = prepared.transformed.loc[masks[gate["name"]], channels].to_numpy()
                    if len(channels) == 2:
                        chosen = chosen[subset_indices(len(chosen))]
                        ax.scatter(chosen[:, 0], chosen[:, 1], s=10, color="#922038", label=gate["name"])
                        ax.legend()
                    else:
                        draw_events(ax, chosen, channels, name=gate["name"])
                from .overrides import effective_recipe

                effective = effective_recipe(w.state.recipe, record["sample_id"])
                actual = next(g for g in effective["gates"] if g["name"] == gate["name"])
                if channels == actual["channels"] or (
                    actual["kind"] == "range" and channels[0] == actual["channels"][0]
                ):
                    draw_boundary(ax, actual, recipe=effective)
                apply_axes(ax, channels, effective, ["recipe", "recipe"], sample=prepared.sample)
                ax.set_title(
                    f"{record['sample_id']} · {int(masks[gate['name']].sum()):,} selected / {len(data):,} parent"
                )
            nonempty = [a for a in arrays if len(a)]
            if nonempty:
                combined = np.concatenate(nonempty)
                lo, hi = combined.min(axis=0), combined.max(axis=0)
                padding = np.maximum((hi - lo) * 0.04, 0.001)
                axes[0].set_xlim(lo[0] - padding[0], hi[0] + padding[0])
                if len(channels) == 2:
                    axes[0].set_ylim(lo[1] - padding[1], hi[1] + padding[1])
            self.note.setText(
                "Read-only comparison. Zoom/pan is linked. Counts use all events; dots are display samples. "
                "Each sample retains its own compensation and gate exceptions."
            )
        except (ValueError, KeyError, OSError) as error:
            self.note.setText(f"Comparison unavailable: {error}")
        self.canvas.draw_idle()
