"""agents-dialpad: chat with the AI coding CLIs on your computer from your phone."""
from importlib import metadata

try:
    __version__ = metadata.version("agents-dialpad")
except metadata.PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0.0.0+unknown"
