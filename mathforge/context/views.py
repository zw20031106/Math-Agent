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
        view = {
            key: deepcopy(candidate[key])
            for key in (
                "candidate_id",
                "method",
                "final_answer",
                "assumptions",
                "theorems",
                "claims",
                "method_steps",
                "unresolved_obligations",
            )
            if key in candidate
        }
        view["review_segments"] = _review_segments(candidate)
    elif role == "RepairAgent" and allowed_claim_ids is not None:
        view["claims"] = [
            claim for claim in view.get("claims", []) if claim.get("claim_id") in allowed_claim_ids
        ]
        view.pop("solution_text", None)
        view.pop("public_solution_steps", None)
    return view


def _review_segments(candidate: dict) -> list[dict]:
    claims = [
        item
        for item in candidate.get("claims", [])
        if isinstance(item, dict)
    ]
    valid_ids = {
        str(item.get("claim_id", ""))
        for item in claims
        if str(item.get("claim_id", ""))
    }
    fallback_ids = [
        str(item.get("claim_id", ""))
        for item in claims
        if item.get("importance") == "critical"
        and str(item.get("claim_id", ""))
    ] or sorted(valid_ids)
    method_steps = [
        item
        for item in candidate.get("method_steps", [])
        if isinstance(item, dict)
    ]
    candidate_id = str(candidate.get("candidate_id", "candidate"))
    segments: list[dict] = []
    for index, text in enumerate(
        candidate.get("public_solution_steps", [])[:64]
    ):
        if not isinstance(text, str) or not text.strip():
            continue
        raw_claim_ids = (
            method_steps[index].get("claim_ids", [])
            if index < len(method_steps)
            else []
        )
        claim_ids = [
            str(claim_id)
            for claim_id in raw_claim_ids
            if str(claim_id) in valid_ids
        ] or fallback_ids[:4]
        segments.append(
            {
                "segment_id": (
                    f"{candidate_id}:public-step:{index + 1}"
                ),
                "claim_ids": list(dict.fromkeys(claim_ids)),
                "text": text.strip()[:3000],
            }
        )
    if not segments:
        for index, claim in enumerate(claims[:64]):
            statement = str(claim.get("statement", "")).strip()
            claim_id = str(claim.get("claim_id", "")).strip()
            if not statement or not claim_id:
                continue
            segments.append(
                {
                    "segment_id": f"{candidate_id}:claim:{index + 1}",
                    "claim_ids": [claim_id],
                    "text": statement[:3000],
                }
            )
    return segments
