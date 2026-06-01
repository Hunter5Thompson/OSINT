# README assets

Drop the README hero media here, then uncomment the `<img>` block at the top of `/README.md`.

## What converts best (in order)
1. **`demo.gif`** — a ~10 s loop of the rotating globe with live layers toggling + one Munin query returning a synthesized answer. Motion sells a 3D/shader project far better than a still.
2. **`hero.png`** — one strong still of the globe with several layers active (flights + events + a hotspot pulse), ideally with the § chrome visible.

## Capture tips
- Resolution: **≥ 1280×720** (the README renders it at 820px wide, so capture at 2× for crispness).
- Keep files small so the README loads fast: **`hero.png` ≤ 1 MB**, **`demo.gif` ≤ 8 MB**.
  - GIF: `ffmpeg -i clip.mov -vf "fps=12,scale=820:-1:flags=lanczos" -loop 0 demo.gif` then `gifsicle -O3 --lossy=60 demo.gif -o demo.gif`.
  - Or record straight to GIF with a screen recorder and compress via `gifsicle`.
- Show **real data**, not an empty globe — toggle a few layers and run one query first.
- Avoid leaking anything sensitive (tokens in a devtools panel, private endpoints).

## Wiring it into the README
Uncomment the hero block in `/README.md` (just below the tagline). For a GIF, swap the filename:

```html
<p align="center">
  <img src="docs/assets/demo.gif" alt="WorldView — live intelligence globe" width="820">
</p>
```
