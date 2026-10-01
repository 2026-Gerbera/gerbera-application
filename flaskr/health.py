"""헬스·버전 엔드포인트 (C-01).

- /health/live : 프로세스만 확인(DB 안 봄)
- /health/ready: SELECT 1 + schema_migrations 최대 버전 >= 이미지 안 migrations/의 기대 버전
                 + (ssl_ca 지정 시) CA 검증 TLS 연결. 하나라도 아니면 503
                 응답: {"status", "db", "schema": {"current", "expected"}, "tls": bool, "tls_verified": bool}
- /version     : release_id 등. DB 호스트는 가린다. digest 근거로 쓰지 않는다(V20)
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from flaskr.db import connection_info, get_engine, tls_requested
from flaskr.migrate import expected_version

bp = Blueprint("health", __name__)


def _current_version(conn) -> str | None:
    try:
        return conn.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar()
    except Exception:
        return None


@bp.get("/health/live")
def live():
    return jsonify(status="ok")


@bp.get("/health/ready")
def ready():
    engine = get_engine()
    expected = expected_version()
    body: dict = {
        "status": "fail",
        "db": "fail",
        "schema": {"current": None, "expected": expected},
        "tls": False,
        "tls_verified": False,
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            body["db"] = "ok"
            current = _current_version(conn)
            body["schema"]["current"] = current
            info = connection_info(engine, conn)
            body["tls"], body["tls_verified"] = info["tls"], info["tls_verified"]
    except Exception as error:
        current_app.logger.warning("ready: DB 확인 실패: %s", type(error).__name__)
        return jsonify(body), 503
    schema_ok = current is not None and expected is not None and current >= expected
    # ssl_ca를 지정했으면(클라우드) CA 검증 TLS 연결이어야 준비 완료
    tls_ok = not tls_requested(engine) or body["tls_verified"]
    if schema_ok and tls_ok:
        body["status"] = "ok"
        return jsonify(body), 200
    return jsonify(body), 503


@bp.get("/version")
def version():
    engine = get_engine()
    cfg = current_app.config
    try:
        with engine.connect() as conn:
            db = connection_info(engine, conn)
    except Exception:
        db = connection_info(engine, None)
    return jsonify(
        release_id=cfg["RELEASE_ID"],
        source_sha=cfg["SOURCE_SHA"],
        app_env=cfg["APP_ENV"],
        schema_expected=expected_version(),
        base_url=cfg["APP_BASE_URL"],
        db=db,
    )
