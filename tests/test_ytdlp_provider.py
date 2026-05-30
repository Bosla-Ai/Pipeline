import pytest
from unittest import mock
from fastapi import HTTPException
from src.engine.models import TopicScope, SourceName, Candidate
from src.engine.stages import PreparedTag, PlannedQuery
from src.providers.ytdlp_provider import YtDlpProvider


@pytest.mark.anyio
async def test_ytdlp_provider_fetch_candidates():
    provider = YtDlpProvider()
    tag = PreparedTag(
        original="Python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    query = PlannedQuery(
        tag=tag,
        source=SourceName.YOUTUBE,
        query="python tutorial",
        expected_content_type="playlist",
        max_results=3,
    )

    mock_raw = [
        {
            "id": "vid123",
            "title": "Python Course 1",
            "url": "https://www.youtube.com/watch?v=vid123",
            "duration": 3600,
            "view_count": 10000,
            "_type": "video",
        },
        {
            "id": "pl456",
            "title": "Python Playlist 2",
            "url": "https://www.youtube.com/playlist?list=pl456",
            "_type": "playlist",
        },
    ]

    with mock.patch(
        "src.providers.ytdlp_provider.scrape_youtube_query_candidates",
        mock.AsyncMock(return_value=mock_raw),
    ) as mock_scrape:
        candidates = await provider.fetch(query)

        mock_scrape.assert_called_once_with(
            query="python tutorial", tag="Python", language="en", max_results=3
        )

        assert len(candidates) == 2
        assert isinstance(candidates[0], Candidate)
        assert candidates[0].title == "Python Course 1"
        assert candidates[0].source == SourceName.YOUTUBE
        assert candidates[0].url == "https://www.youtube.com/watch?v=vid123"

        assert candidates[1].title == "Python Playlist 2"
        assert candidates[1].url == "https://www.youtube.com/playlist?list=pl456"


@pytest.mark.anyio
async def test_youtube_api_endpoints_disabled_response(monkeypatch):
    monkeypatch.setattr("src.api.DISABLE_YOUTUBE_API", True)
    from src.api import search_embeddable_video_endpoint, youtube_playlist_items

    with pytest.raises(HTTPException) as exc:
        await search_embeddable_video_endpoint(q="python")
    assert exc.value.status_code == 503

    with pytest.raises(HTTPException) as exc:
        await youtube_playlist_items(playlistId="pl123")
    assert exc.value.status_code == 503
