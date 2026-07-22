from __future__ import annotations

from mathforge.harness.repair import ClaimRepairService
from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord


def _candidate() -> CandidateSolution:
    return CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct",
        "old",
        "expression",
        claims=[
            Claim("base", "base claim", status="verified"),
            Claim("failed", "bad step", ["base"], status="rejected"),
            Claim("unrelated", "keep me", status="verified"),
        ],
    )


def _record(candidate_id: str, claim_id: str, status: str) -> EvidenceRecord:
    return EvidenceRecord("e", candidate_id, claim_id, "tool:test", status, "hard", "test")


def test_no_evidence_means_no_repair():
    candidate = _candidate()
    result = ClaimRepairService().attempt(
        candidate,
        [],
        repair=lambda *_: candidate,
        reverify=lambda *_: [],
    )
    assert not result.triggered
    assert result.selected is candidate


def test_repair_changes_only_dependency_closure_and_creates_version():
    candidate = _candidate()
    evidence = [_record("candidate", "failed", "fail")]

    def repair(_candidate, affected, _evidence):
        assert affected == ["base", "failed"]
        return CandidateSolution(
            "patch",
            "RepairAgent",
            "local",
            "new",
            "expression",
            claims=[
                Claim("failed", "corrected step", ["base"], status="unverified"),
                Claim("unrelated", "malicious change", status="unverified"),
            ],
        )

    result = ClaimRepairService().attempt(
        candidate,
        evidence,
        repair=repair,
        reverify=lambda repaired, affected: [
            _record(repaired.candidate_id, "failed", "pass")
        ],
    )
    assert not result.rolled_back
    assert result.selected.version == 2
    assert result.selected.candidate_id == "candidate-v2"
    assert next(claim for claim in result.selected.claims if claim.claim_id == "unrelated").statement == "keep me"
    assert candidate.version == 1


def test_repair_rolls_back_without_reverification_and_honors_limit():
    candidate = _candidate()
    evidence = [_record("candidate", "failed", "fail")]

    def patch(*_):
        return CandidateSolution(
            "patch",
            "RepairAgent",
            "local",
            "new",
            "expression",
            claims=[Claim("failed", "changed", ["base"])],
        )

    service = ClaimRepairService()
    first = service.attempt(candidate, evidence, repair=patch, reverify=lambda *_: [])
    second = service.attempt(candidate, evidence, repair=patch, reverify=lambda *_: [])
    assert first.rolled_back and first.selected is candidate
    assert not second.triggered and second.reason == "candidate_limit"
