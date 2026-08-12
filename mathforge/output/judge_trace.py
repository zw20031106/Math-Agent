"""Stable public facade for the bounded judge-trace contract.

Projection is intentionally private so callers depend on this small contract,
not the implementation details required to summarize a long multi-agent run.
"""

from mathforge.output._judge_trace_projection import (
    JUDGE_EVENT_STAGES,
    JUDGE_TRACE_SCHEMA_VERSION,
    JudgeTraceIntegrityError,
    JudgeTraceLimits,
    _proof_summary,
    minimal_judge_trace,
    project_judge_trace,
    validate_judge_trace,
)

__all__ = [
    "JUDGE_EVENT_STAGES",
    "JUDGE_TRACE_SCHEMA_VERSION",
    "JudgeTraceIntegrityError",
    "JudgeTraceLimits",
    "minimal_judge_trace",
    "project_judge_trace",
    "validate_judge_trace",
]
