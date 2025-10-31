def fetch(tags, max_results=5):
    import requests
    from config.settings import YOUTUBE_API_KEY
    """
    Fetch YouTube videos for a list of tags (keywords).
    Returns combined response data with key metadata.
    """
    base_url = "https://www.googleapis.com/youtube/v3/search"
    video_details_url = "https://www.googleapis.com/youtube/v3/videos"
    all_videos = []

    for tag in tags:
        print(f"Searching for: {tag}")
        params = {
            "part": "snippet",
            "q": tag,
            "type": "video",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        }

        # Step 1: Search videos by tag
        search_response = requests.get(base_url, params=params)
        search_data = search_response.json()

        # Extract video IDs
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            continue

        # Step 2: Get video details (stats)
        stats_params = {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": YOUTUBE_API_KEY,
        }

        stats_response = requests.get(video_details_url, params=stats_params)
        stats_data = stats_response.json()
        
        # Step 3: Combine metadata
        for item in stats_data.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            all_videos.append({
                "videoId": item["id"],
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "tags": snippet.get("tags", []),
                "channelTitle": snippet["channelTitle"],
                "publishedAt": snippet["publishedAt"],
                "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
                "commentCount": int(stats.get("commentCount", 0)),
            })

    return all_videos

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
    views = video["viewCount"]
    likes = video["likeCount"]
    comments = video["commentCount"]

    # TODO: continue implement logical scoring 