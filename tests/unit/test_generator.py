import pytest

from idempotency_agent.generator import build_request, generate_test_cases
from idempotency_agent.models import ScenarioType

pytestmark = pytest.mark.unit


def test_generate_covers_all_scenarios():
    cases = generate_test_cases(n_calls=4, concurrent_workers=8)
    scenarios = {c.scenario for c in cases}
    assert scenarios == set(ScenarioType)


def test_n_calls_and_concurrent_counts_respected():
    cases = {c.scenario: c for c in generate_test_cases(n_calls=4, concurrent_workers=8)}
    assert cases[ScenarioType.N_CALLS].repeat_count == 4
    assert cases[ScenarioType.CONCURRENT_CALLS].repeat_count == 8
    assert cases[ScenarioType.CONCURRENT_CALLS].concurrent is True


def test_build_request_puts_key_in_header(request_template):
    url, headers, body = build_request(request_template)
    assert url == request_template.url
    assert headers["Idempotency-Key"] == "key-001"
    assert "Idempotency-Key" not in (body or {})


def test_build_request_different_key_is_unique(request_template):
    _, h1, _ = build_request(request_template, use_different_key=True)
    _, h2, _ = build_request(request_template, use_different_key=True)
    assert h1["Idempotency-Key"] != h2["Idempotency-Key"] != "key-001"


def test_build_request_key_in_body():
    from idempotency_agent.models import RequestTemplate

    tpl = RequestTemplate(
        method="POST", url="http://x/y", body={"a": 1},
        idempotency_key_location="body", idempotency_key_name="idem", idempotency_key_value="v1",
    )
    _, _, body = build_request(tpl)
    assert body["idem"] == "v1"
