from __future__ import annotations

WRITE_PERMISSIONS = {
    "System": frozenset({"raw", "working", "lemma", "evidence"}),
    "Host": frozenset({"summary"}),
    "RouterPlanner": frozenset({"working"}),
    "PrimarySolver": frozenset({"working"}),
    "AlternativeSolver": frozenset({"working"}),
    "LemmaCurator": frozenset({"lemma"}),
    "VerifierSkeptic": frozenset({"evidence", "lemma"}),
    "RepairAgent": frozenset({"working"}),
}

READ_PERMISSIONS = {
    "RouterPlanner": frozenset({"raw"}),
    "PrimarySolver": frozenset({"raw", "working", "lemma", "evidence", "summary"}),
    "AlternativeSolver": frozenset({"raw", "lemma", "evidence", "summary"}),
    "LemmaCurator": frozenset({"raw", "working", "lemma", "evidence", "summary"}),
    "VerifierSkeptic": frozenset({"raw", "working", "lemma", "evidence", "summary"}),
    "RepairAgent": frozenset({"raw", "working", "lemma", "evidence", "summary"}),
    "LLMFinalizer": frozenset({"raw", "working", "lemma", "evidence", "summary"}),
}
