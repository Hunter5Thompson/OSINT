import pytest
from fastapi import HTTPException

from app.routers.timeline import parse_bbox, validate_window


def test_validate_window_rejects_reversed():
    with pytest.raises(HTTPException) as e:
        validate_window("2026-05-02T00:00:00Z", "2026-05-01T00:00:00Z")
    assert e.value.status_code == 422


def test_validate_window_rejects_bad_iso():
    with pytest.raises(HTTPException) as e:
        validate_window("not-a-date", "2026-05-01T00:00:00Z")
    assert e.value.status_code == 422


def test_parse_bbox_none_returns_none():
    assert parse_bbox(None) is None


def test_parse_bbox_valid():
    b = parse_bbox("-10,-20,30,40")
    assert (b.west, b.south, b.east, b.north) == (-10.0, -20.0, 30.0, 40.0)


def test_parse_bbox_bad_count_422():
    with pytest.raises(HTTPException) as e:
        parse_bbox("1,2,3")
    assert e.value.status_code == 422


def test_parse_bbox_out_of_range_422():
    with pytest.raises(HTTPException) as e:
        parse_bbox("-200,0,10,10")
    assert e.value.status_code == 422


def test_validate_window_mixed_tz_does_not_500():
    # one bound tz-aware (Z), one tz-naive must NOT raise TypeError/500;
    # a valid order returns a comparable (start, end) tuple.
    start, end = validate_window("2026-05-01T00:00:00Z", "2026-05-02T00:00:00")
    assert start < end


def test_validate_window_mixed_tz_reversed_422():
    with pytest.raises(HTTPException) as e:
        validate_window("2026-05-02T00:00:00Z", "2026-05-01T00:00:00")
    assert e.value.status_code == 422


def test_parse_bbox_antimeridian_accepted():
    # west>east is the documented anti-meridian wrap — must be accepted, not 422
    b = parse_bbox("170,-10,-170,10")
    assert b.west == 170.0 and b.east == -170.0


def test_parse_bbox_south_gt_north_422():
    with pytest.raises(HTTPException) as e:
        parse_bbox("0,40,10,0")  # south=40 > north=0
    assert e.value.status_code == 422
