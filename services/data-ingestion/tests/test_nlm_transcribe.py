from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest

from notebooklm.transcribe import split_audio, transcribe, transcribe_chunk

_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:8010/v1/audio/transcriptions")


class TestTranscribeChunk:
    @pytest.mark.asyncio
    async def test_returns_segments(self):
        mock_response = httpx.Response(
            200,
            json={
                "text": "Hello world. This is a test.",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "Hello world."},
                    {"start": 2.5, "end": 5.0, "text": "This is a test."},
                ],
            },
            request=_DUMMY_REQUEST,
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        with patch("builtins.open", mock_open(read_data=b"fake audio")):
            result = await transcribe_chunk(
                audio_path=Path("/fake/audio.wav"),
                client=client,
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world."

    @pytest.mark.asyncio
    async def test_fallback_no_segments(self):
        mock_response = httpx.Response(
            200,
            json={"text": "Full transcript without segments."},
            request=_DUMMY_REQUEST,
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        with patch("builtins.open", mock_open(read_data=b"fake audio")):
            result = await transcribe_chunk(
                audio_path=Path("/fake/audio.wav"),
                client=client,
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        assert len(result.segments) == 1
        assert result.segments[0].text == "Full transcript without segments."


class TestTranscribe:
    @pytest.mark.asyncio
    async def test_single_chunk_sets_notebook_id(self):
        mock_chunk_result = MagicMock()
        mock_chunk_result.segments = [
            MagicMock(start=0.0, end=10.0, text="Short audio", speaker=None)
        ]

        with patch("notebooklm.transcribe.split_audio", return_value=[Path("/tmp/c0.wav")]), \
             patch("notebooklm.transcribe.transcribe_chunk", new_callable=AsyncMock, return_value=mock_chunk_result), \
             patch("notebooklm.transcribe.get_original_duration", return_value=10.0), \
             patch("notebooklm.transcribe.majority_language", return_value="en"):
            result = await transcribe(
                notebook_id="nb42",
                audio_path=Path("/fake/podcast.mp3"),
                client=AsyncMock(),
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        assert result.notebook_id == "nb42"
        assert result.language == "en"
        assert "Short audio" in result.full_text

    @pytest.mark.asyncio
    async def test_multi_chunk_offsets(self):
        seg0 = MagicMock(start=0.0, end=5.0, text="Chunk zero", speaker=None)
        seg1 = MagicMock(start=0.0, end=5.0, text="Chunk one", speaker=None)
        chunk0 = MagicMock(segments=[seg0])
        chunk1 = MagicMock(segments=[seg1])

        with patch("notebooklm.transcribe.split_audio", return_value=[Path("/tmp/c0.wav"), Path("/tmp/c1.wav")]), \
             patch("notebooklm.transcribe.transcribe_chunk", new_callable=AsyncMock, side_effect=[chunk0, chunk1]), \
             patch("notebooklm.transcribe.get_original_duration", return_value=1200.0), \
             patch("notebooklm.transcribe.majority_language", return_value="en"):
            result = await transcribe(
                notebook_id="nb1",
                audio_path=Path("/fake/long.mp3"),
                client=AsyncMock(),
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        assert result.segments[1].start == 600.0
        assert result.segments[1].end == 605.0


class TestSplitAudio:
    def test_short_audio_returns_single(self, tmp_path):
        wav_path = tmp_path / "short.wav"
        _write_silent_wav(wav_path, duration_ms=5000)
        chunks = split_audio(wav_path, max_minutes=10)
        assert len(chunks) == 1


def _write_silent_wav(path: Path, duration_ms: int = 5000):
    from pydub import AudioSegment
    silence = AudioSegment.silent(duration=duration_ms)
    silence.export(str(path), format="wav")
