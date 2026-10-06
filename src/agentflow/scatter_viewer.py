"""Explore a population on arbitrary detector axes without creating a gate."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtWidgets as W

from .channel_names import add_detector_choices, select_detector
from .desktop import button, label
from .plot_views import apply_axes, draw_events


class ScatterDialog(W.QDialog):
    def __init__(self, workbench):
        super().__init__(workbench)
        self.workbench = workbench
        self.setWindowTitle("Explore scatterplot · " + workbench.record["sample_id"])
        self.resize(760, 600)
        layout = W.QVBoxLayout(self)
        form = W.QFormLayout()
        self.population, self.x, self.y, self.style = [W.QComboBox() for _ in range(4)]
        self.population.addItems(["root"] + [g["name"] for g in workbench.state.recipe["gates"]])
        self.population.setCurrentText(workbench.active_name)
        channels = list(workbench.state.recipe["transforms"])
        for combo in (self.x, self.y):
            add_detector_choices(combo, workbench.state.prepared.sample, channels)
        roles = workbench.state.recipe.get("channel_roles", {})
        for combo, role, fallback in [(self.x, "gfp", channels[0]), (self.y, "cy5", channels[-1])]:
            select_detector(combo, roles.get(role, {}).get("detector", fallback))
        self.style.addItems(["Density dots", "Scatter", "Density", "Contour"])
        for title, widget in [
            ("Population", self.population),
            ("X detector", self.x),
            ("Y detector", self.y),
            ("Show as", self.style),
        ]:
            form.addRow(title, widget)
            widget.currentIndexChanged.connect(self.redraw)
        layout.addLayout(form)
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(6, 4), layout="constrained"))
        self.ax = self.canvas.figure.add_subplot()
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)
        self.count = label("")
        layout.addWidget(self.count)
        layout.addWidget(label("Axes use the recipe transforms. Exploring does not change gates.", "muted"))
        actions = W.QHBoxLayout()
        actions.addWidget(button("Create subpopulation on these axes…", self.create_population, True))
        actions.addWidget(button("Close", self.accept))
        layout.addLayout(actions)
        self.redraw()

    def redraw(self):
        if not hasattr(self, "canvas"):
            return
        w = self.workbench
        prepared, masks = w.session.get(w.record, w.state.recipe)
        channels = [self.x.currentData(), self.y.currentData()]
        data = prepared.transformed.loc[masks[self.population.currentText()], channels].to_numpy()
        self.ax.clear()
        draw_events(self.ax, data, channels, self.style.currentText().lower(), w.record["color"])
        apply_axes(self.ax, channels, w.state.recipe, ["recipe", "recipe"], sample=prepared.sample)
        self.count.setText(
            f"{len(data):,} events in {self.population.currentText()} · scatter displays up to 20,000"
        )
        self.canvas.draw_idle()

    def create_population(self):
        self.workbench.new_population(
            "rectangle", [self.x.currentData(), self.y.currentData()], self.population.currentText()
        )
