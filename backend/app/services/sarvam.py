import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings


def _is_retryable(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code == 429 or error.response.status_code >= 500)
    )


class SarvamService:
    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def transcribe_and_translate(self, audio: bytes, filename: str, mime_type: str, language: str) -> dict:
        if not settings.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY is missing; configure it in backend/.env.")
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.sarvam.ai/speech-to-text",
                headers={"API-Subscription-Key": settings.sarvam_api_key},
                files={"file": (filename, audio, mime_type)},
                data={"model": "saaras:v2", "language_code": language or "unknown"},
            )
            response.raise_for_status()
            result = response.json()
            transcript = result.get("transcript")
            source_language = result.get("language_code") or language
            if not transcript or not source_language:
                raise RuntimeError("Sarvam did not return a transcript and detected language.")
            if source_language == "en":
                return {"transcript": transcript, "language": source_language, "translation": transcript}
            translation_response = await client.post(
                "https://api.sarvam.ai/translate",
                headers={"API-Subscription-Key": settings.sarvam_api_key},
                json={
                    "input": transcript,
                    "source_language_code": source_language,
                    "target_language_code": "en",
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            translation_response.raise_for_status()
        translated = translation_response.json().get("translated_text")
        if not translated:
            raise RuntimeError("Sarvam did not return translated text.")
        return {"transcript": transcript, "language": source_language, "translation": translated}


sarvam = SarvamService()
