"""
CLI entry point — wiring giữa Click options và runner.

Usage:
  idempotency-agent --url http://localhost:3000/api/orders \
      --body '{"product_id": "abc", "qty": 1}' \
      --key-name Idempotency-Key --key-value key-001 \
      --expected-status 201
"""
import json

import click

from idempotency_agent.config import settings
from idempotency_agent.models import DBValidationConfig, RequestTemplate, ResponseTemplate
from idempotency_agent.reporter import generate_report, print_summary
from idempotency_agent.runner import run_suite


@click.command()
# ── Request ──────────────────────────────────────────────────────────────────
@click.option("--method", default="POST", show_default=True,
              type=click.Choice(["GET", "POST", "PUT", "PATCH", "DELETE"], case_sensitive=False),
              help="HTTP method")
@click.option("--url", required=True, help="Full API URL")
@click.option("--header", multiple=True, help="Header key:value (repeatable)")
@click.option("--body", default=None, help="Request body as JSON string")
# ── Idempotency key ───────────────────────────────────────────────────────────
@click.option("--key-location", default="header", show_default=True,
              type=click.Choice(["header", "body"]),
              help="Where the idempotent key is placed")
@click.option("--key-name", default="Idempotency-Key", show_default=True,
              help="Header name or body field name for idempotent key")
@click.option("--key-value", required=True, help="Value of the idempotent key")
# ── Expected response ─────────────────────────────────────────────────────────
@click.option("--expected-status", default=200, show_default=True, type=int,
              help="Expected HTTP status code")
@click.option("--ignore-field", multiple=True,
              help="Response body fields to ignore when comparing (repeatable)")
# ── Test config ───────────────────────────────────────────────────────────────
@click.option("--n-calls", default=None, type=int, help="Số lần call cho N_CALLS scenario")
@click.option("--concurrent", default=None, type=int, help="Số request song song")
# ── MongoDB (optional) ────────────────────────────────────────────────────────
@click.option("--mongo-uri", default=None)
@click.option("--mongo-db", default=None)
@click.option("--mongo-collection", default=None)
@click.option("--mongo-query", default=None, help="JSON filter for counting documents")
# ── MySQL (optional) ──────────────────────────────────────────────────────────
@click.option("--mysql-host", default=None)
@click.option("--mysql-port", default=3306, type=int)
@click.option("--mysql-user", default=None)
@click.option("--mysql-password", default=None)
@click.option("--mysql-database", default=None)
@click.option("--mysql-table", default=None)
@click.option("--mysql-where", default=None)
# ── AI analysis ───────────────────────────────────────────────────────────────
@click.option("--analyze/--no-analyze", default=False, show_default=True,
              help="Dùng Claude phân tích kết quả & đưa ra nhận định (cần ANTHROPIC_API_KEY)")
# ── Output ────────────────────────────────────────────────────────────────────
@click.option("--report-dir", default=None, help="Report output directory")
def main(
    method, url, header, body,
    key_location, key_name, key_value,
    expected_status, ignore_field,
    n_calls, concurrent,
    mongo_uri, mongo_db, mongo_collection, mongo_query,
    mysql_host, mysql_port, mysql_user, mysql_password, mysql_database, mysql_table, mysql_where,
    analyze,
    report_dir,
):
    headers = {}
    for h in header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    request_template = RequestTemplate(
        method=method.upper(),
        url=url,
        headers=headers,
        body=json.loads(body) if body else None,
        idempotency_key_location=key_location,
        idempotency_key_name=key_name,
        idempotency_key_value=key_value,
    )

    response_template = ResponseTemplate(
        expected_status_code=expected_status,
        ignore_fields=list(ignore_field),
    )

    db_config = DBValidationConfig(
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        mongo_collection=mongo_collection,
        mongo_query=json.loads(mongo_query) if mongo_query else None,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        mysql_database=mysql_database,
        mysql_table=mysql_table,
        mysql_where=mysql_where,
    ) if (mongo_uri or mysql_host) else None

    results = run_suite(
        request_template=request_template,
        response_template=response_template,
        db_config=db_config,
        n_calls=n_calls,
        concurrent_workers=concurrent,
    )

    print_summary(results)

    if analyze:
        from idempotency_agent.analyzer import analyze_results, AnalyzerError
        print("🤖 Đang phân tích kết quả bằng Claude ...")
        try:
            analysis = analyze_results(results, url)
            print("\n" + "=" * 60)
            print(f"  AI VERDICT: {analysis.verdict}  (confidence: {analysis.confidence})")
            print("=" * 60)
            print(f"  {analysis.summary}\n")
            if analysis.likely_causes:
                print("  Nguyên nhân khả dĩ:")
                for c in analysis.likely_causes:
                    print(f"    • {c}")
            if analysis.recommendations:
                print("  Khuyến nghị:")
                for r in analysis.recommendations:
                    print(f"    → {r}")
            print()
        except AnalyzerError as exc:
            click.secho(f"⚠️  AI analysis bỏ qua: {exc}", fg="yellow")

    report_path = generate_report(
        results, url, output_dir=report_dir or settings.report_output_dir
    )
    print(f"📄 HTML report saved: {report_path}\n")


if __name__ == "__main__":
    main()
