import asyncio
import json

import httpx

from app.config import settings
from app.services import sarvam as sarvam_module


def test_speech_to_text_uses_current_model(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"transcript": "Pothole on Main Road", "language_code": "en"},
        )

    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(
        sarvam_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    result = asyncio.run(
        sarvam_module.SarvamService().transcribe_and_translate(
            b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
        )
    )

    assert result == {
        "transcript": "Pothole on Main Road",
        "language": "en",
        "translation": "Pothole on Main Road",
    }
    assert requests[0].url == "https://api.sarvam.ai/speech-to-text"
    assert b"saaras:v3" in requests[0].content


def test_speech_to_text_includes_provider_error_details(monkeypatch) -> None:
    async_client = httpx.AsyncClient

    def handle_request(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Audio file is too short."}},
        )

    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(
        sarvam_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    try:
        asyncio.run(
            sarvam_module.SarvamService().transcribe_and_translate(
                b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
            )
        )
    except httpx.HTTPStatusError as error:
        assert error.response.status_code == 400
        assert "Audio file is too short." in str(error)
    else:
        raise AssertionError("Expected Sarvam's HTTP 400 response to be surfaced.")


def test_non_english_transcript_translates_to_english_india(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/speech-to-text":
            return httpx.Response(
                200,
                json={"transcript": "சாலையில் பள்ளம்", "language_code": "ta-IN"},
            )
        return httpx.Response(200, json={"translated_text": "Pothole on the road"})

    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(
        sarvam_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    result = asyncio.run(
        sarvam_module.SarvamService().transcribe_and_translate(
            b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
        )
    )

    assert result == {
        "transcript": "சாலையில் பள்ளம்",
        "language": "ta-IN",
        "translation": "Pothole on the road",
    }
    assert requests[1].url == "https://api.sarvam.ai/translate"
    assert json.loads(requests[1].content)["target_language_code"] == "en-IN"


def test_english_india_transcript_does_not_need_translation(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"transcript": "Pothole on the road", "language_code": "en-IN"},
        )

    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(
        sarvam_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    result = asyncio.run(
        sarvam_module.SarvamService().transcribe_and_translate(
            b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
        )
    )

    assert result["translation"] == result["transcript"]
    assert len(requests) == 1
