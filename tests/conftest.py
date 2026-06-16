"""
Shared pytest fixtures.
"""
import pytest

from idempotency_agent.models import (
    APICallResult,
    DBSnapshot,
    RequestTemplate,
    ResponseTemplate,
)


@pytest.fixture
def request_template() -> RequestTemplate:
    return RequestTemplate(
        method="POST",
        url="http://testserver/api/orders",
        headers={"Content-Type": "application/json"},
        body={"product_id": "abc", "qty": 1},
        idempotency_key_location="header",
        idempotency_key_name="Idempotency-Key",
        idempotency_key_value="key-001",
    )


@pytest.fixture
def response_template() -> ResponseTemplate:
    return ResponseTemplate(expected_status_code=201, ignore_fields=["created_at"])


def make_call(status=201, body=None, error=None) -> APICallResult:
    return APICallResult(
        status_code=status,
        body=body if body is not None else {"id": 1, "status": "ok"},
        response_time_ms=12.3,
        error=error,
    )


@pytest.fixture
def empty_snapshot() -> DBSnapshot:
    return DBSnapshot()
