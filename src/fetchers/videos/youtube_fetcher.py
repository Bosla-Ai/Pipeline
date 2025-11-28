import requests
import math
import re
from datetime import datetime, timezone
from langdetect import detect, LangDetectException
from src.config.settings import YOUTUBE_API_KEY
from src.utils.helpers import classify_via_frontend

def is_arabic_content(item_snippet):
    """Checks for Arabic audio, NLP detection, or Regex characters."""
    title = item_snippet.get("title", "")
    description = item_snippet.get("description", "")
    
    # 1. API Metadata
    if 'ar' in item_snippet.get("defaultAudioLanguage", "").lower(): return True
    if 'ar' in item_snippet.get("defaultLanguage", "").lower(): return True

    # 2. NLP & Regex
    full_text = f"{title} {description}"
    try:
        if detect(full_text) == 'ar': return True
    except LangDetectException:
        pass
        
    return bool(re.search(r'[\u0600-\u06FF]', full_text))

def is_relevant(tag, title, description):
    """
    Topic Guard: Ensures the video is actually about the requested tag.
    e.g. If searching for 'Docker', the title MUST contain 'Docker'.
    """
    # Normalize strings (lowercase)
    tag_clean = tag.lower().strip()
    title_clean = title.lower()
    desc_clean = description.lower()
    
    # Check 1: Strong Match in Title (Best)
    if tag_clean in title_clean:
        return True
        
    # Check 2: If not in title, check description but be careful.
    # We only accept description match if the title is generic? 
    # For now, let's say if it's not in the title, it's risky, 
    # but we allow it if it appears TWICE in description to avoid casual mentions.
    if desc_clean.count(tag_clean) >= 2:
        return True
        
    return False

async def fetch(sio, socket_id, tags, user_level, language='en', max_results=5):
    if not tags: return {}

    search_url = "https://www.googleapis.com/youtube/v3/search"
    video_details_url = "https://www.googleapis.com/youtube/v3/videos"
    playlist_details_url = "https://www.googleapis.com/youtube/v3/playlists"
    
    final_roadmap = {} 
    
    arabic_levels = { "beginner": "للمبتدئين", "intermediate": "متوسط", "advanced": "متقدم" }
    
    for tag in tags:
        print(f"\n--- Processing tag: {tag} ({language}) ---")
        candidates = [] 
        
        # Query Builder
        if language == 'ar':
            level_ar = arabic_levels.get(user_level, "")
            search_query_playlist = f'كورس {tag} {level_ar} شرح'
            search_query_video = f'شرح {tag} {level_ar}'
            api_lang = 'ar'
        else:
            search_query_playlist = f'{tag} {user_level} full course'
            search_query_video = f'{tag} {user_level} full tutorial'
            api_lang = 'en'

        # =================================================
        # 1. Search Playlists
        # =================================================
        try:
            pl_resp = requests.get(search_url, params={
                "part": "snippet", "q": search_query_playlist, "type": "playlist",
                "maxResults": max_results + 5, # Fetch MORE to allow for filtering
                "key": YOUTUBE_API_KEY, "relevanceLanguage": api_lang
            }).json()
            
            playlist_ids = [i["id"]["playlistId"] for i in pl_resp.get("items", [])]
            
            if playlist_ids:
                details_resp = requests.get(playlist_details_url, params={
                    "part": "snippet,contentDetails", "id": ",".join(playlist_ids), "key": YOUTUBE_API_KEY
                }).json()
                
                for item in details_resp.get("items", []):
                    title = item["snippet"]["title"]
                    desc = item["snippet"].get("description", "")

                    # --- FILTER 1: TOPIC GUARD ---
                    if not is_relevant(tag, title, desc):
                        print(f"    🗑️ Skipped Irrelevant: {title}")
                        continue
                        
                    # --- FILTER 2: LANGUAGE ---
                    if language == 'ar' and not is_arabic_content(item["snippet"]):
                        print(f"    🗑️ Skipped Non-Arabic: {title}")
                        continue

                    data = {
                        "contentType": "Playlist",
                        "contentId": item["id"],
                        "url": f"https://www.youtube.com/playlist?list={item['id']}",
                        "title": title,
                        "description": desc,
                        "channelTitle": item["snippet"]["channelTitle"],
                        "publishedAt": item["snippet"]["publishedAt"],
                        "videoCount": int(item["contentDetails"].get("itemCount", 0)),
                    }
                    data["score"] = calculate_playlist_score(data)
                    candidates.append(data)
        except Exception as e:
            print(f"    Error searching playlists: {e}")

        # =================================================
        # 2. Fallback to Videos
        # =================================================
        if len(candidates) < 2:
            print(f"    ⚠️ Few playlists found, checking Videos...")
            try:
                vid_resp = requests.get(search_url, params={
                    "part": "snippet", "q": search_query_video, "type": "video", 
                    "videoDuration": "long", "maxResults": max_results + 5,
                    "key": YOUTUBE_API_KEY, "relevanceLanguage": api_lang
                }).json()
                
                video_ids = [i["id"]["videoId"] for i in vid_resp.get("items", [])]
                
                if video_ids:
                    stats_resp = requests.get(video_details_url, params={
                        "part": "snippet,statistics", "id": ",".join(video_ids), "key": YOUTUBE_API_KEY
                    }).json()
                    
                    for item in stats_resp.get("items", []):
                        title = item["snippet"]["title"]
                        desc = item["snippet"].get("description", "")
                        
                        # --- FILTERS ---
                        if not is_relevant(tag, title, desc): continue
                        if language == 'ar' and not is_arabic_content(item["snippet"]): continue
                        
                        stats = item.get("statistics", {})
                        data = {
                            "contentType": "Video",
                            "contentId": item["id"],
                            "url": f"https://www.youtube.com/watch?v={item['id']}",
                            "title": title,
                            "description": desc,
                            "channelTitle": item["snippet"]["channelTitle"],
                            "publishedAt": item["snippet"]["publishedAt"],
                            "viewCount": int(stats.get("viewCount", 0)),
                            "likeCount": int(stats.get("likeCount", 0))
                        }
                        data["score"] = calculate_video_score(data)
                        candidates.append(data)
            except Exception as e:
                print(f"    Error searching videos: {e}")

        # =================================================
        # 3. Classify & Select Winner
        # =================================================
        if candidates:
            # Sort raw candidates by score first
            candidates.sort(key=lambda x: x["score"], reverse=True)
            top_candidates = candidates[:5]

            valid_items = await classify_via_frontend(sio, socket_id, top_candidates, user_level)
            
            if valid_items:
                valid_items.sort(key=lambda x: x["score"], reverse=True)
                winner = valid_items[0]
                final_roadmap[tag] = winner
                print(f"🏆 Winner for '{tag}': {winner['title']}")
            else:
                print(f"⚠️ AI rejected items for '{tag}'. Fallback to highest scorer.")
                final_roadmap[tag] = top_candidates[0]
        else:
            final_roadmap[tag] = None

    return final_roadmap

# --- Score Functions ---
def calculate_video_score(video):
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)
    if views < 1000 or likes == 0: return 0
    engagement = (math.log10(likes) / math.log10(views)) * 10
    published_date = datetime.fromisoformat(video["publishedAt"].replace('Z', '+00:00'))
    if published_date.tzinfo is None: published_date = published_date.replace(tzinfo=timezone.utc)
    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))
    return engagement * freshness

def calculate_playlist_score(playlist):
    count = playlist.get("videoCount", 0)
    pub_at = playlist.get("publishedAt", "")
    if not pub_at or count == 0: return 0
    count_score = (min(count, 50.0) / 50.0) * 10
    published_date = datetime.fromisoformat(pub_at.replace('Z', '+00:00'))
    if published_date.tzinfo is None: published_date = published_date.replace(tzinfo=timezone.utc)
    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))
    return (count_score * 0.7) + (freshness * 3.0)