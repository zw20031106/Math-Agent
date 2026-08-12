from __future__ import annotations

from dataclasses import dataclass
import re


_CLOSED_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>", re.IGNORECASE)
_ANY_THINK_TAG = re.compile(r"</?think>", re.IGNORECASE)
_ANSWER_PREFIX = re.compile(
    r"(?:final\s*answer|answer|最终答案|答案)\s*[:：]\s*([^\r\n]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelTextView:
    public_text: str
    salvage_text: str
    think_truncated: bool


def prepare_model_text(value: object) -> ModelTextView:
    """Remove complete reasoning blocks and expose incomplete ones only to salvage."""

    text = str(value or "")
    without_closed = _CLOSED_THINK.sub("", text)
    unmatched_open = _OPEN_THINK.search(without_closed)
    if unmatched_open is None:
        public = _ANY_THINK_TAG.sub("", without_closed).strip()
        return ModelTextView(public, public, False)
    public = _ANY_THINK_TAG.sub("", without_closed[: unmatched_open.start()]).strip()
    salvage = _ANY_THINK_TAG.sub("", without_closed).strip()
    return ModelTextView(public, salvage, True)


def extract_boxed(text: object) -> list[str]:
    """Return complete ``\\boxed{...}`` bodies at arbitrary brace depth."""

    return [body for body, _, _ in _boxed_spans(str(text or ""))]


def extract_last_boxed(text: object) -> str:
    matches = extract_boxed(text)
    return matches[-1].strip() if matches else ""


def unwrap_boxed(value: object) -> str:
    normalized = str(value or "").strip().strip("$").strip()
    spans = _boxed_spans(normalized)
    if len(spans) == 1:
        body, start, end = spans[0]
        if not normalized[:start].strip() and not normalized[end:].strip():
            return body.strip()
    return normalized


def extract_final_answer_text(value: object, *, fallback_last_line: bool = True) -> str:
    """Extract one public answer using the shared think/box parsing rules."""

    text = prepare_model_text(value).public_text
    labeled = _ANSWER_PREFIX.findall(text)
    if labeled:
        boxed = extract_last_boxed(labeled[-1])
        return (boxed or unwrap_boxed(labeled[-1])).rstrip(".。").strip()
    boxed = extract_last_boxed(text)
    if boxed:
        return boxed
    if not fallback_last_line:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return unwrap_boxed(lines[-1] if lines else "").rstrip(".。").strip()


def _boxed_spans(text: str) -> list[tuple[str, int, int]]:
    matches: list[tuple[str, int, int]] = []
    token = r"\boxed"
    cursor = 0
    while True:
        start = text.find(token, cursor)
        if start < 0:
            return matches
        brace = start + len(token)
        while brace < len(text) and text[brace].isspace():
            brace += 1
        if brace >= len(text) or text[brace] != "{":
            cursor = max(brace, start + len(token))
            continue
        depth = 0
        index = brace
        while index < len(text):
            character = text[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    matches.append((text[brace + 1 : index], start, index + 1))
                    cursor = index + 1
                    break
            index += 1
        else:
            return matches
