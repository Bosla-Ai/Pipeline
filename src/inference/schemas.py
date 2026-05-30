from dataclasses import dataclass, field
from src.engine.models import Candidate


@dataclass(frozen=True)
class ClassificationRequest:
    job_id: str
    tag: str
    candidates: list[Candidate]
    labels: list[str]


@dataclass(frozen=True)
class ClassificationResult:
    candidate_key: str
    label: str
    confidence: float
    raw: dict = field(default_factory=dict)
