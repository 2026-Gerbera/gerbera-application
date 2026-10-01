"""DB 연결 (SQLAlchemy + DATABASE_URL).

원본 pallets/flask examples/tutorial/flaskr/db.py @d73fa1c(BSD-3-Clause)를 SQLAlchemy로 다시 씀.

- 개발 PC: sqlite:///instance/flaskr.sqlite (일부러 둔 개발값)
- 온프렘·클라우드: mysql+pymysql://...?charset=utf8mb4 (클라우드는 &ssl_ca=/app/certs/global-bundle.pem)
  SQLAlchemy가 ssl_ca를 PyMySQL ssl={"ca": ...}로 넘겨 인증서·호스트명을 검증한다.
- 쿼리는 text() + 이름 자리표시자(:title). 요청마다 engine.begin()으로 트랜잭션을 닫는다.
- 원본 init-db(DROP TABLE로 시작)는 없다. 스키마는 migrations/ + python -m flaskr.migrate로만 만든다.
"""

from __future__ import annotations

import hashlib
import ipaddress

import click
from flask import Flask, current_app
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

_EXT = "flaskr.engine"


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 280}
    if url.get_backend_name() == "mysql":
        kwargs["connect_args"] = {"init_command": "SET time_zone='+00:00'"}
    return create_engine(url, **kwargs)


def get_engine() -> Engine:
    return current_app.extensions[_EXT]


def init_app(app: Flask) -> None:
    app.extensions[_EXT] = make_engine(app.config["DATABASE_URL"])
    app.cli.add_command(dev_schema_command)


def mask_host(host: str | None) -> str | None:
    """/version에 보여 줄 DB 호스트. 앞부분만 남기고 가린다."""
    if not host:
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if len(labels) > 2:
            labels[1] = "●●●●"
        return ".".join(labels)
    if ip.version == 4:
        parts = host.split(".")
        parts[2] = "●"
        return ".".join(parts)
    return "●●●●:" + hashlib.sha256(host.encode()).hexdigest()[:8]


def tls_requested(engine: Engine) -> bool:
    """URL에 CA 검증 옵션이 있으면 TLS 검증을 요구한 것으로 본다."""
    return "ssl_ca" in engine.url.query


def ssl_version(conn: Connection) -> str:
    if conn.dialect.name != "mysql":
        return ""
    row = conn.execute(text("SHOW SESSION STATUS LIKE 'Ssl_version'")).first()
    return (row[1] or "") if row else ""


def connection_info(engine: Engine, conn: Connection | None) -> dict:
    """/version의 db 항목. 비밀번호·DB 지문(버전, sql_mode)은 넣지 않는다."""
    dialect = engine.url.get_backend_name()
    tls = bool(conn is not None and ssl_version(conn))
    return {
        "dialect": dialect,
        "host": mask_host(engine.url.host) if dialect != "sqlite" else None,
        "tls": tls,
        "tls_verified": tls and tls_requested(engine),
    }


# ---- 개발 PC 전용 ----------------------------------------------------------
# MySQL DDL(migrations/*.sql)은 SQLite에서 돌지 않는다(03 2-5). 개발 PC에서만 쓰는 명령이며
# 이미지 진입점·파이프라인은 부르지 않는다. DROP 없이 없으면 만든다.

_SQLITE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS post (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
         title VARCHAR(200) NOT NULL,
         body TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS schema_migrations (
         version VARCHAR(16) NOT NULL PRIMARY KEY,
         name VARCHAR(100) NOT NULL,
         checksum CHAR(64) NOT NULL,
         applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
         release_id VARCHAR(64) NULL)""",
)


@click.command("dev-schema")
def dev_schema_command() -> None:
    """개발 PC SQLite에 v1 스키마를 만든다(SQLite 전용)."""
    from flaskr.migrate import migration_files

    engine = get_engine()
    if engine.url.get_backend_name() != "sqlite":
        raise click.ClickException("dev-schema는 SQLite 전용입니다. MySQL은 python -m flaskr.migrate up")
    if engine.url.database:
        from pathlib import Path

        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as conn:
        for ddl in _SQLITE_SCHEMA:
            conn.execute(text(ddl))
        for item in migration_files():
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO schema_migrations (version, name, checksum, release_id)"
                    " VALUES (:version, :name, :checksum, 'dev')"
                ),
                {"version": item.version, "name": item.name, "checksum": item.checksum},
            )
    click.echo("개발 SQLite 스키마 준비 완료")
