"""Drawing an unfinished population without manufacturing membership."""

from matplotlib.widgets import RectangleSelector, SpanSelector

from .gate_selectors import GatePolygonSelector
from .plot_views import apply_axes, draw_events


class DraftEditor:
    def show_draft(self, name):
        draft = self.state.draft(name)
        self.stack.setCurrentIndex(0)
        self.title.setText(name)
        self.subtitle.setText(f"Parent: {draft['parent']} · Not drawn · Choose a tool above the plot")
        self.bounds_widget.hide()
        self.review_button.setEnabled(False)
        self.review_badge.setText("Not drawn")
        self.gate_type.setEnabled(not self.state.sample_scope)
        self.gate_type.setCurrentText(draft["kind"])
        self.add_point_button.setChecked(False)
        self.add_point_button.setEnabled(False)
        self.redraw_gate_button.setEnabled(True)
        channels = draft["channels"][:1] if draft["kind"] == "range" else draft["channels"]
        data = self.state.prepared.transformed.loc[self.state.masks()[draft["parent"]], channels].to_numpy()
        draw_events(self.ax, data, channels)
        apply_axes(self.ax, channels, self.state.recipe, ["recipe", "recipe"], self.state.prepared.sample)
        if draft["kind"] == "polygon":
            self.selector = GatePolygonSelector(self.ax, self.polygon, useblit=True, grab_range=15)
            self.help.setText(
                "Click vertices; double-click or click the first to finish. Escape cancels drawing."
            )
        elif draft["kind"] == "range":
            self.selector = SpanSelector(self.ax, self.span, "horizontal", useblit=True)
            self.help.setText("Drag an interval. Escape cancels drawing.")
        else:
            self.selector = RectangleSelector(self.ax, self.rectangle, useblit=True, button=[1])
            self.help.setText("Drag a rectangle. Switch Gate type at any time. Escape cancels drawing.")
        self.note.setText(
            "This population has no count until drawn. Analysis is blocked until it is drawn or deleted."
        )
        self.edit_mode()
        self.refresh()
        self.count.setText("—")
        self.percent.setText("Draw a gate to calculate counts")
        self.canvas.draw_idle()

    def finish_drawing(self, geometry):
        try:
            self.state.complete_draft(self.active_name, geometry)
            self.rebuild(self.active_name)
            self.message.setText(
                "Gate drawn · Review this population. Undo restores the unfinished population."
            )
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.message.setText(str(error))

    def cancel_drawing(self):
        if self.selector:
            self.show_gate(self.active_name)
            self.message.setText(
                "Drawing cancelled. Previous completed boundary restored; unfinished populations stay uncounted."
            )
