"""Tests for pipeline error classes."""

import pytest


def test_extraction_transient_error_exists():
    from pipeline import ExtractionTransientError
    assert issubclass(ExtractionTransientError, Exception)


def test_extraction_config_error_exists():
    from pipeline import ExtractionConfigError
    assert issubclass(ExtractionConfigError, Exception)


def test_error_classes_are_distinct():
    from pipeline import ExtractionConfigError, ExtractionTransientError
    assert not issubclass(ExtractionTransientError, ExtractionConfigError)
    assert not issubclass(ExtractionConfigError, ExtractionTransientError)
