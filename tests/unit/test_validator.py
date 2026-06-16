import pytest

from idempotency_agent.models import (
    DBSnapshot,
    ScenarioType,
    TestCase,
    TestStatus,
)
from idempotency_agent.validator import (
    evaluate,
    validate_db_no_duplicate,
    validate_responses_identical,
    validate_status_codes,
)
from tests.conftest import make_call

pytestmark = pytest.mark.unit


def test_identical_responses_pass():
    ok, diff = validate_responses_identical([make_call(), make_call()], ignore_fields=[])
    assert ok and diff is None


def test_different_responses_fail():
    ok, diff = validate_responses_identical(
        [make_call(body={"id": 1}), make_call(body={"id": 2})], ignore_fields=[]
    )
    assert not ok and diff


def test_ignore_fields_skipped():
    ok, _ = validate_responses_identical(
        [make_call(body={"id": 1, "ts": "a"}), make_call(body={"id": 1, "ts": "b"})],
        ignore_fields=["ts"],
    )
    assert ok


def test_status_code_mismatch_detected():
    ok, reason = validate_status_codes([make_call(status=500)], expected_status=201)
    assert not ok and "500" in reason


@pytest.mark.parametrize("delta,expected_ok", [(0, True), (1, True), (2, False)])
def test_db_duplicate_threshold(delta, expected_ok):
    before = DBSnapshot(mysql_count=10)
    after = DBSnapshot(mysql_count=10 + delta)
    ok, _ = validate_db_no_duplicate(before, after, ScenarioType.CONCURRENT_CALLS)
    assert ok is expected_ok


def test_db_check_skipped_when_not_enforced():
    before, after = DBSnapshot(mysql_count=1), DBSnapshot(mysql_count=5)
    ok, _ = validate_db_no_duplicate(before, after, enforce=False)
    assert ok  # enforce=False → bỏ qua DB check

def test_db_check_enforced_detects_duplicate():
    before, after = DBSnapshot(mysql_count=1), DBSnapshot(mysql_count=5)
    ok, _ = validate_db_no_duplicate(before, after, enforce=True)
    assert not ok  # delta=4 > 1


def test_evaluate_error_short_circuits(response_template, empty_snapshot):
    tc = TestCase(scenario=ScenarioType.DUPLICATE_CALL, description="x", repeat_count=2)
    results = [make_call(), make_call(error="timeout")]
    out = evaluate(tc, results, response_template, empty_snapshot, empty_snapshot)
    assert out.status == TestStatus.ERROR
    assert "timeout" in out.failure_reason


def test_evaluate_pass(response_template, empty_snapshot):
    tc = TestCase(scenario=ScenarioType.DUPLICATE_CALL, description="x", repeat_count=2)
    results = [make_call(status=201), make_call(status=201)]
    out = evaluate(tc, results, response_template, empty_snapshot, empty_snapshot)
    assert out.status == TestStatus.PASS
