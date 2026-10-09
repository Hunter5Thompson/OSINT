# Browser gate for the built frontend

The `test-frontend-browser` CI job installs the locked Node 22 dependencies,
installs the matching Playwright Chromium, builds the frontend with the commit
revision and runs six browser scenarios against that built `dist` directory.
It does not use a Vite development server or transform application source to
expose the Cesium Viewer. Traces, screenshots and a JSON result report are
uploaded for seven days, including failed runs.

## Local reproduction

Run from `services/frontend`. Put the browser cache and evidence under `/data`.
The example assumes the named directories are owned by the current operator:

```bash
npm ci --cache /data/odin-caches/npm
PLAYWRIGHT_BROWSERS_PATH=/data/odin-caches/playwright npx playwright install chromium
npm run lint
npm run type-check
npm run type-check:browser
export ODIN_BUILD_REVISION="$(git rev-parse HEAD)"
VITE_SPATIAL_SCOPE_ENABLED=true npm run build
PLAYWRIGHT_BROWSERS_PATH=/data/odin-caches/playwright \
  ODIN_BROWSER_ARTIFACTS=/data/odin-browser-evidence/reviewed-run \
  npm run test:browser
```

Use a fresh evidence directory for each run: Playwright replaces its output
directory. `ODIN_BROWSER_PORT` selects an unused unprivileged loopback port;
the default is `15174`. The runner owns and stops a strict-port preview server
and refuses to reuse an existing listener. It does not start ODIN services or
connect to production. `--with-deps` is used in the disposable CI runner; it
must not be treated as implicit authorization to change workstation packages.

## Contracts covered

- Optional Recon inactive/off with explicit reason and availability retry.
- Configured HTTP 503 and malformed Recon responses, visible failure, recovery
  and on/off controls. Deep-linked requested state is retained on recovery.
- Spatial Ukraine selection using the tracked reference catalog, declared media
  types, immutable asset hashes and strong metadata ETags. The fixture projects
  the public API shape, rather than serving raw internal manifest descriptors.
- Visible spatial precision, time preset, paused single-step, reverse replay,
  NOW, layer controls and WorldView → Briefing → WorldView lifecycle.
- Aircraft and vessel selection by actual Cesium canvas mouse picks after the
  existing Search UI positions the camera. Nullable measurements must appear
  as `unknown` in specific selected-contact fields.
- The actual served `build-info.json` must contain `ODIN_BUILD_REVISION`.

Each scenario records API request paths, unhandled requests, blocked external
origins, uncaught page errors, catalog revision and the renderer observed from
the existing WebGL context. Unexpected API requests/writes, uncaught errors and
a renderer other than the configured SwiftShader fail the run. All API responses
are explicit fixtures; external HTTP/WebSocket traffic and service workers are
blocked. The reference geometry comes from versioned repository data, without
a backend import, production API or copied catalog cache.

## Evidence boundaries

Chromium uses ANGLE SwiftShader in this gate. A pass proves these browser
interactions and software WebGL rendering of the built SPA with synthetic
providers. It does not prove native RTX performance, dense live Globe usability,
current boundaries, real ingestion/model quality, production deployment or
human visual acceptance. Recon availability controls do not prove PLY download
or Gaussian-splat rendering: the scene fixture provides catalog metadata only.
The existing application image CMD checks and release gates remain separate.

Primary runner documentation: [Playwright CI](https://playwright.dev/docs/ci),
[network routing](https://playwright.dev/docs/network) and
[trace viewer](https://playwright.dev/docs/trace-viewer).
