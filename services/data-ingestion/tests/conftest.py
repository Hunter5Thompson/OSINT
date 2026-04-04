"""Shared pytest configuration for data-ingestion tests."""

collect_ignore_glob: list[str] = []

# NLM tests require optional dependencies (click, pydub) from the
# [project.optional-dependencies] notebooklm group.  Skip collection
# when those packages are not installed so the rest of the suite still
# runs cleanly.
try:
    import click  # noqa: F401
except ModuleNotFoundError:
    collect_ignore_glob.append("test_nlm_cli.py")

try:
    import pydub  # noqa: F401
except ModuleNotFoundError:
    collect_ignore_glob.append("test_nlm_transcribe.py")
