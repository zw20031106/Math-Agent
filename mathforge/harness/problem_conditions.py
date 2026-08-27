"""One immutable, public view of the conditions of a parsed problem.

The model-facing roles must receive the same condition projection.  Keeping the
projection here prevents a role from accidentally reading only ``assumptions``
while another role reads the parser's definitions or quantifiers directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _string_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)
        except TypeError:
            values = (str(value),)
    result: list[str] = []
    for item in values:
        normalized = " ".join(str(item).split()).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


@dataclass(frozen=True)
class ProblemConditionEnvelope:
    """Immutable condition categories shared by all model-facing roles."""

    definitions: tuple[str, ...] = ()
    quantifiers: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    domains: tuple[tuple[str, str], ...] = ()
    target: str = ""
    ambiguities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "definitions",
            "quantifiers",
            "constraints",
            "assumptions",
            "ambiguities",
        ):
            object.__setattr__(self, name, _string_items(getattr(self, name)))
        raw_domains = self.domains
        if isinstance(raw_domains, Mapping):
            pairs = raw_domains.items()
        else:
            pairs = raw_domains
        normalized_domains: list[tuple[str, str]] = []
        for item in pairs or ():
            if isinstance(item, Mapping):
                key = item.get("name", item.get("symbol", ""))
                value = item.get("domain", item.get("value", ""))
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                key, value = item
            else:
                continue
            key_text = " ".join(str(key).split()).strip()
            value_text = " ".join(str(value).split()).strip()
            if key_text and (key_text, value_text) not in normalized_domains:
                normalized_domains.append((key_text, value_text))
        normalized_domains.sort(key=lambda pair: (pair[0], pair[1]))
        object.__setattr__(self, "domains", tuple(normalized_domains))
        object.__setattr__(self, "target", " ".join(str(self.target).split()).strip())

    @classmethod
    def from_problem(cls, problem: Any) -> "ProblemConditionEnvelope":
        """Build the envelope from a ``ProblemIR``-like object.

        Duck typing keeps this service usable by tests and by the immutable
        parser schema without introducing a module import cycle.
        """

        target_phrase = str(
            getattr(problem, "target_phrase", None)
            or getattr(problem, "problem", "")
            or ""
        ).strip()
        target_kind = str(getattr(problem, "target_kind", "") or "").strip()
        target = target_phrase or target_kind
        if target_phrase and target_kind and target_kind not in target_phrase:
            target = f"{target_phrase} [{target_kind}]"
        return cls(
            definitions=getattr(problem, "definitions", ()),
            quantifiers=getattr(problem, "quantifiers", ()),
            constraints=getattr(problem, "constraints", ()),
            assumptions=getattr(
                problem,
                "assumptions",
                getattr(problem, "conditions", ()),
            ),
            domains=getattr(problem, "domains", {}),
            target=target,
            ambiguities=(
                *getattr(problem, "ambiguities", ()),
                *getattr(problem, "target_conflicts", ()),
                *getattr(problem, "answer_type_conflicts", ()),
                *getattr(problem, "response_mode_conflicts", ()),
            ),
        )

    def to_dict(self, *, include_target: bool = True) -> dict[str, Any]:
        payload = {
            "definitions": list(self.definitions),
            "quantifiers": list(self.quantifiers),
            "constraints": list(self.constraints),
            "assumptions": list(self.assumptions),
            "domains": {key: value for key, value in self.domains},
            "ambiguities": list(self.ambiguities),
        }
        if include_target:
            payload["target"] = self.target
        return payload

    def to_prompt(self, *, include_target: bool = True) -> str:
        """Render a compact, category-preserving public prompt block."""

        def render(items: tuple[str, ...]) -> str:
            return "; ".join(items) if items else "none"

        domain_text = "; ".join(
            f"{name}: {value}" if value else name
            for name, value in self.domains
        ) or "none"
        target = self.target if include_target else "provided in the Problem statement"
        return "\n".join(
            (
                "ProblemConditionEnvelope (shared immutable conditions):",
                f"Definitions: {render(self.definitions)}",
                f"Quantifiers: {render(self.quantifiers)}",
                f"Constraints: {render(self.constraints)}",
                f"Assumptions: {render(self.assumptions)}",
                f"Domains: {domain_text}",
                f"Target: {target or 'unspecified'}",
                f"Ambiguities: {render(self.ambiguities)}",
            )
        )

    @property
    def all_conditions(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.definitions,
                    *self.quantifiers,
                    *self.constraints,
                    *self.assumptions,
                    *(f"{key}: {value}" for key, value in self.domains),
                )
            )
        )


class ProblemConditionBuilder:
    """Named builder used by every model-facing role."""

    @staticmethod
    def build(problem: Any) -> ProblemConditionEnvelope:
        return ProblemConditionEnvelope.from_problem(problem)


def build_problem_condition_envelope(problem: Any) -> ProblemConditionEnvelope:
    return ProblemConditionBuilder.build(problem)


__all__ = [
    "ProblemConditionBuilder",
    "ProblemConditionEnvelope",
    "build_problem_condition_envelope",
]
