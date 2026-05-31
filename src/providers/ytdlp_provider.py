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
        from src.cache.pipeline_cache import (
            get_raw_ytdlp_candidates,
            set_raw_ytdlp_candidates,
        )

        cached_raw = await get_raw_ytdlp_candidates(query.query, query.tag.language)
        if cached_raw is not None:
            raw_candidates = cached_raw
        else:
            raw_candidates = await scrape_youtube_query_candidates(
                query=query.query,
                tag=query.tag.original,
                language=query.tag.language,
                max_results=query.max_results,
            )
            if raw_candidates:
                await set_raw_ytdlp_candidates(
                    query.query, query.tag.language, raw_candidates
                )

        candidates = []
        for raw in raw_candidates:
            c = Candidate.from_dict(raw, SourceName.YOUTUBE, query.tag.original)
            candidates.append(c)

        return candidates
