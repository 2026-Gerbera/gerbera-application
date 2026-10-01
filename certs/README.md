# certs/

클라우드 RDS 연결의 CA 검증용 번들 `global-bundle.pem`을 둡니다(`DATABASE_URL`의 `ssl_ca=/app/certs/global-bundle.pem`).

- 받기: https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem (SHA256을 함께 기록)
- 저장소 `.gitignore`의 `*.pem`에 걸려 커밋되지 않습니다. 커밋할지, 빌드 때 받을지는 결정 대기(N24, docs/harness/06 I-33).
- 온프렘은 쓰지 않습니다.
