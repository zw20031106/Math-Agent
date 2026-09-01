from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, ClassVar, Mapping

from mathforge.harness.budget import CallBudget
from mathforge.harness.state import (
    InvalidRuntimeTransition,
    RuntimePhase,
    transition_allowed,
)
from mathforge.harness.problem_conditions import (
    ProblemConditionBuilder,
    ProblemConditionEnvelope,
    build_problem_condition_envelope,
)


CORE_SCHEMA_VERSION = "1.2"
PROBLEM_IR_SCHEMA_VERSION = "2.2"
CANDIDATE_SCHEMA_VERSION = "2.0"
MAX_CLAIMS = 64
MAX_METHOD_STEPS = 64
MAX_CLAIM_STATEMENT_CHARS = 4000
MAX_TOTAL_CLAIM_CHARS = 24000
_CLAIM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def strip_prompt_descriptions(value: Any) -> Any:
    """Return a compact prompt view without schema-description prose.

    Runtime schemas use ``description`` for human-readable metadata in a few
    public records.  Sending that prose on every turn wastes context and can
    drown out the actual problem.  For evidence and obligations the value is
    mathematical content rather than metadata, so it is retained under the
    neutral ``statement`` key before the description key is removed.  The
    original dataclass serializers remain unchanged; this helper is only for
    model-facing prompt rendering.
    """

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name == "description":
                if ("obligation_id" in value or "evidence_id" in value) and "statement" not in result:
                    result["statement"] = strip_prompt_descriptions(item)
                continue
            result[name] = strip_prompt_descriptions(item)
        return result
    if isinstance(value, list):
        return [strip_prompt_descriptions(item) for item in value]
    if isinstance(value, tuple):
        return [strip_prompt_descriptions(item) for item in value]
    return value


class SchemaValidationError(ValueError):
    pass


class CandidateRole(str, Enum):
    PRIMARY_SOLVER = "PrimarySolver"
    ALTERNATIVE_SOLVER = "AlternativeSolver"
    REPAIR_AGENT = "RepairAgent"
    LLM_FINALIZER = "LLMFinalizer"
    DETERMINISTIC_SHADOW = "DeterministicShadow"


class CandidateSource(str, Enum):
    LLM_PRIMARY = "llm_primary"
    LLM_ALTERNATIVE = "llm_alternative"
    LLM_REPAIR = "llm_repair"
    LLM_FINALIZER = "llm_finalizer"
    DETERMINISTIC_SHADOW = "deterministic_shadow"
    LEMMA_GUIDED = "lemma_guided"


class CandidateParseTier(str, Enum):
    STRICT = "strict"
    RECOVERED = "recovered"
    ANSWER_RECOVERED = "answer_recovered"
    REJECTED = "rejected"


_CANDIDATE_ASSURANCE = frozenset(
    {"standard", "emergency", "recovered", "answer_salvaged", "provisional", "verified"}
)


def _default_candidate_source(role: str) -> str:
    return {
        CandidateRole.PRIMARY_SOLVER.value: CandidateSource.LLM_PRIMARY.value,
        CandidateRole.ALTERNATIVE_SOLVER.value: (
            CandidateSource.LLM_ALTERNATIVE.value
        ),
        CandidateRole.REPAIR_AGENT.value: CandidateSource.LLM_REPAIR.value,
        CandidateRole.LLM_FINALIZER.value: CandidateSource.LLM_FINALIZER.value,
        CandidateRole.DETERMINISTIC_SHADOW.value: (
            CandidateSource.DETERMINISTIC_SHADOW.value
        ),
    }.get(role, CandidateSource.LLM_PRIMARY.value)


class ProblemType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    DERIVATION = "derivation"
    PROOF = "proof"
    EXPLANATION = "explanation"


class AnswerType(str, Enum):
    CHOICE = "choice"
    INTEGER = "integer"
    FRACTION = "fraction"
    EXPRESSION = "expression"
    VECTOR = "vector"
    TUPLE = "tuple"
    SET = "set"
    INTERVAL = "interval"
    MATRIX = "matrix"
    POLYNOMIAL = "polynomial"
    ALGEBRAIC_STRUCTURE = "algebraic_structure"
    TEXT = "text"


class ResponseMode(str, Enum):
    ANSWER_ONLY = "answer_only"
    WORKED_SOLUTION = "worked_solution"
    PROOF_FULL = "proof_full"


class TargetKind(str, Enum):
    SELECT_OPTION = "select_option"
    COMPUTE_VALUE = "compute_value"
    PROVE_STATEMENT = "prove_statement"
    DERIVE_STATEMENT = "derive_statement"
    EXPLAIN_REASON = "explain_reason"
    CONSTRUCT_OBJECT = "construct_object"
    MULTIPLE_TARGETS = "multiple_targets"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MethodFamily(str, Enum):
    SUBSTITUTION_ELIMINATION = "substitution-elimination"
    FACTORIZATION_INVARIANT = "factorization-invariant"
    STRUCTURAL_TRANSFORM = "structural-transform"
    SYNTHETIC_GEOMETRY = "synthetic-geometry"
    COORDINATE_GEOMETRY = "coordinate-geometry"
    VECTOR_TRANSFORMATION = "vector-transformation"
    CONGRUENCE = "congruence"
    VALUATION_FACTORIZATION = "valuation-factorization"
    DESCENT_EXTREMAL = "descent-extremal"
    BIJECTION_COUNTING = "bijection-counting"
    RECURRENCE_GENERATING = "recurrence-generating"
    INVARIANT_EXTREMAL = "invariant-extremal"
    CONDITIONING = "conditioning"
    INDICATOR_LINEARITY = "indicator-linearity"
    DISTRIBUTION_TRANSFORM = "distribution-transform"
    DIRECT_ANALYTIC = "direct-analytic"
    CHANGE_OF_VARIABLE = "change-of-variable"
    ESTIMATE_LIMIT = "estimate-limit"
    ROW_SPACE = "row-space"
    SPECTRAL = "spectral"
    LINEAR_MAP_INVARIANT = "linear-map-invariant"
    CALCULUS_STATIONARITY = "calculus-stationarity"
    CONVEXITY_INEQUALITY = "convexity-inequality"
    DUALITY_TRANSFORM = "duality-transform"
    DIRECT_DEDUCTION = "direct-deduction"
    CONTRADICTION = "contradiction"
    MODEL_COUNTEREXAMPLE = "model-counterexample"
    CONSTRUCTIVE_COMPUTATION = "constructive-computation"
    CONTRADICTION_EXTREMAL = "contradiction-extremal"
    CONTRADICTION_OR_EXTREMAL = "contradiction-or-extremal"
    LEMMA_GUIDED = "lemma-guided"


class MethodStepKind(str, Enum):
    DEFINITION = "definition"
    TRANSFORMATION = "transformation"
    THEOREM_APPLICATION = "theorem_application"
    CONSTRUCTION = "construction"
    CASE_SPLIT = "case_split"
    CONTRADICTION = "contradiction"
    COMPUTATION = "computation"
    CONCLUSION = "conclusion"
    OTHER = "other"


@dataclass(frozen=True)
class MethodStep:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    step_id: str
    kind: str
    claim_ids: list[str] = field(default_factory=list)
    theorem: str = ""
    schema_version: str = CORE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid MethodStep schema version")
        if not _CLAIM_ID.fullmatch(self.step_id):
            raise SchemaValidationError(f"invalid method step id: {self.step_id!r}")
        if self.kind not in {item.value for item in MethodStepKind}:
            raise SchemaValidationError(f"invalid method step kind: {self.kind}")
        _require_string_list(self.claim_ids, "MethodStep.claim_ids")
        if any(not _CLAIM_ID.fullmatch(value) for value in self.claim_ids):
            raise SchemaValidationError(f"invalid method step claim reference: {self.step_id}")
        if not isinstance(self.theorem, str) or len(self.theorem) > 256:
            raise SchemaValidationError("invalid method step theorem")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "kind": self.kind,
            "claim_ids": list(self.claim_ids),
            "theorem": self.theorem,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MethodStep":
        if not isinstance(payload, dict):
            raise SchemaValidationError("MethodStep payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        _reject_unknown_fields(
            payload,
            {"schema_version", "step_id", "kind", "claim_ids", "theorem"},
            "MethodStep",
        )
        strings = _require_string_fields(
            payload,
            ("step_id", "kind", "theorem"),
            "MethodStep",
        )
        step = cls(
            step_id=strings["step_id"],
            kind=strings["kind"],
            claim_ids=_require_string_list(
                payload.get("claim_ids"),
                "MethodStep.claim_ids",
            ),
            theorem=strings["theorem"],
            schema_version=cls.SCHEMA_VERSION,
        )
        step.validate()
        return step


def _require_schema_version(payload: dict[str, Any], expected: str) -> None:
    if payload.get("schema_version") != expected:
        raise SchemaValidationError(
            f"unsupported schema version: {payload.get('schema_version')!r}"
        )


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SchemaValidationError(f"{field_name} must be a list of strings")
    return list(value)


def _reject_unknown_fields(
    payload: dict[str, Any],
    allowed: set[str],
    schema_name: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise SchemaValidationError(f"unknown {schema_name} fields: {sorted(unknown)}")


def _require_string_fields(
    payload: dict[str, Any],
    names: tuple[str, ...],
    schema_name: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        value = payload.get(name)
        if not isinstance(value, str):
            raise SchemaValidationError(f"{schema_name}.{name} must be a string")
        result[name] = value
    return result


@dataclass
class ProblemIR:
    SCHEMA_VERSION: ClassVar[str] = PROBLEM_IR_SCHEMA_VERSION

    raw_problem: str
    normalized_problem: str
    problem_type: str
    answer_type: str
    response_mode: str = ResponseMode.ANSWER_ONLY.value
    subject_candidates: list[tuple[str, float]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    domains: dict[str, str] = field(default_factory=dict)
    requested_output: str = ""
    target_phrase: str = ""
    target_kind: str = "compute_value"
    parser_confidence: float = 0.0
    target_confidence: float = 1.0
    answer_type_confidence: float = 1.0
    response_mode_confidence: float = 1.0
    target_conflicts: list[str] = field(default_factory=list)
    answer_type_conflicts: list[str] = field(default_factory=list)
    response_mode_conflicts: list[str] = field(default_factory=list)
    requires_router_disambiguation: bool = False
    options: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    quantifiers: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    difficulty_features: list[str] = field(default_factory=list)
    subproblem_hints: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    schema_version: str = PROBLEM_IR_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "raw_problem": self.raw_problem,
            "normalized_problem": self.normalized_problem,
            "problem_type": self.problem_type,
            "answer_type": self.answer_type,
            "response_mode": self.response_mode,
            "subject_candidates": [list(item) for item in self.subject_candidates],
            "symbols": list(self.symbols),
            "assumptions": list(self.assumptions),
            "domains": dict(self.domains),
            "requested_output": self.requested_output,
            "target_phrase": self.target_phrase,
            "target_kind": self.target_kind,
            "parser_confidence": self.parser_confidence,
            "target_confidence": self.target_confidence,
            "answer_type_confidence": self.answer_type_confidence,
            "response_mode_confidence": self.response_mode_confidence,
            "target_conflicts": list(self.target_conflicts),
            "answer_type_conflicts": list(self.answer_type_conflicts),
            "response_mode_conflicts": list(self.response_mode_conflicts),
            "requires_router_disambiguation": self.requires_router_disambiguation,
            "options": list(self.options),
            "definitions": list(self.definitions),
            "quantifiers": list(self.quantifiers),
            "constraints": list(self.constraints),
            "ambiguities": list(self.ambiguities),
            "difficulty_features": list(self.difficulty_features),
            "subproblem_hints": list(self.subproblem_hints),
            "risk_flags": list(self.risk_flags),
        }

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid ProblemIR schema version")
        string_fields = (
            self.raw_problem,
            self.normalized_problem,
            self.problem_type,
            self.answer_type,
            self.response_mode,
            self.requested_output,
            self.target_phrase,
            self.target_kind,
        )
        if any(not isinstance(value, str) for value in string_fields):
            raise SchemaValidationError("ProblemIR string field has invalid type")
        if self.problem_type not in {item.value for item in ProblemType}:
            raise SchemaValidationError(f"invalid problem type: {self.problem_type}")
        if self.answer_type not in {item.value for item in AnswerType}:
            raise SchemaValidationError(f"invalid answer type: {self.answer_type}")
        if self.response_mode not in {item.value for item in ResponseMode}:
            raise SchemaValidationError(
                f"invalid response mode: {self.response_mode}"
            )
        if self.target_kind not in {item.value for item in TargetKind}:
            raise SchemaValidationError(f"invalid target kind: {self.target_kind}")
        for name, confidence in (
            ("parser", self.parser_confidence),
            ("target", self.target_confidence),
            ("answer type", self.answer_type_confidence),
            ("response mode", self.response_mode_confidence),
        ):
            if (
                type(confidence) not in {int, float}
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise SchemaValidationError(f"invalid {name} confidence")
        if not isinstance(self.requires_router_disambiguation, bool):
            raise SchemaValidationError(
                "ProblemIR.requires_router_disambiguation must be a boolean"
            )
        for name, value in (
            ("symbols", self.symbols),
            ("assumptions", self.assumptions),
            ("options", self.options),
            ("definitions", self.definitions),
            ("quantifiers", self.quantifiers),
            ("constraints", self.constraints),
            ("ambiguities", self.ambiguities),
            ("difficulty_features", self.difficulty_features),
            ("subproblem_hints", self.subproblem_hints),
            ("risk_flags", self.risk_flags),
            ("target_conflicts", self.target_conflicts),
            ("answer_type_conflicts", self.answer_type_conflicts),
            ("response_mode_conflicts", self.response_mode_conflicts),
        ):
            _require_string_list(value, f"ProblemIR.{name}")
        if not isinstance(self.domains, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.domains.items()
        ):
            raise SchemaValidationError("ProblemIR.domains must map strings to strings")
        if not isinstance(self.subject_candidates, list):
            raise SchemaValidationError("ProblemIR.subject_candidates must be a list")
        for item in self.subject_candidates:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or not isinstance(item[0], str)
                or type(item[1]) not in {int, float}
                or not 0.0 <= float(item[1]) <= 1.0
            ):
                raise SchemaValidationError(
                    "ProblemIR.subject_candidates entries must be [subject, probability]"
                )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProblemIR":
        if not isinstance(payload, dict):
            raise SchemaValidationError("ProblemIR payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        allowed = {
            "schema_version",
            "raw_problem",
            "normalized_problem",
            "problem_type",
            "answer_type",
            "response_mode",
            "subject_candidates",
            "symbols",
            "assumptions",
            "domains",
            "requested_output",
            "target_phrase",
            "target_kind",
            "parser_confidence",
            "target_confidence",
            "answer_type_confidence",
            "response_mode_confidence",
            "target_conflicts",
            "answer_type_conflicts",
            "response_mode_conflicts",
            "requires_router_disambiguation",
            "options",
            "definitions",
            "quantifiers",
            "constraints",
            "ambiguities",
            "difficulty_features",
            "subproblem_hints",
            "risk_flags",
        }
        _reject_unknown_fields(payload, allowed, "ProblemIR")
        strings = _require_string_fields(
            payload,
            (
                "raw_problem",
                "normalized_problem",
                "problem_type",
                "answer_type",
                "response_mode",
                "requested_output",
                "target_phrase",
                "target_kind",
            ),
            "ProblemIR",
        )
        raw_subjects = payload.get("subject_candidates")
        if not isinstance(raw_subjects, list):
            raise SchemaValidationError("ProblemIR.subject_candidates must be a list")
        raw_domains = payload.get("domains")
        if not isinstance(raw_domains, dict):
            raise SchemaValidationError("ProblemIR.domains must be an object")
        raw_parser_confidence = payload.get("parser_confidence")
        if not isinstance(raw_parser_confidence, (int, float)) or isinstance(
            raw_parser_confidence,
            bool,
        ):
            raise SchemaValidationError(
                "ProblemIR.parser_confidence must be numeric"
            )
        raw_answer_type_confidence = payload.get("answer_type_confidence")
        if not isinstance(
            raw_answer_type_confidence,
            (int, float),
        ) or isinstance(raw_answer_type_confidence, bool):
            raise SchemaValidationError(
                "ProblemIR.answer_type_confidence must be numeric"
            )
        raw_target_confidence = payload.get("target_confidence")
        if not isinstance(raw_target_confidence, (int, float)) or isinstance(
            raw_target_confidence,
            bool,
        ):
            raise SchemaValidationError("ProblemIR.target_confidence must be numeric")
        raw_response_mode_confidence = payload.get("response_mode_confidence")
        if not isinstance(
            raw_response_mode_confidence,
            (int, float),
        ) or isinstance(raw_response_mode_confidence, bool):
            raise SchemaValidationError(
                "ProblemIR.response_mode_confidence must be numeric"
            )
        raw_requires_disambiguation = payload.get("requires_router_disambiguation")
        if not isinstance(raw_requires_disambiguation, bool):
            raise SchemaValidationError(
                "ProblemIR.requires_router_disambiguation must be a boolean"
            )
        problem = cls(
            raw_problem=strings["raw_problem"],
            normalized_problem=strings["normalized_problem"],
            problem_type=strings["problem_type"],
            answer_type=strings["answer_type"],
            response_mode=strings["response_mode"],
            subject_candidates=[
                tuple(item) if isinstance(item, list) else item
                for item in raw_subjects
            ],
            symbols=_require_string_list(payload.get("symbols"), "ProblemIR.symbols"),
            assumptions=_require_string_list(
                payload.get("assumptions"),
                "ProblemIR.assumptions",
            ),
            domains=dict(raw_domains),
            requested_output=strings["requested_output"],
            target_phrase=strings["target_phrase"],
            target_kind=strings["target_kind"],
            parser_confidence=float(raw_parser_confidence),
            target_confidence=float(raw_target_confidence),
            answer_type_confidence=float(raw_answer_type_confidence),
            response_mode_confidence=float(raw_response_mode_confidence),
            target_conflicts=_require_string_list(
                payload.get("target_conflicts"),
                "ProblemIR.target_conflicts",
            ),
            answer_type_conflicts=_require_string_list(
                payload.get("answer_type_conflicts"),
                "ProblemIR.answer_type_conflicts",
            ),
            response_mode_conflicts=_require_string_list(
                payload.get("response_mode_conflicts"),
                "ProblemIR.response_mode_conflicts",
            ),
            requires_router_disambiguation=raw_requires_disambiguation,
            options=_require_string_list(payload.get("options"), "ProblemIR.options"),
            definitions=_require_string_list(
                payload.get("definitions"),
                "ProblemIR.definitions",
            ),
            quantifiers=_require_string_list(
                payload.get("quantifiers"),
                "ProblemIR.quantifiers",
            ),
            constraints=_require_string_list(
                payload.get("constraints"),
                "ProblemIR.constraints",
            ),
            ambiguities=_require_string_list(
                payload.get("ambiguities"),
                "ProblemIR.ambiguities",
            ),
            difficulty_features=_require_string_list(
                payload.get("difficulty_features"),
                "ProblemIR.difficulty_features",
            ),
            subproblem_hints=_require_string_list(
                payload.get("subproblem_hints"),
                "ProblemIR.subproblem_hints",
            ),
            risk_flags=_require_string_list(
                payload.get("risk_flags"),
                "ProblemIR.risk_flags",
            ),
            schema_version=cls.SCHEMA_VERSION,
        )
        problem.validate()
        return problem

    @property
    def interpretation_conflicts(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *self.target_conflicts,
                    *self.answer_type_conflicts,
                    *self.response_mode_conflicts,
                ]
            )
        )


@dataclass(frozen=True)
class CheckSpec:
    """Host-owned, typed description of one local Claim check."""

    SCHEMA_VERSION: ClassVar[str] = "1.0"

    tool_name: str
    arguments: dict[str, Any]
    status: str
    reason_code: str
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid CheckSpec schema version")
        if not isinstance(self.tool_name, str):
            raise SchemaValidationError("CheckSpec.tool_name must be a string")
        if not isinstance(self.arguments, dict):
            raise SchemaValidationError("CheckSpec.arguments must be an object")
        if self.status not in {
            "ready",
            "unsupported",
            "route_not_selected",
            "argument_unavailable",
            "schema_invalid",
        }:
            raise SchemaValidationError("CheckSpec.status is invalid")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise SchemaValidationError("CheckSpec.reason_code is required")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "status": self.status,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckSpec":
        if not isinstance(payload, dict):
            raise SchemaValidationError("CheckSpec payload must be an object")
        allowed = {
            "schema_version",
            "tool_name",
            "arguments",
            "status",
            "reason_code",
        }
        _reject_unknown_fields(payload, allowed, "CheckSpec")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        spec = cls(
            tool_name=str(payload.get("tool_name", "")),
            arguments=dict(payload.get("arguments", {})),
            status=str(payload.get("status", "")),
            reason_code=str(payload.get("reason_code", "")),
            schema_version=cls.SCHEMA_VERSION,
        )
        spec.validate()
        return spec


@dataclass
class Claim:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    claim_id: str
    statement: str
    depends_on: list[str] = field(default_factory=list)
    check_type: str = "reasoning"
    importance: str = "supporting"
    status: str = "unverified"
    claim_kind: str = "unknown"
    verification_state: str = "unknown"
    check_spec: CheckSpec | None = None
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload = {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
            "check_type": self.check_type,
            "importance": self.importance,
            "status": self.status,
            "claim_kind": self.claim_kind,
            "verification_state": self.verification_state,
        }
        if self.check_spec is not None:
            payload["check_spec"] = self.check_spec.to_dict()
        return payload

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid Claim schema version")
        string_fields = (
            self.claim_id,
            self.statement,
            self.check_type,
            self.importance,
            self.status,
            self.claim_kind,
            self.verification_state,
        )
        if any(not isinstance(value, str) for value in string_fields):
            raise SchemaValidationError("Claim string field has invalid type")
        if self.check_spec is not None:
            if not isinstance(self.check_spec, CheckSpec):
                raise SchemaValidationError("Claim.check_spec has invalid type")
            self.check_spec.validate()
        _require_string_list(self.depends_on, "Claim.depends_on")
        if not _CLAIM_ID.fullmatch(self.claim_id):
            raise SchemaValidationError(f"invalid claim id: {self.claim_id!r}")
        if len(self.statement) > MAX_CLAIM_STATEMENT_CHARS:
            raise SchemaValidationError(f"claim statement too long: {self.claim_id}")
        if len(self.depends_on) > MAX_CLAIMS:
            raise SchemaValidationError(f"too many dependencies: {self.claim_id}")
        if any(not _CLAIM_ID.fullmatch(value) for value in self.depends_on):
            raise SchemaValidationError(f"invalid claim dependency: {self.claim_id}")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Claim":
        if not isinstance(payload, dict):
            raise SchemaValidationError("Claim payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        allowed = {
            "schema_version",
            "claim_id",
            "statement",
            "depends_on",
            "check_type",
            "importance",
            "status",
            "claim_kind",
            "verification_state",
            "check_spec",
        }
        _reject_unknown_fields(payload, allowed, "Claim")
        string_fields = _require_string_fields(
            payload,
            (
                "claim_id",
                "statement",
                "check_type",
                "importance",
                "status",
                "claim_kind",
                "verification_state",
            ),
            "Claim",
        )
        claim = cls(
            claim_id=string_fields["claim_id"],
            statement=string_fields["statement"],
            depends_on=_require_string_list(
                payload.get("depends_on"),
                "Claim.depends_on",
            ),
            check_type=string_fields["check_type"],
            importance=string_fields["importance"],
            status=string_fields["status"],
            claim_kind=string_fields["claim_kind"],
            verification_state=string_fields["verification_state"],
            check_spec=(
                CheckSpec.from_dict(payload["check_spec"])
                if payload.get("check_spec") is not None
                else None
            ),
            schema_version=cls.SCHEMA_VERSION,
        )
        claim.validate()
        return claim


@dataclass
class CandidatePatch:
    source_candidate_id: str
    base_version: int
    affected_claim_ids: list[str]
    replacement_claims: list[Claim]
    final_answer: str = ""
    public_solution_steps: list[str] = field(default_factory=list)
    unresolved_obligations: list[str] = field(default_factory=list)
    parse_status: str = "strict_json"
    contract_deviations: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.source_candidate_id:
            raise SchemaValidationError("CandidatePatch source identity is required")
        if type(self.base_version) is not int or self.base_version < 1:
            raise SchemaValidationError("CandidatePatch base version is invalid")
        _require_string_list(
            self.affected_claim_ids,
            "CandidatePatch.affected_claim_ids",
        )
        _require_string_list(
            self.public_solution_steps,
            "CandidatePatch.public_solution_steps",
        )
        _require_string_list(
            self.unresolved_obligations,
            "CandidatePatch.unresolved_obligations",
        )
        _require_string_list(
            self.contract_deviations,
            "CandidatePatch.contract_deviations",
        )
        if not self.affected_claim_ids:
            raise SchemaValidationError("CandidatePatch affected claims are empty")
        if not isinstance(self.final_answer, str):
            raise SchemaValidationError("CandidatePatch final answer must be a string")
        affected = set(self.affected_claim_ids)
        replacement_ids: set[str] = set()
        for claim in self.replacement_claims:
            claim.validate()
            if claim.claim_id not in affected:
                raise SchemaValidationError(
                    "CandidatePatch contains an unrelated replacement"
                )
            if claim.claim_id in replacement_ids:
                raise SchemaValidationError(
                    "CandidatePatch contains a duplicate replacement"
                )
            replacement_ids.add(claim.claim_id)
        if not replacement_ids:
            raise SchemaValidationError("CandidatePatch has no replacement claims")

    def to_dict(self) -> dict:
        return {
            "source_candidate_id": self.source_candidate_id,
            "base_version": self.base_version,
            "affected_claim_ids": list(self.affected_claim_ids),
            "replacement_claims": [
                claim.to_dict() for claim in self.replacement_claims
            ],
            "final_answer": self.final_answer,
            "public_solution_steps": list(self.public_solution_steps),
            "unresolved_obligations": list(self.unresolved_obligations),
            "parse_status": self.parse_status,
            "contract_deviations": list(self.contract_deviations),
        }


@dataclass
class CandidateSolution:
    SCHEMA_VERSION: ClassVar[str] = CANDIDATE_SCHEMA_VERSION

    candidate_id: str
    role: str
    method: str
    final_answer: str
    answer_type: str
    assumptions: list[str] = field(default_factory=list)
    theorems: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    public_solution_steps: list[str] = field(default_factory=list)
    solution_text: str = ""
    unresolved_obligations: list[str] = field(default_factory=list)
    parse_status: str = "parsed"
    version: int = 1
    planned_method_family: str = ""
    is_method_duplicate: bool = False
    contract_deviations: list[str] = field(default_factory=list)
    method_steps: list[MethodStep] = field(default_factory=list)
    source: str = CandidateSource.LLM_PRIMARY.value
    parse_tier: str = CandidateParseTier.STRICT.value
    degraded: bool = False
    # Host-owned assurance label.  ``emergency`` and ``recovered`` are
    # intentionally visible so arbitration and reports cannot mistake a
    # degraded answer for an ordinary Candidate.
    assurance: str = "standard"
    schema_version: str = CANDIDATE_SCHEMA_VERSION
    # E6 Host-owned cognitive provenance.  These fields are optional for
    # legacy payloads but are carried across repair versions and candidate
    # pool registration whenever available.
    method_family: str = ""
    shared_context_hash: str = ""
    private_context_hash: str = ""
    skill_set_hash: str = ""
    lemma_ids: list[str] = field(default_factory=list)
    proof_backbone_hash: str = ""
    model_identity: str = ""
    prompt_hash: str = ""
    branch_id: str = ""
    branch_context_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "role": self.role,
            "method": self.method,
            "final_answer": self.final_answer,
            "answer_type": self.answer_type,
            "assumptions": list(self.assumptions),
            "theorems": list(self.theorems),
            "claims": [claim.to_dict() for claim in self.claims],
            "public_solution_steps": list(self.public_solution_steps),
            "solution_text": self.solution_text,
            "unresolved_obligations": list(self.unresolved_obligations),
            "parse_status": self.parse_status,
            "version": self.version,
            "planned_method_family": self.planned_method_family,
            "is_method_duplicate": self.is_method_duplicate,
            "contract_deviations": list(self.contract_deviations),
            "method_steps": [step.to_dict() for step in self.method_steps],
            "source": self.source,
            "parse_tier": self.parse_tier,
            "degraded": self.degraded,
            "assurance": self.assurance,
            "method_family": self.method_family,
            "shared_context_hash": self.shared_context_hash,
            "private_context_hash": self.private_context_hash,
            "skill_set_hash": self.skill_set_hash,
            "lemma_ids": list(self.lemma_ids),
            "proof_backbone_hash": self.proof_backbone_hash,
            "model_identity": self.model_identity,
            "prompt_hash": self.prompt_hash,
            "branch_id": self.branch_id,
            "branch_context_hash": self.branch_context_hash,
        }

    @property
    def cognitive_provenance(self) -> dict[str, Any]:
        """Return the public provenance used by the independence gate."""

        return {
            "method_family": self.method_family or self.planned_method_family or self.method,
            "shared_context_hash": self.shared_context_hash,
            "private_context_hash": self.private_context_hash,
            "skill_set_hash": self.skill_set_hash,
            "lemma_ids": list(self.lemma_ids),
            "proof_backbone_hash": self.proof_backbone_hash,
            "model_identity": self.model_identity,
            "prompt_hash": self.prompt_hash,
            "branch_id": self.branch_id,
            "branch_context_hash": self.branch_context_hash,
        }

    @property
    def provenance(self) -> dict[str, Any]:
        """Compatibility alias for callers that use the shorter name."""

        return self.cognitive_provenance

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid CandidateSolution schema version")
        string_fields = (
            self.candidate_id,
            self.role,
            self.method,
            self.final_answer,
            self.answer_type,
            self.solution_text,
            self.parse_status,
            self.planned_method_family,
            self.source,
            self.parse_tier,
            self.assurance,
            self.method_family,
            self.shared_context_hash,
            self.private_context_hash,
            self.skill_set_hash,
            self.proof_backbone_hash,
            self.model_identity,
            self.prompt_hash,
            self.branch_id,
            self.branch_context_hash,
        )
        if any(not isinstance(value, str) for value in string_fields):
            raise SchemaValidationError(
                "CandidateSolution string field has invalid type"
            )
        if self.role not in {item.value for item in CandidateRole}:
            raise SchemaValidationError(f"invalid candidate role: {self.role}")
        if self.source not in {item.value for item in CandidateSource}:
            raise SchemaValidationError(f"invalid candidate source: {self.source}")
        if self.parse_tier not in {item.value for item in CandidateParseTier}:
            raise SchemaValidationError(
                f"invalid candidate parse tier: {self.parse_tier}"
            )
        if self.answer_type not in {item.value for item in AnswerType}:
            raise SchemaValidationError(f"invalid candidate answer type: {self.answer_type}")
        if (
            not self.candidate_id
            or len(self.candidate_id) > 128
            or "::" in self.candidate_id
        ):
            raise SchemaValidationError("invalid candidate id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise SchemaValidationError("invalid candidate version")
        if len(self.method) > 256:
            raise SchemaValidationError("candidate method is too long")
        if not isinstance(self.claims, list) or any(
            not isinstance(claim, Claim) for claim in self.claims
        ):
            raise SchemaValidationError(
                "CandidateSolution.claims must be a list of Claim objects"
            )
        if len(self.claims) > MAX_CLAIMS:
            raise SchemaValidationError(f"claim count exceeds {MAX_CLAIMS}")
        for name, value in (
            ("assumptions", self.assumptions),
            ("theorems", self.theorems),
            ("public_solution_steps", self.public_solution_steps),
            ("unresolved_obligations", self.unresolved_obligations),
            ("contract_deviations", self.contract_deviations),
            ("lemma_ids", self.lemma_ids),
        ):
            _require_string_list(value, f"CandidateSolution.{name}")
        if not isinstance(self.is_method_duplicate, bool):
            raise SchemaValidationError(
                "CandidateSolution.is_method_duplicate must be a boolean"
            )
        if not isinstance(self.degraded, bool):
            raise SchemaValidationError(
                "CandidateSolution.degraded must be a boolean"
            )
        if self.assurance not in _CANDIDATE_ASSURANCE:
            raise SchemaValidationError("invalid CandidateSolution assurance")
        if self.planned_method_family and self.planned_method_family not in {
            item.value for item in MethodFamily
        }:
            raise SchemaValidationError(
                f"invalid planned method family: {self.planned_method_family}"
            )
        if (
            not isinstance(self.method_steps, list)
            or len(self.method_steps) > MAX_METHOD_STEPS
            or any(not isinstance(step, MethodStep) for step in self.method_steps)
        ):
            raise SchemaValidationError(
                "CandidateSolution.method_steps must be a bounded MethodStep list"
            )
        if sum(len(claim.statement) for claim in self.claims) > MAX_TOTAL_CLAIM_CHARS:
            raise SchemaValidationError("total claim text is too long")
        for claim in self.claims:
            claim.validate()
        self._validate_claim_graph()
        self._validate_method_steps()

    def _validate_claim_graph(self) -> None:
        claim_by_id: dict[str, Claim] = {}
        for claim in self.claims:
            if claim.claim_id in claim_by_id:
                raise SchemaValidationError(f"duplicate claim id: {claim.claim_id}")
            claim_by_id[claim.claim_id] = claim
        for claim in self.claims:
            for dependency in claim.depends_on:
                if dependency not in claim_by_id:
                    raise SchemaValidationError(
                        f"unknown dependency {dependency} for claim {claim.claim_id}"
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(claim_id: str) -> None:
            if claim_id in visiting:
                raise SchemaValidationError("claim dependency cycle")
            if claim_id in visited:
                return
            visiting.add(claim_id)
            for dependency in claim_by_id[claim_id].depends_on:
                visit(dependency)
            visiting.remove(claim_id)
            visited.add(claim_id)

        for claim_id in claim_by_id:
            visit(claim_id)

    def _validate_method_steps(self) -> None:
        claim_ids = {claim.claim_id for claim in self.claims}
        step_ids: set[str] = set()
        for step in self.method_steps:
            step.validate()
            if step.step_id in step_ids:
                raise SchemaValidationError(f"duplicate method step id: {step.step_id}")
            step_ids.add(step.step_id)
            unknown = set(step.claim_ids) - claim_ids
            if unknown:
                raise SchemaValidationError(
                    f"unknown method step claim references: {sorted(unknown)}"
                )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateSolution":
        if not isinstance(payload, dict):
            raise SchemaValidationError("CandidateSolution payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        allowed = {
            "schema_version",
            "candidate_id",
            "role",
            "method",
            "final_answer",
            "answer_type",
            "assumptions",
            "theorems",
            "claims",
            "public_solution_steps",
            "solution_text",
            "unresolved_obligations",
            "parse_status",
            "version",
            "planned_method_family",
            "is_method_duplicate",
            "contract_deviations",
            "method_steps",
            "source",
            "parse_tier",
            "degraded",
            "assurance",
            "method_family",
            "shared_context_hash",
            "private_context_hash",
            "skill_set_hash",
            "lemma_ids",
            "proof_backbone_hash",
            "model_identity",
            "prompt_hash",
            "branch_id",
            "branch_context_hash",
        }
        _reject_unknown_fields(payload, allowed, "CandidateSolution")
        strings = _require_string_fields(
            payload,
            (
                "candidate_id",
                "role",
                "method",
                "final_answer",
                "answer_type",
                "solution_text",
                "parse_status",
                "planned_method_family",
            ),
            "CandidateSolution",
        )
        raw_claims = payload.get("claims")
        if not isinstance(raw_claims, list) or any(
            not isinstance(item, dict) for item in raw_claims
        ):
            raise SchemaValidationError("CandidateSolution.claims must be objects")
        raw_method_steps = payload.get("method_steps")
        if not isinstance(raw_method_steps, list) or any(
            not isinstance(item, dict) for item in raw_method_steps
        ):
            raise SchemaValidationError(
                "CandidateSolution.method_steps must be objects"
            )
        version = payload.get("version")
        duplicate = payload.get("is_method_duplicate")
        degraded = payload.get("degraded", False)
        assurance = payload.get("assurance", "standard")
        if not isinstance(version, int) or isinstance(version, bool):
            raise SchemaValidationError("CandidateSolution.version must be an integer")
        if not isinstance(duplicate, bool):
            raise SchemaValidationError(
                "CandidateSolution.is_method_duplicate must be a boolean"
            )
        if not isinstance(degraded, bool):
            raise SchemaValidationError(
                "CandidateSolution.degraded must be a boolean"
            )
        if not isinstance(assurance, str) or assurance not in _CANDIDATE_ASSURANCE:
            raise SchemaValidationError(
                "CandidateSolution.assurance must be a known string"
            )
        candidate = cls(
            candidate_id=strings["candidate_id"],
            role=strings["role"],
            method=strings["method"],
            final_answer=strings["final_answer"],
            answer_type=strings["answer_type"],
            assumptions=_require_string_list(
                payload.get("assumptions"),
                "CandidateSolution.assumptions",
            ),
            theorems=_require_string_list(
                payload.get("theorems"),
                "CandidateSolution.theorems",
            ),
            claims=[Claim.from_dict(item) for item in raw_claims],
            public_solution_steps=_require_string_list(
                payload.get("public_solution_steps"),
                "CandidateSolution.public_solution_steps",
            ),
            solution_text=strings["solution_text"],
            unresolved_obligations=_require_string_list(
                payload.get("unresolved_obligations"),
                "CandidateSolution.unresolved_obligations",
            ),
            parse_status=strings["parse_status"],
            version=version,
            planned_method_family=strings["planned_method_family"],
            is_method_duplicate=duplicate,
            contract_deviations=_require_string_list(
                payload.get("contract_deviations"),
                "CandidateSolution.contract_deviations",
            ),
            method_steps=[
                MethodStep.from_dict(item) for item in raw_method_steps
            ],
            source=str(
                payload.get(
                    "source",
                    _default_candidate_source(strings["role"]),
                )
            ),
            parse_tier=str(
                payload.get("parse_tier", CandidateParseTier.STRICT.value)
            ),
            degraded=degraded,
            assurance=assurance,
            schema_version=cls.SCHEMA_VERSION,
            method_family=str(payload.get("method_family", "")),
            shared_context_hash=str(payload.get("shared_context_hash", "")),
            private_context_hash=str(payload.get("private_context_hash", "")),
            skill_set_hash=str(payload.get("skill_set_hash", "")),
            lemma_ids=_require_string_list(
                payload.get("lemma_ids", []),
                "CandidateSolution.lemma_ids",
            ),
            proof_backbone_hash=str(payload.get("proof_backbone_hash", "")),
            model_identity=str(payload.get("model_identity", "")),
            prompt_hash=str(payload.get("prompt_hash", "")),
            branch_id=str(payload.get("branch_id", "")),
            branch_context_hash=str(payload.get("branch_context_hash", "")),
        )
        candidate.validate()
        return candidate


@dataclass
class RoutePlan:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    primary_subject: str
    auxiliary_subject: str | None
    problem_type: str
    answer_type: str
    risk_level: str
    selected_skills: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    candidate_count: int = 1
    max_reasoning_rounds: int = 1
    use_rag: bool = False
    use_lemma_loop: bool = False
    use_llm_finalizer: bool = False
    method_families: list[str] = field(default_factory=list)
    routing_confidence: float = 0.0
    ambiguity_margin: float = 1.0
    complexity_flags: list[str] = field(default_factory=list)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "primary_subject": self.primary_subject,
            "auxiliary_subject": self.auxiliary_subject,
            "problem_type": self.problem_type,
            "answer_type": self.answer_type,
            "risk_level": self.risk_level,
            "selected_skills": list(self.selected_skills),
            "selected_tools": list(self.selected_tools),
            "candidate_count": self.candidate_count,
            "max_reasoning_rounds": self.max_reasoning_rounds,
            "use_rag": self.use_rag,
            "use_lemma_loop": self.use_lemma_loop,
            "use_llm_finalizer": self.use_llm_finalizer,
            "method_families": list(self.method_families),
            "routing_confidence": self.routing_confidence,
            "ambiguity_margin": self.ambiguity_margin,
            "complexity_flags": list(self.complexity_flags),
        }

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid RoutePlan schema version")
        string_fields = (
            self.primary_subject,
            self.problem_type,
            self.answer_type,
            self.risk_level,
        )
        if any(not isinstance(value, str) for value in string_fields):
            raise SchemaValidationError("RoutePlan string field has invalid type")
        if self.auxiliary_subject is not None and not isinstance(
            self.auxiliary_subject,
            str,
        ):
            raise SchemaValidationError(
                "RoutePlan.auxiliary_subject must be a string or null"
            )
        if self.problem_type not in {item.value for item in ProblemType}:
            raise SchemaValidationError(f"invalid route problem type: {self.problem_type}")
        if self.answer_type not in {item.value for item in AnswerType}:
            raise SchemaValidationError(f"invalid route answer type: {self.answer_type}")
        if self.risk_level not in {item.value for item in RiskLevel}:
            raise SchemaValidationError(f"invalid route risk level: {self.risk_level}")
        if (
            type(self.candidate_count) is not int
            or type(self.max_reasoning_rounds) is not int
        ):
            raise SchemaValidationError("RoutePlan counts must be integers")
        if not 1 <= self.candidate_count <= 3:
            raise SchemaValidationError("invalid route candidate count")
        if not 1 <= self.max_reasoning_rounds <= 3:
            raise SchemaValidationError("invalid route reasoning rounds")
        for name, value in (
            ("selected_skills", self.selected_skills),
            ("selected_tools", self.selected_tools),
            ("method_families", self.method_families),
            ("complexity_flags", self.complexity_flags),
        ):
            _require_string_list(value, f"RoutePlan.{name}")
        invalid_method_families = sorted(
            set(self.method_families)
            - {item.value for item in MethodFamily}
        )
        if invalid_method_families:
            raise SchemaValidationError(
                f"invalid route method families: {invalid_method_families}"
            )
        for name, numeric_value in (
            ("routing_confidence", self.routing_confidence),
            ("ambiguity_margin", self.ambiguity_margin),
        ):
            if (
                type(numeric_value) not in {int, float}
                or not 0.0 <= float(numeric_value) <= 1.0
            ):
                raise SchemaValidationError(f"RoutePlan.{name} must be in [0, 1]")
        for name, bool_value in (
            ("use_rag", self.use_rag),
            ("use_lemma_loop", self.use_lemma_loop),
            ("use_llm_finalizer", self.use_llm_finalizer),
        ):
            if not isinstance(bool_value, bool):
                raise SchemaValidationError(f"RoutePlan.{name} must be a boolean")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutePlan":
        if not isinstance(payload, dict):
            raise SchemaValidationError("RoutePlan payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        allowed = {
            "schema_version",
            "primary_subject",
            "auxiliary_subject",
            "problem_type",
            "answer_type",
            "risk_level",
            "selected_skills",
            "selected_tools",
            "candidate_count",
            "max_reasoning_rounds",
            "use_rag",
            "use_lemma_loop",
            "use_llm_finalizer",
            "method_families",
            "routing_confidence",
            "ambiguity_margin",
            "complexity_flags",
        }
        _reject_unknown_fields(payload, allowed, "RoutePlan")
        strings = _require_string_fields(
            payload,
            (
                "primary_subject",
                "problem_type",
                "answer_type",
                "risk_level",
            ),
            "RoutePlan",
        )
        auxiliary = payload.get("auxiliary_subject")
        if auxiliary is not None and not isinstance(auxiliary, str):
            raise SchemaValidationError(
                "RoutePlan.auxiliary_subject must be a string or null"
            )
        candidate_count = payload.get("candidate_count")
        reasoning_rounds = payload.get("max_reasoning_rounds")
        if type(candidate_count) is not int or type(reasoning_rounds) is not int:
            raise SchemaValidationError("RoutePlan counts must be integers")
        bool_names = ("use_rag", "use_lemma_loop", "use_llm_finalizer")
        if any(not isinstance(payload.get(name), bool) for name in bool_names):
            invalid = next(
                name for name in bool_names if not isinstance(payload.get(name), bool)
            )
            raise SchemaValidationError(f"RoutePlan.{invalid} must be a boolean")
        numeric_names = ("routing_confidence", "ambiguity_margin")
        if any(type(payload.get(name)) not in {int, float} for name in numeric_names):
            invalid = next(
                name
                for name in numeric_names
                if type(payload.get(name)) not in {int, float}
            )
            raise SchemaValidationError(f"RoutePlan.{invalid} must be numeric")
        route = cls(
            primary_subject=strings["primary_subject"],
            auxiliary_subject=auxiliary,
            problem_type=strings["problem_type"],
            answer_type=strings["answer_type"],
            risk_level=strings["risk_level"],
            selected_skills=_require_string_list(
                payload.get("selected_skills"),
                "RoutePlan.selected_skills",
            ),
            selected_tools=_require_string_list(
                payload.get("selected_tools"),
                "RoutePlan.selected_tools",
            ),
            candidate_count=candidate_count,
            max_reasoning_rounds=reasoning_rounds,
            use_rag=payload["use_rag"],
            use_lemma_loop=payload["use_lemma_loop"],
            use_llm_finalizer=payload["use_llm_finalizer"],
            method_families=_require_string_list(
                payload.get("method_families"),
                "RoutePlan.method_families",
            ),
            routing_confidence=float(payload["routing_confidence"]),
            ambiguity_margin=float(payload["ambiguity_margin"]),
            complexity_flags=_require_string_list(
                payload.get("complexity_flags"),
                "RoutePlan.complexity_flags",
            ),
            schema_version=cls.SCHEMA_VERSION,
        )
        route.validate()
        return route


@dataclass
class EvidenceRecord:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    evidence_id: str
    candidate_id: str
    claim_id: str | None
    evidence_type: str
    status: str
    strength: str
    description: str
    payload: dict[str, Any] = field(default_factory=dict)
    invocation: dict[str, Any] = field(default_factory=dict)
    capability: str = "none"
    transaction_status: str = "active"
    schema_version: str = CORE_SCHEMA_VERSION

    @property
    def failure_taxonomy(self) -> str:
        """Canonical E6 status without changing the legacy wire status."""

        from mathforge.verification.e6 import evidence_status

        return evidence_status(self.status, reason=self.description)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "candidate_id": self.candidate_id,
            "claim_id": self.claim_id,
            "evidence_type": self.evidence_type,
            "status": self.status,
            "strength": self.strength,
            "description": self.description,
            "payload": dict(self.payload),
            "invocation": dict(self.invocation),
            "capability": self.capability,
            "transaction_status": self.transaction_status,
        }


@dataclass
class ProofObligation:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    obligation_id: str
    kind: str
    description: str
    required: bool = True
    status: str = "unresolved"
    source_claim_ids: list[str] = field(default_factory=list)
    satisfaction_evidence_ids: list[str] = field(default_factory=list)
    origin: str = "candidate"
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "description": self.description,
            "required": self.required,
            "status": self.status,
            "origin": self.origin,
            "source_claim_ids": list(self.source_claim_ids),
            "satisfaction_evidence_ids": list(self.satisfaction_evidence_ids),
        }


@dataclass
class LemmaCard:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    lemma_id: str
    statement: str
    conditions: list[str]
    dependencies: list[str]
    proof_sketch: str
    status: str
    evidence_ids: list[str]
    source_round: int
    scope: str = "current_problem"
    source_candidate_id: str = ""
    source_claim_id: str = ""
    claim_kind: str = "unknown"
    check_spec: CheckSpec | None = None
    target_obligation_ids: list[str] = field(default_factory=list)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "lemma_id": self.lemma_id,
            "statement": self.statement,
            "conditions": list(self.conditions),
            "dependencies": list(self.dependencies),
            "proof_sketch": self.proof_sketch,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "source_round": self.source_round,
            "scope": self.scope,
            "source_candidate_id": self.source_candidate_id,
            "source_claim_id": self.source_claim_id,
            "claim_kind": self.claim_kind,
            "check_spec": (
                self.check_spec.to_dict()
                if self.check_spec is not None
                else None
            ),
            "target_obligation_ids": list(self.target_obligation_ids),
        }

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid LemmaCard schema version")
        for string_value, name in (
            (self.lemma_id, "lemma_id"),
            (self.statement, "statement"),
            (self.proof_sketch, "proof_sketch"),
            (self.status, "status"),
            (self.scope, "scope"),
            (self.source_candidate_id, "source_candidate_id"),
            (self.source_claim_id, "source_claim_id"),
            (self.claim_kind, "claim_kind"),
        ):
            if not isinstance(string_value, str):
                raise SchemaValidationError(f"LemmaCard.{name} must be a string")
        for list_value, name in (
            (self.conditions, "conditions"),
            (self.dependencies, "dependencies"),
            (self.evidence_ids, "evidence_ids"),
            (self.target_obligation_ids, "target_obligation_ids"),
        ):
            _require_string_list(list_value, f"LemmaCard.{name}")
        if self.check_spec is not None:
            self.check_spec.validate()
        if not self.lemma_id or "::lemma::" not in self.lemma_id:
            raise SchemaValidationError("LemmaCard.lemma_id must be namespaced")
        if not self.source_candidate_id or not self.source_claim_id:
            raise SchemaValidationError("LemmaCard source identity is required")
        if type(self.source_round) is not int or self.source_round < 1:
            raise SchemaValidationError("LemmaCard.source_round must be positive")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LemmaCard":
        if not isinstance(payload, dict):
            raise SchemaValidationError("LemmaCard payload must be an object")
        _require_schema_version(payload, cls.SCHEMA_VERSION)
        allowed = {
            "schema_version",
            "lemma_id",
            "statement",
            "conditions",
            "dependencies",
            "proof_sketch",
            "status",
            "evidence_ids",
            "source_round",
            "scope",
            "source_candidate_id",
            "source_claim_id",
            "claim_kind",
            "check_spec",
            "target_obligation_ids",
        }
        _reject_unknown_fields(payload, allowed, "LemmaCard")
        strings = _require_string_fields(
            payload,
            (
                "lemma_id",
                "statement",
                "proof_sketch",
                "status",
                "scope",
                "source_candidate_id",
                "source_claim_id",
            ),
            "LemmaCard",
        )
        source_round = payload.get("source_round")
        if type(source_round) is not int:
            raise SchemaValidationError("LemmaCard.source_round must be an integer")
        card = cls(
            lemma_id=strings["lemma_id"],
            statement=strings["statement"],
            conditions=_require_string_list(
                payload.get("conditions"),
                "LemmaCard.conditions",
            ),
            dependencies=_require_string_list(
                payload.get("dependencies"),
                "LemmaCard.dependencies",
            ),
            proof_sketch=strings["proof_sketch"],
            status=strings["status"],
            evidence_ids=_require_string_list(
                payload.get("evidence_ids"),
                "LemmaCard.evidence_ids",
            ),
            source_round=source_round,
            scope=strings["scope"],
            source_candidate_id=strings["source_candidate_id"],
            source_claim_id=strings["source_claim_id"],
            claim_kind=str(payload.get("claim_kind", "unknown")),
            check_spec=(
                CheckSpec.from_dict(payload["check_spec"])
                if payload.get("check_spec") is not None
                else None
            ),
            target_obligation_ids=_require_string_list(
                payload.get("target_obligation_ids", []),
                "LemmaCard.target_obligation_ids",
            ),
            schema_version=cls.SCHEMA_VERSION,
        )
        card.validate()
        return card


@dataclass
class RoundState:
    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    round_id: int
    input_lemma_ids: list[str]
    candidate_lemma_ids: list[str]
    verified_lemma_ids: list[str]
    rejected_lemma_ids: list[str]
    resolved_obligations: list[str]
    unresolved_obligations: list[str]
    conflict_count: int
    progress_score: float
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "round_id": self.round_id,
            "input_lemma_ids": list(self.input_lemma_ids),
            "candidate_lemma_ids": list(self.candidate_lemma_ids),
            "verified_lemma_ids": list(self.verified_lemma_ids),
            "rejected_lemma_ids": list(self.rejected_lemma_ids),
            "resolved_obligations": list(self.resolved_obligations),
            "unresolved_obligations": list(self.unresolved_obligations),
            "conflict_count": self.conflict_count,
            "progress_score": self.progress_score,
        }


@dataclass
class MathSession:
    session_id: str
    problem: str
    metadata: dict[str, Any]
    budget: CallBudget
    problem_ir: ProblemIR | None = None
    route_plan: RoutePlan | None = None
    reasoning_state: Any = None
    candidates: list[CandidateSolution] = field(default_factory=list)
    candidate_pool: Any = None
    peer_reviews: list[Any] = field(default_factory=list)
    rebuttals: list[Any] = field(default_factory=list)
    critiques: list[Any] = field(default_factory=list)
    audits: list[Any] = field(default_factory=list)
    repair_lineage: list[dict[str, Any]] = field(default_factory=list)
    verification_closures: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    problem_obligations: list[ProofObligation] = field(default_factory=list)
    proof_obligations: dict[str, list[ProofObligation]] = field(default_factory=dict)
    working_memory: Any = None
    lemma_memory: Any = None
    raw_context_store: Any = None
    # Raw provider responses are retained for the complete case lifetime so
    # answer salvage can run after candidate/protocol rejection.  They are
    # internal state and must never be projected into the public trace.
    raw_model_outputs: list[str] = field(default_factory=list)
    agent_runtime: Any = None
    agent_plan: Any = None
    lemmas: list[LemmaCard] = field(default_factory=list)
    candidate_lemma_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rounds: list[RoundState] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    phase: RuntimePhase = RuntimePhase.CREATED
    phase_history: list[dict[str, str]] = field(default_factory=list)
    _frozen: bool = field(default=False, init=False, repr=False)

    def transition(
        self,
        expected: RuntimePhase,
        target: RuntimePhase,
        *,
        reason: str,
    ) -> dict[str, str]:
        if self._frozen:
            raise RuntimeError("math session is frozen")
        if self.phase != expected:
            raise InvalidRuntimeTransition(
                f"expected phase {expected.value}, current phase is {self.phase.value}"
            )
        if not transition_allowed(expected, target):
            raise InvalidRuntimeTransition(
                f"transition {expected.value}->{target.value} is not allowed"
            )
        record = {
            "from_phase": expected.value,
            "to_phase": target.value,
            "reason": str(reason),
        }
        self.phase = target
        self.phase_history.append(record)
        return dict(record)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "problem": self.problem,
            "metadata": dict(self.metadata),
            "budget": self.budget.to_dict(),
            "problem_ir": self.problem_ir.to_dict() if self.problem_ir else None,
            "route_plan": self.route_plan.to_dict() if self.route_plan else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "candidate_pool": (
                self.candidate_pool.snapshot()
                if self.candidate_pool is not None
                else []
            ),
            "peer_reviews": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.peer_reviews
            ],
            "rebuttals": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.rebuttals
            ],
            "critiques": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.critiques
            ],
            "audits": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.audits
            ],
            "repair_lineage": [dict(item) for item in self.repair_lineage],
            "verification_closures": {
                candidate_id: (
                    item.to_dict()
                    if hasattr(item, "to_dict")
                    else dict(item)
                )
                for candidate_id, item in self.verification_closures.items()
            },
            "evidence": [record.to_dict() for record in self.evidence],
            "problem_obligations": [
                obligation.to_dict()
                for obligation in self.problem_obligations
            ],
            "proof_obligations": {
                candidate_id: [obligation.to_dict() for obligation in obligations]
                for candidate_id, obligations in self.proof_obligations.items()
            },
            "working_memory": (
                self.working_memory.to_dict()
                if self.working_memory is not None and hasattr(self.working_memory, "to_dict")
                else None
            ),
            "raw_model_outputs": list(self.raw_model_outputs),
            "lemma_memory": (
                self.lemma_memory.to_dict()
                if self.lemma_memory is not None and hasattr(self.lemma_memory, "to_dict")
                else None
            ),
            "lemmas": [lemma.to_dict() for lemma in self.lemmas],
            "candidate_lemma_ids": {
                candidate_id: list(lemma_ids)
                for candidate_id, lemma_ids in self.candidate_lemma_ids.items()
            },
            "rounds": [round_state.to_dict() for round_state in self.rounds],
            "trace_events": [dict(event) for event in self.trace_events],
            "phase": self.phase.value,
            "phase_history": [dict(item) for item in self.phase_history],
        }
