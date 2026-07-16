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
