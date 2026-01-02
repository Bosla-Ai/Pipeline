import socketio

async def classify_via_frontend(sio: socketio.AsyncServer, socket_id: str, candidates: list, user_level: str):
    """
    Sends a list of candidates to the Frontend for AI classification.
    Waits for the Frontend to return ONLY the items matching 'user_level'.
    """
    
    if not candidates:
        return []

    print(f"📡 Sending {len(candidates)} items to Frontend ({socket_id}) for classification...")

    try:
        # This is the magic line. 
        # It sends the event and PAUSES here until the Frontend responds.
        filtered_results = await sio.call(
            event='request_inference',  # The event name the React hook listens for
            data={
                'candidates': candidates, 
                'user_level': user_level
            },
            to=socket_id,    # Target the specific user
            timeout=130       # Wait max 30 seconds
        )
        
        print(f"✅ Frontend returned {len(filtered_results)} valid items.")
        return filtered_results

    except TimeoutError:
        print("❌ Error: Frontend timed out (User might have closed the tab).")
        return []
    except Exception as e:
        print(f"❌ Error during classification: {e}")
        return []


async def is_relevant(tag: str, title: str, description: str) -> bool:
    """
    Determines if a video/course is relevant to the requested tag.
    Handles Case-Insensitivity and English-to-Arabic translation.
    """
    tag_clean = tag.lower().strip()
    title_clean = title.lower()
    desc_clean = description.lower() if description else ""

    # TODO: add any tags for programming search 
    translations = {
        "python": "بايثون",
        "java": "جافا",
        "javascript": "جافا سكريبت",
        "js": "جافا سكريبت",
        "c++": "سي بلس بلس",
        "c#": "سي شارب",
        "html": "تش تي ام ال",
        "css": "سي اس اس",
        "sql": "اس كيو ال",
        "database": "قواعد بيانات",
        "docker": "دوكر",
        "kubernetes": "كوبرنيتس",
        "git": "جيت",
        "github": "جيت هاب",
        "machine learning": "تعلم الالة",
        "artificial intelligence": "ذكاء اصطناعي",
        "deep learning": "تعلم عميق",
        "algorithm": "خوارزميات",
        "data structure": "هياكل بيانات",
        "network": "شبكات",
        "security": "امن سيبراني",
        "web": "ويب",
        "android": "اندرويد",
        "ios": "ايفون"
    }

    if tag_clean in title_clean:
        return True

    if tag_clean in translations:
        arabic_term = translations[tag_clean]
        if arabic_term in title_clean:
            return True

    if desc_clean.count(tag_clean) >= 2:
        return True

    return False