from pathlib import Path

from scripts.verify_baseline_files import ROOT, git_blob_sha, verify


def test_immutable_official_files_match_manifest() -> None:
    assert verify() == []


def test_official_user_agent_snapshot_is_preserved() -> None:
    snapshot = ROOT / "baseline_snapshot" / "user_agent_official.py"
    assert git_blob_sha(snapshot) == "b230a6d427b0c6908c9533f2bc67838dbd9257a1"


def test_baseline_sources_compile() -> None:
    for relative_path in (
        "main.py",
        "llm_client.py",
        "baseline_snapshot/user_agent_official.py",
    ):
        source = (Path(ROOT) / relative_path).read_text(encoding="utf-8")
        compile(source, relative_path, "exec")
