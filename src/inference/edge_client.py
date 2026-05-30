import asyncio
from src.inference.schemas import ClassificationRequest, ClassificationResult
from src.socket_server import sio, get_socket_for_job


class EdgeInferenceClient:
    """
    Edge inference client that communicates with the frontend socket
    to run classification/relevance tasks, with strict schema validation
    and zero candidate mutations.
    """

    @staticmethod
    async def classify(
        request: ClassificationRequest,
        timeout: float = 3.0,
    ) -> list[ClassificationResult]:
        """
        Sends candidates to the frontend for classification and validates the response.
        Returns a list of validated ClassificationResult objects.
        """
        if not request.candidates:
            return []

        socket_id = get_socket_for_job(request.job_id)
        if not socket_id:
            return []

        candidates_data = [c.to_dict() for c in request.candidates]

        try:
            response = await sio.call(
                event="request_inference",
                data={
                    "candidates": candidates_data,
                    "labels": request.labels,
                },
                to=socket_id,
                timeout=timeout,
            )
        except Exception:
            return []

        if not response or not isinstance(response, list):
            return []

        validated_results = []

        candidate_lookup = {}
        for c in request.candidates:
            if c.url:
                candidate_lookup[c.url.lower().strip()] = c
            if c.content_id:
                candidate_lookup[c.content_id.lower().strip()] = c

        for item in response[: len(request.candidates)]:
            if not isinstance(item, dict):
                continue

            candidate_key = (
                item.get("candidate_key") or item.get("url") or item.get("content_id")
            )
            if not candidate_key or not isinstance(candidate_key, str):
                continue

            cand_key_clean = candidate_key.lower().strip()
            if cand_key_clean not in candidate_lookup:
                continue

            label = item.get("label")
            if not label or label not in request.labels:
                continue

            try:
                raw_confidence = item.get("confidence")
                if raw_confidence is None:
                    continue
                confidence = float(raw_confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                continue

            validated_results.append(
                ClassificationResult(
                    candidate_key=candidate_key,
                    label=label,
                    confidence=confidence,
                    raw=item,
                )
            )

        return validated_results
