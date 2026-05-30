import re
from typing import List, Tuple, Dict
from src.utils.constants import (
    TAG_MAP,
    DESCRIPTIVE_TAG_DECOMPOSITION,
    CORE_TECH_KEYWORDS,
)
from src.engine.stages import PreparedTag, PlannedSource, PlannedQuery
from src.engine.models import TopicScope, SourceName

_QUERY_TOKEN_EXPANSIONS = {
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
}

_ROLE_TOPIC_SUFFIXES = {
    "analyst": "analytics",
    "designer": "design",
    "developer": "development",
    "engineer": "engineering",
    "tester": "testing",
}


class QueryPlanner:
    @staticmethod
    def normalize_search_tag(tag: str) -> str:
        """
        Normalizes and expands search tag tokens using predefined rules.
        """
        clean = " ".join(tag.replace("-", " ").split()).strip()
        tokens = [
            _QUERY_TOKEN_EXPANSIONS.get(token.lower(), token) for token in clean.split()
        ]
        expanded = " ".join(tokens).strip()
        return TAG_MAP.get(expanded.lower(), expanded)

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        seen = set()
        ordered = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    @classmethod
    def build_search_tag(cls, tag: str, language: str) -> str:
        """
        Reconstructs the query tag targeting the specific language settings.
        """
        normalized = cls.normalize_search_tag(tag)

        if language != "en":
            return normalized

        if not re.search(r"[\u0600-\u06FF]", normalized):
            return normalized

        ascii_terms = []
        for token in re.findall(r"[A-Za-z0-9#+.]+", normalized):
            lowered = token.lower()
            mapped = TAG_MAP.get(lowered, lowered)
            ascii_terms.append(mapped)

        ascii_terms = cls._dedupe_preserve_order(ascii_terms)
        return " ".join(ascii_terms) if ascii_terms else normalized

    @classmethod
    def build_search_plans(cls, tag: str, language: str) -> List[Dict[str, str]]:
        """
        Constructs candidate search query plans for fetchers.
        """
        normalized = cls.normalize_search_tag(tag)
        has_arabic_query = bool(re.search(r"[\u0600-\u06FF]", normalized))
        requested_language = "ar" if language == "ar" and has_arabic_query else "en"
        plans = []
        seen = set()

        def add_plan(query: str, relevance_language: str | None):
            clean_query = " ".join(query.split()).strip()
            if not clean_query:
                return

            key = (clean_query.lower(), relevance_language or "")
            if key in seen:
                return

            seen.add(key)
            plans.append(
                {
                    "query": clean_query,
                    "relevance_language": relevance_language,
                }
            )

        add_plan(normalized, requested_language)

        if language == "ar":
            add_plan(normalized, None)

            english_fallback = cls.build_search_tag(normalized, "en")
            if has_arabic_query and english_fallback.lower() != normalized.lower():
                add_plan(english_fallback, "en")

        return plans

    @classmethod
    def build_smart_queries(cls, tag: str) -> List[Tuple[str, str]]:
        """
        Generates optimized search queries from potentially descriptive tags.
        Decomposes them into (playlist_query, video_query) pairs.
        """
        tag_lower = tag.lower().strip()

        # Check if this is a known descriptive pattern
        for pattern, (q1, q2) in DESCRIPTIVE_TAG_DECOMPOSITION.items():
            if pattern in tag_lower:
                # Also check for a core tech keyword in the tag
                core_tech = None
                for tech in CORE_TECH_KEYWORDS:
                    if tech in tag_lower and tech != pattern:
                        core_tech = tech
                        break

                if core_tech:
                    return [
                        (f"{core_tech} {q1} full course", f"{core_tech} {q2} tutorial"),
                        (f"{tag} full course", f"{tag} tutorial"),
                    ]
                return [
                    (f"{q1} full course", f"{q2} tutorial"),
                    (f"{tag} full course", f"{tag} tutorial"),
                ]

        # For multi-word descriptive tags containing a core tech, lead with the tech
        words = tag_lower.split()
        if len(words) >= 3:
            found_techs = [w for w in words if w in CORE_TECH_KEYWORDS]
            if found_techs:
                primary_tech = found_techs[0]
                context = tag_lower.replace(primary_tech, "").strip()
                context = " ".join(context.split())  # normalize spaces
                if context and len(context) > 2:
                    return [
                        (
                            f"{primary_tech} {context} full course",
                            f"{primary_tech} {context} tutorial",
                        ),
                        (f"{tag} full course", f"{tag} tutorial"),
                    ]

        if len(words) >= 2 and words[-1] in _ROLE_TOPIC_SUFFIXES:
            discipline_tag = " ".join(
                [*words[:-1], _ROLE_TOPIC_SUFFIXES[words[-1]]]
            ).strip()
            if discipline_tag and discipline_tag != tag_lower:
                return [
                    (
                        f"{discipline_tag} full course",
                        f"{discipline_tag} tutorial",
                    ),
                    (f"{tag} full course", f"{tag} tutorial"),
                ]

        # Default: original behavior
        return [(f"{tag} full course", f"{tag} tutorial")]

    @classmethod
    def plan_queries_for_tag(
        cls,
        tag: PreparedTag,
        planned_sources: List[PlannedSource],
        max_results: int,
        query_limit_per_tag: int,
    ) -> List[PlannedQuery]:
        """
        Generates bounded queries per enabled planned source and tag scope.
        """
        planned_queries = []

        # Determine suffixes based on the scope
        scope = tag.scope
        if scope == TopicScope.DEBUGGING_QUERY:
            suffixes = ["fix tutorial", "explained"]
        elif scope == TopicScope.COMPARISON_QUERY:
            suffixes = ["explained", "comparison"]
        elif scope == TopicScope.ATOMIC:
            suffixes = ["tutorial", "explained"]
        elif scope in (TopicScope.TECHNOLOGY, TopicScope.SKILL_TOPIC):
            suffixes = ["full course", "tutorial"]
        elif scope == TopicScope.ROLE_ROADMAP:
            suffixes = ["roadmap", "full course"]
        elif scope == TopicScope.PROJECT_GOAL:
            suffixes = ["project tutorial", "full project"]
        else:
            suffixes = ["full course", "tutorial"]

        for planned_source in planned_sources:
            if not planned_source.enabled:
                continue

            source = planned_source.source

            if source == SourceName.YOUTUBE:
                candidates = []

                # Check for Arabic query
                has_arabic = bool(re.search(r"[\u0600-\u06FF]", tag.normalized))

                if has_arabic:
                    # Try Arabic query first, and then English fallback for each suffix
                    eng_fallback = cls.build_search_tag(tag.normalized, "en")
                    is_useful = (
                        eng_fallback
                        and not re.search(r"[\u0600-\u06FF]", eng_fallback)
                        and eng_fallback.lower() != tag.normalized.lower()
                    )
                    for suffix in suffixes:
                        candidates.append(
                            (f"{tag.normalized} {suffix}".strip(), suffix)
                        )
                        if is_useful:
                            candidates.append(
                                (f"{eng_fallback} {suffix}".strip(), suffix)
                            )
                else:
                    for suffix in suffixes:
                        candidates.append(
                            (f"{tag.normalized} {suffix}".strip(), suffix)
                        )

                seen_queries = set()
                unique_candidates = []
                for query_str, suffix in candidates:
                    clean_query = " ".join(query_str.split()).strip()
                    if not clean_query:
                        continue
                    if clean_query.lower() not in seen_queries:
                        seen_queries.add(clean_query.lower())
                        unique_candidates.append((clean_query, suffix))

                selected_candidates = unique_candidates[:query_limit_per_tag]

                for query_str, suffix in selected_candidates:
                    if suffix in ("full course", "roadmap", "full project"):
                        content_type = "playlist"
                    else:
                        content_type = "video"

                    planned_queries.append(
                        PlannedQuery(
                            tag=tag,
                            source=source,
                            query=query_str,
                            expected_content_type=content_type,
                            max_results=max_results,
                        )
                    )
            else:
                planned_queries.append(
                    PlannedQuery(
                        tag=tag,
                        source=source,
                        query=tag.normalized,
                        expected_content_type="course",
                        max_results=max_results,
                    )
                )

        return planned_queries
