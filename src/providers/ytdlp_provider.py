from typing import Optional
from src.engine.models import Candidate, SourceName
from src.engine.stages import PlannedQuery
from src.providers.base import Provider
from src.fetchers.videos.youtube_scraper import scrape_youtube_query_candidates


class YtDlpProvider(Provider):
    async def fetch(
        self, query: PlannedQuery, *, job_id: Optional[str] = None
    ) -> list[Candidate]:
        """
        Fetch candidates from YouTube using yt-dlp.
        """
        raw_candidates = await scrape_youtube_query_candidates(
            query=query.query,
            tag=query.tag.original,
            language=query.tag.language,
            max_results=query.max_results,
        )

        candidates = []
        for raw in raw_candidates:
            c = Candidate.from_dict(raw, SourceName.YOUTUBE, query.tag.original)
            candidates.append(c)

        return candidates
