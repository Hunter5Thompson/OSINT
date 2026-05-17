# Recon Licenses Directory

This directory backs the bootstrap license audit. For each source dataset
the recon scenes derive from, two artifacts must exist before scenes from
that source are eligible for the manifest:

1. **`<slug>.txt`** — verbatim upstream license text (non-empty). Copy
   from the dataset's homepage; never paraphrase.
2. **Entry in `records.json`** — with `slug`, `spdx`, `upstream_url`,
   `verified_by`, `verified_at` (all non-empty).

Anything missing → bootstrap excludes the affected scenes (fail-closed).
The audit also generates `../LICENSES.md` from these records.
