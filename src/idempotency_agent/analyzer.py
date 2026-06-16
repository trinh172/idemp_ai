"""
Analyzer — dùng LLM để đọc kết quả test (deterministic) và đưa ra nhận định
ở mức cao: API có thực sự idempotent không, nguyên nhân khả dĩ, và khuyến nghị.

Đây KHÔNG thay thế validator. Validator quyết định PASS/FAIL bằng luật cứng;
analyzer chỉ diễn giải kết quả đó thành insight cho con người.

Theo SKILL.md: layer này gọi API ngoài → KHÔNG đặt trong validator (validator phải pure).
Dùng OpenAI-compatible API (OpenRouter, MiniMax, v.v.) — cấu hình qua AI_API_KEY / AI_MODEL / AI_BASE_URL.
"""
import json
import re
from dataclasses import dataclass

from idempotency_agent.config import settings
from idempotency_agent.models import TestResult

_SYSTEM_PROMPT = """\
Bạn là chuyên gia SDET về kiểm thử idempotency của HTTP API.
Bạn nhận kết quả một bộ test idempotency đã chạy (đã có PASS/FAIL/ERROR theo luật cứng).
Nhiệm vụ: diễn giải kết quả, kết luận endpoint có idempotent không, chỉ ra nguyên nhân
khả dĩ và khuyến nghị khắc phục. Trả lời bằng tiếng Việt, ngắn gọn, kỹ thuật, chính xác.
Không bịa thông tin không có trong dữ liệu.

Trả về JSON với cấu trúc sau (KHÔNG thêm bất kỳ text nào ngoài JSON):
{
  "verdict": "IDEMPOTENT" | "NOT_IDEMPOTENT" | "INCONCLUSIVE",
  "confidence": "high" | "medium" | "low",
  "summary": "<2-3 câu tóm tắt>",
  "likely_causes": ["<nguyên nhân 1>", ...],
  "recommendations": ["<khuyến nghị 1, ưu tiên cao nhất>", ...]
}"""


@dataclass
class Analysis:
    verdict: str
    confidence: str
    summary: str
    likely_causes: list[str]
    recommendations: list[str]


class AnalyzerError(RuntimeError):
    """Lỗi khi gọi AI analyzer (thiếu API key, lỗi mạng, …)."""


def _results_to_payload(results: list[TestResult]) -> dict:
    """Rút gọn TestResult thành JSON nhẹ để đưa cho model (không gửi dữ liệu thừa)."""
    return {
        "results": [
            {
                "scenario": r.scenario,
                "status": r.status.value,
                "description": r.description,
                "failure_reason": r.failure_reason,
                "response_diff": r.response_diff,
                "status_codes": [c.status_code for c in r.api_results],
                "errors": [c.error for c in r.api_results if c.error],
                "db_before": vars(r.db_before) if r.db_before else None,
                "db_after": vars(r.db_after) if r.db_after else None,
            }
            for r in results
        ]
    }


def analyze_results(
    results: list[TestResult],
    endpoint: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Analysis:
    """
    Gọi LLM (OpenAI-compatible) phân tích kết quả test.
    Raise AnalyzerError nếu thiếu key hoặc API lỗi.
    """
    key = api_key if api_key is not None else settings.ai_api_key
    if not key:
        raise AnalyzerError(
            "Thiếu AI_API_KEY — set env hoặc truyền api_key để bật AI analysis."
        )

    try:
        from openai import APIError, OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AnalyzerError("Chưa cài 'openai' SDK. Chạy: pip install openai") from exc

    client = OpenAI(
        api_key=key,
        base_url=base_url or settings.ai_base_url,
    )
    payload = _results_to_payload(results)

    user_content = (
        f"Endpoint: {endpoint}\n\n"
        f"Kết quả test (JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Hãy phân tích và trả về JSON theo schema trong system prompt."
    )

    try:
        response = client.chat.completions.create(
            model=model or settings.ai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    except APIError as exc:
        raise AnalyzerError(f"AI API error: {exc}") from exc

    text = response.choices[0].message.content
    if not text:
        raise AnalyzerError("Model không trả về nội dung text.")

    # Extract JSON — hỗ trợ model không dùng response_format
    def _extract_json(t: str) -> str:
        t = t.strip()
        try:
            json.loads(t)
            return t
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", t)
        if m:
            return m.group(1).strip()
        m = re.search(r"(\{[\s\S]*\})", t)
        if m:
            return m.group(1)
        return t

    data = json.loads(_extract_json(text))
    return Analysis(
        verdict=data["verdict"],
        confidence=data["confidence"],
        summary=data["summary"],
        likely_causes=data.get("likely_causes", []),
        recommendations=data.get("recommendations", []),
    )
