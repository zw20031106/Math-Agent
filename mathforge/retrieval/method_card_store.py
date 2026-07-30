from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from mathforge.retrieval.schemas import KnowledgeCard


METHOD_CARD_MANIFEST_SCHEMA_VERSION = "1.0"


class ReviewedMethodCardStore:
    """Read-only, hash-bound library of reviewed general method cards."""

    def __init__(self, data_path: Path, manifest_path: Path) -> None:
        self._data_path = Path(data_path)
        self._manifest_path = Path(manifest_path)
        self._cards, self._store_hash, self._library_version = self._load()

    @property
    def cards(self) -> tuple[KnowledgeCard, ...]:
        return self._cards

    @property
    def store_hash(self) -> str:
        return self._store_hash

    @property
    def library_version(self) -> str:
        return self._library_version

    def _load(self) -> tuple[tuple[KnowledgeCard, ...], str, str]:
        raw = self._data_path.read_bytes()
        store_hash = sha256(raw).hexdigest()
        manifest = json.loads(
            self._manifest_path.read_text(encoding="utf-8")
        )
        if (
            manifest.get("schema_version")
            != METHOD_CARD_MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported method-card manifest")
        if manifest.get("store_sha256") != store_hash:
            raise ValueError("method-card store hash mismatch")
        if manifest.get("runtime_enabled_before_ab") is not False:
            raise ValueError("method-card library must remain disabled before A/B")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("method-card store must be an array")
        cards = tuple(KnowledgeCard.from_dict(item) for item in payload)
        if manifest.get("record_count") != len(cards):
            raise ValueError("method-card record count mismatch")
        if len({card.id for card in cards}) != len(cards):
            raise ValueError("duplicate method-card id")
        for card in cards:
            if (
                card.trust_level != "reviewed"
                or not card.reviewer
                or not card.review_date
                or not card.source_version
            ):
                raise ValueError("method card lacks review/version metadata")
            if card.content_hash != card.computed_content_hash():
                raise ValueError("method-card content hash mismatch")
        library_version = str(manifest.get("library_version", "")).strip()
        if not library_version:
            raise ValueError("method-card library version is required")
        return cards, store_hash, library_version
