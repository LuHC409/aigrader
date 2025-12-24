from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtWidgets


class PathSelector(QtWidgets.QWidget):
    def __init__(self, label: str, select_dir: bool = True, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.select_dir = select_dir
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel(label)
        self.line_edit = QtWidgets.QLineEdit()
        self.browse_btn = QtWidgets.QPushButton("浏览")
        self.browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.browse_btn)

    def path(self) -> str:
        return self.line_edit.text().strip()

    def set_path(self, value: str) -> None:
        self.line_edit.setText(value)

    def _on_browse(self) -> None:
        if self.select_dir:
            directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择文件夹", self.path() or str(Path.home()))
            if directory:
                self.line_edit.setText(directory)
        else:
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择文件", self.path() or str(Path.home()))
            if file_path:
                self.line_edit.setText(file_path)


class LogTextEdit(QtWidgets.QPlainTextEdit):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setReadOnly(True)

    def append_message(self, message: str) -> None:
        self.appendPlainText(message)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
