from __future__ import annotations


PHYSICAL_BACKENDS = {
    "working": "session",
    "lemma": "session",
    "evidence": "session",
    "semantic": "static",
    "procedural": "static",
    "episodic": "experience",
    "failure": "experience",
    "raw": "session",
}

WRITE_PERMISSIONS = {
    "System": frozenset({"raw", "working", "lemma", "evidence"}),
    "RouterPlanner": frozenset({"working"}),
    "PrimarySolver": frozenset({"working"}),
    "AlternativeSolver": frozenset({"working"}),
    "LemmaCurator": frozenset({"lemma"}),
    "VerifierSkeptic": frozenset({"evidence", "lemma"}),
    "RepairAgent": frozenset({"working"}),
}

READ_PERMISSIONS = {
    "RouterPlanner": frozenset({"raw"}),
    "PrimarySolver": frozenset({"raw", "working", "lemma", "evidence"}),
    "AlternativeSolver": frozenset({"raw", "lemma", "evidence"}),
    "LemmaCurator": frozenset({"raw", "working", "lemma", "evidence"}),
    "VerifierSkeptic": frozenset({"raw", "working", "lemma", "evidence"}),
    "RepairAgent": frozenset({"raw", "working", "lemma", "evidence"}),
    "LLMFinalizer": frozenset({"raw", "working", "lemma", "evidence"}),
}
