from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "build_provenance_manifest.json"


def verify() -> list[str]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checks = (
        (
            ROOT / "data" / "math_knowledge.sqlite",
            payload.get("knowledge_db_sha256"),
            "knowledge database",
        ),
        (
            ROOT / "docs" / "content_review_manifest.json",
            payload.get("content_reviews", {}).get("manifest_sha256"),
            "content review manifest",
        ),
        (
            ROOT / "config" / "component_decisions.json",
            payload.get("component_decisions", {}).get("manifest_sha256"),
            "component decisions",
        ),
        (
            ROOT / "data" / "release_governance_manifest.json",
            payload.get("release_governance", {}).get("manifest_sha256"),
            "release governance manifest",
        ),
    )
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("build provenance schema must be 1.0")
    for path, expected, name in checks:
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"{name} hash does not match build provenance")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("\n".join(errors))
        return 1
    print("Build provenance manifest verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
