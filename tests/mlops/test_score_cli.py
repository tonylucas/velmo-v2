import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "velmo.mlops.score", *args],
        capture_output=True,
        text=True,
    )


def test_cli_passes_under_low_threshold(tmp_path):
    result = _run("--min-score", "0.0", "--report", str(tmp_path / "report.md"))
    assert result.returncode == 0, result.stderr


def test_cli_blocks_under_impossible_threshold(tmp_path):
    result = _run("--min-score", "1.0", "--report", str(tmp_path / "report.md"))
    assert result.returncode == 1
    assert "DELIVERY BLOCKED" in result.stdout
