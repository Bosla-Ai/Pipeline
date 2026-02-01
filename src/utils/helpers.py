import re
from src.utils.constants import (
    NEGATIVE_KEYWORDS,
    BEGINNER_KEYWORDS,
    UNWANTED_KEYWORDS,
    KNOWN_BROAD_TOPICS,
)


async def analyze_topic_scope(sio, socket_id, tag):
    """Classifies topic scope: 'Broad' (Playlist preferred) vs 'Atomic' (Video viable)."""
    if not socket_id:
        return "Broad"  # Default permissive

    if tag.lower() in KNOWN_BROAD_TOPICS:
        print(f"    🛡️ Safety Net: '{tag}' is a known Broad topic. Skipping AI.")
        return "Broad"

    labels = [
        "an entire programming language, framework, or major technology",
        "a specific programming concept, error, or technique",
    ]

    try:
        response = await sio.call(
            event="request_inference",
            data={
                "candidates": [{"ai_input_text": f"The technical topic is {tag}."}],
                "labels": labels,
                "hypothesis_template": "{}",
            },
            to=socket_id,
            timeout=10,
        )

        if not response:
            return "Atomic"

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

        print(f"⚠️ Scope Analysis Failed: {type(e).__name__}: {e}")
        print(f"    📋 Traceback: {traceback.format_exc()}")
        return "Atomic"


async def classify_via_frontend(sio, socket_id, tag, candidates):
    if not candidates:
        return []

    if not socket_id:
        print(f"⚠️ No Client. Skipping AI Classification for: {tag}")
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
        f"📡 Sending {len(formatted_candidates)} items to Frontend for NLI (Tag: {tag})..."
    )

    try:
        response = await sio.call(
            event="request_inference",
            data={
                "candidates": formatted_candidates,
                "labels": labels,
                "hypothesis_template": "This content is {}.",
            },
            to=socket_id,
            timeout=30,
        )

        valid_items = []
        for item in response:
            scores = item.get("scores", [])
            resp_labels = item.get("labels", [])

            if not scores or not resp_labels:
                continue

            # 1. Map Labels -> Scores
            c_map = {l: s for l, s in zip(resp_labels, scores)}

            score_comprehensive = c_map.get(label_comprehensive, 0)
            score_specific = c_map.get(label_specific, 0)
            score_unrelated = c_map.get(label_unrelated, 0)

            # 2. Assign Max Label for Debugging
            max_score = -1
            max_label = "Unknown"
            for l, s in c_map.items():
                if s > max_score:
                    max_score = s
                    max_label = l

            item["ai_label"] = max_label
            item["ai_confidence"] = max_score

            # 3. Stricter Acceptance: Margin + Title Keyword Check
            margin_comp = score_comprehensive - score_unrelated
            margin_spec = score_specific - score_unrelated

            # Must have meaningful margin over "unrelated"
            has_margin = (margin_comp > 0.15) or (margin_spec > 0.15)

            # Title must contain tag keywords (prevents "looping animation" for "for loops")
            title_lower = item.get("title", "").lower()
            tag_words = tag.lower().split()

            # Allow 2-char words (like "c#", "ai", "js") but filter out common stop words
            STOP_WORDS = {
                "in",
                "on",
                "at",
                "to",
                "of",
                "is",
                "it",
                "by",
                "an",
                "or",
                "if",
                "do",
                "up",
                "my",
                "me",
                "we",
            }

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
                    f"    ❌ Rejected '{item['title'][:30]}...' ({reason}, Label: {max_label})"
                )

        return valid_items

    except Exception as e:
        print(f"❌ Error during classification: {e}")
        return []


def is_relevant(tag, title, description):
    tag_clean = tag.lower().replace("-", " ").strip()
    title_clean = title.lower().replace("-", " ")

    if any(nk in title_clean for nk in NEGATIVE_KEYWORDS):
        return False

    if tag_clean in title_clean:
        return True
    required_words = tag_clean.split()
    if all(word in title_clean for word in required_words):
        return True

    return False


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
