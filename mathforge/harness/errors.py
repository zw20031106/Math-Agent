from __future__ import annotations

from enum import Enum

from mathforge.harness.state import RuntimePhase


class MathForgeError(Exception):
    """Base class for expected harness failures."""


class BudgetExceeded(MathForgeError):
    """A call, token, or time budget was exhausted."""


class ContractViolation(MathForgeError):
    """A component returned data outside its public contract."""


class FailureCode(str, Enum):
    PARSE = "parse"
    CONTEXT = "context"
    BUDGET = "budget"
    TOOL = "tool"
    PROOF_INCOMPLETE = "proof_incomplete"
    ALL_CANDIDATES_FAILED = "all_candidates_failed"
    CONFIG = "config"


def classify_failure(error: Exception, phase: RuntimePhase) -> FailureCode:
    """Map internal failures to the stable, non-sensitive public taxonomy."""

    error_type = type(error).__name__
    message = str(error).lower()
    if isinstance(error, BudgetExceeded):
        return FailureCode.BUDGET
    if error_type == "ContextBudgetExceeded":
        return FailureCode.CONTEXT
    if error_type == "SchemaValidationError":
        return FailureCode.PARSE
    if "deadline" in message or "budget" in message:
        return FailureCode.BUDGET
    if "proof candidate" in message or "completion gate" in message:
        return FailureCode.PROOF_INCOMPLETE
    if "all solver branches" in message or "all candidates" in message:
        return FailureCode.ALL_CANDIDATES_FAILED
    if phase in {RuntimePhase.CANDIDATES_READY, RuntimePhase.EVIDENCE_READY}:
        return FailureCode.TOOL
    if phase == RuntimePhase.CREATED and isinstance(error, ValueError):
        return FailureCode.CONFIG
    return FailureCode.ALL_CANDIDATES_FAILED
