from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Callable

from mathforge.evaluation.evidence_registry import (
    validate_evidence_registry,
    validate_registered_trees,
)
from mathforge.governance.reviews import validate_review_manifest
from mathforge.harness.fingerprints import (
    content_tree_fingerprint,
    semantic_fingerprint,
)


RELEASE_MANIFEST_SCHEMA_VERSION = "1.0"
_RELEASE_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "competition_config_sha256",
        "prompt_tree_sha256",
        "skill_tree_sha256",
        "evidence_registry_sha256",
        "content_review_manifest_sha256",
        "test_attestation",
    }
)


@dataclass(frozen=True)
class ReleaseReadiness:
    active_baseline: bool
    clean_commit: bool
    all_tests: bool
    content_manifest: bool
    prompt_hash: bool
    skill_hash: bool
    benchmark_evidence: bool
    human_review: bool
    competition_frozen: bool
    competition_hash: bool
    test_attestation: bool
    baseline_commit: bool

    def to_dict(self) -> dict:
        return asdict(self)


_ERRORS = {
    "active_baseline": "active benchmark baseline is missing or invalid",
    "clean_commit": "release commit is dirty",
    "all_tests": "full release test suite has not passed",
    "content_manifest": "content review manifest is invalid",
    "prompt_hash": "prompt tree hash does not match release governance",
    "skill_hash": "skill tree hash does not match release governance",
    "benchmark_evidence": "benchmark evidence is unavailable or fingerprint-invalid",
    "human_review": "human review signatures are incomplete",
    "competition_frozen": "competition config is not frozen",
    "competition_hash": "competition config hash does not match release governance",
    "test_attestation": "release test attestation is missing or stale",
    "baseline_commit": (
        "active baseline commit/config is not an ancestor-compatible release input"
    ),
}


def evaluate_release_readiness(readiness: ReleaseReadiness) -> list[str]:
    state = readiness.to_dict()
    return [_ERRORS[name] for name in _ERRORS if not state[name]]


def release_content_fingerprints(root: Path) -> dict[str, str]:
    prompt_hash = content_tree_fingerprint(root / "prompts", "*.md")
    skill_hash = semantic_fingerprint(
        {
            "legacy": content_tree_fingerprint(root / "skills", "*.md"),
            "packages": content_tree_fingerprint(
                root / "mathforge" / "skills" / "packages",
                "SKILL.md",
            ),
        }
    )
    return {"prompt_tree_sha256": prompt_hash, "skill_tree_sha256": skill_hash}


def release_source_fingerprint(root: Path) -> str:
    fingerprints = release_content_fingerprints(root)
    return semantic_fingerprint(
        {
            "mathforge_python": content_tree_fingerprint(root / "mathforge", "*.py"),
            "scripts_python": content_tree_fingerprint(root / "scripts", "*.py"),
            "tests_python": content_tree_fingerprint(root / "tests", "*.py"),
            "public_entry": sha256((root / "user_agent.py").read_bytes()).hexdigest(),
            "competition_config": sha256(
                (root / "config" / "competition.json").read_bytes()
            ).hexdigest(),
            **fingerprints,
        }
    )


def validate_release_governance_manifest(root: Path) -> list[str]:
    root = root.resolve()
    manifest = _read_json(root / "data" / "release_governance_manifest.json")
    if not manifest:
        return ["release governance manifest is unreadable"]
    errors: list[str] = []
    if set(manifest) != _RELEASE_MANIFEST_FIELDS:
        errors.append("release governance manifest fields are invalid")
    if manifest.get("schema_version") != RELEASE_MANIFEST_SCHEMA_VERSION:
        errors.append("release governance manifest schema is invalid")
    if manifest.get("status") not in {"candidate-unvalidated", "frozen"}:
        errors.append("release governance status is invalid")
    fingerprints = release_content_fingerprints(root)
    expected = {
        "competition_config_sha256": sha256(
            (root / "config" / "competition.json").read_bytes()
        ).hexdigest(),
        "evidence_registry_sha256": sha256(
            (root / "data" / "evaluation_evidence_registry.json").read_bytes()
        ).hexdigest(),
        "content_review_manifest_sha256": sha256(
            (root / "docs" / "content_review_manifest.json").read_bytes()
        ).hexdigest(),
        **fingerprints,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            errors.append(f"release governance {field} mismatch")
    attestation = manifest.get("test_attestation")
    if not isinstance(attestation, dict) or set(attestation) != {
        "status",
        "source_sha256",
    }:
        errors.append("release test attestation is invalid")
    elif attestation.get("status") not in {"pending-phase11", "passed"}:
        errors.append("release test attestation status is invalid")
    return errors


def collect_release_readiness(
    root: Path,
    *,
    results_root: Path | None,
    all_tests_passed: bool,
    git: Callable[[list[str]], str] | None = None,
) -> ReleaseReadiness:
    root = root.resolve()
    release_manifest = _read_json(root / "data" / "release_governance_manifest.json")
    evidence = _read_json(root / "data" / "evaluation_evidence_registry.json")
    competition_path = root / "config" / "competition.json"
    review_path = root / "docs" / "content_review_manifest.json"
    competition = _read_json(competition_path)
    reviews = _read_json(review_path)
    git_call = git or (lambda args: _git(root, args))
    try:
        head = git_call(["rev-parse", "HEAD"]).strip()
        clean = not git_call(["status", "--porcelain"]).strip()
    except (OSError, subprocess.SubprocessError):
        head = ""
        clean = False

    registry_errors = (
        validate_evidence_registry(evidence) if isinstance(evidence, dict) else ["invalid"]
    )
    active_id = evidence.get("active_baseline_id") if isinstance(evidence, dict) else None
    active_entry = next(
        (
            item
            for item in evidence.get("entries", [])
            if isinstance(item, dict) and item.get("id") == active_id
        ),
        None,
    ) if isinstance(evidence, dict) else None
    active_baseline = not registry_errors and active_entry is not None
    tree_valid = False
    if active_baseline and results_root is not None:
        tree_valid = not validate_registered_trees(
            {"entries": [active_entry]},
            results_root,
        )

    engineering_review_valid = not validate_review_manifest(
        review_path,
        require_human=False,
    )
    human_review_valid = not validate_review_manifest(
        review_path,
        require_human=True,
    )
    fingerprints = release_content_fingerprints(root)
    manifest_valid = (
        isinstance(release_manifest, dict)
        and release_manifest.get("schema_version") == RELEASE_MANIFEST_SCHEMA_VERSION
    )
    competition_hash = sha256(competition_path.read_bytes()).hexdigest()
    review_hash = sha256(review_path.read_bytes()).hexdigest()
    evidence_hash = sha256(
        (root / "data" / "evaluation_evidence_registry.json").read_bytes()
    ).hexdigest()
    if manifest_valid:
        engineering_review_valid = engineering_review_valid and (
            release_manifest.get("content_review_manifest_sha256") == review_hash
            and release_manifest.get("evidence_registry_sha256") == evidence_hash
        )
    attestation = (
        release_manifest.get("test_attestation", {}) if manifest_valid else {}
    )
    baseline_is_ancestor = False
    if active_entry is not None and head:
        try:
            git_call(
                [
                    "merge-base",
                    "--is-ancestor",
                    str(active_entry.get("git_commit", "")),
                    head,
                ]
            )
        except (OSError, subprocess.SubprocessError):
            baseline_is_ancestor = False
        else:
            baseline_is_ancestor = True
    baseline_config_matches = (
        active_entry is not None
        and active_entry.get("config_sha256") == competition_hash
    )
    return ReleaseReadiness(
        active_baseline=active_baseline,
        clean_commit=clean,
        all_tests=bool(all_tests_passed),
        content_manifest=engineering_review_valid,
        prompt_hash=(
            manifest_valid
            and release_manifest.get("prompt_tree_sha256")
            == fingerprints["prompt_tree_sha256"]
        ),
        skill_hash=(
            manifest_valid
            and release_manifest.get("skill_tree_sha256")
            == fingerprints["skill_tree_sha256"]
        ),
        benchmark_evidence=active_baseline and tree_valid,
        human_review=human_review_valid and reviews.get("status") == "human-approved",
        competition_frozen=competition.get("status") == "frozen",
        competition_hash=(
            manifest_valid
            and release_manifest.get("competition_config_sha256") == competition_hash
        ),
        test_attestation=(
            isinstance(attestation, dict)
            and attestation.get("status") == "passed"
            and attestation.get("source_sha256")
            == release_source_fingerprint(root)
        ),
        baseline_commit=baseline_is_ancestor and baseline_config_matches,
    )


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _git(root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
