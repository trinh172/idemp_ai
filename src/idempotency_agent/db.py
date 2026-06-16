"""
DB adapters — chụp snapshot trạng thái MongoDB / MySQL để verify side-effects.

Tách riêng khỏi validator để có thể mock dễ dàng trong unit test.
"""
import re

from idempotency_agent.models import DBSnapshot, DBValidationConfig

# Chỉ cho phép identifier hợp lệ (chống SQL injection qua tên bảng).
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    """Validate tên bảng/cột; raise nếu chứa ký tự nguy hiểm."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f"`{name}`"


def _mongo_count(cfg: DBValidationConfig) -> int | None:
    try:
        from pymongo import MongoClient

        client = MongoClient(cfg.mongo_uri)
        try:
            db = client[cfg.mongo_db]
            return db[cfg.mongo_collection].count_documents(cfg.mongo_query or {})
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 — snapshot không được làm crash test run
        print(f"[WARN] MongoDB snapshot failed: {exc}")
        return None


def _mysql_count(cfg: DBValidationConfig) -> int | None:
    try:
        import pymysql

        conn = pymysql.connect(
            host=cfg.mysql_host,
            port=cfg.mysql_port,
            user=cfg.mysql_user,
            password=cfg.mysql_password,
            database=cfg.mysql_database,
        )
        try:
            table = _safe_identifier(cfg.mysql_table)
            where = f" WHERE {cfg.mysql_where}" if cfg.mysql_where else ""
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}{where}")
                return cur.fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] MySQL snapshot failed: {exc}")
        return None


def take_db_snapshot(db_config: DBValidationConfig | None) -> DBSnapshot:
    """Chụp count documents/rows. Trả về snapshot rỗng nếu không có config."""
    snapshot = DBSnapshot()
    if db_config is None:
        return snapshot

    if db_config.has_mongo:
        snapshot.mongo_count = _mongo_count(db_config)
    if db_config.has_mysql:
        snapshot.mysql_count = _mysql_count(db_config)

    return snapshot
