from __future__ import annotations

import re
import unicodedata


_SYMBOL_REPLACEMENTS = {
    "−": "-",
    "–": "-",
    "×": r"\times",
    "÷": r"\div",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "∞": r"\infty",
    "∈": r"\in",
    "∪": r"\cup",
    "∩": r"\cap",
    "√": r"\sqrt",
}


def normalize_problem(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    for source, target in _SYMBOL_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line).strip()
