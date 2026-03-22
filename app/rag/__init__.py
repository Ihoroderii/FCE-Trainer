"""RAG (Retrieval-Augmented Generation) for FCE task generation.

Stores reference FCE examples with embeddings, retrieves the most similar
ones for a given request, and injects them into the generation prompt so
the model produces tasks that match real exam style.

Usage:
    from app.rag import retrieve_examples

    examples = retrieve_examples(paper="use_of_english", part=1, topic="travel")
    # Returns list of example dicts (empty if no examples stored yet)
"""

from app.rag.retrieval import retrieve_examples

__all__ = ["retrieve_examples"]
