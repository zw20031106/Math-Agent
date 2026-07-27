"""Verify immutable official baseline files using Git blob object IDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "baseline_manifest.json"
IMMUTABLE_FILES = ("main.py", "llm_client.py")


def git_blob_sha(path: Path) -> str:
    # Git blob IDs are computed from repository content. On Windows, a normal
    # checkout may materialize text files with CRLF even though the canonical
    # blob contains LF, so mirror Git's text normalization before hashing.
    content = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def verify() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("schema_version") != "2.0":
        errors.append("baseline manifest schema must be 2.0")
    immutable = manifest.get("official_immutable")
    if not isinstance(immutable, dict) or set(immutable) != set(IMMUTABLE_FILES):
        errors.append("baseline manifest immutable file group is invalid")
        immutable = {}
    if manifest.get("participant_mutable") != ["user_agent.py"]:
        errors.append("baseline manifest participant-mutable group is invalid")
    for relative_path in IMMUTABLE_FILES:
        path = ROOT / relative_path
        expected = immutable.get(relative_path)
        if not path.is_file():
            errors.append(f"missing baseline file: {relative_path}")
            continue
        if not isinstance(expected, str):
            continue
        actual = git_blob_sha(path)
        if actual != expected:
            errors.append(
                f"baseline mismatch for {relative_path}: expected {expected}, got {actual}"
            )
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("\n".join(errors))
        return 1
    print("Official immutable baseline files verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
