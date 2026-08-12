from mathforge.retrieval.schemas import KnowledgeCard, SearchHit

__all__ = [
    "KnowledgeCard",
    "Retriever",
    "ReviewedMethodCardStore",
    "SearchHit",
]


def __getattr__(name: str):
    """Keep optional retrieval implementations out of the online hot path."""
    if name == "Retriever":
        from mathforge.retrieval.retriever import Retriever

        return Retriever
    if name == "ReviewedMethodCardStore":
        from mathforge.retrieval.method_card_store import ReviewedMethodCardStore

        return ReviewedMethodCardStore
    raise AttributeError(name)
