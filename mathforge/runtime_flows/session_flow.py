from __future__ import annotations

from typing import Any


class PublicContractGuard:
    """Enforce the immutable formal entry's public result contract."""

    @staticmethod
    def normalize(result: dict[str, Any], fallback_response: str) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {}
        response = str(result.get("final_response", "")).strip()
        result["final_response"] = response or str(fallback_response).strip()
        if not isinstance(result.get("trace"), list):
            result["trace"] = []
        return result
