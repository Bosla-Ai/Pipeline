import re
from src.utils.constants import NEGATIVE_KEYWORDS, BEGINNER_KEYWORDS, UNWANTED_KEYWORDS


async def classify_via_frontend(sio, socket_id, tag, candidates):
    if not candidates:
        return []

    if not socket_id:
        print(
            f"⚠️ No React Client connected. Skipping AI Classification for tag: {tag}"
        )
        return candidates

    # New Labels focused on Topic Centrality vs Distractors
    labels = [
        f"a comprehensive course primarily about {tag}",  # Target
        f"a specific tutorial using {tag} for another topic",  # Distractor
        "unrelated content",  # Garbage
    ]

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
            if not scores:
                continue

            # Label 0: Primary Topic (Target)
            # Label 1: Distractor
            # Label 2: Unrelated

            primary_score = scores[0]
            distractor_score = scores[1]
            unrelated_score = scores[2]

            # Logic: Must be primarily about the tag relative to other options
            if primary_score > distractor_score and primary_score > unrelated_score:
                valid_items.append(item)
            else:
                print(
                    f"    ❌ Rejected '{item['title'][:30]}...' (Primary: {primary_score:.2f}, Distractor: {distractor_score:.2f})"
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
