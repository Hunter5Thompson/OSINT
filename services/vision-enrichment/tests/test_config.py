"""Phase 1 contract tests for vision-enrichment service Settings."""

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
