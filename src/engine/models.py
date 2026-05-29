from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class SourceName(str, Enum):
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
