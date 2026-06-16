"""
Reporter — render HTML report + in summary ra terminal.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from idempotency_agent.config import settings
from idempotency_agent.models import TestResult, TestStatus

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["tojson"] = lambda v, indent=None: json.dumps(v, indent=indent, ensure_ascii=False)
    return env


def generate_report(
    results: list[TestResult],
    endpoint: str,
    output_dir: str | None = None,
) -> str:
    """Sinh HTML report, lưu file, trả về path."""
    output_dir = output_dir or settings.report_output_dir
    template = _build_env().get_template("report.html.j2")

    passed = sum(1 for r in results if r.status == TestStatus.PASS)
    failed = sum(1 for r in results if r.status == TestStatus.FAIL)
    errored = sum(1 for r in results if r.status == TestStatus.ERROR)

    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        endpoint=endpoint,
        total=len(results),
        passed=passed,
        failed=failed,
        errored=errored,
        results=[
            {
                "scenario": r.scenario,
                "description": r.description,
                "status": r.status.value,
                "api_results": [
                    {"status_code": a.status_code, "response_time_ms": a.response_time_ms}
                    for a in r.api_results
                ],
                "failure_reason": r.failure_reason,
                "response_diff": r.response_diff,
                "db_before": r.db_before,
                "db_after": r.db_after,
            }
            for r in results
        ],
    )

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"idempotency_report_{timestamp}.html")
    Path(path).write_text(html, encoding="utf-8")
    return path


def print_summary(results: list[TestResult]) -> None:
    """In kết quả nhanh ra terminal."""
    print("\n" + "=" * 60)
    print("  IDEMPOTENCY TEST RESULTS")
    print("=" * 60)
    for r in results:
        icon = "✅" if r.status == TestStatus.PASS else ("❌" if r.status == TestStatus.FAIL else "⚠️")
        print(f"{icon} [{r.scenario}] {r.description}")
        if r.failure_reason:
            print(f"     → {r.failure_reason}")
    print("=" * 60)
    passed = sum(1 for r in results if r.status == TestStatus.PASS)
    print(f"  {passed}/{len(results)} passed\n")
