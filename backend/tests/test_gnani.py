import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.services import gnani as gnani_module


def test_speech_to_text_uses_gnani_prisma(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"transcript": "Pothole on Main Road", "language_code": "en-IN"},
        )

    monkeypatch.setattr(settings, "gnani_api_key", "test-key")
    monkeypatch.setattr(
        gnani_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    result = asyncio.run(
        gnani_module.GnaniService().transcribe_and_translate(
            b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
        )
    )

    assert result == {
        "transcript": "Pothole on Main Road",
        "language": "en-IN",
        "translation": "Pothole on Main Road",
    }
    assert "api.vachana.ai" in str(requests[0].url)
    assert requests[0].headers.get("X-API-Key-ID") == "test-key"
    assert b'name="language_code"\r\n\r\nindic-auto' in requests[0].content


def test_speech_to_text_includes_provider_error_details(monkeypatch) -> None:
    async_client = httpx.AsyncClient

    def handle_request(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Audio file is too short."}},
        )

    monkeypatch.setattr(settings, "gnani_api_key", "test-key")
    monkeypatch.setattr(
        gnani_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    try:
        asyncio.run(
            gnani_module.GnaniService().transcribe_and_translate(
                b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
            )
        )
    except httpx.HTTPStatusError as error:
        assert error.response.status_code == 400
        assert "Audio file is too short." in str(error)
    else:
        raise AssertionError("Expected Gnani's HTTP 400 response to be surfaced.")


def test_non_english_transcript_translates_via_gemini(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"transcript": "சாலையில் பள்ளம்", "language_code": "ta-IN"},
        )

    monkeypatch.setattr(settings, "gnani_api_key", "test-key")
    monkeypatch.setattr(
        gnani_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    with patch("app.services.gemini.gemini") as mock_gemini:
        mock_gemini.generate_text = AsyncMock(return_value="Pothole on the road")
        result = asyncio.run(
            gnani_module.GnaniService().transcribe_and_translate(
                b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
            )
        )

    assert result == {
        "transcript": "சாலையில் பள்ளம்",
        "language": "ta-IN",
        "translation": "Pothole on the road",
    }
    mock_gemini.generate_text.assert_called_once()


def test_english_india_transcript_does_not_need_translation(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"transcript": "Pothole on the road", "language_code": "en-IN"},
        )

    monkeypatch.setattr(settings, "gnani_api_key", "test-key")
    monkeypatch.setattr(
        gnani_module.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle_request), **kwargs),
    )

    result = asyncio.run(
        gnani_module.GnaniService().transcribe_and_translate(
            b"wav-audio", "voice-report.wav", "audio/wav", "unknown"
        )
    )

    assert result["translation"] == result["transcript"]
    assert len(requests) == 1


def test_language_code_normalization() -> None:
    assert gnani_module._normalize_language_code("hi") == "hi-IN"
    assert gnani_module._normalize_language_code("en") == "en-IN"
    assert gnani_module._normalize_language_code("ta-IN") == "ta-IN"
    assert gnani_module._normalize_language_code("unknown") == "indic-auto"
    assert gnani_module._normalize_language_code("") == "indic-auto"
