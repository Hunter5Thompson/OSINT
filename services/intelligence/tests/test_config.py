"""Phase 1 contract tests for intelligence service Settings."""

import os
from unittest.mock import patch

from config import Settings

# Phase 1 contract: canonical collection name
_CANONICAL_COLLECTION = "odin_intel"


class TestQdrantCollectionDefault:
    """qdrant_collection default must be the canonical collection name."""

    def test_qdrant_collection_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.qdrant_collection == _CANONICAL_COLLECTION


class TestHybridFlagDefault:
    """enable_hybrid must default to False (Phase 2 gate: requires sparse vectors in Qdrant)."""

    def test_enable_hybrid_is_false_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            # Phase 2 will flip this to True once sparse vectors exist in Qdrant.
            # Until then this must stay False to avoid silent empty-result degradation.
            assert s.enable_hybrid is False

    def test_enable_hybrid_can_be_overridden_via_env(self) -> None:
        """Ensure the flag is still configurable — just off by default."""
        with patch.dict(os.environ, {"ENABLE_HYBRID": "true"}, clear=True):
            s = Settings(_env_file=None)
            assert s.enable_hybrid is True
