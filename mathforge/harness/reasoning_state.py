from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import re
from typing import Any, ClassVar

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import InternS2TokenCounter
from mathforge.harness.schemas import CandidateSolution, ProblemIR


REASONING_STATE_SCHEMA_VERSION = "2.0"
REASONING_STATE_MAX_TOKENS = 32768
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_PRIVATE_KEYS = re.compile(
    r"^(?:chain[_-]?of[_-]?thought|scratchpad|hidden[_-]?reasoning|"
    r"private[_-]?reasoning|raw_(?:response|prompt|completion))$",
    re.I,
)
_SUBGOAL_STATUSES = frozenset({"open", "active", "closed", "blocked"})
_CLAIM_STATUSES = frozenset(
    {
        # ``pending``/``accepted`` are retained as wire-compatible aliases
        # for the pre-V2 progress protocol.  New lifecycle transitions use
        # the more explicit V2 names.
        "pending",
        "accepted",
        "proposed",
        "supported",
        "verified",
        "challenged",
        "rejected",
        "superseded",
        "archived",
    }
)
_ACTIVE_CLAIM_STATUSES = frozenset(
    {"pending", "accepted", "proposed", "supported", "verified", "challenged"}
)
_PROGRESS_MODES = frozenset({"explore", "continue"})
_CLAIM_KINDS = frozenset(
    {
        "unknown",
        "reasoning",
        "definition",
        "theorem_preconditions",
        "necessity",
        "sufficiency",
        "existence",
        "uniqueness",
        "boundary",
        "interchange",
        "equality",
        "matrix_shape",
        "probability_normalization",
        "finite_case",
        "answer_shape",
    }
)


class ReasoningStateValidationError(ValueError):
    pass


def _string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise ReasoningStateValidationError(f"{name} must be a string list")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


def _public_id(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not _PUBLIC_ID.fullmatch(normalized):
        raise ReasoningStateValidationError(f"{name} is invalid")
    return normalized


@dataclass(frozen=True)
class ProblemFrame:
    original_problem: str
    normalized_problem: str
    definitions: tuple[str, ...]
    quantifiers: tuple[str, ...]
    constraints: tuple[str, ...]
    assumptions: tuple[str, ...]
    target: str
    target_kind: str
    answer_type: str

    @classmethod
    def from_problem_ir(cls, problem: ProblemIR) -> "ProblemFrame":
        frame = cls(
            original_problem=problem.raw_problem,
            normalized_problem=problem.normalized_problem,
            definitions=tuple(problem.definitions),
            quantifiers=tuple(problem.quantifiers),
            constraints=tuple(problem.constraints),
            assumptions=tuple(problem.assumptions),
            target=problem.target_phrase or problem.requested_output,
            target_kind=problem.target_kind,
            answer_type=problem.answer_type,
        )
        frame.validate()
        return frame

    def validate(self) -> None:
        strings = (
            self.original_problem,
            self.normalized_problem,
            self.target,
            self.target_kind,
            self.answer_type,
        )
        if any(not isinstance(value, str) for value in strings):
            raise ReasoningStateValidationError(
                "ProblemFrame string field has invalid type"
            )
        if not self.normalized_problem.strip():
            raise ReasoningStateValidationError(
                "ProblemFrame normalized problem is empty"
            )
        for name in ("definitions", "quantifiers", "constraints", "assumptions"):
            _string_list(getattr(self, name), f"ProblemFrame.{name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_problem": self.original_problem,
            "normalized_problem": self.normalized_problem,
            "definitions": list(self.definitions),
            "quantifiers": list(self.quantifiers),
            "constraints": list(self.constraints),
            "assumptions": list(self.assumptions),
            "target": self.target,
            "target_kind": self.target_kind,
            "answer_type": self.answer_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProblemFrame":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "ProblemFrame payload must be an object"
            )
        expected = {
            "original_problem",
            "normalized_problem",
            "definitions",
            "quantifiers",
            "constraints",
            "assumptions",
            "target",
            "target_kind",
            "answer_type",
        }
        if set(payload) != expected:
            raise ReasoningStateValidationError(
                "ProblemFrame fields do not match the public schema"
            )
        frame = cls(
            original_problem=str(payload["original_problem"]),
            normalized_problem=str(payload["normalized_problem"]),
            definitions=_string_list(
                payload["definitions"], "ProblemFrame.definitions"
            ),
            quantifiers=_string_list(
                payload["quantifiers"], "ProblemFrame.quantifiers"
            ),
            constraints=_string_list(
                payload["constraints"], "ProblemFrame.constraints"
            ),
            assumptions=_string_list(
                payload["assumptions"], "ProblemFrame.assumptions"
            ),
            target=str(payload["target"]),
            target_kind=str(payload["target_kind"]),
            answer_type=str(payload["answer_type"]),
        )
        frame.validate()
        return frame


@dataclass(frozen=True)
class Subgoal:
    subgoal_id: str
    statement: str
    depends_on: tuple[str, ...] = ()
    exit_condition: str = ""
    status: str = "open"

    def validate(self) -> None:
        _public_id(self.subgoal_id, "Subgoal.subgoal_id")
        if not self.statement.strip():
            raise ReasoningStateValidationError("Subgoal statement is empty")
        if self.status not in _SUBGOAL_STATUSES:
            raise ReasoningStateValidationError("Subgoal status is invalid")
        for dependency in self.depends_on:
            _public_id(dependency, "Subgoal.depends_on")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subgoal_id": self.subgoal_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
            "exit_condition": self.exit_condition,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Subgoal":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "Subgoal payload must be an object"
            )
        expected = {
            "subgoal_id",
            "statement",
            "depends_on",
            "exit_condition",
            "status",
        }
        if set(payload) != expected:
            raise ReasoningStateValidationError(
                "Subgoal fields do not match the public schema"
            )
        subgoal = cls(
            subgoal_id=_public_id(payload["subgoal_id"], "Subgoal.subgoal_id"),
            statement=str(payload["statement"]).strip(),
            depends_on=_string_list(payload["depends_on"], "Subgoal.depends_on"),
            exit_condition=str(payload["exit_condition"]).strip(),
            status=str(payload["status"]).strip(),
        )
        subgoal.validate()
        return subgoal


@dataclass(frozen=True)
class SubgoalLedger:
    items: tuple[Subgoal, ...] = ()

    def validate(self) -> None:
        by_id = {item.subgoal_id: item for item in self.items}
        if len(by_id) != len(self.items):
            raise ReasoningStateValidationError("duplicate Subgoal id")
        for item in self.items:
            item.validate()
            unknown = set(item.depends_on) - set(by_id)
            if unknown:
                raise ReasoningStateValidationError(
                    f"unknown Subgoal dependency: {sorted(unknown)}"
                )
        _validate_acyclic(
            {item.subgoal_id: item.depends_on for item in self.items},
            "Subgoal",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubgoalLedger":
        if not isinstance(payload, dict) or set(payload) != {"items"}:
            raise ReasoningStateValidationError(
                "SubgoalLedger payload is invalid"
            )
        raw = payload["items"]
        if not isinstance(raw, list):
            raise ReasoningStateValidationError(
                "SubgoalLedger.items must be a list"
            )
        ledger = cls(tuple(Subgoal.from_dict(item) for item in raw))
        ledger.validate()
        return ledger


@dataclass(frozen=True)
class PublicClaim:
    claim_id: str
    statement: str
    depends_on: tuple[str, ...] = ()
    subgoal_ids: tuple[str, ...] = ()
    status: str = "pending"
    importance: str = "supporting"
    check_type: str = "reasoning"
    claim_kind: str = "reasoning"
    version: int = 1
    supersedes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    branch_id: str = "branch-main"

    def validate(self) -> None:
        _public_id(self.claim_id, "PublicClaim.claim_id")
        if not self.statement.strip():
            raise ReasoningStateValidationError("PublicClaim statement is empty")
        if self.status not in _CLAIM_STATUSES:
            raise ReasoningStateValidationError("PublicClaim status is invalid")
        if type(self.version) is not int or self.version < 1:
            raise ReasoningStateValidationError("PublicClaim version is invalid")
        if self.importance not in {"critical", "supporting"}:
            raise ReasoningStateValidationError(
                "PublicClaim importance is invalid"
            )
        _public_id(self.check_type, "PublicClaim.check_type")
        if self.claim_kind not in _CLAIM_KINDS:
            raise ReasoningStateValidationError(
                "PublicClaim claim_kind is invalid"
            )
        _public_id(self.branch_id, "PublicClaim.branch_id")
        for dependency in self.depends_on:
            _public_id(dependency, "PublicClaim.depends_on")
        for subgoal_id in self.subgoal_ids:
            _public_id(subgoal_id, "PublicClaim.subgoal_ids")
        for claim_id in self.supersedes:
            _public_id(claim_id, "PublicClaim.supersedes")
        for reference in (*self.evidence_refs, *self.provenance):
            _public_id(reference, "PublicClaim evidence/provenance reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
            "subgoal_ids": list(self.subgoal_ids),
            "status": self.status,
            "importance": self.importance,
            "check_type": self.check_type,
            "claim_kind": self.claim_kind,
            "version": self.version,
            "supersedes": list(self.supersedes),
            "evidence_refs": list(self.evidence_refs),
            "provenance": list(self.provenance),
            "branch_id": self.branch_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublicClaim":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "PublicClaim payload must be an object"
            )
        legacy_expected = {
            "claim_id",
            "statement",
            "depends_on",
            "subgoal_ids",
            "status",
            "importance",
            "check_type",
        }
        v2_fields = {
            "claim_kind",
            "version",
            "supersedes",
            "evidence_refs",
            "provenance",
            "branch_id",
        }
        if not legacy_expected <= set(payload) or bool(
            set(payload) - legacy_expected - v2_fields
        ):
            raise ReasoningStateValidationError(
                "PublicClaim fields do not match the public schema"
            )
        claim = cls(
            claim_id=_public_id(
                payload["claim_id"], "PublicClaim.claim_id"
            ),
            statement=str(payload["statement"]).strip(),
            depends_on=_string_list(
                payload["depends_on"], "PublicClaim.depends_on"
            ),
            subgoal_ids=_string_list(
                payload["subgoal_ids"], "PublicClaim.subgoal_ids"
            ),
            status=str(payload["status"]).strip(),
            importance=str(payload["importance"]).strip(),
            check_type=str(payload["check_type"]).strip(),
            claim_kind=str(payload.get("claim_kind", "reasoning")).strip(),
            version=int(payload.get("version", 1)),
            supersedes=_string_list(
                payload.get("supersedes", []), "PublicClaim.supersedes"
            ),
            evidence_refs=_string_list(
                payload.get("evidence_refs", []), "PublicClaim.evidence_refs"
            ),
            provenance=_string_list(
                payload.get("provenance", []), "PublicClaim.provenance"
            ),
            branch_id=_public_id(
                payload.get("branch_id", "branch-main"),
                "PublicClaim.branch_id",
            ),
        )
        claim.validate()
        return claim


@dataclass(frozen=True)
class ClaimLedger:
    items: tuple[PublicClaim, ...] = ()

    def validate(
        self,
        subgoal_ids: set[str],
        branch_id: str | None = None,
    ) -> None:
        by_id = {item.claim_id: item for item in self.items}
        if len(by_id) != len(self.items):
            raise ReasoningStateValidationError("duplicate PublicClaim id")
        for item in self.items:
            item.validate()
            if branch_id is not None and item.branch_id != branch_id:
                raise ReasoningStateValidationError(
                    "PublicClaim branch does not match ReasoningState branch"
                )
            unknown_claims = set(item.depends_on) - set(by_id)
            if unknown_claims:
                raise ReasoningStateValidationError(
                    f"unknown PublicClaim dependency: {sorted(unknown_claims)}"
                )
            unknown_subgoals = set(item.subgoal_ids) - subgoal_ids
            if unknown_subgoals:
                raise ReasoningStateValidationError(
                    f"unknown PublicClaim Subgoal: {sorted(unknown_subgoals)}"
                )
        _validate_acyclic(
            {item.claim_id: item.depends_on for item in self.items},
            "PublicClaim",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClaimLedger":
        if not isinstance(payload, dict) or set(payload) != {"items"}:
            raise ReasoningStateValidationError("ClaimLedger payload is invalid")
        raw = payload["items"]
        if not isinstance(raw, list):
            raise ReasoningStateValidationError(
                "ClaimLedger.items must be a list"
            )
        return cls(tuple(PublicClaim.from_dict(item) for item in raw))


@dataclass(frozen=True)
class OpenObligation:
    obligation_id: str
    statement: str
    depends_on: tuple[str, ...] = ()

    def validate(self) -> None:
        _public_id(self.obligation_id, "OpenObligation.obligation_id")
        if not self.statement.strip():
            raise ReasoningStateValidationError(
                "OpenObligation statement is empty"
            )
        for dependency in self.depends_on:
            _public_id(dependency, "OpenObligation.depends_on")

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OpenObligation":
        if not isinstance(payload, dict) or set(payload) != {
            "obligation_id",
            "statement",
            "depends_on",
        }:
            raise ReasoningStateValidationError(
                "OpenObligation payload is invalid"
            )
        item = cls(
            obligation_id=_public_id(
                payload["obligation_id"], "OpenObligation.obligation_id"
            ),
            statement=str(payload["statement"]).strip(),
            depends_on=_string_list(
                payload["depends_on"], "OpenObligation.depends_on"
            ),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class RoundDelta:
    round_index: int
    mode: str
    public_summary: str
    strategy: str
    subgoals: tuple[Subgoal, ...] = ()
    claims: tuple[PublicClaim, ...] = ()
    open_obligations: tuple[OpenObligation, ...] = ()
    closed_obligation_ids: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    next_step: str = ""
    stop_reason: str = ""
    information_gain: int = 0

    def validate(self) -> None:
        if type(self.round_index) is not int or self.round_index < 1:
            raise ReasoningStateValidationError("RoundDelta index is invalid")
        if self.mode not in {"explore", "continue", "synthesize"}:
            raise ReasoningStateValidationError("RoundDelta mode is invalid")
        if type(self.information_gain) is not int or self.information_gain < 0:
            raise ReasoningStateValidationError(
                "RoundDelta information gain is invalid"
            )
        for subgoal in self.subgoals:
            subgoal.validate()
        for claim in self.claims:
            claim.validate()
        for obligation in self.open_obligations:
            obligation.validate()
        for obligation_id in self.closed_obligation_ids:
            _public_id(
                obligation_id,
                "RoundDelta.closed_obligation_ids",
            )
        _string_list(self.contradictions, "RoundDelta.contradictions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "mode": self.mode,
            "public_summary": self.public_summary,
            "strategy": self.strategy,
            "subgoals": [item.to_dict() for item in self.subgoals],
            "claims": [item.to_dict() for item in self.claims],
            "open_obligations": [
                item.to_dict() for item in self.open_obligations
            ],
            "closed_obligation_ids": list(self.closed_obligation_ids),
            "contradictions": list(self.contradictions),
            "next_step": self.next_step,
            "stop_reason": self.stop_reason,
            "information_gain": self.information_gain,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "mode": self.mode,
            "subgoal_ids": [item.subgoal_id for item in self.subgoals],
            "claim_ids": [item.claim_id for item in self.claims],
            "open_obligation_ids": [
                item.obligation_id for item in self.open_obligations
            ],
            "closed_obligation_ids": list(self.closed_obligation_ids),
            "information_gain": self.information_gain,
            "next_step": self.next_step,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoundDelta":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "RoundDelta payload must be an object"
            )
        expected = {
            "round_index",
            "mode",
            "public_summary",
            "strategy",
            "subgoals",
            "claims",
            "open_obligations",
            "closed_obligation_ids",
            "contradictions",
            "next_step",
            "stop_reason",
            "information_gain",
        }
        if set(payload) != expected:
            raise ReasoningStateValidationError(
                "RoundDelta fields do not match the public schema"
            )
        delta = cls(
            round_index=int(payload["round_index"]),
            mode=str(payload["mode"]),
            public_summary=str(payload["public_summary"]),
            strategy=str(payload["strategy"]),
            subgoals=tuple(
                Subgoal.from_dict(item) for item in _object_list(
                    payload["subgoals"], "RoundDelta.subgoals"
                )
            ),
            claims=tuple(
                PublicClaim.from_dict(item) for item in _object_list(
                    payload["claims"], "RoundDelta.claims"
                )
            ),
            open_obligations=tuple(
                OpenObligation.from_dict(item) for item in _object_list(
                    payload["open_obligations"],
                    "RoundDelta.open_obligations",
                )
            ),
            closed_obligation_ids=_string_list(
                payload["closed_obligation_ids"],
                "RoundDelta.closed_obligation_ids",
            ),
            contradictions=_string_list(
                payload["contradictions"], "RoundDelta.contradictions"
            ),
            next_step=str(payload["next_step"]),
            stop_reason=str(payload["stop_reason"]),
            information_gain=int(payload["information_gain"]),
        )
        delta.validate()
        return delta


@dataclass(frozen=True)
class PublicToolResult:
    work_item_id: str
    claim_id: str
    tool_name: str
    status: str
    strength: str
    summary: str
    public_payload: dict[str, Any]
    result_digest: str
    impact: str
    reason_code: str

    def validate(self) -> None:
        _public_id(self.work_item_id, "PublicToolResult.work_item_id")
        _public_id(self.claim_id, "PublicToolResult.claim_id")
        _public_id(self.tool_name, "PublicToolResult.tool_name")
        if self.status not in {"pass", "fail", "unknown", "error"}:
            raise ReasoningStateValidationError(
                "PublicToolResult status is invalid"
            )
        if self.strength not in {"none", "soft", "medium", "hard"}:
            raise ReasoningStateValidationError(
                "PublicToolResult strength is invalid"
            )
        if not self.summary.strip() or len(self.summary) > 2048:
            raise ReasoningStateValidationError(
                "PublicToolResult summary is invalid"
            )
        if not isinstance(self.public_payload, dict):
            raise ReasoningStateValidationError(
                "PublicToolResult payload must be an object"
            )
        serialized = json.dumps(
            self.public_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if len(serialized) > 8192 or any(
            _PRIVATE_KEYS.fullmatch(str(key))
            for key in _nested_keys(self.public_payload)
        ):
            raise ReasoningStateValidationError(
                "PublicToolResult payload is unsafe or too large"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.result_digest):
            raise ReasoningStateValidationError(
                "PublicToolResult digest is invalid"
            )
        if self.impact not in {
            "confirm_strategy",
            "switch_strategy",
            "request_clarification",
            "no_change",
        }:
            raise ReasoningStateValidationError(
                "PublicToolResult impact is invalid"
            )
        _public_id(self.reason_code, "PublicToolResult.reason_code")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "work_item_id": self.work_item_id,
            "claim_id": self.claim_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "strength": self.strength,
            "summary": self.summary,
            "public_payload": dict(self.public_payload),
            "result_digest": self.result_digest,
            "impact": self.impact,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublicToolResult":
        expected = {
            "work_item_id",
            "claim_id",
            "tool_name",
            "status",
            "strength",
            "summary",
            "public_payload",
            "result_digest",
            "impact",
            "reason_code",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ReasoningStateValidationError(
                "PublicToolResult fields do not match the public schema"
            )
        result = cls(
            work_item_id=str(payload["work_item_id"]),
            claim_id=str(payload["claim_id"]),
            tool_name=str(payload["tool_name"]),
            status=str(payload["status"]),
            strength=str(payload["strength"]),
            summary=str(payload["summary"]),
            public_payload=dict(payload["public_payload"]),
            result_digest=str(payload["result_digest"]),
            impact=str(payload["impact"]),
            reason_code=str(payload["reason_code"]),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class ReasoningState:
    SCHEMA_VERSION: ClassVar[str] = REASONING_STATE_SCHEMA_VERSION

    state_id: str
    version: int
    problem_frame: ProblemFrame
    subgoal_ledger: SubgoalLedger = field(default_factory=SubgoalLedger)
    claim_ledger: ClaimLedger = field(default_factory=ClaimLedger)
    open_obligations: tuple[OpenObligation, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    tool_results: tuple[PublicToolResult, ...] = ()
    contradictions: tuple[str, ...] = ()
    strategy: str = ""
    rounds: tuple[RoundDelta, ...] = ()
    schema_version: str = REASONING_STATE_SCHEMA_VERSION
    session_id: str = "session-default"
    branch_id: str = "branch-main"
    agent_id: str = "reasoning"

    @classmethod
    def initialize(
        cls,
        problem: ProblemIR,
        *,
        strategy: str = "",
        session_id: str = "session-default",
        branch_id: str = "branch-main",
        agent_id: str = "reasoning",
    ) -> "ReasoningState":
        frame = ProblemFrame.from_problem_ir(problem)
        session_id = _public_id(session_id, "ReasoningState.session_id")
        branch_id = _public_id(branch_id, "ReasoningState.branch_id")
        agent_id = _public_id(agent_id, "ReasoningState.agent_id")
        digest = sha256(
            json.dumps(
                {
                    "frame": frame.to_dict(),
                    "session_id": session_id,
                    "branch_id": branch_id,
                    "agent_id": agent_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]
        state = cls(
            # The digest binds the full identifiers; bounded fragments keep
            # the public ID within the protocol's 96-character limit.
            state_id=(
                f"rs-{digest}-{session_id[:20]}-{branch_id[:20]}-"
                f"{agent_id[:20]}"
            ),
            version=1,
            problem_frame=frame,
            strategy=strategy,
            session_id=session_id,
            branch_id=branch_id,
            agent_id=agent_id,
        )
        state.validate()
        return state

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise ReasoningStateValidationError(
                "ReasoningState schema version is invalid"
            )
        _public_id(self.state_id, "ReasoningState.state_id")
        _public_id(self.session_id, "ReasoningState.session_id")
        _public_id(self.branch_id, "ReasoningState.branch_id")
        _public_id(self.agent_id, "ReasoningState.agent_id")
        if type(self.version) is not int or self.version != len(self.rounds) + 1:
            raise ReasoningStateValidationError(
                "ReasoningState version does not match round history"
            )
        self.problem_frame.validate()
        self.subgoal_ledger.validate()
        subgoal_ids = {
            item.subgoal_id for item in self.subgoal_ledger.items
        }
        self.claim_ledger.validate(subgoal_ids, self.branch_id)
        claim_ids = {item.claim_id for item in self.claim_ledger.items}
        obligation_ids: set[str] = set()
        for item in self.open_obligations:
            item.validate()
            if item.obligation_id in obligation_ids:
                raise ReasoningStateValidationError(
                    "duplicate OpenObligation id"
                )
            obligation_ids.add(item.obligation_id)
            unknown = set(item.depends_on) - claim_ids
            if unknown:
                raise ReasoningStateValidationError(
                    f"unknown OpenObligation Claim: {sorted(unknown)}"
                )
        for reference in self.evidence_refs:
            _public_id(reference, "ReasoningState.evidence_refs")
        work_item_ids: set[str] = set()
        for result in self.tool_results:
            result.validate()
            if result.work_item_id in work_item_ids:
                raise ReasoningStateValidationError(
                    "duplicate PublicToolResult work item"
                )
            if result.claim_id not in claim_ids:
                raise ReasoningStateValidationError(
                    "PublicToolResult references an unknown Claim"
                )
            work_item_ids.add(result.work_item_id)
        _string_list(self.contradictions, "ReasoningState.contradictions")
        for index, delta in enumerate(self.rounds, start=1):
            delta.validate()
            if delta.round_index != index:
                raise ReasoningStateValidationError(
                    "ReasoningState round history is not contiguous"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "version": self.version,
            "problem_frame": self.problem_frame.to_dict(),
            "subgoal_ledger": self.subgoal_ledger.to_dict(),
            "claim_ledger": self.claim_ledger.to_dict(),
            "open_obligations": [
                item.to_dict() for item in self.open_obligations
            ],
            "evidence_refs": list(self.evidence_refs),
            "tool_results": [item.to_dict() for item in self.tool_results],
            "contradictions": list(self.contradictions),
            "strategy": self.strategy,
            "rounds": [item.to_dict() for item in self.rounds],
            "session_id": self.session_id,
            "branch_id": self.branch_id,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReasoningState":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "ReasoningState payload must be an object"
            )
        legacy_expected = {
            "schema_version",
            "state_id",
            "version",
            "problem_frame",
            "subgoal_ledger",
            "claim_ledger",
            "open_obligations",
            "evidence_refs",
            "tool_results",
            "contradictions",
            "strategy",
            "rounds",
        }
        v2_expected = legacy_expected | {"session_id", "branch_id", "agent_id"}
        if set(payload) not in (legacy_expected, v2_expected):
            raise ReasoningStateValidationError(
                "ReasoningState fields do not match the public schema"
            )
        schema_version = str(payload["schema_version"])
        if schema_version not in {"1.1", cls.SCHEMA_VERSION}:
            raise ReasoningStateValidationError(
                "ReasoningState schema version is invalid"
            )
        session_id = _public_id(
            payload.get("session_id", "session-default"),
            "ReasoningState.session_id",
        )
        branch_id = _public_id(
            payload.get("branch_id", "branch-main"),
            "ReasoningState.branch_id",
        )
        agent_id = _public_id(
            payload.get("agent_id", "reasoning"),
            "ReasoningState.agent_id",
        )
        raw_claim_ledger = ClaimLedger.from_dict(payload["claim_ledger"])
        if schema_version == cls.SCHEMA_VERSION and any(
            item.branch_id != branch_id for item in raw_claim_ledger.items
        ):
            raise ReasoningStateValidationError(
                "ReasoningState claim branch does not match state branch"
            )
        claim_ledger = ClaimLedger(
            tuple(
                item
                if item.branch_id == branch_id
                else replace(item, branch_id=branch_id)
                for item in raw_claim_ledger.items
            )
        )
        state = cls(
            state_id=_public_id(payload["state_id"], "ReasoningState.state_id"),
            version=int(payload["version"]),
            problem_frame=ProblemFrame.from_dict(payload["problem_frame"]),
            subgoal_ledger=SubgoalLedger.from_dict(
                payload["subgoal_ledger"]
            ),
            claim_ledger=claim_ledger,
            open_obligations=tuple(
                OpenObligation.from_dict(item) for item in _object_list(
                    payload["open_obligations"],
                    "ReasoningState.open_obligations",
                )
            ),
            evidence_refs=_string_list(
                payload["evidence_refs"], "ReasoningState.evidence_refs"
            ),
            tool_results=tuple(
                PublicToolResult.from_dict(item)
                for item in _object_list(
                    payload["tool_results"],
                    "ReasoningState.tool_results",
                )
            ),
            contradictions=_string_list(
                payload["contradictions"],
                "ReasoningState.contradictions",
            ),
            strategy=str(payload["strategy"]),
            rounds=tuple(
                RoundDelta.from_dict(item) for item in _object_list(
                    payload["rounds"], "ReasoningState.rounds"
                )
            ),
            schema_version=cls.SCHEMA_VERSION,
            session_id=session_id,
            branch_id=branch_id,
            agent_id=agent_id,
        )
        state.validate()
        return state

    def apply_tool_results(
        self,
        results: tuple[PublicToolResult, ...],
    ) -> tuple["ReasoningState", dict[str, Any]]:
        if not results:
            return self, {
                "work_item_ids": [],
                "evidence_ids": list(self.evidence_refs),
                "strategy_changed": False,
                "failure_codes": [],
                "claim_status_transitions": [],
                "updated_claim_ids": [],
                "information_gain": 0,
            }
        existing_ids = {item.work_item_id for item in self.tool_results}
        new_results = [
            item for item in results if item.work_item_id not in existing_ids
        ]
        for item in new_results:
            item.validate()
            if item.claim_id not in {
                claim.claim_id for claim in self.claim_ledger.items
            }:
                raise ReasoningStateValidationError(
                    "PublicToolResult references an unknown Claim"
                )
        existing_claims = {
            item.claim_id: item for item in self.claim_ledger.items
        }
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *self.evidence_refs,
                    *(_tool_evidence_id(item.work_item_id) for item in new_results),
                )
            )
        )
        switch = next(
            (
                item
                for item in new_results
                if item.impact in {"switch_strategy", "request_clarification"}
            ),
            None,
        )
        strategy = (
            f"tool_feedback:{switch.tool_name}:{switch.reason_code}"
            if switch is not None
            else self.strategy
        )
        claim_status_transitions: list[dict[str, str]] = []
        updated_claim_ids: list[str] = []
        for item in new_results:
            prior = existing_claims[item.claim_id]
            if prior.status in {"rejected", "superseded", "archived"}:
                target_status = prior.status
            elif item.status == "pass":
                target_status = (
                    "verified"
                    if item.strength in {"medium", "hard"}
                    else "supported"
                )
            else:
                target_status = "challenged"
            evidence_id = _tool_evidence_id(item.work_item_id)
            updated = replace(
                prior,
                status=target_status,
                version=prior.version + 1,
                evidence_refs=tuple(
                    dict.fromkeys((*prior.evidence_refs, evidence_id))
                ),
                provenance=tuple(
                    dict.fromkeys((*prior.provenance, evidence_id))
                ),
            )
            existing_claims[item.claim_id] = updated
            updated_claim_ids.append(item.claim_id)
            if prior.status != target_status:
                claim_status_transitions.append(
                    {
                        "claim_id": item.claim_id,
                        "from": prior.status,
                        "to": target_status,
                        "evidence_id": evidence_id,
                    }
                )
        contradictions = tuple(
            dict.fromkeys(
                (
                    *self.contradictions,
                    *(
                        f"{item.claim_id}:{item.tool_name}:{item.status}"
                        for item in new_results
                        if item.status == "fail"
                    ),
                )
            )
        )
        state = replace(
            self,
            evidence_refs=evidence_refs,
            tool_results=(*self.tool_results, *new_results),
            claim_ledger=ClaimLedger(tuple(existing_claims.values())),
            contradictions=contradictions,
            strategy=strategy,
        )
        state.validate()
        information_gain = (
            len(new_results)
            + len(claim_status_transitions)
            + int(strategy != self.strategy)
        )
        return state, {
            "work_item_ids": [item.work_item_id for item in new_results],
            "evidence_ids": list(evidence_refs),
            "strategy_changed": strategy != self.strategy,
            "claim_status_transitions": claim_status_transitions,
            "updated_claim_ids": updated_claim_ids,
            "information_gain": information_gain,
            "failure_codes": [
                item.reason_code
                for item in new_results
                if item.status in {"fail", "unknown", "error"}
            ],
        }

    def apply(self, delta: RoundDelta) -> tuple["ReasoningState", dict[str, Any]]:
        delta.validate()
        if delta.round_index != self.version:
            raise ReasoningStateValidationError(
                "RoundDelta does not target the next state version"
            )
        existing_subgoals = {
            item.subgoal_id: item for item in self.subgoal_ledger.items
        }
        added_subgoals: list[str] = []
        updated_subgoals: list[str] = []
        closed_subgoals: list[str] = []
        for subgoal in delta.subgoals:
            prior_subgoal = existing_subgoals.get(subgoal.subgoal_id)
            if prior_subgoal is None:
                existing_subgoals[subgoal.subgoal_id] = subgoal
                added_subgoals.append(subgoal.subgoal_id)
                if subgoal.status == "closed":
                    closed_subgoals.append(subgoal.subgoal_id)
                continue
            immutable_prior = replace(
                prior_subgoal,
                status=subgoal.status,
            )
            if immutable_prior != subgoal:
                raise ReasoningStateValidationError(
                    "Subgoal content cannot be rewritten across rounds"
                )
            if (
                prior_subgoal.status == "closed"
                and subgoal.status != "closed"
            ):
                raise ReasoningStateValidationError(
                    "closed Subgoal cannot be reopened"
                )
            if prior_subgoal.status != subgoal.status:
                existing_subgoals[subgoal.subgoal_id] = subgoal
                updated_subgoals.append(subgoal.subgoal_id)
                if subgoal.status == "closed":
                    closed_subgoals.append(subgoal.subgoal_id)

        existing_claims = {
            item.claim_id: item for item in self.claim_ledger.items
        }
        raw_claims = tuple(
            replace(claim, branch_id=self.branch_id)
            if claim.branch_id == "branch-main"
            else claim
            for claim in delta.claims
        )
        for claim in raw_claims:
            if claim.branch_id != self.branch_id:
                raise ReasoningStateValidationError(
                    "PublicClaim branch does not match ReasoningState branch"
                )
        if len({claim.claim_id for claim in raw_claims}) != len(raw_claims):
            raise ReasoningStateValidationError(
                "duplicate PublicClaim id in RoundDelta"
            )
        raw_claim_ids = {claim.claim_id for claim in raw_claims}
        added_claims: list[str] = []
        revised_claims: list[str] = []
        superseded_claims: list[str] = []
        semantic_repetitions: list[str] = []
        claim_status_changes: list[dict[str, str]] = []
        committed_claims_list: list[PublicClaim] = []
        pending_supersessions: list[tuple[PublicClaim, tuple[str, ...]]] = []
        for claim in raw_claims:
            unknown_supersedes = set(claim.supersedes) - (
                set(existing_claims) | raw_claim_ids
            )
            if unknown_supersedes:
                raise ReasoningStateValidationError(
                    "PublicClaim supersedes an unknown Claim: "
                    f"{sorted(unknown_supersedes)}"
                )
            prior_claim = existing_claims.get(claim.claim_id)
            if prior_claim is None:
                is_semantic_repetition = not claim.supersedes and any(
                    _claim_semantic_key(claim) == _claim_semantic_key(item)
                    and item.status in _ACTIVE_CLAIM_STATUSES
                    for item in self.claim_ledger.items
                )
                if is_semantic_repetition:
                    claim = replace(
                        claim,
                        status="archived",
                        provenance=tuple(
                            dict.fromkeys(
                                (*claim.provenance, "semantic-repetition")
                            )
                        ),
                    )
                existing_claims[claim.claim_id] = claim
                added_claims.append(claim.claim_id)
                pending_supersessions.append((claim, claim.supersedes))
                committed_claims_list.append(claim)
                if is_semantic_repetition:
                    semantic_repetitions.append(claim.claim_id)
                continue
            if prior_claim == claim:
                committed_claims_list.append(claim)
                continue
            same_core = _claim_content_key(prior_claim) == _claim_content_key(
                claim
            )
            is_versioned_revision = (
                claim.version > prior_claim.version
                and prior_claim.claim_id in claim.supersedes
            )
            is_lifecycle_transition = same_core and (
                claim.status != prior_claim.status
                or claim.evidence_refs != prior_claim.evidence_refs
                or claim.provenance != prior_claim.provenance
            )
            if not is_versioned_revision and not is_lifecycle_transition:
                raise ReasoningStateValidationError(
                    "PublicClaim content cannot be rewritten without a version"
                )
            if claim.version <= prior_claim.version:
                claim = replace(claim, version=prior_claim.version + 1)
            existing_claims[claim.claim_id] = claim
            revised_claims.append(claim.claim_id)
            pending_supersessions.append((claim, claim.supersedes))
            committed_claims_list.append(claim)
            if prior_claim.status != claim.status:
                claim_status_changes.append(
                    {
                        "claim_id": claim.claim_id,
                        "from": prior_claim.status,
                        "to": claim.status,
                    }
                )

        for claim, supersedes in pending_supersessions:
            for superseded_id in supersedes:
                if superseded_id == claim.claim_id:
                    # Same-id version revisions are represented by the new
                    # version in the ledger; the prior version remains in the
                    # round audit trail.
                    continue
                prior = existing_claims.get(superseded_id)
                if prior is None:
                    raise ReasoningStateValidationError(
                        "PublicClaim supersedes an unknown Claim"
                    )
                if prior.status != "superseded":
                    existing_claims[superseded_id] = replace(
                        prior,
                        status="superseded",
                        version=prior.version + 1,
                        provenance=tuple(
                            dict.fromkeys(
                                (*prior.provenance, f"superseded-by-{claim.claim_id}")
                            )
                        ),
                    )
                    superseded_claims.append(superseded_id)

        existing_obligations = {
            item.obligation_id: item for item in self.open_obligations
        }
        opened_obligations: list[str] = []
        for obligation in delta.open_obligations:
            prior_obligation = existing_obligations.get(
                obligation.obligation_id
            )
            if prior_obligation is None:
                existing_obligations[obligation.obligation_id] = obligation
                opened_obligations.append(obligation.obligation_id)
            elif prior_obligation != obligation:
                raise ReasoningStateValidationError(
                    "OpenObligation content cannot be rewritten"
                )
        closed_obligations = [
            item
            for item in delta.closed_obligation_ids
            if item in existing_obligations
        ]
        for obligation_id in closed_obligations:
            existing_obligations.pop(obligation_id, None)

        new_contradictions = [
            item
            for item in delta.contradictions
            if item not in self.contradictions
        ]
        new_claim_evidence = {
            evidence_id
            for claim in committed_claims_list
            for evidence_id in claim.evidence_refs
        }
        new_evidence_refs = new_claim_evidence - set(self.evidence_refs)
        evidence_refs = tuple(
            dict.fromkeys((*self.evidence_refs, *sorted(new_evidence_refs)))
        )
        meaningful_claims = (
            len(added_claims)
            - len(semantic_repetitions)
            + len(revised_claims)
            + len(superseded_claims)
            + len(claim_status_changes)
        )
        information_gain = max(
            0,
            meaningful_claims
            + len(updated_subgoals)
            + len(closed_subgoals)
            + len(opened_obligations)
            + (2 * len(closed_obligations))
            + len(new_contradictions)
            + len(new_evidence_refs)
            + int((delta.strategy or self.strategy) != self.strategy)
            - len(semantic_repetitions),
        )
        committed_claims = tuple(committed_claims_list)
        committed_delta = replace(
            delta,
            claims=committed_claims,
            information_gain=information_gain,
        )
        state = replace(
            self,
            version=self.version + 1,
            subgoal_ledger=SubgoalLedger(
                tuple(existing_subgoals.values())
            ),
            claim_ledger=ClaimLedger(tuple(existing_claims.values())),
            open_obligations=tuple(existing_obligations.values()),
            evidence_refs=evidence_refs,
            contradictions=tuple(
                dict.fromkeys((*self.contradictions, *new_contradictions))
            ),
            strategy=delta.strategy or self.strategy,
            rounds=(*self.rounds, committed_delta),
        )
        state.validate()
        summary = {
            "state_id": state.state_id,
            "state_version": state.version,
            "round_index": committed_delta.round_index,
            "mode": committed_delta.mode,
            "added_subgoal_ids": added_subgoals,
            "updated_subgoal_ids": updated_subgoals,
            "closed_subgoal_ids": closed_subgoals,
            "added_claim_ids": added_claims,
            "revised_claim_ids": revised_claims,
            "superseded_claim_ids": list(dict.fromkeys(superseded_claims)),
            "claim_status_changes": claim_status_changes,
            "semantic_repetition_ids": semantic_repetitions,
            "claim_dependency_refs": {
                item.claim_id: list(item.depends_on)
                for item in committed_delta.claims
            },
            "evidence_ids": list(state.evidence_refs),
            "opened_obligation_ids": opened_obligations,
            "closed_obligation_ids": closed_obligations,
            "information_gain": information_gain,
            "information_gain_components": {
                "meaningful_claims": meaningful_claims,
                "new_evidence": len(new_evidence_refs),
                "closed_obligations": len(closed_obligations),
                "resolved_subgoals": len(closed_subgoals),
                "new_contradictions": len(new_contradictions),
                "semantic_repetitions": len(semantic_repetitions),
            },
            "next_step": committed_delta.next_step,
            "stop_reason": committed_delta.stop_reason,
            "degraded_reason": "",
        }
        return state, summary

    def active_frontier(self) -> tuple[str, ...]:
        """Return the branch-local claims required for the next decision.

        Pending/proposed/supporting/challenged claims are live work. Critical
        verified claims and dependencies of open obligations remain live as
        well; low-level verified facts without a live consumer are eligible
        for semantic GC.
        """
        by_id = {item.claim_id: item for item in self.claim_ledger.items}
        keep: set[str] = {
            item.claim_id
            for item in self.claim_ledger.items
            if item.status in {"pending", "accepted", "proposed", "supported", "challenged"}
            or (item.status == "verified" and item.importance == "critical")
        }
        for obligation in self.open_obligations:
            keep.update(obligation.depends_on)
        if not keep and self.claim_ledger.items:
            keep.add(self.claim_ledger.items[-1].claim_id)
        changed = True
        while changed:
            changed = False
            for claim_id in tuple(keep):
                claim = by_id.get(claim_id)
                if claim is None:
                    continue
                before = len(keep)
                keep.update(claim.depends_on)
                changed = changed or len(keep) != before
        return tuple(
            claim.claim_id
            for claim in self.claim_ledger.items
            if claim.claim_id in keep
        )

    def semantic_gc(self) -> tuple["ReasoningState", dict[str, Any]]:
        """Compact historical state while preserving the active frontier."""
        active_ids = set(self.active_frontier())
        retained_claims = tuple(
            claim
            for claim in self.claim_ledger.items
            if claim.claim_id in active_ids
        )
        removed_claim_ids = tuple(
            claim.claim_id
            for claim in self.claim_ledger.items
            if claim.claim_id not in active_ids
        )
        retained_ids = {claim.claim_id for claim in retained_claims}
        by_subgoal_id = {
            item.subgoal_id: item for item in self.subgoal_ledger.items
        }
        retained_subgoal_ids: set[str] = {
            item.subgoal_id
            for item in self.subgoal_ledger.items
            if item.status != "closed"
        }
        retained_subgoal_ids.update(
            subgoal_id
            for claim in retained_claims
            for subgoal_id in claim.subgoal_ids
        )
        changed = True
        while changed:
            changed = False
            for subgoal_id in tuple(retained_subgoal_ids):
                subgoal = by_subgoal_id.get(subgoal_id)
                if subgoal is None:
                    continue
                before = len(retained_subgoal_ids)
                retained_subgoal_ids.update(subgoal.depends_on)
                changed = changed or len(retained_subgoal_ids) != before
        retained_subgoals = tuple(
            item
            for item in self.subgoal_ledger.items
            if item.subgoal_id in retained_subgoal_ids
        )
        obligations = tuple(
            obligation
            for obligation in self.open_obligations
            if set(obligation.depends_on) <= retained_ids
        )

        # Keep only the latest public result per active claim and reduce a
        # historical payload to its digest plus conclusion.  This retains
        # evidence identity without replaying stale tool output.
        latest_results: list[PublicToolResult] = []
        seen_claims: set[str] = set()
        for result in reversed(self.tool_results):
            if result.claim_id not in retained_ids or result.claim_id in seen_claims:
                continue
            seen_claims.add(result.claim_id)
            latest_results.append(
                replace(
                    result,
                    public_payload={
                        "summary": result.summary,
                        "result_digest": result.result_digest,
                    },
                )
            )
        latest_results.reverse()
        kept_evidence = tuple(
            dict.fromkeys(
                (
                    *(
                        reference
                        for claim in retained_claims
                        for reference in claim.evidence_refs
                    ),
                    *(
                        _tool_evidence_id(result.work_item_id)
                        for result in latest_results
                    ),
                )
            )
        )

        # Preserve round numbering/version while replacing old verbose
        # deltas with bounded audit summaries.  The last two rounds remain
        # fully inspectable for the next model call.
        compacted_rounds = tuple(
            item
            if index > max(0, len(self.rounds) - 2)
            else replace(
                item,
                public_summary=(
                    f"gc-round-{item.round_index}: "
                    f"{item.public_summary[:512]}"
                ),
                subgoals=(),
                claims=(),
                open_obligations=(),
                contradictions=item.contradictions[-4:],
            )
            for index, item in enumerate(self.rounds, start=1)
        )
        state = replace(
            self,
            subgoal_ledger=SubgoalLedger(retained_subgoals),
            claim_ledger=ClaimLedger(retained_claims),
            open_obligations=obligations,
            evidence_refs=kept_evidence,
            tool_results=tuple(latest_results),
            rounds=compacted_rounds,
        )
        state.validate()
        summary = {
            "active_claim_ids": list(active_ids),
            "removed_claim_ids": list(removed_claim_ids),
            "removed_subgoal_ids": [
                item.subgoal_id
                for item in self.subgoal_ledger.items
                if item.subgoal_id not in retained_subgoal_ids
            ],
            "retained_tool_result_ids": [
                item.work_item_id for item in latest_results
            ],
            "compacted_round_count": max(0, len(self.rounds) - 2),
            "context_growth_bound": "active_frontier",
        }
        return state, summary

    def gc_active_frontier(self) -> tuple["ReasoningState", dict[str, Any]]:
        """Compatibility alias for callers that name the operation explicitly."""
        return self.semantic_gc()

    def apply_candidate(
        self,
        candidate: CandidateSolution,
    ) -> tuple["ReasoningState", dict[str, Any]]:
        existing_ids = {
            item.claim_id for item in self.claim_ledger.items
        }
        claims: list[PublicClaim] = []
        id_mapping: dict[str, str] = {}
        for item in candidate.claims:
            claim_id = item.claim_id
            if claim_id in existing_ids:
                existing = next(
                    claim
                    for claim in self.claim_ledger.items
                    if claim.claim_id == claim_id
                )
                if existing.statement == item.statement:
                    id_mapping[item.claim_id] = claim_id
                    continue
                claim_id = f"final-{item.claim_id}"
            id_mapping[item.claim_id] = claim_id
        for item in candidate.claims:
            claim_id = id_mapping[item.claim_id]
            if claim_id in existing_ids:
                continue
            claims.append(
                PublicClaim(
                    claim_id=claim_id,
                    statement=item.statement,
                    depends_on=tuple(
                        id_mapping.get(value, value)
                        for value in item.depends_on
                    ),
                    status="pending",
                    importance=item.importance,
                    check_type=item.check_type,
                )
            )
        delta = RoundDelta(
            round_index=self.version,
            mode="synthesize",
            public_summary="A CandidateSolution was synthesized from public state.",
            strategy=candidate.method or self.strategy,
            claims=tuple(claims),
            next_step="verify_candidate",
            stop_reason="candidate_synthesized",
        )
        return self.apply(delta)


@dataclass(frozen=True)
class CompressedReasoningState:
    prompt_json: str
    state_tokens: int
    counting_mode: str
    compressed: bool
    omitted_rounds: int
    semantic_invariants: tuple[str, ...]
    active_claim_ids: tuple[str, ...] = ()
    verified_fact_ids: tuple[str, ...] = ()
    proof_backbone: dict[str, Any] | None = None


class ReasoningStateCompressor:
    """Token-budget a public state while retaining its mathematical core."""

    def __init__(
        self,
        token_counter: InternS2TokenCounter | None = None,
    ) -> None:
        self._counter = token_counter or InternS2TokenCounter()

    def compress(
        self,
        state: ReasoningState,
        *,
        max_tokens: int = REASONING_STATE_MAX_TOKENS,
        verified_fact_bank: Any | None = None,
        proof_backbone: Any | None = None,
    ) -> CompressedReasoningState:
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("ReasoningState token budget must be positive")
        state.validate()
        full_payload = state.to_dict()
        verified_fact_ids = tuple(
            getattr(item, "fact_id", "")
            for item in (
                verified_fact_bank.values()
                if verified_fact_bank is not None
                else ()
            )
            if getattr(item, "fact_id", "")
        )
        backbone_payload = (
            proof_backbone.to_prompt_dict()
            if proof_backbone is not None
            and hasattr(proof_backbone, "to_prompt_dict")
            else None
        )
        if verified_fact_bank is not None:
            full_payload["verified_fact_bank"] = verified_fact_bank.to_dict()
        if backbone_payload is not None:
            full_payload["proof_backbone"] = backbone_payload
        full_text, full_count = self._serialize_and_count(full_payload)
        invariants = (
            "problem_frame",
            "definitions",
            "quantifiers",
            "constraints",
            "target",
            "subgoal_dependencies",
            "claim_dependencies",
            "claim_lifecycle",
            "open_obligations",
            "tool_results",
            "evidence_transitions",
            "branch_identity",
            "active_frontier",
        )
        if verified_fact_bank is not None:
            invariants = (*invariants, "verified_fact_bank")
        if backbone_payload is not None:
            invariants = (*invariants, "proof_backbone")
        if full_count.tokens <= max_tokens:
            return CompressedReasoningState(
                full_text,
                full_count.tokens,
                full_count.counting_mode,
                False,
                0,
                invariants,
                state.active_frontier(),
                verified_fact_ids,
                backbone_payload,
            )

        compact_state, gc_summary = state.semantic_gc()
        compact_payload = compact_state.to_dict()
        if verified_fact_bank is not None:
            compact_payload["verified_fact_bank"] = verified_fact_bank.to_dict()
        if backbone_payload is not None:
            compact_payload["proof_backbone"] = backbone_payload
        active_claim_ids = tuple(gc_summary["active_claim_ids"])
        payload = {
            **compact_payload,
            "rounds": [
                item.to_summary_dict()
                for item in compact_state.rounds[-2:]
            ],
            "contradictions": list(compact_state.contradictions[-16:]),
            "compression": {
                "kind": "active_frontier",
                "omitted_rounds": max(0, len(state.rounds) - 2),
                "preserved_invariants": list(invariants),
                "active_claim_ids": list(active_claim_ids),
                "removed_claim_ids": list(gc_summary["removed_claim_ids"]),
                "removed_subgoal_ids": list(gc_summary["removed_subgoal_ids"]),
            },
        }
        text, count = self._serialize_and_count(payload)
        if count.tokens > max_tokens:
            payload["rounds"] = []
            payload["compression"]["omitted_rounds"] = len(state.rounds)
            text, count = self._serialize_and_count(payload)
        if count.tokens > max_tokens:
            payload["contradictions"] = []
            text, count = self._serialize_and_count(payload)
        if count.tokens > max_tokens:
            raise ContextBudgetExceeded(
                "ReasoningState core exceeds its token budget"
            )
        _validate_projection_invariants(
            state,
            payload,
            active_claim_ids=set(active_claim_ids),
        )
        return CompressedReasoningState(
            text,
            count.tokens,
            count.counting_mode,
            True,
            int(payload["compression"]["omitted_rounds"]),
            invariants,
            active_claim_ids,
            verified_fact_ids,
            backbone_payload,
        )

    def _serialize_and_count(
        self,
        payload: dict[str, Any],
    ) -> tuple[str, Any]:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return text, self._counter.count_text(text)


class ProgressDeltaParser:
    """Parse only public explore/continue deltas; never accept private fields."""

    _FIELDS = {
        "public_summary",
        "strategy",
        "subgoals",
        "claims",
        "open_obligations",
        "closed_obligation_ids",
        "contradictions",
        "next_step",
        "stop_reason",
    }

    def parse(
        self,
        response: str,
        *,
        round_index: int,
        mode: str,
        branch_id: str = "branch-main",
    ) -> RoundDelta:
        if mode not in _PROGRESS_MODES:
            raise ReasoningStateValidationError(
                "ProgressDelta mode must be explore or continue"
            )
        payload = _extract_json_object(str(response))
        private = [key for key in payload if _PRIVATE_KEYS.fullmatch(str(key))]
        if private:
            raise ReasoningStateValidationError(
                "ProgressDelta contains a private reasoning field"
            )
        if set(payload) != self._FIELDS:
            raise ReasoningStateValidationError(
                "ProgressDelta fields do not match the public protocol"
            )
        raw_subgoals = _object_list(
            payload["subgoals"], "ProgressDelta.subgoals"
        )
        subgoals = tuple(
            _progress_subgoal(
                item,
                round_index=round_index,
                item_index=index,
            )
            for index, item in enumerate(raw_subgoals)
        )
        raw_claims = _object_list(
            payload["claims"], "ProgressDelta.claims"
        )
        branch_id = _public_id(branch_id, "ProgressDelta.branch_id")
        claims = tuple(
            _progress_claim(
                item,
                branch_id=branch_id,
                round_index=round_index,
                item_index=index,
            )
            for index, item in enumerate(raw_claims)
        )
        obligations = tuple(
            _progress_obligation(
                item,
                round_index=round_index,
                item_index=index,
            )
            for index, item in enumerate(
                _object_list(
                    payload["open_obligations"],
                    "ProgressDelta.open_obligations",
                )
            )
        )
        delta = RoundDelta(
            round_index=round_index,
            mode=mode,
            public_summary=str(payload["public_summary"]).strip(),
            strategy=str(payload["strategy"]).strip(),
            subgoals=subgoals,
            claims=claims,
            open_obligations=obligations,
            closed_obligation_ids=_string_list(
                payload["closed_obligation_ids"],
                "ProgressDelta.closed_obligation_ids",
            ),
            contradictions=_string_list(
                payload["contradictions"],
                "ProgressDelta.contradictions",
            ),
            next_step=str(payload["next_step"]).strip(),
            stop_reason=str(payload["stop_reason"]).strip(),
        )
        delta.validate()
        return delta


def _progress_claim(
    payload: dict[str, Any],
    *,
    branch_id: str = "branch-main",
    round_index: int,
    item_index: int,
) -> PublicClaim:
    base_fields = {
        "statement",
        "claim_kind",
        "depends_on",
        "subgoal_refs",
        "importance",
    }
    host_owned_fields = {
        "claim_id",
        "subgoal_ids",
        "check_type",
        "status",
        "version",
        "supersedes",
        "evidence_refs",
        "provenance",
        "branch_id",
    }
    if not isinstance(payload, dict):
        raise ReasoningStateValidationError(
            "ProgressDelta Claim fields are invalid"
        )
    if set(payload).intersection(host_owned_fields):
        raise ReasoningStateValidationError(
            "ProgressDelta contains Host-owned Claim lifecycle fields"
        )
    if set(payload) != base_fields:
        raise ReasoningStateValidationError(
            "ProgressDelta Claim fields are invalid"
        )
    claim_kind = str(payload["claim_kind"]).strip()
    if claim_kind not in _CLAIM_KINDS:
        raise ReasoningStateValidationError(
            "ProgressDelta claim_kind is invalid"
        )
    claim = PublicClaim(
        claim_id=f"host-r{round_index}-c{item_index + 1}",
        statement=str(payload["statement"]).strip(),
        depends_on=_semantic_refs(
            payload["depends_on"],
            name="ProgressDelta.depends_on",
            local_prefix=f"host-r{round_index}-c",
            item_index=item_index,
        ),
        subgoal_ids=_semantic_refs(
            payload["subgoal_refs"],
            name="ProgressDelta.subgoal_refs",
            local_prefix=f"host-r{round_index}-g",
            item_index=None,
        ),
        status="proposed",
        importance=str(payload["importance"]).strip(),
        check_type=_check_type_for_claim_kind(claim_kind),
        claim_kind=claim_kind,
        version=1,
        branch_id=_public_id(
            branch_id,
            "ProgressDelta.branch_id",
        ),
    )
    claim.validate()
    return claim


def _progress_subgoal(
    payload: dict[str, Any],
    *,
    round_index: int,
    item_index: int,
) -> Subgoal:
    semantic_fields = {"statement", "depends_on", "exit_condition"}
    if not isinstance(payload, dict):
        raise ReasoningStateValidationError("ProgressDelta Subgoal is invalid")
    if set(payload).intersection({"subgoal_id", "status"}):
        raise ReasoningStateValidationError(
            "ProgressDelta contains Host-owned Subgoal lifecycle fields"
        )
    if set(payload) != semantic_fields:
        raise ReasoningStateValidationError("ProgressDelta Subgoal is invalid")
    subgoal = Subgoal(
        subgoal_id=f"host-r{round_index}-g{item_index + 1}",
        statement=str(payload["statement"]).strip(),
        depends_on=_semantic_refs(
            payload["depends_on"],
            name="ProgressDelta.Subgoal.depends_on",
            local_prefix=f"host-r{round_index}-g",
            item_index=item_index,
        ),
        exit_condition=str(payload["exit_condition"]).strip(),
        status="open",
    )
    subgoal.validate()
    return subgoal


def _progress_obligation(
    payload: dict[str, Any],
    *,
    round_index: int,
    item_index: int,
) -> OpenObligation:
    semantic_fields = {"statement", "depends_on"}
    if not isinstance(payload, dict):
        raise ReasoningStateValidationError(
            "ProgressDelta OpenObligation is invalid"
        )
    if "obligation_id" in payload:
        raise ReasoningStateValidationError(
            "ProgressDelta contains a Host-owned Obligation field"
        )
    if set(payload) != semantic_fields:
        raise ReasoningStateValidationError(
            "ProgressDelta OpenObligation is invalid"
        )
    obligation = OpenObligation(
        obligation_id=f"host-r{round_index}-o{item_index + 1}",
        statement=str(payload["statement"]).strip(),
        depends_on=_semantic_refs(
            payload["depends_on"],
            name="ProgressDelta.OpenObligation.depends_on",
            local_prefix=f"host-r{round_index}-c",
            item_index=None,
        ),
    )
    obligation.validate()
    return obligation


def _semantic_refs(
    value: Any,
    *,
    name: str,
    local_prefix: str,
    item_index: int | None,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ReasoningStateValidationError(f"{name} must be a reference list")
    references: list[str] = []
    for reference in value:
        if type(reference) is int:
            if reference < 0 or (item_index is not None and reference >= item_index):
                raise ReasoningStateValidationError(
                    f"{name} local index must reference a prior item"
                )
            references.append(f"{local_prefix}{reference + 1}")
        elif isinstance(reference, str):
            references.append(_public_id(reference, name))
        else:
            raise ReasoningStateValidationError(
                f"{name} must contain integer indices or public IDs"
            )
    return tuple(dict.fromkeys(references))


def _check_type_for_claim_kind(claim_kind: str) -> str:
    return {
        "equality": "symbolic_equivalence",
        "matrix_shape": "matrix_shape_check",
        "probability_normalization": "density_normalization",
        "finite_case": "small_case_enumeration",
        "answer_shape": "answer_type_check",
    }.get(claim_kind, claim_kind)


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    candidates = [cleaned]
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        candidates.append("\n".join(lines[1:-1]).strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            for index, character in enumerate(candidate):
                if character != "{":
                    continue
                try:
                    value, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return value
            continue
        if isinstance(value, dict):
            return value
    raise ReasoningStateValidationError(
        "ProgressDelta response is not a JSON object"
    )


def _claim_content_key(claim: PublicClaim) -> tuple[Any, ...]:
    """Fields that are immutable unless a V2 revision is explicitly made."""
    return (
        claim.statement,
        claim.depends_on,
        claim.subgoal_ids,
        claim.importance,
        claim.check_type,
        claim.claim_kind,
        claim.branch_id,
    )


def _claim_semantic_key(claim: PublicClaim) -> tuple[Any, ...]:
    """Normalized meaning used to discount repeated IDs from information gain."""
    return (
        " ".join(claim.statement.split()).casefold(),
        tuple(claim.depends_on),
        tuple(claim.subgoal_ids),
        claim.check_type,
        claim.claim_kind,
    )


def _tool_evidence_id(work_item_id: str) -> str:
    candidate = f"tool-{work_item_id}"
    if len(candidate) <= 96:
        return candidate
    return f"tool-{sha256(work_item_id.encode('utf-8')).hexdigest()[:24]}"


def _object_list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(item, dict) for item in value
    ):
        raise ReasoningStateValidationError(f"{name} must be an object list")
    return value


def _validate_acyclic(
    dependencies: dict[str, tuple[str, ...]],
    label: str,
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise ReasoningStateValidationError(f"{label} dependency cycle")
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in dependencies[item_id]:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in dependencies:
        visit(item_id)


def _validate_projection_invariants(
    state: ReasoningState,
    payload: dict[str, Any],
    *,
    active_claim_ids: set[str] | None = None,
) -> None:
    if payload["problem_frame"] != state.problem_frame.to_dict():
        raise ReasoningStateValidationError(
            "ReasoningState compression changed the ProblemFrame"
        )
    subgoal_payload = SubgoalLedger.from_dict(payload["subgoal_ledger"])
    source_subgoal_ids = {
        item.subgoal_id for item in state.subgoal_ledger.items
    }
    projected_subgoal_ids = {
        item.subgoal_id for item in subgoal_payload.items
    }
    if not projected_subgoal_ids <= source_subgoal_ids:
        raise ReasoningStateValidationError(
            "ReasoningState compression invented Subgoals"
        )
    claim_payload = ClaimLedger.from_dict(payload["claim_ledger"])
    source_claim_ids = {item.claim_id for item in state.claim_ledger.items}
    projected_claim_ids = {item.claim_id for item in claim_payload.items}
    allowed_claim_ids = active_claim_ids or source_claim_ids
    if not projected_claim_ids <= source_claim_ids:
        raise ReasoningStateValidationError(
            "ReasoningState compression invented Claims"
        )
    if not projected_claim_ids <= allowed_claim_ids:
        raise ReasoningStateValidationError(
            "ReasoningState compression retained a non-frontier Claim"
        )
    claim_payload.validate(
        projected_subgoal_ids,
        state.branch_id,
    )
    projected_obligations = tuple(
        OpenObligation.from_dict(item)
        for item in _object_list(
            payload["open_obligations"],
            "compressed.open_obligations",
        )
    )
    if not set(item.obligation_id for item in projected_obligations) <= {
        item.obligation_id for item in state.open_obligations
    }:
        raise ReasoningStateValidationError(
            "ReasoningState compression invented open obligations"
        )
    if any(
        set(item.depends_on) - projected_claim_ids
        for item in projected_obligations
    ):
        raise ReasoningStateValidationError(
            "ReasoningState compression broke obligation dependencies"
        )
    projected_results = tuple(
        PublicToolResult.from_dict(item)
        for item in _object_list(
            payload["tool_results"],
            "compressed.tool_results",
        )
    )
    source_work_items = {item.work_item_id for item in state.tool_results}
    if any(item.work_item_id not in source_work_items for item in projected_results):
        raise ReasoningStateValidationError(
            "ReasoningState compression invented tool results"
        )
    if any(item.claim_id not in projected_claim_ids for item in projected_results):
        raise ReasoningStateValidationError(
            "ReasoningState compression retained evidence for a non-frontier Claim"
        )


def _nested_keys(value: Any) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_nested_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.extend(_nested_keys(item))
    return tuple(keys)
