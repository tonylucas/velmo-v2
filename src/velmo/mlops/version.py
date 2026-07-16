"""Identify the evaluated agent version: the Git tag, else the package version.

The Git tag is the immutable version identifier (see the design, decision #5).
Offline / outside a checkout it falls back to the installed package metadata.
"""

from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version


def _git_describe() -> str | None:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tag = result.stdout.strip()
    return tag or None


def _package_version() -> str:
    try:
        return version("velmo-v2")
    except PackageNotFoundError:
        return "2.0.0"


def current_version() -> str:
    return _git_describe() or _package_version()
