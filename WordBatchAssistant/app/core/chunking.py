from __future__ import annotations

import math
from typing import List, Tuple

from .types import DocMeta


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return int(math.ceil(len(text) / 4))


def truncate_text(text: str, meta: DocMeta, max_input_tokens: int) -> Tuple[str, DocMeta]:
    token_est = meta.token_est or estimate_tokens(text)
    meta.token_est = token_est
    if token_est <= max_input_tokens or max_input_tokens <= 0:
        return text, meta

    if len(text) <= 10:
        meta.was_truncated = True
        return text, meta

    head_len = int(len(text) * 0.7)
    tail_len = len(text) - head_len
    tail_start = max(len(text) - max(tail_len, 1), 0)
    head = text[:head_len]
    tail = text[tail_start:]
    truncated = head.rstrip() + "\n...\n" + tail.lstrip()
    meta.was_truncated = True
    return truncated, meta


def chunk_text(text: str, chunk_target_tokens: int) -> List[str]:
    paragraphs = [p.strip() for p in text.split("\n")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return [""]

    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0
    target = max(chunk_target_tokens, 200)
    for paragraph in paragraphs:
        paragraph_tokens = estimate_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > target:
            chunks.append("\n".join(current))
            current = [paragraph]
            current_tokens = paragraph_tokens
        else:
            current.append(paragraph)
            current_tokens += paragraph_tokens
    if current:
        chunks.append("\n".join(current))
    return chunks
