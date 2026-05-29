import asyncio
from typing import List, Optional, Tuple, Dict
from src.engine.models import CourseSource
from src.utils.helpers import analyze_topic_scope


class SourcePlanner:
    @staticmethod
    def plan_sources(
        sources: Optional[List[CourseSource]], prefer_paid: bool
    ) -> List[CourseSource]:
        """
        Determine active sources based on user preferences and request.
        """
        if sources:
            active_sources = sources
            if prefer_paid:
                # Strip free sources when user explicitly prefers paid;
                # YouTube is still used as fallback for atomic / unmatched tags later.
                paid_only = [s for s in active_sources if s != CourseSource.YOUTUBE]
                if paid_only:
                    active_sources = paid_only
        elif prefer_paid:
            active_sources = [CourseSource.UDEMY]
        else:
            active_sources = [CourseSource.YOUTUBE]
        return active_sources

    @staticmethod
    async def plan_tag_scopes(
        sio, socket_id: Optional[str], tags: List[str], job_id: Optional[str] = None
    ) -> Tuple[List[str], List[str], Dict[str, str]]:
        """
        Classify tags into Broad and Atomic categories using heuristic and AI fallback.
        """
        broad_tags = []
        atomic_tags = []
        scope_cache = {}

        async def analyze_tag(tag):
            try:
                scope = await analyze_topic_scope(sio, socket_id, tag, job_id=job_id)
            except TypeError:
                scope = await analyze_topic_scope(sio, socket_id, tag)
            return tag, scope

        scope_results = await asyncio.gather(*(analyze_tag(t) for t in tags))
        for tag, scope in scope_results:
            scope_cache[tag] = scope
            if scope == "Broad":
                broad_tags.append(tag)
            else:
                atomic_tags.append(tag)

        return broad_tags, atomic_tags, scope_cache
