"""Splintarr - Intelligent backlog search automation for Sonarr and Radarr."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("splintarr")
except PackageNotFoundError:
    __version__ = "dev"

__author__ = "menottim"
__license__ = "MIT"
