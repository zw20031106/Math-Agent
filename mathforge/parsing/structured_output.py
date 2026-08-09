from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class StructuredObjectResult:
    value: dict[str, Any]
    parse_tier: str
    recovery_reason: str = ""
    assurance_degradation: str = "none"


class StructuredOutputRecoveryLayer:
    """Recover one public JSON object through ordered, auditable tiers."""

    def parse_object(
        self,
        response: str,
        *,
        truncated: bool = False,
        required_fields: Iterable[str] = (),
    ) -> StructuredObjectResult:
        text = str(response).strip()
        required = frozenset(required_fields)
        if not text:
            raise ValueError("structured response is empty")

        if not json_latex_lexical_issues(text):
            strict = _load_object(text)
            if strict is not None and required <= set(strict):
                return StructuredObjectResult(strict, "strict_json")

        fenced = _unique_fenced_object(text, required)
        if fenced is not None:
            return StructuredObjectResult(
                fenced,
                "fenced_json",
                "unique_fenced_json",
                "low",
            )

        outer = _unique_outer_object(text, required)
        if outer is not None:
            return StructuredObjectResult(
                outer,
                "outer_object",
                "unique_outer_object",
                "low",
            )

        repaired_text, reasons = _safe_lexical_repair(text)
        repaired = _load_object(repaired_text)
        if repaired is not None and required <= set(repaired):
            return StructuredObjectResult(
                repaired,
                "trailing_repair",
                "+".join(reasons),
                "medium",
            )

        if truncated:
            closed = _close_truncated_containers(repaired_text)
            value = _load_object(closed) if closed is not None else None
            if value is not None and required <= set(value):
                reason = [*reasons, "closed_truncated_containers"]
                return StructuredObjectResult(
                    value,
                    "truncated_prefix",
                    "+".join(reason),
                    "high",
                )
        raise ValueError("structured response has no recoverable JSON object")

    def salvage_top_level_fields(
        self,
        response: str,
        field_names: Iterable[str],
    ) -> dict[str, Any]:
        """Decode complete top-level values from an otherwise truncated object."""
        text, _ = _safe_lexical_repair(str(response))
        decoder = json.JSONDecoder()
        result: dict[str, Any] = {}
        for name in field_names:
            match = re.search(rf'"{re.escape(name)}"\s*:\s*', text)
            if match is None:
                continue
            try:
                value, _ = decoder.raw_decode(text[match.end() :])
            except json.JSONDecodeError:
                continue
            result[name] = value
        return result


def json_latex_lexical_issues(text: str) -> tuple[str, ...]:
    """Report raw LaTeX backslashes that are not valid JSON string escapes."""
    issues: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        character = text[index]
        if character == '"':
            preceding = 0
            cursor = index - 1
            while cursor >= 0 and text[cursor] == "\\":
                preceding += 1
                cursor -= 1
            if preceding % 2 == 0:
                in_string = not in_string
            index += 1
            continue
        if not in_string or character != "\\":
            index += 1
            continue
        run_end = index
        while run_end < len(text) and text[run_end] == "\\":
            run_end += 1
        run_length = run_end - index
        if run_length % 2 == 1 and run_end < len(text):
            following = text[run_end]
            unicode_escape = (
                following == "u"
                and re.fullmatch(r"[0-9A-Fa-f]{4}", text[run_end + 1 : run_end + 5])
                is not None
            )
            if following.isalpha() and not unicode_escape:
                issues.append(f"unescaped_latex_control_sequence_at:{index}")
        index = run_end
    return tuple(issues)


def _load_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _unique_fenced_object(
    text: str,
    required: frozenset[str],
) -> dict[str, Any] | None:
    objects = []
    for block in re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        candidate = block.strip()
        if json_latex_lexical_issues(candidate):
            continue
        value = _load_object(candidate)
        if value is not None and required <= set(value):
            objects.append(value)
    return objects[0] if len(objects) == 1 else None


def _unique_outer_object(
    text: str,
    required: frozenset[str],
) -> dict[str, Any] | None:
    objects = []
    for block in _balanced_objects(text):
        if json_latex_lexical_issues(block):
            continue
        value = _load_object(block)
        if value is not None and required <= set(value):
            objects.append(value)
    return objects[0] if len(objects) == 1 else None


def _balanced_objects(text: str) -> list[str]:
    objects: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start : index + 1])
                start = None
    return objects


def _safe_lexical_repair(text: str) -> tuple[str, tuple[str, ...]]:
    repaired = re.sub(r",\s*([}\]])", r"\1", text)
    reasons: list[str] = []
    if repaired != text:
        reasons.append("removed_trailing_comma")
    latex_repaired = _escape_raw_latex_controls(repaired)
    if latex_repaired != repaired:
        reasons.append("escaped_latex_control_sequence")
    return latex_repaired, tuple(reasons or ["safe_lexical_repair"])


def _escape_raw_latex_controls(text: str) -> str:
    output: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        character = text[index]
        if character == '"':
            preceding = 0
            cursor = len(output) - 1
            while cursor >= 0 and output[cursor] == "\\":
                preceding += 1
                cursor -= 1
            if preceding % 2 == 0:
                in_string = not in_string
            output.append(character)
            index += 1
            continue
        if not in_string or character != "\\":
            output.append(character)
            index += 1
            continue
        run_end = index
        while run_end < len(text) and text[run_end] == "\\":
            run_end += 1
        run = text[index:run_end]
        following = text[run_end] if run_end < len(text) else ""
        unicode_escape = (
            following == "u"
            and re.fullmatch(r"[0-9A-Fa-f]{4}", text[run_end + 1 : run_end + 5])
            is not None
        )
        if len(run) % 2 == 1 and following.isalpha() and not unicode_escape:
            run += "\\"
        output.append(run)
        index = run_end
    return "".join(output)


def _close_truncated_containers(text: str) -> str | None:
    stack: list[str] = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    closers = {"{": "}", "[": "]"}
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            stack.append(character)
        elif character in "]}":
            if not stack or stack.pop() != pairs[character]:
                return None
    if in_string or not stack or len(stack) > 8:
        return None
    return text + "".join(closers[item] for item in reversed(stack))
