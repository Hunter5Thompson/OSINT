from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
from pydub import AudioSegment

from nlm_ingest.schemas import Transcript, TranscriptSegment

log = structlog.get_logger()

CHUNK_MINUTES = 10


@dataclass
class ChunkResult:
    segments: list[TranscriptSegment]
    language: str | None = None


def split_audio(audio_path: Path, max_minutes: int = CHUNK_MINUTES) -> list[Path]:
    audio = AudioSegment.from_file(str(audio_path))
    max_ms = max_minutes * 60 * 1000
    if len(audio) <= max_ms:
        return [audio_path]

    chunks: list[Path] = []
    chunk_dir = audio_path.parent / f"{audio_path.stem}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    num_chunks = math.ceil(len(audio) / max_ms)
    for i in range(num_chunks):
        start_ms = i * max_ms
        end_ms = min((i + 1) * max_ms, len(audio))
        chunk = audio[start_ms:end_ms]
        chunk_path = chunk_dir / f"chunk_{i:03d}.mp3"
        chunk.export(str(chunk_path), format="mp3", bitrate="128k")
        chunks.append(chunk_path)

    log.info("audio_split", path=str(audio_path), chunks=len(chunks))
    return chunks


def get_original_duration(audio_path: Path) -> float:
    audio = AudioSegment.from_file(str(audio_path))
    return len(audio) / 1000.0


def majority_language(chunk_results: list[ChunkResult]) -> str:
    langs = [c.language for c in chunk_results if c.language]
    if not langs:
        return "en"
    counter = Counter(langs)
    return counter.most_common(1)[0][0]


async def transcribe_chunk(
    audio_path: Path,
    client: httpx.AsyncClient,
    voxtral_url: str,
    voxtral_model: str,
) -> ChunkResult:
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = await client.post(
        f"{voxtral_url}/audio/transcriptions",
        files={"file": (audio_path.name, audio_bytes, "audio/mpeg")},
        data={"model": voxtral_model},
        timeout=600.0,
    )
    response.raise_for_status()
    data = response.json()

    text = data.get("text", "")
    raw_segments = data.get("segments", [])
    language = data.get("language")

    if raw_segments:
        segments = [
            TranscriptSegment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=s.get("text", ""),
                speaker=s.get("speaker"),
            )
            for s in raw_segments
        ]
    else:
        segments = [TranscriptSegment(start=0.0, end=0.0, text=text)]

    return ChunkResult(segments=segments, language=language)


async def transcribe(
    notebook_id: str,
    audio_path: Path,
    client: httpx.AsyncClient,
    voxtral_url: str,
    voxtral_model: str,
) -> Transcript:
    chunks = split_audio(audio_path)
    chunk_duration_sec = CHUNK_MINUTES * 60

    all_segments: list[TranscriptSegment] = []
    chunk_results: list[ChunkResult] = []

    for i, chunk_path in enumerate(chunks):
        result = await transcribe_chunk(chunk_path, client, voxtral_url, voxtral_model)
        chunk_results.append(result)
        offset = i * chunk_duration_sec
        for seg in result.segments:
            all_segments.append(
                TranscriptSegment(
                    start=seg.start + offset,
                    end=seg.end + offset,
                    text=seg.text,
                    speaker=seg.speaker,
                )
            )

    return Transcript(
        notebook_id=notebook_id,
        segments=all_segments,
        full_text=" ".join(s.text for s in all_segments),
        duration_seconds=get_original_duration(audio_path),
        language=majority_language(chunk_results),
    )
