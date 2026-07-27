from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])" + "s" + "k-" + r"[A-Za-z0-9_-]{20,}"
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str


def scan_repository(root: Path = ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
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
        for match in _TOKEN_PATTERN.finditer(text):
            findings.append(
                SecretFinding(
                    path=path.relative_to(root).as_posix(),
                    line=text.count("\n", 0, match.start()) + 1,
                    kind="api_token",
                )
            )
    return findings


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
