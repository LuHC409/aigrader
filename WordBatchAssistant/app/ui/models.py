from __future__ import annotations

from typing import List, Optional

from PySide6 import QtCore

from ..core.types import TaskItem


class TaskTableModel(QtCore.QAbstractTableModel):
    headers = ["File", "Status", "Output", "Error"]

    def __init__(self) -> None:
        super().__init__()
        self._tasks: List[TaskItem] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self._tasks)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.headers)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):  # noqa: N802
        if not index.isValid() or role not in {QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole}:
            return None
        task = self._tasks[index.row()]
        column = index.column()
        if column == 0:
            return task.filename
        if column == 1:
            return task.status
        if column == 2:
            return task.output_path or ""
        if column == 3:
            return task.error_message
        return None

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.DisplayRole):  # noqa: N802,E501
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return self.headers[section]
        return str(section + 1)

    def set_tasks(self, tasks: List[TaskItem]) -> None:
        self.beginResetModel()
        self._tasks = tasks
        self.endResetModel()

    def update_task(self, task: TaskItem) -> None:
        for row, existing in enumerate(self._tasks):
            if existing.filepath == task.filepath:
                self._tasks[row] = task
                top_left = self.index(row, 0)
                bottom_right = self.index(row, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bottom_right)
                return

    def tasks(self) -> List[TaskItem]:
        return list(self._tasks)
