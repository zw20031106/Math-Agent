from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import re
from typing import Any, ClassVar

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import InternS2TokenCounter
from mathforge.harness.schemas import CandidateSolution, ProblemIR


REASONING_STATE_SCHEMA_VERSION = "1.1"
REASONING_STATE_MAX_TOKENS = 32768
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_PRIVATE_KEYS = re.compile(
    r"^(?:chain[_-]?of[_-]?thought|scratchpad|hidden[_-]?reasoning|"
    r"private[_-]?reasoning|raw_(?:response|prompt|completion))$",
    re.I,
)
_SUBGOAL_STATUSES = frozenset({"open", "active", "closed", "blocked"})
_CLAIM_STATUSES = frozenset({"pending", "accepted", "rejected"})
_PROGRESS_MODES = frozenset({"explore", "continue"})


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

    def validate(self) -> None:
        _public_id(self.claim_id, "PublicClaim.claim_id")
        if not self.statement.strip():
            raise ReasoningStateValidationError("PublicClaim statement is empty")
        if self.status not in _CLAIM_STATUSES:
            raise ReasoningStateValidationError("PublicClaim status is invalid")
        if self.importance not in {"critical", "supporting"}:
            raise ReasoningStateValidationError(
                "PublicClaim importance is invalid"
            )
        _public_id(self.check_type, "PublicClaim.check_type")
        for dependency in self.depends_on:
            _public_id(dependency, "PublicClaim.depends_on")
        for subgoal_id in self.subgoal_ids:
            _public_id(subgoal_id, "PublicClaim.subgoal_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
            "subgoal_ids": list(self.subgoal_ids),
            "status": self.status,
            "importance": self.importance,
            "check_type": self.check_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublicClaim":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "PublicClaim payload must be an object"
            )
        expected = {
            "claim_id",
            "statement",
            "depends_on",
            "subgoal_ids",
            "status",
            "importance",
            "check_type",
        }
        if set(payload) != expected:
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
        )
        claim.validate()
        return claim


@dataclass(frozen=True)
class ClaimLedger:
    items: tuple[PublicClaim, ...] = ()

    def validate(self, subgoal_ids: set[str]) -> None:
        by_id = {item.claim_id: item for item in self.items}
        if len(by_id) != len(self.items):
            raise ReasoningStateValidationError("duplicate PublicClaim id")
        for item in self.items:
            item.validate()
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

    @classmethod
    def initialize(
        cls,
        problem: ProblemIR,
        *,
        strategy: str = "",
    ) -> "ReasoningState":
        frame = ProblemFrame.from_problem_ir(problem)
        digest = sha256(
            json.dumps(
                frame.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]
        state = cls(
            state_id=f"rs-{digest}",
            version=1,
            problem_frame=frame,
            strategy=strategy,
        )
        state.validate()
        return state

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise ReasoningStateValidationError(
                "ReasoningState schema version is invalid"
            )
        _public_id(self.state_id, "ReasoningState.state_id")
        if type(self.version) is not int or self.version != len(self.rounds) + 1:
            raise ReasoningStateValidationError(
                "ReasoningState version does not match round history"
            )
        self.problem_frame.validate()
        self.subgoal_ledger.validate()
        subgoal_ids = {
            item.subgoal_id for item in self.subgoal_ledger.items
        }
        self.claim_ledger.validate(subgoal_ids)
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
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReasoningState":
        if not isinstance(payload, dict):
            raise ReasoningStateValidationError(
                "ReasoningState payload must be an object"
            )
        expected = {
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
        if set(payload) != expected:
            raise ReasoningStateValidationError(
                "ReasoningState fields do not match the public schema"
            )
        state = cls(
            state_id=_public_id(payload["state_id"], "ReasoningState.state_id"),
            version=int(payload["version"]),
            problem_frame=ProblemFrame.from_dict(payload["problem_frame"]),
            subgoal_ledger=SubgoalLedger.from_dict(
                payload["subgoal_ledger"]
            ),
            claim_ledger=ClaimLedger.from_dict(payload["claim_ledger"]),
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
            schema_version=str(payload["schema_version"]),
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
            }
        existing_ids = {item.work_item_id for item in self.tool_results}
        new_results = [
            item for item in results if item.work_item_id not in existing_ids
        ]
        for item in new_results:
            item.validate()
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *self.evidence_refs,
                    *(f"tool-{item.work_item_id}" for item in new_results),
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
            contradictions=contradictions,
            strategy=strategy,
        )
        state.validate()
        return state, {
            "work_item_ids": [item.work_item_id for item in new_results],
            "evidence_ids": list(evidence_refs),
            "strategy_changed": strategy != self.strategy,
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
        added_claims: list[str] = []
        for claim in delta.claims:
            prior_claim = existing_claims.get(claim.claim_id)
            if prior_claim is None:
                existing_claims[claim.claim_id] = claim
                added_claims.append(claim.claim_id)
            elif prior_claim != claim:
                raise ReasoningStateValidationError(
                    "PublicClaim content cannot be rewritten across rounds"
                )

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
        information_gain = sum(
            (
                len(added_subgoals),
                len(updated_subgoals),
                len(added_claims),
                len(opened_obligations),
                len(closed_obligations),
                len(new_contradictions),
            )
        )
        committed_delta = replace(
            delta,
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
            "claim_dependency_refs": {
                item.claim_id: list(item.depends_on)
                for item in committed_delta.claims
            },
            "evidence_ids": list(state.evidence_refs),
            "opened_obligation_ids": opened_obligations,
            "closed_obligation_ids": closed_obligations,
            "information_gain": information_gain,
            "next_step": committed_delta.next_step,
            "stop_reason": committed_delta.stop_reason,
            "degraded_reason": "",
        }
        return state, summary

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
    ) -> CompressedReasoningState:
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("ReasoningState token budget must be positive")
        state.validate()
        full_payload = state.to_dict()
        full_text, full_count = self._serialize_and_count(full_payload)
        invariants = (
            "problem_frame",
            "definitions",
            "quantifiers",
            "constraints",
            "target",
            "subgoal_dependencies",
            "claim_dependencies",
            "open_obligations",
            "tool_results",
        )
        if full_count.tokens <= max_tokens:
            return CompressedReasoningState(
                full_text,
                full_count.tokens,
                full_count.counting_mode,
                False,
                0,
                invariants,
            )

        payload = {
            **full_payload,
            "rounds": [
                item.to_summary_dict()
                for item in state.rounds[-2:]
            ],
            "contradictions": list(state.contradictions[-16:]),
            "compression": {
                "kind": "public_state_projection",
                "omitted_rounds": max(0, len(state.rounds) - 2),
                "preserved_invariants": list(invariants),
            },
        }
        text, count = self._serialize_and_count(payload)
        if count.tokens > max_tokens:
            payload["rounds"] = []
            payload["compression"]["omitted_rounds"] = len(state.rounds)
            text, count = self._serialize_and_count(payload)
        if count.tokens > max_tokens:
            raise ContextBudgetExceeded(
                "ReasoningState core exceeds its token budget"
            )
        _validate_projection_invariants(state, payload)
        return CompressedReasoningState(
            text,
            count.tokens,
            count.counting_mode,
            True,
            int(payload["compression"]["omitted_rounds"]),
            invariants,
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
        subgoals = tuple(
            Subgoal.from_dict(item)
            for item in _object_list(payload["subgoals"], "ProgressDelta.subgoals")
        )
        raw_claims = _object_list(
            payload["claims"], "ProgressDelta.claims"
        )
        claims = tuple(_progress_claim(item) for item in raw_claims)
        obligations = tuple(
            OpenObligation.from_dict(item)
            for item in _object_list(
                payload["open_obligations"],
                "ProgressDelta.open_obligations",
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


def _progress_claim(payload: dict[str, Any]) -> PublicClaim:
    if not isinstance(payload, dict) or set(payload) not in ({
        "claim_id",
        "statement",
        "depends_on",
        "subgoal_ids",
        "importance",
        "check_type",
    }, {
        "claim_id",
        "statement",
        "depends_on",
        "subgoal_ids",
        "importance",
    }):
        raise ReasoningStateValidationError(
            "ProgressDelta Claim fields are invalid"
        )
    claim = PublicClaim(
        claim_id=_public_id(
            payload["claim_id"], "ProgressDelta.claim_id"
        ),
        statement=str(payload["statement"]).strip(),
        depends_on=_string_list(
            payload["depends_on"], "ProgressDelta.depends_on"
        ),
        subgoal_ids=_string_list(
            payload["subgoal_ids"], "ProgressDelta.subgoal_ids"
        ),
        status="pending",
        importance=str(payload["importance"]).strip(),
        check_type=str(payload.get("check_type", "reasoning")).strip(),
    )
    claim.validate()
    return claim


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
) -> None:
    if payload["problem_frame"] != state.problem_frame.to_dict():
        raise ReasoningStateValidationError(
            "ReasoningState compression changed the ProblemFrame"
        )
    if payload["subgoal_ledger"] != state.subgoal_ledger.to_dict():
        raise ReasoningStateValidationError(
            "ReasoningState compression changed Subgoals"
        )
    if payload["claim_ledger"] != state.claim_ledger.to_dict():
        raise ReasoningStateValidationError(
            "ReasoningState compression changed Claims"
        )
    if payload["open_obligations"] != [
        item.to_dict() for item in state.open_obligations
    ]:
        raise ReasoningStateValidationError(
            "ReasoningState compression changed open obligations"
        )
    if payload["tool_results"] != [
        item.to_dict() for item in state.tool_results
    ]:
        raise ReasoningStateValidationError(
            "ReasoningState compression changed tool results"
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
