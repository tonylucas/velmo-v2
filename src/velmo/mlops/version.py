"""Identify the running agent version: the baked-in stamp, the Git tag, else the
package version.

The Git tag is the immutable version identifier (see the design, decision #5),
but `git describe` only answers inside a checkout — and the deployed image
carries no `.git` directory, so in production it would silently fall back to the
package version and report the same string for every release. `VELMO_VERSION` is
therefore stamped into the image at build time and takes precedence: it travels
with the artefact, so what the container reports is what was actually deployed.
"""

from __future__ import annotations

import os
import subprocess
from importlib.metadata import PackageNotFoundError, version

VERSION_ENV = "VELMO_VERSION"


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


def _stamped_version() -> str | None:
    # Blank or whitespace-only means "not stamped" — an unset build arg must not
    # win over the Git tag and turn the version into an empty label.
    return (os.getenv(VERSION_ENV) or "").strip() or None


def current_version() -> str:
    return _stamped_version() or _git_describe() or _package_version()
