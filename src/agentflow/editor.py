"""Optional Matplotlib gate editor. Coordinates match the batch engine."""

import copy
from pathlib import Path

from .engine import digest, evaluate, save_recipe, validate


class GateEditor:
    """Edit one named gate; all other gates remain in the same recipe."""

    def __init__(self, prepared, recipe, name, path):
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, PolygonSelector, RectangleSelector

        self.recipe = copy.deepcopy(recipe)
        self.gate = next(g for g in self.recipe["gates"] if g["name"] == name)
        self.path = Path(path)
        self.original_hash = digest(path) if self.path.exists() else None
        self.prepared = prepared
        frame = prepared.transformed
        self.saved = False
        self.plt = plt
        self.fig, self.ax = plt.subplots(figsize=(9, 7), facecolor="white")
        self.fig.subplots_adjust(bottom=0.23, top=0.90)
        self.ax.set_facecolor("white")
        parent = evaluate(prepared, recipe)[self.gate["parent"]]
        x, y = self.gate["channels"]
        data = frame.loc[parent, [x, y]].to_numpy()
        if not len(data):
            plt.close(self.fig)
            raise ValueError("Parent gate contains no events; edit the parent first")
        self.ax.hexbin(data[:, 0], data[:, 1], gridsize=100, mincnt=1, bins="log", cmap="viridis")
        for axis, channel in [("x", x), ("y", y)]:
            getattr(self.ax, f"set_{axis}label")(
                f"{channel} ({recipe['transforms'][channel]['kind']} coordinates)"
            )
        self.fig.text(0.12, 0.95, f"Edit {name}  |  Parent: {self.gate['parent']}", fontsize=14)
        self.status = self.fig.text(0.12, 0.14, "")
        self.fig.text(
            0.12,
            0.10,
            "Drag handles to adjust. Save & Close accepts; closing the window cancels.",
            fontsize=10,
        )
        # Set limits before restoring selectors: Matplotlib clips rectangle
        # extents to the current view, which could otherwise alter saved gates.
        if self.gate["kind"] == "polygon":
            self.ax.update_datalim(self.gate["vertices"])
        else:
            x0, x1, y0, y1 = self.gate["bounds"]
            self.ax.update_datalim([[x0, y0], [x1, y1]])
        self.ax.autoscale_view()
        if self.gate["kind"] == "polygon":
            self.selector = PolygonSelector(self.ax, self.polygon_changed, useblit=True)
            self.selector.verts = self.gate["vertices"]
            self.ax.update_datalim(self.gate["vertices"])
        else:
            self.selector = RectangleSelector(
                self.ax, self.rectangle_changed, interactive=True, useblit=True, button=[1]
            )
            self.selector.extents = self.gate["bounds"]
            x0, x1, y0, y1 = self.gate["bounds"]
            self.ax.update_datalim([[x0, y0], [x1, y1]])
        self.ax.autoscale_view()
        self.save_button = Button(self.fig.add_axes((0.58, 0.025, 0.20, 0.05)), "Save & Close")
        self.cancel_button = Button(self.fig.add_axes((0.80, 0.025, 0.12, 0.05)), "Cancel")
        self.save_button.on_clicked(self.save)
        self.cancel_button.on_clicked(lambda _: plt.close(self.fig))
        self.refresh()

    def polygon_changed(self, vertices):
        self.gate["vertices"] = [[float(x), float(y)] for x, y in vertices]
        self.refresh()

    def rectangle_changed(self, press, release):
        self.gate["bounds"] = [float(v) for v in self.selector.extents]
        self.refresh()

    def refresh(self):
        try:
            validate(self.recipe)
            masks = evaluate(self.prepared, self.recipe)
            count = int(masks[self.gate["name"]].sum())
            parent = int(masks[self.gate["parent"]].sum())
            self.status.set_text(
                f"{count:,} / {parent:,} parent events ({100 * count / parent:.2f}%) — all events"
            )
        except ValueError as error:
            self.status.set_text(str(error))
        self.fig.canvas.draw_idle()

    def save(self, _=None):
        try:
            if self.gate["kind"] == "polygon":
                self.gate["vertices"] = [list(point) for point in self.selector.verts]
            else:
                self.gate["bounds"] = list(self.selector.extents)
            current = digest(self.path) if self.path.exists() else None
            if current != self.original_hash:
                raise ValueError("Recipe changed on disk. Cancel and reopen to avoid losing edits.")
            save_recipe(self.path, self.recipe)
            self.saved = True
            self.plt.close(self.fig)
        except (ValueError, OSError) as error:
            self.status.set_text(f"Not saved: {error}")
            self.fig.canvas.draw_idle()
