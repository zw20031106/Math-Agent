from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from mathforge.harness.schemas import ProblemIR


FROZEN_LEMMA_SCHEMA_VERSION = "1.0"
FROZEN_LEMMA_MANIFEST_SCHEMA_VERSION = "1.0"
_HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def lemma_content_hash(payload: dict[str, Any]) -> str:
    content = dict(payload)
    content.pop("content_hash", None)
    return sha256(_canonical_payload(content)).hexdigest()


@dataclass(frozen=True)
class FrozenLemma:
    lemma_id: str
    statement: str
    normalized_signature: str
    domain: str
    assumptions: tuple[str, ...]
    preconditions: tuple[str, ...]
    conclusion: str
    proof_outline_public: tuple[str, ...]
    verification_type: str
    verification_artifact_hash: str
    source_version: str
    review_status: str
    content_hash: str
    schema_version: str = FROZEN_LEMMA_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FrozenLemma":
        required = {
            "schema_version",
            "lemma_id",
            "statement",
            "normalized_signature",
            "domain",
            "assumptions",
            "preconditions",
            "conclusion",
            "proof_outline_public",
            "verification_type",
            "verification_artifact_hash",
            "source_version",
            "review_status",
            "content_hash",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("frozen lemma fields do not match the schema")
        for name in required - {
            "assumptions",
            "preconditions",
            "proof_outline_public",
        }:
            if not isinstance(payload[name], str):
                raise ValueError(f"frozen lemma {name} must be a string")
        for name in ("assumptions", "preconditions", "proof_outline_public"):
            value = payload[name]
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(f"frozen lemma {name} must be a string list")
        lemma = cls(
            lemma_id=payload["lemma_id"],
            statement=payload["statement"],
            normalized_signature=payload["normalized_signature"],
            domain=payload["domain"],
            assumptions=tuple(payload["assumptions"]),
            preconditions=tuple(payload["preconditions"]),
            conclusion=payload["conclusion"],
            proof_outline_public=tuple(payload["proof_outline_public"]),
            verification_type=payload["verification_type"],
            verification_artifact_hash=payload["verification_artifact_hash"],
            source_version=payload["source_version"],
            review_status=payload["review_status"],
            content_hash=payload["content_hash"],
            schema_version=payload["schema_version"],
        )
        lemma.validate()
        return lemma

    def validate(self) -> None:
        if self.schema_version != FROZEN_LEMMA_SCHEMA_VERSION:
            raise ValueError("unsupported frozen lemma schema")
        if not all(
            (
                self.lemma_id,
                self.statement,
                self.normalized_signature,
                self.domain,
                self.conclusion,
                self.verification_type,
                self.source_version,
            )
        ):
            raise ValueError("frozen lemma required text is empty")
        if self.review_status != "frozen":
            raise ValueError("only reviewed and frozen lemmas may be loaded")
        if not _HEX_HASH.fullmatch(self.verification_artifact_hash):
            raise ValueError("invalid verification artifact hash")
        if not _HEX_HASH.fullmatch(self.content_hash):
            raise ValueError("invalid frozen lemma content hash")
        if self.content_hash != lemma_content_hash(self.to_dict()):
            raise ValueError("frozen lemma content hash mismatch")
        forbidden = (
            "benchmark_nonce",
            "candidate_id",
            "final_response",
            "test_case_id",
        )
        serialized = json.dumps(self.to_dict(), ensure_ascii=False).casefold()
        if any(marker in serialized for marker in forbidden):
            raise ValueError("frozen lemma contains case-specific content")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lemma_id": self.lemma_id,
            "statement": self.statement,
            "normalized_signature": self.normalized_signature,
            "domain": self.domain,
            "assumptions": list(self.assumptions),
            "preconditions": list(self.preconditions),
            "conclusion": self.conclusion,
            "proof_outline_public": list(self.proof_outline_public),
            "verification_type": self.verification_type,
            "verification_artifact_hash": self.verification_artifact_hash,
            "source_version": self.source_version,
            "review_status": self.review_status,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FrozenLemmaHit:
    lemma: FrozenLemma
    score: int
    assumption_checks: tuple[dict[str, Any], ...]

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "lemma_id": self.lemma.lemma_id,
            "content_hash": self.lemma.content_hash,
            "score": self.score,
            "assumption_checks": [dict(item) for item in self.assumption_checks],
        }


class FrozenLemmaStore:
    """Immutable, hash-checked L2 store used only for read-time retrieval."""

    def __init__(self, data_path: Path, manifest_path: Path) -> None:
        self._data_path = Path(data_path)
        self._manifest_path = Path(manifest_path)
        self._lemmas, self._store_hash = self._load()

    @property
    def store_hash(self) -> str:
        return self._store_hash

    @property
    def count(self) -> int:
        return len(self._lemmas)

    def retrieve(
        self,
        problem: ProblemIR,
        *,
        limit: int = 4,
    ) -> tuple[FrozenLemmaHit, ...]:
        query = _tokens(
            " ".join(
                [
                    problem.normalized_problem,
                    *problem.assumptions,
                    *problem.domains.keys(),
                    *problem.domains.values(),
                ]
            )
        )
        context = _normalized(
            " ".join(
                [
                    problem.normalized_problem,
                    *problem.assumptions,
                    *(
                        f"{key} {value}"
                        for key, value in problem.domains.items()
                    ),
                ]
            )
        )
        hits: list[FrozenLemmaHit] = []
        for lemma in self._lemmas:
            checks = tuple(
                {
                    "condition": condition,
                    "satisfied": _normalized(condition) in context,
                }
                for condition in (*lemma.assumptions, *lemma.preconditions)
            )
            if any(not item["satisfied"] for item in checks):
                continue
            signature_tokens = _tokens(
                f"{lemma.normalized_signature} {lemma.domain} "
                f"{lemma.statement} {lemma.conclusion}"
            )
            score = len(query.intersection(signature_tokens))
            if score <= 0:
                continue
            hits.append(FrozenLemmaHit(lemma, score, checks))
        hits.sort(key=lambda item: (-item.score, item.lemma.lemma_id))
        return tuple(hits[: max(0, limit)])

    def _load(self) -> tuple[tuple[FrozenLemma, ...], str]:
        if not self._data_path.exists() or not self._manifest_path.exists():
            return (), ""
        raw = self._data_path.read_bytes()
        store_hash = sha256(raw).hexdigest()
        manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != FROZEN_LEMMA_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported frozen lemma manifest")
        if manifest.get("store_sha256") != store_hash:
            raise ValueError("frozen lemma store hash mismatch")
        records = []
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                records.append(FrozenLemma.from_dict(json.loads(line)))
        if manifest.get("record_count") != len(records):
            raise ValueError("frozen lemma record count mismatch")
        if len({item.lemma_id for item in records}) != len(records):
            raise ValueError("duplicate frozen lemma id")
        return tuple(records), store_hash


def freeze_reviewed_payload(payload: dict[str, Any]) -> FrozenLemma:
    staged = dict(payload)
    if staged.get("review_status") != "human_approved":
        raise ValueError("staged lemma lacks human approval")
    staged["schema_version"] = FROZEN_LEMMA_SCHEMA_VERSION
    staged["review_status"] = "frozen"
    staged["content_hash"] = ""
    staged["content_hash"] = lemma_content_hash(staged)
    return FrozenLemma.from_dict(staged)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in _TOKEN.findall(value)}
