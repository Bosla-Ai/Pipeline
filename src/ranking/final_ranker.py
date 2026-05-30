import os
import urllib.parse
from src.engine.models import Candidate, SourceName, TopicScope
from src.engine.stages import PreparedTag
from src.inference.schemas import ClassificationResult
from src.security.url_policy import is_valid_url
from src.ranking.dedupe import token_set_jaccard


def calculate_final_score(
    candidate: Candidate,
    tag: PreparedTag,
    cheap_score: float,
    ai_result: ClassificationResult | None = None,
    explain: bool = False,
) -> float | dict:
    """
    Calculate final normalized score based on weighted factors and penalties.
    """
    if not candidate.title or not candidate.title.strip():
        return -999.0
    if not candidate.url or not is_valid_url(candidate.url):
        return -999.0

    # title_relevance
    title_relevance = token_set_jaccard(candidate.title, tag.normalized)
    title_relevance = max(0.0, min(1.0, title_relevance))

    # cheap_rank_score
    cheap_rank_score = max(0.0, min(1.0, cheap_score / 100.0))

    # scope_content_type_fit
    is_playlist = (
        (candidate.metadata.get("content_type") == "playlist")
        or ("playlist" in candidate.url)
        or ("list=" in candidate.url)
    )

    if tag.scope in (
        TopicScope.ROLE_ROADMAP,
        TopicScope.TECHNOLOGY,
        TopicScope.SKILL_TOPIC,
    ):
        if is_playlist:
            scope_content_type_fit = 1.0
        elif (
            candidate.duration_minutes is not None and candidate.duration_minutes >= 45
        ):
            scope_content_type_fit = 0.7
        else:
            scope_content_type_fit = 0.2
    elif tag.scope in (
        TopicScope.ATOMIC,
        TopicScope.DEBUGGING_QUERY,
        TopicScope.COMPARISON_QUERY,
        TopicScope.PROJECT_GOAL,
    ):
        if not is_playlist:
            scope_content_type_fit = 1.0
        else:
            if tag.normalized.lower() in candidate.title.lower():
                scope_content_type_fit = 0.8
            else:
                scope_content_type_fit = 0.1
    else:
        scope_content_type_fit = 0.5

    # language_fit
    title_lower = candidate.title.lower()
    has_arabic_char = any(
        ord(char) >= 0x0600 and ord(char) <= 0x06FF for char in title_lower
    )
    req_lang = tag.language.lower() if tag.language else "en"
    if req_lang == "ar":
        if has_arabic_char or candidate.language == "ar":
            language_fit = 1.0
        else:
            language_fit = 0.2
    else:
        if has_arabic_char:
            language_fit = 0.3
        else:
            language_fit = 1.0

    # source_quality
    if candidate.source == SourceName.COURSERA:
        source_quality = 1.0
    elif candidate.source == SourceName.UDEMY:
        source_quality = 0.9
    else:
        source_quality = 0.8

    # Weights setup
    has_ai = ai_result is not None
    if has_ai:
        weights = {
            "title_relevance": 0.35,
            "cheap_rank_score": 0.20,
            "scope_content_type_fit": 0.15,
            "language_fit": 0.10,
            "source_quality": 0.10,
            "ai_relevance": 0.10,
        }
        ai_relevance = 1.0 if ai_result.label == "relevant" else 0.0
        ai_relevance *= ai_result.confidence
    else:
        weights = {
            "title_relevance": 0.40,
            "cheap_rank_score": 0.23,
            "scope_content_type_fit": 0.17,
            "language_fit": 0.10,
            "source_quality": 0.10,
            "ai_relevance": 0.0,
        }
        ai_relevance = 0.0

    # Score calculation
    weighted_score = (
        weights["title_relevance"] * title_relevance
        + weights["cheap_rank_score"] * cheap_rank_score
        + weights["scope_content_type_fit"] * scope_content_type_fit
        + weights["language_fit"] * language_fit
        + weights["source_quality"] * source_quality
        + weights["ai_relevance"] * ai_relevance
    )

    # Penalties
    penalties = 0.0
    penalty_details = []

    # shorts/reels/tiktok
    for term in ("shorts", "reels", "tiktok"):
        if term in title_lower:
            penalties += 0.5
            penalty_details.append(f"title_contains_{term}")

    # very_short_duration_for_course
    if tag.scope in (
        TopicScope.ROLE_ROADMAP,
        TopicScope.TECHNOLOGY,
        TopicScope.SKILL_TOPIC,
    ):
        if candidate.duration_minutes is not None and candidate.duration_minutes < 15:
            penalties += 0.3
            penalty_details.append("very_short_duration_for_broad_scope")

    # low_title_relevance
    if title_relevance < 0.2:
        penalties += 0.3
        penalty_details.append("low_title_relevance")

    # ai_unrelated_high_confidence
    if has_ai and ai_result.label != "relevant" and ai_result.confidence >= 0.7:
        penalties += 0.4
        penalty_details.append("ai_unrelated_high_confidence")

    final_score = weighted_score - penalties
    final_score = max(0.0, final_score)

    if explain:
        score_breakdown = {
            "weighted_score": weighted_score,
            "penalties": penalties,
            "features": {
                "title_relevance": title_relevance,
                "cheap_rank_score": cheap_rank_score,
                "scope_content_type_fit": scope_content_type_fit,
                "language_fit": language_fit,
                "source_quality": source_quality,
                "ai_relevance": ai_relevance if has_ai else None,
            },
            "weights": weights,
            "penalty_details": penalty_details,
        }
        explanation = {
            "finalScore": final_score,
            "source": (
                candidate.source.value
                if hasattr(candidate.source, "value")
                else str(candidate.source)
            ),
            "scoreBreakdown": score_breakdown,
        }
        return {"score": final_score, "explanation": explanation}

    return final_score


def final_rank(
    candidates: list[Candidate],
    tag: PreparedTag,
    cheap_scores: dict[str, float],
    ai_results: list[ClassificationResult] | None = None,
) -> list[Candidate]:
    """
    Ranks candidates using the final score formula.
    Sets candidate.raw_score and candidate.ranking_explanation.
    """
    explain = os.environ.get("ENABLE_RANKING_DEBUG", "").lower() == "true"

    # Map AI results by candidate URL/content_id
    ai_map = {}
    if ai_results:
        for res in ai_results:
            key = res.candidate_key.lower().strip()
            ai_map[key] = res

    scored = []
    for c in candidates:
        cheap_score = cheap_scores.get(c.url, c.raw_score or 0.0)

        # Look up AI result
        ai_res = None
        if c.url:
            ai_res = ai_map.get(c.url.lower().strip())
        if not ai_res and c.content_id:
            ai_res = ai_map.get(c.content_id.lower().strip())

        if explain:
            res = calculate_final_score(c, tag, cheap_score, ai_res, explain=True)
            c.raw_score = res["score"]
            c.ranking_explanation = res["explanation"]
        else:
            score = calculate_final_score(c, tag, cheap_score, ai_res, explain=False)
            c.raw_score = score
            c.ranking_explanation = None

        scored.append(c)

    return sorted(scored, key=lambda x: x.raw_score, reverse=True)
