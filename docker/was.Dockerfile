# 기준 Dockerfile(was). 빌드 컨텍스트 = 샘플 앱 루트.
# python:3.13-slim, 멀티 아키텍처 index digest 고정(amd64+arm64)
FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY flaskr/ flaskr/
COPY migrations/ migrations/
COPY certs/ certs/

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
# v3 업로드 로컬 저장소(/app/img). 실행 사용자 10001이 쓴다. VOLUME은 선언하지 않는다
RUN mkdir /app/img && chown app:app /app/img
USER 10001

EXPOSE 8000
# 마이그레이션은 같은 이미지로: --entrypoint python ... -m flaskr.migrate {precheck|up|verify} --json
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "flaskr:create_app()"]
