"""
Idempotency Test Agent — SDET framework để verify tính idempotency của HTTP API.

Public API:
    from idempotency_agent import run_suite, RequestTemplate, ResponseTemplate
"""
from idempotency_agent.models import (
    RequestTemplate,
    ResponseTemplate,
    DBValidationConfig,
    TestCase,
    TestResult,
    TestStatus,
    ScenarioType,
    APICallResult,
    DBSnapshot,
)
from idempotency_agent.runner import run_suite

__version__ = "1.0.0"

__all__ = [
    "run_suite",
    "RequestTemplate",
    "ResponseTemplate",
    "DBValidationConfig",
    "TestCase",
    "TestResult",
    "TestStatus",
    "ScenarioType",
    "APICallResult",
    "DBSnapshot",
]
