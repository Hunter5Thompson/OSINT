# Recon availability contract

Recon is optional. The core API can start without a scene catalogue or PLY
assets. Availability is evaluated during backend startup; changed inputs need
a reviewed backend restart before a new catalogue is served.

| Configuration | Scene list | UI |
| --- | --- | --- |
| `RECON_MODE=auto` (default), no explicit manifest path and no default manifest | HTTP 200, `scenes: []`, `availability: disabled`, `reason: not_configured` | No Recon scenes configured; layer off |
| `RECON_MODE=disabled` | HTTP 200, empty/inactive catalogue, `reason: operator_disabled` | Recon disabled by operator; layer off |
| `RECON_MODE=enabled`, or an explicit `RECON_MANIFEST_PATH` in auto mode, with missing/invalid inputs | HTTP 503 | Recon scene data unavailable; Retry |
| Valid manifest and matching local assets in auto/enabled mode | HTTP 200, `availability: available`, `reason: null` | Scene pins can be enabled |

Disabled Recon scene detail requests return HTTP 404. A configured but broken
catalogue returns HTTP 503 for scene details. A valid empty catalogue reports
available with no scenes; the UI keeps its empty layer off. Recon failures do
not become a claim that unrelated data or models are healthy.

Before publishing a catalogue, the backend checks each asset's location, byte
size and full SHA256 against the manifest. Hashing runs outside the event loop.
A missing directory is never created during module import; read-only release
inputs therefore do not prevent core startup. Existing immutable-cache and
Range-request behavior remains available for delivered assets.

The frontend validates responses before drawing scene pins. Older servers
that return only `scenes` remain compatible. Invalid catalogue responses stay
visible as delivery errors. All mounted consumers share one request/cache;
Retry updates both the layer list and the scene viewer.

## Providing reviewed assets

License verification and the renderer smoke remain separate gates in
[recon-smoke.md](recon-smoke.md). Optional inactivity does not satisfy them or
authorize downloads. Put large PLY assets and their license records under
`/data`; check fresh free space before a multi-GB download.

For the immutable release configuration, place the reviewed manifest at
`$ODIN_RELEASE_DATA_DIR/backend/recon_manifest.json` and PLY files in its
`recon/` directory, then set `RECON_STATIC_DIR=/app/data/recon` in the reviewed
deployment environment. The existing `/app/data` bind is read-only. No code
mount is required. Existing non-release deployments can retain the default
`/app/static/recon` path when that directory is actually delivered.

The image smoke checks the real backend CMD twice on an isolated internal
network: unconfigured Recon is inactive and required missing Recon is HTTP
503, while both core health responses retain the baked build revision.
Automated tests and fixture browser checks do not establish deployed behavior,
licensed asset completeness, renderer performance or human acceptance.
