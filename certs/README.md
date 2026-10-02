# certs/

클라우드 RDS 연결의 CA 검증용 번들 `global-bundle.pem`을 둡니다(`DATABASE_URL`의 `ssl_ca=/app/certs/global-bundle.pem`).
was 이미지가 `COPY certs/ certs/`로 이 폴더를 그대로 넣습니다. 온프렘은 쓰지 않습니다.

- N24 결정: 저장소에 커밋합니다. 플랫폼 buildspec은 코드 소유 상수라 빌드 때 받는 단계가 없습니다.
  공개 CA 인증서 묶음이라 비밀값이 아닙니다. `.gitignore`의 `*.pem` 규칙에서 이 파일만 예외입니다.
- 출처: https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
- 받은 날: 2026-10-02
- SHA256: `fe45bbebf92ad3e27a583bbb2ddd1553c521ed4d49af5514dc0a40372ea5395c`
- 내용: 인증서 111개(ap-northeast-2 포함), 가장 이른 만료 2061년, 줄바꿈 LF

갱신할 때는 같은 주소에서 다시 받아 SHA256을 이 파일에 고칩니다.

```bash
curl -fsS --proto =https -o certs/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
sha256sum certs/global-bundle.pem
```
