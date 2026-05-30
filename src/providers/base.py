from typing import Protocol, Optional
from src.engine.models import Candidate
from src.engine.stages import PlannedQuery


class Provider(Protocol):
    async def fetch(
        self, query: PlannedQuery, *, job_id: Optional[str] = None
    ) -> list[Candidate]:
        """
        Fetch candidate resources from the provider for the given planned query.
        """
        ...
