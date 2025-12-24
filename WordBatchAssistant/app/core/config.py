from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .types import AppConfig


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_PATH = PACKAGE_ROOT / "default_prompt.txt"

DEFAULT_PROMPT = (
    "你是一位严格且客观的文章评审官。请仅根据系统自动提供的文档内容给出结论。\n"
    "输出要求：\n"
    "1. 综合评分（1-10 分）并写一句理由；\n"
    "2. 三条亮点（每条一句话，引用文中事实）；\n"
    "3. 三条必须改进的地方（每条一句话，引用文中事实）；\n"
    "4. 一段 3-5 句话的整体改进建议，给出明确行动项；\n"
    "不得编造内容，禁止含糊其辞。"
)


DEFAULT_CONFIG: Dict[str, Any] = {
    "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    "model": "openai/gpt-oss-20b:free",
    "api_key": "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",
    "temperature": 0.0,
    "max_output_tokens": 8192,
    "timeout_sec": 120,
    "concurrency": 2,
    "include_tables": True,
    "long_doc_mode": "truncate",
    "max_input_tokens": 20000,
    "chunk_target_tokens": 6000,
}


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_config(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not data:
        return normalized
    api_section = data.get("api")
    processing_section = data.get("processing")
    if isinstance(api_section, dict):
        normalized.update(api_section)
    if isinstance(processing_section, dict):
        normalized.update(processing_section)
    for key, value in data.items():
        if key not in {"api", "processing"}:
            normalized[key] = value
    return normalized


def merge_config(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = base.copy()
    if override:
        normalized = _normalize_config(override)
        result.update({k: v for k, v in normalized.items() if v is not None})
    return result


def load_config(path: Optional[str], api_key: Optional[str] = None) -> AppConfig:
    data: Dict[str, Any] = {}
    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        data = _read_json(config_path)
    merged = merge_config(DEFAULT_CONFIG, data)
    merged["api_key"] = api_key or merged.get("api_key") or os.getenv("APP_API_KEY", "")
    return AppConfig(**merged)


def load_prompt(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return prompt_path.read_text(encoding="utf-8")


def load_default_prompt(custom_path: Optional[str] = None) -> str:
    candidates = [
        custom_path,
        os.getenv("APP_PROMPT_FILE"),
        str(DEFAULT_PROMPT_PATH) if DEFAULT_PROMPT_PATH.exists() else None,
    ]
    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if path.exists():
                return path.read_text(encoding="utf-8")
    return DEFAULT_PROMPT
