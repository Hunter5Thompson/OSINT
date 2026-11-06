# Collector fetch availability

`GET /api/health/collectors` reports each configured RSS publisher, each OFAC
list and each HAPI country separately. `available` means a successful parseable
fetch, including a valid empty response. It does not certify graph/Qdrant writes,
document freshness, successful extraction or factual truth. Use `/health/feeds`
for indexed-document freshness and ingestion logs for processing failures.

The Redis hash `health:collector-fetch:v1` stores a bounded registry, one latest
observation and one last-success timestamp per feed. Failed attempts retain the
last success; missing observations are unknown. Old successful observations become
stale (RSS: two hours; daily collectors: two days). An absent/corrupt registry or
unreachable Redis returns HTTP 503, not an empty green list. The RSS cycle republishes
the registry after Redis recovers. Writes have a two-second telemetry timeout and
cannot block the ingestion pipeline indefinitely. No credentials or fetched text
are stored in this telemetry.

## Publisher corrections verified 2026-11-06

- UN News's configured official RSS endpoint returned HTTP 200 and 30 items during
  the fresh probe. Historical 404 errors are not evidence of present availability.
- Both configured European Parliament RSS endpoints returned HTTP 403. They stay
  explicitly unavailable; an unrelated publisher or search proxy is not silently
  substituted. The official [RSS page](https://www.europarl.europa.eu/at-your-service/en/stay-informed/rss-feeds)
  also required a browser verification at review time.
- OFAC's flat `sdn.xml` and `consolidated.xml` downloads redirect to their current
  files. Follow redirects and parse the flat `sdnList` schema, not the advanced
  `Sanctions` schema. The [official namespace notice](https://ofac.treasury.gov/recent-actions/20240507_44)
  specifies the `/exports/XML` namespace. Live parse-only probes returned 19,563
  SDN entries and 486 consolidated entries. These counts are dated observations.
- HAPI's [official getting-started documentation](https://hdx-hapi.readthedocs.io/en/latest/getting-started/)
  requires `app_identifier` in the query string, not a header. Without a configured
  identifier the collector reports `not_configured` without making country requests
  or creating collections. The active deployment had no identifier. Enabling HAPI
  remains contingent on operator-supplied configuration and live schema/coverage
  qualification; this change does not claim HAPI coverage.

Probe and regression evidence: `/data/odin-reliability-20261106/p2/`.
