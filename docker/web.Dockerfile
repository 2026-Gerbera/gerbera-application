# 기준 Dockerfile(web). 빌드 컨텍스트 = 샘플 앱 루트.
# nginx 비root 이미지(8080), 멀티 아키텍처 index digest 고정(amd64+arm64)
FROM nginxinc/nginx-unprivileged:1.28-alpine@sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8

# 공식 템플릿 방식: 기동 때 WAS_UPSTREAM을 채워 /etc/nginx/conf.d/default.conf를 만든다
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY flaskr/static/ /usr/share/nginx/html/static/

EXPOSE 8080
