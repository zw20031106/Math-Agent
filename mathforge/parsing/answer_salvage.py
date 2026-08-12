from __future__ import annotations

import json
import re
from collections.abc import Iterable


_BOXED = re.compile(r"\\boxed\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_FINAL_ANSWER_JSON = re.compile(
    r'"final_answer"\s*:\s*"((?:[^"\\]|\\.)*)"'
)
_LABELED_ANSWER = re.compile(
    r"(?:最终答案|答案|final\s+answer|answer)\s*[:：]\s*([^\r\n]+)",
    re.IGNORECASE,
)
_CLOSED_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"</?think>", re.IGNORECASE)


def salvage_any_answer(raw_texts: Iterable[object] | None) -> str | None:
    """Recover the latest gradeable answer from complete or partial responses."""

    texts = list(raw_texts or ())
    for raw_text in reversed(texts):
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        body = _strip_think(raw_text)
        for source in (body, raw_text):
            boxed = _last_match(_BOXED, source)
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


def _strip_think(text: str) -> str:
    without_closed = _CLOSED_THINK.sub("", text)
    return _OPEN_THINK.sub("", without_closed)


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
    boxed = _last_match(_BOXED, normalized)
    return rf"\boxed{{{boxed or normalized}}}"
