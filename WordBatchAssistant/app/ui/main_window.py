from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import config as config_module
from ..core.logging_utils import setup_logging
from ..core.runner import BatchRunner
from ..core.types import AppConfig, RunnerHooks, RunnerSummary, TaskItem
from .models import TaskTableModel
from .widgets import LogTextEdit, PathSelector


class RunnerWorker(QtCore.QObject):
    task_updated = QtCore.Signal(object)
    progress = QtCore.Signal(int, int)
    log = QtCore.Signal(str)
    finished = QtCore.Signal(object, object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        config: AppConfig,
        prompt: str,
        input_dir: str,
        output_dir: str,
        previous_status: Optional[Dict[str, str]] = None,
        retry_failed_only: bool = False,
        only_files: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.prompt = prompt
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.previous_status = previous_status or {}
        self.retry_failed_only = retry_failed_only
        self._runner: Optional[BatchRunner] = None
        self._logger = None
        self.only_files = only_files

    @QtCore.Slot()
    def run(self) -> None:
        try:
            log_dir = Path(self.output_dir) / "logs"
            self._logger = setup_logging(str(log_dir))
            hooks = RunnerHooks(
                on_task_update=self.task_updated.emit,
                on_progress=self.progress.emit,
                on_log=self.log.emit,
            )
            self._runner = BatchRunner(
                config=self.config,
                prompt_template=self.prompt,
                input_dir=self.input_dir,
                output_dir=self.output_dir,
                hooks=hooks,
                logger=self._logger,
                only_files=self.only_files,
            )
            self._runner.scan(self.previous_status)
            summary = self._runner.run(retry_failed_only=self.retry_failed_only)
            self.finished.emit(summary, self._runner.tasks)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        if self._runner:
            self._runner.cancel()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WordBatchAssistant")
        self.resize(1100, 720)
        self.task_model = TaskTableModel()
        self._worker_thread: Optional[QtCore.QThread] = None
        self._worker: Optional[RunnerWorker] = None
        self._previous_status: Dict[str, str] = {}
        self.custom_prompt_path: Optional[str] = None
        self._active_output_dir: Optional[str] = None
        self._last_summary_path: Optional[str] = None
        self._build_ui()
        self._load_defaults()

    # UI Construction -------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(QtWidgets.QLabel("输入模式："))
        self.mode_folder_radio = QtWidgets.QRadioButton("批量文件夹")
        self.mode_file_radio = QtWidgets.QRadioButton("单个文件")
        self.mode_folder_radio.setChecked(True)
        self.mode_folder_radio.toggled.connect(self._update_input_mode)
        mode_layout.addWidget(self.mode_folder_radio)
        mode_layout.addWidget(self.mode_file_radio)
        mode_layout.addStretch(1)
        layout.addLayout(mode_layout)

        self.instructions_label = QtWidgets.QLabel(
            "使用提示：① 选择批量目录或单个文件；② 输入 API Key 并选择模型；③ 点击“开始”，结果保存在输入目录/results，汇总为 summary.csv，日志在 logs/run.log。"
        )
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setStyleSheet("color: #555;")
        layout.addWidget(self.instructions_label)

        self.input_selector = PathSelector("输入目录")
        self.file_selector = PathSelector("单个文件", select_dir=False)
        self.file_selector.hide()
        self.output_selector = PathSelector("输出目录")

        layout.addWidget(self.input_selector)
        layout.addWidget(self.file_selector)
        layout.addWidget(self.output_selector)

        prompt_header = QtWidgets.QHBoxLayout()
        prompt_label = QtWidgets.QLabel("Prompt 模板（系统默认，必要时可修改）")
        self.prompt_unlock_btn = QtWidgets.QToolButton()
        self.prompt_unlock_btn.setText("编辑 Prompt")
        self.prompt_unlock_btn.setCheckable(True)
        self.prompt_unlock_btn.toggled.connect(self._toggle_prompt_edit)
        prompt_header.addWidget(prompt_label)
        prompt_header.addStretch(1)
        prompt_header.addWidget(self.prompt_unlock_btn)
        layout.addLayout(prompt_header)

        self.prompt_hint_label = QtWidgets.QLabel(
            "默认 Prompt 会严格客观评价 Word 文档，给出评分、亮点与改进建议。如需自定义，可从本地文件加载或恢复默认。"
        )
        self.prompt_hint_label.setWordWrap(True)
        layout.addWidget(self.prompt_hint_label)

        self.prompt_edit = QtWidgets.QPlainTextEdit()
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setMinimumHeight(220)
        layout.addWidget(self.prompt_edit)

        prompt_source_row = QtWidgets.QHBoxLayout()
        self.prompt_source_label = QtWidgets.QLabel("当前模板：默认")
        self.prompt_load_btn = QtWidgets.QPushButton("从文件加载")
        self.prompt_reset_btn = QtWidgets.QPushButton("恢复默认")
        self.prompt_save_default_btn = QtWidgets.QPushButton("保存为默认")
        self.prompt_load_btn.clicked.connect(self._load_prompt_from_file)
        self.prompt_reset_btn.clicked.connect(self._reset_prompt_to_default)
        self.prompt_save_default_btn.clicked.connect(self._save_prompt_as_default)
        prompt_source_row.addWidget(self.prompt_source_label)
        prompt_source_row.addStretch(1)
        prompt_source_row.addWidget(self.prompt_load_btn)
        prompt_source_row.addWidget(self.prompt_reset_btn)
        prompt_source_row.addWidget(self.prompt_save_default_btn)
        layout.addLayout(prompt_source_row)

        basic_group = QtWidgets.QGroupBox("基础参数（只需填写 API Key / 选择模型）")
        basic_layout = QtWidgets.QGridLayout(basic_group)

        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_toggle = QtWidgets.QCheckBox("显示")
        self.api_toggle.toggled.connect(self._toggle_api_visibility)

        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "openai/gpt-oss-20b:free",
            "openai/gpt-4o-mini",
            "deepseek/deepseek-chat",
            "google/gemini-1.5-pro",
            "anthropic/claude-3.5-sonnet",
        ])

        basic_layout.addWidget(QtWidgets.QLabel("API Key"), 0, 0)
        basic_layout.addWidget(self.api_key_edit, 0, 1)
        basic_layout.addWidget(self.api_toggle, 0, 2)
        basic_layout.addWidget(QtWidgets.QLabel("模型"), 1, 0)
        basic_layout.addWidget(self.model_combo, 1, 1, 1, 2)
        layout.addWidget(basic_group)

        self.advanced_toggle = QtWidgets.QToolButton()
        self.advanced_toggle.setText("显示高级参数")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)

        self.advanced_group = QtWidgets.QGroupBox("高级参数（可选）")
        self.advanced_group.setVisible(False)
        config_layout = QtWidgets.QGridLayout(self.advanced_group)

        self.endpoint_edit = QtWidgets.QLineEdit()
        self.temperature_spin = QtWidgets.QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.max_output_spin = QtWidgets.QSpinBox()
        self.max_output_spin.setRange(16, 16000)
        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(10, 600)
        self.concurrency_spin = QtWidgets.QSpinBox()
        self.concurrency_spin.setRange(1, 8)
        self.include_tables_check = QtWidgets.QCheckBox("包含表格")
        self.long_mode_combo = QtWidgets.QComboBox()
        self.long_mode_combo.addItems(["truncate", "chunk"])
        self.max_input_spin = QtWidgets.QSpinBox()
        self.max_input_spin.setRange(1000, 40000)
        self.chunk_target_spin = QtWidgets.QSpinBox()
        self.chunk_target_spin.setRange(500, 20000)

        config_layout.addWidget(QtWidgets.QLabel("Endpoint"), 0, 0)
        config_layout.addWidget(self.endpoint_edit, 0, 1, 1, 3)
        config_layout.addWidget(QtWidgets.QLabel("Temperature"), 1, 0)
        config_layout.addWidget(self.temperature_spin, 1, 1)
        config_layout.addWidget(QtWidgets.QLabel("Max Output Tokens"), 1, 2)
        config_layout.addWidget(self.max_output_spin, 1, 3)
        config_layout.addWidget(QtWidgets.QLabel("Timeout(s)"), 2, 0)
        config_layout.addWidget(self.timeout_spin, 2, 1)
        config_layout.addWidget(QtWidgets.QLabel("并发数"), 2, 2)
        config_layout.addWidget(self.concurrency_spin, 2, 3)
        config_layout.addWidget(self.include_tables_check, 3, 0)
        config_layout.addWidget(QtWidgets.QLabel("长文策略"), 3, 1)
        config_layout.addWidget(self.long_mode_combo, 3, 2)
        config_layout.addWidget(QtWidgets.QLabel("最大输入 tokens"), 4, 0)
        config_layout.addWidget(self.max_input_spin, 4, 1)
        config_layout.addWidget(QtWidgets.QLabel("分块目标 tokens"), 4, 2)
        config_layout.addWidget(self.chunk_target_spin, 4, 3)

        layout.addWidget(self.advanced_group)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_label = QtWidgets.QLabel("0 / 0")

        self.summary_label = QtWidgets.QLabel("总任务：0 | 成功：0 | 失败：0 | 跳过：0")

        button_row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("开始")
        self.cancel_btn = QtWidgets.QPushButton("取消")
        self.retry_btn = QtWidgets.QPushButton("仅重试失败")
        self.open_output_btn = QtWidgets.QPushButton("打开输出")
        self.open_summary_btn = QtWidgets.QPushButton("打开汇总")
        self.open_summary_btn.setEnabled(False)
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.retry_btn)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.open_output_btn)
        button_row.addWidget(self.open_summary_btn)

        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.summary_label)
        layout.addLayout(button_row)

        self.table_view = QtWidgets.QTableView()
        self.table_view.setModel(self.task_model)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_view)

        self.log_view = LogTextEdit()
        layout.addWidget(self.log_view)

        self.start_btn.clicked.connect(self._on_start_clicked)
        self.retry_btn.clicked.connect(lambda: self._on_start_clicked(retry_failed_only=True))
        self.cancel_btn.clicked.connect(self._cancel_worker)
        self.open_output_btn.clicked.connect(self._open_output_dir)
        self.open_summary_btn.clicked.connect(self._open_summary_file)

    def _load_defaults(self) -> None:
        defaults = config_module.DEFAULT_CONFIG
        self.endpoint_edit.setText(defaults["endpoint"])
        self.model_combo.setCurrentText(defaults["model"])
        self.temperature_spin.setValue(defaults["temperature"])
        self.max_output_spin.setValue(defaults["max_output_tokens"])
        self.timeout_spin.setValue(defaults["timeout_sec"])
        self.concurrency_spin.setValue(defaults["concurrency"])
        self.include_tables_check.setChecked(defaults["include_tables"])
        self.long_mode_combo.setCurrentText(defaults["long_doc_mode"])
        self.max_input_spin.setValue(defaults["max_input_tokens"])
        self.chunk_target_spin.setValue(defaults["chunk_target_tokens"])
        self.api_key_edit.setText(defaults.get("api_key", ""))
        self.prompt_edit.setPlainText(config_module.load_default_prompt())
        self.custom_prompt_path = None
        self._update_prompt_source_label("默认模板")

    # Button handlers --------------------------------------------------
    def _on_start_clicked(self, retry_failed_only: bool = False) -> None:
        if self._worker_thread:
            return
        only_files: Optional[List[str]] = None
        if self.mode_folder_radio.isChecked():
            input_dir = self.input_selector.path().strip()
            if not input_dir:
                QtWidgets.QMessageBox.warning(self, "缺少输入", "请选择输入目录")
                return
        else:
            single_file = self.file_selector.path().strip()
            if not single_file:
                QtWidgets.QMessageBox.warning(self, "缺少文件", "请选择需要处理的 .docx 文件")
                return
            path_obj = Path(single_file)
            if path_obj.suffix.lower() != ".docx":
                QtWidgets.QMessageBox.warning(self, "格式不支持", "单文件模式仅支持 .docx")
                return
            input_dir = str(path_obj.parent)
            only_files = [str(path_obj.resolve())]

        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QtWidgets.QMessageBox.warning(self, "缺少 Prompt", "请填写 Prompt 模板")
            return
        if not self.api_key_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "缺少 API Key", "请输入 API Key")
            return
        output_dir = self.output_selector.path().strip()
        if not output_dir:
            output_dir = input_dir
            self.output_selector.set_path(output_dir)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        self._active_output_dir = output_dir
        self.open_summary_btn.setEnabled(False)

        config = AppConfig(
            endpoint=self.endpoint_edit.text().strip(),
            model=self.model_combo.currentText().strip(),
            api_key=self.api_key_edit.text().strip(),
            temperature=self.temperature_spin.value(),
            max_output_tokens=self.max_output_spin.value(),
            timeout_sec=self.timeout_spin.value(),
            concurrency=self.concurrency_spin.value(),
            include_tables=self.include_tables_check.isChecked(),
            long_doc_mode=self.long_mode_combo.currentText(),
            max_input_tokens=self.max_input_spin.value(),
            chunk_target_tokens=self.chunk_target_spin.value(),
        )

        previous = {task.filepath: task.status for task in self.task_model.tasks()}
        self._worker = RunnerWorker(
            config=config,
            prompt=prompt,
            input_dir=input_dir,
            output_dir=output_dir,
            previous_status=previous,
            retry_failed_only=retry_failed_only,
            only_files=only_files,
        )
        self._worker_thread = QtCore.QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.task_updated.connect(self._on_task_update)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self.log_view.append_message)
        self._worker.finished.connect(self._on_runner_finished)
        self._worker.failed.connect(self._on_runner_failed)
        self._worker_thread.start()
        self._set_running_state(True)

    def _cancel_worker(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _open_output_dir(self) -> None:
        path = self.output_selector.path()
        if not path:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    # Slots ------------------------------------------------------------
    def _on_task_update(self, task: TaskItem) -> None:
        self.task_model.update_task(task)

    def _on_progress(self, completed: int, total: int) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(completed)
        self.progress_label.setText(f"{completed} / {total}")

    def _on_runner_finished(self, summary: RunnerSummary, tasks: List[TaskItem]) -> None:
        self.task_model.set_tasks(tasks)
        self._previous_status = {task.filepath: task.status for task in tasks}
        self.log_view.append_message("处理完成")
        self.summary_label.setText(
            f"总任务：{summary.total} | 成功：{summary.success} | 失败：{summary.failed} | 跳过：{summary.skipped}"
        )
        if self._active_output_dir:
            summary_path = Path(self._active_output_dir) / "summary.csv"
            self._last_summary_path = str(summary_path)
            self.open_summary_btn.setEnabled(summary_path.exists())
        self._cleanup_worker()

    def _on_runner_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "运行失败", message)
        self.log_view.append_message(f"错误: {message}")
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait()
        self._worker = None
        self._worker_thread = None
        self._set_running_state(False)
        if not self._last_summary_path or not Path(self._last_summary_path).exists():
            self.open_summary_btn.setEnabled(False)

    def _set_running_state(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.retry_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    def _toggle_api_visibility(self, checked: bool) -> None:
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password)

    def _toggle_prompt_edit(self, checked: bool) -> None:
        self.prompt_edit.setReadOnly(not checked)
        self.prompt_unlock_btn.setText("锁定 Prompt" if checked else "编辑 Prompt")

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_group.setVisible(checked)
        self.advanced_toggle.setText("隐藏高级参数" if checked else "显示高级参数")

    def _update_input_mode(self) -> None:
        is_folder = self.mode_folder_radio.isChecked()
        self.input_selector.setVisible(is_folder)
        self.file_selector.setVisible(not is_folder)
        if is_folder and not self.input_selector.path() and self.file_selector.path():
            self.input_selector.set_path(str(Path(self.file_selector.path()).parent))
        if not is_folder and self.input_selector.path():
            self.file_selector.set_path("")

    def _load_prompt_from_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 Prompt 文件", str(Path.home()))
        if not file_path:
            return
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "读取失败", str(exc))
            return
        self.prompt_edit.setPlainText(content)
        self.custom_prompt_path = file_path
        self._update_prompt_source_label(Path(file_path).name)

    def _reset_prompt_to_default(self) -> None:
        self.prompt_edit.setPlainText(config_module.load_default_prompt())
        self.custom_prompt_path = None
        self._update_prompt_source_label("默认模板")

    def _update_prompt_source_label(self, source: str) -> None:
        self.prompt_source_label.setText(f"当前模板：{source}")

    def _open_summary_file(self) -> None:
        if not self._last_summary_path:
            QtWidgets.QMessageBox.information(self, "暂无汇总", "暂未生成 summary.csv")
            return
        path = Path(self._last_summary_path)
        if not path.exists():
            QtWidgets.QMessageBox.information(self, "暂无汇总", "summary.csv 尚未生成或已被移动")
            self.open_summary_btn.setEnabled(False)
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _save_prompt_as_default(self) -> None:
        content = self.prompt_edit.toPlainText()
        target_path = config_module.DEFAULT_PROMPT_PATH
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "保存失败", f"无法写入 {target_path}: {exc}")
            return
        self.custom_prompt_path = str(target_path)
        self._update_prompt_source_label("默认模板 (已更新)")
        QtWidgets.QMessageBox.information(self, "保存成功", f"已更新默认 Prompt：{target_path}")
