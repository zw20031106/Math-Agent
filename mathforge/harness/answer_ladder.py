"""Deterministic L1–L5 answer delivery.

The ladder is intentionally small and explicit.  It preserves every useful
answer artifact while keeping verification state separate from deliverability:
an unverified or salvaged answer is degraded, never silently promoted to a
verified candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from mathforge.parsing.answer_extraction import (
    extract_tail_answer,
    sanitize_final_answer,
)
from mathforge.parsing.answer_salvage import salvage_answer_with_source


ANSWER_LEVELS = ("L1", "L2", "L3", "L4", "L5")


@dataclass(frozen=True)
class AnswerLadderResult:
    """One deterministic selection from the answer ladder."""

    answer: str
    source: str
    candidate_id: str = ""
    issues: tuple[str, ...] = ()
    status: str = "success"

    @property
    def degraded(self) -> bool:
        return self.source != "L1"

    @property
    def used_fallback(self) -> bool:
        return self.source == "L5"

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "candidate_id": self.candidate_id,
            "issues": list(self.issues),
            "status": self.status,
            "degraded": self.degraded,
        }


class AnswerLadder:
    """Resolve L1 through L5 in order without skipping an available level."""

    def resolve(
        self,
        *,
        validated_candidates: Iterable[Any] = (),
        unverified_candidates: Iterable[Any] = (),
        raw_model_outputs: Iterable[object] = (),
        fallback: object = "0",
        answer_type: str = "",
        validator: Callable[[str], bool] | None = None,
    ) -> AnswerLadderResult:
        del answer_type  # The parser is type-agnostic; answer-shape gates own types.
        issues: list[str] = []
        # Materialize once: callers commonly pass the provider's bounded
        # response iterator, and L3/L4 both need to inspect the same records.
        raw_outputs = tuple(raw_model_outputs or ())

        for candidate in validated_candidates or ():
            result = _candidate_result(candidate, source="L1", validator=validator)
            if result is not None:
                return result
            issues.extend(_candidate_issues(candidate))

        for candidate in unverified_candidates or ():
            # L2 is deliberately the answer that survived parsing but not the
            # full validation gate.  Reapplying the validator here would turn
            # the unverified level into another rejection and recreate the
            # old all-or-nothing drop to L5.
            result = _candidate_result(candidate, source="L2", validator=None)
            if result is not None:
                return result
            issues.extend(_candidate_issues(candidate))

        salvaged, salvage_source = salvage_answer_with_source(raw_outputs)
        if salvaged:
            answer, sanitize_issues = sanitize_final_answer(salvaged)
            if answer:
                source = salvage_source if salvage_source in {"L3", "L4"} else "L3"
                return AnswerLadderResult(
                    answer=answer,
                    source=source,
                    issues=tuple(dict.fromkeys([*issues, *sanitize_issues])),
                )
            issues.extend(sanitize_issues)

        # Some providers return a tail formula without a label or box.  Keep
        # this as a distinct L4 pass so the metrics show whether boxed salvage
        # or tail extraction is carrying the run.
        for raw in reversed(raw_outputs):
            tail = extract_tail_answer(raw)
            answer, sanitize_issues = sanitize_final_answer(tail)
            if answer:
                return AnswerLadderResult(
                    answer=answer,
                    source="L4",
                    issues=tuple(dict.fromkeys([*issues, *sanitize_issues])),
                )
            issues.extend(sanitize_issues)

        normalized_fallback, fallback_issues = sanitize_final_answer(fallback)
        if not normalized_fallback:
            normalized_fallback = "0"
        return AnswerLadderResult(
            answer=normalized_fallback,
            source="L5",
            issues=tuple(dict.fromkeys([*issues, *fallback_issues])),
            status="failed",
        )


def resolve_answer_ladder(**kwargs: Any) -> AnswerLadderResult:
    """Functional entry point used by terminal and runtime paths."""

    return AnswerLadder().resolve(**kwargs)


def select_answer(**kwargs: Any) -> AnswerLadderResult:
    """Compatibility alias for callers that prefer selection terminology."""

    return resolve_answer_ladder(**kwargs)


def _candidate_result(
    candidate: Any,
    *,
    source: str,
    validator: Callable[[str], bool] | None,
) -> AnswerLadderResult | None:
    if isinstance(candidate, dict):
        answer_value = candidate.get(
            "final_answer",
            candidate.get("answer", candidate.get("final_response", "")),
        )
        candidate_id = str(candidate.get("candidate_id", ""))
    else:
        answer_value = getattr(
            candidate,
            "final_answer",
            getattr(candidate, "answer", getattr(candidate, "final_response", "")),
        )
        candidate_id = str(getattr(candidate, "candidate_id", ""))
    answer, issues = sanitize_final_answer(answer_value)
    if not answer or "placeholder_leak" in issues:
        return None
    if validator is not None:
        try:
            if not bool(validator(answer)):
                return None
        except Exception:
            return None
    return AnswerLadderResult(
        answer=answer,
        source=source,
        candidate_id=candidate_id,
        issues=tuple(issues),
    )


def _candidate_issues(candidate: Any) -> tuple[str, ...]:
    value = candidate.get("contract_deviations", ()) if isinstance(candidate, dict) else getattr(candidate, "contract_deviations", ())
    return tuple(str(item) for item in value or () if str(item).strip())


__all__ = [
    "ANSWER_LEVELS",
    "AnswerLadder",
    "AnswerLadderResult",
    "resolve_answer_ladder",
    "select_answer",
]
