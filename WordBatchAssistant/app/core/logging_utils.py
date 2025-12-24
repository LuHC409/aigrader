from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


LOGGER_NAME = "WordBatchAssistant"


def setup_logging(log_dir: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path / "run.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    logger.handlers = [file_handler]
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
