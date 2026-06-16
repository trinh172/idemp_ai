"""
Validator — kiểm tra response & DB state, tổng hợp thành TestResult.
Pure: không network, không DB, không I/O.
"""
from deepdiff import DeepDiff

from idempotency_agent.models import (
    AITestCase,
    APICallResult,
    DBSnapshot,
    IDEMPOTENT_SCENARIOS,
    ResponseTemplate,
    TestCase,
    TestResult,
    TestStatus,
)


# ─── Response validation ──────────────────────────────────────────────────────

def _normalize(body, ignore_fields: list[str]):
    if not isinstance(body, dict):
        return body
    return {k: v for k, v in body.items() if k not in ignore_fields}


def validate_responses_identical(
    results: list[APICallResult],
    ignore_fields: list[str],
) -> tuple[bool, dict | None]:
    if len(results) < 2:
        return True, None
    first = _normalize(results[0].body, ignore_fields)
    for other in results[1:]:
        diff = DeepDiff(first, _normalize(other.body, ignore_fields), ignore_order=True)
        if diff:
            return False, diff.to_dict()
    return True, None


def validate_status_codes(
    results: list[APICallResult],
    expected_status: int,
) -> tuple[bool, str | None]:
    wrong = [
        f"Call #{i + 1}: got {r.status_code}"
        for i, r in enumerate(results)
        if r.status_code != expected_status
    ]
    return (False, "; ".join(wrong)) if wrong else (True, None)


# ─── DB validation ──────────────────────────────────────────────────────────────

def validate_db_no_duplicate(
    before: DBSnapshot,
    after: DBSnapshot,
    enforce: bool,
) -> tuple[bool, str | None]:
    """DB chỉ được tăng tối đa 1 record nếu enforce=True."""
    if not enforce:
        return True, None
    issues = []
    if before.mongo_count is not None and after.mongo_count is not None:
        if (delta := after.mongo_count - before.mongo_count) > 1:
            issues.append(f"MongoDB: {delta} records created (expected ≤ 1)")
    if before.mysql_count is not None and after.mysql_count is not None:
        if (delta := after.mysql_count - before.mysql_count) > 1:
            issues.append(f"MySQL: {delta} rows created (expected ≤ 1)")
    return (False, "; ".join(issues)) if issues else (True, None)


# ─── Evaluate (hardcoded scenarios) ──────────────────────────────────────────

def evaluate(
    test_case: TestCase,
    api_results: list[APICallResult],
    response_template: ResponseTemplate,
    db_before: DBSnapshot,
    db_after: DBSnapshot,
) -> TestResult:
    errors = [r for r in api_results if r.is_error]
    if errors:
        return TestResult(
            scenario=test_case.scenario.value,
            description=test_case.description,
            status=TestStatus.ERROR,
            api_results=api_results,
            db_before=db_before,
            db_after=db_after,
            failure_reason=f"Request error: {errors[0].error}",
        )

    failures: list[str] = []
    is_idempotent = test_case.scenario in IDEMPOTENT_SCENARIOS

    ok, reason = validate_status_codes(api_results, response_template.expected_status_code)
    if not ok:
        failures.append(f"Status code mismatch — {reason}")

    response_diff = None
    if is_idempotent:
        ok, diff = validate_responses_identical(api_results, response_template.ignore_fields)
        if not ok:
            failures.append("Responses are NOT identical across calls")
            response_diff = diff

    ok, reason = validate_db_no_duplicate(db_before, db_after, enforce=is_idempotent)
    if not ok:
        failures.append(reason)

    return TestResult(
        scenario=test_case.scenario.value,
        description=test_case.description,
        status=TestStatus.FAIL if failures else TestStatus.PASS,
        api_results=api_results,
        db_before=db_before,
        db_after=db_after,
        failure_reason="; ".join(failures) if failures else None,
        response_diff=response_diff,
    )


# ─── Evaluate (AI-designed test cases) ───────────────────────────────────────

def evaluate_ai(
    test_case: AITestCase,
    api_results: list[APICallResult],
    response_template: ResponseTemplate,
    db_before: DBSnapshot,
    db_after: DBSnapshot,
) -> TestResult:
    """Evaluate dựa trên flags do AI thiết kế (không dùng IDEMPOTENT_SCENARIOS)."""
    errors = [r for r in api_results if r.is_error]
    if errors:
        return TestResult(
            scenario=test_case.name,
            description=test_case.description,
            status=TestStatus.ERROR,
            api_results=api_results,
            db_before=db_before,
            db_after=db_after,
            failure_reason=f"Request error: {errors[0].error}",
        )

    failures: list[str] = []

    ok, reason = validate_status_codes(api_results, response_template.expected_status_code)
    if not ok:
        failures.append(f"Status code mismatch — {reason}")

    response_diff = None
    if test_case.should_responses_be_identical:
        ok, diff = validate_responses_identical(api_results, response_template.ignore_fields)
        if not ok:
            failures.append("Responses are NOT identical across calls")
            response_diff = diff

    ok, reason = validate_db_no_duplicate(
        db_before, db_after, enforce=test_case.should_db_not_duplicate
    )
    if not ok:
        failures.append(reason)

    return TestResult(
        scenario=test_case.name,
        description=test_case.description,
        status=TestStatus.FAIL if failures else TestStatus.PASS,
        api_results=api_results,
        db_before=db_before,
        db_after=db_after,
        failure_reason="; ".join(failures) if failures else None,
        response_diff=response_diff,
    )
