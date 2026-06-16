"""
Runner — orchestration layer. Tách khỏi CLI để có thể gọi trực tiếp từ test/code.
"""
from idempotency_agent.config import settings
from idempotency_agent.db import take_db_snapshot
from idempotency_agent.executor import run_test_case
from idempotency_agent.generator import generate_test_cases
from idempotency_agent.models import (
    AITestCase,
    DBValidationConfig,
    RequestTemplate,
    ResponseTemplate,
    ScenarioType,
    TestCase,
    TestResult,
)
from idempotency_agent.validator import evaluate, evaluate_ai


def run_suite(
    request_template: RequestTemplate,
    response_template: ResponseTemplate,
    db_config: DBValidationConfig | None = None,
    n_calls: int | None = None,
    concurrent_workers: int | None = None,
    verbose: bool = True,
) -> list[TestResult]:
    """
    Chạy toàn bộ idempotency suite, trả về list TestResult.

    Pure orchestration — không tự in report/summary để caller tự quyết định output.
    """
    n_calls = n_calls or settings.n_calls
    concurrent_workers = concurrent_workers or settings.concurrent_workers

    test_cases = generate_test_cases(
        n_calls=n_calls,
        concurrent_workers=concurrent_workers,
    )
    if verbose:
        print(f"\n🔍 Running {len(test_cases)} idempotency test cases "
              f"against {request_template.url}\n")

    results: list[TestResult] = []
    for i, tc in enumerate(test_cases, 1):
        if verbose:
            print(f"  [{i}/{len(test_cases)}] {tc.scenario.value} ... ", end="", flush=True)

        db_before = take_db_snapshot(db_config)
        api_results = run_test_case(tc, request_template)
        db_after = take_db_snapshot(db_config)

        result = evaluate(tc, api_results, response_template, db_before, db_after)
        results.append(result)

        if verbose:
            icon = "✅" if result.status.value == "PASS" else (
                "❌" if result.status.value == "FAIL" else "⚠️"
            )
            print(icon)

    return results


def run_ai_suite(
    test_cases: list[AITestCase],
    request_template: RequestTemplate,
    response_template: ResponseTemplate,
    db_config: DBValidationConfig | None = None,
    verbose: bool = False,
) -> list[TestResult]:
    """Chạy list AITestCase do AI thiết kế, trả về list TestResult."""
    results: list[TestResult] = []
    for tc in test_cases:
        db_before = take_db_snapshot(db_config)

        from dataclasses import replace as _replace

        # omit_key=True: gửi request không có idempotency key (test case missing key)
        if tc.omit_key:
            effective_template = _replace(
                request_template,
                idempotency_key_location="__omit__",  # sentinel — executor bỏ qua
                idempotency_key_value="",
            )
            _tc = TestCase(
                scenario=ScenarioType.SINGLE_CALL,
                description=tc.description,
                repeat_count=tc.repeat_count,
                concurrent=tc.concurrent,
                use_different_key=False,
            )
            api_results = run_test_case(_tc, effective_template)
            db_after = take_db_snapshot(db_config)
            result = evaluate_ai(tc, api_results, response_template, db_before, db_after)
            results.append(result)
            continue

        # use_different_payload=True: call 1 dùng body gốc, call 2 dùng body biến đổi, cùng key
        if tc.use_different_payload:
            kv = tc.key_value or request_template.idempotency_key_value
            t = _replace(request_template, idempotency_key_value=kv)
            _tc1 = TestCase(scenario=ScenarioType.SINGLE_CALL, description=tc.description,
                            repeat_count=1, concurrent=False, use_different_key=False)
            api_results_1 = run_test_case(_tc1, t)

            # Body biến đổi: thêm field dummy hoặc thay đổi giá trị một field có sẵn
            original_body = dict(request_template.body) if request_template.body else {}
            varied_body = {**original_body, "_test_variation": "modified_payload"}
            t2 = _replace(t, body=varied_body)
            _tc2 = TestCase(scenario=ScenarioType.SINGLE_CALL, description=tc.description,
                            repeat_count=1, concurrent=False, use_different_key=False)
            api_results_2 = run_test_case(_tc2, t2)

            api_results = api_results_1 + api_results_2
            db_after = take_db_snapshot(db_config)
            result = evaluate_ai(tc, api_results, response_template, db_before, db_after)
            results.append(result)
            continue

        # Override key value nếu AI chỉ định riêng cho test case này
        effective_template = request_template
        if tc.key_value or tc.alt_key_value:
            kv = tc.key_value or request_template.idempotency_key_value
            effective_template = _replace(request_template, idempotency_key_value=kv)

            if tc.alt_key_value and tc.use_different_key:
                # different_key test: gọi call 1 với key_value, call 2 với alt_key_value
                # → 2 request riêng biệt, gộp kết quả lại
                t1 = _replace(request_template, idempotency_key_value=kv)
                t2 = _replace(request_template, idempotency_key_value=tc.alt_key_value)
                _tc1 = TestCase(scenario=ScenarioType.SINGLE_CALL, description=tc.description,
                                repeat_count=1, concurrent=False, use_different_key=False)
                _tc2 = TestCase(scenario=ScenarioType.SINGLE_CALL, description=tc.description,
                                repeat_count=1, concurrent=False, use_different_key=False)
                api_results = run_test_case(_tc1, t1) + run_test_case(_tc2, t2)
                db_after = take_db_snapshot(db_config)
                result = evaluate_ai(tc, api_results, response_template, db_before, db_after)
                results.append(result)
                continue

        # Tái dụng executor qua TestCase tạm — chỉ cần repeat_count/concurrent/use_different_key
        _tc = TestCase(
            scenario=ScenarioType.SINGLE_CALL,
            description=tc.description,
            repeat_count=tc.repeat_count,
            concurrent=tc.concurrent,
            use_different_key=tc.use_different_key,
        )
        api_results = run_test_case(_tc, effective_template)
        db_after = take_db_snapshot(db_config)
        result = evaluate_ai(tc, api_results, response_template, db_before, db_after)
        results.append(result)
    return results
