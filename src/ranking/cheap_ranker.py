import math
import re
from src.engine.models import Candidate, SourceName, TopicScope


def detect_coursera_type(url: str) -> str:
    url_lower = url.lower()
    if (
        "/professional-certificates/" in url_lower
        or "/professional-certificate/" in url_lower
    ):
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
                "scoreBreakdown": scoreBreakdown,
            },
        }

    return final_score


def cheap_rank_candidate(
    candidate: Candidate,
    tag: str,
    scope: TopicScope = TopicScope.UNKNOWN,
    explain: bool = False,
) -> float | dict:
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

    # YouTube relevance and quality scoring
    base_score = candidate.raw_score or 0.0
    boosts = 0.0
    scoreBreakdown = {"baseScore": float(base_score)}
    reasonCodes = []
    penalty = 1.0

    # 1. Title matching
    tag_clean = re.sub(r"[^\w\s]", " ", tag_lower)
    title_clean = re.sub(r"[^\w\s]", " ", title_lower)
    tag_words = set(tag_clean.split())
    title_words = set(title_clean.split())

    # Remove filler words from tag/title overlap
    filler_words = {
        "full",
        "course",
        "tutorial",
        "complete",
        "beginner",
        "beginners",
        "learn",
    }
    tag_words_clean = tag_words - filler_words
    title_words_clean = title_words - filler_words

    overlap = len(tag_words_clean.intersection(title_words_clean))
    relevance_boost = overlap * 5.0
    if tag_lower in title_lower:
        relevance_boost += 10.0
        reasonCodes.append("title_exact_tag_match")
    if overlap > 0:
        reasonCodes.append("tag_word_overlap")

    if relevance_boost > 0:
        boosts += relevance_boost
        scoreBreakdown["relevanceBoost"] = float(relevance_boost)

    # 2. Description relevance
    if candidate.description:
        desc_lower = candidate.description.lower()
        if tag_lower in desc_lower:
            boosts += 5.0
            scoreBreakdown["descriptionMatchBoost"] = 5.0
            reasonCodes.append("description_tag_match")

    # 3. Negative keywords (distractor terms) penalty
    negative_keywords = [
        "scam",
        "clickbait",
        "reaction",
        "review",
        "trailer",
        "teaser",
        "syllabus",
        "shorts",
        "reels",
        "tiktok",
        "meme",
        "news",
        "podcast",
        "livestream",
        "motivation",
        "interview only",
    ]
    for kw in negative_keywords:
        if kw in title_lower:
            mult = (
                0.6
                if kw
                in (
                    "scam",
                    "clickbait",
                    "reaction",
                    "review",
                    "trailer",
                    "teaser",
                    "syllabus",
                )
                else 0.4
            )
            penalty *= mult
            reasonCodes.append("negative_keyword_penalty")

    # 4. Duration fit (triage short/long content)
    if candidate.duration_minutes is not None:
        if candidate.duration_minutes > 120:  # > 2 hours
            boosts += 15.0
            scoreBreakdown["durationBoost"] = 15.0
            reasonCodes.append("long_duration_boost")
        elif candidate.duration_minutes > 60:  # > 1 hour
            boosts += 10.0
            scoreBreakdown["durationBoost"] = 10.0
            reasonCodes.append("medium_duration_boost")
        elif candidate.duration_minutes < 10:  # < 10 mins (too short for full topics)
            # Only penalize if not debugging or atomic scope
            if scope not in (TopicScope.DEBUGGING_QUERY, TopicScope.ATOMIC):
                penalty *= 0.5
                reasonCodes.append("short_duration_penalty")

    # 5. Rating fit
    if candidate.rating is not None:
        if candidate.rating >= 4.5:
            boosts += 10.0
            scoreBreakdown["ratingBoost"] = 10.0
            reasonCodes.append("high_rating_boost")
        elif candidate.rating < 4.0:
            penalty *= 0.7
            reasonCodes.append("low_rating_penalty")

    # 6. Scope fit (playlist vs video preference)
    is_playlist = (
        (candidate.metadata.get("content_type") == "playlist")
        or ("playlist" in candidate.url)
        or ("list=" in candidate.url)
    )

    if scope in (
        TopicScope.ROLE_ROADMAP,
        TopicScope.TECHNOLOGY,
        TopicScope.SKILL_TOPIC,
    ):
        if is_playlist:
            boosts += 25.0
            scoreBreakdown["scopeFitBoost"] = 25.0
            reasonCodes.append("playlist_preferred_for_broad_scope")
        else:
            # For broad scope, short video is penalized
            if (
                candidate.duration_minutes is not None
                and candidate.duration_minutes < 30
            ):
                penalty *= 0.8
                reasonCodes.append("short_video_broad_scope_penalty")
    elif scope in (
        TopicScope.ATOMIC,
        TopicScope.DEBUGGING_QUERY,
        TopicScope.COMPARISON_QUERY,
        TopicScope.PROJECT_GOAL,
    ):
        if is_playlist:
            # Specific queries prefer videos, penalize playlist unless exact tag match in title
            if tag_lower not in title_lower:
                penalty *= 0.5
                reasonCodes.append("playlist_specific_scope_penalty")
        else:
            boosts += 10.0
            scoreBreakdown["scopeFitBoost"] = 10.0
            reasonCodes.append("video_preferred_for_specific_scope")

    # 7. View/like metrics logarithmic boost
    if candidate.view_count is not None and candidate.view_count > 0:
        view_boost = math.log10(candidate.view_count + 1) * 1.5
        boosts += view_boost
        scoreBreakdown["viewCountBoost"] = float(view_boost)
    if candidate.like_count is not None and candidate.like_count > 0:
        like_boost = math.log10(candidate.like_count + 1) * 1.0
        boosts += like_boost
        scoreBreakdown["likeCountBoost"] = float(like_boost)

    pre_penalty_score = base_score + boosts
    final_score = pre_penalty_score * penalty

    if penalty != 1.0:
        scoreBreakdown["penaltyAdjustment"] = float(final_score - pre_penalty_score)

    if explain:
        explanation = {
            "finalScore": final_score,
            "source": (
                candidate.source.value
                if hasattr(candidate.source, "value")
                else str(candidate.source)
            ),
            "reasonCodes": reasonCodes,
            "scoreBreakdown": scoreBreakdown,
        }
        if penalty != 1.0:
            explanation["penaltyMultiplier"] = float(penalty)
        return {"score": final_score, "explanation": explanation}

    return final_score


def cheap_rank(
    candidates: list[Candidate],
    tag: str,
    scope: TopicScope = TopicScope.UNKNOWN,
) -> list[Candidate]:
    """Calculate scores for candidates, update their raw_score attribute, and sort descending."""
    import os

    explain = os.environ.get("ENABLE_RANKING_DEBUG", "").lower() == "true"

    scored_candidates = []
    for c in candidates:
        if explain:
            res = cheap_rank_candidate(c, tag, scope=scope, explain=True)
            c.raw_score = res["score"]
            c.ranking_explanation = res["explanation"]
        else:
            score = cheap_rank_candidate(c, tag, scope=scope, explain=False)
            c.raw_score = score
            c.ranking_explanation = None
        scored_candidates.append(c)

    return sorted(scored_candidates, key=lambda x: x.raw_score, reverse=True)
