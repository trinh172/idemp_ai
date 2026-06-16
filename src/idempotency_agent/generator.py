"""
Generator — sinh test cases idempotency từ request template.
"""
import json
import uuid

from idempotency_agent.models import RequestTemplate, ScenarioType, TestCase


def generate_test_cases(
    n_calls: int = 3,
    concurrent_workers: int = 5,
) -> list[TestCase]:
    """Sinh đầy đủ bộ test case idempotency chuẩn."""
    return [
        TestCase(
            scenario=ScenarioType.SINGLE_CALL,
            description="Gọi API 1 lần — baseline response",
            repeat_count=1,
        ),
        TestCase(
            scenario=ScenarioType.DUPLICATE_CALL,
            description="Gọi 2 lần cùng idempotent key — response phải identical",
            repeat_count=2,
        ),
        TestCase(
            scenario=ScenarioType.N_CALLS,
            description=f"Gọi {n_calls} lần cùng idempotent key — response luôn giống lần đầu",
            repeat_count=n_calls,
        ),
        TestCase(
            scenario=ScenarioType.CONCURRENT_CALLS,
            description=f"Gọi song song {concurrent_workers} request cùng lúc — không tạo duplicate",
            repeat_count=concurrent_workers,
            concurrent=True,
        ),
        TestCase(
            scenario=ScenarioType.DIFFERENT_KEY,
            description="Gọi với idempotent key khác — phải tạo operation mới",
            repeat_count=1,
            use_different_key=True,
        ),
    ]


def _coerce_key(val):
    """Parse key value nếu là JSON-encoded string (vd '["abc"]' → ['abc'])."""
    if isinstance(val, str) and val.startswith(("[", "{")):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return val


def build_request(
    template: RequestTemplate,
    use_different_key: bool = False,
) -> tuple[str, dict, dict | None]:
    """Build (url, headers, body) từ template, gắn idempotent key vào đúng vị trí."""
    headers = dict(template.headers)
    body = dict(template.body) if template.body else None

    key_value = str(uuid.uuid4()) if use_different_key else _coerce_key(template.idempotency_key_value)

    if template.idempotency_key_location == "__omit__":
        # missing_key test case — xóa key khỏi cả header lẫn body nếu có
        headers.pop(template.idempotency_key_name, None)
        if body is not None:
            body.pop(template.idempotency_key_name, None)
    elif template.idempotency_key_location == "header":
        headers[template.idempotency_key_name] = key_value
    elif template.idempotency_key_location == "body" and body is not None:
        original_val = body.get(template.idempotency_key_name)
        if isinstance(original_val, list):
            # Field gốc là array → gán đúng array
            # key_value đã là list → dùng trực tiếp
            # key_value là scalar → wrap thành [scalar]
            if isinstance(key_value, list):
                body[template.idempotency_key_name] = key_value
            else:
                body[template.idempotency_key_name] = [key_value]
        else:
            # Field gốc là scalar (string/int/...) → gán scalar
            # key_value là list (AI trả nhầm) → lấy phần tử đầu
            if isinstance(key_value, list):
                body[template.idempotency_key_name] = key_value[0] if key_value else ""
            else:
                body[template.idempotency_key_name] = key_value

    return template.url, headers, body
