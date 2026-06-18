"""Verifies phase + item progress frames are emitted at the right points."""

import pytest

from src.transport.runtime import set_inference_transport, reset_inference_transport
from src.engine.roadmap_engine import RoadmapEngine
from src.engine.fetch_coordinator import FetchCoordinator


class RecordingTransport:
    def __init__(self):
        self.published = []

    async def publish(self, job_id, event, data):
        self.published.append((job_id, event, data))

    def target_for_job(self, job_id):
        return "grp"


def _progress_payloads(transport):
    return [data for (_jid, event, data) in transport.published if event == "progress"]


@pytest.fixture(autouse=True)
def _clean_transport():
    reset_inference_transport()
    yield
    reset_inference_transport()


# ── engine phase rail ─────────────────────────────────────────────────────


async def test_generate_impl_emits_phase_rail(monkeypatch):
    t = RecordingTransport()
    set_inference_transport(t)

    import src.engine.roadmap_engine as eng

    async def fake_wait_for_socket(job_id, timeout):
        return "grp"

    monkeypatch.setattr(eng, "wait_for_socket", fake_wait_for_socket)
    monkeypatch.setattr(eng, "generate_learning_path", lambda *a, **k: {"phases": []})

    engine = RoadmapEngine(
        sio=None, fetch_youtube=None, fetch_coursera=None, get_global_driver=None
    )

    async def fake_fetch(*args, **kwargs):
        return {"youtube": {}, "coursera": {}, "udemy": {}}

    monkeypatch.setattr(engine.fetch_coordinator, "fetch_resources", fake_fetch)

    await engine._generate_impl(
        tags=["React"], prefer_paid=False, language="en", job_id="j1"
    )

    phases = [p["phase"] for p in _progress_payloads(t) if p.get("kind") == "phase"]
    assert phases == ["analyzing", "searching", "finalizing", "done"]


# ── per-tag item lifecycle ────────────────────────────────────────────────


class _FakeProvider:
    async def fetch(self, pq):
        return [{"raw": True}]


class _FakeCandidate:
    url = "https://yt/u"

    def to_dict(self):
        return {"title": "Real Title", "url": self.url, "score": 1.0}


class _FakeWinner:
    def to_dict(self):
        return {"title": "Real Title", "url": "https://yt/u", "score": 1.0}


async def test_ytdlp_pipeline_emits_item_lifecycle(monkeypatch):
    t = RecordingTransport()
    set_inference_transport(t)

    # Scope planning + query/source planning → one tag, one query.
    from src.planning.source_planner import SourcePlanner
    from src.planning.query_planner import QueryPlanner

    async def fake_plan_scopes(sio, sid, tags, job_id=None):
        return (list(tags), [], {tag: "broad" for tag in tags})

    monkeypatch.setattr(SourcePlanner, "plan_tag_scopes", staticmethod(fake_plan_scopes))
    monkeypatch.setattr(
        SourcePlanner, "plan_sources_for_scope", staticmethod(lambda **k: ["youtube"])
    )
    monkeypatch.setattr(
        QueryPlanner, "normalize_search_tag", staticmethod(lambda s: s)
    )
    monkeypatch.setattr(
        QueryPlanner, "plan_queries_for_tag", staticmethod(lambda **k: ["pq1"])
    )

    monkeypatch.setattr(
        "src.providers.ytdlp_provider.YtDlpProvider", lambda *a, **k: _FakeProvider()
    )
    monkeypatch.setattr(
        "src.providers.youtube_legacy_adapter.normalize_youtube_candidate",
        lambda raw, tag: _FakeCandidate(),
    )
    monkeypatch.setattr("src.ranking.dedupe.dedupe_candidates", lambda c: list(c))
    monkeypatch.setattr(
        "src.ranking.cheap_ranker.cheap_rank_candidate", lambda c, tag, scope=None: 1.0
    )
    monkeypatch.setattr(
        "src.ranking.final_ranker.final_rank", lambda **k: [_FakeWinner()]
    )
    monkeypatch.setattr(
        "src.inference.schemas.ClassificationRequest", lambda **k: object()
    )

    class _FakeEdge:
        @staticmethod
        async def classify(req, timeout=3.0):
            return []

    monkeypatch.setattr("src.inference.edge_client.EdgeInferenceClient", _FakeEdge)

    coord = FetchCoordinator(
        sio=None, fetch_youtube=None, fetch_coursera=None, get_global_driver=None
    )
    result = await coord._fetch_youtube_ytdlp_pipeline(
        tags=["React Hooks"], language="en", current_sid="grp", job_id="j1"
    )

    assert result == {"React Hooks": {"title": "Real Title", "url": "https://yt/u", "score": 1.0}}

    items = [p for p in _progress_payloads(t) if p.get("kind") == "item"]
    statuses = [(i["tag"], i["status"]) for i in items]
    assert ("React Hooks", "searching") in statuses
    assert ("React Hooks", "classifying") in statuses
    found = [i for i in items if i["status"] == "found"]
    assert found and found[0]["resource"]["title"] == "Real Title"
    # The first classify also flips the global phase.
    assert any(p.get("phase") == "classifying" for p in _progress_payloads(t))
