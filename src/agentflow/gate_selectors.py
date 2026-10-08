"""Pointer behavior shared by the desktop and Matplotlib gate editors."""

import numpy as np
from matplotlib.path import Path
from matplotlib.widgets import PolygonSelector

POLYGON_HELP = (
    "Drag inside to move; drag vertices to reshape. Ctrl+click adds a vertex; "
    "right-click a vertex removes it. Click points, then double-click or click the first to finish."
)


def _data_coords(ax, event):
    """*event*'s position in *ax*'s data coordinates, using public Matplotlib API only.

    Matplotlib 3.11 removed the private ``_SelectorWidget._get_data_coords`` this mirrors.
    ``event.xdata``/``ydata`` refer to ``event.inaxes``, which is not *ax* when Axes are
    overlaid, so then invert *ax*'s own transform. The common case avoids that round trip,
    which can add floating-point error to synthetic events.
    """
    if event.inaxes is ax:
        return (event.xdata, event.ydata)
    return tuple(ax.transData.inverted().transform((event.x, event.y)))


class GatePolygonSelector(PolygonSelector):
    """Add interior dragging and explicit insertion to Matplotlib's polygon tool.

    Coordinates remain in recipe space. Matplotlib owns handle hit testing,
    drawing, keyboard modifiers and completion callbacks.
    """

    insert_mode = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The editors own Escape ("cancel drawing" restores the last completed boundary).
        # Matplotlib's own Escape binding would then clear that restored polygon: on 3.10
        # its handler happened to raise before clearing, on 3.11 it completes. PolygonSelector
        # takes no state_modifier_keys argument, so unbind it here; "not-applicable" is
        # Matplotlib's own value for an unused modifier (same attribute in 3.10 and 3.11).
        self._state_modifier_keys["clear"] = "not-applicable"

    def _press(self, event):
        if event.dblclick and not self._selection_completed and event.button == 1:
            points = list(self.verts)
            point = _data_coords(self.ax, event)
            if not points or not np.allclose(points[-1], point):
                points.append(point)
            if len(points) >= 3:
                self.verts = points
                self._double_finished = True
                self.onselect(self.verts)
                return

        self._interior_move = False
        self._insert_vertex = False
        if self._selection_completed and event.button == 1:
            keys = (event.key or "").split("+")
            if self.insert_mode or "control" in keys or "ctrl" in keys or "move_vertex" in self._state:
                # Choose the nearest segment in screen pixels, including closing edge.
                vertices = np.asarray(self.verts)
                pixels = self.ax.transData.transform(vertices)
                start, end = pixels, np.roll(pixels, -1, axis=0)
                delta = end - start
                length = (delta * delta).sum(axis=1)
                fraction = np.clip(
                    ((np.array([event.x, event.y]) - start) * delta).sum(axis=1)
                    / np.maximum(length, np.finfo(float).eps),
                    0,
                    1,
                )
                distance = ((start + fraction[:, None] * delta - [event.x, event.y]) ** 2).sum(axis=1)
                points = list(self.verts)
                points.insert(int(np.argmin(distance)) + 1, _data_coords(self.ax, event))
                self.verts = points
                self._insert_vertex = True
                return
        super()._press(event)
        if (
            self._selection_completed
            and event.button == 1
            and self._active_handle_idx < 0
            and "move_all" not in self._state
            and Path(self.verts).contains_point(_data_coords(self.ax, event))
        ):
            self._state.add("move_all")
            self._interior_move = True

    def _onmove(self, event):
        if not getattr(self, "_insert_vertex", False):
            super()._onmove(event)

    def _release(self, event):
        if getattr(self, "_double_finished", False):
            self._double_finished = False
            return
        if getattr(self, "_insert_vertex", False):
            self._insert_vertex = False
            self.onselect(self.verts)
            return
        super()._release(event)
        if getattr(self, "_interior_move", False):
            self._state.discard("move_all")
            self._interior_move = False
