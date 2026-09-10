"""Native population hierarchy with stable recipe-order navigation."""

from PySide6 import QtCore
from PySide6 import QtWidgets as W


class PopulationTree(W.QTreeWidget):
    currentRowChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setAnimated(False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setAccessibleName("Population hierarchy")
        self.currentItemChanged.connect(self._changed)

    def _changed(self, current, previous):
        if current in self.rows:
            self.currentRowChanged.emit(self.rows.index(current))

    def populate(self, names, gates, titles):
        expanded = {item.data(0, QtCore.Qt.UserRole): item.isExpanded() for item in self.rows}
        self.clear()
        self.rows = []
        nodes = {}
        definitions = {g["name"]: g for g in gates}
        for name in names:
            item = W.QTreeWidgetItem([titles.get(name, name)])
            item.setData(0, QtCore.Qt.UserRole, name)
            nodes[name] = item
            self.rows.append(item)
        for name in names:
            parent = definitions.get(name, {}).get("parent", "root")
            if parent in nodes:
                nodes[parent].addChild(nodes[name])
            else:
                self.addTopLevelItem(nodes[name])
        for name, item in nodes.items():
            item.setExpanded(expanded.get(name, True))

    def setCurrentRow(self, row):
        if not 0 <= row < len(self.rows):
            return
        item = self.rows[row]
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(item)
        self.scrollToItem(item)

    def currentRow(self):
        return self.rows.index(self.currentItem()) if self.currentItem() in self.rows else -1

    def set_population_text(self, row, title, detail, tooltip):
        item = self.rows[row]
        item.setText(0, f"{title}\n{detail}")
        item.setToolTip(0, tooltip)
