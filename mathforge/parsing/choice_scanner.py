from __future__ import annotations

from dataclasses import dataclass, field
import re


_MARKER = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"\((?P<paren>[A-H])\)|"
    r"（(?P<cjk_paren>[A-H])）|"
    r"(?P<punctuated>[A-H])[)）.、:：]"
    r")",
    re.IGNORECASE,
)
_CHOICE_INTENT = re.compile(
    r"(?:选择|下列|哪(?:一|个|项)|正确的是|错误的是|"
    r"which\s+of|which\s+(?:statement|answer|option)|"
    r"select\s+(?:the\s+)?(?:correct|best))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChoiceScan:
    options: list[str] = field(default_factory=list)
    stem: str = ""
    confidence: float = 0.0
    conflicts: list[str] = field(default_factory=list)


class ChoiceScanner:
    """Scan line-based and inline A-H option sequences without truncating the stem."""

    def scan(self, text: str) -> ChoiceScan:
        normalized = str(text or "")
        markers = list(_MARKER.finditer(normalized))
        sequences = self._sequences(markers)
        if not sequences:
            conflicts = (
                ["choice_intent_without_reliable_options"]
                if _CHOICE_INTENT.search(normalized)
                else []
            )
            return ChoiceScan(conflicts=conflicts)

        sequence = max(sequences, key=len)
        line_based = all(
            not normalized[normalized.rfind("\n", 0, match.start()) + 1 : match.start()].strip()
            for match in sequence
        )
        if not line_based and len(sequence) < 3 and not _CHOICE_INTENT.search(normalized):
            return ChoiceScan(conflicts=["inline_option_sequence_without_choice_intent"])

        options: list[str] = []
        for index, marker in enumerate(sequence):
            end = sequence[index + 1].start() if index + 1 < len(sequence) else len(normalized)
            content = normalized[marker.end() : end].strip(" \t\r\n;；")
            if not content:
                return ChoiceScan(conflicts=["empty_choice_option"])
            options.append(content)

        conflicts: list[str] = []
        if len(sequences) > 1:
            conflicts.append("multiple_choice_sequences")
        confidence = 0.99 if line_based else 0.96
        return ChoiceScan(
            options=options,
            stem=normalized[: sequence[0].start()].strip(),
            confidence=confidence,
            conflicts=conflicts,
        )

    @staticmethod
    def _sequences(markers: list[re.Match[str]]) -> list[list[re.Match[str]]]:
        sequences: list[list[re.Match[str]]] = []
        current: list[re.Match[str]] = []
        expected = "A"
        for marker in markers:
            label = next(
                value.upper()
                for value in (
                    marker.group("paren"),
                    marker.group("cjk_paren"),
                    marker.group("punctuated"),
                )
                if value
            )
            if label == "A":
                if len(current) >= 2:
                    sequences.append(current)
                current = [marker]
                expected = "B"
                continue
            if current and label == expected:
                current.append(marker)
                expected = chr(ord(expected) + 1)
                continue
            if len(current) >= 2:
                sequences.append(current)
            current = []
            expected = "A"
        if len(current) >= 2:
            sequences.append(current)
        return sequences
