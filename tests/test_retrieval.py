from __future__ import annotations

from pathlib import Path

from mathforge.retrieval.builder import build_database
from mathforge.retrieval.retriever import Retriever
from mathforge.retrieval.schemas import KnowledgeCard


def _card(identifier: str, trust: str, statement: str) -> KnowledgeCard:
    return KnowledgeCard(
        identifier,
        "algebra",
        "procedure",
        "Equation checking",
        statement,
        ["equation"],
        [],
        ["extraneous root"],
        "test_fixture",
        "tests/test_retrieval.py",
        trust,
    )


def test_retrieval_filters_trust_and_preserves_sources(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite"
    build_database(
        database,
        [
            _card("reviewed", "reviewed", "Check equation roots."),
            _card("conflicted", "conflicted", "Conflicted equation advice."),
        ],
    )
    solver = Retriever(database).retrieve("equation extraneous root", subject="algebra")
    assert [card.id for card in solver] == ["reviewed"]
    assert solver[0].source_ref
    skeptic = Retriever(database).retrieve(
        "equation advice", subject="algebra", role="VerifierSkeptic"
    )
    assert {card.id for card in skeptic} == {"reviewed", "conflicted"}


def test_missing_database_degrades_to_empty_result(tmp_path: Path):
    assert Retriever(tmp_path / "missing.sqlite").retrieve("equation") == []


def test_top_k_is_bounded(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite"
    build_database(
        database,
        [_card(f"c{index}", "reviewed", f"Equation rule {index}") for index in range(10)],
    )
    assert len(Retriever(database, max_top_k=3).retrieve("equation", top_k=10)) == 3
