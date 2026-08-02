"""Repository-layout seam shared by checkout and flat-image infra tooling."""

from pathlib import Path


def find_repo_root(module_path: Path, *, fallback: Path | None = None) -> Path:
    """Find the monorepo root, falling back to the flat image working directory."""

    for parent in module_path.resolve().parents:
        if (parent / "services" / "frontend").is_dir():
            return parent
    return fallback or Path.cwd()
