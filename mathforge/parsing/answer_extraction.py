from __future__ import annotations

from dataclasses import dataclass
import re


_CLOSED_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>", re.IGNORECASE)
_ANY_THINK_TAG = re.compile(r"</?think>", re.IGNORECASE)
_ANSWER_PREFIX = re.compile(
    r"(?:final\s*answer|answer|final\s*result|conclusion|"
    r"最终答案|答案|最终结果|结论|结果)"
    r"\s*(?:(?:is|为|是)\s+|[:：=]\s*|\s+)([^\r\n]+)",
    re.IGNORECASE,
)
_ANSWER_CUE = re.compile(
    r"(?:therefore|thus|hence|\bso\b|the\s+result\s+is|it\s+follows\s+that|"
    r"综上|由此|故|所以|因此)\s*[,，:：]?\s*([^\r\n]+)",
    re.IGNORECASE,
)
_PLACEHOLDER_PATTERNS = (
    re.compile(r"<\s*exact\s+answer\s*>", re.IGNORECASE),
    re.compile(r"<\s*answer\s*>", re.IGNORECASE),
    re.compile(r"<\s*your\s+answer(?:\s+[^>]*)?\s*>", re.IGNORECASE),
    re.compile(r"\{\{[^{}]*\}\}"),
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bFILL[_ -]?IN\b", re.IGNORECASE),
)
_INSTRUCTION_LEAK_MARKERS = (
    "Provide solution text",
    "Provide the",
    "You should",
    "Your task",
    "请给出",
    "请输出",
    "Output format",
    "Return only",
)
_MATH_LATEX_MARKER = re.compile(
    r"\\(?:frac|sqrt|sum|prod|int|lim|begin|left|right|boxed)\b",
    re.IGNORECASE,
)
_MATH_OPERATOR_MARKER = re.compile(
    r"(?:\b(?:sin|cos|tan|log|ln)\s*[\[(]|"
    r"(?:[0-9A-Za-z)]\s*[=+\-*/^<>]\s*[0-9A-Za-z(]))",
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
    normalized = str(value or "").strip()
    # Remove a dollar pair only when it wraps the whole value.  Calling
    # ``strip("$")`` would silently delete the closing delimiter from prose
    # such as ``Compute $3+3$`` and make the public projection non-idempotent.
    if normalized.startswith("$") and normalized.endswith("$"):
        normalized = normalized[1:-1].strip()
    spans = _boxed_spans(normalized)
    if len(spans) == 1:
        body, start, end = spans[0]
        if not normalized[:start].strip() and not normalized[end:].strip():
            return body.strip()
    return normalized


def extract_final_answer_text(value: object, *, fallback_last_line: bool = True) -> str:
    """Extract one public answer from complete or damaged model output.

    The raw response is inspected before ``<think>`` blocks are removed.  A
    public answer still wins over a private reasoning answer when both exist,
    while a boxed answer inside an incomplete reasoning block remains
    recoverable.  This ordering is deliberately shared by the parser,
    scorer, and terminal fallback.
    """

    raw = str(value or "")
    view = prepare_model_text(raw)
    public = view.public_text
    salvage = view.salvage_text if view.think_truncated else public

    # Prefer an explicit public label, then a public boxed expression.  Only
    # after those checks do we use the raw scan, which prevents a discarded
    # private trial answer from shadowing a later public conclusion.
    for text in _unique_texts((public, salvage)):
        labeled = _ANSWER_PREFIX.findall(text)
        if labeled:
            answer = labeled[-1]
            boxed = extract_last_boxed(answer)
            return (boxed or unwrap_boxed(answer)).rstrip(".。；;").strip()
        cues = _ANSWER_CUE.findall(text)
        if cues:
            answer = cues[-1]
            boxed = extract_last_boxed(answer)
            return (boxed or unwrap_boxed(answer)).rstrip(".。；;").strip()
        boxed = extract_last_boxed(text)
        if boxed:
            return boxed.strip()

    # Requirement A2: scan the original response before think stripping.  It
    # is a last resort because private reasoning may contain exploratory boxes.
    raw_boxed = extract_last_boxed(raw)
    if raw_boxed:
        return raw_boxed.strip()
    if not fallback_last_line:
        return ""
    lines = [line.strip() for line in salvage.splitlines() if line.strip()]
    return unwrap_boxed(lines[-1] if lines else "").rstrip(".。；;").strip()


def extract_tail_answer(value: object) -> str:
    """Extract an answer-shaped tail without requiring a JSON envelope."""

    raw = str(value or "")
    view = prepare_model_text(raw)
    text = view.salvage_text if view.think_truncated else view.public_text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        matches = _ANSWER_PREFIX.findall(line) or _ANSWER_CUE.findall(line)
        if matches:
            return unwrap_boxed(matches[-1]).rstrip(".。；;").strip()
    return unwrap_boxed(lines[-1]).rstrip(".。；;").strip()


def sanitize_final_answer(value: object) -> tuple[str, list[str]]:
    """Remove placeholders and prompt text from a candidate final answer.

    The second return value is an auditable, public-safe issue list.  A
    placeholder is never considered an answer; instruction text after a real
    answer is trimmed at its first marker.
    """

    text = str(value or "").strip()
    if not text:
        return "", []
    issues: list[str] = []
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            return "", ["placeholder_leak"]
    normalized = unwrap_boxed(text).strip()
    marker_positions = [
        normalized.casefold().find(marker.casefold())
        for marker in _INSTRUCTION_LEAK_MARKERS
    ]
    positions = [position for position in marker_positions if position >= 0]
    if positions:
        first = min(positions)
        if first > 0:
            normalized = normalized[:first].rstrip(" \t\r\n:：,，;；.-")
            issues.append("instruction_leak_trimmed")
        else:
            return "", ["instruction_leak"]
    normalized = normalized.strip()
    normalized, form_issues = enforce_answer_form(normalized)
    issues.extend(form_issues)
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(normalized):
            return "", sorted(set([*issues, "placeholder_leak"]))
    return normalized, sorted(set(issues))


def enforce_answer_form(value: object, *, max_chars: int = 300) -> tuple[str, list[str]]:
    """Keep long mathematical expressions, but recover a real tail answer.

    Long prose is usually a leaked derivation or prompt fragment.  If it does
    not look expression-like, the deterministic extractor is run once more;
    no model call is made and no content is fabricated.
    """

    text = str(value or "").strip()
    if len(text) <= max(0, int(max_chars)) or _looks_math_expression(text):
        return text, []
    recovered = extract_final_answer_text(text, fallback_last_line=True)
    recovered = unwrap_boxed(recovered).strip()
    if recovered and recovered != text:
        return recovered, ["answer_form_recovered"]
    return text, []


def _looks_math_expression(text: str) -> bool:
    """Recognize expression syntax without treating every digit as math."""

    if _MATH_LATEX_MARKER.search(text) or _MATH_OPERATOR_MARKER.search(text):
        return True
    compact = "".join(str(text).split())
    return bool(
        compact
        and not any(character.isalpha() for character in compact)
        and any(character.isdigit() for character in compact)
    )


def _unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "")
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


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
