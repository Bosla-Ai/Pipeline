import re
from typing import List, Tuple, Dict
from src.utils.constants import (
    TAG_MAP,
    DESCRIPTIVE_TAG_DECOMPOSITION,
    CORE_TECH_KEYWORDS,
)

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
