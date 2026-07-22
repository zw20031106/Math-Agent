class MathForgeError(Exception):
    """Base class for expected harness failures."""


class BudgetExceeded(MathForgeError):
    """A call, token, or time budget was exhausted."""


class ContractViolation(MathForgeError):
    """A component returned data outside its public contract."""
