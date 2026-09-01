from __future__ import annotations

from pathlib import Path

from scripts.check_complexity_budget import (
    MAX_MATHFORGE_SOURCE_LINES,
    count_source_lines,
)


def test_complexity_gate_counts_only_nonblank_python_lines(tmp_path: Path) -> None:
    source = tmp_path / "mathforge"
    source.mkdir()
    (source / "module.py").write_text("\n# comment\nvalue = 1\n", encoding="utf-8")
    (source / "notes.txt").write_text("not python\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")

    assert count_source_lines(source) == 2


def test_complexity_policy_is_stricter_than_historical_65k_baseline() -> None:
    assert MAX_MATHFORGE_SOURCE_LINES == 55_000
    assert MAX_MATHFORGE_SOURCE_LINES < 65_315
