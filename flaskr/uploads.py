"""v3 이미지 업로드·조회.

저장 위치는 모듈 상수 IMG_DIR 하나로 정한다.
- 로컬 디렉토리(예: "img"): 앱 루트(flaskr의 상위, 컨테이너에서는 /app) 기준. 없으면 만든다.
- s3://<bucket>/<prefix>: boto3로 저장·목록·조회한다. 리전은 기본 설정이 없으면 ap-northeast-2,
  자격증명은 기본 체인(클라우드는 태스크 역할)이다.

파일 이름은 기존 개수 + 1인 순번 <n>.<ext>다. 데모용이라 동시 업로드·권한(IDOR)은 고려하지 않는다.
"""

from __future__ import annotations

import os
import re
import socket
from functools import cache
from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

IMG_DIR = os.environ['IMG_DIR']

bp = Blueprint("uploads", __name__)

# 1MB. nginx client_max_body_size 1m(1MiB) 안에 multipart 머리 여유를 남긴다
MAX_BYTES = 1_000_000
CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif"}
_EXTENSIONS = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif"}  # jpeg는 jpg로 저장
_NAME = re.compile(r"([1-9][0-9]*)\.(png|jpg|gif)")
_DEFAULT_REGION = "ap-northeast-2"


# ---- 저장 헬퍼 ----------------------------------------------------------------


def _s3_location(img_dir: str) -> tuple[str, str] | None:
    """s3://bucket/prefix면 (bucket, prefix). 로컬 경로면 None."""
    if not img_dir.startswith("s3://"):
        return None
    bucket, _, prefix = img_dir.removeprefix("s3://").partition("/")
    return bucket, prefix.strip("/")


def _s3_key(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


@cache
def _s3_client():
    import boto3  # s3 모드에서만 불러온다

    session = boto3.session.Session()
    return session.client("s3", region_name=session.region_name or _DEFAULT_REGION)


def _local_dir(img_dir: str) -> Path:
    """앱 루트 기준 디렉토리(절대 경로면 그대로). 없으면 만든다."""
    directory = Path(current_app.root_path).parent / img_dir
    os.makedirs(directory, exist_ok=True)
    return directory


def list_images() -> list[str]:
    """저장된 이미지 이름. 순번 오름차순."""
    location = _s3_location(IMG_DIR)
    if location is not None:
        bucket, prefix = location
        start = _s3_key(prefix, "")
        kwargs = {"Bucket": bucket, "Prefix": start}
        names = []
        while True:
            page = _s3_client().list_objects_v2(**kwargs)
            names += [item["Key"][len(start) :] for item in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = page["NextContinuationToken"]
    else:
        names = [path.name for path in _local_dir(IMG_DIR).iterdir() if path.is_file()]
    return sorted((n for n in names if _NAME.fullmatch(n)), key=lambda n: int(n.split(".")[0]))


def save_image(name: str, data: bytes) -> None:
    location = _s3_location(IMG_DIR)
    if location is not None:
        bucket, prefix = location
        _s3_client().put_object(
            Bucket=bucket, Key=_s3_key(prefix, name), Body=data, ContentType=_content_type(name)
        )
        return
    directory = _local_dir(IMG_DIR)
    (directory / name).write_bytes(data)


def read_image(name: str) -> bytes | None:
    """이미지 바이트. 없으면 None."""
    location = _s3_location(IMG_DIR)
    if location is not None:
        bucket, prefix = location
        client = _s3_client()
        try:
            obj = client.get_object(Bucket=bucket, Key=_s3_key(prefix, name))
        except client.exceptions.NoSuchKey:
            return None
        return obj["Body"].read()
    path = _local_dir(IMG_DIR) / name
    return path.read_bytes() if path.is_file() else None


def next_name(names: list[str], ext: str) -> str:
    """기존 개수 + 1. 그 순번이 이미 있으면(중간 파일이 지워진 경우) 다음 빈 순번."""
    used = {name.split(".")[0] for name in names}
    n = len(names) + 1
    while str(n) in used:
        n += 1
    return f"{n}.{ext}"


def _content_type(name: str) -> str:
    return CONTENT_TYPES[name.rpartition(".")[2]]


# ---- 라우트 -------------------------------------------------------------------


def _index_page(error: str | None = None, status: int = 200):
    images = list(reversed(list_images()))  # 최근 것부터
    host = socket.gethostname()  # 응답한 서버(태스크·컨테이너) 구분용
    return render_template("uploads/index.html", images=images, host=host, error=error), status


@bp.get("/uploads")
def index():
    return _index_page()


@bp.post("/upload")
def upload():
    file = request.files.get("image")
    if file is None or not file.filename:
        return _index_page("이미지 파일을 고르세요.", 400)
    ext = _EXTENSIONS.get(Path(file.filename).suffix.lower().removeprefix("."))
    if ext is None:
        return _index_page("png, jpg, gif만 올릴 수 있습니다.", 400)
    data = file.read(MAX_BYTES + 1)
    if not data:
        return _index_page("빈 파일입니다.", 400)
    if len(data) > MAX_BYTES:
        return _index_page("1MB 이하만 올릴 수 있습니다.", 413)
    save_image(next_name(list_images(), ext), data)
    return redirect(url_for("uploads.index"))


@bp.get("/uploads/<name>")
def image(name: str):
    # 순번 이름(<n>.<ext>)만 받는다. 경로 탈출(.., /, \)은 여기서 404가 된다
    if not _NAME.fullmatch(name):
        abort(404)
    data = read_image(name)
    if data is None:
        abort(404)
    response = current_app.response_class(data, mimetype=_content_type(name))
    response.headers["X-Content-Type-Options"] = "nosniff"
    # 새로고침마다 다시 받아 어느 서버가 응답해도 보이는지 확인한다
    response.headers["Cache-Control"] = "no-store"
    return response
