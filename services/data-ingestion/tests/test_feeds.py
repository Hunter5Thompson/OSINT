"""Tests for data-ingestion feed collectors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from feeds.gdelt_collector import GDELT_QUERIES, GDELTCollector
from feeds.hotspot_updater import HOTSPOTS, HotspotUpdater
from feeds.rss_collector import RSS_FEEDS, RSSCollector, _content_hash, _point_id_from_hash
from feeds.tle_updater import TLE_GROUPS, TLEUpdater, parse_tle_text


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------
class TestContentHash:
    def test_deterministic(self) -> None:
        h1 = _content_hash("Hello World", "https://example.com/article")
        h2 = _content_hash("Hello World", "https://example.com/article")
        assert h1 == h2

    def test_case_insensitive(self) -> None:
        h1 = _content_hash("Hello World", "https://example.com/Article")
        h2 = _content_hash("hello world", "https://example.com/article")
        assert h1 == h2

    def test_different_inputs_different_hash(self) -> None:
        h1 = _content_hash("Title A", "https://example.com/a")
        h2 = _content_hash("Title B", "https://example.com/b")
        assert h1 != h2

    def test_whitespace_stripped(self) -> None:
        h1 = _content_hash("  Title  ", "  https://example.com  ")
        h2 = _content_hash("Title", "https://example.com")
        assert h1 == h2


class TestPointIdFromHash:
    def test_returns_positive_int(self) -> None:
        h = _content_hash("title", "https://example.com")
        pid = _point_id_from_hash(h)
        assert isinstance(pid, int)
        assert pid > 0

    def test_deterministic(self) -> None:
        h = _content_hash("title", "https://example.com")
        assert _point_id_from_hash(h) == _point_id_from_hash(h)


# ---------------------------------------------------------------------------
# TLE parser tests
# ---------------------------------------------------------------------------
class TestTLEParser:
    SAMPLE_TLE = """\
ISS (ZARYA)
1 25544U 98067A   24045.52631944  .00016717  00000+0  30153-3 0  9998
2 25544  51.6413 247.4627 0006703  32.6918  70.0291 15.49560539439567
NOAA 15
1 25338U 98030A   24045.49135538  .00000251  00000+0  12345-3 0  9999
2 25338  98.7320 105.4280 0010234 245.1234 114.8766 14.25978123345678
"""

    def test_parse_two_satellites(self) -> None:
        sats = parse_tle_text(self.SAMPLE_TLE)
        assert len(sats) == 2

    def test_satellite_fields(self) -> None:
        sats = parse_tle_text(self.SAMPLE_TLE)
        iss = sats[0]
        assert iss["name"] == "ISS (ZARYA)"
        assert iss["norad_id"] == "25544"
        assert iss["tle_line1"].startswith("1 ")
        assert iss["tle_line2"].startswith("2 ")

    def test_empty_input(self) -> None:
        assert parse_tle_text("") == []

    def test_malformed_input(self) -> None:
        result = parse_tle_text("just some random text\nnothing to see here\n")
        assert result == []


# ---------------------------------------------------------------------------
# RSS feed list validation
# ---------------------------------------------------------------------------
class TestRSSFeedList:
    def test_minimum_feed_count(self) -> None:
        assert len(RSS_FEEDS) >= 20

    def test_feeds_have_required_keys(self) -> None:
        for feed in RSS_FEEDS:
            assert "name" in feed
            assert "url" in feed
            assert feed["url"].startswith("http")

    def test_feed_names_unique(self) -> None:
        names = [f["name"] for f in RSS_FEEDS]
        assert len(names) == len(set(names))

    def test_includes_verified_defense_primary_sources(self) -> None:
        names = {f["name"] for f in RSS_FEEDS}
        assert "BMVg" in names
        assert "Bundeswehr" in names
        assert "Bundestag Verteidigung" in names
        assert "SWP Publications (DE)" in names
        assert "EU Parliament Security and Defence" in names


# ---------------------------------------------------------------------------
# GDELT query validation
# ---------------------------------------------------------------------------
class TestGDELTQueries:
    def test_has_queries(self) -> None:
        assert len(GDELT_QUERIES) >= 3

    def test_queries_have_required_keys(self) -> None:
        for q in GDELT_QUERIES:
            assert "name" in q
            assert "query" in q


# ---------------------------------------------------------------------------
# TLE groups validation
# ---------------------------------------------------------------------------
class TestTLEGroups:
    def test_includes_key_groups(self) -> None:
        names = {g["name"] for g in TLE_GROUPS}
        assert "active" in names
        assert "stations" in names
        assert "military" in names
        assert "weather" in names

    def test_groups_have_param(self) -> None:
        for g in TLE_GROUPS:
            assert "param" in g
            assert "FORMAT=tle" in g["param"]


# ---------------------------------------------------------------------------
# Hotspot data validation
# ---------------------------------------------------------------------------
class TestHotspots:
    def test_minimum_hotspot_count(self) -> None:
        assert len(HOTSPOTS) >= 50

    def test_hotspots_have_required_fields(self) -> None:
        required = {"id", "name", "lat", "lon", "region", "threat_level", "description", "sources"}
        for h in HOTSPOTS:
            missing = required - set(h.keys())
            assert not missing, f"Hotspot {h.get('id', '?')} missing fields: {missing}"

    def test_valid_coordinates(self) -> None:
        for h in HOTSPOTS:
            assert -90 <= h["lat"] <= 90, f"{h['id']} lat out of range"
            assert -180 <= h["lon"] <= 180, f"{h['id']} lon out of range"

    def test_valid_threat_levels(self) -> None:
        valid_levels = {"low", "moderate", "elevated", "high", "critical"}
        for h in HOTSPOTS:
            assert h["threat_level"] in valid_levels, f"{h['id']} has invalid threat_level"

    def test_unique_ids(self) -> None:
        ids = [h["id"] for h in HOTSPOTS]
        assert len(ids) == len(set(ids))

    def test_key_hotspots_present(self) -> None:
        ids = {h["id"] for h in HOTSPOTS}
        assert "ua-ru-conflict" in ids
        assert "taiwan-strait" in ids
        assert "gaza-israel" in ids
        assert "south-china-sea" in ids
        assert "korean-dmz" in ids


# ---------------------------------------------------------------------------
# Collector instantiation tests (with mocked dependencies)
# ---------------------------------------------------------------------------
class TestCollectorInstantiation:
    @patch("feeds.rss_collector.QdrantClient")
    def test_rss_collector_init(self, mock_qdrant_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_qdrant_cls.return_value = mock_client

        collector = RSSCollector()
        assert collector.qdrant is not None
        mock_client.create_collection.assert_called_once()

    @patch("feeds.gdelt_collector.QdrantClient")
    def test_gdelt_collector_init(self, mock_qdrant_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_qdrant_cls.return_value = mock_client

        collector = GDELTCollector()
        assert collector.qdrant is not None

    def test_tle_updater_init(self) -> None:
        updater = TLEUpdater()
        assert updater._redis is None  # lazy init

    @patch("feeds.hotspot_updater.QdrantClient")
    def test_hotspot_updater_init(self, mock_qdrant_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_qdrant_cls.return_value = mock_client

        updater = HotspotUpdater()
        assert updater._redis is None  # lazy init
        assert updater.qdrant is not None


# ---------------------------------------------------------------------------
# HotspotUpdater threat level adjustment
# ---------------------------------------------------------------------------
class TestThreatLevelAdjustment:
    @patch("feeds.hotspot_updater.QdrantClient")
    def test_high_mentions_escalate(self, mock_qdrant_cls: MagicMock) -> None:
        mock_qdrant_cls.return_value = MagicMock()
        updater = HotspotUpdater()
        assert updater._adjust_threat_level("elevated", 35) == "critical"

    @patch("feeds.hotspot_updater.QdrantClient")
    def test_moderate_mentions_escalate_one(self, mock_qdrant_cls: MagicMock) -> None:
        mock_qdrant_cls.return_value = MagicMock()
        updater = HotspotUpdater()
        assert updater._adjust_threat_level("moderate", 20) == "elevated"

    @patch("feeds.hotspot_updater.QdrantClient")
    def test_low_mentions_deescalate(self, mock_qdrant_cls: MagicMock) -> None:
        mock_qdrant_cls.return_value = MagicMock()
        updater = HotspotUpdater()
        assert updater._adjust_threat_level("elevated", 1) == "moderate"

    @patch("feeds.hotspot_updater.QdrantClient")
    def test_critical_stays_critical(self, mock_qdrant_cls: MagicMock) -> None:
        mock_qdrant_cls.return_value = MagicMock()
        updater = HotspotUpdater()
        assert updater._adjust_threat_level("critical", 50) == "critical"

    @patch("feeds.hotspot_updater.QdrantClient")
    def test_low_cannot_go_below_low(self, mock_qdrant_cls: MagicMock) -> None:
        mock_qdrant_cls.return_value = MagicMock()
        updater = HotspotUpdater()
        assert updater._adjust_threat_level("low", 0) == "low"


# ---------------------------------------------------------------------------
# RSS feed parsing with mock data
# ---------------------------------------------------------------------------
class TestRSSParsing:
    """Test that feedparser correctly handles RSS XML data."""

    SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Military Exercise in Pacific</title>
      <link>https://example.com/article-1</link>
      <description>A large-scale naval exercise was conducted in the Pacific.</description>
      <pubDate>Mon, 04 Mar 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Diplomatic Talks Resume</title>
      <link>https://example.com/article-2</link>
      <description>Diplomatic negotiations resumed between rival nations.</description>
      <pubDate>Tue, 05 Mar 2026 08:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    def test_feedparser_parses_sample(self) -> None:
        import feedparser

        parsed = feedparser.parse(self.SAMPLE_RSS)
        assert len(parsed.entries) == 2
        assert parsed.entries[0].title == "Military Exercise in Pacific"
        assert parsed.entries[0].link == "https://example.com/article-1"
        assert parsed.entries[1].title == "Diplomatic Talks Resume"

    def test_deduplication_hashing(self) -> None:
        import feedparser

        parsed = feedparser.parse(self.SAMPLE_RSS)
        entry = parsed.entries[0]
        h1 = _content_hash(entry.title, entry.link)
        h2 = _content_hash(entry.title, entry.link)
        assert h1 == h2
        # Different entry produces different hash
        entry2 = parsed.entries[1]
        h3 = _content_hash(entry2.title, entry2.link)
        assert h1 != h3
