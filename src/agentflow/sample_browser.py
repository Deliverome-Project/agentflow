"""Searchable sample review queue; progressive loading keeps errors visible."""

from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .desktop import button, label
from .overrides import effective_recipe
from .quality import sample_quality


class SampleBrowser(W.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Samples · review queue")
        self.resize(1050, 650)
        layout = W.QVBoxLayout(self)
        self.search = W.QLineEdit(placeholderText="Search sample, condition, group, plate, well or QC flag")
        layout.addWidget(
            label(
                f"Population: {window.active_name} · previews show parent events on independent scales",
                "muted",
            )
        )
        layout.addWidget(self.search)
        row = W.QHBoxLayout()
        self.attention = W.QCheckBox("Needs review or QC attention")
        row.addWidget(self.attention)
        row.addWidget(label("Low-count flag below", "muted"))
        self.low_count = W.QSpinBox()
        self.low_count.setRange(0, 10000000)
        self.low_count.setValue(100)
        self.low_count.setToolTip(
            "Review aid only: flags selected-population counts below this value; never excludes events"
        )
        row.addWidget(self.low_count)
        layout.addLayout(row)
        self.table = W.QTableWidget(len(window.records), 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Sample",
                "Condition / group",
                "Plate / well",
                "Preview",
                "Events kept",
                "Review",
                "QC / action",
                "Reference",
            ]
        )
        self.table.setIconSize(QtCore.QSize(110, 48))
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.status = label("Preparing sample review…", "muted")
        layout.addWidget(self.status)
        actions = W.QHBoxLayout()
        actions.addWidget(button("Open selected sample", self.open_selected, True))
        actions.addWidget(button("Next needing attention", self.next_attention))
        actions.addWidget(button("Pause loading", self.pause))
        self.resume_button = button("Resume", self.resume)
        actions.addWidget(self.resume_button)
        actions.addWidget(button("Close", self.accept))
        layout.addLayout(actions)
        self.details = {}
        for i, record in enumerate(window.records):
            values = [
                record["sample_id"],
                record.get("condition") or record["group"],
                " / ".join(record.get(k, "") for k in ("plate", "well")),
                "Pending",
                "—",
                "Pending",
                "Pending",
                "Pinned" if record["sample_id"] in window.pinned else "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(i, col, W.QTableWidgetItem(value))
        self.search.textChanged.connect(self.filter_rows)
        self.attention.toggled.connect(self.filter_rows)
        self.low_count.valueChanged.connect(self.update_flags)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load_next)
        self.cursor = 0
        self.finished.connect(lambda *_: self.timer.stop())
        self.timer.start(0)

    def pause(self):
        self.timer.stop()
        self.status.setText(f"Paused after {self.cursor}/{len(self.window.records)} samples")

    def resume(self):
        if self.cursor < len(self.window.records):
            self.timer.start(0)

    def load_next(self):
        if self.cursor >= len(self.window.records):
            self.status.setText("Ready. QC flags are descriptive; no samples or events are excluded.")
            return
        i = self.cursor
        self.cursor += 1
        w = self.window
        record = w.records[i]
        try:
            prepared, masks = w.session.get(record, w.state.recipe)
            effective = effective_recipe(w.state.recipe, record["sample_id"])
            gate = next((g for g in effective["gates"] if g["name"] == w.active_name), None)
            population = gate["name"] if gate else "root"
            count = int(masks[population].sum()) if gate else None
            reviewed = (
                all(g.get("reviewed", False) for g in effective["gates"])
                and not effective.get("draft_gates")
                and not effective.get("pending_gates")
            )
            flags = []
            qc = sample_quality(prepared)
            if qc["time_nonmonotonic"]:
                flags.append("Time runs backward: inspect acquisition")
            if qc["upper_range_events"]:
                flags.append("Upper-range events: inspect detector limits")
            if qc["uncompensated"]:
                flags.append("Uncompensated: confirm intended setup")
            if qc["identity_compensation"]:
                flags.append("Identity matrix: inspect compensation")
            if gate and not masks[gate["parent"]].any():
                flags.append("Empty parent: inspect upstream gates")
            self.details[i] = (count, reviewed, flags)
            self.table.item(i, 4).setText(f"{count:,}" if count is not None else "— (not drawn)")
            self.table.item(i, 5).setText("Reviewed" if reviewed else "Needs review")
            self.preview(i, prepared, masks, gate)
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.table.item(i, 3).setText("Unavailable")
            self.table.item(i, 5).setText("Error")
            self.table.item(i, 6).setText(str(error))
        self.update_flags()
        self.status.setText(f"Loaded {self.cursor}/{len(w.records)} · double-click any ready row to open it")
        self.timer.start(0)

    def preview(self, row, prepared, masks, gate):
        import numpy as np

        from .plot_views import subset_indices

        channels = gate["channels"] if gate else list(self.window.state.recipe["transforms"])[:2]
        population = gate["parent"] if gate else "root"
        values = prepared.transformed.loc[masks[population], channels].to_numpy()
        pixmap = QtGui.QPixmap(110, 48)
        pixmap.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#922038"))
        if len(values) and len(channels) == 1:
            counts, _ = np.histogram(values[:, 0], bins=32)
            for index, count in enumerate(counts):
                x = int(4 + index * 101 / 31)
                painter.drawLine(x, 43, x, int(43 - 38 * count / max(1, counts.max())))
        elif len(values):
            lo, hi = values.min(axis=0), values.max(axis=0)
            points = (values[subset_indices(len(values), 250)] - lo) / np.maximum(hi - lo, 1e-12)
            for point in points:
                painter.drawPoint(int(4 + point[0] * 101), int(43 - point[1] * 38))
        painter.end()
        self.table.item(row, 3).setText("")
        self.table.item(row, 3).setData(QtCore.Qt.DecorationRole, pixmap)
        self.table.item(row, 3).setToolTip(
            "Parent events · recipe axes · independently scaled preview; open sample for labeled axes"
        )
        self.table.setRowHeight(row, 54)

    def update_flags(self):
        for i, (count, _, flags) in self.details.items():
            notes = flags + (
                [f"Low count (<{self.low_count.value()}): inspect population"]
                if count is not None and count < self.low_count.value()
                else []
            )
            self.table.item(i, 6).setText("; ".join(notes) or "No flags")
            self.table.item(i, 6).setToolTip(self.table.item(i, 6).text())
        self.filter_rows()

    def needs_attention(self, row):
        return self.table.item(row, 5).text() != "Reviewed" or self.table.item(row, 6).text() != "No flags"

    def filter_rows(self):
        query = self.search.text().casefold()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() for col in range(self.table.columnCount()))
            self.table.setRowHidden(
                row,
                query not in text.casefold()
                or (self.attention.isChecked() and not self.needs_attention(row)),
            )

    def next_attention(self):
        start = self.table.currentRow()
        rows = list(range(start + 1, self.table.rowCount())) + list(range(start + 1))
        for row in rows:
            if not self.table.isRowHidden(row) and self.needs_attention(row):
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                return

    def open_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.window.sample_choice.setCurrentIndex(row)
        if self.window.record["sample_id"] == self.window.records[row]["sample_id"]:
            self.accept()
