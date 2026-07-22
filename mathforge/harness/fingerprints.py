from __future__ import annotations

from hashlib import sha256


def request_fingerprint(problem: str, nonce: str) -> str:
    payload = f"{nonce}\0{problem}".encode("utf-8")
    return sha256(payload).hexdigest()
