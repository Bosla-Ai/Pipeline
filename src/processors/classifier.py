def classifier_result(input, parameters):
    import requests
    from config.settings import HF_TOKEN

    API_URL = "https://router.huggingface.co/hf-inference/models/joeddav/xlm-roberta-large-xnli"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    def query(payload):
        response = requests.post(API_URL, headers=headers, json=payload)
        return response.json()

    output = query({
        "inputs": f"{input}",
        "parameters": {"candidate_labels": parameters},
    })
    
    return output