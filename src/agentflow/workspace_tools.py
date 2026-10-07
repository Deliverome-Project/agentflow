"""Discoverable workspace actions, navigation and recovery UI."""

import copy
import html

from PySide6 import QtCore
from PySide6 import QtWidgets as W

from .channel_names import channel_label


class WorkspaceTools:
    def init_workspace_tools(self):
        self.view_channels = copy.deepcopy(self.state.recipe.get("display", {}).get("view_channels", {}))
        self.breadcrumbs = self.subtitle
        self.breadcrumbs.setTextFormat(QtCore.Qt.RichText)
        self.breadcrumbs.setTextInteractionFlags(
            QtCore.Qt.LinksAccessibleByMouse | QtCore.Qt.LinksAccessibleByKeyboard
        )
        self.breadcrumbs.setOpenExternalLinks(False)
        self.breadcrumbs.linkActivated.connect(lambda index: self.gates.setCurrentRow(int(index)))
        self.gates.itemDoubleClicked.connect(lambda *_: self.explore_population())
        self.sample_choice.setEditable(True)
        self.sample_choice.setInsertPolicy(W.QComboBox.NoInsert)
        self.sample_choice.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.sample_choice.completer().setCompletionMode(W.QCompleter.PopupCompletion)
        for i, record in enumerate(self.records):
            text = " · ".join(
                dict.fromkeys(
                    str(record[k])
                    for k in ("sample_id", "condition", "group", "plate", "well")
                    if record.get(k)
                )
            )
            self.sample_choice.setItemText(i, text)
        menu = W.QMenu(self)
        menu.addAction(
            "Drawing instructions", lambda: W.QMessageBox.information(self, "Drawing", self.help.text())
        )
        menu.addAction("Return to gating axes", self.gating_axes)
        menu.addAction("Quadrants…", self.quadrant_dialog)
        menu.addAction("Compare with control…", self.compare_control)
        menu.addAction("Highlight population on parent…", self.backgate)
        menu.addAction("Browse and review samples…", self.sample_browser)
        menu.addSeparator()
        menu.addAction("Save checkpoint…", self.save_checkpoint)
        menu.addAction("Restore checkpoint…", self.restore_checkpoint)
        menu.addAction("Recover unsaved changes…", self.recover_changes)
        menu.addAction("Discard recovery copy…", self.discard_recovery)
        # Replace the compact help button with one small, labeled tools menu.
        self.gate_help_button.clicked.disconnect()
        self.gate_help_button.setText("Tools")
        self.gate_help_button.setFixedWidth(80)
        self.gate_help_button.setMenu(menu)
        self.gate_help_button.setAccessibleName("Population tools")
        self.analysis_menu.addMenu(menu).setText("Population tools")
        self.scope_badge = self.review_badge
        self.canvas.mpl_connect("pick_event", self.axis_picked)
        self.canvas.mpl_connect("button_press_event", self.drill_plot)
        self.show_gate(self.active_name)
        if self.state.recovery_pending:
            self.message.setText(
                "Unsaved work is available. Tools → Recover unsaved changes, or discard the recovery copy."
            )

    def update_breadcrumbs(self):
        gate = self.state.gate(self.active_name) or self.state.draft(self.active_name)
        if not gate:
            return
        lineage = [gate]
        while lineage[-1]["parent"] != "root":
            lineage.append(self.state.gate(lineage[-1]["parent"]))
        links = [
            f'<a href="{self.names.index(g["name"])}">{html.escape(self.population_title(g["name"]))}</a>'
            if g["name"] in self.names
            else html.escape(self.population_title(g["name"]))
            for g in reversed(lineage)
        ]
        self.breadcrumbs.setText("All events › " + " › ".join(links))
        self.update_scope_badge()
        self.ax.xaxis.label.set_picker(8)
        self.ax.yaxis.label.set_picker(8)
        gate = self.state.gate(self.active_name)
        if gate:
            self.ax.xaxis.label.set_text(self.ax.xaxis.label.get_text() + " (change)")
            if len(self.display_channels(gate)) == 2:
                self.ax.yaxis.label.set_text(self.ax.yaxis.label.get_text() + " (change)")

    def update_scope_badge(self):
        gate = self.state.gate(self.active_name)
        status = (
            "Not drawn"
            if self.state.draft(self.active_name)
            else "Reviewed"
            if gate and gate.get("reviewed")
            else "Draft"
        )
        scope = "this sample" if self.state.sample_scope else f"{len(self.records)} samples"
        self.scope_badge.setText(f"{status} · Editing {scope}")

    def axis_picked(self, event):
        if event.artist not in (self.ax.xaxis.label, self.ax.yaxis.label):
            return
        gate = self.state.gate(self.active_name)
        if gate is None:
            self.message.setText("Finish drawing before exploring different axes.")
            return
        channels = list(self.display_channels(gate))
        index = 0 if event.artist is self.ax.xaxis.label else 1
        if index >= len(channels):
            return
        detectors = list(self.state.recipe["transforms"])
        labels = [channel_label(self.state.prepared.sample, c) for c in detectors]
        choice, ok = W.QInputDialog.getItem(
            self,
            "Display detector",
            "Explore on detector (gate stays unchanged)",
            labels,
            detectors.index(channels[index]),
            False,
        )
        if not ok:
            return
        channels[index] = detectors[labels.index(choice)]
        if len(set(channels)) != len(channels):
            self.message.setText("Choose distinct display detectors.")
            return
        self.view_channels[self.active_name] = channels
        self.redraw()

    def drill_plot(self, event):
        if event.dblclick and event.inaxes == self.ax and self.state.gate(self.active_name):
            # Polygon double-click belongs to the drawing tool while replacing a gate.
            from .gate_selectors import GatePolygonSelector

            if isinstance(self.selector, GatePolygonSelector) and not self.selector._selection_completed:
                return
            QtCore.QTimer.singleShot(0, self.explore_population)

    def explore_population(self):
        if self.state.gate(self.active_name):
            self.scatter_dialog()

    def quadrant_dialog(self):
        from .workspace_dialogs import QuadrantDialog

        self.flush_bounds()
        QuadrantDialog(self).exec()

    def compare_control(self):
        from .workspace_dialogs import ComparisonDialog

        if self.state.gate(self.active_name):
            self.flush_bounds()
            ComparisonDialog(self).exec()

    def backgate(self):
        from .workspace_dialogs import ComparisonDialog

        if self.state.gate(self.active_name):
            self.flush_bounds()
            ComparisonDialog(self, backgate=True).exec()

    def sample_browser(self):
        from .sample_browser import SampleBrowser

        self.flush_bounds()
        SampleBrowser(self).exec()
