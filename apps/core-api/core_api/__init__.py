"""Ryzen AI 9 laptop Core Backend."""

from .app import create_app
from .config import Settings

__all__ = ["Settings", "create_app"]
