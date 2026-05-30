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
    explain: bool = False,
) -> float | dict:
    """Calculate a source-specific score for Coursera candidates without using fake metadata."""
    title_lower = title.lower()
    tag_lower = tag.lower()

    score = 0.0
    scoreBreakdown = {}
    reasonCodes = []

    if tag_lower in title_lower:
        score += 50
        scoreBreakdown["titleMatch"] = 50.0
        reasonCodes.append("title_exact_tag_match")

    tag_words = [word for word in tag_lower.split() if len(word) > 2]
    if tag_words:
        matched = sum(1 for word in tag_words if word in title_lower)
        overlap_score = 30.0 * (matched / len(tag_words))
        score += overlap_score
        if overlap_score > 0:
            scoreBreakdown["wordOverlap"] = overlap_score
            reasonCodes.append("tag_word_overlap")

    source_type = detect_coursera_type(url)

    type_bonus = 0.0
    if source_type == "professional_certificate":
        type_bonus = 12.0
    elif source_type == "specialization":
        type_bonus = 10.0
    elif source_type == "course":
        type_bonus = 8.0
    elif source_type == "project":
        type_bonus = 5.0

    if type_bonus > 0:
        score += type_bonus
        scoreBreakdown["typeBonus"] = type_bonus
        reasonCodes.append("type_bonus")

    pos_bonus = float(max(0, 10 - search_position))
    score += pos_bonus
    if pos_bonus > 0:
        scoreBreakdown["searchPositionBonus"] = pos_bonus
        reasonCodes.append("search_position_bonus")

    # Native Arabic bonus
    has_arabic_char = any(ord(char) >= 0x0600 and ord(char) <= 0x06FF for char in title)
    if has_arabic_char:
        score += 15.0
        scoreBreakdown["arabicBonus"] = 15.0
        reasonCodes.append("arabic_title_bonus")

    final_score = max(score, 0.0)
    if score < 0.0:
        reasonCodes.append("score_floor_applied")
        scoreBreakdown["capAdjustment"] = -score

    if explain:
        return {
            "score": final_score,
            "explanation": {
                "finalScore": final_score,
                "source": "coursera",
                "sourceType": source_type,
                "reasonCodes": reasonCodes,
                "scoreBreakdown": scoreBreakdown
            }
        }

    return final_score


def cheap_rank_candidate(candidate: Candidate, tag: str, explain: bool = False) -> float | dict:
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
            explain=explain,
        )

    if candidate.source == SourceName.UDEMY:
        from src.utils.scoring import calculate_udemy_score
        return calculate_udemy_score(candidate.metadata, tag, explain=explain)

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

    pre_penalty_score = base_score + relevance_boost + duration_boost + rating_boost
    final_score_uncapped = pre_penalty_score * penalty
    final_score = max(final_score_uncapped, 0.0)

    if explain:
        scoreBreakdown = {
            "baseScore": float(base_score),
        }
        reasonCodes = []

        if relevance_boost > 0:
            scoreBreakdown["relevanceBoost"] = float(relevance_boost)
            if overlap > 0:
                reasonCodes.append("tag_word_overlap")
            if tag_lower in title_lower:
                reasonCodes.append("title_exact_tag_match")

        if duration_boost > 0:
            scoreBreakdown["durationBoost"] = float(duration_boost)
            if candidate.duration_minutes > 120:
                reasonCodes.append("long_duration_boost")
            elif candidate.duration_minutes > 60:
                reasonCodes.append("medium_duration_boost")

        if rating_boost > 0:
            scoreBreakdown["ratingBoost"] = float(rating_boost)
            reasonCodes.append("high_rating_boost")

        if penalty != 1.0:
            # Trace reasons for penalty
            for kw in negative_keywords:
                if kw in title_lower:
                    reasonCodes.append("negative_keyword_penalty")
            if candidate.duration_minutes and candidate.duration_minutes < 10:
                reasonCodes.append("short_duration_penalty")
            if candidate.rating and candidate.rating < 4.0:
                reasonCodes.append("low_rating_penalty")

            penalty_adjustment = final_score - pre_penalty_score
            scoreBreakdown["penaltyAdjustment"] = float(penalty_adjustment)

        if final_score_uncapped < 0.0:
            reasonCodes.append("score_floor_applied")
            scoreBreakdown["capAdjustment"] = -final_score_uncapped

        explanation = {
            "finalScore": final_score,
            "source": candidate.source.value if hasattr(candidate.source, "value") else str(candidate.source),
            "reasonCodes": reasonCodes,
            "scoreBreakdown": scoreBreakdown
        }
        if penalty != 1.0:
            explanation["penaltyMultiplier"] = float(penalty)

        return {
            "score": final_score,
            "explanation": explanation
        }

    return final_score


def cheap_rank(candidates: list[Candidate], tag: str) -> list[Candidate]:
    """Calculate scores for candidates, update their raw_score attribute, and sort descending."""
    import os
    explain = os.environ.get("ENABLE_RANKING_DEBUG", "").lower() == "true"

    scored_candidates = []
    for c in candidates:
        if explain:
            res = cheap_rank_candidate(c, tag, explain=True)
            c.raw_score = res["score"]
            c.ranking_explanation = res["explanation"]
        else:
            score = cheap_rank_candidate(c, tag, explain=False)
            c.raw_score = score
            c.ranking_explanation = None
        scored_candidates.append(c)

    return sorted(scored_candidates, key=lambda x: x.raw_score, reverse=True)

