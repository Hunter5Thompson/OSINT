# Self-hosted fonts — Hlíðskjalf Noir

Fonts used by the ODIN / WorldView frontend. All files are self-hosted; runtime
loads from `/fonts/...` (Vite serves `public/` at the document root). No
third-party CDN is queried at runtime.

Every `@font-face` declaration uses `font-display: swap` so the UI reveals
immediately with a fallback and re-flows once the WOFF2 arrives.

## Families

### Instrument Serif — `instrument-serif/`

- **License:** SIL Open Font License 1.1
- **Designer:** Rodrigo Fuenzalida / Instrument
- **Source:** <https://fonts.google.com/specimen/Instrument+Serif>
- **Canonical repo:** <https://github.com/Instrument/instrument-serif>

Files:

| File | Weight / Style | Notes |
|---|---|---|
| `InstrumentSerif-Italic.woff2` | 400 italic | Latin subset from Google Fonts v5 |
| `InstrumentSerif-Italic-Bold.woff2` | 700 italic | **Shim** — Google Fonts only ships Instrument Serif in one weight (400). This file is a byte-identical copy of the 400-italic WOFF2, kept under the bold filename so the `@font-face { font-weight: 700 }` declaration resolves to a real file instead of 404. The visual weight difference, if required by a future design, must be synthesised via CSS (`font-synthesis: weight`) or replaced with a genuine bold cut once available. |

### Hanken Grotesk — `hanken-grotesk/`

- **License:** SIL Open Font License 1.1
- **Designer:** Alfredo Marco Pradil / Hanken Design Co.
- **Source:** <https://fonts.google.com/specimen/Hanken+Grotesk>
- **Canonical repo:** <https://github.com/hanken-design/HankenGrotesk>

Files:

| File | Weight / Style | Notes |
|---|---|---|
| `HankenGrotesk-Variable.woff2` | 300–600 normal | Variable WOFF2, latin subset from Google Fonts v12. Covers U+0000–00FF and common extensions. |

### Martian Mono — `martian-mono/`

- **License:** SIL Open Font License 1.1
- **Designer:** Roman Shamin
- **Source:** <https://fonts.google.com/specimen/Martian+Mono>
- **Canonical repo:** <https://github.com/evilmartians/mono>

Files:

| File | Weight / Style | Notes |
|---|---|---|
| `MartianMono-Variable.woff2` | 300–500 normal | Variable WOFF2, latin subset from Google Fonts v6. |

## Placeholder / shim status

As of 2026-04-14, all files are **real WOFF2 binaries** from Google Fonts'
canonical delivery (latin subset). The only non-canonical file is
`InstrumentSerif-Italic-Bold.woff2`, which is a duplicate of the 400-italic
file (Google Fonts does not ship Instrument Serif 700). See the Instrument
Serif table above for how to replace it.

To refresh (e.g. after a Google Fonts version bump):

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
curl -sSLA "$UA" "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital,wght@1,400&family=Hanken+Grotesk:wght@300..600&family=Martian+Mono:wght@300..500&display=swap"
# Then pipe the returned URLs to curl, one per subset you want.
```

## Why self-host?

- No third-party request leaking user IP/referrer to Google.
- Deterministic caching (bundle hash changes only when we change fonts).
- Offline development.
- Compliance with the project rule _"no third-party CDNs at runtime"_.
