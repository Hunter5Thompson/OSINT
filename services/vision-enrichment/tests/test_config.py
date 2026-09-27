"""Phase 1 contract tests for vision-enrichment service Settings."""

import os
from unittest.mock import patch

from pydantic import ValidationError

from config import Settings

# Phase 1 contract: canonical collection name
_CANONICAL_COLLECTION = "odin_intel"


class TestQdrantCollectionDefault:
    """qdrant_collection default must be the canonical collection name."""

    def test_qdrant_collection_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.qdrant_collection == _CANONICAL_COLLECTION


def test_image_limits_and_root_are_configurable_from_environment():
    with patch.dict(
        os.environ,
        {"VISION_IMAGE_ROOT": "/fixture/images", "VISION_MAX_FILE_SIZE_MB": "4"},
        clear=True,
    ):
        settings = Settings(_env_file=None)
    assert settings.vision_image_root == "/fixture/images"
    assert settings.vision_max_file_size_mb == 4


def test_image_maximum_must_be_positive():
    with patch.dict(os.environ, {"VISION_MAX_FILE_SIZE_MB": "0"}, clear=True):
        try:
            Settings(_env_file=None)
        except ValidationError:
            return
    raise AssertionError("zero image limit must be rejected")
