from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceFragment:
    relative_path: str
    text: str
    truncated: bool


class ReferenceLoader:
    """Read bounded package references; scripts are never executable here."""

    def load(self, package_root: Path, relative_path: str, *, max_chars: int) -> ReferenceFragment:
        if max_chars < 0:
            raise ValueError("reference budget must be nonnegative")
        root = package_root.resolve()
        requested = (root / relative_path).resolve()
        if requested == root or root not in requested.parents:
            raise ValueError("reference path escapes Skill package")
        allowed_roots = {(root / "references").resolve(), (root / "assets").resolve()}
        if not any(requested == item or item in requested.parents for item in allowed_roots):
            raise ValueError("only references/ and assets/ may be disclosed")
        if not requested.is_file():
            raise FileNotFoundError(relative_path)
        text = requested.read_text(encoding="utf-8")
        return ReferenceFragment(relative_path, text[:max_chars], len(text) > max_chars)
