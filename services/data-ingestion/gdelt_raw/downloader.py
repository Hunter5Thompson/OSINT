"""Download GDELT raw zips with MD5 verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from gdelt_raw.config import get_settings

log = structlog.get_logger(__name__)


class MD5MismatchError(Exception):
    pass


@dataclass(frozen=True)
class LastUpdateEntry:
    size: int
    md5: str
    url: str
    stream: str  # "events" | "mentions" | "gkg"
    slice_id: str  # "20260425120000"


def _stream_from_url(url: str) -> str:
    if ".export.CSV.zip" in url:
        return "events"
    if ".mentions.CSV.zip" in url:
        return "mentions"
    if ".gkg.csv.zip" in url:
        return "gkg"
    raise ValueError(f"Unknown GDELT stream in URL: {url}")


def slice_id_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".", 1)[0]


def parse_lastupdate(text: str) -> list[LastUpdateEntry]:
    entries: list[LastUpdateEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        size_s, md5, url = line.split(maxsplit=2)
        entries.append(
            LastUpdateEntry(
                size=int(size_s),
                md5=md5,
                url=url,
                stream=_stream_from_url(url),
                slice_id=slice_id_from_url(url),
            )
        )
    return entries


async def fetch_lastupdate() -> list[LastUpdateEntry]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.download_timeout) as client:
        resp = await client.get(f"{settings.base_url}/lastupdate.txt")
        resp.raise_for_status()
        return parse_lastupdate(resp.text)


async def download_slice(
    entry: LastUpdateEntry,
    out_dir: Path,
    *,
    verify_md5: bool = True,
) -> Path:
    """Download a single slice file.

    If ``verify_md5=True`` and ``entry.md5`` is non-empty, validate and raise
    :class:`MD5MismatchError` on drift. Backfill sets ``verify_md5=False``
    because we don't have MD5s for historical slices (they're not in
    ``lastupdate.txt``).
    """
    settings = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / entry.url.rsplit("/", 1)[-1]
    async with httpx.AsyncClient(timeout=settings.download_timeout) as client:
        resp = await client.get(entry.url)
        resp.raise_for_status()
        content = resp.content
    if verify_md5 and entry.md5:
        actual_md5 = hashlib.md5(content).hexdigest()
        if actual_md5 != entry.md5:
            raise MD5MismatchError(
                f"expected={entry.md5} actual={actual_md5} url={entry.url}"
            )
    out_path.write_bytes(content)
    log.info(
        "gdelt_downloaded",
        stream=entry.stream,
        slice=entry.slice_id,
        bytes=len(content),
        md5_verified=(verify_md5 and bool(entry.md5)),
    )
    return out_path
