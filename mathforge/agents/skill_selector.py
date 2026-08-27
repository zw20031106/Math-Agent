"""Compatibility facade for the canonical Skill selector.

Skill selection used to have a second implementation in this module.  The
runtime now owns one implementation in :mod:`mathforge.skills.selector`; this
facade preserves the import path used by older integrations and tests.
"""

from mathforge.skills.selector import (
    DynamicSkillComposition,
    DynamicSkillSelector,
    SkillFragmentDecision,
)


__all__ = [
    "DynamicSkillComposition",
    "DynamicSkillSelector",
    "SkillFragmentDecision",
]
