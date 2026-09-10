"""Optional desktop entry point for opening analyses or importing FCS files."""

from pathlib import Path

from PySide6 import QtGui
from PySide6 import QtWidgets as W

from .desktop import button, label
from .engine import load_recipe
from .projects import create_project
from .samples import SampleSession, read_samples
from .theme import ASSETS, desktop_style
from .workbench import ScreenWindow


class Launcher(W.QDialog):
    def __init__(self):
        super().__init__()
        self.selection = None
        self.setWindowTitle("Agentflow · Open an analysis")
        self.resize(620, 360)
        self.setStyleSheet(desktop_style())
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(label("agentflow", "brand"))
        layout.addWidget(label("Your flow analysis", "title"))
        layout.addWidget(label("Open a saved analysis or start from FCS files.", "muted"))
        layout.addWidget(button("Open analysis folder…", self.open_folder, True))
        layout.addWidget(button("Choose recipe and sample sheet…", self.open_files))
        layout.addWidget(button("Import FCS files…", self.import_files))
        self.status = label("Analysis folders contain recipe.json and samples.csv.", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def select(self, recipe, samples):
        try:
            loaded = load_recipe(recipe)
            records = read_samples(samples)
            for record in records:
                if not Path(record["fcs_path"]).is_file():
                    raise ValueError(
                        f"Missing FCS file: {record['fcs_path']}. Update its path in the sample sheet."
                    )
            SampleSession(records).get(records[0], loaded)
            self.selection = (Path(recipe), records)
            self.accept()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(f"Cannot open: {error}")

    def open_folder(self):
        folder = W.QFileDialog.getExistingDirectory(self, "Open analysis folder")
        if folder:
            self.select(Path(folder) / "recipe.json", Path(folder) / "samples.csv")

    def open_files(self):
        recipe, _ = W.QFileDialog.getOpenFileName(self, "Choose recipe", "", "JSON (*.json)")
        if not recipe:
            return
        samples, _ = W.QFileDialog.getOpenFileName(
            self, "Choose sample sheet", str(Path(recipe).parent), "CSV (*.csv)"
        )
        if samples:
            self.select(recipe, samples)

    def import_files(self):
        files, _ = W.QFileDialog.getOpenFileNames(self, "Select FCS samples", "", "FCS (*.fcs *.FCS)")
        if not files:
            return
        parent = W.QFileDialog.getExistingDirectory(self, "Choose where to create the analysis folder")
        if not parent:
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Create analysis")
        form = W.QFormLayout(dialog)
        name = W.QLineEdit("flow-analysis")
        compensation = W.QComboBox()
        compensation.addItems(
            ["Choose compensation…", "Use each file's embedded matrix", "Explicitly uncompensated"]
        )
        example = W.QCheckBox("DUMMY / EXAMPLE data")
        form.addRow("New folder name", name)
        form.addRow("Compensation", compensation)
        form.addRow(example)
        info = label(
            "Draft scatter/singlet gates will be created. Assign fluorescence detectors after opening.",
            "muted",
        )
        info.setWordWrap(True)
        form.addRow(info)

        def create():
            try:
                if (
                    not name.text().strip()
                    or Path(name.text()).name != name.text()
                    or name.text() in {".", ".."}
                ):
                    raise ValueError("Enter a single new folder name")
                if compensation.currentIndex() == 0:
                    raise ValueError("Choose how compensation should be handled")
                result = create_project(
                    files,
                    Path(parent) / name.text(),
                    "fcs" if compensation.currentIndex() == 1 else "none",
                    example.isChecked(),
                )
                dialog.accept()
                self.select(result / "recipe.json", result / "samples.csv")
            except (ValueError, OSError, KeyError, TypeError) as error:
                info.setText(str(error))

        form.addRow(button("Create & open", create, True))
        dialog.exec()


def run_launcher():
    app = W.QApplication.instance() or W.QApplication([])
    for path in ASSETS.glob("*.ttf"):
        QtGui.QFontDatabase.addApplicationFont(str(path))
    launcher = Launcher()
    if launcher.exec() != W.QDialog.Accepted:
        return 2
    path, records = launcher.selection
    recipe = load_recipe(path)
    window = ScreenWindow(records, recipe, None, path)
    window.show()
    app.exec()
    return 0
