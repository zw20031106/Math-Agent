"""Deterministic rendering of a verified proof backbone.

The public proof response is intentionally derived from Host-owned claims and
their verification state.  A model's free-form ``solution_text`` is retained
as a compatibility fallback for old candidates, but it is never used as the
semantic source when a verified claim closure is available.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from mathforge.harness.truncation import ProofBackbone
from mathforge.output.deterministic_formatter import exact_final_answer


_VERIFIED_STATUSES = frozenset(
    {
        "accepted",
        "audited",
        "complete",
        "formally_verified",
        "hard_verified",
        "pass",
        "supported",
        "verified",
    }
)
_VERIFIED_STATES = frozenset(
    {
        "audited",
        "formally_verified",
        "hard_verified",
        "numerically_supported",
        "semantically_verified",
        "supported",
        "verified",
    }
)
_REJECTED_VALUES = frozenset(
    {"failed", "fail", "rejected", "superseded", "unknown", "unverified"}
)
_WHITESPACE = re.compile(r"\s+")
_ANSWER_LABEL = re.compile(
    r"^\s*(?:(?:final\s*)?answer|最终答案|答案)\s*[:：]\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProofRenderResult:
    """Proof text plus the deterministic coverage decision behind it."""

    text: str
    candidate_id: str = ""
    candidate_version: int = 1
    required_claim_ids: tuple[str, ...] = ()
    verified_claim_ids: tuple[str, ...] = ()
    rendered_claim_ids: tuple[str, ...] = ()
    missing_claim_ids: tuple[str, ...] = ()
    coverage: float = 0.0
    conclusion_claim_id: str = ""
    conclusion: str = ""
    complete: bool = False
    structured: bool = False
    fallback_used: bool = False
    emergency_fallback: bool = False

    @property
    def coverage_complete(self) -> bool:
        return self.complete and not self.missing_claim_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "required_claim_ids": list(self.required_claim_ids),
            "verified_claim_ids": list(self.verified_claim_ids),
            "rendered_claim_ids": list(self.rendered_claim_ids),
            "missing_claim_ids": list(self.missing_claim_ids),
            "coverage": self.coverage,
            "conclusion_claim_id": self.conclusion_claim_id,
            "conclusion": self.conclusion,
            "complete": self.complete,
            "structured": self.structured,
            "fallback_used": self.fallback_used,
            "emergency_fallback": self.emergency_fallback,
        }


class VerifiedProofRenderer:
    """Render a concise proof from verified claims in dependency order.

    The renderer is deliberately conservative.  A claim with no positive
    verification state is not silently promoted to a proof step.  If a legacy
    candidate has no structured verified claims, its existing public steps are
    returned as an explicitly degraded compatibility fallback.
    """

    def __init__(self, *, max_chars: int | None = None) -> None:
        if max_chars is not None and max_chars < 0:
            raise ValueError("proof renderer max_chars must be nonnegative")
        self.max_chars = max_chars

    def render(
        self,
        candidate: Any,
        proof_backbone: ProofBackbone | None = None,
        verification_closure: Any | None = None,
        *,
        closure: Any | None = None,
        verified_claim_ids: Iterable[str] = (),
        evidence: Iterable[Any] = (),
        max_chars: int | None = None,
    ) -> ProofRenderResult:
        if verification_closure is None:
            verification_closure = closure
        claims = tuple(getattr(candidate, "claims", ()) or ())
        by_id = {
            str(getattr(claim, "claim_id", "")): claim
            for claim in claims
            if str(getattr(claim, "claim_id", ""))
        }
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        candidate_version = _positive_int(getattr(candidate, "version", 1))
        answer = exact_final_answer(
            str(getattr(candidate, "final_answer", "")),
            str(getattr(candidate, "answer_type", "text")),
        )

        backbone = proof_backbone
        if backbone is None:
            try:
                backbone = ProofBackbone.from_candidate(candidate)
            except (TypeError, ValueError, AttributeError):
                backbone = ProofBackbone()

        conclusion_id = str(
            getattr(verification_closure, "conclusion_claim_id", "")
            or getattr(backbone, "terminal_claim_id", "")
        )
        if not conclusion_id and claims:
            conclusion_id = str(getattr(claims[-1], "claim_id", ""))
        conclusion = str(
            getattr(backbone, "terminal_conclusion", "")
            or getattr(by_id.get(conclusion_id), "statement", "")
            or answer
        ).strip()

        required = _required_claim_ids(backbone, verification_closure, by_id)
        ordered = _dependency_first_order(
            by_id,
            (*getattr(backbone, "necessary_support_claim_ids", ()),
             *getattr(backbone, "critical_claim_ids", ()),
             *required,
             conclusion_id),
        )
        if not required:
            required = tuple(ordered)
        required_set = set(required)
        explicit_verified = {
            str(item).strip()
            for item in verified_claim_ids
            if str(item).strip() in by_id
        }
        inferred_verified = {
            claim_id
            for claim_id, claim in by_id.items()
            if _claim_verified(claim)
        }
        evidence_verified = _evidence_verified_claims(evidence, candidate_id)
        closure_verified = _closure_verified_claims(
            verification_closure,
            by_id,
            conclusion_id,
        )
        verified = explicit_verified | inferred_verified | evidence_verified | closure_verified
        verified &= set(by_id)
        verified_ordered = tuple(item for item in ordered if item in verified)
        missing = tuple(item for item in required if item not in verified)
        coverage = (
            1.0
            if not required
            else round((len(required_set) - len(set(missing))) / len(required_set), 6)
        )
        structured = bool(verified_ordered and claims)

        if structured:
            rendered_ids = tuple(item for item in ordered if item in verified)
            text = self._render_claims(
                [by_id[item] for item in rendered_ids],
                answer=answer,
            )
            limit = self.max_chars if max_chars is None else max_chars
            text, rendered_ids, emergency = self._bound_semantically(
                text,
                rendered_ids,
                by_id,
                required=required,
                answer=answer,
                max_chars=limit,
            )
            complete = not missing and conclusion_id in set(rendered_ids)
            return ProofRenderResult(
                text=text,
                candidate_id=candidate_id,
                candidate_version=candidate_version,
                required_claim_ids=required,
                verified_claim_ids=tuple(item for item in ordered if item in verified),
                rendered_claim_ids=rendered_ids,
                missing_claim_ids=missing,
                coverage=coverage,
                conclusion_claim_id=conclusion_id,
                conclusion=conclusion,
                complete=complete and not emergency,
                structured=True,
                fallback_used=False,
                emergency_fallback=emergency,
            )

        legacy = _legacy_body(candidate)
        legacy_text = _append_answer(legacy, answer)
        limit = self.max_chars if max_chars is None else max_chars
        if limit is not None and limit > 0 and len(legacy_text) > limit:
            # There is no verified semantic unit to clip safely.  Returning
            # the exact answer is safer than inventing a partial derivation.
            return ProofRenderResult(
                text=answer[:limit] if answer else legacy_text[:limit],
                candidate_id=candidate_id,
                candidate_version=candidate_version,
                required_claim_ids=required,
                verified_claim_ids=tuple(item for item in ordered if item in verified),
                rendered_claim_ids=(),
                missing_claim_ids=missing or required,
                coverage=coverage,
                conclusion_claim_id=conclusion_id,
                conclusion=conclusion,
                complete=False,
                structured=False,
                fallback_used=True,
                emergency_fallback=True,
            )
        return ProofRenderResult(
            text=legacy_text,
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            required_claim_ids=required,
            verified_claim_ids=tuple(item for item in ordered if item in verified),
            rendered_claim_ids=(),
            missing_claim_ids=missing or required,
            coverage=coverage,
            conclusion_claim_id=conclusion_id,
            conclusion=conclusion,
            complete=False,
            structured=False,
            fallback_used=True,
            emergency_fallback=False,
        )

    @staticmethod
    def _render_claims(claims: Iterable[Any], *, answer: str) -> str:
        lines: list[str] = []
        for index, claim in enumerate(claims, start=1):
            statement = _clean_statement(getattr(claim, "statement", ""))
            if statement:
                lines.append(f"{index}. {statement}")
        if answer:
            lines.append(f"因此，答案为：{answer}")
        return "\n".join(lines).strip()

    @staticmethod
    def _bound_semantically(
        text: str,
        rendered_ids: tuple[str, ...],
        by_id: Mapping[str, Any],
        *,
        required: tuple[str, ...],
        answer: str,
        max_chars: int | None,
    ) -> tuple[str, tuple[str, ...], bool]:
        if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
            return text, rendered_ids, False
        required_set = set(required)
        # Drop non-required supporting claims first.  This is semantic
        # compaction; it does not cut a claim in the middle.
        kept = list(rendered_ids)
        for claim_id in tuple(reversed(kept)):
            if claim_id in required_set:
                continue
            kept.remove(claim_id)
            candidate_text = VerifiedProofRenderer._render_claims(
                [by_id[item] for item in kept], answer=answer
            )
            if len(candidate_text) <= max_chars:
                return candidate_text, tuple(kept), False
        candidate_text = VerifiedProofRenderer._render_claims(
            [by_id[item] for item in kept], answer=answer
        )
        if len(candidate_text) <= max_chars:
            return candidate_text, tuple(kept), False
        # All remaining units are required.  A hard character boundary is an
        # emergency fallback and explicitly marks coverage as degraded.
        return (answer[:max_chars] if answer else candidate_text[:max_chars]), tuple(kept), True


def render_verified_proof(
    candidate: Any,
    **kwargs: Any,
) -> ProofRenderResult:
    """Functional convenience wrapper for :class:`VerifiedProofRenderer`."""

    return VerifiedProofRenderer().render(candidate, **kwargs)


def _required_claim_ids(
    backbone: ProofBackbone,
    closure: Any | None,
    by_id: Mapping[str, Any],
) -> tuple[str, ...]:
    values: list[str] = []
    for source in (
        getattr(backbone, "necessary_support_claim_ids", ()),
        getattr(backbone, "critical_claim_ids", ()),
        getattr(closure, "critical_claim_ids", ()) if closure is not None else (),
    ):
        for item in source:
            item = str(item)
            if item in by_id and item not in values:
                values.append(item)
    terminal = str(getattr(closure, "conclusion_claim_id", "") if closure is not None else "")
    if not terminal:
        terminal = str(getattr(backbone, "terminal_claim_id", ""))
    if terminal in by_id and terminal not in values:
        values.append(terminal)
    return tuple(values)


def _dependency_first_order(
    by_id: Mapping[str, Any],
    requested: Iterable[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visited or claim_id not in by_id:
            return
        if claim_id in visiting:
            return
        visiting.add(claim_id)
        for dependency in getattr(by_id[claim_id], "depends_on", ()) or ():
            visit(str(dependency))
        visiting.remove(claim_id)
        visited.add(claim_id)
        ordered.append(claim_id)

    for claim_id in requested:
        visit(str(claim_id))
    return tuple(ordered)


def _claim_verified(claim: Any) -> bool:
    status = str(getattr(claim, "status", "")).strip().casefold()
    state = str(getattr(claim, "verification_state", "")).strip().casefold()
    check_type = str(getattr(claim, "check_type", "")).strip().casefold()
    if status in _REJECTED_VALUES or state in _REJECTED_VALUES:
        return False
    # Syntax/shape checks establish parseability, not mathematical proof
    # validity.  They must not turn a degraded proof into a verified one.
    if "syntax" in check_type or "latex" in check_type:
        return state in {
            "semantically_verified",
            "hard_verified",
            "audited",
            "formally_verified",
        }
    return status in _VERIFIED_STATUSES or state in _VERIFIED_STATES


def _closure_verified_claims(
    closure: Any | None,
    by_id: Mapping[str, Any],
    conclusion_id: str,
) -> set[str]:
    if closure is None or not bool(getattr(closure, "hard_verified", False)):
        return set()
    values = set(
        str(item)
        for item in getattr(closure, "critical_claim_ids", ())
        if str(item) in by_id
    )
    if conclusion_id in by_id:
        values.add(conclusion_id)
    return values


def _evidence_verified_claims(
    evidence: Iterable[Any],
    candidate_id: str,
) -> set[str]:
    values: set[str] = set()
    for record in evidence or ():
        if str(getattr(record, "candidate_id", "")) != candidate_id:
            continue
        if str(getattr(record, "status", "")).casefold() != "pass":
            continue
        if str(getattr(record, "strength", "")).casefold() != "hard":
            continue
        evidence_type = str(getattr(record, "evidence_type", "")).casefold()
        capability = str(getattr(record, "capability", "")).casefold()
        if "syntax" in evidence_type or "latex" in evidence_type:
            continue
        if "syntax" in capability or "latex" in capability:
            continue
        claim_id = str(getattr(record, "claim_id", ""))
        if claim_id:
            values.add(claim_id)
    return values


def _legacy_body(candidate: Any) -> str:
    solution = str(getattr(candidate, "solution_text", "") or "").strip()
    if not solution:
        solution = "\n".join(
            str(item).strip()
            for item in getattr(candidate, "public_solution_steps", ()) or ()
            if str(item).strip()
        ).strip()
    solution = _ANSWER_LABEL.sub("", solution).strip()
    return solution


def _append_answer(body: str, answer: str) -> str:
    body = str(body or "").strip()
    if not answer:
        return body
    last_line = next(
        (line.strip() for line in reversed(body.splitlines()) if line.strip()),
        "",
    )
    return body if last_line == answer else f"{body}\n\n{answer}" if body else answer


def _clean_statement(value: Any) -> str:
    text = _WHITESPACE.sub(" ", str(value or "")).strip()
    return text.replace("\x00", " ")


def _positive_int(value: Any) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


__all__ = ["ProofRenderResult", "VerifiedProofRenderer", "render_verified_proof"]
