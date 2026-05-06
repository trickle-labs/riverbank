"""Post-extraction quality strategies for riverbank.

Post-processing runs *after* ``load_triples_with_confidence()`` has written
triples to pg_ripple.  Each strategy improves graph quality without requiring
a full re-extraction pass.

Available strategies:

* **Post-1: Embedding-Based Entity Deduplication** (``dedup`` module)
  Embeds entity IRI labels, clusters by cosine similarity, and emits
  ``owl:sameAs`` links to canonicalise cross-document entity references.

* **Post-2: Self-Critique Verification Pass** (``verify`` module)
  Re-evaluates low-confidence triples with a cheap second LLM call.
  Confirmed triples get a confidence boost; rejected triples are
  quarantined for human review.
"""
from __future__ import annotations

from riverbank.postprocessors.dedup import DeduplicationResult, EntityDeduplicator
from riverbank.postprocessors.verify import VerificationPass, VerificationResult

__all__ = [
    "DeduplicationResult",
    "EntityDeduplicator",
    "VerificationPass",
    "VerificationResult",
]
