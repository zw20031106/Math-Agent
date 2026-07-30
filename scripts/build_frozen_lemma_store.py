from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from mathforge.memory.frozen_lemma_store import (
    FROZEN_LEMMA_MANIFEST_SCHEMA_VERSION,
    freeze_reviewed_payload,
)


def build_store(staging: Path, output: Path, manifest_path: Path) -> dict:
    records = []
    seen: set[str] = set()
    for line in staging.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        lemma = freeze_reviewed_payload(json.loads(line))
        if lemma.lemma_id in seen:
            raise ValueError(f"duplicate lemma id: {lemma.lemma_id}")
        seen.add(lemma.lemma_id)
        records.append(lemma)
    records.sort(key=lambda item: item.lemma_id)
    rendered = "".join(
        json.dumps(
            item.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for item in records
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    raw = output.read_bytes()
    manifest = {
        "schema_version": FROZEN_LEMMA_MANIFEST_SCHEMA_VERSION,
        "record_count": len(records),
        "store_sha256": sha256(raw).hexdigest(),
        "source": str(staging.name),
        "build_mode": "offline_reviewed_only",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a reviewed, immutable MathForge lemma store."
    )
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    build_store(args.staging, args.output, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

