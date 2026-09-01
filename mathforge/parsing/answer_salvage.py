from __future__ import annotations

import json
import re
from collections.abc import Iterable

from mathforge.parsing.answer_extraction import (
    extract_last_boxed,
    extract_tail_answer,
    prepare_model_text,
    sanitize_final_answer,
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

    answer, _ = salvage_answer_with_source(raw_texts)
    return answer


def salvage_answer_with_source(
    raw_texts: Iterable[object] | None,
) -> tuple[str | None, str]:
    """Return ``(answer, source)`` for the L3/L4 salvage levels.

    L3 is reserved for an explicit ``\\boxed{...}`` expression.  L4 is a
    labelled/cue-word or final-line answer recovered from a response that did
    not contain a boxed expression.
    """

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
                answer, issues = sanitize_final_answer(rf"\boxed{{{boxed}}}")
                if answer and "placeholder_leak" not in issues:
                    return rf"\boxed{{{answer}}}", "L3"
            encoded = _last_match(_FINAL_ANSWER_JSON, source)
            if encoded:
                value = _decode_json_string(encoded)
                if value:
                    answer, issues = sanitize_final_answer(value)
                    if answer and "placeholder_leak" not in issues:
                        return _boxed(answer), "L4"
            labeled = _last_match(_LABELED_ANSWER, source)
            if labeled:
                answer, issues = sanitize_final_answer(labeled)
                if answer and "placeholder_leak" not in issues:
                    return _boxed(answer), "L4"
            tail = extract_tail_answer(source)
            answer, issues = sanitize_final_answer(tail)
            if answer and "placeholder_leak" not in issues:
                return _boxed(answer), "L4"
        # A complete ``<think>`` block is intentionally hidden from the
        # public view, but a boxed answer inside it is still useful salvage.
        # Check the original response only after public/salvage views so a
        # published conclusion wins over private scratchwork.
        raw_boxed = extract_last_boxed(raw_text)
        if raw_boxed:
            answer, issues = sanitize_final_answer(rf"\boxed{{{raw_boxed}}}")
            if answer and "placeholder_leak" not in issues:
                return rf"\boxed{{{answer}}}", "L3"
    return None, ""


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
