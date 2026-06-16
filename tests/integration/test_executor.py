"""
Integration test cho executor — dùng respx để mock HTTP, không cần server thật.
"""
import httpx
import pytest
import respx

from idempotency_agent.executor import execute_test_case
from idempotency_agent.models import ScenarioType, TestCase

pytestmark = pytest.mark.integration


@respx.mock
async def test_duplicate_calls_hit_endpoint_twice(request_template):
    route = respx.post("http://testserver/api/orders").mock(
        return_value=httpx.Response(201, json={"id": 1, "status": "ok"})
    )
    tc = TestCase(scenario=ScenarioType.DUPLICATE_CALL, description="dup", repeat_count=2)

    results = await execute_test_case(tc, request_template)

    assert route.call_count == 2
    assert all(r.status_code == 201 for r in results)


@respx.mock
async def test_concurrent_calls_all_complete(request_template):
    respx.post("http://testserver/api/orders").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    tc = TestCase(
        scenario=ScenarioType.CONCURRENT_CALLS, description="conc",
        repeat_count=5, concurrent=True,
    )

    results = await execute_test_case(tc, request_template)

    assert len(results) == 5
    assert all(r.error is None for r in results)


@respx.mock
async def test_network_error_captured(request_template):
    respx.post("http://testserver/api/orders").mock(
        side_effect=httpx.ConnectError("refused")
    )
    tc = TestCase(scenario=ScenarioType.SINGLE_CALL, description="err", repeat_count=1)

    results = await execute_test_case(tc, request_template)

    assert results[0].is_error
    assert results[0].status_code == -1
