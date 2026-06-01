# Product

## Register

product

## Users

**Primary: Albert (Solo Analyst / AI Engineer)**
- Builds and operates the system end-to-end. Runs ODIN locally on an RTX 5090, Ubuntu, single-user mode. Comfortable with CesiumJS, FastAPI, LangGraph, Docker, vLLM.
- Context: monitoring geopolitical events, OSINT investigations, intelligence briefings. Deep work sessions on a single large desktop monitor. No mobile, no shared multi-user environment.
- Job-to-be-done: turn fragmented public feeds (RSS, GDELT, ADS-B, AIS, TLE, USGS, FIRMS, NotebookLM) into structured, queryable situational awareness, then write reports off the result.

**Secondary: Power-User / Independent Researcher**
- Self-hosts via Docker Compose, brings own API keys. May have less ML/infra depth than Albert but understands OSINT workflows.
- Context: region-focused analysis (one conflict zone, one threat actor). Reads the UI rather than pairs with it.
- Job-to-be-done: persistent situational dashboard for one or two specific scopes, plus ad-hoc deep dives via the agent.

Single-user system by design (PRD scope-exclusion). No login, no multi-tenancy.

## Product Purpose

ODIN's WorldView is a locally-runnable tactical intelligence platform. It fuses real-time public data feeds onto a photorealistic 3D globe, ingests structured event/entity claims into a Neo4j knowledge graph + Qdrant vector store, and lets the user query the corpus through a ReAct agent (Munin) for structured briefings.

It exists because the alternative, Palantir Gotham and similar commercial platforms, is proprietary, expensive, opaque, and cloud-bound. ODIN is the open, transparent, single-operator-class equivalent: same workflows, OSINT-only data, runs on one consumer GPU.

Success looks like: the operator can answer a geopolitical question in one session without leaving the app, sees the live map, queries the graph, reads the synthesized brief, and verifies every claim's provenance back to a source URL.

## Brand Personality

**Hlíðskjalf Noir**: Nordic Brutalism × Astronomical Geometry.

Three-word personality: **deliberate · instrumental · declassified.**

- **Voice**: editorial, not promotional. Reads like a paragraph from a published intelligence assessment, not a sales page. Numbered sections (§I · Layers, §IV · Ticker), warm-tinted greyscale, italic Instrument Serif headlines.
- **Tone**: calm under load. Even during pulsing incident markers or active agent streaming, the chrome stays still. Motion is sparse, precise, never decorative.
- **Emotional goal**: the user feels like an analyst at a worktable, not a player in a tactical sim. The Orrery marks the app's pulse the way a clockwork instrument marks time, quiet, certain, evidently mechanical.

Surface vocabulary: § paragraph numbering everywhere, Norse-mythology code names (Hugin = ingestion / "sees", Munin = agent / "remembers", Sentinel = incident, Hlíðskjalf = Odin's high seat / observation deck).

## Anti-references

ODIN explicitly avoids three saturated lanes that AI-generated and SaaS interfaces converge on:

- **AI-Chatbot Glassmorphism.** Frosted-glass bubbles as default, gradient headlines, animated floating orbs, ChatGPT/Claude UI clones. ODIN uses backdrop-blur once (HUD chrome over the 3D globe), purposefully, never decoratively.
- **Green-on-Black Hacker Terminal.** Phosphor-green text, monospace-only, CRT scanlines as default chrome. The CRT shader exists in ODIN but as an opt-in visual filter on the globe, not as the system's resting state. Default chrome is warm-tinted Hlíðskjalf greys, not Matrix green.
- **SaaS-Clean (Linear / Notion / Vercel).** Inter for everything, soft drop-shadows, purple-to-blue gradients, cards-in-cards, "everything is rounded". ODIN runs `border-radius: 0` outside the Orrery, ships Instrument Serif + Hanken Grotesk + Martian Mono (never Inter), and uses § hair-lines instead of card affordances.

Conceptual anti-reference (from PRD): **Palantir Gotham**, proprietary, cloud-only, opaque pricing, opaque models. ODIN is the open, local, transparent inverse.

## Design Principles

1. **Local-first, transparency by default.** Every byte of inference, ingestion, and storage runs on the operator's machine. The UI surfaces service health (vLLM, TEI, Neo4j, Qdrant, Redis) rather than hiding the stack. No telemetry, no cloud round-trips, no third-party trackers.

2. **Editorial calm, instrumental precision.** Reads like a magazine, operates like a measurement device. Typography carries hierarchy (Instrument Serif italic for headlines, Hanken Grotesk for body, Martian Mono for coordinates/IDs/timestamps); chrome stays still while data moves.

3. **Provenance over polish.** Every claim, event, and entity in the graph carries source URL, confidence score, and timestamp. The UI never displays a synthesized brief without making the underlying sources reachable in two clicks.

4. **Motion is signal, never decoration.** The Orrery and incident pulses are diegetic, they convey state (system pulse, incident severity). No hover animations on routine links, no bounce, no elastic. Honor `prefers-reduced-motion: reduce` globally.

## Accessibility & Inclusion

**Target: WCAG 2.2 AA as binding floor.**

- **Contrast**: body text ≥4.5:1, large text ≥3:1. The `--ash` token (3.3 to 3.8:1 vs `--void`) is decoration-only per spec, eyebrow labels, disabled state, ornamental timestamps. All readable body text uses `--stone` (~6.5:1) or higher. Sentinel-as-text-color requires a brighter variant; current 4.1:1 violates the floor.
- **Keyboard navigation**: every interactive element reachable in logical tab order. `:focus-visible` outline globally defined (currently missing, see audit findings). No `outline: none` without a documented replacement.
- **Semantic structure**: `<main>` landmark on every page; HUD panels use `<section role="region" aria-label>`; loaders use `role="status"` with descriptive `aria-label`.
- **Motion**: `prefers-reduced-motion: reduce` honored globally (Orrery, incident pulse, landing reveal, button flash). Test harness uses `[data-reduced-motion="true"]` attribute as jsdom-compatible equivalent.
- **Touch targets**: WCAG 2.5.8 AA (24×24px) as soft target. Map-dense interactive elements (layer toggles) may invoke the "essential" exception when justified, but should grow on hover/focus where feasible.
- **Form labels**: every input has an associated `<label>` or `aria-label`. Placeholders are never the only label.

Out of scope (deliberate, per PRD): mobile and tablet viewports. Anything below ~1280×800 shows a desktop-only block screen rather than degrading the HUD.
