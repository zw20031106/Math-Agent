from __future__ import annotations

from typing import Any


def build_public_result(identifier: int | str | None, result: dict) -> dict:
    final_response = result.get("final_response", "")
    trace = result.get("trace", [])
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError("public result requires a non-empty final_response")
    if not isinstance(trace, list):
        raise ValueError("public result requires a list-valued trace")
    return {
        "id": identifier,
        "final_response": final_response,
        "trace": trace,
    }


def identifier_from_metadata(metadata: dict[str, Any]) -> int | str | None:
    identifier = metadata.get("id", metadata.get("idx"))
    return identifier if isinstance(identifier, (int, str)) else None
