from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from typing import Dict, Optional


SUMMARY_FIELDS = [
    "filename",
    "filepath",
    "status",
    "elapsed_sec",
    "input_chars",
    "input_tokens_est",
    "mode",
    "output_path",
    "error_message",
]


class OutputWriter:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.results_dir = self.base_dir / "results"
        self.logs_dir = self.base_dir / "logs"
        self.summary_path = self.base_dir / "summary.csv"
        self.run_json_path = self.base_dir / "run.json"
        self._summary_initialized = False
        self._summary_lock = threading.Lock()

    def prepare(self) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def write_result(self, filename: str, content: str) -> str:
        sanitized_name = Path(filename).with_suffix(".md").name
        path = self.results_dir / sanitized_name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def append_summary(self, row: Dict[str, Optional[str]]) -> None:
        with self._summary_lock:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self.summary_path.exists() or not self._summary_initialized
            with self.summary_path.open("a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
                if write_header:
                    writer.writeheader()
                    self._summary_initialized = True
                writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})

    def write_run_metadata(self, payload: Dict[str, Optional[str]]) -> None:
        self.run_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
