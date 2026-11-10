import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

GNANI_BASE_URL = "https://api.vachana.ai"
GNANI_STT_ENDPOINT = f"{GNANI_BASE_URL}/stt/v3"
GNANI_DEFAULT_MODEL = "prisma-v3.0"  # Multilingual with auto language detection
GNANI_ENGLISH_LANGUAGE_CODE = "en-IN"

# Language code mapping from Sarvam/BCP-47 to Gnani format
LANGUAGE_MAP = {
    "hi": "hi-IN",
    "en": "en-IN",
    "kn": "kn-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "bn": "bn-IN",
    "pa": "pa-IN",
    "ur": "ur-IN",
}


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
            f"Gnani {service} request failed: {error}. Provider response: {detail}",
            request=error.request,
            response=response,
        ) from error


def _normalize_language_code(language: str) -> str:
    """Convert a short language code like 'hi' to Gnani's format 'hi-IN'."""
    if not language or language == "unknown":
        return "indic-auto"
    if "-" in language:
        return language  # Already in BCP-47 format like 'hi-IN'
    return LANGUAGE_MAP.get(language, f"{language}-IN")


class GnaniService:
    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def transcribe_and_translate(self, audio: bytes, filename: str, mime_type: str, language: str) -> dict:
        """Transcribe audio using Gnani STT, then translate to English using Gemini if needed."""
        if not settings.gnani_api_key:
            raise RuntimeError("GNANI_API_KEY is missing; configure it in backend/.env.")

        language_code = _normalize_language_code(language)

        async with httpx.AsyncClient(timeout=120) as client:
            # Step 1: Speech-to-Text using Gnani Prisma
            response = await client.post(
                GNANI_STT_ENDPOINT,
                headers={"X-API-Key-ID": settings.gnani_api_key},
                files={"audio_file": (filename, audio, mime_type)},
                data={
                    "language_code": language_code,
                    "model": GNANI_DEFAULT_MODEL,
                },
            )
            _raise_for_status(response, "speech-to-text")
            result = response.json()

            # Gnani returns transcript in the response
            transcript = result.get("transcript") or result.get("text")
            detected_language = result.get("language_code") or result.get("detected_language") or language_code
            if not transcript:
                raise RuntimeError("Gnani did not return a transcript.")

            # Normalize detected language to short code for comparison
            source_short = detected_language.split("-")[0].lower() if detected_language else ""

            # Step 2: If already English, no translation needed
            if source_short == "en":
                return {"transcript": transcript, "language": detected_language, "translation": transcript}

            # Step 3: Translate to English using Gemini (Gnani doesn't have a translation API)
            from app.services.gemini import gemini

            translation_prompt = (
                f"Translate the following {detected_language} text to English accurately. "
                f"Return ONLY the English translation, nothing else.\n\n"
                f"Text: {transcript}"
            )
            translated = await gemini.generate_text(translation_prompt)
            if not translated or not translated.strip():
                raise RuntimeError("Translation to English failed.")

            return {"transcript": transcript, "language": detected_language, "translation": translated.strip()}


gnani = GnaniService()
