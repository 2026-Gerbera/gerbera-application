"""환경변수 읽기 (C-01 앱 env 계약).

값은 전부 환경변수로 받는다. 이미지 안에는 환경별 값이 없다.
"""

from __future__ import annotations

import os


class MissingEnvError(RuntimeError):
    pass


def require_env(name: str) -> str:
    """필수 키. 없으면 기동을 실패시켜 배포 실패로 드러나게 한다."""
    value = os.environ.get(name, "")
    if not value:
        raise MissingEnvError(f"필수 환경변수 {name}가 없습니다")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int = 0) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def load() -> dict:
    """create_app이 쓰는 설정. v1에는 서명 키 설정이 없다(장부 32)."""
    return {
        "DATABASE_URL": require_env("DATABASE_URL"),
        "APP_BASE_URL": require_env("APP_BASE_URL"),
        "RELEASE_ID": os.environ.get("RELEASE_ID", "unknown"),
        "SOURCE_SHA": os.environ.get("SOURCE_SHA", "unknown"),
        "APP_ENV": os.environ.get("APP_ENV", "unknown"),
        "PROXY_FIX_X_FOR": env_int("PROXY_FIX_X_FOR", 0),
        "PROXY_FIX_X_PROTO": env_int("PROXY_FIX_X_PROTO", 0),
    }
