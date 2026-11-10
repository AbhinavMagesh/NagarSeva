import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

SARVAM_STT_MODEL = "saaras:v3"
SARVAM_ENGLISH_LANGUAGE_CODE = "en-IN"


def _is_retryable(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code == 429 or error.response.status_code >= 500)
    )


def _raise_for_status(response: httpx.Response, service: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        detail = None
        if isinstance(payload, dict):
            provider_error = payload.get("error")
            if isinstance(provider_error, dict):
                detail = provider_error.get("message")
            elif isinstance(provider_error, str):
                detail = provider_error
            detail = detail or payload.get("message") or payload.get("detail")
        detail = str(detail or response.text or "No error details returned by provider.")[:1000]
        raise httpx.HTTPStatusError(
            f"Sarvam {service} request failed: {error}. Provider response: {detail}",
            request=error.request,
            response=response,
        ) from error


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
                data={"model": SARVAM_STT_MODEL, "language_code": language or "unknown"},
            )
            _raise_for_status(response, "speech-to-text")
            result = response.json()
            transcript = result.get("transcript")
            source_language = result.get("language_code") or language
            if not transcript or not source_language:
                raise RuntimeError("Sarvam did not return a transcript and detected language.")
            if source_language in {"en", SARVAM_ENGLISH_LANGUAGE_CODE}:
                return {"transcript": transcript, "language": source_language, "translation": transcript}
            translation_response = await client.post(
                "https://api.sarvam.ai/translate",
                headers={"API-Subscription-Key": settings.sarvam_api_key},
                json={
                    "input": transcript,
                    "source_language_code": source_language,
                    "target_language_code": SARVAM_ENGLISH_LANGUAGE_CODE,
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            _raise_for_status(translation_response, "translation")
        translated = translation_response.json().get("translated_text")
        if not translated:
            raise RuntimeError("Sarvam did not return translated text.")
        return {"transcript": transcript, "language": source_language, "translation": translated}


sarvam = SarvamService()
