import pytest

from idempotency_agent.analyzer import (
    Analysis,
    AnalyzerError,
    _results_to_payload,
    analyze_results,
)
from idempotency_agent.models import ScenarioType, TestResult, TestStatus

pytestmark = pytest.mark.unit


def _result(status=TestStatus.PASS):
    return TestResult(
        scenario=ScenarioType.DUPLICATE_CALL,
        description="dup",
        status=status,
        failure_reason="boom" if status != TestStatus.PASS else None,
    )


def test_payload_is_compact_and_serializable():
    import json

    payload = _results_to_payload([_result(TestStatus.FAIL)])
    json.dumps(payload)  # phải serialize được
    assert payload["results"][0]["status"] == "FAIL"
    assert payload["results"][0]["failure_reason"] == "boom"


def test_missing_api_key_raises():
    with pytest.raises(AnalyzerError, match="AI_API_KEY"):
        analyze_results([_result()], "http://x/y", api_key="")


def test_analyze_parses_model_output(monkeypatch):
    """Mock OpenAI client để test parsing không cần gọi mạng."""
    import sys
    import types

    captured = {}

    _json_text = (
        '{"verdict":"NOT_IDEMPOTENT","confidence":"high",'
        '"summary":"Hai response khác nhau.","likely_causes":["Server bỏ qua key"],'
        '"recommendations":["Lưu key vào DB"]}'
    )

    class _Message:
        content = _json_text

    class _Choice:
        message = _Message()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, api_key=None, base_url=None):
            self.chat = _Chat()

    fake = types.ModuleType("openai")
    fake.OpenAI = _Client
    fake.APIError = Exception
    monkeypatch.setitem(sys.modules, "openai", fake)

    out = analyze_results([_result(TestStatus.FAIL)], "http://x/orders", api_key="sk-test")

    assert isinstance(out, Analysis)
    assert out.verdict == "NOT_IDEMPOTENT"
    assert out.recommendations == ["Lưu key vào DB"]
    # đảm bảo dùng json_object format
    assert captured["response_format"] == {"type": "json_object"}
