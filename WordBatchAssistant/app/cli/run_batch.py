from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..core import config as config_module
from ..core.logging_utils import setup_logging
from ..core.runner import BatchRunner
from ..core.types import RunnerHooks, TaskItem


def _default_output_dir(input_dir: str) -> str:
    return str(Path(input_dir))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch process Word documents via LLM")
    parser.add_argument("--input_dir", help="Directory that contains .docx files")
    parser.add_argument("--input_file", help="Process a single .docx file")
    parser.add_argument("--output_dir", help="Directory to store outputs")
    parser.add_argument("--prompt_file", help="Prompt template file (optional, defaults to 内置模板)")
    parser.add_argument("--config_file", help="JSON config file (optional)")
    parser.add_argument("--api_key", help="API key (overrides env APP_API_KEY)")
    parser.add_argument("--retry_failed", action="store_true", help="Only retry failed tasks")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.input_dir and not args.input_file:
        parser.error("必须提供 --input_dir 或 --input_file")
    if args.input_dir and args.input_file:
        parser.error("--input_dir 与 --input_file 只能二选一")

    only_files = None
    if args.input_file:
        input_path = Path(args.input_file).resolve()
        if input_path.suffix.lower() != ".docx":
            parser.error("--input_file 仅支持 .docx 文件")
        input_dir = str(input_path.parent)
        only_files = [str(input_path)]
        default_output = input_dir
    else:
        input_dir = args.input_dir
        default_output = _default_output_dir(input_dir)

    output_dir = args.output_dir or default_output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    api_key = args.api_key or os.getenv("APP_API_KEY")
    app_config = config_module.load_config(args.config_file, api_key=api_key)
    prompt_template = (
        config_module.load_prompt(args.prompt_file)
        if args.prompt_file
        else config_module.load_default_prompt()
    )

    logger = setup_logging(str(Path(output_dir) / "logs"))

    def on_task_update(task: TaskItem) -> None:
        logger.info("%s -> %s", task.filename, task.status)

    hooks = RunnerHooks(on_task_update=on_task_update)

    runner = BatchRunner(
        config=app_config,
        prompt_template=prompt_template,
        input_dir=input_dir,
        output_dir=output_dir,
        hooks=hooks,
        logger=logger,
        only_files=only_files,
    )

    runner.scan()
    runner.run(retry_failed_only=args.retry_failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
