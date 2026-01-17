import socketio
import asyncio

sio = socketio.AsyncClient()


@sio.event
async def connect():
    print("✅ Mock Frontend Connected")
    pass


@sio.event
async def request_inference(data):
    print(f"📩 Received inference request for {len(data['candidates'])} items.")

    results = []
    for cand in data["candidates"]:
        title = cand["title"].lower()
        tag_in_logic = data["labels"][0].split("about ")[
            -1
        ]  # extracting tag roughly if needed

        # Simulate Logic
        # Label 0: Primary
        # Label 1: Distractor
        # Label 2: Unrelated

        scores = [0.1, 0.1, 0.8]  # Default unrelated

        if "microservices" in title:
            # Distractor
            scores = [0.1, 0.8, 0.1]
        elif "random" in title:
            # Unrelated
            scores = [0.0, 0.0, 1.0]
        else:
            # Assume Target if not the above (e.g. "ASP.NET Core Full Course")
            scores = [0.9, 0.05, 0.05]

        results.append(
            {
                "sequence": cand.get("sequence"),
                "scores": scores,
                "title": cand["title"],
                "contentType": cand["contentType"],
            }
        )

    print("📤 Sending Mock Response...")
    return results


@sio.event
async def request_language_detection(data):
    print(
        f"📩 Received Language Detection request for {len(data['candidates'])} items. Target: {data.get('target_language')}"
    )

    # Simulate Language Detection
    valid_items = []
    for cand in data["candidates"]:
        # Mock logic: Assume everything is Arabic if it has 'ar' or arabic chars
        # For simplicity, let's just accept everything in this mock unless title says "English"
        if "english" in cand["title"].lower():
            print(f"    ❌ Detected non-target language for: {cand['title']}")
            continue
        valid_items.append(cand)

    print(f"📤 Sending Mock Lang Response ({len(valid_items)} items)...")
    return valid_items


async def main():
    await sio.connect("http://localhost:8000")
    await sio.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
