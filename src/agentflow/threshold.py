"""One movable boundary for one-sided histogram gates."""

from matplotlib.widgets import AxesWidget


class ThresholdSelector(AxesWidget):
    def __init__(self, ax, value, below, callback, color):
        super().__init__(ax)
        self.value, self.below, self.callback = value, below, callback
        self.dragging = False
        self.line = ax.axvline(value, color=color, linewidth=2.5)
        left, right = ax.get_xlim()
        self.shade = ax.axvspan(left if below else value, value if below else right, color=color, alpha=0.1)
        self.connect_event("button_press_event", self.press)
        self.connect_event("motion_notify_event", self.move)
        self.connect_event("button_release_event", self.release)

    def set_visible(self, visible):
        self.line.set_visible(visible)
        self.shade.set_visible(visible)

    def update(self, value):
        self.value = float(value)
        self.line.set_xdata([value, value])
        left, right = self.ax.get_xlim()
        self.shade.set_x(left if self.below else value)
        self.shade.set_width(value - left if self.below else right - value)
        self.canvas.draw_idle()

    def press(self, event):
        if self.ignore(event) or event.button != 1 or event.inaxes != self.ax:
            return
        if not self.canvas.widgetlock.available(self):
            return
        self.dragging = True
        self.update(event.xdata)

    def move(self, event):
        if self.dragging and not self.ignore(event) and event.inaxes == self.ax:
            self.update(event.xdata)

    def release(self, event):
        if not self.dragging:
            return
        self.dragging = False
        if self.ignore(event):
            return
        if event.inaxes == self.ax:
            self.update(event.xdata)
        self.callback(self.value, self.value)
