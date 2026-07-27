from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from math import log2
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "config" / "secret_scan_allowlist.json"
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])" + "s" + "k-" + r"(?P<value>[A-Za-z0-9_-]{20,})"
)
_BEARER_PATTERN = re.compile(
    r"\b" + "Bearer" + r"\s+(?P<value>[A-Za-z0-9._~+/=-]{20,})",
    re.IGNORECASE,
)
_INTERN_PATTERN = re.compile(
    r"\b"
    + "intern"
    + r"(?:lm)?[_-](?:api[_-]?)?(?:key|token)"
    + r"\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9._~+/=-]{20,})",
    re.IGNORECASE,
)
_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key)"
    r"\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9._~+/=-]{20,})",
    re.IGNORECASE,
)
_HIGH_ENTROPY_PATTERN = re.compile(
    r"(?P<quote>[\"'])(?P<value>[A-Za-z0-9_+/=-]{40,})(?P=quote)"
)
_HEX_DIGEST = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str


def scan_repository(root: Path = ROOT) -> list[SecretFinding]:
    allowlist = _load_allowlist(root)
    findings: list[SecretFinding] = []
    seen: set[tuple[str, int, str]] = set()
    for path in _candidate_files(root):
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if b"\0" in content:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()
        for kind, pattern in (
            ("api_token", _TOKEN_PATTERN),
            ("bearer_token", _BEARER_PATTERN),
            ("intern_token", _INTERN_PATTERN),
            ("api_key_assignment", _ASSIGNMENT_PATTERN),
        ):
            for match in pattern.finditer(text):
                _record_finding(
                    findings,
                    seen,
                    allowlist,
                    relative,
                    text,
                    match,
                    kind,
                )
        for match in _HIGH_ENTROPY_PATTERN.finditer(text):
            value = match.group("value")
            if _HEX_DIGEST.fullmatch(value) or _entropy(value) < 4.2:
                continue
            _record_finding(
                findings,
                seen,
                allowlist,
                relative,
                text,
                match,
                "high_entropy_string",
            )
    return findings


def _record_finding(
    findings: list[SecretFinding],
    seen: set[tuple[str, int, str]],
    allowlist: set[tuple[str, str, str]],
    relative: str,
    text: str,
    match: re.Match[str],
    kind: str,
) -> None:
    value = match.groupdict().get("value", match.group(0))
    digest = sha256(value.encode("utf-8")).hexdigest()
    if (relative, kind, digest) in allowlist:
        return
    line = text.count("\n", 0, match.start()) + 1
    key = (relative, line, kind)
    if key not in seen:
        seen.add(key)
        findings.append(SecretFinding(relative, line, kind))


def _load_allowlist(root: Path) -> set[tuple[str, str, str]]:
    path = root / "config" / "secret_scan_allowlist.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    result: set[tuple[str, str, str]] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("path")
        kind = entry.get("kind")
        digest = entry.get("value_sha256")
        if (
            isinstance(relative, str)
            and isinstance(kind, str)
            and isinstance(digest, str)
            and len(digest) == 64
        ):
            result.add((relative, kind, digest.lower()))
    return result


def _entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * log2(count / length)
        for count in counts.values()
    )


def _candidate_files(root: Path) -> list[Path]:
    try:
        output = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", errors="surrogateescape")
    except (OSError, subprocess.CalledProcessError):
        return sorted(path for path in root.rglob("*") if path.is_file())
    return [root / relative for relative in output.split("\0") if relative]


def main() -> int:
    findings = scan_repository()
    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}:{finding.line}")
        return 1
    print("Secret pattern scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
