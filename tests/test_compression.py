from __future__ import annotations

import pytest

from mathforge.context.compressor import ContextCompressor
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import ContextSnapshot
from mathforge.context.validator import CompressionValidator


def _snapshot() -> ContextSnapshot:
    return ContextSnapshot(
        "ctx-1",
        "raw:1",
        "prove P under condition C",
        ["C"],
        "P",
        candidates=[
            {
                "candidate_id": "primary",
                "role": "PrimarySolver",
                "method": "direct",
                "solution_text": "full private derivation",
                "claims": [
                    {"claim_id": "c1", "depends_on": []},
                    {"claim_id": "c2", "depends_on": ["c1"]},
                    {"claim_id": "c3", "depends_on": []},
                ],
            }
        ],
        evidence=[
            {"evidence_id": "hard-1", "strength": "hard", "status": "pass"},
            {"evidence_id": "soft-1", "strength": "soft", "status": "pass"},
        ],
        obligations=[{"obligation_id": "required-1", "required": True}],
        claim_graph={"c1": [], "c2": ["c1"], "c3": []},
    )


def test_agent_views_hide_primary_derivation_and_limit_repair_closure():
    compressor = ContextCompressor()
    alternative = compressor.compress(_snapshot(), role="AlternativeSolver")
    assert "solution_text" not in alternative.candidates[0]
    repair = compressor.compress(_snapshot(), role="RepairAgent", focus_claim_ids=["c2"])
    assert {claim["claim_id"] for claim in repair.candidates[0]["claims"]} == {"c1", "c2"}
    assert set(repair.claim_graph) == {"c1", "c2"}


def test_compression_preserves_hard_invariants_and_rolls_back_invalid_view():
    original = _snapshot()
    compressed = ContextCompressor().compress(original, role="VerifierSkeptic", max_chars=1000)
    assert CompressionValidator().validate(original, compressed) == []
    assert ContextCompressor.serialized_size(compressed) <= 1000
    invalid = _snapshot()
    invalid.original_problem = "changed"
    assert "original_problem_changed" in CompressionValidator().validate(original, invalid)


def test_compression_explicitly_rejects_an_infeasible_hard_budget():
    with pytest.raises(ContextBudgetExceeded, match="budget"):
        ContextCompressor().compress(
            _snapshot(),
            role="VerifierSkeptic",
            max_chars=300,
        )
