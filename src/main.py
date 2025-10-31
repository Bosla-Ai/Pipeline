from processors.classifier import classifier_result

result = classifier_result(
    input='C#',
    parameters=['.net','laravel','node']
)

print(result)

from fetchers.youtube_fetcher import fetch

# print(fetch(['C#']))