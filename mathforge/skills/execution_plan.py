"""Executable plans and public outcomes for mathematical Skills.

Skill markdown remains the source of method knowledge, but this module owns
the small, deterministic contract that turns a selected package into runtime
work.  It intentionally contains no model calls and no private reasoning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable


SKILL_EXECUTION_PLAN_SCHEMA_VERSION = "1.0"
SKILL_OUTCOME_SCHEMA_VERSION = "1.0"
SKILL_CHECK_TASK_SCHEMA_VERSION = "1.0"


def _text_tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value).strip()
            for value in (values or ())
            if str(value).strip()
        )
    )


def _section_items(definition: Any, name: str) -> tuple[str, ...]:
    sections = getattr(definition, "sections", {}) or {}
    value = sections.get(name, "") if isinstance(sections, dict) else ""
    if not str(value).strip():
        return ()
    # Keep each public line as one precondition/stop condition.  This gives
    # traces stable, bounded atoms without attempting to parse mathematics.
    return _text_tuple(
        line.lstrip("-•* ").strip()
        for line in str(value).splitlines()
        if line.strip()
    ) or (str(value).strip(),)


def expected_accuracy_gain(
    expected_gain: float,
    *,
    capability_available: bool = True,
    historical_precision: float = 1.0,
) -> float:
    """Return the offline, capability-adjusted accuracy gain prior.

    ``expected_gain`` is supplied by an offline benchmark or an explicit
    prior.  Capability availability is deliberately a hard multiplier: an
    unavailable capability cannot contribute positive utility.
    """

    gain = max(0.0, float(expected_gain))
    precision = min(1.0, max(0.0, float(historical_precision)))
    return gain * (1.0 if capability_available else 0.0) * precision


def skill_utility(
    expected_gain: float,
    token_cost: int,
    *,
    capability_available: bool = True,
    historical_precision: float = 1.0,
    epsilon: float = 1.0,
) -> float:
    """Compute the deterministic Skill selection utility."""

    if float(epsilon) <= 0.0:
        raise ValueError("utility epsilon must be positive")
    denominator = max(float(token_cost), float(epsilon))
    if denominator <= 0.0:
        raise ValueError("utility denominator must be positive")
    return expected_accuracy_gain(
        expected_gain,
        capability_available=capability_available,
        historical_precision=historical_precision,
    ) / denominator


@dataclass(frozen=True)
class SkillExecutionPlan:
    """Host-owned executable contract for one selected Skill."""

    skill_name: str
    skill_version: str
    role: str
    selection_score: float
    selection_reasons: tuple[str, ...]
    preconditions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    verification_hooks: tuple[str, ...]
    alternative_skills: tuple[str, ...]
    failure_signals: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    token_cost: int
    # E3 utility/admission fields are additive so callers using the plan
    # shape from the implementation document remain source compatible.
    expected_gain: float = 0.0
    capability_available: bool = True
    historical_precision: float = 1.0
    expected_accuracy_gain: float = 0.0
    utility: float = 0.0
    admission_status: str = "admitted"
    admission_reasons: tuple[str, ...] = ()
    source_skill_name: str = ""
    schema_version: str = SKILL_EXECUTION_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("skill_name", "skill_version", "role"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.schema_version != SKILL_EXECUTION_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported SkillExecutionPlan schema version")
        if self.admission_status not in {
            "admitted",
            "degraded",
            "rejected",
            "alternative",
        }:
            raise ValueError(f"invalid Skill admission status: {self.admission_status}")
        if type(self.capability_available) is not bool:
            raise ValueError("capability_available must be a boolean")
        if type(self.token_cost) is not int or self.token_cost < 0:
            raise ValueError("Skill token_cost must be a nonnegative integer")
        for name in (
            "selection_score",
            "expected_gain",
            "historical_precision",
            "expected_accuracy_gain",
            "utility",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"Skill {name} must be finite and nonnegative")
        if not 0.0 <= float(self.historical_precision) <= 1.0:
            raise ValueError("historical_precision must be in [0, 1]")
        object.__setattr__(self, "selection_reasons", _text_tuple(self.selection_reasons))
        for name in (
            "preconditions",
            "required_capabilities",
            "verification_hooks",
            "alternative_skills",
            "failure_signals",
            "stop_conditions",
            "admission_reasons",
        ):
            object.__setattr__(self, name, _text_tuple(getattr(self, name)))
        expected = expected_accuracy_gain(
            self.expected_gain,
            capability_available=self.capability_available,
            historical_precision=self.historical_precision,
        )
        denominator = max(float(self.token_cost), 1.0)
        # A zero default is allowed for compatibility with a plan assembled
        # before benchmark priors are available; non-zero values are checked
        # so a trace cannot claim a utility inconsistent with its inputs.
        if self.expected_accuracy_gain and not math.isclose(
            self.expected_accuracy_gain, expected, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError("expected_accuracy_gain is inconsistent with inputs")
        if self.utility and not math.isclose(
            self.utility, expected / denominator, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError("utility is inconsistent with inputs")
        object.__setattr__(self, "expected_accuracy_gain", expected)
        object.__setattr__(self, "utility", expected / denominator)
        if not self.source_skill_name:
            object.__setattr__(self, "source_skill_name", self.skill_name)

    @classmethod
    def from_definition(
        cls,
        definition: Any,
        *,
        role: str,
        selection_score: float = 0.0,
        selection_reasons: Iterable[str] = (),
        token_cost: int | None = None,
        expected_gain: float | None = None,
        capability_available: bool = True,
        historical_precision: float | None = None,
        admission_status: str = "admitted",
        admission_reasons: Iterable[str] = (),
        source_skill_name: str = "",
    ) -> "SkillExecutionPlan":
        body = str(getattr(definition, "body", ""))
        estimated_tokens = max(1, int(round(len(body) / 4.0)))
        cost = estimated_tokens if token_cost is None else int(token_cost)
        gain = (
            float(getattr(definition, "expected_gain"))
            if expected_gain is None and hasattr(definition, "expected_gain")
            else (0.0 if expected_gain is None else float(expected_gain))
        )
        precision = (
            float(getattr(definition, "historical_precision"))
            if historical_precision is None
            and hasattr(definition, "historical_precision")
            else (1.0 if historical_precision is None else float(historical_precision))
        )
        return cls(
            skill_name=str(getattr(definition, "name", "")),
            skill_version=str(getattr(definition, "version", "")),
            role=str(role),
            selection_score=float(selection_score),
            selection_reasons=_text_tuple(selection_reasons),
            preconditions=_section_items(definition, "exact preconditions"),
            required_capabilities=_text_tuple(getattr(definition, "requires", ())),
            verification_hooks=_text_tuple(
                getattr(definition, "verification_hooks", ())
            ),
            alternative_skills=_text_tuple(
                getattr(definition, "alternative_skills", ())
            ),
            failure_signals=_text_tuple(
                getattr(definition, "failure_signals", ())
            ),
            stop_conditions=_section_items(
                definition, "stop / escalate conditions"
            ),
            token_cost=cost,
            expected_gain=gain,
            capability_available=bool(capability_available),
            historical_precision=precision,
            admission_status=admission_status,
            admission_reasons=_text_tuple(admission_reasons),
            source_skill_name=source_skill_name,
        )

    @property
    def admitted(self) -> bool:
        return self.admission_status in {"admitted", "alternative"}

    @property
    def status(self) -> str:
        """Compatibility alias used by admission/trace consumers."""

        return self.admission_status

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "selection_reasons",
            "preconditions",
            "required_capabilities",
            "verification_hooks",
            "alternative_skills",
            "failure_signals",
            "stop_conditions",
            "admission_reasons",
        ):
            payload[name] = list(getattr(self, name))
        payload["admitted"] = self.admitted
        return payload


@dataclass(frozen=True)
class SkillCheckTask:
    """A deterministic TaskGraph-facing verification hook."""

    task_id: str
    node_id: str
    skill_name: str
    hook: str
    tool_name: str
    dependencies: tuple[str, ...] = ()
    status: str = "pending"
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = SKILL_CHECK_TASK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.task_id or not self.node_id or not self.skill_name or not self.hook:
            raise ValueError("SkillCheckTask identity fields must be non-empty")
        if self.status not in {"pending", "running", "completed", "failed", "skipped"}:
            raise ValueError(f"invalid SkillCheckTask status: {self.status}")
        if self.schema_version != SKILL_CHECK_TASK_SCHEMA_VERSION:
            raise ValueError("unsupported SkillCheckTask schema version")
        object.__setattr__(self, "dependencies", _text_tuple(self.dependencies))
        object.__setattr__(self, "evidence_ids", _text_tuple(self.evidence_ids))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dependencies"] = list(self.dependencies)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload

    @property
    def verification_hook(self) -> str:
        return self.hook

    @property
    def tool(self) -> str:
        return self.tool_name


@dataclass(frozen=True)
class SkillOutcome:
    """Public result of a Skill hook/failure transition."""

    skill_name: str
    status: str
    signal: str = ""
    reason: str = ""
    alternative_skill: str = ""
    replan_required: bool = False
    evidence_ids: tuple[str, ...] = ()
    source_skill_name: str = ""
    schema_version: str = SKILL_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.skill_name:
            raise ValueError("SkillOutcome skill_name must be non-empty")
        if self.status not in {"passed", "failed", "degraded", "fallback", "rejected"}:
            raise ValueError(f"invalid SkillOutcome status: {self.status}")
        if self.schema_version != SKILL_OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported SkillOutcome schema version")
        object.__setattr__(self, "evidence_ids", _text_tuple(self.evidence_ids))
        if self.status == "fallback" and not self.alternative_skill:
            raise ValueError("fallback SkillOutcome requires alternative_skill")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


__all__ = [
    "SKILL_CHECK_TASK_SCHEMA_VERSION",
    "SKILL_EXECUTION_PLAN_SCHEMA_VERSION",
    "SKILL_OUTCOME_SCHEMA_VERSION",
    "SkillCheckTask",
    "SkillExecutionPlan",
    "SkillOutcome",
    "expected_accuracy_gain",
    "skill_utility",
]
