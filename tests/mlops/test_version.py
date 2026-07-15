from velmo.mlops.version import current_version


def test_current_version_is_a_nonempty_string():
    value = current_version()
    assert isinstance(value, str)
    assert value != ""
