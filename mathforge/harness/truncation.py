"""Deterministic long-horizon recovery services.

The services in this module are Host-owned.  They deliberately operate on
public protocol fields and bounded state summaries; no private model trace is
stored, reconstructed, or sent back to a Solver.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from mathforge.parsing.answer_extraction import extract_boxed, prepare_model_text


class TruncationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PROBABLE_TRUNCATION = "PROBABLE_TRUNCATION"
    DEFINITE_TRUNCATION = "DEFINITE_TRUNCATION"
    STRUCTURAL_DAMAGE = "STRUCTURAL_DAMAGE"


_TRUNCATION_STATUSES = frozenset(item.value for item in TruncationStatus)
_LENGTH_FINISH_REASONS = frozenset({"length", "length_inferred", "max_tokens", "token_limit"})
_PROTOCOL_SUFFIXES = ("</json>", "</result>", "</agent_turn>", "<|end|>", "<|eot_id|>")


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _response_attr(response: Any, *names: str) -> Any:
    for name in names:
        if isinstance(response, Mapping) and name in response:
            return response[name]
        value = getattr(response, name, None)
        if value is not None:
            return value
    return None


def _object_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _json_balance(text: str) -> str:
    """Return ``balanced``, ``unbalanced`` or ``not_json`` deterministically."""

    cleaned = text.strip()
    if not cleaned:
        return "not_json"
    try:
        value = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        value = None
    if isinstance(value, (dict, list)):
        return "balanced"
    # A response can contain a protocol envelope around the JSON object.  The
    # scanner intentionally ignores braces inside quoted strings.
    stack: list[str] = []
    in_string = False
    escaped = False
    saw_container = False
    for character in cleaned:
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
            saw_container = True
        elif character in "]}":
            if not stack or (character == "]" and stack[-1] != "[") or (
                character == "}" and stack[-1] != "{"
            ):
                return "unbalanced"
            stack.pop()
    if in_string or stack:
        return "unbalanced"
    return "balanced" if saw_container else "not_json"


def _field_presence(text: str, required: Sequence[str]) -> tuple[str, ...]:
    if not required:
        return ()
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict):
        return tuple(sorted(item for item in required if item not in value))
    return tuple(
        sorted(
            item
            for item in required
            if re.search(rf'"{re.escape(item)}"\s*:', text) is None
        )
    )


def _infer_observed_tokens(response: Any) -> int | None:
    value = _response_attr(
        response,
        "observed_tokens",
        "output_tokens",
        "completion_tokens",
    )
    if value is not None:
        return _as_int(value)
    usage = _response_attr(response, "usage")
    if isinstance(usage, Mapping):
        return _as_int(
            usage.get("completion_tokens", usage.get("output_tokens"))
        )
    return None


@dataclass(frozen=True)
class TruncationAssessment:
    """Evidence-backed classification of one model response."""

    status: str
    native_finish_reason: str = ""
    observed_tokens: int | None = None
    max_tokens: int | None = None
    json_balance: str = "not_json"
    required_fields: tuple[str, ...] = ()
    missing_required_fields: tuple[str, ...] = ()
    think_tag: str = "absent"
    boxed_answer: bool = False
    protocol_suffix: bool = True
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _TRUNCATION_STATUSES:
            raise ValueError("invalid truncation status")
        if self.json_balance not in {"balanced", "unbalanced", "not_json"}:
            raise ValueError("invalid JSON balance")
        if self.think_tag not in {"absent", "complete", "unclosed"}:
            raise ValueError("invalid think tag status")
        if not isinstance(self.protocol_suffix, bool) or not isinstance(
            self.boxed_answer, bool
        ):
            raise ValueError("invalid truncation evidence flag")
        if self.observed_tokens is not None and self.observed_tokens < 0:
            raise ValueError("observed token count cannot be negative")
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ValueError("maximum token count cannot be negative")

    @property
    def is_truncated(self) -> bool:
        return self.status in {
            TruncationStatus.PROBABLE_TRUNCATION.value,
            TruncationStatus.DEFINITE_TRUNCATION.value,
            TruncationStatus.STRUCTURAL_DAMAGE.value,
        }

    @property
    def definitely_truncated(self) -> bool:
        return self.status == TruncationStatus.DEFINITE_TRUNCATION.value

    @property
    def json_balanced(self) -> bool:
        return self.json_balance == "balanced"

    @property
    def required_fields_complete(self) -> bool:
        return not self.missing_required_fields

    @property
    def think_tag_truncated(self) -> bool:
        return self.think_tag == "unclosed"

    @property
    def protocol_suffix_present(self) -> bool:
        return self.protocol_suffix

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "native_finish_reason": self.native_finish_reason,
            "observed_tokens": self.observed_tokens,
            "max_tokens": self.max_tokens,
            "json_balance": self.json_balance,
            "required_fields": list(self.required_fields),
            "missing_required_fields": list(self.missing_required_fields),
            "think_tag": self.think_tag,
            "boxed_answer": self.boxed_answer,
            "protocol_suffix": self.protocol_suffix,
            "reasons": list(self.reasons),
            "is_truncated": self.is_truncated,
        }

    @classmethod
    def assess(
        cls,
        response: Any,
        *,
        native_finish_reason: str | None = None,
        finish_reason: str | None = None,
        observed_tokens: int | None = None,
        max_tokens: int | None = None,
        required_fields: Iterable[str] = (),
        protocol_suffix: str | bool | None = None,
        protocol_suffix_present: bool | None = None,
        boxed_answer: bool | None = None,
        think_tag: str | bool | None = None,
    ) -> "TruncationAssessment":
        """Assess native metadata and public structural signals.

        A complete payload with a provider ``length`` marker is *probable*,
        rather than automatically unusable: existing callers may still gate it
        through Candidate verification.  An unbalanced or missing-required
        payload is definite when a length signal is present.
        """

        text = str(response or "")
        native = str(
            native_finish_reason
            if native_finish_reason is not None
            else finish_reason
            if finish_reason is not None
            else _response_attr(response, "finish_reason", "native_finish_reason")
            or ""
        ).strip().casefold()
        observed = (
            _as_int(observed_tokens)
            if observed_tokens is not None
            else _infer_observed_tokens(response)
        )
        maximum = (
            _as_int(max_tokens)
            if max_tokens is not None
            else _as_int(
                _response_attr(response, "max_tokens", "maximum_tokens")
            )
        )
        budget_signal = bool(
            _response_attr(response, "output_budget_exceeded", "budget_exceeded")
        )
        length_signal = native in _LENGTH_FINISH_REASONS or budget_signal or (
            observed is not None and maximum is not None and maximum > 0 and observed >= maximum
        )
        view = prepare_model_text(text)
        if think_tag is None:
            think_state = "unclosed" if view.think_truncated else (
                "complete" if re.search(r"</?think>", text, re.I) else "absent"
            )
        elif isinstance(think_tag, bool):
            think_state = "complete" if think_tag else "absent"
        else:
            think_state = str(think_tag).strip().casefold()
            if think_state in {"open", "truncated", "unfinished"}:
                think_state = "unclosed"
            elif think_state in {"closed", "present", "true"}:
                think_state = "complete"
            elif think_state in {"false", "none", "missing"}:
                think_state = "absent"
            if think_state not in {"absent", "complete", "unclosed"}:
                raise ValueError("invalid think tag status")
        balance = _json_balance(view.public_text or text)
        required = tuple(sorted(dict.fromkeys(str(item) for item in required_fields)))
        missing = _field_presence(view.public_text or text, required)
        if boxed_answer is None:
            boxed = bool(extract_boxed(view.salvage_text or text))
        else:
            boxed = bool(boxed_answer)
        if protocol_suffix_present is not None:
            suffix = bool(protocol_suffix_present)
        elif protocol_suffix is None:
            # The current protocol has no mandatory textual terminator.  If a
            # known terminator is present it is evidence; otherwise this signal
            # remains neutral instead of manufacturing a failure.
            suffix = True
        elif isinstance(protocol_suffix, bool):
            suffix = protocol_suffix
        else:
            suffix_text = str(protocol_suffix).strip()
            suffix = not suffix_text or text.rstrip().endswith(suffix_text)
        reasons: list[str] = []
        if native in _LENGTH_FINISH_REASONS:
            reasons.append(f"native_finish_reason:{native}")
        if budget_signal:
            reasons.append("output_budget_exceeded")
        if observed is not None and maximum is not None and maximum > 0 and observed >= maximum:
            reasons.append("observed_tokens_reached_max_tokens")
        if balance == "unbalanced":
            reasons.append("json_unbalanced")
        if missing:
            reasons.append("missing_required_fields:" + ",".join(missing))
        if think_state == "unclosed":
            reasons.append("think_tag_unclosed")
        if not suffix:
            reasons.append("protocol_suffix_missing")
        if not text.strip():
            reasons.append("empty_response")

        damage = (
            balance == "unbalanced"
            or bool(missing)
            or think_state == "unclosed"
            or not suffix
            or not text.strip()
        )
        if damage and length_signal:
            status = TruncationStatus.DEFINITE_TRUNCATION.value
        elif damage:
            status = TruncationStatus.STRUCTURAL_DAMAGE.value
        elif length_signal:
            status = TruncationStatus.PROBABLE_TRUNCATION.value
        else:
            status = TruncationStatus.COMPLETE.value
        return cls(
            status=status,
            native_finish_reason=native,
            observed_tokens=observed,
            max_tokens=maximum,
            json_balance=balance,
            required_fields=required,
            missing_required_fields=missing,
            think_tag=think_state,
            boxed_answer=boxed,
            protocol_suffix=suffix,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @classmethod
    def from_response(cls, response: Any, **kwargs: Any) -> "TruncationAssessment":
        return cls.assess(response, **kwargs)

    @classmethod
    def evaluate(cls, response: Any, **kwargs: Any) -> "TruncationAssessment":
        return cls.assess(response, **kwargs)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TruncationAssessment":
        if not isinstance(payload, Mapping):
            raise ValueError("TruncationAssessment payload must be an object")
        required = {
            "status",
            "native_finish_reason",
            "observed_tokens",
            "max_tokens",
            "json_balance",
            "required_fields",
            "missing_required_fields",
            "think_tag",
            "boxed_answer",
            "protocol_suffix",
            "reasons",
            "is_truncated",
        }
        if set(payload) != required:
            raise ValueError("TruncationAssessment fields do not match the public schema")
        for name in ("required_fields", "missing_required_fields", "reasons"):
            value = payload[name]
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(f"TruncationAssessment {name} must be a string list")
        if not isinstance(payload["boxed_answer"], bool) or not isinstance(
            payload["protocol_suffix"], bool
        ):
            raise ValueError("TruncationAssessment flags must be booleans")
        if not isinstance(payload["is_truncated"], bool):
            raise ValueError("TruncationAssessment is_truncated must be a boolean")
        assessment = cls(
            status=str(payload["status"]),
            native_finish_reason=str(payload["native_finish_reason"]),
            observed_tokens=payload["observed_tokens"],
            max_tokens=payload["max_tokens"],
            json_balance=str(payload["json_balance"]),
            required_fields=tuple(payload["required_fields"]),
            missing_required_fields=tuple(payload["missing_required_fields"]),
            think_tag=str(payload["think_tag"]),
            boxed_answer=payload["boxed_answer"],
            protocol_suffix=payload["protocol_suffix"],
            reasons=tuple(payload["reasons"]),
        )
        if assessment.is_truncated != payload["is_truncated"]:
            raise ValueError("TruncationAssessment is_truncated is inconsistent")
        return assessment

    classify = assess


# The short alias is useful to integrations that refer to this service as a
# classifier/evaluator while keeping the public phase name available.
TruncationClassifier = TruncationAssessment
TruncationEvaluator = TruncationAssessment


def assess_truncation(response: Any, **kwargs: Any) -> TruncationAssessment:
    return TruncationAssessment.assess(response, **kwargs)


@dataclass(frozen=True)
class CheckpointCursor:
    """A public recovery boundary after one successful Progress commit."""

    checkpoint_id: str
    state_version: int
    plan_version: int
    branch_id: str
    open_subgoals: tuple[str, ...] = ()
    open_obligations: tuple[str, ...] = ()
    critical_claim_ids: tuple[str, ...] = ()
    next_step: str = ""

    def __post_init__(self) -> None:
        if not str(self.checkpoint_id).strip() or not str(self.branch_id).strip():
            raise ValueError("checkpoint and branch IDs are required")
        if type(self.state_version) is not int or self.state_version < 1:
            raise ValueError("checkpoint state_version is invalid")
        if type(self.plan_version) is not int or self.plan_version < 0:
            raise ValueError("checkpoint plan_version is invalid")
        for name in ("open_subgoals", "open_obligations", "critical_claim_ids"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"checkpoint {name} must be a string tuple")
        if not isinstance(self.next_step, str):
            raise ValueError("checkpoint next_step must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "state_version": self.state_version,
            "plan_version": self.plan_version,
            "branch_id": self.branch_id,
            "open_subgoals": list(self.open_subgoals),
            "open_obligations": list(self.open_obligations),
            "critical_claim_ids": list(self.critical_claim_ids),
            "next_step": self.next_step,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CheckpointCursor":
        expected = {
            "checkpoint_id", "state_version", "plan_version", "branch_id",
            "open_subgoals", "open_obligations", "critical_claim_ids", "next_step",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("CheckpointCursor fields do not match the public schema")
        lists: dict[str, tuple[str, ...]] = {}
        for name in ("open_subgoals", "open_obligations", "critical_claim_ids"):
            raw = payload[name]
            if not isinstance(raw, (list, tuple)):
                raise ValueError(f"checkpoint {name} must be a list")
            if any(not isinstance(item, str) or not item.strip() for item in raw):
                raise ValueError(f"checkpoint {name} must contain non-empty strings")
            lists[name] = tuple(dict.fromkeys(item.strip() for item in raw))
        return cls(
            checkpoint_id=str(payload["checkpoint_id"]),
            state_version=int(payload["state_version"]),
            plan_version=int(payload["plan_version"]),
            branch_id=str(payload["branch_id"]),
            **lists,
            next_step=str(payload["next_step"]),
        )

    @classmethod
    def from_state(
        cls,
        state: Any,
        *,
        plan_version: int = 0,
        next_step: str | None = None,
        checkpoint_id: str | None = None,
    ) -> "CheckpointCursor":
        subgoals = tuple(
            item.subgoal_id
            for item in getattr(state, "subgoal_ledger").items
            if getattr(item, "status", "open") in {"open", "active", "blocked"}
        )
        obligations = tuple(item.obligation_id for item in getattr(state, "open_obligations"))
        claims = tuple(
            item.claim_id
            for item in getattr(state, "claim_ledger").items
            if getattr(item, "importance", "supporting") == "critical"
            and getattr(item, "status", "pending") not in {"rejected", "superseded", "archived"}
        )
        step = str(next_step if next_step is not None else (getattr(state, "rounds")[-1].next_step if getattr(state, "rounds", ()) else ""))
        identity = json.dumps(
            {
                "state_id": str(getattr(state, "state_id", "")),
                "state_version": int(getattr(state, "version", 1)),
                "plan_version": int(plan_version),
                "branch_id": str(getattr(state, "branch_id", "")),
                "open_subgoals": subgoals,
                "open_obligations": obligations,
                "critical_claim_ids": claims,
                "next_step": step,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return cls(
            checkpoint_id=checkpoint_id or f"cp-{digest}",
            state_version=int(getattr(state, "version", 1)),
            plan_version=int(plan_version),
            branch_id=str(getattr(state, "branch_id", "branch-main")),
            open_subgoals=subgoals,
            open_obligations=obligations,
            critical_claim_ids=claims,
            next_step=step,
        )

    @property
    def version(self) -> int:
        return self.state_version


@dataclass
class CheckpointStore:
    """Bounded, per-problem checkpoint state; never a cross-problem memory."""

    max_checkpoints: int = 2
    _items: list[tuple[CheckpointCursor, Any]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.max_checkpoints) is not int or self.max_checkpoints < 1:
            raise ValueError("max_checkpoints must be positive")

    def commit(
        self,
        state: Any,
        *,
        plan_version: int = 0,
        next_step: str | None = None,
    ) -> CheckpointCursor:
        cursor = CheckpointCursor.from_state(
            state,
            plan_version=plan_version,
            next_step=next_step,
        )
        # State objects in this project are immutable, but round-trip through
        # their public dictionary when possible to prevent accidental mutation
        # by a caller retaining a mutable nested object.
        snapshot = type(state).from_dict(state.to_dict()) if hasattr(type(state), "from_dict") else state
        self._items.append((cursor, snapshot))
        self._items = self._items[-self.max_checkpoints :]
        return cursor

    @property
    def latest(self) -> tuple[CheckpointCursor, Any] | None:
        return self._items[-1] if self._items else None

    def reload(self, cursor: CheckpointCursor | None = None) -> Any:
        if not self._items:
            return None
        selected = self._items[-1]
        if cursor is not None:
            for item in reversed(self._items):
                if item[0].checkpoint_id == cursor.checkpoint_id:
                    selected = item
                    break
            else:
                raise KeyError(cursor.checkpoint_id)
        state = selected[1]
        return type(state).from_dict(state.to_dict()) if hasattr(type(state), "from_dict") else state

    def discard_uncommitted(self, cursor: CheckpointCursor | None = None) -> Any:
        return self.reload(cursor)

    def cursors(self) -> tuple[CheckpointCursor, ...]:
        return tuple(item[0] for item in self._items)


@dataclass(frozen=True)
class VerifiedFact:
    fact_id: str
    statement: str
    source_claim_id: str
    dependencies: tuple[str, ...] = ()
    evidence_strength: str = "hard"
    first_version: int = 1
    last_used_version: int = 1
    pinned: bool = False

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or not self.statement.strip() or not self.source_claim_id.strip():
            raise ValueError("VerifiedFact identity, statement and source claim are required")
        if self.evidence_strength not in {"none", "soft", "medium", "hard"}:
            raise ValueError("invalid VerifiedFact evidence strength")
        if type(self.first_version) is not int or self.first_version < 1:
            raise ValueError("invalid VerifiedFact first_version")
        if type(self.last_used_version) is not int or self.last_used_version < self.first_version:
            raise ValueError("invalid VerifiedFact last_used_version")
        if not isinstance(self.dependencies, tuple) or any(not isinstance(item, str) or not item.strip() for item in self.dependencies):
            raise ValueError("VerifiedFact dependencies must be a string tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "statement": self.statement,
            "source_claim_id": self.source_claim_id,
            "dependencies": list(self.dependencies),
            "evidence_strength": self.evidence_strength,
            "first_version": self.first_version,
            "last_used_version": self.last_used_version,
            "pinned": self.pinned,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VerifiedFact":
        if not isinstance(payload, Mapping):
            raise ValueError("VerifiedFact payload must be an object")
        expected = {"fact_id", "statement", "source_claim_id", "dependencies", "evidence_strength", "first_version", "last_used_version", "pinned"}
        if set(payload) != expected:
            raise ValueError("VerifiedFact fields do not match the public schema")
        dependencies = payload["dependencies"]
        if not isinstance(dependencies, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip()
            for item in dependencies
        ):
            raise ValueError("VerifiedFact dependencies must be a string list")
        for name in ("first_version", "last_used_version"):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"VerifiedFact {name} must be an integer")
        if not isinstance(payload["pinned"], bool):
            raise ValueError("VerifiedFact pinned must be a boolean")
        return cls(
            fact_id=str(payload["fact_id"]),
            statement=str(payload["statement"]),
            source_claim_id=str(payload["source_claim_id"]),
            dependencies=tuple(dict.fromkeys(item.strip() for item in dependencies)),
            evidence_strength=str(payload["evidence_strength"]),
            first_version=payload["first_version"],
            last_used_version=payload["last_used_version"],
            pinned=payload["pinned"],
        )


class VerifiedFactBank:
    """Host-owned facts promoted only by deterministic evidence gates."""

    def __init__(self, facts: Iterable[VerifiedFact] = ()) -> None:
        self._facts: dict[str, VerifiedFact] = {}
        for fact in facts:
            self.add(fact)

    def add(self, fact: VerifiedFact) -> VerifiedFact:
        if not isinstance(fact, VerifiedFact):
            raise TypeError("VerifiedFactBank accepts VerifiedFact objects")
        prior = self._facts.get(fact.fact_id)
        if prior is not None:
            if prior.statement != fact.statement or prior.source_claim_id != fact.source_claim_id:
                raise ValueError("VerifiedFact identity cannot be rewritten")
            strength = max(("none", "soft", "medium", "hard").index(item) for item in (prior.evidence_strength, fact.evidence_strength))
            fact = replace(
                fact,
                evidence_strength=("none", "soft", "medium", "hard")[strength],
                first_version=min(prior.first_version, fact.first_version),
                last_used_version=max(prior.last_used_version, fact.last_used_version),
                dependencies=tuple(dict.fromkeys((*prior.dependencies, *fact.dependencies))),
                pinned=prior.pinned or fact.pinned,
            )
        self._facts[fact.fact_id] = fact
        return fact

    def record(
        self,
        *,
        fact_id: str,
        statement: str,
        source_claim_id: str,
        dependencies: Iterable[str] = (),
        evidence_strength: str = "hard",
        version: int = 1,
        pinned: bool = False,
    ) -> VerifiedFact:
        return self.add(VerifiedFact(
            fact_id=fact_id,
            statement=statement,
            source_claim_id=source_claim_id,
            dependencies=tuple(dict.fromkeys(str(item) for item in dependencies)),
            evidence_strength=evidence_strength,
            first_version=version,
            last_used_version=version,
            pinned=pinned,
        ))

    def record_claim(self, claim: Any, *, version: int, evidence_strength: str = "hard", pinned: bool = False) -> VerifiedFact:
        evidence_refs = tuple(_object_attr(claim, "evidence_refs", ()))
        claim_id = str(_object_attr(claim, "claim_id", "claim"))
        fact_id = evidence_refs[0] if evidence_refs else f"fact-{claim_id}"
        return self.record(
            fact_id=fact_id,
            statement=str(_object_attr(claim, "statement", "")),
            source_claim_id=claim_id,
            dependencies=_object_attr(claim, "depends_on", ()),
            evidence_strength=evidence_strength,
            version=version,
            pinned=pinned,
        )

    def use(self, fact_id: str, *, version: int) -> VerifiedFact:
        fact = self._facts[fact_id]
        if type(version) is not int or version < fact.first_version:
            raise ValueError("fact use version is invalid")
        fact = replace(fact, last_used_version=max(fact.last_used_version, version))
        self._facts[fact_id] = fact
        return fact

    def pin(self, fact_id: str) -> VerifiedFact:
        fact = self._facts[fact_id]
        fact = replace(fact, pinned=True)
        self._facts[fact_id] = fact
        return fact

    def get(self, fact_id: str) -> VerifiedFact | None:
        return self._facts.get(fact_id)

    def values(self) -> tuple[VerifiedFact, ...]:
        return tuple(self._facts[key] for key in sorted(self._facts))

    @property
    def facts(self) -> tuple[VerifiedFact, ...]:
        """Read-only public view used by prompt/report integrations."""

        return self.values()

    def add_fact(self, fact: VerifiedFact) -> VerifiedFact:
        return self.add(fact)

    def promote(self, fact: VerifiedFact) -> VerifiedFact:
        return self.add(fact)

    def get_facts(self) -> tuple[VerifiedFact, ...]:
        return self.values()

    def for_claims(self, claim_ids: Iterable[str], *, version: int | None = None) -> tuple[VerifiedFact, ...]:
        selected = tuple(fact for fact in self.values() if fact.source_claim_id in set(claim_ids) or set(fact.dependencies).intersection(claim_ids))
        if version is not None:
            for fact in selected:
                self.use(fact.fact_id, version=version)
        return selected

    def semantic_gc(self, *, active_claim_ids: Iterable[str], current_version: int, max_age: int = 2) -> tuple[VerifiedFact, ...]:
        active = set(active_claim_ids)
        retained: dict[str, VerifiedFact] = {}
        for fact in self.values():
            recent = current_version - fact.last_used_version <= max(0, max_age)
            if fact.pinned or fact.source_claim_id in active or set(fact.dependencies).intersection(active) or recent:
                retained[fact.fact_id] = fact
        self._facts = retained
        return self.values()

    def to_dict(self) -> dict[str, Any]:
        return {"facts": [fact.to_dict() for fact in self.values()]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VerifiedFactBank":
        if not isinstance(payload, Mapping) or set(payload) != {"facts"}:
            raise ValueError("VerifiedFactBank payload is invalid")
        return cls(VerifiedFact.from_dict(item) for item in payload["facts"])

    def to_prompt_json(self, *, claim_ids: Iterable[str] = ()) -> str:
        selected_claim_ids = tuple(claim_ids)
        facts = self.for_claims(selected_claim_ids) if selected_claim_ids else self.values()
        return json.dumps(
            {"verified_facts": [{"fact_id": item.fact_id, "statement": item.statement, "source_claim_id": item.source_claim_id, "dependencies": list(item.dependencies), "evidence_strength": item.evidence_strength} for item in facts]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _necessary_support_closure(
    claims_by_id: Mapping[str, Any],
    roots: Iterable[str],
) -> set[str]:
    """Return only the public claims needed by the terminal frontier."""

    retained: set[str] = set()
    pending = [str(item) for item in roots if str(item) in claims_by_id]
    while pending:
        claim_id = pending.pop()
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        for dependency in _object_attr(claim, "depends_on", ()):
            dependency_id = str(dependency)
            if dependency_id in claims_by_id and dependency_id not in retained:
                retained.add(dependency_id)
                pending.append(dependency_id)
    return retained


@dataclass(frozen=True)
class ProofBackbone:
    """Minimal terminal-to-evidence proof skeleton used during compression."""

    terminal_conclusion: str = ""
    terminal_claim_id: str = ""
    critical_claim_ids: tuple[str, ...] = ()
    necessary_support_claim_ids: tuple[str, ...] = ()
    hard_evidence_ids: tuple[str, ...] = ()
    verified_theorem_conditions: tuple[str, ...] = ()
    claim_dependencies: tuple[tuple[str, tuple[str, ...]], ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise ValueError("ProofBackbone version is invalid")
        for name in ("critical_claim_ids", "necessary_support_claim_ids", "hard_evidence_ids", "verified_theorem_conditions"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"ProofBackbone {name} must be a string tuple")
        if not isinstance(self.terminal_conclusion, str) or not isinstance(self.terminal_claim_id, str):
            raise ValueError("ProofBackbone terminal fields are invalid")

    @property
    def support_claim_ids(self) -> tuple[str, ...]:
        return self.necessary_support_claim_ids

    @property
    def critical_claims(self) -> tuple[str, ...]:
        return self.critical_claim_ids

    @property
    def necessary_support_claims(self) -> tuple[str, ...]:
        return self.necessary_support_claim_ids

    @property
    def hard_evidence(self) -> tuple[str, ...]:
        return self.hard_evidence_ids

    @property
    def theorem_conditions(self) -> tuple[str, ...]:
        return self.verified_theorem_conditions

    @classmethod
    def from_state(cls, state: Any, *, verified_facts: Iterable[VerifiedFact] = ()) -> "ProofBackbone":
        claims = tuple(getattr(getattr(state, "claim_ledger"), "items", ()))
        active = tuple(item for item in claims if getattr(item, "status", "") not in {"rejected", "superseded", "archived"})
        critical = tuple(item.claim_id for item in active if getattr(item, "importance", "supporting") == "critical")
        terminal = next((item for item in reversed(active) if getattr(item, "importance", "supporting") == "critical"), None)
        terminal = terminal or (active[-1] if active else None)
        terminal_id = terminal.claim_id if terminal is not None else ""
        terminal_text = terminal.statement if terminal is not None else ""
        by_id = {item.claim_id: item for item in active}
        support = tuple(
            item.claim_id
            for item in active
            if item.claim_id
            in _necessary_support_closure(
                by_id,
                critical or ((terminal_id,) if terminal_id else ()),
            )
            and item.claim_id not in set(critical)
        )
        dependencies = tuple((item.claim_id, tuple(item.depends_on)) for item in active if item.depends_on)
        facts = tuple(verified_facts)
        evidence = tuple(dict.fromkeys(ref for item in active for ref in getattr(item, "evidence_refs", ()) if any(fact.fact_id == ref and fact.evidence_strength == "hard" for fact in facts)))
        conditions = tuple(fact.statement for fact in facts if fact.source_claim_id in set(critical) and fact.evidence_strength == "hard")
        return cls(
            terminal_conclusion=terminal_text,
            terminal_claim_id=terminal_id,
            critical_claim_ids=critical,
            necessary_support_claim_ids=support,
            hard_evidence_ids=evidence,
            verified_theorem_conditions=conditions,
            claim_dependencies=dependencies,
            version=int(getattr(state, "version", 1)),
        )

    @classmethod
    def from_candidate(cls, candidate: Any) -> "ProofBackbone":
        claims = tuple(getattr(candidate, "claims", ()))
        critical = tuple(item.claim_id for item in claims if getattr(item, "importance", "supporting") == "critical")
        terminal = next((item for item in reversed(claims) if getattr(item, "importance", "supporting") == "critical"), None)
        terminal = terminal or (claims[-1] if claims else None)
        by_id = {item.claim_id: item for item in claims}
        terminal_id = terminal.claim_id if terminal is not None else ""
        support = tuple(
            item.claim_id
            for item in claims
            if item.claim_id
            in _necessary_support_closure(
                by_id,
                critical or ((terminal_id,) if terminal_id else ()),
            )
            and item.claim_id not in set(critical)
        )
        dependencies = tuple((item.claim_id, tuple(item.depends_on)) for item in claims if item.depends_on)
        evidence = tuple(dict.fromkeys(ref for item in claims for ref in getattr(item, "evidence_refs", ()) if ref))
        return cls(
            terminal_conclusion=str(getattr(candidate, "final_answer", "")),
            terminal_claim_id=terminal.claim_id if terminal is not None else "",
            critical_claim_ids=critical,
            necessary_support_claim_ids=support,
            hard_evidence_ids=evidence,
            claim_dependencies=dependencies,
            version=int(getattr(candidate, "version", 1)),
        )

    def extend(self, *, critical_claim_ids: Iterable[str] = (), support_claim_ids: Iterable[str] = (), hard_evidence_ids: Iterable[str] = (), theorem_conditions: Iterable[str] = (), version: int | None = None) -> "ProofBackbone":
        return replace(
            self,
            critical_claim_ids=tuple(dict.fromkeys((*self.critical_claim_ids, *(str(item) for item in critical_claim_ids)))),
            necessary_support_claim_ids=tuple(dict.fromkeys((*self.necessary_support_claim_ids, *(str(item) for item in support_claim_ids)))),
            hard_evidence_ids=tuple(dict.fromkeys((*self.hard_evidence_ids, *(str(item) for item in hard_evidence_ids)))),
            verified_theorem_conditions=tuple(dict.fromkeys((*self.verified_theorem_conditions, *(str(item) for item in theorem_conditions)))),
            version=self.version if version is None else version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "terminal_conclusion": self.terminal_conclusion,
            "terminal_claim_id": self.terminal_claim_id,
            "critical_claim_ids": list(self.critical_claim_ids),
            "necessary_support_claim_ids": list(self.necessary_support_claim_ids),
            "hard_evidence_ids": list(self.hard_evidence_ids),
            "verified_theorem_conditions": list(self.verified_theorem_conditions),
            "claim_dependencies": {key: list(value) for key, value in self.claim_dependencies},
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofBackbone":
        expected = {"terminal_conclusion", "terminal_claim_id", "critical_claim_ids", "necessary_support_claim_ids", "hard_evidence_ids", "verified_theorem_conditions", "claim_dependencies", "version"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("ProofBackbone fields do not match the public schema")
        return cls(
            terminal_conclusion=str(payload["terminal_conclusion"]),
            terminal_claim_id=str(payload["terminal_claim_id"]),
            critical_claim_ids=tuple(dict.fromkeys(str(item) for item in payload["critical_claim_ids"])),
            necessary_support_claim_ids=tuple(dict.fromkeys(str(item) for item in payload["necessary_support_claim_ids"])),
            hard_evidence_ids=tuple(dict.fromkeys(str(item) for item in payload["hard_evidence_ids"])),
            verified_theorem_conditions=tuple(dict.fromkeys(str(item) for item in payload["verified_theorem_conditions"])),
            claim_dependencies=tuple((str(key), tuple(str(item) for item in value)) for key, value in sorted(dict(payload["claim_dependencies"]).items())),
            version=int(payload["version"]),
        )

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "terminal_conclusion": self.terminal_conclusion,
            "terminal_claim_id": self.terminal_claim_id,
            "critical_claim_ids": list(self.critical_claim_ids),
            "necessary_support_claim_ids": list(self.necessary_support_claim_ids),
            "hard_evidence_ids": list(self.hard_evidence_ids),
            "verified_theorem_conditions": list(self.verified_theorem_conditions),
            "claim_dependencies": {key: list(value) for key, value in self.claim_dependencies},
            "version": self.version,
        }

    def to_prompt_json(self) -> str:
        return json.dumps(self.to_prompt_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class DependencyInference:
    dependencies: dict[str, tuple[str, ...]]
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependencies": {key: list(value) for key, value in sorted(self.dependencies.items())},
            "sources": {key: list(value) for key, value in sorted(self.sources.items())},
        }


def _relation_ids(value: Any, names: Sequence[str]) -> tuple[str, ...]:
    """Read a bounded list of public relation IDs from an object or mapping."""

    result: list[str] = []
    for name in names:
        raw = _object_attr(value, name, ())
        if raw is None:
            continue
        if isinstance(raw, (str, bytes)):
            raw = (raw,)
        elif not isinstance(raw, Iterable):
            raw = (raw,)
        for item in raw:
            item = str(item).strip()
            if item and item not in result:
                result.append(item)
    return tuple(result)


def _relation_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        nested = value.get("items")
        if isinstance(nested, (list, tuple)):
            return tuple(nested)
        return (value,)
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


class HostInferredDependencies:
    """Derive dependency edges from all Host-visible relations."""

    @staticmethod
    def infer(
        claims: Iterable[Any] = (),
        *,
        obligations: Iterable[Any] = (),
        tool_results: Iterable[Any] = (),
        proof_backbone: ProofBackbone | None = None,
        terminal_claim_ids: Iterable[str] = (),
    ) -> DependencyInference:
        # Accept a Candidate/ReasoningState convenience object as well as the
        # canonical claim iterable.  The inference itself remains Host-owned.
        owner = claims
        if hasattr(claims, "claim_ledger"):
            claims = getattr(getattr(claims, "claim_ledger"), "items", ())
        elif not isinstance(claims, (str, bytes, Mapping)) and hasattr(claims, "claims"):
            claims = getattr(claims, "claims")
        elif isinstance(claims, Mapping):
            if "claim_ledger" in claims:
                ledger = claims["claim_ledger"]
                claims = _object_attr(ledger, "items", ledger)
            elif "claims" in claims:
                claims = claims["claims"]
        if owner is not None:
            if not obligations:
                obligations = _object_attr(owner, "open_obligations", ())
            if not tool_results:
                tool_results = _object_attr(owner, "tool_results", ())
        claim_items = _relation_items(claims)
        claim_ids = {
            str(_object_attr(item, "claim_id", ""))
            for item in claim_items
            if _object_attr(item, "claim_id", "")
        }
        edges: dict[str, set[str]] = {claim_id: set() for claim_id in claim_ids}
        sources: dict[str, set[str]] = {claim_id: set() for claim_id in claim_ids}
        for claim in claim_items:
            claim_id = str(_object_attr(claim, "claim_id", ""))
            if not claim_id:
                continue
            for dependency in _relation_ids(claim, ("depends_on",)):
                dependency = str(dependency)
                if dependency in claim_ids and dependency != claim_id:
                    edges[claim_id].add(dependency)
                    sources[claim_id].add("explicit_claim_depends_on")
        for obligation in _relation_items(obligations):
            refs = tuple(
                item
                for item in _relation_ids(
                    obligation,
                    ("source_claim_ids", "target_claim_ids", "claim_ids"),
                )
                if item in claim_ids
            )
            deps = tuple(
                item
                for item in _relation_ids(
                    obligation,
                    ("depends_on", "dependency_claim_ids", "support_claim_ids"),
                )
                if item in claim_ids
            )
            # ProofObligation uses source_claim_ids for the public relation;
            # when no separate dependency list exists, co-referenced claims
            # are the only host-visible support relation available.
            if not deps and len(refs) > 1:
                deps = refs
            for target in refs:
                for dependency in deps:
                    if dependency != target:
                        edges[target].add(dependency)
                        sources[target].add("proof_obligation_relation")
        for result in _relation_items(tool_results):
            target = str(
                _object_attr(
                    result,
                    "claim_id",
                    _object_attr(result, "target_claim_id", ""),
                )
            )
            if target in claim_ids:
                for dependency in _relation_ids(
                    result,
                    ("depends_on", "related_claim_ids", "source_claim_ids"),
                ):
                    dependency = str(dependency)
                    if dependency in claim_ids and dependency != target:
                        edges[target].add(dependency)
                        sources[target].add("tool_check_target")
        if proof_backbone is not None:
            relation = dict(proof_backbone.claim_dependencies)
            for target, dependencies in relation.items():
                if target not in claim_ids:
                    continue
                for dependency in dependencies:
                    if dependency in claim_ids and dependency != target:
                        edges[target].add(dependency)
                        sources[target].add("proof_backbone_relation")
            terminal = set(proof_backbone.critical_claim_ids) | set(terminal_claim_ids)
            support = set(proof_backbone.necessary_support_claim_ids)
            for target in terminal:
                if target not in claim_ids:
                    continue
                for dependency in support:
                    if dependency in claim_ids and dependency != target:
                        edges[target].add(dependency)
                        sources[target].add("terminal_conclusion_reference")
        return DependencyInference(
            dependencies={key: tuple(sorted(value)) for key, value in sorted(edges.items())},
            sources={key: tuple(sorted(value)) for key, value in sorted(sources.items()) if value},
        )

    from_claims = infer
    build = infer


def infer_host_dependencies(*args: Any, **kwargs: Any) -> DependencyInference:
    return HostInferredDependencies.infer(*args, **kwargs)


@dataclass(frozen=True)
class RecoveryDecision:
    admitted: bool
    provisional: bool
    winner_allowed: bool
    corroboration: str = ""
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "provisional": self.provisional,
            "winner_allowed": self.winner_allowed,
            "corroboration": self.corroboration,
            "reasons": list(self.reasons),
        }


class RecoveredAnswerGate:
    """Require corroboration before a salvaged answer enters arbitration."""

    @staticmethod
    def evaluate(
        candidate: Any,
        *,
        deterministic_tool_hard_pass: bool = False,
        independent_candidates: Iterable[Any] = (),
        compact_fresh_confirmation: bool = False,
        high_risk: bool = False,
        proof_full: bool = False,
    ) -> RecoveryDecision:
        tier = str(_object_attr(candidate, "parse_tier", ""))
        assurance = str(_object_attr(candidate, "assurance", ""))
        # A stateful rebuild still carries a public derivation and is not the
        # answer-only salvage case.  Only answer-salvaged/provisional turns
        # require this corroboration gate.
        recovered = tier in {"answer_recovered", "semantic_answer_salvage"} or assurance in {"answer_salvaged", "provisional"}
        if not recovered:
            return RecoveryDecision(True, False, True, "not_recovered", ())
        answer = " ".join(
            str(_object_attr(candidate, "final_answer", "")).split()
        ).casefold()
        independent = any(
            " ".join(str(_object_attr(item, "final_answer", "")).split()).casefold()
            == answer
            and item is not candidate
            and not bool(_object_attr(item, "degraded", False))
            for item in independent_candidates
        )
        corroboration = (
            "deterministic_tool_hard_pass" if deterministic_tool_hard_pass else
            "independent_candidate_equivalent" if independent else
            "compact_fresh_confirmation" if compact_fresh_confirmation else ""
        )
        reasons: list[str] = ["answer_salvage_is_provisional"]
        if not corroboration:
            reasons.append("recovery_corroboration_missing")
        winner_allowed = bool(corroboration) and not (high_risk or proof_full)
        if high_risk or proof_full:
            reasons.append("high_risk_or_proof_requires_non_salvaged_winner")
        return RecoveryDecision(
            admitted=bool(corroboration),
            provisional=True,
            winner_allowed=winner_allowed,
            corroboration=corroboration,
            reasons=tuple(reasons),
        )

    admit = evaluate
    check = evaluate


def is_recovered_candidate(candidate: Any) -> bool:
    return bool(RecoveredAnswerGate.evaluate(candidate).provisional)


def emergency_allowed(*, remaining_time: float, closure_threshold: float, usable_candidate: bool) -> bool:
    if closure_threshold < 0 or remaining_time < 0:
        raise ValueError("time thresholds must be non-negative")
    return remaining_time < closure_threshold and not usable_candidate


@dataclass(frozen=True)
class InformationGainScore:
    score: int
    components: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "components": dict(self.components)}


class InformationGainScorer:
    """Score semantic progress; IDs alone never count as progress."""

    WEIGHTS = {
        "new_critical_claim": 4,
        "verified_claim": 5,
        "closed_obligation": 5,
        "closed_subgoal": 5,
        "new_hard_evidence": 5,
        "counterexample": 4,
        "proof_backbone_extension": 3,
        "strategy_switch": 2,
        "semantic_repeat": -4,
    }

    @classmethod
    def score(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        previous_semantic_sha256: str = "",
        semantic_sha256: str = "",
    ) -> InformationGainScore:
        value = payload or {}
        components: dict[str, int] = {}
        def count(key: str, amount: int = 1) -> None:
            if amount:
                components[key] = components.get(key, 0) + amount * cls.WEIGHTS[key]
        claims = _collect_objects(value, {"claims", "critical_claims", "verified_claims"})
        for claim in claims:
            if str(claim.get("importance", "")).casefold() == "critical" or bool(claim.get("critical")):
                count("new_critical_claim")
            status = str(claim.get("status", claim.get("verification_state", ""))).casefold()
            if status in {"verified", "hard_verified"}:
                count("verified_claim")
        closed_obligations = _collect_ids(value, {"closed_obligation_ids", "closed_obligations", "resolved_obligation_ids"})
        closed_subgoals = _collect_ids(value, {"closed_subgoal_ids", "closed_subgoals", "resolved_subgoal_ids"})
        count("closed_obligation", len(closed_obligations))
        count("closed_subgoal", len(closed_subgoals))
        hard_evidence = _collect_hard_evidence(value)
        count("new_hard_evidence", len(hard_evidence))
        counterexamples = _collect_ids(value, {"counterexample", "counterexamples", "counterexample_ids"})
        count("counterexample", len(counterexamples))
        backbone = _collect_ids(value, {"proof_backbone_extension", "backbone_claim_ids", "backbone_evidence_ids"})
        count("proof_backbone_extension", len(backbone))
        if _contains_strategy_switch(value):
            count("strategy_switch")
        if previous_semantic_sha256 and semantic_sha256 and previous_semantic_sha256 == semantic_sha256:
            count("semantic_repeat")
        return InformationGainScore(sum(components.values()), components)

    calculate = score
    evaluate = score


def _collect_objects(value: Any, keys: set[str]) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in keys and isinstance(nested, list):
                found.extend(item for item in nested if isinstance(item, Mapping))
            found.extend(_collect_objects(nested, keys))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_collect_objects(nested, keys))
    return found


def _collect_ids(value: Any, keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in keys:
                if isinstance(nested, list):
                    found.update(str(item).strip() for item in nested if str(item).strip())
                elif isinstance(nested, (str, int)) and str(nested).strip():
                    found.add(str(nested).strip())
            found.update(_collect_ids(nested, keys))
    elif isinstance(value, list):
        for nested in value:
            found.update(_collect_ids(nested, keys))
    return found


def _collect_hard_evidence(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        strength = str(value.get("strength", value.get("evidence_strength", ""))).casefold()
        if strength == "hard":
            for key in ("evidence_id", "id", "work_item_id"):
                if value.get(key):
                    found.add(str(value[key]))
        for nested in value.values():
            found.update(_collect_hard_evidence(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_collect_hard_evidence(nested))
    return found


def _contains_strategy_switch(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in {"strategy_switch", "strategy_changed", "switch_strategy"} and bool(nested):
                return True
            if _contains_strategy_switch(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_strategy_switch(item) for item in value)
    return False


def resume_prompt_context(cursor: CheckpointCursor, state: Any = None, *, verified_facts: Iterable[VerifiedFact] = (), proof_backbone: ProofBackbone | None = None) -> str:
    """Render a bounded public resume block for the next Solver input."""

    payload: dict[str, Any] = {
        "checkpoint_id": cursor.checkpoint_id,
        "checkpoint_version": cursor.state_version,
        "plan_version": cursor.plan_version,
        "branch_id": cursor.branch_id,
        "open_subgoals": list(cursor.open_subgoals),
        "open_obligations": list(cursor.open_obligations),
        "critical_claim_ids": list(cursor.critical_claim_ids),
        "next_step": cursor.next_step,
    }
    facts = tuple(verified_facts)
    if facts:
        payload["prior_critical_facts"] = [
            {"fact_id": item.fact_id, "statement": item.statement, "source_claim_id": item.source_claim_id}
            for item in facts
        ]
    # A checkpoint may precede deterministic evidence promotion. Preserve the
    # public critical-claim statements separately so the next turn sees the
    # prior mathematical frontier without treating unverified claims as
    # verified facts.
    if state is not None and hasattr(state, "claim_ledger"):
        critical_claims = [
            item
            for item in getattr(state.claim_ledger, "items", ())
            if getattr(item, "importance", "supporting") == "critical"
            and getattr(item, "status", "") not in {"rejected", "superseded", "archived"}
        ]
        if critical_claims:
            payload["prior_critical_claims"] = [
                {
                    "claim_id": str(item.claim_id),
                    "statement": str(item.statement),
                    "depends_on": list(getattr(item, "depends_on", ())),
                }
                for item in critical_claims
            ]
    if proof_backbone is not None:
        payload["proof_backbone"] = proof_backbone.to_prompt_dict()
    return "\n\nPublic checkpoint resume (discard any uncommitted delta; continue the same frontier):\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _claim_to_candidate_claim(claim: Any) -> Any:
    from mathforge.harness.schemas import Claim

    status = str(getattr(claim, "status", "unverified"))
    verification = "verified" if status == "verified" else "unknown"
    return Claim(
        claim_id=str(getattr(claim, "claim_id")),
        statement=str(getattr(claim, "statement")),
        depends_on=list(getattr(claim, "depends_on", ())),
        check_type=str(getattr(claim, "check_type", "reasoning")),
        importance=str(getattr(claim, "importance", "supporting")),
        status="verified" if status == "verified" else "unverified",
        claim_kind=str(getattr(claim, "claim_kind", "reasoning")),
        verification_state=verification,
    )


def rebuild_candidate_from_state(
    state: Any,
    *,
    final_answer: str,
    candidate_id: str,
    role: str,
    method: str,
    answer_type: str,
    proof_backbone: ProofBackbone | None = None,
) -> Any | None:
    """Rebuild a degraded Candidate from public state and its proof skeleton."""

    answer = str(final_answer).strip()
    if not answer:
        return None
    from mathforge.harness.schemas import CandidateSolution, CandidateSource, MethodStep

    state_claims = tuple(getattr(state, "claim_ledger").items)
    backbone = proof_backbone or ProofBackbone.from_state(state)
    wanted = set(backbone.critical_claim_ids) | set(backbone.necessary_support_claim_ids)
    claims = tuple(item for item in state_claims if not wanted or item.claim_id in wanted)
    if not claims:
        return None
    candidate_claims = [_claim_to_candidate_claim(item) for item in claims]
    steps = [item.statement for item in claims if item.statement.strip()]
    if backbone.terminal_conclusion and backbone.terminal_conclusion not in steps:
        steps.append(backbone.terminal_conclusion)
    method_steps = [
        MethodStep(
            step_id=f"rebuild-step-{index}",
            kind="conclusion" if claim.importance == "critical" else "other",
            claim_ids=[claim.claim_id],
        )
        for index, claim in enumerate(candidate_claims, start=1)
    ]
    candidate = CandidateSolution(
        candidate_id=candidate_id,
        role=role,
        method=method,
        final_answer=answer,
        answer_type=answer_type,
        claims=candidate_claims,
        public_solution_steps=steps,
        solution_text="\n".join(steps),
        unresolved_obligations=[str(item.obligation_id) for item in getattr(state, "open_obligations", ())],
        parse_status="truncated_candidate_rebuilt",
        version=max(1, int(getattr(state, "version", 1))),
        planned_method_family=method,
        method_steps=method_steps,
        source=(
            CandidateSource.LLM_ALTERNATIVE.value
            if role == "AlternativeSolver"
            else CandidateSource.LLM_PRIMARY.value
        ),
        parse_tier="recovered",
        degraded=True,
        assurance="recovered",
    )
    candidate.contract_deviations.append("truncation_stateful_rebuild")
    candidate.validate()
    return candidate


def compact_candidate_rebuild_prompt(state: Any, proof_backbone: ProofBackbone, open_obligations: Iterable[str] = ()) -> str:
    """Create the bounded synthesis context used for a candidate recovery turn."""

    payload = {
        "reasoning_state": {
            "state_id": str(getattr(state, "state_id", "")),
            "state_version": int(getattr(state, "version", 1)),
            "problem_frame": getattr(state, "problem_frame").to_dict(),
            "critical_claim_ids": list(proof_backbone.critical_claim_ids),
            "open_obligations": list(open_obligations),
        },
        "proof_backbone": proof_backbone.to_prompt_dict(),
        "instruction": "Rebuild a complete Candidate from these public facts; do not output answer-only and do not invent missing derivation.",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "CheckpointCursor",
    "CheckpointStore",
    "DependencyInference",
    "HostInferredDependencies",
    "InformationGainScore",
    "InformationGainScorer",
    "ProofBackbone",
    "RecoveredAnswerGate",
    "RecoveryDecision",
    "TruncationAssessment",
    "TruncationClassifier",
    "TruncationEvaluator",
    "TruncationStatus",
    "VerifiedFact",
    "VerifiedFactBank",
    "assess_truncation",
    "compact_candidate_rebuild_prompt",
    "emergency_allowed",
    "infer_host_dependencies",
    "is_recovered_candidate",
    "rebuild_candidate_from_state",
    "resume_prompt_context",
]
