from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from mathforge.harness.fingerprints import (
    content_tree_fingerprint,
    semantic_fingerprint,
)


REVIEW_MANIFEST_SCHEMA_VERSION = "1.0"
ROOT = Path(__file__).resolve().parents[2]


def validate_review_manifest(
    path: Path,
    *,
    require_human: bool,
) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["content review manifest is unreadable"]
    if not isinstance(payload, dict):
        return ["content review manifest must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != REVIEW_MANIFEST_SCHEMA_VERSION:
        errors.append("content review manifest schema version is invalid")
    scopes = payload.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        errors.append("content review scopes are missing")
        return errors
    for scope in scopes:
        errors.extend(_validate_scope(scope))
    if require_human and (
        payload.get("status") != "human-approved"
        or not payload.get("human_signatures")
    ):
        errors.append("human review signatures are incomplete")
    return errors


def _validate_scope(scope: Any) -> list[str]:
    if not isinstance(scope, dict):
        return ["content review scope must be an object"]
    identifier = str(scope.get("id", "unknown"))
    required_text = ("version", "engineering_reviewer", "review_date", "sha256")
    for name in required_text:
        if not isinstance(scope.get(name), str) or not scope[name].strip():
            return [f"{identifier} review field {name} is missing"]
    try:
        date.fromisoformat(scope["review_date"])
    except ValueError:
        return [f"{identifier} review date is invalid"]
    try:
        actual_hash, actual_count = _scope_fingerprint(scope)
    except ValueError as error:
        return [f"{identifier} {error}"]
    errors: list[str] = []
    if actual_hash != scope["sha256"]:
        errors.append(f"{identifier} content hash mismatch")
    if actual_count != scope.get("expected_count"):
        errors.append(f"{identifier} content count mismatch")
    return errors


def _scope_fingerprint(scope: dict[str, Any]) -> tuple[str, int]:
    kind = scope.get("kind")
    if kind == "tree":
        root = _safe_path(str(scope.get("path", "")))
        pattern = str(scope.get("pattern", "*.md"))
        files = sorted(root.rglob(pattern))
        return content_tree_fingerprint(root, pattern), len(files)
    if kind == "file":
        path = _safe_path(str(scope.get("path", "")))
        return _normalized_file_hash(path), 1
    if kind == "file_set":
        raw_paths = scope.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise ValueError("file set is empty")
        paths = [_safe_path(str(item)) for item in raw_paths]
        payload = {
            path.relative_to(ROOT).as_posix(): _normalized_file_hash(path)
            for path in paths
        }
        return semantic_fingerprint(payload), len(paths)
    raise ValueError("review scope kind is invalid")


def _safe_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError("review path escapes repository")
    if not path.exists():
        raise ValueError("review path does not exist")
    return path


def _normalized_file_hash(path: Path) -> str:
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
