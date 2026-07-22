from __future__ import annotations

from typing import Any

from mathforge.memory.session_memory import SessionMemory


class LemmaMemory:
    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def add_verified(self, lemma: dict[str, Any]) -> None:
        if lemma.get("status") != "verified":
            raise ValueError("only verified lemmas can enter solver-visible memory")
        self._memory.add("lemma", dict(lemma), "VerifierSkeptic")

    def verified(self) -> list[dict[str, Any]]:
        return [
            dict(item.payload)
            for item in self._memory.read(frozenset({"lemma"}))
            if item.payload.get("status") == "verified"
        ]

    def to_dict(self) -> dict:
        return {"verified": self.verified()}
