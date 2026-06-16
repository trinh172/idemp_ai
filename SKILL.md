---
name: idempotency-agent
description: Quy tắc & kiến trúc bắt buộc khi làm việc trên Idempotency Test Agent. AI agent PHẢI đọc và tuân theo file này trước khi chỉnh sửa bất kỳ code nào trong repo.
---

# SKILL — Idempotency Test Agent (SDET)

> AI agent: đây là **rule file** của project. Đọc trước khi code. Mọi thay đổi phải tuân theo các nguyên tắc dưới đây. Khi có mâu thuẫn giữa yêu cầu nhanh và rule này, **ưu tiên rule** và nêu rõ cho user.

## 1. Mục tiêu project

Verify tính **idempotency** của HTTP API: gọi cùng một request (cùng idempotency key) nhiều lần / song song thì **response phải identical** và **DB không được tạo bản ghi trùng**.

## 2. Kiến trúc (layered — KHÔNG được phá vỡ)

```
cli.py        →  parse CLI, build models, gọi runner. KHÔNG chứa business logic.
web.py        →  FastAPI: map JSON → models → runner → serialize. Wiring layer như cli, KHÔNG logic.
serve.py      →  khởi động uvicorn cho web.py.
runner.py     →  orchestration: generate → execute → snapshot → evaluate. Trả về list[TestResult].
generator.py  →  sinh TestCase + build request (gắn idempotency key).
executor.py   →  gọi HTTP (async httpx). KHÔNG validate, KHÔNG raise — lỗi → APICallResult.error.
db.py         →  snapshot Mongo/MySQL. KHÔNG raise ra ngoài — lỗi snapshot chỉ log [WARN].
validator.py  →  pure logic so sánh response + DB delta → TestResult. KHÔNG I/O, KHÔNG network.
reporter.py   →  render HTML (Jinja2 từ templates/) + print summary.
analyzer.py   →  gọi Claude (Anthropic SDK) diễn giải kết quả → Analysis. Gọi API ngoài, KHÔNG đặt trong validator.
models.py     →  dataclass thuần, KHÔNG logic (trừ @property thuần tính toán).
config.py     →  Settings dataclass đọc từ env. Mọi tunable đi qua đây.
```

**Quy tắc dependency:** luồng phụ thuộc chỉ đi một chiều
`{cli, web} → runner → {generator, executor, db, validator, reporter} → models/config`.
KHÔNG để layer thấp import layer cao (vd: validator không được import executor).

## 3. Nguyên tắc bắt buộc

1. **Validator phải pure** — không network, không DB, không đọc file, không thời gian thực. Nhận input → trả output. Đây là điều kiện để unit test nhanh & ổn định.
2. **Executor không bao giờ raise** — mọi exception bọc vào `APICallResult(status_code=-1, error=...)`.
3. **DB snapshot không bao giờ làm crash test run** — bọc try/except, fail thì trả `None` + log `[WARN]`.
4. **SQL/identifier phải an toàn** — tên bảng/cột đi qua `_safe_identifier()`. KHÔNG f-string nối thẳng input user vào SQL. Where-clause là dual-use; nếu mở rộng, ưu tiên parametrized query.
5. **Không hardcode config** — đọc từ `config.settings`. Không rải `os.getenv` khắp nơi.
8. **AI analyzer là phụ trợ, không phải nguồn chân lý** — verdict PASS/FAIL luôn do `validator` (luật cứng) quyết định. `analyzer.py` chỉ diễn giải; nếu thiếu key/API lỗi → raise `AnalyzerError`, caller phải degrade gracefully (không làm hỏng test run). Model mặc định `claude-opus-4-8`, dùng structured output + adaptive thinking.
6. **HTML template tách khỏi code** — nằm trong `templates/*.j2`, render qua Jinja2 với `autoescape=True`. Không nhúng HTML string vào .py.
7. **Tiếng Việt cho docstring/comment** giữ nhất quán với codebase hiện tại; tên biến/hàm tiếng Anh.

## 4. Định nghĩa PASS/FAIL (không tự đổi nếu không có yêu cầu)

| Scenario          | Điều kiện PASS                                                        |
|-------------------|----------------------------------------------------------------------|
| `single_call`     | status == expected                                                   |
| `duplicate_call`  | status đúng **và** 2 response identical (sau khi bỏ `ignore_fields`) **và** DB delta ≤ 1 |
| `n_calls`         | như trên với N lần                                                   |
| `concurrent_calls`| như trên, gọi song song                                              |
| `different_key`   | status đúng (key khác → được phép tạo operation mới)                 |

- `ERROR` (không phải FAIL) khi có lỗi network/timeout → short-circuit trong `evaluate`.
- `IDEMPOTENT_SCENARIOS` (models.py) là nguồn chân lý cho "scenario nào enforce identical + no-duplicate". Sửa rule thì sửa ở đó, đừng lặp lại điều kiện rải rác.

## 5. Testing (SDET discipline)

- Mọi thay đổi logic trong `validator.py`, `generator.py`, `db.py` PHẢI kèm/đi qua unit test (`tests/unit/`, marker `@pytest.mark.unit`).
- Thay đổi `executor.py` → integration test với `respx` mock HTTP (`tests/integration/`), KHÔNG gọi server thật.
- Chạy: `pytest` (hoặc `pytest -m unit` cho vòng nhanh). Phải xanh trước khi coi là xong.
- Lint: `ruff check src tests`.
- Không commit nếu test đỏ. Không xoá/disable test để cho qua — sửa code.

## 6. Bộ test case chuẩn idempotency (baseline)

AI agent PHẢI tham khảo danh sách này khi thiết kế test case. Không cần implement tất cả — chọn những case phù hợp với API đang test. Đây là nguồn chân lý về "cần test gì".

| # | Tên | Mô tả | Điều kiện PASS | Flag cần thiết |
|---|-----|--------|----------------|----------------|
| 1 | `successful_retry_same_key` | Gọi thành công → retry cùng key | Chỉ 1 transaction; response body & key identical | `should_responses_be_identical=true` |
| 2 | `retry_after_network_timeout` | Gọi → timeout → retry cùng key | Payment xử lý đúng 1 lần; retry trả kết quả gốc; không duplicate debit/credit | `should_responses_be_identical=true`, `should_db_not_duplicate=true` |
| 3 | `key_not_stored_on_timeout` | Gọi → timeout → retry; key chưa được lưu ở lần 1 | Key được lưu sau timeout; lần retry tạo transaction mới (key chưa tồn tại) | `should_responses_be_identical=false` |
| 4 | `concurrent_same_key` | Nhiều request song song cùng key | Đúng 1 transaction trong DB; tất cả response identical; không deadlock | `concurrent=true`, `should_responses_be_identical=true`, `should_db_not_duplicate=true` |
| 5 | `same_key_different_payload` | Cùng key, body khác | API reject 400/409; message báo payload mismatch; không tạo transaction mới | `should_responses_be_identical=false` (expect error status) |
| 6 | `different_key_same_payload` | Key A và key B, cùng payload | 2 transaction riêng biệt, mỗi cái có unique transaction ID | `use_different_key=true`, `should_responses_be_identical=false` |
| 7 | `key_expiry` | Gọi → đợi key hết hạn → retry cùng key | System coi là request mới; tạo transaction mới | `should_responses_be_identical=false` (sau khi delay) |
| 8 | `reuse_key_after_failure` | Gọi với data invalid → fail → retry cùng key | Cùng failure response; không tạo transaction; error code nhất quán | `should_responses_be_identical=true` (error response phải identical) |
| 9 | `missing_idempotency_key` | Không gửi key | API reject 400 Bad Request; message báo thiếu key | status 400 expected |

### Quy tắc ưu tiên khi thiết kế test case (QUAN TRỌNG)

**Rule #1 — User nói "đảm bảo", "ít nhất", "check", "verify" + scenario cụ thể → PHẢI thêm case đó, KHÔNG bỏ qua.**

Mapping từ ngôn ngữ tự nhiên sang baseline:
| User nói | → Baseline case |
|----------|----------------|
| "gọi 1 lần", "single call", "tạo ticket thành công" | → #1 `successful_retry_same_key` (repeat_count=1 first, then +1) hoặc thêm case riêng |
| "gọi 2 lần cùng key", "retry cùng key", "duplicate request" | → #1 với repeat_count=2 |
| "cùng key khác payload", "same key different body/payload" | → #5, use_different_payload=true |
| "concurrent", "song song", "đồng thời", "N lần song song" | → #4, concurrent=true, repeat_count=N |
| "key khác", "different key" | → #6, use_different_key=true |
| "không có key", "missing key", "thiếu key" | → #9, omit_key=true |
| "timeout", "retry sau lỗi" | → #2 |
| "key hết hạn", "key expiry" | → #7 |
| "gọi với data sai", "invalid data" | → #8 |

**Rule #2 — Số lần gọi tường minh phải được tôn trọng.**
- User nói "concurrent 10 lần" → `concurrent=true, repeat_count=10`
- User nói "gọi 5 lần cùng key" → `repeat_count=5`

**Rule #3 — Thứ tự ưu tiên:**
1. Scenario user liệt kê tường minh → PHẢI có, đúng thứ tự
2. Scenario suy luận từ loại API → thêm vào nếu chưa đủ coverage
3. Không trùng lặp (nếu user đã nói "2 lần cùng key" thì không thêm thêm case tương tự)

### Hướng dẫn ánh xạ sang AITestCase theo loại API

```
Khi user mô tả "payment API", "transaction", "order":
  → Ưu tiên: #1, #4, #6, #8, #9
  → Thêm nếu có DB config: #2, #4 với should_db_not_duplicate=true
  → Nếu user đề cập timeout/retry: thêm #2, #3
  → Nếu user đề cập key expiry: thêm #7
```

### Flags theo baseline case

```
Case #5 (same key, different payload):
  → use_different_payload=true — hệ thống tự gọi 2 request: call 1 body gốc, call 2 body biến đổi, cùng key

Case #3, #7 cần delay giữa các bước → chưa support tự động
  → Ghi trong expected_behavior, repeat_count=1, đánh dấu "requires manual timing"
```

### Số lượng test case theo độ phức tạp

- API đơn giản (GET/idempotent by design): tối thiểu #1, #6, #9 (3 cases)
- API tạo resource (POST payment/order): #1, #4, #6, #8, #9 (5 cases)
- API payment có retry requirement: #1, #2, #4, #6, #8, #9 (6 cases)
- Full coverage: tất cả 9 cases (dùng khi user yêu cầu "comprehensive" hoặc "full")

## 6. Khi thêm scenario mới

1. Thêm vào `ScenarioType` (models.py).
2. Nếu là idempotent-type → thêm vào `IDEMPOTENT_SCENARIOS`.
3. Thêm `TestCase` trong `generate_test_cases`.
4. Thêm điều kiện validate trong `validator.evaluate` nếu cần.
5. Thêm unit test tương ứng.

## 7. Cấm

- ❌ Đưa business logic vào `cli.py` hoặc `models.py`.
- ❌ Network/DB call bên trong `validator.py`.
- ❌ Nối chuỗi input user vào SQL.
- ❌ Hardcode secret/URL trong source — dùng env / CLI options.
- ❌ In/format report bên trong `runner.run_suite` (nó chỉ trả data; output do caller quyết định).
