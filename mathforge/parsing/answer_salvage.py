from __future__ import annotations

import json
import re
from collections.abc import Iterable

from mathforge.parsing.answer_extraction import (
    extract_last_boxed,
    prepare_model_text,
    unwrap_boxed,
)

_FINAL_ANSWER_JSON = re.compile(
    r'"final_answer"\s*:\s*"((?:[^"\\]|\\.)*)"'
)
_LABELED_ANSWER = re.compile(
    r"(?:最终答案|答案|final\s+answer|answer)\s*[:：]\s*([^\r\n]+)",
    re.IGNORECASE,
)


def salvage_any_answer(raw_texts: Iterable[object] | None) -> str | None:
    """Recover the latest gradeable answer from complete or partial responses."""

    texts = list(raw_texts or ())
    for raw_text in reversed(texts):
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        model_text = prepare_model_text(raw_text)
        sources = (
            [model_text.salvage_text, model_text.public_text]
            if model_text.think_truncated
            else [model_text.public_text]
        )
        for source in sources:
            boxed = extract_last_boxed(source)
            if boxed:
                return rf"\boxed{{{boxed}}}"
            encoded = _last_match(_FINAL_ANSWER_JSON, source)
            if encoded:
                value = _decode_json_string(encoded)
                if value:
                    return _boxed(value)
            labeled = _last_match(_LABELED_ANSWER, source)
            if labeled:
                return _boxed(labeled)
    return None


def _last_match(pattern: re.Pattern[str], text: str) -> str:
    matches = pattern.findall(text)
    return matches[-1].strip() if matches else ""


def _decode_json_string(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except (json.JSONDecodeError, TypeError, ValueError):
        decoded = value
    return decoded.strip() if isinstance(decoded, str) else ""


def _boxed(value: str) -> str:
    normalized = value.strip()
    return rf"\boxed{{{unwrap_boxed(normalized)}}}"
