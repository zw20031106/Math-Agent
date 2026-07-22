from __future__ import annotations


class FallbackSolver:
    """Return a safe non-empty response when the primary path is unavailable."""

    def solve(self, problem: str) -> str:
        if not problem.strip():
            return "No mathematical problem was provided."
        return (
            "The mathematical model call was unavailable, so a verified solution "
            "could not be produced for this problem."
        )
