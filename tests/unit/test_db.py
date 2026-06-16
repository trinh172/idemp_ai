import pytest

from idempotency_agent.db import _safe_identifier, take_db_snapshot

pytestmark = pytest.mark.unit


def test_safe_identifier_allows_valid_names():
    assert _safe_identifier("orders") == "`orders`"
    assert _safe_identifier("order_items_2") == "`order_items_2`"


@pytest.mark.parametrize("bad", ["orders; DROP TABLE x", "a b", "1abc", "tbl`", "--"])
def test_safe_identifier_rejects_injection(bad):
    with pytest.raises(ValueError):
        _safe_identifier(bad)


def test_snapshot_none_config_returns_empty():
    snap = take_db_snapshot(None)
    assert snap.mongo_count is None and snap.mysql_count is None
