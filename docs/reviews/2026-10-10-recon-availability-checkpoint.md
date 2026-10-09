# Recon — optional availability checkpoint

G02/UI-02 is repaired in the isolated source branch; production deployment
and real licensed scene/renderer acceptance remain open. The current live
backend still returns HTTP 503. No production container or data was changed.

## Observed cause

On 10 October 2026, `osint-backend-1` had neither
`/app/data/recon_manifest.json` nor PLY files under `/app/static/recon`, and no
explicit `RECON_*` environment configuration. The existing API treated this
unconfigured optional capability as a service error, while the layer list
could still show Recon ON. Malformed configured JSON could stop core startup.

## Resulting behavior

`RECON_MODE=auto|enabled|disabled` distinguishes unconfigured optional Recon
from configured delivery failures. Auto retains existing delivered scenes;
no default manifest and no explicit manifest path means HTTP 200 with an
empty, explicitly inactive catalogue. Operator-disabled Recon also reports
inactive. Required/configured missing or invalid inputs retain HTTP 503.
Core startup survives those failures and an invalid optional static path.

Before advertising scenes, startup verifies the local asset path, download
URL, byte size and full SHA256 off the event loop. Static directories are no
longer created during import. Existing immutable-cache/Range checks stay
green. The frontend validates catalogue responses, shows per-layer status,
keeps unavailable/empty Recon off and offers Retry. All consumers share one
observable cache; retry updates both layer list and viewer. Older API
responses containing only scenes remain compatible.

The operational matrix and reviewed read-only data layout are documented in
[recon-availability.md](../workflows/recon-availability.md). This change does
not download assets or replace license/renderer acceptance.

## Evidence and limits

- Startup behavior first failed for auto absence, disabled malformed JSON and
  configured malformed JSON. Corrected RED used actual HTTP/startup behavior;
  an earlier Pydantic monkeypatch setup failure is not a behavioral RED.
- Four delivered-asset defects were red: missing file, byte-size mismatch,
  same-size SHA mismatch and a URL pointing at a missing file. Invalid static
  path import also failed before the fix.
- Frontend RED covered inactive/error distinctions, shared retry, malformed
  responses, layer availability and disabled toggles. Existing successful
  catalogue/cache behavior remains tested.
- Whole-service frontend: 699 tests; ESLint, TypeScript and build passed.
  Backend: 912 tests and Mypy across 92 files passed. Ops: 89 tests passed.
  Service/changed test/ops Ruff and diff checks passed.
- The previous backend image at clean `099037f` fails the new real image
  smoke because unconfigured Recon returns 503. New images must be built
  from the new clean commit before claiming image-level GREEN.

Raw logs live under
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G01/` with `recon` in the
filename. The preliminary host build used the previous commit metadata
input only to check compilation; it is not release provenance. The actual
clean-commit image build and process revision checks are separate evidence.
No remote CI, deployed revision, native GPU or human acceptance is claimed.
