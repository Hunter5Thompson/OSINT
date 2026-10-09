# Baked Spark Tracing Lite

Tracing observes Intelligence queries and RSS/Notebook extraction. It owns
neither results nor provider/parser errors. Without `SPARK_TRACE_ENDPOINT`
the adapters do nothing. Reporter startup/finish/close failures preserve the
original return value or exception, including cancellation. A legacy query
error response is recorded as an error rather than successful inference.

The reporter and adapters are packaged in the application images. The
[vendored transport](../../vendor/spark-trace-reporter/README.md) is an explicit
snapshot of the existing local collector client; service copies are checked
for byte equality in CI. No import or Python-code mount from the old external
observability worktree is required by these new images.

## Reviewable release configuration

`./odin.sh --release --tracing` selects the three normal release files followed
by `docker-compose.tracing.release.yml`. The flag requires release mode. Its
overlay configures Intelligence and Spark ingestion only, with default target
IDs `workstation-5090` and `spark`; only Spark ingestion carries `spark_id=spark`.
The overlay adds the existing socket directory and token file as read-only
binds, without automatic source creation or a database mount. It preserves
the common spatial-data inputs from the release overlay.

Declare the reviewed runtime paths in the selected release environment:

```dotenv
ODIN_TRACE_RUN_DIR=/data/spark-observability/run
ODIN_TRACE_TOKEN_FILE=/data/spark-observability/ingestion.token
ODIN_TRACE_CAPTURE=metadata
```

The guard checks mount/endpoint/capture contracts and input path types before
lifecycle operations. It never reads or prints the token. A collector may be
temporarily offline; its socket inode is not required at preflight. Mounting
the directory lets a restarted collector replace the socket inode without
recreating client containers. The current images run as root; changing that
requires matching socket/token permissions in a separate reviewed change.

The existing Intelligence deployment used `text` capture. A release intended
to retain that configuration must explicitly set `ODIN_TRACE_CAPTURE=text`.
Metadata omits request/response text; bounded text capture removes recognized
credential keys and binary payloads. Free text is not comprehensively scanned.
Nonstreaming TTFT and missing provider usage remain unknown. Direct SDK calls
inside tools retain the active tool's parent span where LangGraph supplies it.

Queue overflow or failed transport loses telemetry and increments the
reporter's drop count. There is no durable retry journal. Reporter heartbeats
expose drop/error state to the collector. Shutdown flushes for a bounded
interval outside the event loop, even when another cleanup operation fails.

## Validation and rollout limits

Service tests run independently, without importing the external collector.
They exercise the public query/parser paths, real LangGraph callbacks,
parallel traces, SDK parent lineage, budgets/timeouts, missing usage,
exceptions/cancellation, transport bounds and shutdown. Ops tests render and
validate release Compose without executing lifecycle operations.

`scripts/ops/smoke_trace_image.py` probes each actual built image using an
isolated schema-v1 Unix collector fixture and only disposable token/control
inputs. It overrides the entrypoint to test the packaged adapters; the separate
`smoke_image.py` still verifies the real application CMD. Three transport
phases retain one reporter instance: collector online, collector absent,
socket recreated. Provider responses remain fixtures; `--network none`
prevents external calls. Local runs use `--work-dir` under `/data`.

The fixture checks the emitted transport contract. `--collector-source PATH`
additionally loads the current local collector API/schema/store into the same
isolated receiver and writes only disposable SQLite data, outside the mounts
seen by the client. This separately checks that collector's acceptance/storage
contract. Its live socket service, production trace freshness, provider quality,
deployment and human acceptance still require separate evidence.

On 10 October 2026, the fresh runtime inventory confirmed the external tracing
overlay on Intelligence. The Spark-ingestion container had no tracing mounts
or configuration. This supersedes the older statement that both active
containers carried that overlay. The external dirty checkout and live services
were preserved; source integration does not restore productive tracing by
itself.

For an approved rollout, retain the current collector and runtime inputs,
drain the old ingestion writer before replacement and use reviewed image
digests. Rollback needs the saved old image and its exact Compose/input
configuration, including the old reporter bind for Intelligence. Changing
client images does not roll back collector data. Do not run both ingestion
writers concurrently or use a global Compose-down operation.
