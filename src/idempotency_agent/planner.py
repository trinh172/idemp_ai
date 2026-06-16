"""
Planner — AI agent đọc curl info + mô tả idempotency từ user,
tự động sinh ra cấu hình test (key location/name/gen, expected status, ignore fields).

Theo SKILL.md: gọi API ngoài → KHÔNG đặt trong validator/generator.
"""
import json
import re
from dataclasses import dataclass, field

from idempotency_agent.config import settings
from idempotency_agent.models import AITestCase


def _extract_json(text: str) -> str:
    """Extract JSON từ text — hỗ trợ model không dùng response_format."""
    text = text.strip()
    # Thử parse trực tiếp
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    # Tìm ```json ... ``` block
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        return m.group(1).strip()
    # Tìm JSON object/array đầu tiên
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if m:
        return m.group(1)
    return text

_SYSTEM_PROMPT = """\
Bạn là chuyên gia SDET phân tích HTTP API để cấu hình test idempotency.

Bạn nhận:
1. Thông tin curl đã parse: method, url, headers (có thể chứa auth), body
2. Mô tả từ user về cách xác định idempotency key và cách generate data

Nhiệm vụ: xác định chính xác cấu hình test idempotency.

Trả về JSON (chỉ JSON, KHÔNG có text khác):
{
  "key_location": "header" | "body",
  "key_name": "<tên field idempotency key>",
  "key_gen": "uuid4" | "timestamp" | "fixed",
  "key_value": "<giá trị mẫu hợp lệ — UUID nếu uuid4, timestamp nếu timestamp, giá trị user cung cấp nếu fixed>",
  "expected_status": <int — HTTP status mong đợi khi success>,
  "ignore_fields": ["<field trong response cần bỏ qua khi so sánh, vd: id, created_at, updated_at, timestamp>"],
  "response_data_path": "<tên field chứa dữ liệu thực trong response, vd 'data'. Null nếu response không có wrapper>",
  "notes": "<1-2 câu giải thích lý do chọn cấu hình này>"
}

Quy tắc suy luận:
- Nếu mô tả user hoặc headers có tên key rõ ràng (Idempotency-Key, X-Idempotency-Key, ...) → key_location = header
- Nếu mô tả đề cập field trong body (vd: "field request_id trong body") → key_location = body
- Nếu mô tả nói "UUID" hoặc không nói gì → key_gen = uuid4
- Nếu mô tả cung cấp giá trị cụ thể (vd: "key là order-001") → key_gen = fixed, key_value = giá trị đó
- expected_status: POST tạo mới → 201; GET/PUT/PATCH thường → 200; xem thêm path URL để đoán
- ignore_fields: luôn bỏ id, created_at, updated_at, timestamp nếu không có thông tin rõ ràng hơn
- Nếu Authorization header có Bearer token → ghi chú nhưng KHÔNG đưa token vào output (đã được xử lý riêng)
- response_data_path: nếu API có pattern wrapper kiểu {returnCode, data: {...}} thì điền "data". Nếu response trực tiếp là payload thì để null."""


@dataclass
class TestPlan:
    key_location: str
    key_name: str
    key_gen: str          # "uuid4" | "timestamp" | "fixed"
    key_value: str        # giá trị mẫu để dùng làm idempotency key
    expected_status: int
    ignore_fields: list[str] = field(default_factory=list)
    response_data_path: str | None = None  # vd "data" nếu API wrap trong {data: ...}
    notes: str = ""


_DESIGN_SYSTEM_PROMPT = """\
Bạn là SDET chuyên thiết kế test case idempotency. Phân tích requirements và thiết kế test cases.

## QUAN TRỌNG — Quy tắc ưu tiên (PHẢI tuân thủ)

**Rule #1: Nếu user đề cập TƯỜNG MINH một scenario (dùng từ "đảm bảo", "ít nhất", "check", "verify", "gọi X lần", v.v.) thì PHẢI tạo test case đó, KHÔNG ĐƯỢC bỏ qua.**

Mapping từ ngôn ngữ tự nhiên:
- "gọi 1 lần", "tạo thành công", "single call" → #1 (repeat_count=1 rồi verify success)
- "gọi 2 lần cùng key", "retry cùng key", "duplicate" → #1 với repeat_count=2
- "cùng key khác payload", "same key different body/payload" → #5, use_different_payload=true
- "concurrent N lần", "song song N lần", "N concurrent" → #4, concurrent=true, repeat_count=N (lấy đúng số N user nói)
- "key khác", "different key", "2 key riêng" → #6, use_different_key=true
- "không có key", "missing key", "thiếu key" → #9, omit_key=true

**Rule #2: Số lần gọi tường minh phải được giữ nguyên.**
- "concurrent 10 lần" → repeat_count=10 (không tự đổi thành 3 hay 5)
- "gọi 5 lần" → repeat_count=5

**Rule #3: Sau khi tạo đủ cases user yêu cầu, BẮT BUỘC bổ sung thêm cases từ baseline để tăng coverage.**
- Bước 1: Tạo TẤT CẢ cases user liệt kê tường minh
- Bước 2: Xem còn case nào trong baseline phù hợp với loại API mà chưa được cover → thêm vào
- Bước 3: Ưu tiên bổ sung: different_key_same_payload (#6), missing_key (#9), reuse_key_after_failure (#8)
- Tổng: tối thiểu max(user_cases, 4), tối đa 8 test cases. KHÔNG được dừng ở đúng số user liệt kê.

## Bộ baseline chuẩn (9 test cases)

1. successful_retry_same_key — Gọi thành công → retry cùng key → chỉ 1 transaction, response identical
   → should_responses_be_identical=true, repeat_count=2

2. retry_after_network_timeout — Gọi → timeout → retry cùng key → xử lý đúng 1 lần, không duplicate
   → should_responses_be_identical=true, should_db_not_duplicate=true, repeat_count=2
   → Ghi note: "requires simulated timeout — manual verification needed for timeout step"

3. key_not_stored_on_timeout — Key chưa lưu ở lần 1 (timeout), retry tạo transaction mới
   → should_responses_be_identical=false, repeat_count=1
   → Ghi note: "requires manual timing/delay between calls"

4. concurrent_same_key — Nhiều request song song cùng key → đúng 1 transaction, không deadlock
   → concurrent=true, should_responses_be_identical=true, should_db_not_duplicate=true, repeat_count=3+

5. same_key_different_payload — Cùng key, body khác → API reject 400/409 hoặc trả response từ lần đầu
   → use_different_payload=true, should_responses_be_identical=false, repeat_count=1
   → use_different_payload=true: hệ thống tự động gọi 2 request: call 1 body gốc, call 2 body biến đổi, cùng key

6. different_key_same_payload — Key A và key B, cùng payload → 2 transaction riêng biệt
   → use_different_key=true, should_responses_be_identical=false, repeat_count=1

7. key_expiry — Gọi → đợi key hết hạn → retry → system coi là request mới
   → should_responses_be_identical=false, repeat_count=1
   → Ghi note: "requires waiting for key TTL — manual verification needed"

8. reuse_key_after_failure — Gọi data invalid → fail → retry cùng key → cùng failure response
   → should_responses_be_identical=true, repeat_count=2
   → Ghi note: "use invalid data for first call to trigger failure"

9. missing_idempotency_key — Không gửi key → API reject 400
   → omit_key=true, should_responses_be_identical=false, repeat_count=1
   → omit_key=true sẽ loại bỏ hoàn toàn idempotency key khỏi request

## Lựa chọn test case theo loại API (CHỈ dùng khi user KHÔNG liệt kê scenario cụ thể)

- API đơn giản: #1, #6, #9
- API tạo resource (POST order/payment): #1, #4, #6, #8, #9
- API payment có retry: #1, #2, #4, #6, #8, #9
- Full coverage (user yêu cầu "comprehensive"): tất cả 9 cases

## Output format — PHẢI dùng ĐÚNG tên field, wrap trong "test_cases":

{
  "test_cases": [
    {
      "name": "successful_retry_same_key",
      "description": "Gọi thành công rồi retry cùng idempotency key — chỉ 1 transaction được tạo",
      "repeat_count": 2,
      "concurrent": false,
      "use_different_key": false,
      "should_responses_be_identical": true,
      "should_db_not_duplicate": false,
      "key_value": null,
      "alt_key_value": null,
      "omit_key": false,
      "use_different_payload": false,
      "expected_behavior": "Cả 2 response phải giống nhau, API trả cùng kết quả"
    }
  ]
}

Về key_value và alt_key_value:
- key_value: nếu API dùng ID dạng số hoặc format đặc biệt (không phải UUID), đặt giá trị cụ thể phù hợp. Ví dụ: "251001000000101". Để null nếu UUID là OK.
- alt_key_value: dùng cho use_different_key=true — đặt giá trị key thứ 2 khác key_value. Ví dụ: "251001000000102". Để null để hệ thống tự tạo UUID.
- Nhìn vào body/headers của curl để đoán format đúng của key (số, string, UUID, v.v.)

Quy tắc:
- "name" phải là snake_case, KHÔNG dùng tiếng Việt có dấu
- should_db_not_duplicate=true CHỈ khi user đề cập DB hoặc có DB config
- Tối thiểu 3, tối đa 8 test cases
- Case #3, #5, #7 không auto-execute được → vẫn thêm vào nhưng ghi rõ trong expected_behavior"""



class PlannerError(RuntimeError):
    """Lỗi khi gọi AI planner."""


def plan_from_curl(
    parsed_curl: dict,
    description: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> TestPlan:
    """
    Gọi AI phân tích curl + mô tả → TestPlan.
    Raise PlannerError nếu thiếu key hoặc AI lỗi.
    """
    key = api_key if api_key is not None else settings.ai_api_key
    if not key:
        raise PlannerError("Thiếu AI_API_KEY để chạy AI planner.")

    try:
        from openai import APIError, OpenAI
    except ImportError as exc:  # pragma: no cover
        raise PlannerError("Chưa cài 'openai' SDK.") from exc

    client = OpenAI(api_key=key, base_url=base_url or settings.ai_base_url)

    # Ẩn giá trị auth token trước khi gửi cho AI (không cần phân tích)
    safe_headers = {
        k: (v[:8] + "...") if k.lower() == "authorization" else v
        for k, v in parsed_curl.get("headers", {}).items()
    }
    safe_curl = {**parsed_curl, "headers": safe_headers}

    user_content = (
        f"Curl info đã parse:\n{json.dumps(safe_curl, ensure_ascii=False, indent=2)}\n\n"
        f"Mô tả idempotency từ user:\n{description.strip() or '(user không cung cấp mô tả)'}\n\n"
        "Hãy phân tích và trả về JSON cấu hình test."
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
        raise PlannerError(f"AI API error: {exc}") from exc

    text = response.choices[0].message.content
    if not text:
        raise PlannerError("AI không trả về nội dung.")

    data = json.loads(_extract_json(text))
    return TestPlan(
        key_location=data.get("key_location", "header"),
        key_name=data.get("key_name", "Idempotency-Key"),
        key_gen=data.get("key_gen", "uuid4"),
        key_value=data.get("key_value", ""),
        expected_status=int(data.get("expected_status", 200)),
        ignore_fields=data.get("ignore_fields", []),
        response_data_path=data.get("response_data_path") or None,
        notes=data.get("notes", ""),
    )


def design_test_cases(
    parsed_curl: dict,
    plan: "TestPlan",
    description: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> list[AITestCase]:
    """
    Gọi AI phân tích requirements và thiết kế test cases.
    Raise PlannerError nếu thiếu key hoặc AI lỗi.
    """
    key = api_key if api_key is not None else settings.ai_api_key
    if not key:
        raise PlannerError("Thiếu AI_API_KEY để thiết kế test cases.")

    try:
        from openai import APIError, OpenAI
    except ImportError as exc:  # pragma: no cover
        raise PlannerError("Chưa cài 'openai' SDK.") from exc

    client = OpenAI(api_key=key, base_url=base_url or settings.ai_base_url)

    safe_headers = {
        k: (v[:8] + "...") if k.lower() == "authorization" else v
        for k, v in parsed_curl.get("headers", {}).items()
    }

    context = {
        "api": {**parsed_curl, "headers": safe_headers},
        "idempotency_config": {
            "key_location": plan.key_location,
            "key_name": plan.key_name,
            "expected_status": plan.expected_status,
        },
        "user_description": description.strip() or "(user không cung cấp mô tả)",
    }

    user_content = (
        f"Context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Hãy phân tích requirements và thiết kế bộ test case idempotency phù hợp."
    )

    try:
        response = client.chat.completions.create(
            model=model or settings.ai_model,
            messages=[
                {"role": "system", "content": _DESIGN_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    except APIError as exc:
        raise PlannerError(f"AI API error: {exc}") from exc

    text = response.choices[0].message.content
    if not text:
        raise PlannerError("AI không trả về nội dung.")

    raw = json.loads(_extract_json(text))
    # Tìm list trong response: thử các key phổ biến rồi fallback tìm value đầu tiên là list
    if isinstance(raw, list):
        items = raw
    else:
        items = (
            raw.get("test_cases")
            or raw.get("cases")
            or raw.get("tests")
            or raw.get("scenarios")
            or next((v for v in raw.values() if isinstance(v, list)), [])
        )

    if not items:
        raise PlannerError(
            f"AI không sinh được test case. Raw response: {text[:300]}"
        )

    return [
        AITestCase(
            name=tc.get("name", f"case_{i}"),
            description=tc.get("description", ""),
            repeat_count=int(tc.get("repeat_count", 1)),
            concurrent=bool(tc.get("concurrent", False)),
            use_different_key=bool(tc.get("use_different_key", False)),
            should_responses_be_identical=bool(tc.get("should_responses_be_identical", False)),
            should_db_not_duplicate=bool(tc.get("should_db_not_duplicate", False)),
            expected_behavior=tc.get("expected_behavior", ""),
            key_value=tc.get("key_value") or None,
            alt_key_value=tc.get("alt_key_value") or None,
            omit_key=bool(tc.get("omit_key", False)),
            use_different_payload=bool(tc.get("use_different_payload", False)),
        )
        for i, tc in enumerate(items)
    ]
