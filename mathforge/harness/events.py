JUDGE_EVENTS = frozenset(
    {
        "session_started",
        "problem_parsed",
        "route_planned",
        "retrieval_completed",
        "candidate_fanout_completed",
        "hard_evidence_gate",
        "lemma_loop_completed",
        "candidate_arbitrated",
        "primary_completed",
        "answer_validation_warning",
        "repair_completed",
        "deadline_finalize",
        "fallback_used",
    }
)
