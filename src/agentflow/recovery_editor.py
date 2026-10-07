"""Recovery and named checkpoints shared by single- and multi-sample editors."""

from PySide6 import QtCore
from PySide6 import QtWidgets as W


class RecoveryEditor:
    def init_recovery_tools(self):
        menu = W.QMenu(self)
        menu.addAction(
            "Drawing instructions", lambda: W.QMessageBox.information(self, "Drawing", self.help.text())
        )
        menu.addAction("Save checkpoint…", self.save_checkpoint)
        menu.addAction("Restore checkpoint…", self.restore_checkpoint)
        menu.addAction("Recover unsaved changes…", self.recover_changes)
        menu.addAction("Discard recovery copy…", self.discard_recovery)
        self.gate_help_button.setMenu(menu)
        self.gate_help_button.setText("Tools")
        self.gate_help_button.setFixedWidth(80)
        self.recovery_timer = QtCore.QTimer(self)
        self.recovery_timer.setInterval(3000)
        self.recovery_timer.timeout.connect(self.autosave_pending_fields)
        self.recovery_timer.start()
        if self.state.recovery_pending:
            self.message.setText(
                "Unsaved work is available. Tools → Recover unsaved changes, or discard the recovery copy."
            )

    def autosave_pending_fields(self):
        # Capture valid typed thresholds too, without claiming incomplete text was saved.
        if not self.isVisible() or self.state.recovery_pending:
            return
        try:
            self.flush_bounds()
            self.state.write_recovery()
        except (OSError, ValueError, TypeError) as error:
            self.message.setText(f"Recovery needs attention: {error}")

    def save_checkpoint(self):
        name, ok = W.QInputDialog.getText(self, "Save checkpoint", "Name this analysis checkpoint")
        if ok:
            try:
                self.flush_bounds()
                self.state.checkpoint(name.strip())
                self.message.setText(f"Checkpoint saved: {name}")
            except (ValueError, OSError) as error:
                self.message.setText(str(error))

    def restore_checkpoint(self):
        choices = sorted(p.stem for p in self.state.checkpoint_dir.glob("*.json"))
        if not choices:
            self.message.setText("No checkpoints yet. Use Tools → Save checkpoint.")
            return
        name, ok = W.QInputDialog.getItem(
            self,
            "Restore checkpoint",
            "Restore (current edits remain available through Undo)",
            choices,
            0,
            False,
        )
        if ok:
            self.perform(lambda: self.state.restore_checkpoint(name), redraw=False)
            self.rebuild(self.active_name)

    def recover_changes(self):
        if not self.state.recovery_path.exists():
            self.message.setText("No recovery copy is available.")
            return
        self.perform(self.state.recover, redraw=False)
        self.rebuild(self.active_name)

    def discard_recovery(self):
        if (
            W.QMessageBox.question(
                self,
                "Discard recovery",
                "Discard the unsaved recovery copy? The saved analysis is unchanged.",
            )
            == W.QMessageBox.Yes
        ):
            self.state.recovery_path.unlink(missing_ok=True)
            self.state.recovery_pending = False
            self.message.setText("Recovery copy discarded.")
