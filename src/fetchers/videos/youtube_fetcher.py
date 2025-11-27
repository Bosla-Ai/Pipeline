import requests
import math
from datetime import datetime, timezone
from config.settings import YOUTUBE_API_KEY
from utils.helpers import classify_via_frontend

async def fetch(sio, socket_id, tags, user_level, max_results=3):
    """
    Fetches content (Playlists preferred, Long Video fallback),
    Scores them, and uses Frontend AI to classify/filter by user level.
    """
    if not tags:
        print("No tags provided, skipping fetch.")
        return {}

    search_url = "https://www.googleapis.com/youtube/v3/search"
    video_details_url = "https://www.googleapis.com/youtube/v3/videos"
    playlist_details_url = "https://www.googleapis.com/youtube/v3/playlists"
    
    all_content = {}
    
    # Prepare level string for better search query relevance
    level_query_string = ""
    if user_level and user_level in ['beginner', 'intermediate', 'advanced']:
        level_query_string = user_level

    for tag in tags:
        print(f"\n--- Processing tag: {tag} ---")
        candidates = [] 
        
        # =========================================================
        # STRATEGY 1: Try to find PLAYLISTS
        # =========================================================
        search_query = f'{tag} {level_query_string} full course tutorial'
        print(f"  [Strategy 1] Searching Playlists for: {search_query}")

        search_params_playlist = {
            "part": "snippet",
            "q": search_query,
            "type": "playlist",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        }

        playlist_ids = []
        try:
            pl_search_resp = requests.get(search_url, params=search_params_playlist).json()
            if "items" in pl_search_resp:
                playlist_ids = [item["id"]["playlistId"] for item in pl_search_resp["items"]]
        except requests.exceptions.RequestException as e:
            print(f"    Request failed: {e}")

        # --- Process Playlists if found ---
        if playlist_ids:
            try:
                pl_details_resp = requests.get(playlist_details_url, params={
                    "part": "snippet,contentDetails",
                    "id": ",".join(playlist_ids),
                    "key": YOUTUBE_API_KEY,
                }).json()
                
                for item in pl_details_resp.get("items", []):
                    snippet = item["snippet"]
                    details = item["contentDetails"]
                    
                    data = {
                        "contentType": "Playlist",
                        "contentId": item["id"],
                        "url": f"https://www.youtube.com/playlist?list={item['id']}",
                        "title": snippet["title"],
                        "description": snippet.get("description", ""),
                        "channelTitle": snippet["channelTitle"],
                        "publishedAt": snippet["publishedAt"],
                        "videoCount": int(details.get("itemCount", 0)),
                        "language": snippet.get("defaultLanguage", "en").split('-')[0]
                    }
                    data["score"] = calculate_playlist_score(data)
                    candidates.append(data)
            except Exception as e:
                print(f"    Error details playlists: {e}")

        # =========================================================
        # STRATEGY 2: Fallback to LONG VIDEOS (only if no playlists)
        # =========================================================
        if not candidates:
            print(f"  [Strategy 2] Fallback: Searching Long Videos for '{tag}'...")
            video_query = f'{tag} {level_query_string} full tutorial' 
            
            try:
                vid_search_resp = requests.get(search_url, params={
                    "part": "snippet",
                    "q": video_query,
                    "type": "video",
                    "videoDuration": "long", # > 20 mins
                    "maxResults": max_results,
                    "key": YOUTUBE_API_KEY,
                }).json()
                
                video_ids = [item["id"]["videoId"] for item in vid_search_resp.get("items", [])]
                
                if video_ids:
                    vid_details_resp = requests.get(video_details_url, params={
                        "part": "snippet,statistics",
                        "id": ",".join(video_ids),
                        "key": YOUTUBE_API_KEY,
                    }).json()
                    
                    for item in vid_details_resp.get("items", []):
                        snippet = item["snippet"]
                        stats = item.get("statistics", {})
                        
                        data = {
                            "contentType": "Video",
                            "contentId": item["id"],
                            "url": f"https://www.youtube.com/watch?v={item['id']}",
                            "title": snippet["title"],
                            "description": snippet.get("description", ""),
                            "channelTitle": snippet["channelTitle"],
                            "publishedAt": snippet["publishedAt"],
                            "viewCount": int(stats.get("viewCount", 0)),
                            "likeCount": int(stats.get("likeCount", 0)),
                            "commentCount": int(stats.get("commentCount", 0)),
                            "language": snippet.get("defaultAudioLanguage", "en").split('-')[0]
                        }
                        data["score"] = calculate_video_score(data)
                        candidates.append(data)

            except Exception as e:
                print(f"    Error processing video details: {e}")

        # =========================================================
        # STEP 3: CLASSIFY via FRONTEND (Socket)
        # =========================================================
        if candidates:
            print(f"  Asking Frontend to classify {len(candidates)} candidates...")
            # This calls the helper function to run inference on the client
            classified_results = await classify_via_frontend(sio, socket_id, candidates, user_level)
            
            # Sort by score
            classified_results.sort(key=lambda x: x["score"], reverse=True)
            
            # Store filterd list
            all_content[tag] = classified_results
            print(f"  Approved {len(classified_results)} items for '{tag}'.")
        else:
            all_content[tag] = []

    return all_content


def calculate_video_score(video):
    """
    Calculates score based on engagement (likes/views ratio) and freshness.
    """
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)
    
    if views < 1000 or likes == 0:
        return 0

    # Engagement Score (0-10)
    engagement_score = (math.log10(likes) / math.log10(views)) * 10
    
    # Freshness Score
    published_date = datetime.fromisoformat(video["publishedAt"].replace('Z', '+00:00'))
    if published_date.tzinfo is None:
         published_date = published_date.replace(tzinfo=timezone.utc)
         
    days_old = (datetime.now(timezone.utc) - published_date).days
    if days_old < 0: days_old = 0
            
    # Half-life of 5 years
    T_HALF_DAYS = 365 * 5 
    freshness_score = math.exp(-math.log(2) * (days_old / T_HALF_DAYS))
    
    return engagement_score * freshness_score

def calculate_playlist_score(playlist):
    """
    Calculates score based on completeness (video count) and freshness.
    """
    video_count = playlist.get("videoCount", 0)
    published_at_str = playlist.get("publishedAt", "")
    
    if not published_at_str or video_count == 0:
        return 0
        
    # Completeness Score (0-10) - Ideal is 50 videos
    MAX_VIDEOS_FOR_SCORE = 50.0
    video_count_score = (min(video_count, MAX_VIDEOS_FOR_SCORE) / MAX_VIDEOS_FOR_SCORE) * 10

    # Freshness Score
    published_date = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
    if published_date.tzinfo is None:
         published_date = published_date.replace(tzinfo=timezone.utc)
         
    days_old = (datetime.now(timezone.utc) - published_date).days
    if days_old < 0: days_old = 0
            
    T_HALF_DAYS = 365 * 5 
    freshness_score = math.exp(-math.log(2) * (days_old / T_HALF_DAYS))

    # Weighted Score: 70% Completeness, 30% Freshness
    return (video_count_score * 0.7) + (freshness_score * 3.0)