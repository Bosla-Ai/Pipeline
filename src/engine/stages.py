from dataclasses import dataclass
from src.engine.models import TopicScope, SourceName, Candidate, RankedCandidate


@dataclass(frozen=True)
class PreparedTag:
    original: str
    normalized: str
    language: str
    scope: TopicScope = TopicScope.UNKNOWN


@dataclass(frozen=True)
class PlannedSource:
    tag: PreparedTag
    source: SourceName
    enabled: bool
    reason: str
    estimated_cost: str


@dataclass(frozen=True)
class PlannedQuery:
    tag: PreparedTag
    source: SourceName
    query: str
    expected_content_type: str
    max_results: int


@dataclass
class CandidateBatch:
    tag: PreparedTag
    source: SourceName
    query: str
    candidates: list[Candidate]


@dataclass
class RankedBatch:
    tag: PreparedTag
    candidates: list[RankedCandidate]
