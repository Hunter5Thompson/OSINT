"""Static aggregation suffix after DISTINCT ev; never truncate matching events.

Rows are bounded by bucket count. Payload cardinality is the distinct raw
category/severity pairs per bucket, not the number of matching events.
Normalization remains in the shared Python severity/category functions.
"""

HISTOGRAM_AGGREGATION = """
WITH ev,
     toInteger((floor(ev.timeline_at.epochMillis / 1000.0)
       + toFloat(ev.timeline_at.microsecond) / 1000000.0) * 1000.0) AS ts_ms
WITH ev, toInteger((ts_ms - $start_ms) / $bucket_ms) AS raw_bucket
WITH ev, CASE WHEN raw_bucket < 0 THEN 0
              WHEN raw_bucket >= $buckets THEN $buckets - 1
              ELSE raw_bucket END AS bucket
WITH bucket, ev.codebook_type AS category, ev.severity AS severity, count(*) AS n
RETURN bucket, sum(n) AS count,
       collect({codebook_type: category, severity: severity, count: n}) AS groups
ORDER BY bucket
"""
