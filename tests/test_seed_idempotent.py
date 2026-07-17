from sqlalchemy import select

from velmo.db import Customer, fresh_sqlite_session
from velmo.sampledata import seed_if_empty


def test_seed_if_empty_is_idempotent():
    session = fresh_sqlite_session()
    assert seed_if_empty(session) is True  # first run seeds
    count = len(session.scalars(select(Customer)).all())
    assert count > 0
    assert seed_if_empty(session) is False  # second run skips
    assert len(session.scalars(select(Customer)).all()) == count  # no duplicates
