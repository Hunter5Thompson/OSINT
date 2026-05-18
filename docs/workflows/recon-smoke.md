# Recon Viewer — End-to-End Smoke

**Date:** _fill on first execution_
**Operator:** _initials_

Manual smoke for the Skyfall Recon MVP. Run this before merging the feature branch
to `main` and after any change touching the recon stack.

The Phase-0 renderer-parity gate is at `recon-phase-0-smoke.md` and already PASSED
on 2026-05-18 with **mkk** as the chosen renderer. Spark was eliminated
(`THREE.Matrix2 is not a constructor` on the pinned three@0.165.0).

The originally-spec'd 30 Mbps bandwidth gate is also relaxed for this smoke. It is
physics-bound: 240 MB / 30 Mbps ≈ 64 s of pure transfer before any decode/upload,
so first-frame timing is dominated by the operator's actual link speed. Record
what you measure; don't fail the run on raw seconds alone.

## Pre-requisites

1. **License records populated** (per Task 7 fail-closed contract):
   - `services/backend/static/recon/licenses/spacenet-2.txt` — paste SpaceNet 2 license text verbatim, non-empty
   - `services/backend/static/recon/licenses/spacenet-4.txt` — paste SpaceNet 4 license text verbatim, non-empty
   - `services/backend/static/recon/licenses/records.json` — populate `records.SpaceNet 2` and `records.SpaceNet 4` with all five required fields (`slug`, `spdx`, `upstream_url`, `verified_by`, `verified_at`)
   - Without this, `./odin.sh recon bootstrap` raises `BootstrapPartialError` ("only 0/12 scenes emitted"). Pass `--allow-partial` only for experimentation; the smoke run requires the full 12 scenes.
2. `hf` (Hugging Face CLI) on PATH.
3. ~3 GB free disk space at `services/backend/static/recon/` for the 12 PLYs.

## Step 1 — Bootstrap

```bash
cd ~/ODIN/OSINT
./odin.sh recon bootstrap
ls -lh services/backend/static/recon/    # expect 12 .ply files
python3 -c "import json; m=json.load(open('services/backend/data/recon_manifest.json')); print(len(m['scenes']), 'scenes')"
```

Expected: 12 scenes emitted, `LICENSES.md` written next to the PLYs.

## Step 2 — Start Interactive Stack

```bash
./odin.sh up interactive
./odin.sh smoke    # health checks should all be green
curl -s http://localhost:8080/api/recon/scenes | python3 -m json.tool | head -40
```

Expected: backend running on :8080, `/api/recon/scenes` returns a JSON object with 12 scenes, each `ply_url` ending in `?sha=<64-char-sha>`.

## Step 3 — Browser Smoke

Open `http://localhost:5173/worldview` in a desktop browser with WebGL2 support
(Chrome, Firefox, or any Chromium). DevTools open in another panel.

### Hotspot visibility
- [ ] **12 amber pins visible** on the globe — 8 over Jacksonville (Florida), 4 over New York City. Use shift+drag and zoom to confirm.

### Click → modal opens
- [ ] Click any JAX pin (e.g. **jax_004** at 158 MB — smallest scene)
- [ ] Modal opens with the scene's `display_name` and an attribution footer pulled from the bootstrap-generated string
- [ ] No bandwidth-warning dialog on a fast connection (4G/Wi-Fi); BandwidthGuard fires only on 2G/3G

### Renderer load + camera
- [ ] Loading progress bar visible, byte counter increments
- [ ] First navigable frame appears in under ~10 seconds on a workstation-class connection (load-time depends on hardware/network — for reference, Phase-0 measured 7.6 s for jax_068 at 240 MB)
- [ ] **WASD + Q/E** moves the camera; **mouse-look** works while pointer is locked (click the canvas to engage)
- [ ] Strafe-right (D) moves visually to the right (regression test for the 2026-05-18 cross-product fix in `mkkRenderer.ts`)

### LARGE badge
- [ ] Close the modal (X button or ESC)
- [ ] Open **nyc_219** (324 MB)
- [ ] Top-center of modal shows a `LARGE — 309 MB` badge (red border, amber text)

### PNG capture
- [ ] Click the Capture button in the HUD (top-left)
- [ ] Browser triggers a PNG download named `recon-nyc_219-<timestamp>.png`
- [ ] Open the file — it shows the live render, not a blank frame (validates `preserveDrawingBuffer: true`)

### Error UI + Retry
- [ ] Open DevTools → Network tab → Right-click the `/static/recon/NYC_010_final.ply` request → **Block request URL**
- [ ] Close any open recon modal, then click **nyc_010** pin
- [ ] Modal opens, transitions to error state with the failure message and a **Retry** button
- [ ] Unblock the URL, click **Retry** — scene loads cleanly

### BandwidthGuard
- [ ] DevTools → Network tab → throttling profile = **Slow 3G** (or any 2G/3G preset)
- [ ] Close any open modal, click **jax_068** pin
- [ ] **Bandwidth confirm dialog** appears with the size in MB and **Load anyway** / **Cancel** buttons
- [ ] Cancel — modal closes
- [ ] Re-open same pin — dialog appears again (loadAllowed reset on close)
- [ ] Disable throttling, re-open — no dialog, scene loads directly

### WebGL2 refusal
- [ ] In a separate browser that doesn't support WebGL2 (or a Chromium launched with `--disable-webgl2`), open the same scene
- [ ] Modal opens but displays the WebGL2 fallback message + Close button; no canvas mounted, no PLY fetched

### ESC behavior
- [ ] With a scene open, press ESC → modal closes
- [ ] Open the same scene → modal re-opens, bandwidth prompt re-appears if metered

### Bundle isolation
- [ ] DevTools → Network tab → reload the page → confirm `mkkRenderer-*.js` chunk is **not** fetched on initial page load
- [ ] Click any recon pin → confirm the chunk is now fetched (visible in Network as a separate JS request, ~700 KB)

## Step 4 — Per-Scene Load Time Table

For each of the 12 scenes, click the pin, time first-navigable-frame, record:

| scene_id | size (MB) | first_progress_ms | first_frame_ms | notes |
|----------|----------:|------------------:|---------------:|-------|
| jax_004  |       151 |                   |                |       |
| jax_068  |       229 |                   |                |       |
| jax_164  |       277 |                   |                |       |
| jax_168  |       253 |                   |                |       |
| jax_175  |       222 |                   |                |       |
| jax_214  |       212 |                   |                |       |
| jax_260  |       217 |                   |                |       |
| jax_264  |       260 |                   |                |       |
| nyc_004  |       232 |                   |                |       |
| nyc_010  |       306 |                   |                |       |
| nyc_219  |       309 |                   |                |       |
| nyc_336  |       204 |                   |                |       |

## Step 5 — Sign-off

```
Smoke run date: __________
Operator:       __________
All checkboxes passed:  yes / no (note failures inline above)
Approved to merge:      yes / no
```

## Known Limitations (Spec §3a Non-Goals)

- No live training; only the 12 pre-built scenes
- No commercial satellite imagery procurement
- Mobile is degraded (BandwidthGuard warns); desktop is the target
- No editing/annotating splat scenes inside WorldView
- Single-user, no auth, no multi-tenancy
