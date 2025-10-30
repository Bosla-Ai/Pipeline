from processors.classifier import classifier_result

result = classifier_result(
    input='C#',
    parameters=['.net','laravel','node']
)

print(max(result['scores']))