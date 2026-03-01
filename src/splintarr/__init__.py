"""Splintarr - Intelligent backlog search automation for Sonarr and Radarr."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _get_version() -> str:
    """Get version from package metadata, falling back to pyproject.toml."""
    try:
        return version("splintarr")
    except PackageNotFoundError:
        pass

    # Fallback: read from pyproject.toml (for Docker/source installs)
    for candidate in [
        Path(__file__).parent.parent.parent / "pyproject.toml",  # src/splintarr/../../
        Path("/app/pyproject.toml"),  # Docker container path
    ]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if line.strip().startswith("version"):
                    return line.split("=")[1].strip().strip('"').strip("'")

    return "dev"


__version__ = _get_version()
__author__ = "menottim"
__license__ = "MIT"
