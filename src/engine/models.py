from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceName(str, Enum):
    YOUTUBE = "youtube"
    UDEMY = "udemy"
    COURSERA = "coursera"


class CourseSource(str, Enum):
    YOUTUBE = "youtube"
    UDEMY = "udemy"
    COURSERA = "coursera"


class TopicScope(str, Enum):
    ATOMIC = "atomic"
    SKILL_TOPIC = "skill_topic"
    TECHNOLOGY = "technology"
    ROLE_ROADMAP = "role_roadmap"
    PROJECT_GOAL = "project_goal"
    DEBUGGING_QUERY = "debugging_query"
    COMPARISON_QUERY = "comparison_query"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EngineRequest:
    tags: list[str]
    prefer_paid: bool
    language: str
    sources: list[str] | None
    job_id: str


@dataclass(frozen=True)
class TagContext:
    original: str
    normalized: str
    language: str
    scope: TopicScope = TopicScope.UNKNOWN


@dataclass(frozen=True)
class SourceQuery:
    tag: TagContext
    source: SourceName
    query: str
    expected_content_type: str
    max_results: int


@dataclass
class Candidate:
    source: SourceName
    tag: str
    title: str
    url: str
    content_id: str | None = None
    description: str | None = None
    channel_or_provider: str | None = None
    language: str | None = None

    duration_minutes: float | None = None
    view_count: int | None = None
    like_count: int | None = None
    rating: float | None = None
    review_count: int | None = None
    lecture_count: int | None = None
    published_at: str | None = None

    raw_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], source: SourceName | str, tag: str
    ) -> Candidate:
        source_enum = SourceName(source) if isinstance(source, str) else source
        title = raw.get("title", "")
        url = raw.get("url", "")
        content_id = raw.get("contentId")
        description = raw.get("description")

        channel_or_provider = raw.get("channel_or_provider")
        if not channel_or_provider:
            if source_enum == SourceName.YOUTUBE:
                channel_or_provider = raw.get("channelTitle")
            elif source_enum == SourceName.UDEMY:
                channel_or_provider = raw.get("instructor")
            elif source_enum == SourceName.COURSERA:
                channel_or_provider = raw.get("platform", "Coursera")

        language = raw.get("language") or raw.get("defaultLanguage")

        duration_minutes = raw.get("duration_minutes") or raw.get("duration_mins")
        if duration_minutes is not None:
            try:
                duration_minutes = float(duration_minutes)
            except (ValueError, TypeError):
                duration_minutes = None

        view_count = (
            raw.get("view_count") or raw.get("viewCount") or raw.get("avg_views")
        )
        if view_count is not None:
            try:
                view_count = int(view_count)
            except (ValueError, TypeError):
                view_count = None

        like_count = (
            raw.get("like_count") or raw.get("likeCount") or raw.get("avg_likes")
        )
        if like_count is not None:
            try:
                like_count = int(like_count)
            except (ValueError, TypeError):
                like_count = None

        rating = raw.get("rating")
        if rating is not None:
            try:
                rating = float(rating)
            except (ValueError, TypeError):
                rating = None

        review_count = (
            raw.get("review_count") or raw.get("reviewCount") or raw.get("avg_comments")
        )
        if review_count is not None:
            try:
                review_count = int(review_count)
            except (ValueError, TypeError):
                review_count = None

        lecture_count = raw.get("lecture_count") or raw.get("videoCount")
        if lecture_count is not None:
            try:
                lecture_count = int(lecture_count)
            except (ValueError, TypeError):
                lecture_count = None

        published_at = raw.get("published_at") or raw.get("publishedAt")
        raw_score = raw.get("raw_score") or raw.get("score", 0.0)
        try:
            raw_score = float(raw_score)
        except (ValueError, TypeError):
            raw_score = 0.0

        return cls(
            source=source_enum,
            tag=tag,
            title=title,
            url=url,
            content_id=content_id,
            description=description,
            channel_or_provider=channel_or_provider,
            language=language,
            duration_minutes=duration_minutes,
            view_count=view_count,
            like_count=like_count,
            rating=rating,
            review_count=review_count,
            lecture_count=lecture_count,
            published_at=published_at,
            raw_score=raw_score,
            metadata=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        res = dict(self.metadata)
        res.update(
            {
                "title": self.title,
                "url": self.url,
                "score": self.raw_score,
            }
        )
        if self.content_id is not None:
            res["contentId"] = self.content_id
        if self.description is not None:
            res["description"] = self.description
        if self.published_at is not None:
            res["publishedAt"] = self.published_at
        return res


@dataclass
class RankedCandidate:
    candidate: Candidate
    score: float
    reasons: list[str] = field(default_factory=list)
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class TagResult:
    tag: str
    candidates: list[RankedCandidate]
    selected: RankedCandidate | None


@dataclass
class EngineResult:
    job_id: str
    results: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
