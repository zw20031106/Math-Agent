from __future__ import annotations

import ast
from collections import Counter
from dataclasses import asdict, dataclass
import re

import sympy

from mathforge.tools.safe_parse import parse_expression


_FINAL_ANSWER = re.compile(
    r"^\s*(?:final\s*answer|answer|答案)\s*[:：]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_INTEGER = re.compile(r"[+-]?\d+")
_FRACTION = re.compile(r"([+-]?\d+)\s*/\s*([+-]?\d+)")
_CHOICE = re.compile(r"[A-H](?:\s*[,、]\s*[A-H])*", re.IGNORECASE)


@dataclass(frozen=True)
class ScoreResult:
    scored: bool
    correct: bool | None
    reason: str
    actual: str
    expected: str
    scorer: str
    error: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def score_response(
    expected: str | None,
    response: str,
    *,
    answer_type: str,
    scorer: str | None = None,
) -> ScoreResult:
    """Score an extracted final answer without substring or suffix matching."""
    if expected is None:
        return ScoreResult(False, None, "missing_expected_answer", "", "", scorer or "none")

    actual = extract_final_answer(response)
    expected_text = str(expected).strip()
    scorer_name = (scorer or _default_scorer(answer_type)).strip().lower()
    if scorer_name in {"none", "unscored", "manual", "rubric"}:
        return ScoreResult(
            False,
            None,
            "manual_or_rubric_scoring_required",
            actual,
            expected_text,
            scorer_name,
        )
    if not actual:
        return ScoreResult(True, False, "missing_final_answer", actual, expected_text, scorer_name)

    comparators = {
        "exact": _compare_exact,
        "choice": _compare_choice,
        "integer": _compare_integer,
        "fraction": _compare_fraction,
        "symbolic": _compare_symbolic,
        "expression": _compare_symbolic,
        "set": _compare_set,
        "interval": _compare_interval,
        "matrix": _compare_matrix,
    }
    comparator = comparators.get(scorer_name)
    if comparator is None:
        return ScoreResult(
            False,
            None,
            "unknown_scorer",
            actual,
            expected_text,
            scorer_name,
            error=True,
        )
    try:
        correct, reason = comparator(expected_text, actual)
    except _ExpectedAnswerError as error:
        return ScoreResult(
            False,
            None,
            str(error),
            actual,
            expected_text,
            scorer_name,
            error=True,
        )
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError) as error:
        return ScoreResult(
            True,
            False,
            f"invalid_actual_answer:{type(error).__name__}",
            actual,
            expected_text,
            scorer_name,
        )
    return ScoreResult(True, correct, reason, actual, expected_text, scorer_name)


def extract_final_answer(response: str) -> str:
    text = str(response or "").strip()
    matches = _FINAL_ANSWER.findall(text)
    if matches:
        return _unwrap_answer(matches[-1])
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return _unwrap_answer(lines[-1] if lines else "")


def _default_scorer(answer_type: str) -> str:
    normalized = str(answer_type or "").strip().lower()
    if normalized in {"choice", "integer", "fraction", "set", "interval", "matrix"}:
        return normalized
    if normalized == "expression":
        return "symbolic"
    if normalized in {"text", "proof", "explanation", "derivation"}:
        return "manual"
    return "exact"


def _compare_exact(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _normalize_exact(expected)
    if not expected_value:
        raise _ExpectedAnswerError("invalid_expected_answer")
    correct = _normalize_exact(actual) == expected_value
    return correct, "exact_match" if correct else "exact_mismatch"


def _compare_choice(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _strict_match(_CHOICE, expected, expected=True).upper().replace("、", ",")
    actual_match = _CHOICE.fullmatch(_normalize_scalar(actual))
    if actual_match is None:
        return False, "invalid_actual_choice"
    actual_value = actual_match.group(0).upper().replace("、", ",")
    correct = re.sub(r"\s+", "", actual_value) == re.sub(r"\s+", "", expected_value)
    return correct, "choice_match" if correct else "choice_mismatch"


def _compare_integer(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = int(_strict_match(_INTEGER, expected, expected=True))
    actual_match = _INTEGER.fullmatch(_normalize_scalar(actual))
    if actual_match is None:
        return False, "invalid_actual_integer"
    correct = int(actual_match.group(0)) == expected_value
    return correct, "integer_match" if correct else "integer_mismatch"


def _compare_fraction(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _parse_fraction(expected, expected=True)
    try:
        actual_value = _parse_fraction(actual, expected=False)
    except ValueError:
        return False, "invalid_actual_fraction"
    correct = actual_value == expected_value
    return correct, "fraction_match" if correct else "fraction_mismatch"


def _compare_symbolic(expected: str, actual: str) -> tuple[bool, str]:
    try:
        expected_value = parse_expression(_normalize_expression(expected))
    except (SyntaxError, TypeError, ValueError) as error:
        raise _ExpectedAnswerError(f"invalid_expected_answer:{type(error).__name__}") from error
    actual_value = parse_expression(_normalize_expression(actual))
    correct = sympy.simplify(actual_value - expected_value) == 0
    return correct, "symbolic_equivalent" if correct else "symbolic_not_equivalent"


def _compare_set(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _parse_set(expected, expected=True)
    try:
        actual_value = _parse_set(actual, expected=False)
    except (SyntaxError, TypeError, ValueError):
        return False, "invalid_actual_set"
    correct = actual_value == expected_value
    return correct, "set_equivalent" if correct else "set_not_equivalent"


def _compare_interval(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _parse_intervals(expected, expected=True)
    try:
        actual_value = _parse_intervals(actual, expected=False)
    except (SyntaxError, TypeError, ValueError):
        return False, "invalid_actual_interval"
    correct = actual_value == expected_value
    return correct, "interval_equivalent" if correct else "interval_not_equivalent"


def _compare_matrix(expected: str, actual: str) -> tuple[bool, str]:
    expected_value = _parse_matrix(expected, expected=True)
    try:
        actual_value = _parse_matrix(actual, expected=False)
    except (SyntaxError, TypeError, ValueError):
        return False, "invalid_actual_matrix"
    if len(actual_value) != len(expected_value) or any(
        len(actual_row) != len(expected_row)
        for actual_row, expected_row in zip(actual_value, expected_value)
    ):
        return False, "matrix_shape_mismatch"
    correct = all(
        sympy.simplify(actual_item - expected_item) == 0
        for actual_row, expected_row in zip(actual_value, expected_value)
        for actual_item, expected_item in zip(actual_row, expected_row)
    )
    return correct, "matrix_equivalent" if correct else "matrix_not_equivalent"


def _parse_fraction(value: str, *, expected: bool) -> sympy.Rational:
    normalized = _normalize_scalar(value)
    match = _FRACTION.fullmatch(normalized)
    if match is None or int(match.group(2)) == 0:
        if expected:
            raise _ExpectedAnswerError("invalid_expected_answer")
        raise ValueError("invalid fraction")
    return sympy.Rational(int(match.group(1)), int(match.group(2)))


def _parse_set(value: str, *, expected: bool) -> frozenset[str]:
    normalized = _normalize_scalar(value).replace(r"\{", "{").replace(r"\}", "}")
    if not (normalized.startswith("{") and normalized.endswith("}")):
        if expected:
            raise _ExpectedAnswerError("invalid_expected_answer")
        raise ValueError("invalid set")
    items = _split_top_level(normalized[1:-1], ",")
    try:
        return frozenset(_canonical_expression(item) for item in items if item.strip())
    except (SyntaxError, TypeError, ValueError) as error:
        if expected:
            raise _ExpectedAnswerError(f"invalid_expected_answer:{type(error).__name__}") from error
        raise


def _parse_intervals(value: str, *, expected: bool) -> Counter:
    normalized = _normalize_scalar(value).replace(r"\cup", "∪")
    parts = [part.strip() for part in re.split(r"\s*(?:∪|\bunion\b)\s*", normalized) if part.strip()]
    intervals: list[tuple[str, str, str, str]] = []
    try:
        for part in parts:
            if len(part) < 5 or part[0] not in "([" or part[-1] not in ")]":
                raise ValueError("invalid interval")
            endpoints = _split_top_level(part[1:-1], ",")
            if len(endpoints) != 2:
                raise ValueError("invalid interval")
            intervals.append(
                (
                    part[0],
                    _canonical_endpoint(endpoints[0]),
                    _canonical_endpoint(endpoints[1]),
                    part[-1],
                )
            )
    except (SyntaxError, TypeError, ValueError) as error:
        if expected:
            raise _ExpectedAnswerError(f"invalid_expected_answer:{type(error).__name__}") from error
        raise
    if not intervals:
        if expected:
            raise _ExpectedAnswerError("invalid_expected_answer")
        raise ValueError("invalid interval")
    return Counter(intervals)


def _parse_matrix(value: str, *, expected: bool) -> list[list[sympy.Expr]]:
    normalized = _normalize_scalar(value)
    latex = re.fullmatch(
        r"\\begin\{(?:p|b|v)?matrix\}(.*?)\\end\{(?:p|b|v)?matrix\}",
        normalized,
        re.DOTALL,
    )
    try:
        if latex:
            rows = [row for row in re.split(r"\\\\", latex.group(1)) if row.strip()]
            raw_rows = [[item.strip() for item in row.split("&")] for row in rows]
        else:
            payload = ast.literal_eval(normalized)
            if not isinstance(payload, (list, tuple)):
                raise ValueError("invalid matrix")
            raw_rows = [list(row) if isinstance(row, (list, tuple)) else [] for row in payload]
        if not raw_rows or any(not row for row in raw_rows):
            raise ValueError("invalid matrix")
        return [[parse_expression(_normalize_expression(str(item))) for item in row] for row in raw_rows]
    except (SyntaxError, TypeError, ValueError) as error:
        if expected:
            raise _ExpectedAnswerError(f"invalid_expected_answer:{type(error).__name__}") from error
        raise


def _canonical_expression(value: str) -> str:
    return sympy.srepr(sympy.simplify(parse_expression(_normalize_expression(value))))


def _canonical_endpoint(value: str) -> str:
    normalized = _normalize_expression(value).lower()
    infinity = {
        "infinity": "oo",
        "+infinity": "oo",
        "inf": "oo",
        "+inf": "oo",
        "∞": "oo",
        "+∞": "oo",
        "-infinity": "-oo",
        "-inf": "-oo",
        "-∞": "-oo",
    }
    if normalized in infinity:
        return infinity[normalized]
    return _canonical_expression(normalized)


def _strict_match(pattern: re.Pattern, value: str, *, expected: bool) -> str:
    match = pattern.fullmatch(_normalize_scalar(value))
    if match is None:
        if expected:
            raise _ExpectedAnswerError("invalid_expected_answer")
        raise ValueError("invalid value")
    return match.group(0)


def _split_top_level(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _normalize_exact(value: str) -> str:
    return re.sub(r"\s+", " ", _unwrap_answer(value)).strip().casefold()


def _normalize_scalar(value: str) -> str:
    return _unwrap_answer(value).strip()


def _normalize_expression(value: str) -> str:
    normalized = _unwrap_answer(value).replace("−", "-").replace("×", "*").replace("÷", "/")
    fraction = re.fullmatch(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", normalized)
    if fraction:
        normalized = f"({fraction.group(1)})/({fraction.group(2)})"
    return normalized.strip()


def _unwrap_answer(value: str) -> str:
    normalized = str(value or "").strip().strip("$").strip()
    boxed = re.fullmatch(r"\\boxed\{(.*)\}", normalized, re.DOTALL)
    if boxed:
        normalized = boxed.group(1).strip()
    return normalized.rstrip(".。")


class _ExpectedAnswerError(ValueError):
    pass
