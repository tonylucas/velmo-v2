from velmo.kb_store import parse_chroma_url


def test_explicit_url():
    assert parse_chroma_url("http://localhost:8001") == ("localhost", 8001)


def test_internal_fqdn():
    assert parse_chroma_url("http://velmo2-tony-chroma.internal.foo.io:8000") == (
        "velmo2-tony-chroma.internal.foo.io",
        8000,
    )


def test_default_port_when_missing():
    assert parse_chroma_url("http://host") == ("host", 8000)


def test_reads_env_when_no_arg(monkeypatch):
    monkeypatch.setenv("CHROMA_URL", "http://envhost:9000")
    assert parse_chroma_url() == ("envhost", 9000)


def test_missing_env_raises_a_readable_error(monkeypatch):
    # The two backends guard on CHROMA_URL before calling this and fall back to
    # their offline variant, so the only unguarded caller is scripts/seed_kb.py —
    # which genuinely needs a Chroma service. It used to die on a bare KeyError.
    # Defaulting to localhost:8000 would be worse: .env.example uses 8001, so the
    # script would connect to the wrong port and fail with a confusing timeout.
    import pytest

    monkeypatch.delenv("CHROMA_URL", raising=False)

    with pytest.raises(RuntimeError, match="CHROMA_URL is not set"):
        parse_chroma_url()
