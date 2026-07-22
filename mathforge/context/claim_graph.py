from __future__ import annotations

from mathforge.harness.schemas import Claim


class ClaimGraph:
    def __init__(self, claims: list[Claim]) -> None:
        self._claims = {claim.claim_id: claim for claim in claims}

    def dependency_closure(self, claim_ids: list[str]) -> list[str]:
        closure: set[str] = set()
        stack = list(claim_ids)
        while stack:
            claim_id = stack.pop()
            if claim_id in closure or claim_id not in self._claims:
                continue
            closure.add(claim_id)
            stack.extend(self._claims[claim_id].depends_on)
        return sorted(closure)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            claim_id: list(claim.depends_on)
            for claim_id, claim in sorted(self._claims.items())
        }
