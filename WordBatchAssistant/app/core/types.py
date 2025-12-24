from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class AppConfig:
    endpoint: str
    model: str
    api_key: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 512
    timeout_sec: int = 60
    concurrency: int = 2
    include_tables: bool = True
    long_doc_mode: str = "truncate"
    max_input_tokens: int = 3000
    chunk_target_tokens: int = 1200

    def sanitized_dict(self) -> Dict[str, Any]:
        data = self.__dict__.copy()
        data.pop("api_key", None)
        return data


@dataclass
class DocMeta:
    paragraph_count: int = 0
    table_count: int = 0
    char_count: int = 0
    token_est: int = 0
    was_truncated: bool = False
    chunk_count: int = 1

    def as_json_dict(self) -> Dict[str, Any]:
        return {
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "char_count": self.char_count,
            "token_est": self.token_est,
            "was_truncated": self.was_truncated,
            "chunk_count": self.chunk_count,
        }


TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_SKIPPED = "skipped"
TASK_STATUS_CANCELLED = "cancelled"


@dataclass
class TaskItem:
    filepath: str
    filename: str
    output_path: Optional[str] = None
    status: str = TASK_STATUS_PENDING
    error_message: str = ""
    meta: Optional[DocMeta] = None


@dataclass
class LLMUsage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass
class LLMResponse:
    text: str
    usage: Optional[LLMUsage] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class TaskResult:
    status: str
    elapsed_sec: float
    output_path: Optional[str]
    error_message: str = ""
    input_chars: int = 0
    input_tokens_est: int = 0
    mode: str = "truncate"
    usage: Optional[LLMUsage] = None


@dataclass
class RunnerSummary:
    start_time: float
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "cancelled": self.cancelled,
        }


@dataclass
class RunnerHooks:
    on_task_update: Optional[Callable[[TaskItem], None]] = None
    on_progress: Optional[Callable[[int, int], None]] = None
    on_log: Optional[Callable[[str], None]] = None
    on_finished: Optional[Callable[[RunnerSummary], None]] = None


def safe_hook(hook: Optional[Callable[..., None]], *args: Any) -> None:
    if hook:
        hook(*args)
