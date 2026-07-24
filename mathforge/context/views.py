from __future__ import annotations

from copy import deepcopy


def candidate_view(candidate: dict, role: str, allowed_claim_ids: set[str] | None = None) -> dict:
    view = deepcopy(candidate)
    if role == "AlternativeSolver" and candidate.get("role") == "PrimarySolver":
        view = {
            "candidate_id": candidate.get("candidate_id"),
            "role": candidate.get("role"),
            "method": candidate.get("method"),
        }
    elif role == "VerifierSkeptic":
        view.pop("solution_text", None)
        view.pop("public_solution_steps", None)
    elif role == "RepairAgent" and allowed_claim_ids is not None:
        view["claims"] = [
            claim for claim in view.get("claims", []) if claim.get("claim_id") in allowed_claim_ids
        ]
        view.pop("solution_text", None)
        view.pop("public_solution_steps", None)
    return view
