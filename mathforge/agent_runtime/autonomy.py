from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from mathforge.agent_runtime.protocol import AgentTurnPayload


@dataclass(frozen=True)
class ProgressGateDecision:
    continue_allowed: bool
    information_gain: int
    semantic_sha256: str
    stop_reason: str = ""
    obligation_delta: int = 0
    evidence_delta: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "continue_allowed": self.continue_allowed,
            "information_gain": self.information_gain,
            "semantic_sha256": self.semantic_sha256,
            "stop_reason": self.stop_reason,
            "obligation_delta": self.obligation_delta,
            "evidence_delta": self.evidence_delta,
        }


class AgentProgressTracker:
    """Detect public progress without imposing a fixed number of Agent Turns."""

    def __init__(self) -> None:
        self._seen_hashes: dict[str, set[str]] = {}
        self._seen_facts: dict[str, set[str]] = {}
        self._seen_obligations: dict[str, set[str]] = {}
        self._seen_evidence: dict[str, set[str]] = {}

    def observe(
        self,
        agent_id: str,
        payload: AgentTurnPayload,
    ) -> ProgressGateDecision:
        semantic = {
            "action": payload.action,
            "public_state_delta": payload.public_state_delta,
            "result_payload": payload.result_payload,
            "outbound_intents": list(payload.outbound_intents),
        }
        canonical = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        hashes = self._seen_hashes.setdefault(agent_id, set())
        if digest in hashes:
            return ProgressGateDecision(
                False,
                0,
                digest,
                "repeated_public_artifact_hash",
            )
        hashes.add(digest)

        facts = self._public_facts(semantic)
        seen = self._seen_facts.setdefault(agent_id, set())
        information_gain = len(facts - seen)
        seen.update(facts)
        obligations = self._semantic_ids(
            semantic,
            {
                "obligation_id",
                "obligation_ids",
                "target_obligation_ids",
                "unresolved_obligation_ids",
                "open_obligations",
            },
        )
        evidence = self._semantic_ids(
            semantic,
            {
                "evidence_id",
                "evidence_ids",
                "tool_evidence_refs",
                "verified_evidence_ids",
            },
        )
        seen_obligations = self._seen_obligations.setdefault(agent_id, set())
        seen_evidence = self._seen_evidence.setdefault(agent_id, set())
        obligation_delta = len(obligations - seen_obligations)
        evidence_delta = len(evidence - seen_evidence)
        seen_obligations.update(obligations)
        seen_evidence.update(evidence)
        information_gain += obligation_delta + evidence_delta
        if payload.action == "continue_reasoning" and information_gain <= 0:
            return ProgressGateDecision(
                False,
                0,
                digest,
                "no_public_information_gain",
                obligation_delta,
                evidence_delta,
            )
        return ProgressGateDecision(
            True,
            information_gain,
            digest,
            obligation_delta=obligation_delta,
            evidence_delta=evidence_delta,
        )

    @classmethod
    def _semantic_ids(cls, value: Any, keys: set[str]) -> set[str]:
        result: set[str] = set()
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key)
                if normalized in keys:
                    if isinstance(nested, list):
                        result.update(
                            str(item).strip()
                            for item in nested
                            if str(item).strip()
                        )
                    elif isinstance(nested, (str, int, float, bool)):
                        item = str(nested).strip()
                        if item:
                            result.add(item)
                result.update(cls._semantic_ids(nested, keys))
        elif isinstance(value, list):
            for nested in value:
                result.update(cls._semantic_ids(nested, keys))
        return result

    @classmethod
    def _public_facts(cls, value: Any, *, key: str = "") -> set[str]:
        facts: set[str] = set()
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                facts.update(cls._public_facts(nested, key=str(nested_key)))
            return facts
        if isinstance(value, list):
            for nested in value:
                facts.update(cls._public_facts(nested, key=key))
            return facts
        if isinstance(value, (str, int, float, bool)):
            normalized = " ".join(str(value).split()).casefold()
            if not normalized:
                return facts
            if (
                key.endswith("_id")
                or key.endswith("_ids")
                or key
                in {
                    "statement",
                    "public_summary",
                    "next_step",
                    "request",
                    "target",
                    "check_type",
                    "message_type",
                }
            ):
                facts.add(f"{key}:{normalized}")
        return facts

    def clear(self) -> None:
        self._seen_hashes.clear()
        self._seen_facts.clear()
        self._seen_obligations.clear()
        self._seen_evidence.clear()
