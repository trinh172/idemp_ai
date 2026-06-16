"""
Executor — gọi HTTP API (async) và thu thập kết quả từng lần call.
"""
import asyncio
import time

import httpx

from idempotency_agent.config import settings
from idempotency_agent.generator import build_request
from idempotency_agent.models import APICallResult, RequestTemplate, TestCase


async def _single_call(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    body: dict | None,
    idempotency_key: str | None = None,
) -> APICallResult:
    """Thực hiện 1 lần gọi API, trả về kết quả (không raise)."""
    try:
        start = time.monotonic()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=body,
            timeout=settings.request_timeout_seconds,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        try:
            body_json = response.json()
        except Exception:
            body_json = response.text

        return APICallResult(
            status_code=response.status_code,
            body=body_json,
            response_time_ms=round(elapsed_ms, 2),
            request_body=body,
            request_idempotency_key=idempotency_key,
        )
    except Exception as exc:
        return APICallResult(
            status_code=-1,
            body=None,
            response_time_ms=0,
            error=str(exc),
            request_body=body,
            request_idempotency_key=idempotency_key,
        )


async def execute_test_case(
    test_case: TestCase,
    request_template: RequestTemplate,
) -> list[APICallResult]:
    """Chạy một test case, trả về list kết quả từng lần call."""
    url, headers, body = build_request(
        request_template,
        use_different_key=test_case.use_different_key,
    )

    # Xác định idempotency key value thực tế đã gắn vào request
    key_name = request_template.idempotency_key_name
    if request_template.idempotency_key_location == "header":
        idem_key = headers.get(key_name)
    else:
        idem_key = (body or {}).get(key_name) if isinstance(body, dict) else None

    async with httpx.AsyncClient() as client:
        if test_case.concurrent:
            tasks = [
                _single_call(client, request_template.method, url, headers, body, idem_key)
                for _ in range(test_case.repeat_count)
            ]
            return list(await asyncio.gather(*tasks))

        results = []
        for _ in range(test_case.repeat_count):
            results.append(
                await _single_call(client, request_template.method, url, headers, body, idem_key)
            )
        return results


def run_test_case(
    test_case: TestCase,
    request_template: RequestTemplate,
) -> list[APICallResult]:
    """Sync wrapper cho execute_test_case."""
    return asyncio.run(execute_test_case(test_case, request_template))
