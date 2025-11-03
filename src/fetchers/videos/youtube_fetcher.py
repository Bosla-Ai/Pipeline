def fetch(tags, user_level, max_results=10):
    """
    Fetches both videos AND playlists for a list of tags.
    Scores them separately and returns a combined, scored list.
    """
    import requests
    from config.settings import YOUTUBE_API_KEY
    
    if not tags:
        print("No tags provided, skipping fetch.")
        return []

    search_url = "https://www.googleapis.com/youtube/v3/search"
    video_details_url = "https://www.googleapis.com/youtube/v3/videos"
    playlist_details_url = "https://www.googleapis.com/youtube/v3/playlists"
    
    all_content = []
    video_ids = []
    playlist_ids = []
    
    level_query_string = ""
    if user_level and user_level in ['beginner', 'intermediate', 'advanced']:
        level_query_string = user_level

    # --- Step 1: Search for BOTH videos and playlists ---
    search_query = f'{" ".join(tags)} {level_query_string} tutorial course'
    print(f"Searching for: {search_query}")

    search_params = {
        "part": "snippet",
        "q": search_query,
        "type": "video,playlist",
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }

    search_response = requests.get(search_url, params=search_params).json()
    
    for item in search_response.get("items", []):
        item_id = item.get("id", {})
        if item_id.get("kind") == "youtube#video":
            video_ids.append(item_id.get("videoId"))
        elif item_id.get("kind") == "youtube#playlist":
            playlist_ids.append(item_id.get("playlistId"))

    # --- Step 2: Process Videos ---
    if video_ids:
        stats_params = {
            "part": "snippet,statistics", # Snippet contains the language
            "id": ",".join(video_ids),
            "key": YOUTUBE_API_KEY,
        }
        stats_response = requests.get(video_details_url, params=stats_params).json()

        for item in stats_response.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            video_id = item["id"]
            
            language_code = snippet.get("defaultAudioLanguage", snippet.get("defaultLanguage"))
            
            # video langauge detection
            if language_code:
                language = language_code.split('-')[0]
            else:
                language = "unknown" 

            video_data = {
                "contentType": "Video",
                "contentId": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "channelTitle": snippet["channelTitle"],
                "publishedAt": snippet["publishedAt"],
                "language": language, 
                "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
                "commentCount": int(stats.get("commentCount", 0)),
            }
            video_data["score"] = calculate_video_score(video_data)
            all_content.append(video_data)

    # --- Step 3: Process Playlists ---
    if playlist_ids:
        playlist_params = {
            "part": "snippet,contentDetails",
            "id": ",".join(playlist_ids),
            "key": YOUTUBE_API_KEY,
        }
        playlist_response = requests.get(playlist_details_url, params=playlist_params).json()

        for item in playlist_response.get("items", []):
            snippet = item["snippet"]
            details = item["contentDetails"]
            playlist_id = item["id"]
            
            # Playlists language detection
            language_code = snippet.get("defaultLanguage")
            if language_code:
                language = language_code.split('-')[0]
            else:
                language = "unknown" 

            playlist_data = {
                "contentType": "Playlist",
                "contentId": playlist_id,
                "url": f"https://www.youtube.com/playlist?list={playlist_id}",
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "channelTitle": snippet["channelTitle"],
                "publishedAt": snippet["publishedAt"],
                "language": language, # <-- ADDED
                "videoCount": int(details.get("itemCount", 0)),
            }
            playlist_data["score"] = calculate_playlist_score(playlist_data)
            all_content.append(playlist_data)
            
    # --- Step 4: Return combined, sorted list (best content first) ---
    all_content.sort(key=lambda x: x["score"], reverse=True)
    
    return all_content

def classify_video_level(title, description):
    """
    Classifying videos level 
    """
    from processors.classifier import classifier_result
    text = f"{title} {description}".lower()

    levels = ['beginner','intermediate','advanced']
    
    result = classifier_result(text,levels)
    
    # checking existence 
    if not result or 'scores' not in result or 'labels' not in result:
        return None    
    
    idx = max(range(len(result['scores'])), key=lambda i: result['scores'][i])
            
    return levels[idx]


def calculate_video_score(video):
    """
    Calculates a "learning quality" score for a video.
    Score is primarily based on engagement, with a small modifier for freshness.
    """
    from datetime import datetime, timezone
    import math
    
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)
    
    # 1. Reliability Threshold: Filter out noise
    MIN_VIEW_THRESHOLD = 1000
    if views < MIN_VIEW_THRESHOLD or likes == 0:
        return 0

    # 2. Engagement Score (0-10): This is now the most important part.
    # log10(likes) / log10(views) * 10 
    engagement_score = (math.log10(likes) / math.log10(views)) * 10
    
    # 3. Freshness Score (0.0 - 1.0): Now has low importance.
    published_date = datetime.fromisoformat(video["publishedAt"].replace('Z', '+00:00'))
    
    if published_date.tzinfo is None:
         published_date = published_date.replace(tzinfo=timezone.utc)
         
    days_old = (datetime.now(timezone.utc) - published_date).days
    
    if days_old < 0: 
        days_old = 0
            
    # We set a "half-life" to 5 years (approx. 1825 days).
    # A 5-year-old video's score is only cut by 50%.
    T_HALF_DAYS = 365 * 5 
    
    freshness_score = math.exp(-math.log(2) * (days_old / T_HALF_DAYS))
    
    # 5. Final Score
    final_score = engagement_score * freshness_score
    
    return final_score

def calculate_playlist_score(playlist):
    """
    Calculates a "learning quality" score for a playlist.
    Score is based on video count (a proxy for a "full course") and freshness.
    """
    from datetime import datetime, timezone
    import math
        
    video_count = playlist.get("videoCount", 0)
    published_at_str = playlist.get("publishedAt", "")
    
    if not published_at_str or video_count == 0:
        return 0
        
    # 1. Video Count Score (0-10)
    # We'll say a "perfect" course has 50 videos. 
    # This gives a 0-10 score based on how complete the course is.
    MAX_VIDEOS_FOR_SCORE = 50.0
    video_count_score = (min(video_count, MAX_VIDEOS_FOR_SCORE) / MAX_VIDEOS_FOR_SCORE) * 10

    # 2. Freshness Score (0.0 - 1.0)
    # We use the same 5-year half-life as videos
    published_date = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
    if published_date.tzinfo is None:
         published_date = published_date.replace(tzinfo=timezone.utc)
         
    days_old = (datetime.now(timezone.utc) - published_date).days
    if days_old < 0: days_old = 0
            
    T_HALF_DAYS = 365 * 5 
    freshness_score = math.exp(-math.log(2) * (days_old / T_HALF_DAYS))

    # 3. Final Score
    # We weigh the "completeness" (video count) more than freshness.
    final_score = (video_count_score * 0.7) + (freshness_score * 3.0) # Weighted to 0-10
    
    return final_score