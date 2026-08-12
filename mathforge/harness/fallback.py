from __future__ import annotations

from mathforge.harness.terminalizer import MINIMAL_FALLBACK_RESPONSE


class FallbackSolver:
    """Return a safe non-empty response when the primary path is unavailable."""

    def solve(self, problem: str) -> str:
        del problem
        return MINIMAL_FALLBACK_RESPONSE
