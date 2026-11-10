"""Download messages and files from Discord servers you are a member of."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("discoop")
except PackageNotFoundError:
    __version__ = "0+unknown"
