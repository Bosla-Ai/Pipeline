from src.engine.models import Candidate, SourceName


def detect_coursera_type(url: str) -> str:
    url_lower = url.lower()
    if "/professional-certificates/" in url_lower or "/professional-certificate/" in url_lower:
        return "professional_certificate"
    if "/specializations/" in url_lower or "/specialization/" in url_lower:
        return "specialization"
    if "/projects/" in url_lower or "/project/" in url_lower:
        return "project"
    if "/learn/" in url_lower or "/course/" in url_lower:
        return "course"
    return "unknown"


def calculate_coursera_score(
    title: str,
    tag: str,
    url: str,
    search_position: int,
) -> float:
    """Calculate a source-specific score for Coursera candidates without using fake metadata."""
    title_lower = title.lower()
    tag_lower = tag.lower()

    score = 0.0

    if tag_lower in title_lower:
        score += 50

    tag_words = [word for word in tag_lower.split() if len(word) > 2]
    if tag_words:
        matched = sum(1 for word in tag_words if word in title_lower)
        score += 30 * (matched / len(tag_words))

    source_type = detect_coursera_type(url)

    if source_type == "professional_certificate":
        score += 12
    elif source_type == "specialization":
        score += 10
    elif source_type == "course":
        score += 8
    elif source_type == "project":
        score += 5

    score += max(0, 10 - search_position)

    # Native Arabic bonus
    has_arabic_char = any(ord(char) >= 0x0600 and ord(char) <= 0x06FF for char in title)
    if has_arabic_char:
        score += 15.0

    return score


def cheap_rank_candidate(candidate: Candidate, tag: str) -> float:
    """Calculate a relevance/quality score for a Candidate based on metadata and rules."""
    title_lower = candidate.title.lower()
    tag_lower = tag.lower()

    if candidate.source == SourceName.COURSERA:
        search_position = candidate.metadata.get("searchPosition")
        if search_position is None:
            search_position = candidate.metadata.get("search_position", 0)
        return calculate_coursera_score(
            title=candidate.title,
            tag=tag,
            url=candidate.url,
            search_position=search_position,
        )

    if candidate.source == SourceName.UDEMY:
        from src.utils.scoring import calculate_udemy_score
        return calculate_udemy_score(candidate.metadata, tag)

    # Baseline score for YouTube is its raw_score
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
