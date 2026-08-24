"""The reported version must identify the deployed artefact, not the checkout.

The container ships without a `.git` directory, so `git describe` cannot answer
there. `VELMO_VERSION` is stamped into the image at build time and wins over
everything else — without that precedence the deployed app would report the
package version for every release, and the version banner would be a lie.
"""

import pytest
from velmo.mlops.version import VERSION_ENV, current_version


def test_current_version_is_a_nonempty_string():
    value = current_version()
    assert isinstance(value, str)
    assert value != ""


def test_the_stamped_version_wins_over_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    # In the image this is the only source that can be right; the tests run
    # inside a Git checkout, so `git describe` would otherwise answer first.
    monkeypatch.setenv(VERSION_ENV, "v1.2.3")

    assert current_version() == "v1.2.3"


def test_a_blank_stamp_falls_back_instead_of_reporting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unset build arg reaches the container as an empty string. Letting it win
    # would render an empty version label rather than the next-best answer.
    monkeypatch.setenv(VERSION_ENV, "   ")

    assert current_version().strip() != ""


def test_without_a_stamp_the_checkout_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VERSION_ENV, raising=False)

    assert current_version().strip() != ""
