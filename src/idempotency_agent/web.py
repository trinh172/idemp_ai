"""
Web layer — FastAPI app cho phép nhập request template / token / idempotency key
qua UI và chạy idempotency suite.

Theo SKILL.md: đây là layer wiring (giống cli.py), KHÔNG chứa business logic —
chỉ map input → models → runner.run_suite → serialize output.
"""
from pathlib import Path

import uuid as _uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from idempotency_agent.models import (
    DBValidationConfig,
    RequestTemplate,
    ResponseTemplate,
    TestResult,
)
from idempotency_agent.runner import run_suite

_TEMPLATE_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Idempotency Test Agent", version="1.0.0")


# ─── Request/response schemas (chỉ cho web layer) ─────────────────────────────

class MongoConfig(BaseModel):
    uri: str | None = None
    db: str | None = None
    collection: str | None = None
    query: dict | None = None


class MysqlConfig(BaseModel):
    host: str | None = None
    port: int = 3306
    user: str | None = None
    password: str | None = None
    database: str | None = None
    table: str | None = None
    where: str | None = None


class RunRequest(BaseModel):
    # ── Request template ──
    method: str = "POST"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict | None = None
    # ── Authorization (optional) ──
    auth_token: str | None = None
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"  # "" để gửi token trần
    # ── Idempotency key ──
    key_location: str = "header"   # header | body
    key_name: str = "Idempotency-Key"
    key_value: str
    # ── Expected response ──
    expected_status: int = 200
    ignore_fields: list[str] = Field(default_factory=list)
    # ── Test config ──
    n_calls: int | None = None
    concurrent: int | None = None
    # ── DB (optional) ──
    mongo: MongoConfig | None = None
    mysql: MysqlConfig | None = None
    # ── AI analysis (optional) ──
    analyze: bool = False


# ─── Serialization helpers ────────────────────────────────────────────────────

def _extract_response_data(body, path: str | None):
    """Lấy sub-field từ response body theo path (vd 'data'). Trả nguyên body nếu không có path."""
    if not path or not isinstance(body, dict):
        return body
    return body.get(path, body)


def _serialize(result: TestResult, response_data_path: str | None = None) -> dict:
    return {
        "scenario": result.scenario,
        "description": result.description,
        "status": result.status.value,
        "failure_reason": result.failure_reason,
        "response_diff": result.response_diff,
        "calls": [
            {
                "index": i + 1,
                "status_code": c.status_code,
                "response_time_ms": c.response_time_ms,
                "error": c.error,
                "request_body": c.request_body,
                "idempotency_key": c.request_idempotency_key,
                "response_body": _extract_response_data(c.body, response_data_path),
                "response_body_full": c.body,
            }
            for i, c in enumerate(result.api_results)
        ],
        "db_before": vars(result.db_before) if result.db_before else None,
        "db_after": vars(result.db_after) if result.db_after else None,
    }


def _build_db_config(req: RunRequest) -> DBValidationConfig | None:
    has_mongo = req.mongo and req.mongo.uri and req.mongo.collection
    has_mysql = req.mysql and req.mysql.host and req.mysql.table
    if not (has_mongo or has_mysql):
        return None
    m, s = req.mongo or MongoConfig(), req.mysql or MysqlConfig()
    return DBValidationConfig(
        mongo_uri=m.uri, mongo_db=m.db, mongo_collection=m.collection, mongo_query=m.query,
        mysql_host=s.host, mysql_port=s.port, mysql_user=s.user, mysql_password=s.password,
        mysql_database=s.database, mysql_table=s.table, mysql_where=s.where,
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

class CurlRunRequest(BaseModel):
    curl: str
    description: str = ""
    response_data_path: str | None = None  # vd "data" nếu API wrap {data: ...}
    n_calls: int | None = None
    concurrent: int | None = None
    mongo: MongoConfig | None = None
    mysql: MysqlConfig | None = None
    analyze: bool = True


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")


# Sync endpoint cố ý: run_suite gọi asyncio.run bên trong; FastAPI chạy sync
# endpoint trong threadpool nên không đụng event loop của server.
@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    headers = dict(req.headers)
    if req.auth_token:
        value = f"{req.auth_scheme} {req.auth_token}".strip() if req.auth_scheme else req.auth_token
        headers[req.auth_header] = value

    request_template = RequestTemplate(
        method=req.method.upper(),
        url=req.url,
        headers=headers,
        body=req.body,
        idempotency_key_location=req.key_location,
        idempotency_key_name=req.key_name,
        idempotency_key_value=req.key_value,
    )
    response_template = ResponseTemplate(
        expected_status_code=req.expected_status,
        ignore_fields=req.ignore_fields,
    )

    results = run_suite(
        request_template=request_template,
        response_template=response_template,
        db_config=_build_db_config(req),
        n_calls=req.n_calls,
        concurrent_workers=req.concurrent,
        verbose=False,
    )

    out = {
        "endpoint": req.url,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status.value == "PASS"),
            "failed": sum(1 for r in results if r.status.value == "FAIL"),
            "errored": sum(1 for r in results if r.status.value == "ERROR"),
        },
        "results": [_serialize(r) for r in results],
        "analysis": None,
    }

    if req.analyze:
        from idempotency_agent.analyzer import AnalyzerError, analyze_results
        try:
            a = analyze_results(results, req.url)
            out["analysis"] = {
                "verdict": a.verdict,
                "confidence": a.confidence,
                "summary": a.summary,
                "likely_causes": a.likely_causes,
                "recommendations": a.recommendations,
            }
        except AnalyzerError as exc:
            out["analysis"] = {"error": str(exc)}

    return out


@app.post("/api/run-curl")
def api_run_curl(req: CurlRunRequest) -> dict:
    """Nhận curl command + mô tả → AI tự sinh cấu hình → chạy suite idempotency."""
    from idempotency_agent.curl_parser import CurlParseError, parse_curl
    from idempotency_agent.planner import PlannerError, design_test_cases, plan_from_curl
    from idempotency_agent.runner import run_ai_suite

    # 1. Parse curl
    try:
        parsed = parse_curl(req.curl)
    except CurlParseError as exc:
        raise HTTPException(status_code=400, detail=f"Lỗi parse curl: {exc}")

    # 2. AI planner → TestPlan (key config, expected status)
    try:
        plan = plan_from_curl(parsed, req.description)
    except PlannerError as exc:
        raise HTTPException(status_code=502, detail=f"AI planner lỗi: {exc}")

    # 3. AI designer → AITestCase list (requirement analysis + test design)
    try:
        ai_test_cases = design_test_cases(parsed, plan, req.description)
    except PlannerError as exc:
        raise HTTPException(status_code=502, detail=f"AI test design lỗi: {exc}")

    # 4. Tách auth ra khỏi headers
    headers = dict(parsed.get("headers", {}))
    auth_value = headers.pop("Authorization", None) or headers.pop("authorization", None)
    if auth_value:
        headers["Authorization"] = auth_value

    # 5. Xác định key value
    if plan.key_gen == "uuid4" or not plan.key_value:
        key_value = str(_uuid.uuid4())
    else:
        key_value = plan.key_value

    # 6. Build models
    request_template = RequestTemplate(
        method=parsed["method"],
        url=parsed["url"],
        headers=headers,
        body=parsed.get("body"),
        idempotency_key_location=plan.key_location,
        idempotency_key_name=plan.key_name,
        idempotency_key_value=key_value,
    )
    rdp = req.response_data_path or plan.response_data_path or None
    response_template = ResponseTemplate(
        expected_status_code=plan.expected_status,
        ignore_fields=plan.ignore_fields,
    )

    # DB config (tuỳ chọn)
    has_mongo = req.mongo and req.mongo.uri and req.mongo.collection
    has_mysql = req.mysql and req.mysql.host and req.mysql.table
    db_config = None
    if has_mongo or has_mysql:
        m = req.mongo or MongoConfig()
        s = req.mysql or MysqlConfig()
        from idempotency_agent.models import DBValidationConfig
        db_config = DBValidationConfig(
            mongo_uri=m.uri, mongo_db=m.db, mongo_collection=m.collection, mongo_query=m.query,
            mysql_host=s.host, mysql_port=s.port, mysql_user=s.user, mysql_password=s.password,
            mysql_database=s.database, mysql_table=s.table, mysql_where=s.where,
        )

    # 7. Chạy AI-designed suite
    results = run_ai_suite(
        test_cases=ai_test_cases,
        request_template=request_template,
        response_template=response_template,
        db_config=db_config,
    )

    out = {
        "endpoint": parsed["url"],
        "plan": {
            "key_location": plan.key_location,
            "key_name": plan.key_name,
            "key_gen": plan.key_gen,
            "key_value": key_value,
            "expected_status": plan.expected_status,
            "ignore_fields": plan.ignore_fields,
            "notes": plan.notes,
            "response_data_path": rdp,
        },
        "test_design": [
            {
                "name": tc.name,
                "description": tc.description,
                "repeat_count": tc.repeat_count,
                "concurrent": tc.concurrent,
                "use_different_key": tc.use_different_key,
                "should_responses_be_identical": tc.should_responses_be_identical,
                "should_db_not_duplicate": tc.should_db_not_duplicate,
                "key_value": tc.key_value,
                "alt_key_value": tc.alt_key_value,
                "expected_behavior": tc.expected_behavior,
            }
            for tc in ai_test_cases
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status.value == "PASS"),
            "failed": sum(1 for r in results if r.status.value == "FAIL"),
            "errored": sum(1 for r in results if r.status.value == "ERROR"),
        },
        "results": [_serialize(r, rdp) for r in results],
        "analysis": None,
    }

    if req.analyze:
        from idempotency_agent.analyzer import AnalyzerError, analyze_results
        try:
            a = analyze_results(results, parsed["url"])
            out["analysis"] = {
                "verdict": a.verdict,
                "confidence": a.confidence,
                "summary": a.summary,
                "likely_causes": a.likely_causes,
                "recommendations": a.recommendations,
            }
        except AnalyzerError as exc:
            out["analysis"] = {"error": str(exc)}

    return out
