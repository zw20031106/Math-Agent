"""Compatibility facade for the canonical Skill selector.

Skill selection used to have a second implementation in this module.  The
runtime now owns one implementation in :mod:`mathforge.skills.selector`; this
facade preserves the import path used by older integrations and tests.
"""

from mathforge.skills.selector import (
    DynamicSkillComposition,
    DynamicSkillSelector as _CanonicalDynamicSkillSelector,
    SkillFragmentDecision,
)


class DynamicSkillSelector(_CanonicalDynamicSkillSelector):
    """Legacy-compatible selector with no V3 top-k truncation."""

    def __init__(self, registry, *, top_k=None, runtime=None):
        super().__init__(registry, top_k=top_k, runtime=runtime)


__all__ = [
    "DynamicSkillComposition",
    "DynamicSkillSelector",
    "SkillFragmentDecision",
]
