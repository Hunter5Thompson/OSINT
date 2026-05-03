"""Qdrant doctor CLI for the WorldView platform.

Usage:
    uv run python -m qdrant_doctor          # uses defaults from env/settings
    odin-qdrant-doctor                      # via installed entry point
    odin-qdrant-doctor --help

Exit codes:
    0  All checks passed (or only warnings issued).
    1  One or more FAIL conditions detected.
"""

from __future__ import annotations

import sys
from typing import Any

import click
from qdrant_client import QdrantClient

from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

__all__ = ["run_doctor", "main"]

# ANSI color codes for terminal output
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}OK{_RESET}    {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}WARN{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {_BOLD}INFO{_RESET}  {msg}")


def _section(title: str) -> None:
    print(f"\n{_BOLD}=== {title} ==={_RESET}")


def run_doctor(
    *,
    qdrant_url: str,
    collection_name: str,
    enable_hybrid: bool,
    v2_collection: str | None = None,
) -> int:
    """Run all Qdrant health checks.

    Returns:
        0 if all checks passed (warnings allowed).
        1 if any FAIL condition was detected.
    """
    failed = False

    _section("Qdrant Doctor")
    _info(f"URL:             {qdrant_url}")
    _info(f"Collection:      {collection_name}")
    _info(f"enable_hybrid:   {enable_hybrid}")

    # ------------------------------------------------------------------
    # 1. Connectivity + collection list
    # ------------------------------------------------------------------
    _section("Collection Existence")
    try:
        client = QdrantClient(url=qdrant_url)
        collections = client.get_collections().collections
        collection_names = {c.name for c in collections}
    except Exception as exc:
        _fail(f"Cannot connect to Qdrant at {qdrant_url}: {exc}")
        return 1

    if collection_name not in collection_names:
        if enable_hybrid:
            _fail(f"Collection '{collection_name}' does not exist (required for hybrid mode).")
            return 1
        else:
            _fail(f"Collection '{collection_name}' does not exist (required for dense-only runtime).")
            return 1
    else:
        _ok(f"Collection '{collection_name}' exists.")

    # Warn about odin_v2 if relevant
    if v2_collection and v2_collection not in collection_names and not enable_hybrid:
        _warn(
            f"Collection '{v2_collection}' (Phase 2) is absent, "
            "but hybrid is disabled — this is expected for Phase 1 runtime."
        )

    # ------------------------------------------------------------------
    # 2. Fetch collection info
    # ------------------------------------------------------------------
    _section("Schema Inspection")
    try:
        info = client.get_collection(collection_name)
    except Exception as exc:
        _fail(f"Cannot retrieve collection info for '{collection_name}': {exc}")
        return 1

    params = info.config.params
    vectors = params.vectors
    sparse_vectors = params.sparse_vectors
    point_count = info.points_count

    _info(f"Points:          {point_count}")

    # Describe vector config
    if isinstance(vectors, dict):
        _info(f"Vector config:   named — {list(vectors.keys())}")
        for name, vp in vectors.items():
            _info(f"  [{name}]  size={vp.size}  distance={vp.distance.value if hasattr(vp.distance, 'value') else vp.distance}")
    else:
        dist_str = vectors.distance.value if hasattr(vectors.distance, "value") else str(vectors.distance)
        _info(f"Vector config:   unnamed  size={vectors.size}  distance={dist_str}")

    if sparse_vectors:
        _info(f"Sparse vectors:  {list(sparse_vectors.keys())}")
    else:
        _info("Sparse vectors:  (none)")

    # ------------------------------------------------------------------
    # 3. Schema validation
    # ------------------------------------------------------------------
    _section("Schema Validation")
    try:
        validate_collection_schema(info, enable_hybrid=enable_hybrid)
        _ok(f"Schema matches expected {'hybrid' if enable_hybrid else 'dense-only'} contract.")
    except QdrantSchemaMismatch as exc:
        _fail(str(exc))
        failed = True

    # ------------------------------------------------------------------
    # Result summary
    # ------------------------------------------------------------------
    _section("Result")
    if failed:
        _fail("One or more checks failed. See above for details.")
        return 1

    _ok("All checks passed.")
    return 0


@click.command()
@click.option(
    "--qdrant-url",
    default=None,
    envvar="QDRANT_URL",
    help="Qdrant base URL (default: from QDRANT_URL env or http://localhost:6333).",
)
@click.option(
    "--collection",
    default=None,
    envvar="QDRANT_COLLECTION",
    help="Collection name to check (default: from QDRANT_COLLECTION env or 'odin_intel').",
)
@click.option(
    "--hybrid/--no-hybrid",
    default=None,
    envvar="ENABLE_HYBRID",
    help="Enable hybrid schema checks (default: from ENABLE_HYBRID env or False).",
)
@click.option(
    "--v2-collection",
    default="odin_v2",
    envvar="QDRANT_V2_COLLECTION",
    help="Phase 2 collection name to warn about if absent (default: odin_v2).",
)
def main(
    qdrant_url: str | None,
    collection: str | None,
    hybrid: bool | None,
    v2_collection: str,
) -> None:
    """Qdrant collection health check for the WorldView platform.

    Validates that the configured Qdrant collection exists and has the correct
    vector schema for the active runtime mode (dense-only or hybrid).

    Exits with code 0 on success (warnings allowed), 1 on any FAIL.
    """
    # Fall back to project settings for unset options
    from config import settings

    url = qdrant_url or settings.qdrant_url
    coll = collection or settings.qdrant_collection
    use_hybrid = hybrid if hybrid is not None else getattr(settings, "enable_hybrid", False)

    exit_code = run_doctor(
        qdrant_url=url,
        collection_name=coll,
        enable_hybrid=use_hybrid,
        v2_collection=v2_collection,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
