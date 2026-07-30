from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


EXACT_INTERN_MODEL = "intern-s2-preview-397b"
UNOBSERVABLE_REASON = "official_client_returns_assistant_content_only"


@dataclass(frozen=True)
class ModelIdentity:
    requested_model: str
    request_source: str
    response_model_observable: bool = False
    thinking_mode_observable: bool = False
    unobservable_reason: str = UNOBSERVABLE_REASON

    def __post_init__(self) -> None:
        if not self.requested_model or not self.request_source:
            raise ValueError("model request identity is incomplete")
        if (
            self.response_model_observable is not False
            or self.thinking_mode_observable is not False
        ):
            raise ValueError("the injected chat surface does not expose response model metadata")
        if self.unobservable_reason != UNOBSERVABLE_REASON:
            raise ValueError("model observability reason is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ModelIdentity:
        expected = {
            "requested_model",
            "request_source",
            "response_model_observable",
            "thinking_mode_observable",
            "unobservable_reason",
        }
        if set(payload) != expected:
            raise ValueError("model identity fields are invalid")
        return cls(**payload)


def exact_model_identity(
    requested_model: str,
    *,
    request_source: str,
) -> ModelIdentity:
    if requested_model != EXACT_INTERN_MODEL:
        raise RuntimeError(
            "model must equal the exact callable model ID "
            f"{EXACT_INTERN_MODEL}; aliases are not accepted"
        )
    return ModelIdentity(
        requested_model=requested_model,
        request_source=request_source,
    )


def official_client_model_identity() -> ModelIdentity:
    return ModelIdentity(
        requested_model="unreported",
        request_source="official_client_injected",
    )


def unreported_model_identity() -> ModelIdentity:
    return ModelIdentity(
        requested_model="unreported",
        request_source="not_supplied",
    )
