# Orbital regression inputs

`iss-valid.tle` is the exact published sgp4 2.27 documentation pair, including
verified checksum digits. `celestrak-100651.json` is unchanged from the frozen
2026-10-09 GP feed. Provenance and complete-feed hash are in `sources.json`.
These are mathematical fixtures, not current physical-location verification.

`decoder-cases.json` deliberately mutates copied inputs, recalculating checksum
digits where necessary to isolate another grammar defect. Such mutated inputs
must never be called authentic orbital source data. Both Python service suites
consume this one matrix through their independently packaged parser copies.

`reference-vectors.json` uses sgp4 2.27's independently installed accelerated
C++ implementation, WGS72 and TEME km/km/s. Regenerate only in a separate pinned
environment with the frozen evidence directory (never fetch a changing feed):

```bash
/data/odin-caches/sgp4-reference-env/bin/python \
  tests/fixtures/satellites/generate_reference.py \
  /data/odin-goals/2026-10-09-repo-hardening/evidence/G05 \
  tests/fixtures/satellites
```

`qualify_satellite_js.mjs` performs the independent numeric gate against an
explicitly selected, checksum-verified package entry, without application or
network state. Frontend tests additionally run the same vectors against the
actual installed and pinned dependency. Numeric tolerances were fixed before
the first reference comparison in DEC-005.
