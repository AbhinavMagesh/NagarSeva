import base64
import json
import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger("nagarseva.gemini")


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

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self._require_key(),
            "Content-Type": "application/json",
        }

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
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                params={"key": self._require_key()},
                json={
                    "contents": [{"parts": contents}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2,
                    },
                },
            )
            if response.is_error:
                try:
                    err_payload = response.json()
                    err_msg = err_payload.get("error", {}).get("message", response.text)
                except Exception:
                    err_msg = response.text
                logger.error("Gemini generate_json failed (%s): %s", response.status_code, err_msg)
                raise RuntimeError(f"Gemini API error ({response.status_code}): {err_msg}")

        try:
            candidates = response.json().get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", [])
            text = next(p["text"] for p in parts if "text" in p).strip()
            if text.startswith("```"):
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(text)
        except (KeyError, IndexError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            logger.error("Failed to parse Gemini response: %s", response.text)
            raise RuntimeError("Gemini returned an invalid structured response.") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Gemini returned a response that was not a JSON object.")
        return result

    @retry_provider
    async def generate_text(self, prompt: str) -> str:
        """Generate plain text from a prompt (no JSON parsing)."""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                params={"key": self._require_key()},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                    },
                },
            )
            if response.is_error:
                try:
                    err_payload = response.json()
                    err_msg = err_payload.get("error", {}).get("message", response.text)
                except Exception:
                    err_msg = response.text
                logger.error("Gemini generate_text failed (%s): %s", response.status_code, err_msg)
                raise RuntimeError(f"Gemini API error ({response.status_code}): {err_msg}")

        try:
            candidates = response.json().get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", [])
            text_result = next(p["text"] for p in parts if "text" in p).strip()
        except (KeyError, IndexError, StopIteration, TypeError) as exc:
            logger.error("Failed to parse Gemini text response: %s", response.text)
            raise RuntimeError("Gemini returned an invalid text response.") from exc
        return text_result

    @retry_provider
    async def embedding(self, text: str) -> list[float]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_embedding_model}:embedContent"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                params={"key": self._require_key()},
                json={
                    "model": f"models/{settings.gemini_embedding_model}",
                    "content": {"parts": [{"text": text}]},
                    "output_dimensionality": 768,
                },
            )
            if response.is_error:
                try:
                    err_payload = response.json()
                    err_msg = err_payload.get("error", {}).get("message", response.text)
                except Exception:
                    err_msg = response.text
                logger.error("Gemini embedding failed (%s): %s", response.status_code, err_msg)
                raise RuntimeError(f"Gemini embedding error ({response.status_code}): {err_msg}")

        try:
            values = response.json()["embedding"]["values"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Gemini returned an invalid embedding response.") from exc
        if len(values) != 768:
            raise RuntimeError(f"Expected a 768-dimensional embedding, received {len(values)} values.")
        return values


gemini = GeminiService()
