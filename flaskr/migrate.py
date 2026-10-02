"""마이그레이션 러너 (C-09).

    python -m flaskr.migrate {precheck|up|verify} [--json]

- 입력: 환경변수 DATABASE_URL_MIGRATOR(있으면 우선, 마이그레이션 전용 계정) 또는 DATABASE_URL(MySQL),
  이미지 안 migrations/NNNN_<이름>.sql,
  선택 MIGRATE_MODE=bootstrap(precheck에서 DB가 비었는지 확인, V18)
- precheck는 @@require_secure_transport도 확인한다(ON인데 TLS가 아니면 실패)
- 출력: stdout 한 줄 `MIGRATE_RESULT {...}` + exit code(0 = ok, 1 = 실패, 2 = 사용법 오류)
  {"phase", "ok", "current", "expected", "applied", "signature", "fingerprint"} 외 키는 없다
  (온프렘 provider가 extra=forbid로 검사한다). 진단 문구는 stderr로만 쓴다.
- 추가형만: CREATE TABLE, CREATE INDEX, ALTER TABLE ... ADD ... 만 허용한다.
- MySQL DDL은 암묵 커밋이라 중간 실패 시 앞 문장이 남는다. 문장마다 information_schema로
  이미 있는지 확인하고 건너뛰므로 다시 실행해도 안전하다.
- DB는 롤백하지 않는다. 그래서 v1 코드가 v2 스키마(post.author_id NULL 허용)에서도 돌아야 한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PHASES = ("precheck", "up", "verify")
LOCK_NAME = "flaskr_migrate"
_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_EMPTY_SIGNATURE = "sha256:" + hashlib.sha256(b"").hexdigest()


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    checksum: str


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "migrations"


def migration_files() -> list[MigrationFile]:
    files = []
    for path in sorted(migrations_dir().glob("*.sql")):
        match = _FILE.match(path.name)
        if not match:
            raise MigrationError(f"마이그레이션 파일 이름 오류: {path.name}")
        files.append(
            MigrationFile(
                version=match.group(1),
                name=match.group(2),
                path=path,
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    versions = [f.version for f in files]
    if len(set(versions)) != len(versions):
        raise MigrationError("같은 버전 번호의 마이그레이션 파일이 둘 이상 있습니다")
    return files


def expected_version() -> str | None:
    files = migration_files()
    return files[-1].version if files else None


# ---- 문장 분리·lint·가드 ----------------------------------------------------

_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?", re.IGNORECASE
)
_CREATE_INDEX = re.compile(
    r"^CREATE\s+(UNIQUE\s+)?INDEX\s+`?(\w+)`?\s+ON\s+`?(\w+)`?", re.IGNORECASE
)
_ALTER_ADD = re.compile(r"^ALTER\s+TABLE\s+`?(\w+)`?\s+ADD\s+(.*)$", re.IGNORECASE | re.DOTALL)
_ADD_CONSTRAINT = re.compile(r"^CONSTRAINT\s+`?(\w+)`?", re.IGNORECASE)
_ADD_INDEX = re.compile(r"^(UNIQUE\s+)?(INDEX|KEY)\s+`?(\w+)`?", re.IGNORECASE)
_ADD_COLUMN = re.compile(r"^(COLUMN\s+)?`?(\w+)`?\s+", re.IGNORECASE)
_DESTRUCTIVE = re.compile(r"\b(DROP|RENAME|MODIFY|CHANGE|TRUNCATE)\b", re.IGNORECASE)


def split_statements(sql: str) -> list[str]:
    """`--` 주석을 지우고 줄 끝 `;`으로 문장을 나눈다(MULTI_STATEMENTS를 쓰지 않는다)."""
    lines = []
    for line in sql.splitlines():
        cut = line.find("--")
        lines.append(line if cut < 0 else line[:cut])
    statements, current = [], []
    for line in lines:
        current.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def lint(statement: str) -> str | None:
    """추가형이 아니면 이유를 돌려준다."""
    if _CREATE_TABLE.match(statement) or _CREATE_INDEX.match(statement):
        return None
    match = _ALTER_ADD.match(statement)
    if match and not _DESTRUCTIVE.search(match.group(2)):
        return None
    return "추가형이 아닌 문장: " + statement.split("\n", 1)[0][:80]


def _exists(conn, sql: str, **params) -> bool:
    from sqlalchemy import text

    return conn.execute(text(sql), params).first() is not None


def already_applied(conn, statement: str) -> bool:
    """문장 단위 가드: 결과물이 이미 있으면 True."""
    schema_filter = "TABLE_SCHEMA = DATABASE()"
    match = _CREATE_TABLE.match(statement)
    if match:
        return _exists(
            conn,
            f"SELECT 1 FROM information_schema.TABLES WHERE {schema_filter} AND TABLE_NAME = :t",
            t=match.group(2),
        )
    match = _CREATE_INDEX.match(statement)
    if match:
        return _exists(
            conn,
            "SELECT 1 FROM information_schema.STATISTICS"
            f" WHERE {schema_filter} AND TABLE_NAME = :t AND INDEX_NAME = :i",
            t=match.group(3),
            i=match.group(2),
        )
    match = _ALTER_ADD.match(statement)
    if not match:
        return False
    table, rest = match.group(1), match.group(2).strip()
    sub = _ADD_CONSTRAINT.match(rest)
    if sub:
        return _exists(
            conn,
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS"
            f" WHERE {schema_filter} AND TABLE_NAME = :t AND CONSTRAINT_NAME = :c",
            t=table,
            c=sub.group(1),
        )
    sub = _ADD_INDEX.match(rest)
    if sub:
        return _exists(
            conn,
            "SELECT 1 FROM information_schema.STATISTICS"
            f" WHERE {schema_filter} AND TABLE_NAME = :t AND INDEX_NAME = :i",
            t=table,
            i=sub.group(3),
        )
    sub = _ADD_COLUMN.match(rest)
    if sub:
        return _exists(
            conn,
            "SELECT 1 FROM information_schema.COLUMNS"
            f" WHERE {schema_filter} AND TABLE_NAME = :t AND COLUMN_NAME = :c",
            t=table,
            c=sub.group(2),
        )
    return False


# ---- DB 조회 ----------------------------------------------------------------

_SCHEMA_MIGRATIONS = """CREATE TABLE IF NOT EXISTS schema_migrations (
  version    VARCHAR(16)  NOT NULL PRIMARY KEY,
  name       VARCHAR(100) NOT NULL,
  checksum   CHAR(64)     NOT NULL,
  applied_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  release_id VARCHAR(64)  NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"""


def applied_rows(conn) -> dict[str, str]:
    """{version: checksum}. 표가 없으면 빈 dict."""
    from sqlalchemy import text

    if not _exists(
        conn,
        "SELECT 1 FROM information_schema.TABLES"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'schema_migrations'",
    ):
        return {}
    rows = conn.execute(text("SELECT version, checksum FROM schema_migrations")).all()
    return {row[0]: row[1] for row in rows}


def drift(files: list[MigrationFile], applied: dict[str, str]) -> list[str]:
    return [f.version for f in files if f.version in applied and applied[f.version] != f.checksum]


def schema_signature(conn) -> str:
    """정렬한 information_schema(표·컬럼·인덱스·제약)의 sha256."""
    from sqlalchemy import text

    parts = []
    queries = (
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES"
        " WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME",
        "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, IS_NULLABLE,"
        " COLUMN_DEFAULT, EXTRA, COLLATION_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION",
        "SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE"
        " FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
        " ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
        "SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE"
        " FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE()"
        " ORDER BY TABLE_NAME, CONSTRAINT_NAME",
    )
    for query in queries:
        for row in conn.execute(text(query)).all():
            parts.append("|".join("" if v is None else str(v) for v in row))
        parts.append("--")
    return "sha256:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()


def fingerprint(conn) -> dict[str, str]:
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT VERSION(), @@GLOBAL.sql_mode, @@collation_server, @@GLOBAL.time_zone")
    ).one()
    ssl = conn.execute(text("SHOW SESSION STATUS LIKE 'Ssl_version'")).first()
    return {
        "version": str(row[0]),
        "sql_mode": str(row[1] or ""),
        "collation": str(row[2] or ""),
        "time_zone": str(row[3] or ""),
        "ssl_version": (ssl[1] or "") if ssl else "",
    }


# ---- 단계 -------------------------------------------------------------------


def _result(phase: str, ok: bool, current, expected, applied, signature, fp) -> dict:
    return {
        "phase": phase,
        "ok": ok,
        "current": current,
        "expected": expected,
        "applied": applied,
        "signature": signature,
        "fingerprint": fp,
    }


def _warn(message: str) -> None:
    sys.stderr.write(f"migrate: {message}\n")


def run(phase: str) -> dict:
    from sqlalchemy import text

    from flaskr.db import make_engine

    files = migration_files()
    if not files:
        raise MigrationError("migrations/에 파일이 없습니다")
    expected = files[-1].version
    # 온프렘은 권한을 나눠 마이그레이션 계정 주소를 DATABASE_URL_MIGRATOR로 넘긴다(앱 런타임에는 없음)
    database_url = os.environ.get("DATABASE_URL_MIGRATOR") or os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise MigrationError("DATABASE_URL_MIGRATOR와 DATABASE_URL이 모두 없습니다")
    engine = make_engine(database_url)
    if engine.url.get_backend_name() != "mysql":
        raise MigrationError("러너는 MySQL 전용입니다(개발 SQLite는 flask dev-schema)")
    tls_required = "ssl_ca" in engine.url.query

    ok = True
    applied_now: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        fp = fingerprint(conn)
        if tls_required and not fp["ssl_version"]:
            _warn("ssl_ca를 지정했지만 TLS 연결이 아닙니다")
            ok = False
        if phase == "precheck":
            secure = conn.execute(text("SELECT @@GLOBAL.require_secure_transport")).scalar()
            _warn(f"require_secure_transport={'ON' if secure else 'OFF'}")
            if secure and not fp["ssl_version"]:
                _warn("서버가 TLS를 요구하는데 TLS 연결이 아닙니다")
                ok = False
            if os.environ.get("MIGRATE_MODE") == "bootstrap":
                # 부트스트랩은 빈 DB에만(V18). 남은 표가 있으면 다른 앱·이전 데이터일 수 있다
                tables = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.TABLES"
                        " WHERE TABLE_SCHEMA = DATABASE()"
                    )
                ).scalar()
                if tables:
                    _warn(f"bootstrap인데 DB가 비어 있지 않습니다(표 {tables}개)")
                    ok = False

        problems = [
            f"{f.path.name}: {reason}"
            for f in files
            for reason in filter(None, map(lint, split_statements(f.path.read_text("utf-8"))))
        ]
        for problem in problems:
            _warn(problem)
        ok = ok and not problems

        applied = applied_rows(conn)
        drifted = drift(files, applied)
        if drifted:
            _warn("이미 적용된 파일 내용이 바뀜: " + ", ".join(drifted))
            ok = False

        if phase == "up" and ok:
            locked = conn.execute(text("SELECT GET_LOCK(:n, 10)"), {"n": LOCK_NAME}).scalar()
            if locked != 1:
                raise MigrationError("마이그레이션 잠금을 얻지 못했습니다")
            try:
                conn.execute(text(_SCHEMA_MIGRATIONS))
                applied = applied_rows(conn)
                if drift(files, applied):
                    raise MigrationError("잠금 뒤 checksum 드리프트")
                for item in files:
                    if item.version in applied:
                        continue
                    for statement in split_statements(item.path.read_text("utf-8")):
                        if already_applied(conn, statement):
                            _warn(f"{item.path.name}: 이미 있음, 건너뜀")
                            continue
                        conn.execute(text(statement))
                    conn.execute(
                        text(
                            "INSERT INTO schema_migrations (version, name, checksum, release_id)"
                            " VALUES (:v, :n, :c, :r)"
                        ),
                        {
                            "v": item.version,
                            "n": item.name,
                            "c": item.checksum,
                            "r": os.environ.get("RELEASE_ID") or None,
                        },
                    )
                    applied_now.append(item.version)
                applied = applied_rows(conn)
            finally:
                conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})

        current = max(applied) if applied else None
        if phase in ("up", "verify") and current != expected:
            if phase == "verify" or ok:
                _warn(f"현재 버전 {current} != 기대 버전 {expected}")
            ok = False
        signature = schema_signature(conn)
    engine.dispose()
    return _result(phase, ok, current, expected, applied_now, signature, fp)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--json"]
    if len(args) != 1 or args[0] not in PHASES:
        sys.stderr.write("사용법: python -m flaskr.migrate {precheck|up|verify} [--json]\n")
        return 2
    phase = args[0]
    try:
        result = run(phase)
    except Exception as error:  # 결과 줄은 항상 남긴다
        _warn(f"{type(error).__name__}: {error}")
        expected = None
        try:
            expected = expected_version()
        except MigrationError:
            pass
        result = _result(
            phase,
            False,
            None,
            expected or "0000",
            [],
            _EMPTY_SIGNATURE,
            {"version": "", "sql_mode": "", "collation": "", "time_zone": "", "ssl_version": ""},
        )
    sys.stdout.write("MIGRATE_RESULT " + json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
