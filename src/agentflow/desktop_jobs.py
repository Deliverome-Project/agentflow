"""Run the existing headless CLI in a separate process, isolated from Qt rendering."""

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
from PySide6 import QtCore


class AnalysisJob(QtCore.QObject):
    completed = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal()
    progress = QtCore.Signal(int, int)
    cancelled = QtCore.Signal()

    def __init__(self, records, recipe_path, output, parent=None):
        super().__init__(parent)
        self.records, self.recipe_path, self.output = records, recipe_path, Path(output)
        self.process = QtCore.QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.process.readyReadStandardOutput.connect(self._progress)
        self.stdout = b""
        self.directory = None
        self.done = False

    def _progress(self):
        self.stdout += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.stdout:
            line, self.stdout = self.stdout.split(b"\n", 1)
            try:
                message = json.loads(line)
                if message.get("status") == "progress":
                    self.progress.emit(int(message["processed"]), int(message["total"]))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue

    def cancel(self):
        if self.directory is not None and not self.done:
            # Let the CLI close its event writer, drain bounded rendering jobs
            # and remove staging, instead of killing it mid-publication.
            (Path(self.directory.name) / "cancel").touch()

    def isRunning(self):
        return self.process.state() != QtCore.QProcess.NotRunning

    def start(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentflow-manifest-")
        manifest = Path(self.directory.name) / "samples.csv"
        pd.DataFrame(self.records).to_csv(manifest, index=False)
        self.process.start(
            sys.executable,
            [
                "-m",
                "agentflow.cli",
                "run",
                str(manifest),
                "--recipe",
                str(self.recipe_path),
                "--out",
                str(self.output),
                "--progress",
                "--cancel-file",
                str(Path(self.directory.name) / "cancel"),
            ],
        )

    def _error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self.failed.emit(self.process.errorString())
            self._cleanup()

    def _finished(self, code, status):
        if self.done:
            return
        if code == 0 and status == QtCore.QProcess.NormalExit:
            self.completed.emit(str(self.output / "report.html"))
        else:
            message = bytes(self.process.readAllStandardError()).decode(errors="replace")
            # Library warnings may precede the CLI's final structured status.
            for line in reversed(message.splitlines()):
                try:
                    details = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(details, dict) or details.get("status") not in {"error", "cancelled"}:
                    continue
                if code == 2 and status == QtCore.QProcess.NormalExit and details["status"] == "cancelled":
                    self.cancelled.emit()
                    self._cleanup()
                    return
                message = details.get("message", message)
                break
            self.failed.emit(message.strip() or "Analysis process exited unexpectedly")
        self._cleanup()

    def _cleanup(self):
        if self.done:
            return
        self.done = True
        if self.directory is not None:
            self.directory.cleanup()
        self.finished.emit()
