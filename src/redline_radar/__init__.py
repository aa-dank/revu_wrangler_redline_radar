"""Redline Radar package metadata helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import tomllib


def _read_version_from_pyproject() -> str:
	"""Read version from pyproject.toml when package metadata is unavailable."""
	pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
	data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
	return str(data["project"]["version"])


try:
	__version__ = version("redline-radar")
except PackageNotFoundError:
	__version__ = _read_version_from_pyproject()
