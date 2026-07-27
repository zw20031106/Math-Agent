from __future__ import annotations

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
INSTALLED_RESOURCE_ROOT = Path(sys.prefix) / "share" / "mathforge"


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource in a source tree or an installed wheel."""

    source = SOURCE_ROOT.joinpath(*parts)
    if source.exists():
        return source
    return INSTALLED_RESOURCE_ROOT.joinpath(*parts)
