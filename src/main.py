from processors.classifier import classifier_result

result = classifier_result(
    input='C#',
    parameters=['.net','laravel','node']
)

# print(result['scores'])

from fetchers.videos.youtube_fetcher import fetch,classify_video_level
import json

results = fetch(['pytorch'], 'beginner')
# 2. Convert the list to a formatted JSON string
formatted_json = json.dumps(results, indent=4) 
# 3. Print the formatted string
print(formatted_json)