from src.engine.models import Candidate, SourceName


def calculate_coursera_score(
    title: str,
    tag: str,
    url: str,
    search_position: int,
    is_native_arabic: bool = False,
    platform: str = "Coursera",
) -> float:
    """Calculate a source-specific score for Coursera candidates without using fake metadata."""
    # Base score from search position (lower position = better/more relevant)
    position_score = max(5.0, 20.0 - (search_position * 2.0))

    title_lower = title.lower()
    tag_lower = tag.lower()

    # Title relevance
    if tag_lower in title_lower:
        relevance_boost = 15.0
    else:
        # Word overlap
        tag_words = set(tag_lower.split())
        title_words = set(title_lower.split())
        overlap = len(tag_words.intersection(title_words))
        relevance_boost = overlap * 4.0

    # URL type scoring
    url_lower = url.lower()
    url_type_score = 10.0  # default for course/learn
    if "professional-certificates" in url_lower:
        url_type_score = 25.0
    elif "specializations" in url_lower:
        url_type_score = 20.0
    elif "projects" in url_lower:
        url_type_score = 5.0

    # Native Arabic bonus
    arabic_bonus = 15.0 if is_native_arabic else 0.0

    # Negative keywords penalty
    negative_keywords = ["review", "scam", "intro only", "trailer", "syllabus"]
    penalty = 1.0
    for kw in negative_keywords:
        if kw in title_lower:
            penalty *= 0.5

    final_score = (
        position_score + relevance_boost + url_type_score + arabic_bonus
    ) * penalty
    return final_score


def cheap_rank_candidate(candidate: Candidate, tag: str) -> float:
    """Calculate a relevance/quality score for a Candidate based on metadata and rules."""
    title_lower = candidate.title.lower()
    tag_lower = tag.lower()

    if candidate.source == SourceName.COURSERA:
        search_position = candidate.metadata.get("search_position", 0)
        is_native_arabic = candidate.metadata.get("is_native_arabic", False)
        return calculate_coursera_score(
            title=candidate.title,
            tag=tag,
            url=candidate.url,
            search_position=search_position,
            is_native_arabic=is_native_arabic,
            platform=candidate.channel_or_provider or "Coursera",
        )

    # Baseline score for YouTube/Udemy is their raw_score
    base_score = candidate.raw_score

    # Tag-word match boost
    tag_words = set(tag_lower.split())
    title_words = set(title_lower.split())
    overlap = len(tag_words.intersection(title_words))
    relevance_boost = overlap * 5.0

    if tag_lower in title_lower:
        relevance_boost += 10.0

    # Negative keywords penalty
    negative_keywords = [
        "scam",
        "clickbait",
        "reaction",
        "review",
        "trailer",
        "teaser",
        "syllabus",
    ]
    penalty = 1.0
    for kw in negative_keywords:
        if kw in title_lower:
            penalty *= 0.6

    # Duration fit
    duration_boost = 0.0
    if candidate.duration_minutes:
        if candidate.duration_minutes > 120:  # > 2 hours
            duration_boost = 15.0
        elif candidate.duration_minutes > 60:  # > 1 hour
            duration_boost = 10.0
        elif candidate.duration_minutes < 10:  # < 10 mins (very short)
            penalty *= 0.5

    # Rating fit
    rating_boost = 0.0
    if candidate.rating:
        if candidate.rating >= 4.5:
            rating_boost = 10.0
        elif candidate.rating < 4.0:
            penalty *= 0.7

    final_score = (
        base_score + relevance_boost + duration_boost + rating_boost
    ) * penalty
    return final_score


def cheap_rank(candidates: list[Candidate], tag: str) -> list[Candidate]:
    """Calculate scores for candidates, update their raw_score attribute, and sort descending."""
    scored_candidates = []
    for c in candidates:
        score = cheap_rank_candidate(c, tag)
        c.raw_score = score
        scored_candidates.append(c)

    return sorted(scored_candidates, key=lambda x: x.raw_score, reverse=True)
