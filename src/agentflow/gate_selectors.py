"""Pointer behavior shared by the desktop and Matplotlib gate editors."""

import numpy as np
from matplotlib.path import Path
from matplotlib.widgets import PolygonSelector

POLYGON_HELP = (
    "Drag inside to move; drag vertices to reshape. Ctrl+click adds a vertex; "
    "right-click a vertex removes it. Esc starts a new polygon: click points, then the first to finish."
)


class GatePolygonSelector(PolygonSelector):
    """Add interior dragging and explicit insertion to Matplotlib's polygon tool.

    Coordinates remain in recipe space. Matplotlib owns handle hit testing,
    drawing, keyboard modifiers and completion callbacks.
    """

    def _press(self, event):
        self._interior_move = False
        self._insert_vertex = False
        if self._selection_completed and event.button == 1:
            keys = (event.key or "").split("+")
            if "control" in keys or "ctrl" in keys or "move_vertex" in self._state:
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
                points.insert(int(np.argmin(distance)) + 1, self._get_data_coords(event))
                self.verts = points
                self._insert_vertex = True
                return
        super()._press(event)
        if (
            self._selection_completed
            and event.button == 1
            and self._active_handle_idx < 0
            and "move_all" not in self._state
            and Path(self.verts).contains_point(self._get_data_coords(event))
        ):
            self._state.add("move_all")
            self._interior_move = True

    def _onmove(self, event):
        if not getattr(self, "_insert_vertex", False):
            super()._onmove(event)

    def _release(self, event):
        if getattr(self, "_insert_vertex", False):
            self._insert_vertex = False
            self.onselect(self.verts)
            return
        super()._release(event)
        if getattr(self, "_interior_move", False):
            self._state.discard("move_all")
            self._interior_move = False
