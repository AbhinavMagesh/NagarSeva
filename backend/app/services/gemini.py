import base64
import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings


def _is_retryable(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code == 429 or error.response.status_code >= 500)
    )


retry_provider = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)


class GeminiService:
    def _require_key(self) -> str:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is missing; configure it in backend/.env.")
        return settings.gemini_api_key

    @retry_provider
    async def generate_json(self, prompt: str, images: list[tuple[bytes, str]] | None = None) -> dict[str, Any]:
        contents: list[dict[str, Any]] = [{"text": prompt}]
        for image_bytes, mime_type in images or []:
            contents.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            })
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                url,
                params={"key": self._require_key()},
                json={
                    "contents": [{"parts": contents}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2,
                    },
                },
            )
            response.raise_for_status()
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Gemini returned an invalid structured response.") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Gemini returned a response that was not a JSON object.")
        return result

    @retry_provider
    async def embedding(self, text: str) -> list[float]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_embedding_model}:embedContent"
        )
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                params={"key": self._require_key()},
                json={
                    "model": f"models/{settings.gemini_embedding_model}",
                    "content": {"parts": [{"text": text}]},
                    "output_dimensionality": 768,
                },
            )
            response.raise_for_status()
        try:
            values = response.json()["embedding"]["values"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Gemini returned an invalid embedding response.") from exc
        if len(values) != 768:
            raise RuntimeError(f"Expected a 768-dimensional embedding, received {len(values)} values.")
        return values


gemini = GeminiService()
