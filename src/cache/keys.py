import hashlib

PIPELINE_CACHE_VERSION = "v2"
QUERY_PLANNER_VERSION = "query-v1"
YTDLP_PROVIDER_VERSION = "ytdlp-v2"
RANKER_VERSION = "ranker-v1"
CLASSIFIER_VERSION = "edge-v1"
NORMALIZER_VERSION = "norm-v1"


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def get_raw_ytdlp_key(query: str, lang: str) -> str:
    """
    pipeline:v2:raw:youtube_yt_dlp:lang={lang}:q={query_hash}:qp={query_planner_version}:provider={provider_version}
    """
    q_hash = _hash_str(query)
    return (
        f"pipeline:{PIPELINE_CACHE_VERSION}:raw:youtube_yt_dlp:"
        f"lang={lang}:q={q_hash}:qp={QUERY_PLANNER_VERSION}:provider={YTDLP_PROVIDER_VERSION}"
    )


def get_normalized_key(source: str, raw_hash: str) -> str:
    """
    pipeline:v2:normalized:source={source}:raw={raw_hash}:normalizer={normalizer_version}
    """
    return (
        f"pipeline:{PIPELINE_CACHE_VERSION}:normalized:source={source}:"
        f"raw={raw_hash}:normalizer={NORMALIZER_VERSION}"
    )


def get_ranked_key(tag: str, source: str, candidate_set_hash: str) -> str:
    """
    pipeline:v2:ranked:tag={tag_hash}:source={source}:ranker={ranker_version}:candidate_set={candidate_set_hash}
    """
    tag_hash = _hash_str(tag)
    return (
        f"pipeline:{PIPELINE_CACHE_VERSION}:ranked:tag={tag_hash}:source={source}:"
        f"ranker={RANKER_VERSION}:candidate_set={candidate_set_hash}"
    )
