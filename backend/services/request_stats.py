"""Reference-only stats over past requests — not part of the generation pipeline.

Backs wayfinder map #1's ticket #5 decision: the wizard's "แนว" step shows how many past
requests included a decoration from each category, purely as information for the person
choosing — it is never read back into any filter or the Auto-mode pick logic.
"""

from backend.models import request_log
from backend.services import catalog


def category_counts(conn, limit=10_000):
    """category -> how many past requests included at least one decoration in it.

    10_000 stands in for "the whole log" the same way api_catalog_categories() already reads
    10_000 rows to mean "the whole catalogue" — this is a single-user internal tool, not a
    scale that needs paging.
    """
    counts = {}
    for row in request_log.recent(conn, limit=limit):
        seen_categories = set()
        for element in request_log.elements_of(row):
            code = element.get("code")
            if not code:
                continue
            try:
                product = catalog.find(code)
            except Exception:
                continue
            category = catalog.category_of(product)
            if category:
                seen_categories.add(category)
        for category in seen_categories:
            counts[category] = counts.get(category, 0) + 1
    return counts
