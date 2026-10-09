# Spark Tracing Lite reporter

Canonical ODIN snapshot of the existing dependency-free local reporter.
Original source: `/home/deadpool-ultra/homepage/spark_trace_reporter.py`;
captured 10 October 2026, original SHA256
`6f5ce2b4473606fd5a66ca1236ad7ab7c0a7baf707310c566946fc157e899430`.
That source matched the active Intelligence runtime copy byte for byte.

Only Python 3.12 style fixes (UTC alias/import formatting) were applied to
the vendored transport. Collector schema version 1, authentication, bounded
queue/worker, metadata/text capture, redaction and shutdown behavior remain
the original contract. ODIN adapters add their own failure boundaries.

Intelligence and data-ingestion carry exact generated copies at their service
roots, so each service's wheel, tests and image work independently without a
runtime import or mount from another checkout. Edit this canonical file, copy
its bytes to both roots, and run `tests/ops/test_tracing_vendor_contract.py`.
CI rejects drift between the three files. Both copies are packaged by the
existing `*.py` wheel include; Docker includes them explicitly or with its
application source. No unversioned reporter bind is part of a release.

Local upstream stays untouched. Source provenance is not a claim that a live
client or collector has been deployed from this revision.
