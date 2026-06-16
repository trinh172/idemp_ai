# Idempotency Test Agent

SDET tool tự động verify tính **idempotency** của HTTP API — gọi cùng request (cùng idempotency key) nhiều lần / song song và kiểm tra response identical + DB không tạo bản ghi trùng.

> 🤖 AI agent làm việc trên repo này: đọc [`SKILL.md`](SKILL.md) trước.

## Cấu trúc

```
src/idempotency_agent/      # package chính (src layout)
├── cli.py                  # CLI entry (Click)
├── runner.py               # orchestration
├── generator.py            # sinh test case + build request
├── executor.py             # gọi HTTP async (httpx)
├── db.py                   # snapshot Mongo/MySQL
├── validator.py            # so sánh response + DB delta (pure)
├── reporter.py             # render HTML report
├── models.py               # dataclasses
├── config.py               # Settings từ env
└── templates/report.html.j2
tests/
├── unit/                   # logic thuần (pytest -m unit)
└── integration/            # executor + respx mock HTTP
reports/                    # output HTML (gitignored)
```

## Cài đặt

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # hoặc: pip install -r requirements-dev.txt
cp .env.example .env
```

## Web UI

```bash
idempotency-web          # http://127.0.0.1:8000
# HOST=0.0.0.0 PORT=9000 RELOAD=1 idempotency-web
```

Form cho phép nhập **request template** (method/url/headers/body), **token** (nếu cần authorize) và **idempotency key** (vị trí/tên/giá trị), cùng tùy chọn nâng cao (expected status, n_calls, concurrent, Mongo/MySQL). Bấm *Chạy test* → kết quả từng scenario hiển thị ngay.
API: `POST /api/run` (JSON) · Swagger: `/docs`.

## Chạy (CLI)

```bash
idempotency-agent \
  --method POST \
  --url http://localhost:3000/api/orders \
  --header "Content-Type:application/json" \
  --body '{"product_id": "abc", "qty": 1}' \
  --key-name Idempotency-Key --key-value key-001 \
  --expected-status 201
```

### AI analysis (Claude)

Thêm `--analyze` (CLI) hoặc tick "AI analysis" (web) để Claude đọc kết quả test và đưa ra **verdict** (`IDEMPOTENT` / `NOT_IDEMPOTENT` / `INCONCLUSIVE`), nguyên nhân khả dĩ và khuyến nghị. Cần `ANTHROPIC_API_KEY` trong env; model mặc định `claude-opus-4-8` (đổi qua `ANTHROPIC_MODEL`). Verdict PASS/FAIL vẫn do luật cứng quyết định — AI chỉ diễn giải.

```bash
ANTHROPIC_API_KEY=sk-... idempotency-agent --url http://localhost:3000/api/orders \
  --key-value key-001 --expected-status 201 --analyze
```

Với DB validation:

```bash
idempotency-agent --url http://localhost:3000/api/orders \
  --body '{"product_id":"abc"}' --key-value key-001 \
  --mongo-uri mongodb://localhost:27017 --mongo-db mydb \
  --mongo-collection orders --mongo-query '{"product_id":"abc"}'
```

> Chưa cài package? Chạy trực tiếp: `PYTHONPATH=src python -m idempotency_agent.cli --url ...`

## Test & lint

```bash
pytest                 # full suite
pytest -m unit         # vòng nhanh
ruff check src tests
```
