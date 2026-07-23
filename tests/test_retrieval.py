from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mathforge.retrieval.builder import build_database, load_cards
from mathforge.retrieval.retriever import Retriever
from mathforge.retrieval.schemas import KnowledgeCard


def _card(identifier: str, trust: str, statement: str) -> KnowledgeCard:
    card = KnowledgeCard(
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
        "test-fixture-v1",
        "test-maintainer",
        "2026-07-23",
    )
    return replace(card, content_hash=card.computed_content_hash())


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


def test_composite_rank_preserves_trust_condition_and_bm25(tmp_path: Path):
    database = tmp_path / "rank.sqlite"
    weak = _card("a-weak", "reviewed", "General equation advice.")
    exact = _card(
        "z-exact",
        "verified",
        "Use exactterm exactterm when checking this equation.",
    )
    reviewed_exact = _card(
        "b-reviewed-exact",
        "reviewed",
        "Use exactterm exactterm exactterm for an equation.",
    )
    build_database(database, [weak, exact, reviewed_exact])

    hits = Retriever(database).search(
        "equation exactterm",
        subject="algebra",
        top_k=3,
    )

    assert [hit.card.id for hit in hits] == [
        "z-exact",
        "b-reviewed-exact",
        "a-weak",
    ]
    assert hits[0].trust_priority < hits[1].trust_priority
    assert hits[1].condition_score == hits[2].condition_score
    assert hits[1].bm25_score < hits[2].bm25_score


def test_retrieval_closes_database_before_returning(tmp_path: Path):
    database = tmp_path / "movable.sqlite"
    build_database(database, [_card("reviewed", "reviewed", "Equation rule.")])
    assert Retriever(database).retrieve("equation")

    moved = tmp_path / "moved.sqlite"
    database.rename(moved)
    moved.unlink()
    assert not moved.exists()


def test_builder_rejects_stale_content_hash_before_replacing_database(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite"
    valid = _card("valid", "reviewed", "Equation rule.")
    build_database(database, [valid])
    stale = replace(valid, statement="Changed without review")

    with pytest.raises(ValueError, match="content hash mismatch"):
        build_database(database, [stale])

    assert database.exists()


def test_production_cards_have_versioned_review_records():
    root = Path(__file__).resolve().parents[1]
    cards = load_cards(root / "data" / "knowledge_cards.json")

    assert cards
    assert all(card.source_version for card in cards)
    assert all(card.reviewer == "project-maintainer" for card in cards)
    assert all(card.review_date == "2026-07-23" for card in cards)
    assert all(card.content_hash == card.computed_content_hash() for card in cards)
