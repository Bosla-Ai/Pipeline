import asyncio
from typing import List, Optional, Tuple, Dict
from src.engine.models import CourseSource, TopicScope, SourceName
from src.engine.stages import PreparedTag, PlannedSource
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
                paid_only = [s for s in active_sources if s != CourseSource.YOUTUBE]
                if paid_only:
                    active_sources = paid_only
        elif prefer_paid:
            active_sources = [CourseSource.UDEMY]
        else:
            active_sources = [CourseSource.YOUTUBE]
        return active_sources

    @staticmethod
    def plan_sources_for_scope(
        tag: PreparedTag,
        prefer_paid: bool,
        requested_sources: List[CourseSource] | None,
        free_hf_mode: bool,
    ) -> List[PlannedSource]:
        """
        Determine source planning based on scope, preferences, and HF environment limits.
        """
        planned = []

        # YouTube is always planned and enabled (via yt-dlp)
        planned.append(
            PlannedSource(
                tag=tag,
                source=SourceName.YOUTUBE,
                enabled=True,
                reason="free_hf_youtube_only" if free_hf_mode else "youtube_primary",
                estimated_cost="free",
            )
        )

        # Determine Udemy and Coursera eligibility
        udemy_requested = False
        coursera_requested = False

        if requested_sources is not None:
            udemy_requested = CourseSource.UDEMY in requested_sources
            coursera_requested = CourseSource.COURSERA in requested_sources
        elif prefer_paid:
            udemy_requested = True
            coursera_requested = True

        # Udemy planning
        udemy_enabled = False
        udemy_reason = "not_requested"
        if udemy_requested:
            if free_hf_mode:
                udemy_reason = "disabled_on_free_hf"
            elif tag.scope in (
                TopicScope.SKILL_TOPIC,
                TopicScope.TECHNOLOGY,
                TopicScope.ROLE_ROADMAP,
                TopicScope.PROJECT_GOAL,
            ):
                udemy_enabled = True
                udemy_reason = "broad_scope_match"
            else:
                udemy_reason = f"atomic_scope_prefers_youtube_for_{tag.scope.value}"

        planned.append(
            PlannedSource(
                tag=tag,
                source=SourceName.UDEMY,
                enabled=udemy_enabled,
                reason=udemy_reason,
                estimated_cost="paid" if udemy_enabled else "none",
            )
        )

        # Coursera planning
        coursera_enabled = False
        coursera_reason = "not_requested"
        if coursera_requested:
            if free_hf_mode:
                coursera_reason = "disabled_on_free_hf"
            elif tag.scope in (
                TopicScope.ROLE_ROADMAP,
                TopicScope.TECHNOLOGY,
                TopicScope.SKILL_TOPIC,
            ):
                coursera_enabled = True
                coursera_reason = "broad_scope_match"
            else:
                coursera_reason = f"scope_not_applicable_for_{tag.scope.value}"

        planned.append(
            PlannedSource(
                tag=tag,
                source=SourceName.COURSERA,
                enabled=coursera_enabled,
                reason=coursera_reason,
                estimated_cost="paid" if coursera_enabled else "none",
            )
        )

        return planned

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
