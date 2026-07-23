from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def request_fingerprint(problem: str, nonce: str) -> str:
    payload = f"{nonce}\0{problem}".encode("utf-8")
    return sha256(payload).hexdigest()


def file_fingerprint(path: Path) -> str:
    return sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def semantic_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def content_tree_fingerprint(root: Path, pattern: str = "*.md") -> str:
    digest = sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob(pattern), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()
