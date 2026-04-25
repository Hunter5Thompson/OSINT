import hashlib

import pytest

from gdelt_raw.downloader import (
    LastUpdateEntry,
    download_slice,
    parse_lastupdate,
    slice_id_from_url,
)

LASTUPDATE_SAMPLE = """\
75054 0729f01aacfec7ae2beb068c6cc9a47e http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip
142297 0c76d7ef20465fcab808d99ee2256496 http://data.gdeltproject.org/gdeltv2/20260425120000.mentions.CSV.zip
5885170 d9c68dd9f253f50775ef1479e4ad509b http://data.gdeltproject.org/gdeltv2/20260425120000.gkg.csv.zip
"""


def test_parse_lastupdate():
    entries = parse_lastupdate(LASTUPDATE_SAMPLE)
    assert len(entries) == 3
    assert entries[0].stream == "events"
    assert entries[0].md5 == "0729f01aacfec7ae2beb068c6cc9a47e"
    assert entries[0].slice_id == "20260425120000"
    assert entries[1].stream == "mentions"
    assert entries[2].stream == "gkg"


def test_slice_id_extraction():
    assert (
        slice_id_from_url(
            "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
        )
        == "20260425120000"
    )


@pytest.mark.asyncio
async def test_download_slice_verifies_md5(tmp_path, httpx_mock):
    payload = b"fake-zip-content"
    real_md5 = hashlib.md5(payload).hexdigest()
    url = "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=len(payload),
        md5=real_md5,
        url=url,
        stream="events",
        slice_id="20260425120000",
    )
    out = await download_slice(entry, tmp_path)
    assert out.exists()
    assert out.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_slice_rejects_wrong_md5(tmp_path, httpx_mock):
    payload = b"actual-payload"
    wrong_md5 = "0" * 32
    url = "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=len(payload),
        md5=wrong_md5,
        url=url,
        stream="events",
        slice_id="20260425120000",
    )
    from gdelt_raw.downloader import MD5MismatchError

    with pytest.raises(MD5MismatchError):
        await download_slice(entry, tmp_path)


@pytest.mark.asyncio
async def test_backfill_downloads_historical_slice_without_md5(tmp_path, httpx_mock):
    """Backfill path: MD5 is '' because we don't fetch lastupdate for history.
    download_slice must accept verify_md5=False."""
    payload = b"historical-zip-payload"
    url = "http://data.gdeltproject.org/gdeltv2/20260101000000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=0,
        md5="",
        url=url,
        stream="events",
        slice_id="20260101000000",
    )
    out = await download_slice(entry, tmp_path, verify_md5=False)
    assert out.read_bytes() == payload
