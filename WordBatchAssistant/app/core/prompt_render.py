from __future__ import annotations

import json
import string
from typing import Any, Dict, Set


ALLOWED_VARIABLES = {"filename", "filepath", "content", "meta"}


class PromptTemplateError(ValueError):
    pass


def validate_template(template: str) -> Set[str]:
    used: Set[str] = set()
    formatter = string.Formatter()
    for _, field_name, _, _ in formatter.parse(template):
        if field_name is None:
            continue
        if field_name not in ALLOWED_VARIABLES:
            raise PromptTemplateError(f"Unknown template variable: {field_name}")
        used.add(field_name)
    return used


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    used_variables = validate_template(template)
    template_to_use = template
    if "content" not in used_variables:
        template_to_use = template_to_use.rstrip() + "\n\n【正文内容】\n{content}\n"
        used_variables.add("content")
    if "meta" not in used_variables and "meta" in variables:
        template_to_use = template_to_use.rstrip() + "\n\n【元信息】\n{meta}\n"
        used_variables.add("meta")

    missing = [key for key in used_variables if key not in variables]
    if missing:
        raise PromptTemplateError(f"Missing template variables: {', '.join(missing)}")
    normalized_vars = {**variables}
    if "meta" in normalized_vars and not isinstance(normalized_vars["meta"], str):
        normalized_vars["meta"] = json.dumps(normalized_vars["meta"], ensure_ascii=False)
    try:
        return template_to_use.format(**normalized_vars)
    except KeyError as exc:
        raise PromptTemplateError(f"Missing template variable: {exc}") from exc
