import argparse
import os
import sqlite3

from PyQt5 import QtCore, QtGui, QtWidgets
from typing import Dict, List, Optional, Union


COL_NAME = 0
COL_IMAGE = 1
COL_ID = 2
COL_ID_PARENT = 3
COL_STATE = 4


def _name_bg_for_state(state: Optional[int]) -> Optional[QtGui.QBrush]:
    if state == 0:
        return QtGui.QBrush(QtGui.QColor("#ffb3b3"))
    if state == 1:
        return QtGui.QBrush(QtGui.QColor("#fff0a6"))
    if state == 2:
        return QtGui.QBrush(QtGui.QColor("#b8f5b8"))
    return None


def _pixmap_from_blob(blob: Optional[bytes]) -> Optional[QtGui.QPixmap]:
    if not blob:
        return None
    pm = QtGui.QPixmap()
    if not pm.loadFromData(blob):
        return None
    return pm


class HierarchyWindow(QtWidgets.QMainWindow):
    def __init__(self, db_path: str):
        super().__init__()
        self._db_path = db_path
        self._suppress_changes = False

        self.setWindowTitle("SQLite Hierarchy")
        self.resize(900, 600)

        self.tree = QtWidgets.QTreeView(self)
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked
        )
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.setCentralWidget(self.tree)

        self.model = QtGui.QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["name", "image", "id", "id_parent", "state"])
        self.model.itemChanged.connect(self._on_item_changed)
        self.tree.setModel(self.model)

        self.tree.setColumnHidden(COL_ID, True)
        self.tree.setColumnHidden(COL_ID_PARENT, True)
        self.tree.setColumnHidden(COL_STATE, True)

        self._load_tree()
        self.tree.expandAll()
        self.tree.header().setSectionResizeMode(COL_NAME, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(COL_IMAGE, QtWidgets.QHeaderView.ResizeToContents)

    def _connect(self):
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        return con

    def _load_tree(self):
        self._suppress_changes = True
        try:
            self.model.removeRows(0, self.model.rowCount())

            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT id, id_parent, name, image, state FROM hierarhy ORDER BY id"
                ).fetchall()
            finally:
                con.close()

            by_id = {int(r["id"]): r for r in rows}  # type: Dict[int, sqlite3.Row]
            children = {}  # type: Dict[Optional[int], List[int]]
            for r in rows:
                pid = r["id_parent"]
                pid_key = int(pid) if pid is not None else None  # type: Optional[int]
                children.setdefault(pid_key, []).append(int(r["id"]))

            def add_node(node_id, parent_item):
                r = by_id[node_id]
                state = r["state"]
                name_bg = _name_bg_for_state(int(state) if state is not None else None)
                pm = _pixmap_from_blob(r["image"])

                items = [
                    QtGui.QStandardItem("" if r["name"] is None else str(r["name"])),
                    QtGui.QStandardItem(""),
                    QtGui.QStandardItem(str(r["id"])),
                    QtGui.QStandardItem("" if r["id_parent"] is None else str(r["id_parent"])),
                    QtGui.QStandardItem("" if state is None else str(state)),
                ]

                for it in items:
                    it.setEditable(False)

                items[COL_NAME].setEditable(True)

                if name_bg is not None:
                    items[COL_NAME].setData(name_bg, QtCore.Qt.BackgroundRole)

                if pm is not None:
                    icon_pm = pm.scaled(
                        48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                    items[COL_IMAGE].setData(QtGui.QIcon(icon_pm), QtCore.Qt.DecorationRole)

                for it in items:
                    it.setData(int(r["id"]), QtCore.Qt.UserRole)

                if parent_item is None:
                    self.model.appendRow(items)
                else:
                    parent_item.appendRow(items)

                for child_id in children.get(node_id, []):
                    add_node(child_id, items[COL_NAME])

            for root_id in children.get(None, []):
                add_node(root_id, None)
        finally:
            self._suppress_changes = False

    def _on_item_changed(self, item):
        if self._suppress_changes:
            return
        if item.column() != COL_NAME:
            return

        node_id = item.data(QtCore.Qt.UserRole)
        new_name = item.text()
        con = self._connect()
        try:
            con.execute("UPDATE hierarhy SET name = ? WHERE id = ?", (new_name, node_id))
            con.commit()
        finally:
            con.close()

    def _selected_node_id(self) -> Optional[int]:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return None
        return idx.data(QtCore.Qt.UserRole)

    def _on_context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        self.tree.setCurrentIndex(idx)
        node_id = self._selected_node_id()
        if node_id is None:
            return

        menu = QtWidgets.QMenu(self)
        act_add = menu.addAction("Добавить дочерний элемент")
        chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_add:
            self._add_child(node_id)

    def _add_child(self, parent_id):
        try:
            con = self._connect()
            try:
                cur = con.cursor()
                cur.execute(
                    "INSERT INTO hierarhy (id_parent, name, image, state) VALUES (?, ?, ?, ?)",
                    (parent_id, "Новый элемент", None, 1),
                )
                con.commit()
            finally:
                con.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось добавить дочерний элемент:\n{e}",
            )
            return

        self._load_tree()
        self.tree.expandAll()


def dump_schema(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        print("Tables:", tables)
        for t in tables:
            print(f"\n== {t} ==")
            for cid, name, typ, notnull, dflt, pk in cur.execute(
                f"PRAGMA table_info({t})"
            ):
                print(
                    f"{cid}: {name} {typ} "
                    f"notnull={notnull} dflt={dflt} pk={pk}"
                )
    finally:
        con.close()


def inspect_images(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        total = cur.execute("SELECT COUNT(*) FROM hierarhy").fetchone()[0]
        non_null = cur.execute(
            "SELECT COUNT(*) FROM hierarhy WHERE image IS NOT NULL"
        ).fetchone()[0]
        non_empty = cur.execute(
            "SELECT COUNT(*) FROM hierarhy WHERE image IS NOT NULL AND length(image) > 0"
        ).fetchone()[0]
        print(f"total={total}")
        print(f"image IS NOT NULL: {non_null}")
        print(f"image non-empty (len>0): {non_empty}")

        print("\nSample non-empty image rows (id, bytes_len, first16_hex):")
        for _id, ln, hx in cur.execute(
            "SELECT id, length(image), hex(substr(image, 1, 16)) "
            "FROM hierarhy "
            "WHERE image IS NOT NULL AND length(image) > 0 "
            "ORDER BY id LIMIT 10"
        ):
            print(_id, ln, hx)
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=os.path.join(os.path.dirname(__file__), "task"),
        help="Path to SQLite database file",
    )
    parser.add_argument("--schema", action="store_true", help="Print DB schema and exit")
    parser.add_argument(
        "--roots",
        action="store_true",
        help="Inspect id_parent values and print root candidates",
    )
    parser.add_argument(
        "--images",
        action="store_true",
        help="Inspect image column contents (BLOB) and exit",
    )
    args = parser.parse_args()

    if args.schema:
        dump_schema(args.db)
        return
    if args.roots:
        con = sqlite3.connect(args.db)
        try:
            cur = con.cursor()
            null_cnt = cur.execute(
                "SELECT COUNT(*) FROM hierarhy WHERE id_parent IS NULL"
            ).fetchone()[0]
            zero_cnt = cur.execute(
                "SELECT COUNT(*) FROM hierarhy WHERE id_parent = 0"
            ).fetchone()[0]
            self_cnt = cur.execute(
                "SELECT COUNT(*) FROM hierarhy WHERE id_parent = id"
            ).fetchone()[0]
            total = cur.execute("SELECT COUNT(*) FROM hierarhy").fetchone()[0]
            print(f"total={total}")
            print(f"id_parent IS NULL: {null_cnt}")
            print(f"id_parent = 0: {zero_cnt}")
            print(f"id_parent = id: {self_cnt}")

            print("\nExamples where id_parent IS NULL:")
            for row in cur.execute(
                "SELECT id, id_parent, name, state FROM hierarhy "
                "WHERE id_parent IS NULL "
                "ORDER BY id LIMIT 10"
            ):
                print(row)

            print("\nExamples where id_parent = 0:")
            for row in cur.execute(
                "SELECT id, id_parent, name, state FROM hierarhy "
                "WHERE id_parent = 0 "
                "ORDER BY id LIMIT 10"
            ):
                print(row)

            print("\nExamples where id_parent = id:")
            for row in cur.execute(
                "SELECT id, id_parent, name, state FROM hierarhy "
                "WHERE id_parent = id "
                "ORDER BY id LIMIT 10"
            ):
                print(row)
        finally:
            con.close()
        return
    if args.images:
        inspect_images(args.db)
        return

    app = QtWidgets.QApplication([])
    w = HierarchyWindow(args.db)
    w.show()
    app.exec_()


if __name__ == "__main__":
    main()
