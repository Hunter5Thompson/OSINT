# Bounded analysis requests (BP-02)

All four backend model triggers authorize first, then acquire one common permit
before spatial/store work or SSE. `MODEL_MAX_CONCURRENCY=1` is the conservative
default; queue capacity is **zero**. Exhaustion returns JSON 429 with `MODEL_BUSY`,
a human-readable message and `Retry-After: 1`. Admission failure returns 503.
No rejected request writes a user message or contacts Intelligence.

`MODEL_ADMISSION_DIR=/tmp/odin-backend-model-admission` is a stable local Linux
filesystem namespace. `flock` makes the limit apply across backend workers, not
just one event loop. All workers must use the same directory and capacity.
Do not unlink/replace slot files while any worker runs. Multiple containers
require a shared local bind directory; separate filesystems/hosts are outside
this contract. Kernel file ownership releases permits on worker death without
an expiring lease admitting overlapping work. No Redis availability dependency
is introduced. Capacity changes require draining all workers first.

A request-scoped FastAPI dependency owns the permit through the full SSE
response. Completion, route errors, generator errors, disconnect and task
cancellation release it. The lifecycle contract follows the
[FastAPI request dependency scope](https://fastapi.tiangolo.com/advanced/advanced-dependencies/).

`MODEL_TIMEOUT_S=300` bounds the complete downstream HTTP operation, including
a slow peer that evades per-read timeouts. Intelligence additionally owns its
query task until completion, disconnect or `QUERY_TIMEOUT_S=240` (including the
legacy path), then cancels and joins it. Its disconnect watcher also has a
cooperative stop flag because a Starlette receive probe can consume cancellation.
The existing ReAct deadline remains independently active.

This bounds admitted backend requests and cooperative Intelligence task cleanup.
A bounded live probe on 2026-11-01 used the real HTTP routes and synthesis
ChatOpenAI adapter against the already running local vLLM qwen3.5 model. Client
abort, backend timeout and Intelligence timeout all returned active/waiting
requests and KV-cache usage to zero, observed 57-111ms after the HTTP terminal
point; permits were reusable. Retrieval was replaced with one benign model call,
and no database/model deployment was changed. These measurements include gauge
publication latency and are not a universal physical generation limit: backend
admission can be released before downstream cancellation is observed, and other
model clients do not share its permits. llama.cpp and full retrieval/tool workflow
cancellation remain unqualified. Deploy the updated Intelligence image with BP-02
to obtain the downstream cancellation behavior.

The JSON-only downstream contract exposes no intermediate agent progress.
Backend SSE therefore reports `intelligence / processing`, then the real result
or error. It no longer fabricates three agent stages. Browser requests own their
AbortController, invalidate stale callbacks, and cancel on replacement/unmount.
Dossier UI shows the real failure reason, explicit cancellation, recoverable
chat reload errors and clickable HTTP(S) source URLs; source IDs stay text.
