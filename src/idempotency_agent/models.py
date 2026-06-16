"""
Data models — pure dataclasses, không chứa business logic.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ScenarioType(str, Enum):
    SINGLE_CALL = "single_call"
    DUPLICATE_CALL = "duplicate_call"
    N_CALLS = "n_calls"
    CONCURRENT_CALLS = "concurrent_calls"
    DIFFERENT_KEY = "different_key"


class TestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


# Scenarios mà response phải identical & DB không được tạo duplicate.
IDEMPOTENT_SCENARIOS = frozenset(
    {
        ScenarioType.DUPLICATE_CALL,
        ScenarioType.N_CALLS,
        ScenarioType.CONCURRENT_CALLS,
    }
)


@dataclass
class RequestTemplate:
    """Template cho API request từ user input."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Optional[dict[str, Any]] = None
    idempotency_key_location: str = "header"  # "header" | "body"
    idempotency_key_name: str = "Idempotency-Key"
    idempotency_key_value: str = ""


@dataclass
class ResponseTemplate:
    """Template response mong đợi."""

    expected_status_code: int = 200
    expected_body_fields: Optional[dict[str, Any]] = None
    ignore_fields: list[str] = field(default_factory=list)


@dataclass
class DBValidationConfig:
    """Config để validate DB state sau mỗi test."""

    # MongoDB
    mongo_uri: Optional[str] = None
    mongo_db: Optional[str] = None
    mongo_collection: Optional[str] = None
    mongo_query: Optional[dict] = None

    # MySQL
    mysql_host: Optional[str] = None
    mysql_port: int = 3306
    mysql_user: Optional[str] = None
    mysql_password: Optional[str] = None
    mysql_database: Optional[str] = None
    mysql_table: Optional[str] = None
    mysql_where: Optional[str] = None

    @property
    def has_mongo(self) -> bool:
        return bool(self.mongo_uri and self.mongo_collection)

    @property
    def has_mysql(self) -> bool:
        return bool(self.mysql_host and self.mysql_table)


@dataclass
class TestCase:
    """Một test case cụ thể."""

    scenario: ScenarioType
    description: str
    repeat_count: int = 1
    concurrent: bool = False
    use_different_key: bool = False


@dataclass
class APICallResult:
    """Kết quả một lần gọi API."""

    status_code: int
    body: Any
    response_time_ms: float
    error: Optional[str] = None
    request_body: Any = None          # body thực tế đã gửi (sau khi gắn key nếu ở body)
    request_idempotency_key: Optional[str] = None  # giá trị idempotency key đã dùng

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class DBSnapshot:
    """Snapshot DB tại một thời điểm."""

    mongo_count: Optional[int] = None
    mysql_count: Optional[int] = None


@dataclass
class AITestCase:
    """Test case do AI thiết kế — không hardcode scenario."""

    name: str
    description: str
    repeat_count: int = 1
    concurrent: bool = False
    use_different_key: bool = False
    should_responses_be_identical: bool = False
    should_db_not_duplicate: bool = False
    expected_behavior: str = ""
    key_value: Optional[str] = None      # override key chính (None = dùng giá trị từ plan)
    alt_key_value: Optional[str] = None  # override key cho use_different_key=True
    omit_key: bool = False               # True = gửi request KHÔNG có idempotency key (test case #9)
    use_different_payload: bool = False  # True = call 2 dùng payload biến đổi, cùng key (test case #5)


@dataclass
class TestResult:
    """Kết quả của một test case."""

    scenario: str  # ScenarioType.value hoặc tên do AI đặt
    description: str
    status: TestStatus
    api_results: list[APICallResult] = field(default_factory=list)
    db_before: Optional[DBSnapshot] = None
    db_after: Optional[DBSnapshot] = None
    failure_reason: Optional[str] = None
    response_diff: Optional[dict] = None
