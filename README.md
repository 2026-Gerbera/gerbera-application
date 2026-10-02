# gerbera-application — 배포 대상 샘플 앱 (flaskr)

SoftBank Hackathon 2026 Term1 팀 Gerbera의 배포 파이프라인([gerbera-deploy-ai](https://github.com/2026-Gerbera/gerbera-deploy-ai))이 온프렘과 클라우드에 배포하는 샘플 앱입니다. Flask 공식 튜토리얼 flaskr(BSD-3-Clause)을 바탕으로 만들었습니다. 담당은 장민영(O3)입니다.

## 브랜치

| 브랜치 | 쓰는 쪽 | 뜻 |
|---|---|---|
| `prod` (기본 브랜치) | 개발자 | 기준 코드. 파이프라인이 이 브랜치를 보고 배포합니다 |
| `ai-prod` | 파이프라인 | 배포 후보 = `prod` merge + 승인된 AI 패치 커밋(이력 보존). 사람은 커밋하지 않습니다 |
| `main` | 파이프라인 | 실제로 배포된 코드의 기록. 배포를 일으키지 않습니다 |

| 태그 | 뜻 |
|---|---|
| `deployed/onprem`, `deployed/cloud` | 환경별로 배포·검증에 성공한 커밋(롤백 기준). 파이프라인이 옮깁니다 |
| `v1`, `v2` | 데모 기준 상태. 움직이지 않으므로 같은 데모를 여러 번 반복할 수 있습니다 |

- `prod/...` 같은 이름의 브랜치는 만들지 않습니다(git은 `prod` 브랜치와 `prod/onprem` 브랜치를 함께 둘 수 없습니다).
- v1(태그 `v1`): 로그인이 없는 익명 게시판입니다. 서명 키와 세션을 쓰지 않습니다.
- v2(다음 작업): 추가할 기능은 팀에서 협의 중입니다. 아래 "v2 기능 추가 절차"를 따릅니다.
- `dev.env`와 코드에 있는 개발값(`sqlite:///...`, `localhost` 등)은 데모용으로 일부러 둔 값입니다. 고치지 않습니다. 배포할 때 파이프라인이 대상 환경 값으로 바꿉니다.

## 구성

| 경로 | 내용 |
|---|---|
| `flaskr/` | `create_app`, `config.py`(`require_env`·`env_bool`), `db.py`(SQLAlchemy, `text()`), `blog.py`(목록·글쓰기), `health.py`, `migrate.py`(러너) |
| `migrations/NNNN_<이름>.sql` | 추가형 DDL만 둡니다. 버전 ID는 앞의 4자리(`0001`)입니다 |
| `docker/was.Dockerfile`, `docker/web.Dockerfile`, `nginx/default.conf.template` | 기준 Dockerfile. 베이스 이미지는 멀티 아키텍처 index digest로 고정했고 비root로 실행합니다. web은 `WAS_UPSTREAM` 템플릿을 쓰며 포트는 8080입니다 |
| `deploy.yaml` | 파이프라인이 읽는 배포 설정. 저장소 루트에 있어야 합니다 |
| `dev.env` / `env.example` | 개발 PC 환경 파일(일부러 둔 개발값) / was 환경 키 이름 목록(값 없음) |
| `certs/` | RDS CA 번들을 둘 자리(`*.pem`은 커밋하지 않음) |

## 환경 키

| 키 | 필수 | 설명 |
|---|---|---|
| `DATABASE_URL` | ✅ (없으면 기동 실패) | `mysql+pymysql://<user>:<pw>@<host>:3306/flaskr?charset=utf8mb4`. 클라우드는 뒤에 `&ssl_ca=/app/certs/global-bundle.pem`을 붙입니다 |
| `APP_BASE_URL` | ✅ (없으면 기동 실패) | 공개 주소 |
| `APP_ENV`, `RELEASE_ID`, `SOURCE_SHA` | – (기본값 `unknown`) | `/version`에 그대로 나갑니다 |
| `PROXY_FIX_X_FOR`, `PROXY_FIX_X_PROTO` | – (기본값 0) | 온프렘 0/0, 클라우드 2/1 |
| `WAS_UPSTREAM` | web 컨테이너에서 ✅ | 예: `172.30.0.10:8000` |

## 엔드포인트

- `GET /health/live`: DB는 보지 않고 프로세스 상태만 확인합니다.
- `GET /health/ready`: 200 또는 503. 응답은 `{"status", "db", "schema": {"current", "expected"}, "tls": bool, "tls_verified": bool}`입니다. 스키마 버전이 이미지 안 `migrations/`보다 뒤처져 있으면 503입니다. `DATABASE_URL`에 `ssl_ca`가 있는데(클라우드) CA 검증 TLS 연결이 아니어도 503입니다.
- `GET /version`: `release_id`, `source_sha`, `app_env`, `schema_expected`, `base_url`, `db`(`dialect`, 가린 `host`, `tls`, `tls_verified`)를 돌려줍니다.
- web 컨테이너의 `GET /nginx-health`는 200을 돌려주고, `/static/`은 nginx가 직접 제공합니다.

## v2 기능 추가 절차

어떤 기능이 들어오든 아래를 지키면 파이프라인의 기대(was만 재빌드, 추가형 마이그레이션, 교차 검증)와 맞습니다.

1. **기능 모듈**: `flaskr/<기능>.py`에 Blueprint `bp`를 두고, `flaskr/__init__.py`의 `_feature_modules()`에 한 줄 추가합니다.
2. **화면**: `flaskr/templates/<기능>/`에 템플릿을 둡니다. 메뉴는 `base.html`의 `{% block nav %}`에 넣습니다.
3. **바꾸지 않는 것**: `nginx/`, `docker/web.Dockerfile`, `flaskr/static/`. 이것들이 바뀌면 web 이미지도 다시 빌드됩니다(`deploy.yaml`의 web `paths`).
4. **스키마**: `migrations/0002_<이름>.sql`처럼 다음 번호로 **추가형만** 씁니다(`CREATE TABLE`, `CREATE INDEX`, `ALTER TABLE ... ADD`). DB는 롤백하지 않으므로, 새 컬럼은 NULL 허용이나 기본값을 두어 **v1 코드가 새 스키마에서도 동작**해야 합니다. MySQL은 `ADD COLUMN IF NOT EXISTS`를 지원하지 않습니다(러너가 문장 단위로 확인해 건너뜀).
5. **새 환경 키**: `config.py`에서 읽고 `env.example`에 이름만 추가합니다. 비밀값은 파이프라인이 주입합니다.
6. **AI 패치 데모 패턴**: 데모는 AI가 환경 의존 코드(코드 안에 박힌 `localhost` 주소, 쿠키 Secure·ProxyFix 설정, 서명 키 같은 개발값)를 환경변수로 고치는 diff를 보여 줍니다. v2 코드에 어떤 패턴을 일부러 둘지는 기능이 정해지면 팀과 맞춥니다.
7. **검증**: 기능의 스모크 시나리오를 팀 저장소 `verify/smoke`에 추가합니다. 로컬 MySQL 8.4에서 `precheck → up → verify`와 v1 × 새 스키마 호환을 확인합니다.

## 마이그레이션 러너

```sh
docker run --rm --entrypoint python -e DATABASE_URL=... <was 이미지> -m flaskr.migrate {precheck|up|verify} --json
```

- stdout에 `MIGRATE_RESULT {"phase","ok","current","expected","applied","signature","fingerprint"}` 한 줄을 씁니다. 진단 메시지는 stderr로 나갑니다.
- exit code: 0 = 성공, 1 = 실패(결과 줄은 그래도 남김), 2 = 사용법 오류.
- `precheck`는 `@@require_secure_transport`도 확인합니다. 서버가 TLS를 요구하는데 TLS 연결이 아니면 실패합니다.
- DB 주소는 `DATABASE_URL_MIGRATOR`가 있으면 그것을, 없으면 `DATABASE_URL`을 씁니다. 온프렘은 권한을 나눠 마이그레이션 계정 주소를 `DATABASE_URL_MIGRATOR`로 넘깁니다. 앱(웹 서버)은 이 키를 읽지 않습니다.
- 선택 환경변수 `MIGRATE_MODE=bootstrap`을 주면, `precheck`가 DB가 비어 있는지 확인합니다(V18). 표가 남아 있으면 실패합니다. 파이프라인이 이 값을 넘길지는 O1·C2와 정해야 합니다.
- `up`은 잠금(`GET_LOCK`)을 잡고, checksum 드리프트를 확인하고, 문장 단위로 이미 적용됐는지 확인해 건너뜁니다. 다시 실행해도 안전합니다. DROP·RENAME·MODIFY 같은 파괴형 문장이 있으면 `precheck`부터 실패합니다.

## 개발 PC

```sh
pip install -r requirements-dev.txt
flask --app flaskr --env-file dev.env dev-schema   # SQLite 전용. DROP 없음
flask --app flaskr --env-file dev.env run
```

## 라이선스

flaskr 원본의 고지는 [LICENSE.txt](LICENSE.txt)와 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다(pallets/flask `d73fa1c`, BSD-3-Clause).
