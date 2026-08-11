from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SearchResourcesRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["youtube", "coursera"]
    query: str = Field(min_length=1, max_length=300)
    language: str = Field(default="en", min_length=2, max_length=16)
    limit: int = Field(default=15, ge=1, le=15)
    duration_min_minutes: int | None = Field(default=None, ge=0)
    duration_max_minutes: int | None = Field(default=None, ge=1)
    type: Literal["video", "playlist", "course"] | None = None
    embeddable: bool | None = None

class ResourceCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    url: HttpUrl
    title: str
    durationMinutes: float
    language: str
    channel: str
    viewCount: int
    publishedAt: str | None = None
    cheapScore: float
    finalScore: float


class SearchMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["youtube", "coursera"]
    query: str
    rawCount: int
    filteredCount: int
    shortlistCount: int


class SearchResourcesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[ResourceCandidate]
    meta: SearchMeta


class MarketDataRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(min_length=1, max_length=20)
    language: str | None = Field(default=None, min_length=2, max_length=16)


class DemandSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: str
    questionCount: int


class TagTrend(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: str
    questionCount: int
    hasSynonyms: bool
    relatedTags: list[str]


class MarketDataResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    demandSignals: list[DemandSignal]
    trendingSkills: list[str]
    decliningSkills: list[str]
    tagTrends: list[TagTrend]
    ecosystemNotes: list[str]
    sourcesFailed: list[str]
