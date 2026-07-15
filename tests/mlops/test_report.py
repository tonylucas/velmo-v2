from velmo.mlops import Scores, write_report

SAMPLE = Scores(
    memory=0.9,
    guardrails=1.0,
    quality=1.0,
    global_=0.95,
    block_rate=1.0,
    false_positive_rate=0.0,
    latency_ms=12.3,
    cost=0.0,
)


def test_report_contains_signals(tmp_path):
    path = tmp_path / "report.md"
    write_report(SAMPLE, path)
    text = path.read_text(encoding="utf-8").lower()
    for signal in ["memoire", "blocage", "faux positif", "latence", "cout"]:
        assert signal in text


def test_report_appends_one_row_per_call(tmp_path):
    path = tmp_path / "report.md"
    write_report(SAMPLE, path)
    write_report(SAMPLE, path)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("|")]
    # header label row + separator row + 2 data rows
    assert len(lines) == 4
