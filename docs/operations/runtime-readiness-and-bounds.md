# Runtime readiness and resource bounds

`GET /api/health` remains process liveness. `GET /api/health/ready` probes Neo4j
and the configured Qdrant collection/schema as required dependencies, Redis as
optional. Probes run concurrently with a two-second bound: unavailable required
dependencies return 503; a missing cache returns 200/degraded. This does not
measure publisher freshness, model quality or external factual truth.

Redis retains its client after connection failure. Operations have a one-second
bound; a five-second cooldown and one recovery probe avoid a concurrent retry
stampede. Cache misses remain safe while recovery runs.

Manual RAG ingestion returns 501 and creates no job. Statistics use exact Qdrant
counts; failed/invalid responses retain null plus unavailable, distinct from a
successful zero. Each known source family has independent count availability.

Timeline histogram templates aggregate distinct matching events in Neo4j without
an event LIMIT. Result rows are bounded by requested buckets (maximum 240).
Each row contains weighted raw category/severity groups, normalized using the
shared Python functions. Bytes still depend on distinct category/severity pairs;
this is not a constant-byte or bounded database-scan claim. Exact spatial reads
remain in one snapshot with their separate coverage accounting. Temporal bounds,
sub-millisecond truncation, dates before 1970 and dateline filters are tested.
A marked disposable Neo4j benchmark seeds 20,000 events per case and compares all
buckets to the previous Python algorithm across twelve global/spatial/time cases.
All matched; the global case transferred four rows instead of 15,000.

The map leases at most one paused, detached Cesium Viewer between route visits.
Healthy reuse avoids repeated native context allocation. Token changes, rendering
failure and context loss discard the lease. Layer hooks still unmount normally.
This bounds ordinary navigation; it does not fix Chromium context disposal or
qualify arbitrarily repeated device failures.

The first viewer-lease candidate with four MSAA samples failed after 26 minutes:
Chrome lost its WebGL context and the kernel recorded NVIDIA Xid 31. Stable RSS
did not qualify that run. The follow-up uses single-sample render targets; this
is an empirical stability candidate, not a demonstrated root-cause fix. All four
short native tests pass; the complete follow-up soak retains the same criteria.

Native acceptance is separate from JS heap. The complete 60-minute dense native
soak compares medians at minutes 10–15 and 55–60: browser RSS growth <32 MiB and
slope <0.5 MiB/min, GPU process RSS growth <64 MiB, renderer RSS growth <128 MiB;
existing JS heap (<5 MiB) and DOM (<50 nodes) gates remain. Errors/context losses
must be zero. Shared device-wide VRAM is diagnostic, not app-owned memory.
The source/assets were frozen before the run. Final verdict and measurements:
`/data/odin-reliability-20261106/p5/` (pending until the full run completes).
