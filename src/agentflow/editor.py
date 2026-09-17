"""Matplotlib workflow editor; every gate preview uses the batch engine."""

import copy
from pathlib import Path

import numpy as np

from .compensation import load_matrix
from .engine import digest, evaluate, prepare, save_recipe, validate
from .gate_selectors import POLYGON_HELP, GatePolygonSelector
from .plots import draw_population
from .workflow import ROLES, add_reporter, mark_unreviewed


class GateEditor:
    """Edit one gate or a complete workflow. Disk is changed only by Save & Close."""

    def __init__(self, prepared, recipe, name, path):
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, RadioButtons, TextBox

        self.plt = plt
        self.recipe = copy.deepcopy(recipe)
        self.prepared = prepared
        self.path = Path(path)
        self.original_hash = digest(path) if self.path.exists() else None
        self.saved = False
        self.history = []
        self.future = []
        self.widgets = []
        self.selector = None
        self.fig = plt.figure(figsize=(13, 8), facecolor="white")
        self.fig.canvas.manager.set_window_title("Agentflow — gate review")
        self.ax = self.fig.add_axes([0.29, 0.29, 0.67, 0.56])
        title = recipe.get("experiment", {}).get("label", "Agentflow gate editor")
        self.fig.text(
            0.035,
            0.96,
            title,
            fontsize=16,
            weight="bold",
            color="#865800" if recipe.get("experiment", {}).get("is_example") else "#16313b",
        )
        self.heading = self.fig.text(0.29, 0.90, "", fontsize=13)
        self.status = self.fig.text(0.29, 0.22, "", fontsize=11)
        self.detail = self.fig.text(0.29, 0.18, "", fontsize=9)
        self.comp_status = self.fig.text(0.035, 0.10, "", fontsize=9)
        self.fig.text(
            0.29, 0.135, "Drag handles / span to edit. Close window = cancel all unsaved changes.", fontsize=9
        )
        self.save_button = Button(self.fig.add_axes([0.69, 0.025, 0.17, 0.05]), "Save & Close")
        self.cancel_button = Button(self.fig.add_axes([0.88, 0.025, 0.08, 0.05]), "Cancel")
        self.save_button.on_clicked(self.save)
        self.cancel_button.on_clicked(lambda _: plt.close(self.fig))
        self.undo_button = Button(self.fig.add_axes([0.29, 0.025, 0.08, 0.05]), "Undo")
        self.redo_button = Button(self.fig.add_axes([0.38, 0.025, 0.08, 0.05]), "Redo")
        self.review_button = Button(self.fig.add_axes([0.48, 0.025, 0.18, 0.05]), "Mark gate reviewed")
        self.undo_button.on_clicked(self.undo)
        self.redo_button.on_clicked(self.redo)
        self.review_button.on_clicked(self.review)
        self.matrix_box = TextBox(self.fig.add_axes([0.035, 0.19, 0.19, 0.04]), "", initial="")
        self.fig.text(0.035, 0.24, "Compensation matrix file", fontsize=9)
        self.matrix_button = Button(self.fig.add_axes([0.035, 0.135, 0.19, 0.04]), "Load compensation")
        self.matrix_button.on_clicked(self.apply_matrix)
        self._radio_class = RadioButtons
        self.radio = None
        self._build_gate_list(name)

    def _build_gate_list(self, name=None):
        if self.radio is not None:
            self.radio.disconnect_events()
            self.radio.ax.remove()
        actual = [g["name"] for g in self.recipe["gates"]]
        pending = [p["name"] for p in self.recipe.get("pending_gates", [])]
        order = ["cells", "singlets", *ROLES]
        self.names = [n for n in order if n in actual + pending] + [
            n for n in actual + pending if n not in order
        ]
        if not self.names:
            raise ValueError("Recipe has no gates to edit")
        selected = name if name in self.names else self.names[0]
        self.radio = self._radio_class(
            self.fig.add_axes([0.025, 0.37, 0.21, 0.46]), self.names, active=self.names.index(selected)
        )
        self.radio.on_clicked(self.select_gate)
        self.select_gate(selected)

    def _remember(self):
        self.history.append(copy.deepcopy(self.recipe))
        self.future.clear()

    def select_gate(self, name):
        from matplotlib.widgets import Button, RectangleSelector, SpanSelector, TextBox

        if self.radio is not None and self.radio.value_selected != name:
            self.radio.eventson = False
            self.radio.set_active(self.names.index(name))
            self.radio.eventson = True
        if self.selector is not None:
            self.selector.disconnect_events()
        self.selector = None
        for widget in self.widgets:
            widget.disconnect_events()
            widget.ax.remove()
        self.widgets = []
        self.ax.clear()
        self.active_name = name
        self.gate = next((g for g in self.recipe["gates"] if g["name"] == name), None)
        self.comp_status.set_text("Compensation: " + self.recipe["compensation"]["mode"])
        if self.prepared.matrix is not None and np.allclose(
            self.prepared.matrix.matrix, np.eye(len(self.prepared.matrix.detectors))
        ):
            self.comp_status.set_text(self.comp_status.get_text() + "\nIdentity matrix: no correction")
        if self.gate is None:
            pending = next(p for p in self.recipe["pending_gates"] if p["name"] == name)
            self.heading.set_text(pending["label"] + " — UNMAPPED / NOT ANALYZED")
            channels = [self.prepared.sample.pnn_labels[i] for i in self.prepared.sample.fluoro_indices]
            self.ax.text(
                0.03,
                0.7,
                pending["reason"] + "\n\nAvailable fluorescence detectors:\n" + ", ".join(channels),
                transform=self.ax.transAxes,
                wrap=True,
            )
            self.ax.set_axis_off()
            self.status.set_text("This step contributes no gate or population count.")
            self.detail.set_text("Map only a detector actually acquired with the intended dye.")
            if name in ROLES:
                self.channel_box = TextBox(
                    self.fig.add_axes([0.39, 0.38, 0.23, 0.05]), "Detector ", initial=""
                )
                button = Button(
                    self.fig.add_axes([0.65, 0.38, 0.25, 0.05]), "Assign detector / add draft gate"
                )
                button.on_clicked(self.assign_detector)
                self.widgets.extend([self.channel_box, button])
            self.fig.canvas.draw_idle()
            return
        self.ax.set_axis_on()
        parent = evaluate(self.prepared, self.recipe)[self.gate["parent"]]
        draw_population(self.ax, self.prepared, self.gate, parent)
        x = self.gate["channels"][0]
        self.ax.set_xlabel(f"{x} ({self.recipe['transforms'][x]['kind']})")
        if len(self.gate["channels"]) == 2:
            y = self.gate["channels"][1]
            self.ax.set_ylabel(f"{y} ({self.recipe['transforms'][y]['kind']})")
        self.heading.set_text(f"{self.gate.get('label', name)} | parent: {self.gate['parent']}")
        self.detail.set_text(
            self.gate.get("note", "Fixed transformed coordinates; previews count all events.")
        )
        kind = self.gate["kind"]
        if kind == "polygon":
            self.ax.update_datalim(self.gate["vertices"])
            self.ax.autoscale_view()
            self.selector = GatePolygonSelector(self.ax, self.polygon_changed, useblit=True)
            self.selector.verts = self.gate["vertices"]
            self.detail.set_text(POLYGON_HELP)
        elif kind == "rectangle":
            x0, x1, y0, y1 = self.gate["bounds"]
            self.ax.update_datalim([[x0, y0], [x1, y1]])
            self.ax.autoscale_view()
            left, right = self.ax.get_xlim()
            bottom, top = self.ax.get_ylim()
            self.ax.set_xlim(min(0, left), right)
            self.ax.set_ylim(min(0, bottom), top)
            self.selector = RectangleSelector(
                self.ax,
                self.rectangle_changed,
                interactive=True,
                useblit=True,
                button=[1],
                drag_from_anywhere=True,
            )
            self.selector.extents = self.gate["bounds"]
        else:
            for bound in self.gate["bounds"]:
                if bound is not None:
                    self.ax.update_datalim([[bound, 0]])
            self.ax.autoscale_view()
            low, high = self.gate["bounds"]
            xmin, xmax = self.ax.get_xlim()
            self.selector = SpanSelector(
                self.ax,
                self.range_changed,
                "horizontal",
                interactive=True,
                useblit=True,
                props={"facecolor": "#d69728", "alpha": 0.25},
                drag_from_anywhere=True,
            )
            self.selector.extents = (xmin if low is None else low, xmax if high is None else high)
            self.lower_box = TextBox(
                self.fig.add_axes([0.40, 0.09, 0.16, 0.035]),
                "Lower ",
                initial="none" if low is None else f"{low:.8g}",
            )
            self.upper_box = TextBox(
                self.fig.add_axes([0.68, 0.09, 0.16, 0.035]),
                "Upper ",
                initial="none" if high is None else f"{high:.8g}",
            )
            apply = Button(self.fig.add_axes([0.86, 0.09, 0.10, 0.035]), "Set bounds")
            apply.on_clicked(self.set_bounds)
            self.widgets.extend([self.lower_box, self.upper_box, apply])
        self.refresh()

    def polygon_changed(self, vertices):
        self._remember()
        self.gate["vertices"] = [[float(x), float(y)] for x, y in vertices]
        mark_unreviewed(self.recipe, self.gate["name"])
        self.refresh()

    def rectangle_changed(self, press=None, release=None):
        self._remember()
        self.gate["bounds"] = [float(v) for v in self.selector.extents]
        mark_unreviewed(self.recipe, self.gate["name"])
        self.refresh()

    def range_changed(self, low, high):
        self._remember()
        self.gate["bounds"] = [float(low), float(high)]
        mark_unreviewed(self.recipe, self.gate["name"])
        self.lower_box.set_val(f"{low:.8g}")
        self.upper_box.set_val(f"{high:.8g}")
        self.refresh()

    def set_bounds(self, _=None):
        try:

            def number(text):
                return None if text.strip().lower() in ("none", "null", "") else float(text)

            candidate = copy.deepcopy(self.recipe)
            gate = next(g for g in candidate["gates"] if g["name"] == self.active_name)
            gate["bounds"] = [number(self.lower_box.text), number(self.upper_box.text)]
            validate(candidate)
            self._remember()
            self.recipe = candidate
            mark_unreviewed(self.recipe, self.active_name)
            self.select_gate(self.active_name)
        except (ValueError, TypeError) as error:
            self.status.set_text(str(error))
            self.fig.canvas.draw_idle()

    def refresh(self):
        try:
            validate(self.recipe)
            masks = evaluate(self.prepared, self.recipe)
            count = int(masks[self.gate["name"]].sum())
            parent = int(masks[self.gate["parent"]].sum())
            pct = f"{100 * count / parent:.2f}%" if parent else "undefined"
            self.status.set_text(
                f"{count:,} / {parent:,} parent events ({pct}) — {'REVIEWED' if self.gate.get('reviewed') else 'DRAFT'}"
            )
        except ValueError as error:
            self.status.set_text(str(error))
        self.fig.canvas.draw_idle()

    def review(self, _=None):
        if self.gate is None:
            return
        self._remember()
        self.gate["reviewed"] = True
        self.refresh()

    def assign_detector(self, _=None):
        try:
            candidate = add_reporter(
                self.recipe,
                self.prepared.sample,
                self.active_name,
                self.channel_box.text.strip(),
                confirmed=True,
            )
            self._remember()
            self.recipe = candidate
            self.prepared = prepare(self.prepared.sample, self.recipe)
            self._build_gate_list(self.active_name)
        except (ValueError, KeyError) as error:
            self.status.set_text(str(error))
            self.fig.canvas.draw_idle()

    def apply_matrix(self, _=None):
        try:
            candidate = copy.deepcopy(self.recipe)
            candidate["compensation"] = load_matrix(Path(self.matrix_box.text).expanduser())
            prepared = prepare(self.prepared.sample, candidate)
            self._remember()
            self.recipe = candidate
            self.prepared = prepared
            mark_unreviewed(self.recipe)
            self.select_gate(self.active_name)
            self.status.set_text("Matrix loaded. All gates need review in the new compensated space.")
        except (ValueError, KeyError, OSError, TypeError) as error:
            # prepare may have changed sample compensation before failing.
            self.prepared = prepare(self.prepared.sample, self.recipe)
            self.status.set_text(str(error))
            self.fig.canvas.draw_idle()

    def undo(self, _=None):
        if not self.history:
            return
        self.future.append(copy.deepcopy(self.recipe))
        self.recipe = self.history.pop()
        self.prepared = prepare(self.prepared.sample, self.recipe)
        self._build_gate_list(self.active_name)

    def redo(self, _=None):
        if not self.future:
            return
        self.history.append(copy.deepcopy(self.recipe))
        self.recipe = self.future.pop()
        self.prepared = prepare(self.prepared.sample, self.recipe)
        self._build_gate_list(self.active_name)

    def save(self, _=None):
        try:
            # Public selector properties capture mouse edits; untouched range
            # bounds retain null/unbounded endpoints rather than clipping them.
            if self.gate is not None and self.selector is not None:
                key = "vertices" if self.gate["kind"] == "polygon" else "bounds"
                if self.gate["kind"] == "polygon":
                    value = [list(point) for point in self.selector.verts]
                elif self.gate["kind"] == "rectangle":
                    value = list(self.selector.extents)
                else:
                    value = self.gate["bounds"]
                if value != self.gate[key]:
                    mark_unreviewed(self.recipe, self.gate["name"])
                self.gate[key] = value
            current = digest(self.path) if self.path.exists() else None
            if current != self.original_hash:
                raise ValueError("Recipe changed on disk. Cancel and reopen to avoid losing edits.")
            save_recipe(self.path, self.recipe)
            self.saved = True
            self.plt.close(self.fig)
        except (ValueError, OSError, TypeError) as error:
            self.status.set_text(f"Not saved: {error}")
            self.fig.canvas.draw_idle()
