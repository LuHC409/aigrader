from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Union

from .chunking import chunk_text, truncate_text
from .docx_extract import DocumentExtractionError, UnsupportedDocumentError, extract_text
from .llm_client import LLMClient
from .output_writer import OutputWriter
from .prompt_render import PromptTemplateError, render_prompt
from .types import (
    AppConfig,
    DocMeta,
    LLMUsage,
    RunnerHooks,
    RunnerSummary,
    TaskItem,
    TaskResult,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_SUCCESS,
    safe_hook,
)


class CancelledError(Exception):
    pass


class BatchRunner:
    def __init__(
        self,
        config: AppConfig,
        prompt_template: str,
        input_dir: str,
        output_dir: str,
        hooks: Optional[RunnerHooks] = None,
        logger=None,
        only_files: Optional[List[str]] = None,
    ) -> None:
        self.config = config
        self.prompt_template = prompt_template
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.hooks = hooks or RunnerHooks()
        self.cancel_event = threading.Event()
        self.logger = logger
        self.llm_client = LLMClient(config)
        self.output_writer = OutputWriter(str(self.output_dir))
        self.output_writer.prepare()
        self.tasks: List[TaskItem] = []
        self.only_files = {str(Path(p).resolve()) for p in only_files} if only_files else set()

    def scan(self, previous_status: Optional[Dict[str, str]] = None) -> List[TaskItem]:
        files = [p for p in self.input_dir.rglob("*") if p.is_file()]
        tasks: List[TaskItem] = []
        skipped_docs = 0
        for file_path in sorted(files):
            suffix = file_path.suffix.lower()
            resolved = str(file_path.resolve())
            if self.only_files and resolved not in self.only_files:
                continue
            if suffix == ".docx":
                status = TASK_STATUS_PENDING
                if previous_status and str(file_path) in previous_status:
                    status = previous_status[str(file_path)]
                tasks.append(TaskItem(filepath=str(file_path), filename=file_path.name, status=status))
            elif suffix == ".doc":
                skipped_docs += 1
                tasks.append(
                    TaskItem(
                        filepath=str(file_path),
                        filename=file_path.name,
                        status=TASK_STATUS_SKIPPED,
                        error_message="仅支持 .docx，请在 Word 中另存为 docx",
                    )
                )
        if self.only_files and not tasks:
            safe_hook(self.hooks.on_log, "未找到选中的文件，请确认扩展名为 .docx")
        self.tasks = tasks
        safe_hook(self.hooks.on_log, f"发现 {len(tasks)} 个任务，其中 {skipped_docs} 个 .doc 将被跳过")
        return tasks

    def run(self, retry_failed_only: bool = False) -> RunnerSummary:
        if not self.tasks:
            self.scan()
        tasks = self.tasks
        if retry_failed_only:
            tasks = [task for task in tasks if task.status == TASK_STATUS_FAILED]

        total = len(tasks)
        summary = RunnerSummary(start_time=time.time(), total=total)
        if total == 0:
            safe_hook(self.hooks.on_log, "未发现可处理的 .docx 文件")
            payload = {
                **summary.to_dict(),
                "end_time": time.time(),
                "duration_sec": 0.0,
                "config": self.config.sanitized_dict(),
            }
            self.output_writer.write_run_metadata(payload)
            safe_hook(self.hooks.on_finished, summary)
            return summary
        safe_hook(self.hooks.on_progress, 0, max(total, 1))

        completed = 0
        pending_tasks: List[TaskItem] = []
        for task in tasks:
            if task.status == TASK_STATUS_PENDING:
                pending_tasks.append(task)
                continue
            result = TaskResult(
                status=task.status,
                elapsed_sec=0.0,
                output_path=task.output_path,
                error_message=task.error_message,
                mode=self.config.long_doc_mode,
            )
            self.output_writer.append_summary(self._summary_row(task, result))
            self._record_result(result, summary)
            completed += 1
            safe_hook(self.hooks.on_task_update, task)
            if task.status == TASK_STATUS_SKIPPED and task.error_message:
                safe_hook(self.hooks.on_log, f"跳过: {task.filename} -> {task.error_message}")
            safe_hook(self.hooks.on_progress, completed, max(total, 1))

        if not pending_tasks:
            duration = time.time() - summary.start_time
            payload = {
                **summary.to_dict(),
                "end_time": time.time(),
                "duration_sec": duration,
                "config": self.config.sanitized_dict(),
            }
            self.output_writer.write_run_metadata(payload)
            safe_hook(self.hooks.on_finished, summary)
            return summary

        with ThreadPoolExecutor(max_workers=max(1, self.config.concurrency)) as executor:
            future_map = {executor.submit(self._process_task, task): task for task in pending_tasks}
            for future in as_completed(future_map):
                result = future.result()
                self._record_result(result, summary)
                completed += 1
                safe_hook(self.hooks.on_progress, completed, max(total, 1))

        duration = time.time() - summary.start_time
        payload = {
            **summary.to_dict(),
            "end_time": time.time(),
            "duration_sec": duration,
            "config": self.config.sanitized_dict(),
        }
        self.output_writer.write_run_metadata(payload)
        safe_hook(self.hooks.on_finished, summary)
        return summary

    def cancel(self) -> None:
        self.cancel_event.set()

    # Internal helpers -------------------------------------------------

    def _process_task(self, task: TaskItem) -> TaskResult:
        start = time.time()
        task.status = TASK_STATUS_RUNNING
        safe_hook(self.hooks.on_task_update, task)
        try:
            self._check_cancel()
            safe_hook(self.hooks.on_log, f"处理中: {task.filename}")
            text, meta = self._extract_task_text(task)
            self._check_cancel()
            if self.config.long_doc_mode == "chunk":
                response_text, usage = self._run_chunk_mode(task, text, meta)
                processed_input = text
            else:
                processed_text, meta = self._apply_truncate_strategy(text, meta)
                processed_input = processed_text
                prompt = self._render_prompt(task, processed_text, meta)
                self._check_cancel()
                response = self.llm_client.generate(prompt)
                response_text = response.text
                usage = response.usage

            output_path = self.output_writer.write_result(task.filename, response_text)
            task.output_path = output_path
            task.status = TASK_STATUS_SUCCESS
            result = TaskResult(
                status=TASK_STATUS_SUCCESS,
                elapsed_sec=time.time() - start,
                output_path=output_path,
                input_chars=len(processed_input),
                input_tokens_est=meta.token_est,
                mode=self.config.long_doc_mode,
                usage=usage,
            )
            row = self._summary_row(task, result)
            self.output_writer.append_summary(row)
            safe_hook(self.hooks.on_task_update, task)
            safe_hook(self.hooks.on_log, f"完成: {task.filename}")
            return result
        except CancelledError:
            task.status = TASK_STATUS_CANCELLED
            task.error_message = "Cancelled"
            row = self._summary_row(
                task,
                TaskResult(
                    status=TASK_STATUS_CANCELLED,
                    elapsed_sec=time.time() - start,
                    output_path=None,
                    error_message="Cancelled",
                    mode=self.config.long_doc_mode,
                ),
            )
            self.output_writer.append_summary(row)
            safe_hook(self.hooks.on_task_update, task)
            return TaskResult(
                status=TASK_STATUS_CANCELLED,
                elapsed_sec=time.time() - start,
                output_path=None,
                error_message="Cancelled",
                mode=self.config.long_doc_mode,
            )
        except UnsupportedDocumentError as exc:
            task.status = TASK_STATUS_SKIPPED
            task.error_message = str(exc)
            result = TaskResult(
                status=TASK_STATUS_SKIPPED,
                elapsed_sec=time.time() - start,
                output_path=None,
                error_message=str(exc),
                mode=self.config.long_doc_mode,
            )
            self.output_writer.append_summary(self._summary_row(task, result))
            safe_hook(self.hooks.on_task_update, task)
            safe_hook(self.hooks.on_log, f"跳过: {task.filename} -> {task.error_message}")
            return result
        except (PromptTemplateError, DocumentExtractionError, Exception) as exc:  # noqa: BLE001
            task.status = TASK_STATUS_FAILED
            task.error_message = str(exc)
            result = TaskResult(
                status=TASK_STATUS_FAILED,
                elapsed_sec=time.time() - start,
                output_path=None,
                error_message=str(exc),
                mode=self.config.long_doc_mode,
            )
            self.output_writer.append_summary(self._summary_row(task, result))
            safe_hook(self.hooks.on_task_update, task)
            safe_hook(self.hooks.on_log, f"失败: {task.filename} -> {task.error_message}")
            return result

    def _extract_task_text(self, task: TaskItem) -> tuple[str, DocMeta]:
        text, meta = extract_text(task.filepath, include_tables=self.config.include_tables)
        task.meta = meta
        return text, meta

    def _apply_truncate_strategy(self, text: str, meta: DocMeta) -> tuple[str, DocMeta]:
        truncated_text, updated_meta = truncate_text(text, meta, self.config.max_input_tokens)
        return truncated_text, updated_meta

    def _run_chunk_mode(self, task: TaskItem, text: str, meta: DocMeta) -> tuple[str, Optional[LLMUsage]]:
        chunks = chunk_text(text, self.config.chunk_target_tokens)
        meta.chunk_count = len(chunks)
        if len(chunks) == 1:
            meta.was_truncated = False
            prompt = self._render_prompt(task, chunks[0], meta)
            response = self.llm_client.generate(prompt)
            return response.text, response.usage

        partial_results: List[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            chunk_meta = meta.as_json_dict()
            chunk_meta.update({"chunk_index": idx, "chunk_total": len(chunks)})
            prompt = self._render_prompt(task, chunk, chunk_meta)
            self._check_cancel()
            response = self.llm_client.generate(prompt)
            partial_results.append(response.text)

        combined = "\n\n".join(partial_results)
        final_meta = meta.as_json_dict()
        final_meta.update({"chunk_total": len(chunks), "chunk_aggregated": True})
        final_prompt = self._render_prompt(task, combined, final_meta)
        final_response = self.llm_client.generate(final_prompt)
        meta.was_truncated = False
        return final_response.text, final_response.usage

    def _render_prompt(self, task: TaskItem, content: str, meta: Union[DocMeta, Dict]) -> str:
        if isinstance(meta, DocMeta):
            meta_dict = meta.as_json_dict()
        else:
            meta_dict = dict(meta)
        variables = {
            "filename": task.filename,
            "filepath": task.filepath,
            "content": content,
            "meta": meta_dict,
        }
        return render_prompt(self.prompt_template, variables)

    def _record_result(self, result: TaskResult, summary: RunnerSummary) -> None:
        if result.status == TASK_STATUS_SUCCESS:
            summary.success += 1
        elif result.status == TASK_STATUS_FAILED:
            summary.failed += 1
        elif result.status == TASK_STATUS_SKIPPED:
            summary.skipped += 1
        elif result.status == TASK_STATUS_CANCELLED:
            summary.cancelled += 1

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise CancelledError()

    def _summary_row(self, task: TaskItem, result: TaskResult):
        return {
            "filename": task.filename,
            "filepath": task.filepath,
            "status": result.status,
            "elapsed_sec": f"{result.elapsed_sec:.2f}",
            "input_chars": result.input_chars,
            "input_tokens_est": result.input_tokens_est,
            "mode": result.mode,
            "output_path": result.output_path or "",
            "error_message": task.error_message or result.error_message,
        }
