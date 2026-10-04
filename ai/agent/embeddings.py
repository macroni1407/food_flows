"""Jina embeddings. Reviews are embedded as passages, questions as queries."""
import time

import requests

from . import settings

BATCH_SIZE = 64


def embed(texts, task):
    """task: 'retrieval.passage' for stored review texts, 'retrieval.query' for questions."""
    vectors = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        payload = {
            "model": settings.EMBEDDING_MODEL,
            "task": task,
            "normalized": True,
            "input": [{"text": text} for text in batch],
        }
        for attempt in range(3):
            try:
                response = requests.post(
                    settings.JINA_URL,
                    headers={"Authorization": f"Bearer {settings.JINA_API_KEY}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))  # stable if absent
        vectors.extend(item["embedding"] for item in data)
    return vectors
