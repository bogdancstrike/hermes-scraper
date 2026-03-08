"""
Field-level confidence merging for multi-source extraction.

Each extraction source has a pre-assigned confidence score per field.
pick_field() selects the first non-empty value from the ordered source list.
"""
from __future__ import annotations

# (source_name, confidence_score) ordered by priority per field
FIELD_SOURCES: dict[str, list[tuple[str, float]]] = {
    "title": [
        ("jsonld", 0.98), ("trafilatura", 0.92), ("og", 0.82),
        ("readability", 0.65),
    ],
    "author": [
        ("jsonld", 0.95), ("trafilatura", 0.86), ("og", 0.70),
    ],
    "date": [
        ("jsonld", 0.95), ("htmldate", 0.90), ("trafilatura", 0.86),
        ("og", 0.78),
    ],
    "summary": [
        ("jsonld", 0.90), ("og", 0.82), ("trafilatura", 0.75),
    ],
    "content": [
        ("trafilatura", 0.95), ("readability", 0.65),
    ],
    "canonical_url": [
        ("og", 0.90), ("jsonld", 0.88),
    ],
    "top_image": [
        ("jsonld", 0.90), ("og", 0.85),
    ],
    "language": [
        ("trafilatura", 0.90), ("og", 0.70),
    ],
    "publisher": [
        ("jsonld", 0.95),
    ],
    "tags": [
        ("jsonld", 0.90), ("og", 0.75),
    ],
}


def pick_field(
    field: str,
    sources: dict[str, dict],
) -> tuple[str | None, str, float]:
    """
    Pick the best value for a field from multiple extraction sources.

    Args:
        field:   Field name (e.g. "title", "author").
        sources: Dict mapping source_name → extracted dict from that source.

    Returns:
        (value, source_name, confidence) tuple.
        value is None if no source provided a non-empty value.
    """
    priority = FIELD_SOURCES.get(field, [])
    for source_name, confidence in priority:
        src_data = sources.get(source_name, {})
        value = src_data.get(field)
        if value and str(value).strip():
            return value, source_name, confidence
    # Fallback: try any source in order
    for source_name, src_data in sources.items():
        value = src_data.get(field)
        if value and str(value).strip():
            return value, source_name, 0.5
    return None, "", 0.0


def merge_fields(sources: dict[str, dict]) -> tuple[dict, dict, dict]:
    """
    Merge all fields from multiple sources using confidence priority.

    Args:
        sources: Dict mapping source_name → extracted dict.

    Returns:
        (merged_data, field_sources, field_confidence)
        merged_data: field → best value
        field_sources: field → source name that provided the value
        field_confidence: field → confidence score
    """
    fields = list(FIELD_SOURCES.keys())
    merged: dict = {}
    fsources: dict[str, str] = {}
    fconfidence: dict[str, float] = {}

    for field in fields:
        value, source, confidence = pick_field(field, sources)
        merged[field] = value
        if source:
            fsources[field] = source
            fconfidence[field] = confidence

    return merged, fsources, fconfidence
