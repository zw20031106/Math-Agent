from __future__ import annotations

from fractions import Fraction
import re

from mathforge.parsing.answer_extraction import unwrap_boxed

_ANSWER_PREFIX = re.compile(
    r"^\s*(?:final\s*answer|answer|最终答案|答案)\s*[:：]\s*",
    re.I,
)
_LATEX_FRACTION = re.compile(
    r"\\(?:d?frac)\s*\{([+-]?\d+)\}\s*\{(\d+)\}"
)


def unwrap_answer(value: str) -> str:
    normalized = _ANSWER_PREFIX.sub("", str(value or "").strip())
    normalized = unwrap_boxed(normalized)
    text_wrapper = re.fullmatch(
        r"\\(?:text|mathrm)\s*\{(.*)\}",
        normalized,
        re.DOTALL,
    )
    if text_wrapper is not None:
        normalized = text_wrapper.group(1).strip()
    return normalized.rstrip(".。").strip()


def canonical_answer(value: str, answer_type: str = "expression") -> str:
    normalized = unwrap_answer(value)
    normalized = (
        normalized.replace("−", "-")
        .replace("–", "-")
        .replace(r"\left", "")
        .replace(r"\right", "")
        .replace(r"\,", "")
        .replace(r"\!", "")
    )
    kind = str(answer_type or "expression").strip().lower()
    if kind == "choice":
        return ",".join(
            part.upper()
            for part in re.findall(r"[A-H]", normalized, re.I)
        )
    if kind == "integer":
        try:
            return str(int(normalized))
        except ValueError:
            return _compact(normalized)
    if kind == "fraction":
        fraction = _fraction_value(normalized)
        return str(fraction) if fraction is not None else _compact(normalized)
    if kind in {"tuple", "vector"}:
        values = _sequence_values(normalized)
        return (
            f"({','.join(_canonical_atom(item) for item in values)})"
            if values is not None
            else _compact(normalized)
        )
    if kind == "matrix":
        rows = _matrix_rows(normalized)
        return (
            "[" + ";".join(
                ",".join(_canonical_atom(item) for item in row)
                for row in rows
            ) + "]"
            if rows is not None
            else _compact(normalized)
        )
    if kind == "set":
        body = normalized.replace(r"\{", "{").replace(r"\}", "}").strip()
        if body.startswith("{") and body.endswith("}"):
            values = _split_top_level(body[1:-1], ",")
            return "{" + ",".join(
                sorted(_canonical_atom(item) for item in values)
            ) + "}"
        return _compact(body)
    if kind == "interval":
        return _compact(
            normalized
            .replace(r"\infty", "inf")
            .replace("∞", "inf")
            .replace(r"\cup", "∪")
            .replace("union", "∪")
        )
    return _canonical_atom(normalized)


def answer_shape_valid(value: str, answer_type: str) -> bool:
    normalized = unwrap_answer(value)
    if not normalized:
        return False
    kind = str(answer_type or "").strip().lower()
    if kind == "choice":
        return bool(re.fullmatch(r"[A-H](?:\s*[,、]\s*[A-H])*", normalized, re.I))
    if kind == "integer":
        return bool(re.fullmatch(r"[+-]?\d+", normalized))
    if kind == "fraction":
        return _fraction_value(normalized) is not None
    if kind in {"vector", "tuple"}:
        values = _sequence_values(normalized)
        return values is not None and len(values) >= 2
    if kind == "interval":
        compact = normalized.replace(r"\left", "").replace(r"\right", "").strip()
        return bool(re.fullmatch(r"[\[(].+[\])]", compact))
    if kind == "set":
        compact = normalized.replace(r"\{", "{").replace(r"\}", "}")
        return compact.startswith("{") and compact.endswith("}")
    if kind == "matrix":
        return _matrix_rows(normalized) is not None
    return True


def _fraction_value(value: str) -> Fraction | None:
    matched = _LATEX_FRACTION.fullmatch(value.strip())
    if matched is not None:
        numerator, denominator = matched.groups()
    else:
        matched = re.fullmatch(r"([+-]?\d+)\s*/\s*(\d+)", value.strip())
        if matched is None:
            return None
        numerator, denominator = matched.groups()
    if int(denominator) == 0:
        return None
    return Fraction(int(numerator), int(denominator))


def _sequence_values(value: str) -> list[str] | None:
    compact = re.sub(r"\^\s*(?:\{?T\}?|\\top)\s*$", "", value.strip(), flags=re.I)
    matrix = _matrix_rows(compact)
    if matrix is not None and len(matrix) == 1:
        return matrix[0]
    if matrix is not None and all(len(row) == 1 for row in matrix):
        return [row[0] for row in matrix]
    if len(compact) >= 2 and compact[0] in "([" and compact[-1] in ")]":
        compact = compact[1:-1]
    values = _split_top_level(compact.replace("，", ","), ",")
    return values if len(values) >= 2 else None


def _matrix_rows(value: str) -> list[list[str]] | None:
    latex = re.fullmatch(
        r"\\begin\{(?:p|b|v|V)?matrix\}(.*?)\\end\{(?:p|b|v|V)?matrix\}",
        value.strip(),
        re.DOTALL,
    )
    if latex is not None:
        rows = [
            [item.strip() for item in row.split("&")]
            for row in re.split(r"\\\\", latex.group(1))
            if row.strip()
        ]
        return rows if rows and all(row and all(row) for row in rows) else None
    compact = value.strip()
    if not (compact.startswith("[[") and compact.endswith("]]")):
        return None
    raw_rows = _split_top_level(compact[1:-1], ",")
    parsed: list[list[str]] = []
    for row in raw_rows:
        row = row.strip()
        if not (row.startswith("[") and row.endswith("]")):
            return None
        items = _split_top_level(row[1:-1], ",")
        if not items:
            return None
        parsed.append(items)
    return parsed if parsed and len({len(row) for row in parsed}) == 1 else None


def _canonical_atom(value: str) -> str:
    normalized = _LATEX_FRACTION.sub(r"(\1)/(\2)", value)
    normalized = (
        normalized.replace(r"\pi", "pi")
        .replace(r"\cdot", "*")
        .replace(r"\times", "*")
    )
    normalized = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", normalized)
    return _compact(normalized).casefold()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _split_top_level(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(value):
        if character in "([{":
            stack.append(character)
        elif character in ")]}":
            if stack and stack[-1] == pairs[character]:
                stack.pop()
        elif character == separator and not stack:
            part = value[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts
