# Mapshaper offline bundle

`mapshaper-0.7.49-offline.tgz` is a deterministic build input for the Spatial
Scope compiler. It is not an ingestion-service runtime dependency. The production
wheel and Docker image deliberately exclude the compiler, Shapely, and this archive.

The adjacent manifest locks Mapshaper and its six-package GeoJSON runtime closure.
Every downloaded npm archive is checked twice during regeneration: npm's reported
integrity must equal the reviewed manifest value, and the script independently
recalculates the `sha512` npm integrity from the downloaded bytes. The Mapshaper
source archive is additionally checked against its reviewed SHA-256.

Rebuild from the repository root with Python 3.12+, npm, GNU tar 1.35, and gzip
1.12. Regeneration is the only networked part of this procedure:

```bash
python3 services/data-ingestion/spatial_catalog/tools/rebuild_mapshaper_bundle.py \
  --output /tmp/mapshaper-0.7.49-offline.tgz
cmp /tmp/mapshaper-0.7.49-offline.tgz \
  services/data-ingestion/spatial_catalog/data/mapshaper-0.7.49-offline.tgz
```

The script fails before publishing its output unless every upstream integrity and
the final source-lock hash match. The required final digest is:

```text
sha256:68b39a96791d6e62b51163e8e39f1f32ba55c0d3b9fbceade58ad07db7dae8f1
```

To run the offline compiler from a checkout, install its explicit build extra and
provide a Node runtime satisfying the bundle's reviewed engine range:

```bash
cd services/data-ingestion
uv sync --extra spatial-catalog
uv run python -m spatial_catalog build --help
```

The compiler checks the actual `node --version` before Mapshaper is invoked and
records it in the non-revision-forming `build-provenance.json` report.
