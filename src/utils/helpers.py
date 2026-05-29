import asyncio
import math
import os
import re
from src.utils.constants import (
    NEGATIVE_KEYWORDS,
    BEGINNER_KEYWORDS,
    UNWANTED_KEYWORDS,
    STOP_WORDS,
)

# ── Dynamic Scope Analysis (no static list dependency) ────────────────────

# Markers that signal a broad, curriculum-level topic
_BROAD_MARKERS = {
    "mastery",
    "fundamentals",
    "essentials",
    "masterclass",
    "bootcamp",
    "complete",
    "comprehensive",
    "advanced",
    "beginner",
    "intermediate",
    "administration",
    "engineering",
    "development",
    "architecture",
    "for developers",
    "for engineers",
    "for beginners",
    "from scratch",
    "full course",
    "deep dive",
    "in depth",
    "zero to hero",
}

# Markers that signal an atomic, specific concept
_ATOMIC_MARKERS = {
    "how to",
    "fix",
    "error",
    "bug",
    "vs",
    "difference between",
    "what is",
    "tutorial on",
    "quick tip",
    "in 5 minutes",
    "in 10 minutes",
    "snippet",
    "cheat sheet",
    "one liner",
}

_TAG_DESCRIPTOR_WORDS = {
    "advanced",
    "basics",
    "beginner",
    "beginners",
    "bootcamp",
    "complete",
    "comprehensive",
    "course",
    "crash",
    "deep",
    "essentials",
    "expert",
    "for",
    "from",
    "full",
    "fundamentals",
    "guide",
    "hero",
    "in",
    "intermediate",
    "intro",
    "introduction",
    "masterclass",
    "mastery",
    "overview",
    "practical",
    "scratch",
    "step",
    "steps",
    "to",
    "tutorial",
    "walkthrough",
    "zero",
    "أساسيات",
    "احتراف",
    "بالكامل",
    "خطوة",
    "خطوات",
    "دليل",
    "شرح",
    "شامل",
    "عملي",
    "كامل",
    "كورس",
    "للمبتدئين",
    "متقدم",
    "مقدمة",
}


def _parse_positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default

    try:
        return max(1, int(value))
    except ValueError:
        return default


_FRONTEND_AI_MAX_CONCURRENCY = _parse_positive_int_env("FRONTEND_AI_MAX_CONCURRENCY", 2)
_FRONTEND_AI_SEMAPHORE = asyncio.Semaphore(_FRONTEND_AI_MAX_CONCURRENCY)


class InferenceBatcher:
    """Aggregates and batches frontend classification and scope analysis requests
    to reduce network roundtrips over Socket.IO.
    """

    def __init__(self):
        self._groups = (
            {}
        )  # (socket_id, group_key) -> list of (candidate_dict, future, labels, hypothesis_template, timeout)
        self._timers = {}  # (socket_id, group_key) -> Task or None

    async def schedule_inference(
        self,
        sio,
        socket_id,
        group_key,
        candidates,
        labels,
        hypothesis_template,
        timeout,
    ):
        loop = asyncio.get_running_loop()
        key = (socket_id, group_key)

        futures = [loop.create_future() for _ in candidates]

        if key not in self._groups:
            self._groups[key] = []

        for cand, fut in zip(candidates, futures):
            self._groups[key].append((cand, fut, labels, hypothesis_template, timeout))

        if (
            key not in self._timers
            or self._timers[key] is None
            or self._timers[key].done()
        ):
            self._timers[key] = asyncio.create_task(
                self._run_batch(sio, socket_id, group_key)
            )

        results = await asyncio.gather(*futures, return_exceptions=True)

        real_results = []
        for r in results:
            if isinstance(r, Exception):
                raise r
            real_results.append(r)
        return real_results

    async def _run_batch(self, sio, socket_id, group_key):
        # Wait a brief moment to allow other concurrent calls to queue their candidates
        await asyncio.sleep(0.05)

        key = (socket_id, group_key)
        items = self._groups.pop(key, [])
        if not items:
            return

        _, _, labels, hypothesis_template, timeout = items[0]
        batch_candidates = [cand for cand, _, _, _, _ in items]
        futures = [fut for _, fut, _, _, _ in items]

        try:
            async with _FRONTEND_AI_SEMAPHORE:
                response = await sio.call(
                    event="request_inference",
                    data={
                        "candidates": batch_candidates,
                        "labels": labels,
                        "hypothesis_template": hypothesis_template,
                    },
                    to=socket_id,
                    timeout=timeout,
                )

            if not response or not isinstance(response, list):
                raise ValueError("Invalid or empty response from frontend inference")

            # Distribute results
            for i, fut in enumerate(futures):
                if i < len(response):
                    fut.set_result(response[i])
                else:
                    fut.set_result({})
        except Exception as e:
            for fut in futures:
                if not fut.done():
                    fut.set_exception(e)


_inference_batcher = InferenceBatcher()


def _heuristic_scope(tag: str) -> str | None:
    """Classify scope using language heuristics. Returns 'Broad', 'Atomic', or None (uncertain)."""
    tag_lower = tag.lower().strip()
    words = tag_lower.split()

    # 1) Very short tags (1-2 words) → almost always a technology name → Broad
    if len(words) <= 2:
        return "Broad"

    # 2) Check for explicit broad markers in the tag
    for marker in _BROAD_MARKERS:
        if marker in tag_lower:
            return "Broad"

    # 3) Check for explicit atomic markers
    for marker in _ATOMIC_MARKERS:
        if marker in tag_lower:
            return "Atomic"

    # 4) Tags with "with" or "for" + technology name pattern → curriculum tags → Broad
    #    e.g. "Automated Testing with Jest", "Kubernetes for Application Developers"
    if re.search(r"\b(with|for|using)\b", tag_lower):
        return "Broad"

    # 5) Title-case multi-word tags (like "Linux System Administration") → structured course title → Broad
    title_case_words = sum(1 for w in tag.split() if w[0].isupper() and len(w) > 2)
    if title_case_words >= 2:
        return "Broad"

    return None  # Uncertain — defer to AI


async def analyze_topic_scope(sio, socket_id, tag):
    """Classifies topic scope: 'Broad' (Playlist/Course) vs 'Atomic' (Single Video).

    Uses a heuristic-first approach for speed and reliability,
    falling back to on-device AI classification when uncertain.
    No static topic list dependency.
    """
    # Fast heuristic pass
    heuristic = _heuristic_scope(tag)
    if heuristic:
        print(f"    🧩 Heuristic Scope: '{tag}' → {heuristic}")
        return heuristic

    # No socket → default permissive (Broad is safer — searches wider)
    if not socket_id:
        print(f"    🧩 No socket, defaulting to Broad for '{tag}'")
        return "Broad"

    labels = [
        "an entire programming language, framework, or major technology",
        "a specific programming concept, error, or technique",
    ]

    try:
        response = await _inference_batcher.schedule_inference(
            sio=sio,
            socket_id=socket_id,
            group_key="scope",
            candidates=[{"ai_input_text": f"The technical topic is {tag}."}],
            labels=labels,
            hypothesis_template="{}",
            timeout=4,
        )

        if not response:
            return "Broad"

        # Map labels to scores
        result = response[0]
        score_map = {
            l: s for l, s in zip(result.get("labels", []), result.get("scores", []))
        }

        broad_score = score_map.get(labels[0], 0)
        atomic_score = score_map.get(labels[1], 0)

        print(
            f"    🧠 Scope Analysis for '{tag}': Broad={broad_score:.2f}, Atomic={atomic_score:.2f}"
        )

        if broad_score > atomic_score:
            return "Broad"
        return "Atomic"

    except Exception as e:
        import traceback

        print(f"    [Scope] Scope Analysis Failed: {type(e).__name__}: {e}")
        print(f"    Traceback: {traceback.format_exc()}")
        return "Broad"


async def classify_via_frontend(sio, socket_id, tag, candidates):
    if not candidates:
        return []

    if not socket_id:
        print(f"    [AI] No Client. Skipping AI Classification for: {tag}")
        return candidates

    # Labels: Integrity vs Distractors
    label_comprehensive = f"a comprehensive course primarily about {tag}"
    label_specific = f"a specific tutorial using {tag} for another topic"
    label_unrelated = "unrelated content"

    labels = [label_comprehensive, label_specific, label_unrelated]

    formatted_candidates = []
    for c in candidates:
        content_type_str = (
            "Playlist" if c["contentType"] == "Playlist" else "Single Video"
        )

        input_text = (
            f"Type: {content_type_str}. "
            f"Title: {c['title']}. "
            f"Channel: {c.get('channelTitle', '')}. "
            f"Duration: {c.get('duration_mins', 0)} mins. "
            f"Description: {c.get('description', '')[:200]}"
        )
        c["ai_input_text"] = input_text
        formatted_candidates.append(c)

    print(
        f"    [AI] Sending {len(formatted_candidates)} items to Frontend for NLI (Tag: {tag})..."
    )

    try:
        response = await _inference_batcher.schedule_inference(
            sio=sio,
            socket_id=socket_id,
            group_key=f"classify_{tag}",
            candidates=formatted_candidates,
            labels=labels,
            hypothesis_template="This content is {}.",
            timeout=12,
        )

        valid_items = []
        for item in response:
            scores = item.get("scores", [])
            resp_labels = item.get("labels", [])

            if not scores or not resp_labels:
                continue

            c_map = {l: s for l, s in zip(resp_labels, scores)}

            score_comprehensive = c_map.get(label_comprehensive, 0)
            score_specific = c_map.get(label_specific, 0)
            score_unrelated = c_map.get(label_unrelated, 0)

            max_score = -1
            max_label = "Unknown"
            for l, s in c_map.items():
                if s > max_score:
                    max_score = s
                    max_label = l

            item["ai_label"] = max_label
            item["ai_confidence"] = max_score

            richness_bonus = 0.0
            is_playlist = item.get("contentType") == "Playlist"
            video_count = item.get("videoCount", 0)
            duration = item.get("duration_mins", 0)
            desc = item.get("description", "").lower()

            if is_playlist and video_count >= 15:
                richness_bonus = 0.10

            has_timestamps = any(
                k in desc for k in ["timestamp", "chapter", "0:00", "00:00"]
            )
            if not is_playlist and (duration >= 60 or has_timestamps):
                richness_bonus = 0.10

            score_comprehensive += richness_bonus

            final_mult = 1.0
            if tag.lower() in item.get("title", "").lower():
                final_mult = 1.1

            c_map[label_comprehensive] = score_comprehensive * final_mult
            c_map[label_specific] = score_specific * final_mult

            margin_comp = score_comprehensive - score_unrelated
            margin_spec = score_specific - score_unrelated

            has_margin = (margin_comp > 0.15) or (margin_spec > 0.15)

            title_lower = item.get("title", "").lower()
            tag_words = tag.lower().split()

            title_has_tag = any(
                word in title_lower
                for word in tag_words
                if len(word) > 2 or (len(word) == 2 and word not in STOP_WORDS)
            )

            is_valid = has_margin and title_has_tag

            if is_valid:
                valid_items.append(item)
            else:
                reason = "low margin" if not has_margin else "title mismatch"
                print(
                    f"    [AI] Rejected '{item['title'][:30]}...' ({reason}, Label: {max_label})"
                )

        return valid_items

    except Exception as e:
        print(f"    [AI] Error during classification: {e}")
        return []


# Synonyms for common tag words that YouTube creators use interchangeably
_WORD_SYNONYMS = {
    "basics": {
        "tutorial",
        "fundamentals",
        "beginners",
        "introduction",
        "intro",
        "crash course",
        "beginner",
    },
    "fundamentals": {"basics", "tutorial", "introduction", "core", "beginner"},
    "tutorial": {"basics", "course", "guide", "lesson", "beginner"},
    "advanced": {"deep dive", "pro", "expert", "mastery", "in depth"},
    "introduction": {"intro", "basics", "beginner", "getting started", "101"},
    "intro": {"introduction", "basics", "beginner", "getting started"},
    "guide": {"tutorial", "course", "walkthrough", "handbook"},
    "course": {"tutorial", "guide", "full course", "bootcamp", "masterclass"},
    "overview": {"introduction", "basics", "summary", "crash course"},
    "essentials": {"basics", "fundamentals", "core", "tutorial", "beginner"},
    "concepts": {"fundamentals", "basics", "core", "tutorial"},
    "patterns": {"design patterns", "architecture", "best practices"},
    "architecture": {"design", "patterns", "structure", "clean code"},
    "workflow": {"pipeline", "process", "automation", "setup"},
    "containerization": {"docker", "containers", "container"},
    "security": {"auth", "authentication", "authorization", "secure"},
    "restful": {"rest", "rest api", "api"},
    "nosql": {"mongodb", "cassandra", "redis", "dynamo"},
    "databases": {"database", "db", "sql", "mongodb", "postgres"},
    "testing": {"test", "tests", "unit test", "jest", "pytest", "mocha"},
}

# Extra filler words to strip from descriptive tags (on top of STOP_WORDS)
_TAG_FILLER_WORDS = {
    "and",
    "with",
    "for",
    "using",
    "the",
    "a",
    "an",
    "from",
    "into",
    "about",
    "through",
    "via",
    "across",
    "between",
}


def _extract_core_words(tag_clean: str) -> list[str]:
    """Extract meaningful words from a descriptive tag, removing stop/filler words."""
    words = tag_clean.split()
    core = [
        w
        for w in words
        if w not in STOP_WORDS and w not in _TAG_FILLER_WORDS and len(w) > 1
    ]
    return core if core else words  # fallback to all words if everything was filtered


def is_relevant(tag, title, description):
    tag_clean = tag.lower().replace("-", " ").strip()
    title_clean = title.lower().replace("-", " ")
    text = (title_clean + " " + (description or "").lower()).strip()

    if any(nk in title_clean for nk in NEGATIVE_KEYWORDS):
        return False

    # Check 1: exact tag substring in title
    if tag_clean in title_clean:
        return True

    # Check 2: all words from tag present in title
    required_words = tag_clean.split()
    if all(word in title_clean for word in required_words):
        return True

    # Check 3: synonym-aware — allow synonym substitutions for tag words
    # e.g. tag="html basics" matches title="html tutorial for beginners"
    #      because "basics" -> synonym "tutorial" is in title
    if len(required_words) >= 2:
        all_match = True
        for word in required_words:
            if word in title_clean:
                continue  # direct match
            synonyms = _WORD_SYNONYMS.get(word, set())
            if any(syn in text for syn in synonyms):
                continue  # synonym match
            all_match = False
            break
        if all_match:
            return True

    # Check 4: core-word matching for descriptive/long tags
    # e.g. "Node.js and Express Framework Essentials" → core: ["node.js", "express", "framework", "essentials"]
    # If most core words (or their synonyms) match, accept it.
    core_words = _extract_core_words(tag_clean)
    if len(core_words) >= 2:
        matched = 0
        for word in core_words:
            if word in title_clean:
                matched += 1
                continue
            synonyms = _WORD_SYNONYMS.get(word, set())
            if any(syn in text for syn in synonyms):
                matched += 1
                continue
        # Require at least 50% of core words to match (minimum 2)
        threshold = max(2, math.ceil(len(core_words) * 0.67))
        if matched >= threshold:
            return True

    return False


def strict_relevance_score(tag, title, description):
    tag_clean = tag.lower().replace("-", " ").strip()
    title_clean = title.lower().replace("-", " ")
    desc_clean = (description or "").lower()
    text = f"{title_clean} {desc_clean}".strip()

    if not is_relevant(tag, title, description):
        return 0.0

    core_words = _extract_core_words(tag_clean)
    matched = 0
    for word in core_words:
        if word in text:
            matched += 1
            continue
        synonyms = _WORD_SYNONYMS.get(word, set())
        if any(syn in text for syn in synonyms):
            matched += 1

    ratio = matched / max(len(core_words), 1)
    score = ratio

    if tag_clean in title_clean:
        score += 0.35

    if core_words and all(word in title_clean for word in core_words if len(word) > 1):
        score += 0.25

    anchor_words = _extract_anchor_words(tag_clean)
    if anchor_words:
        anchor_matches = 0
        for word in anchor_words:
            if word in text:
                anchor_matches += 1
                continue
            synonyms = _WORD_SYNONYMS.get(word, set())
            if any(syn in text for syn in synonyms):
                anchor_matches += 1

        if anchor_matches == 0:
            return 0.0

        score += (anchor_matches / len(anchor_words)) * 0.25

    return min(score, 1.0)


def _extract_anchor_words(tag_clean: str) -> list[str]:
    return [
        word
        for word in _extract_core_words(tag_clean)
        if word not in _TAG_DESCRIPTOR_WORDS and len(word) > 2
    ]


def is_too_basic(title, description, user_level):
    if user_level == "beginner":
        return False

    text = (title + " " + description).lower()
    if any(k in text for k in BEGINNER_KEYWORDS):
        return True
    return False


def is_garbage_content(title, description):
    text = (title + " " + description).lower()
    if any(word in text for word in UNWANTED_KEYWORDS):
        return True

    # Regex Checks for specific scripts (Hindi, Cyrillic, etc.)
    if re.search(r"[\u0900-\u097F]", text):
        return True
    if re.search(r"[\u0400-\u04FF]", text):
        return True

    return False


def is_arabic_content(item_snippet):
    if "ar" in item_snippet.get("defaultAudioLanguage", "").lower():
        return True
    if "ar" in item_snippet.get("defaultLanguage", "").lower():
        return True

    title = item_snippet.get("title", "")
    description = item_snippet.get("description", "")
    full_text = f"{title} {description}"

    if re.search(r"[\u0600-\u06FF]", full_text):
        return True

    return False
